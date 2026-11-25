import argparse
import json
from pathlib import Path
import sys

from rich.console import Console

from slopcheck import __version__
from slopcheck.diff import GitDiffError
from slopcheck.scanner import ScanResult, get_badge_url, scan_target
from slopcheck.svg import render_scorecard_svg

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
    "duplicate-helper": "magenta",
    "test-theatre": "red",
    "security-slop": "bold red",
}


def _render_console_report(
    result: ScanResult,
    max_score: int,
    summary_only: bool,
    top_n: int | None,
) -> None:
    console = Console(highlight=False)

    if result.file_issues and not summary_only:
        console.print()
        items = list(result.file_issues.items())
        if top_n is not None and top_n > 0:
            items = sorted(
                items,
                key=lambda pair: sum(i.weight for i in pair[1]),
                reverse=True,
            )[:top_n]
        for file_path, issues in items:
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
    filled = int(round(bar_width * (result.score / 100)))
    empty = bar_width - filled
    color = result.verdict_color
    bar = f"[{color}]{'█' * filled}[/][bright_black]{'░' * empty}[/]"

    mode_tag = " [dim](diff)[/dim]" if result.diff_mode else ""
    console.print(
        f"  [bold white]Slop Score[/]{mode_tag}  [{color} bold]{result.score:>3}%[/]  {bar}  [{color} bold]{result.verdict}[/]"
    )
    console.print(
        f"  [dim]Scanned {result.files_scanned} files ({result.total_lines:,} lines, {len(result.issues)} issues) in {result.elapsed:.3f}s[/dim]"
    )
    console.print()

    if result.score > max_score:
        console.print(
            f"[bold red]FAILED:[/] Slop score {result.score} exceeds maximum allowed threshold of {max_score}\n"
        )


def _build_parser() -> argparse.ArgumentParser:
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
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Scan only added/modified lines in git working tree and untracked files",
    )
    parser.add_argument(
        "--base",
        type=str,
        default=None,
        help="Compare HEAD against git base ref (implies --diff), e.g. origin/main",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Scan only staged git changes (implies --diff)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON output",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        default=None,
        help="Write a dark-neon SVG scorecard to PATH",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Custom repository/project title for SVG scorecard",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Directory or relative path prefix to skip (repeatable)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show only the final Slop Score summary bar",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Show only top N worst files in console output",
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="Disable cross-file duplicate, test-theatre, and security checks",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = scan_target(
            args.path,
            diff_mode=args.diff,
            diff_base=args.base,
            staged=args.staged,
            excludes=tuple(args.exclude),
            semantic=not args.no_semantic,
        )
    except GitDiffError as exc:
        print(f"slopcheck diff error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.svg is not None:
        svg_text = render_scorecard_svg(result, title=args.title)
        args.svg.parent.mkdir(parents=True, exist_ok=True)
        args.svg.write_text(svg_text, encoding="utf-8")

    if args.json:
        print(json.dumps(result.to_dict(__version__), indent=2))
    elif args.badge:
        print(f"![Slop Score]({get_badge_url(result.score)})")
    else:
        _render_console_report(result, args.max_score, args.summary, args.top)

    if result.score > args.max_score:
        sys.exit(1)


if __name__ == "__main__":
    main()
