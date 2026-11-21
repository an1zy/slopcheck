import argparse
import ast
from pathlib import Path
import sys
import time

from rich.console import Console

from slopcheck.core import Issue, calculate_score, iter_source_files
from slopcheck.polyglot import check_polyglot
from slopcheck.rules import ALL_RULES

RULE_COLORS = {
    "silent-except": "red",
    "silent-catch": "red",
    "bloat-docstring": "magenta",
    "ai-cliche": "yellow",
    "captain-comment": "cyan",
    "emoji-slop": "yellow",
    "debug-print": "red",
    "redundant-boolean": "yellow",
    "deep-nesting": "red",
    "wildcard-import": "magenta",
    "useless-wrapper": "cyan",
}


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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="slopcheck",
        description="Linter for code slop, bloated docstrings, and cargo-cult comments.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        type=Path,
        help="Directory or file to scan (default: .)",
    )
    parser.add_argument(
        "--max-score",
        type=int,
        default=100,
        help="Maximum acceptable slop score (default: 100)",
    )
    parser.add_argument(
        "--badge",
        action="store_true",
        help="Print a shields.io markdown badge instead of the full report",
    )
    args = parser.parse_args()

    start_time = time.perf_counter()
    files = list(iter_source_files(args.path))
    total_lines = 0
    all_issues: list[Issue] = []
    file_issues: dict[Path, list[Issue]] = {}

    for file_path in files:
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        total_lines += len(source.splitlines())
        current_issues: list[Issue] = []

        if file_path.suffix == ".py":
            try:
                tree = ast.parse(source, filename=str(file_path))
            except SyntaxError:
                tree = None

            for rule in ALL_RULES:
                current_issues.extend(rule(file_path, source, tree))
        else:
            current_issues.extend(check_polyglot(file_path, source))

        if current_issues:
            current_issues.sort(key=lambda i: (i.line, i.rule))
            file_issues[file_path] = current_issues
            all_issues.extend(current_issues)

    elapsed = time.perf_counter() - start_time
    score = calculate_score(all_issues, total_lines)

    if args.badge:
        badge_color = get_badge_color(score)
        print(f"![Slop Score](https://img.shields.io/badge/slop_score-{score}%25-{badge_color})")
        if score > args.max_score:
            sys.exit(1)
        return

    verdict, color = get_verdict(score)
    console = Console(highlight=False)

    if file_issues:
        console.print()
        for file_path, issues in file_issues.items():
            try:
                display_path = file_path.relative_to(Path.cwd())
            except ValueError:
                display_path = file_path
            console.print(f"[bold white]{display_path}[/]")
            for issue in issues:
                rule_color = RULE_COLORS.get(issue.rule, "white")
                console.print(
                    f"  [dim]{issue.line:>4}[/]  [{rule_color}]{issue.rule:<18}[/]  [dim]+{issue.weight:<2}[/]  {issue.message}"
                )
        console.print()

    bar_width = 30
    filled = int(round(bar_width * (score / 100)))
    empty = bar_width - filled
    bar = f"[{color}]{'█' * filled}[/][bright_black]{'░' * empty}[/]"

    console.print(f"  [bold white]Slop Score[/]  [{color} bold]{score:>3}%[/]  {bar}  [{color} bold]{verdict}[/]")
    console.print(f"  [dim]Scanned {len(files)} files ({total_lines:,} lines) in {elapsed:.3f}s[/dim]")
    console.print()

    if score > args.max_score:
        console.print(
            f"[bold red]FAILED:[/] Slop score {score} exceeds maximum allowed threshold of {args.max_score}\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
