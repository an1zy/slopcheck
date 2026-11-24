import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import time
import warnings

from slopcheck.core import Issue, calculate_score, iter_source_files
from slopcheck.diff import collect_diff_lines
from slopcheck.polyglot import check_polyglot
from slopcheck.rules import scan_python


def get_verdict(score: int) -> tuple[str, str]:
    if score <= 10:
        return "CLEAN", "green"
    if score <= 35:
        return "SUSPICIOUS", "yellow"
    if score <= 65:
        return "VIBE-CODED", "magenta"
    return "PURE SLOP", "red"


def get_badge_color(score: int) -> str:
    if score <= 10:
        return "brightgreen"
    if score <= 35:
        return "yellow"
    if score <= 65:
        return "orange"
    return "red"


def get_badge_url(score: int) -> str:
    color = get_badge_color(score)
    return f"https://img.shields.io/badge/slop_score-{score}%25-{color}"


@dataclass(frozen=True)
class ScanResult:
    target: Path
    files_scanned: int
    total_lines: int
    score: int
    verdict: str
    verdict_color: str
    elapsed: float
    issues: list[Issue]
    file_issues: dict[Path, list[Issue]]
    rule_counts: dict[str, int]
    diff_mode: bool = False
    diff_base: str | None = None

    def to_dict(self, version: str) -> dict:
        resolved_target = self.target.resolve()
        base = resolved_target if resolved_target.is_dir() else resolved_target.parent
        serialized_issues = []
        for issue in self.issues:
            try:
                rel = str(issue.path.resolve().relative_to(base))
            except ValueError:
                rel = issue.path.name
            serialized_issues.append({
                "file": rel.replace("\\", "/"),
                "line": issue.line,
                "rule": issue.rule,
                "weight": issue.weight,
                "message": issue.message,
            })

        return {
            "version": version,
            "target": str(self.target),
            "diff_mode": self.diff_mode,
            "diff_base": self.diff_base,
            "score": self.score,
            "verdict": self.verdict,
            "badge_url": get_badge_url(self.score),
            "files_scanned": self.files_scanned,
            "total_lines": self.total_lines,
            "issues_count": len(self.issues),
            "elapsed_seconds": round(self.elapsed, 4),
            "rule_counts": self.rule_counts,
            "issues": serialized_issues,
        }


def _scan_file_source(file_path: Path, source: str) -> list[Issue]:
    if file_path.suffix == ".py":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            tree = None
        return scan_python(file_path, source, tree)
    return check_polyglot(file_path, source)


def scan_target(
    target: Path,
    diff_mode: bool = False,
    diff_base: str | None = None,
    staged: bool = False,
    excludes: tuple[str, ...] = (),
) -> ScanResult:
    """Scan a directory, file, or git diff for AI-generated code slop."""
    start_time = time.perf_counter()
    diff_map: dict[Path, set[int]] | None = None

    if diff_mode or diff_base is not None or staged:
        diff_mode = True
        diff_map = collect_diff_lines(target, base=diff_base, staged=staged, excludes=excludes)
        files = sorted(diff_map.keys())
    else:
        files = list(iter_source_files(target, excludes=excludes))

    total_lines = 0
    all_issues: list[Issue] = []
    file_issues: dict[Path, list[Issue]] = {}

    for file_path in files:
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if diff_map is not None:
            changed_lines = diff_map[file_path]
            total_lines += len(changed_lines)
            raw_issues = _scan_file_source(file_path, source)
            current_issues = [i for i in raw_issues if i.line in changed_lines]
        else:
            total_lines += len(source.splitlines())
            current_issues = _scan_file_source(file_path, source)

        if current_issues:
            current_issues.sort(key=lambda i: (i.line, i.rule))
            file_issues[file_path] = current_issues
            all_issues.extend(current_issues)

    elapsed = time.perf_counter() - start_time
    score = calculate_score(all_issues, total_lines)
    verdict, verdict_color = get_verdict(score)
    rule_counts = dict(Counter(issue.rule for issue in all_issues).most_common())

    return ScanResult(
        target=target,
        files_scanned=len(files),
        total_lines=total_lines,
        score=score,
        verdict=verdict,
        verdict_color=verdict_color,
        elapsed=elapsed,
        issues=all_issues,
        file_issues=file_issues,
        rule_counts=rule_counts,
        diff_mode=diff_mode,
        diff_base=diff_base,
    )
