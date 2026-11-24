import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SKIP_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "target",
    "bin",
    "obj",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".tox",
    ".nox",
    ".eggs",
    "coverage",
    "htmlcov",
    "out",
    "vendor",
    "Pods",
    ".gradle",
})

SKIP_FILE_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".d.ts", ".generated.ts", ".generated.py")

MAX_FILE_BYTES = 512 * 1024

SUPPORTED_EXTENSIONS = frozenset({
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".rs",
    ".c",
    ".cpp",
    ".cc",
    ".h",
    ".hpp",
    ".cs",
    ".go",
    ".java",
})


@dataclass(frozen=True)
class Issue:
    path: Path
    line: int
    rule: str
    message: str
    weight: int


def _is_skipped_file(name: str) -> bool:
    lower_name = name.lower()
    return any(lower_name.endswith(sfx) for sfx in SKIP_FILE_SUFFIXES)


def _is_within_size_limit(path: Path) -> bool:
    try:
        return path.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def _matches_exclude(rel_path: str, excludes: tuple[str, ...]) -> bool:
    if not excludes:
        return False
    norm = rel_path.replace("\\", "/")
    parts = norm.split("/")
    for pattern in excludes:
        clean = pattern.strip().strip("/")
        if not clean:
            continue
        if clean in parts or norm.startswith(clean + "/") or norm == clean:
            return True
    return False


def iter_source_files(root: Path, excludes: tuple[str, ...] = ()) -> Iterator[Path]:
    """Yield supported source files under root while pruning ignored paths."""
    if not root.exists():
        return

    if root.is_file():
        if (
            root.suffix in SUPPORTED_EXTENSIONS
            and not _is_skipped_file(root.name)
            and _is_within_size_limit(root)
        ):
            yield root
        return

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not _matches_exclude(d, excludes)
        ]
        for filename in filenames:
            if _is_skipped_file(filename):
                continue
            candidate = Path(dirpath, filename)
            if candidate.suffix not in SUPPORTED_EXTENSIONS:
                continue
            try:
                rel = str(candidate.relative_to(root))
            except ValueError:
                rel = candidate.name
            if _matches_exclude(rel, excludes) or not _is_within_size_limit(candidate):
                continue
            yield candidate


# Backwards compatibility alias
iter_python_files = iter_source_files


def calculate_score(issues: list[Issue], total_lines: int) -> int:
    if total_lines <= 0 or not issues:
        return 0

    total_weight = sum(issue.weight for issue in issues)
    # Increased sensitivity (~3.5x) so ~20 major issues per 3500 lines yield ~25-35%
    score = int(round((total_weight / total_lines) * 350))
    return min(100, max(0, score))
