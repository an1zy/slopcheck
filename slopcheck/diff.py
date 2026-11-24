from pathlib import Path
import re
import subprocess

from slopcheck.core import (
    MAX_FILE_BYTES,
    SUPPORTED_EXTENSIONS,
    _is_skipped_file,
    _is_within_size_limit,
    _matches_exclude,
)

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class GitDiffError(RuntimeError):
    """Raised when git diff inspection cannot run in the target directory."""


def _run_git(cwd: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
        )
    except FileNotFoundError as exc:
        raise GitDiffError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or str(exc)).strip()
        raise GitDiffError(msg or "git command failed") from exc


def find_repo_root(target: Path) -> Path:
    anchor = target if target.is_dir() else target.parent
    if not anchor.exists():
        raise GitDiffError(f"Path does not exist: {target}")
    res = _run_git(anchor, ["rev-parse", "--show-toplevel"])
    return Path(res.stdout.strip()).resolve()


def parse_unified_diff(diff_text: str, repo_root: Path) -> dict[Path, set[int]]:
    """Parse unified=0 git diff output into a map of file paths to added line numbers."""
    changed: dict[Path, set[int]] = {}
    current_path: Path | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            raw = line[4:].strip()
            if raw == "/dev/null":
                current_path = None
                continue
            rel = raw[2:] if raw.startswith("b/") else raw
            current_path = (repo_root / rel).resolve()
            changed.setdefault(current_path, set())
            continue

        if current_path is None:
            continue

        match = HUNK_RE.match(line)
        if not match:
            continue

        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count > 0:
            changed[current_path].update(range(start, start + count))

    return {p: lines for p, lines in changed.items() if lines}


def _is_scannable(path: Path, repo_root: Path, target_abs: Path, excludes: tuple[str, ...]) -> bool:
    if not path.is_file():
        return False
    if path.suffix not in SUPPORTED_EXTENSIONS or _is_skipped_file(path.name):
        return False
    if not _is_within_size_limit(path):
        return False
    if target_abs.is_file() and path != target_abs:
        return False
    if target_abs.is_dir():
        try:
            path.relative_to(target_abs)
        except ValueError:
            return False
    try:
        rel = str(path.relative_to(repo_root))
    except ValueError:
        rel = path.name
    return not _matches_exclude(rel, excludes)


def _has_head_commit(repo_root: Path) -> bool:
    res = _run_git(repo_root, ["rev-parse", "--verify", "HEAD"], check=False)
    return res.returncode == 0


def _collect_untracked(repo_root: Path, rel_spec: str) -> dict[Path, set[int]]:
    res = _run_git(repo_root, ["ls-files", "--others", "--exclude-standard", "--", rel_spec])
    result: dict[Path, set[int]] = {}
    for line in res.stdout.splitlines():
        clean = line.strip()
        if not clean:
            continue
        p = (repo_root / clean).resolve()
        if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
            continue
        line_count = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        if line_count > 0:
            result[p] = set(range(1, line_count + 1))
    return result


def collect_diff_lines(
    target: Path,
    base: str | None = None,
    staged: bool = False,
    excludes: tuple[str, ...] = (),
) -> dict[Path, set[int]]:
    """Collect added or modified line numbers per source file from git diff."""
    repo_root = find_repo_root(target)
    target_abs = target.resolve()
    try:
        rel_spec = str(target_abs.relative_to(repo_root)) or "."
    except ValueError:
        rel_spec = "."

    if base:
        res = _run_git(
            repo_root,
            ["diff", "-U0", "--no-color", "--diff-filter=ACMR", f"{base}...HEAD", "--", rel_spec],
            check=False,
        )
        if res.returncode != 0:
            res = _run_git(
                repo_root,
                ["diff", "-U0", "--no-color", "--diff-filter=ACMR", f"{base}..HEAD", "--", rel_spec],
            )
        raw_map = parse_unified_diff(res.stdout, repo_root)
    elif staged:
        res = _run_git(
            repo_root,
            ["diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR", "--", rel_spec],
        )
        raw_map = parse_unified_diff(res.stdout, repo_root)
    else:
        diff_args = ["diff", "-U0", "--no-color", "--diff-filter=ACMR"]
        if _has_head_commit(repo_root):
            diff_args.append("HEAD")
        diff_args.extend(["--", rel_spec])
        res = _run_git(repo_root, diff_args)
        raw_map = parse_unified_diff(res.stdout, repo_root)
        untracked = _collect_untracked(repo_root, rel_spec)
        for path, lines in untracked.items():
            raw_map.setdefault(path, set()).update(lines)

    return {
        p: lines
        for p, lines in raw_map.items()
        if _is_scannable(p, repo_root, target_abs, excludes)
    }
