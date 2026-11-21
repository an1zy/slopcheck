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
    "out",
    "vendor",
})

SKIP_FILE_SUFFIXES = (".min.js", ".bundle.js", ".d.ts")

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


def iter_source_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return

    if root.is_file():
        if root.suffix in SUPPORTED_EXTENSIONS and not _is_skipped_file(root.name):
            yield root
        return

    for dirpath, dirnames, filenames in os.walk(root):
        # Pruning in-place prevents descending into ignored directory trees
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if _is_skipped_file(filename):
                continue
            if Path(filename).suffix in SUPPORTED_EXTENSIONS:
                yield Path(dirpath, filename)


# Backwards compatibility alias
iter_python_files = iter_source_files


def calculate_score(issues: list[Issue], total_lines: int) -> int:
    if total_lines <= 0 or not issues:
        return 0

    total_weight = sum(issue.weight for issue in issues)
    # Increased sensitivity (~3.5x) so ~20 major issues per 3500 lines yield ~25-35%
    score = int(round((total_weight / total_lines) * 350))
    return min(100, max(0, score))
