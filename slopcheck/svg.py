from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from slopcheck.scanner import ScanResult

VERDICT_THEMES = {
    "CLEAN": ("#10b981", "#052e22", "#34d399"),
    "SUSPICIOUS": ("#f59e0b", "#332206", "#fbbf24"),
    "VIBE-CODED": ("#d946ef", "#340c3c", "#e879f9"),
    "PURE SLOP": ("#ef4444", "#360c0e", "#f87171"),
}

RULE_HEX = {
    "silent-except": "#f87171",
    "silent-catch": "#f87171",
    "ai-cliche": "#fbbf24",
    "emoji-slop": "#fb923c",
    "deep-nesting": "#ef4444",
    "debug-print": "#f43f5e",
    "wildcard-import": "#e879f9",
    "bloat-docstring": "#c084fc",
    "useless-wrapper": "#38bdf8",
    "captain-comment": "#22d3ee",
    "redundant-boolean": "#facc15",
    "duplicate-helper": "#f472b6",
    "test-theatre": "#fb7185",
    "security-slop": "#ef4444",
}


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3):]


def _build_rule_bars(result: ScanResult, x_start: int, y_start: int, accent: str) -> list[str]:
    sans = "system-ui, -apple-system, Segoe UI, sans-serif"
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    if not result.rule_counts:
        return [
            f'<rect x="{x_start}" y="{y_start}" width="486" height="96" rx="10" fill="#0d1117" stroke="#1f2937"/>',
            f'<text x="{x_start + 243}" y="{y_start + 42}" text-anchor="middle" fill="{accent}" font-size="14" font-weight="700" font-family="{sans}">ZERO SLOP PATTERNS DETECTED</text>',
            f'<text x="{x_start + 243}" y="{y_start + 64}" text-anchor="middle" fill="#9ca3af" font-size="12" font-family="{sans}">AST &amp; polyglot heuristics found zero bloat, clichés, or silent catches.</text>',
        ]

    lines: list[str] = []
    top_rules = list(result.rule_counts.items())[:5]
    max_count = max(count for _, count in top_rules) or 1
    bar_max_w = 260

    for idx, (rule, count) in enumerate(top_rules):
        y = y_start + idx * 26
        fill_w = max(8, int(round((count / max_count) * bar_max_w)))
        color = RULE_HEX.get(rule, accent)
        lines.append(
            f'<text x="{x_start}" y="{y + 13}" fill="#e4e4e7" font-size="12" font-family="{mono}">{escape(rule)}</text>'
        )
        lines.append(
            f'<rect x="{x_start + 150}" y="{y + 3}" width="{bar_max_w}" height="10" rx="5" fill="#18181b"/>'
        )
        lines.append(
            f'<rect x="{x_start + 150}" y="{y + 3}" width="{fill_w}" height="10" rx="5" fill="{color}"/>'
        )
        lines.append(
            f'<text x="{x_start + 482}" y="{y + 13}" text-anchor="end" fill="#a1a1aa" font-size="12" font-weight="600" font-family="{mono}">{count}</text>'
        )
    return lines


def _build_hotspot_rows(result: ScanResult, y_start: int) -> list[str]:
    if not result.file_issues:
        return []

    ranked = sorted(
        result.file_issues.items(),
        key=lambda item: sum(i.weight for i in item[1]),
        reverse=True,
    )[:3]
    resolved_target = result.target.resolve()
    base = resolved_target if resolved_target.is_dir() else resolved_target.parent
    sans = "system-ui, -apple-system, Segoe UI, sans-serif"
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    parts = [
        f'<text x="36" y="{y_start}" fill="#71717a" font-size="11" font-weight="700" letter-spacing="1.2" font-family="{sans}">TOP HOTSPOTS</text>'
    ]
    for idx, (fpath, issues) in enumerate(ranked):
        y = y_start + 14 + idx * 24
        try:
            rel = str(fpath.resolve().relative_to(base))
        except ValueError:
            rel = fpath.name
        top_rule = Counter(i.rule for i in issues).most_common(1)[0][0]
        weight = sum(i.weight for i in issues)
        parts.append(
            f'<rect x="36" y="{y}" width="746" height="20" rx="4" fill="#14141b"/>'
        )
        parts.append(
            f'<text x="46" y="{y + 14}" fill="#e4e4e7" font-size="11.5" font-family="{mono}">{escape(_truncate(rel.replace(chr(92), "/"), 46))}</text>'
        )
        parts.append(
            f'<text x="495" y="{y + 14}" fill="#a1a1aa" font-size="11" font-family="{mono}">{escape(top_rule)}</text>'
        )
        parts.append(
            f'<text x="772" y="{y + 14}" text-anchor="end" fill="#fbbf24" font-size="11" font-weight="600" font-family="{mono}">{len(issues)} issues (+{weight})</text>'
        )
    return parts


def render_scorecard_svg(result: ScanResult, title: str | None = None) -> str:
    """Render a standalone dark-neon SVG scorecard summarizing scan results."""
    accent, pill_bg, glow = VERDICT_THEMES.get(result.verdict, ("#10b981", "#052e22", "#34d399"))
    resolved = result.target.resolve()
    display_title = title or resolved.name or str(result.target)
    mode_label = f"DIFF: {result.diff_base}" if result.diff_base else ("GIT DIFF" if result.diff_mode else "FULL REPO")

    hotspot_rows = _build_hotspot_rows(result, 310)
    hotspot_count = min(3, len(result.file_issues))
    height = 360 if not hotspot_rows else 356 + hotspot_count * 24 + 28

    radius = 64
    circumference = 2 * 3.14159265 * radius
    dash_offset = circumference * (1.0 - (result.score / 100.0))

    metric_items = [
        ("FILES", f"{result.files_scanned:,}"),
        ("LINES", f"{result.total_lines:,}"),
        ("ISSUES", f"{len(result.issues):,}"),
        ("TIME", f"{result.elapsed:.2f}s"),
    ]
    sans = "system-ui, -apple-system, Segoe UI, sans-serif"
    metric_svg: list[str] = []
    for idx, (label, value) in enumerate(metric_items):
        mx = 296 + idx * 124
        metric_svg.append(f'<rect x="{mx}" y="94" width="114" height="54" rx="10" fill="#14141b" stroke="#27272a"/>')
        metric_svg.append(f'<text x="{mx + 14}" y="114" fill="#71717a" font-size="10" font-weight="700" letter-spacing="1" font-family="{sans}">{label}</text>')
        metric_svg.append(f'<text x="{mx + 14}" y="137" fill="#f4f4f5" font-size="17" font-weight="700" font-family="{sans}">{escape(value)}</text>')

    rule_svg = _build_rule_bars(result, 296, 174, accent)
    footer_y = height - 20
    ring_bg_stroke = accent if result.score == 0 else "#1f2937"
    ring_bg_opacity = ' stroke-opacity="0.28"' if result.score == 0 else ""

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="{height}" viewBox="0 0 820 {height}">',
        '<defs>',
        '<linearGradient id="topGlow" x1="0%" y1="0%" x2="100%" y2="0%">',
        f'<stop offset="0%" stop-color="{accent}"/>',
        f'<stop offset="100%" stop-color="{glow}"/>',
        '</linearGradient>',
        '</defs>',
        f'<rect width="820" height="{height}" rx="16" fill="#09090b"/>',
        f'<rect x="12" y="12" width="796" height="{height - 24}" rx="14" fill="#111116" stroke="#27272a"/>',
        '<rect x="12" y="12" width="796" height="4" rx="2" fill="url(#topGlow)"/>',
        '<text x="36" y="52" fill="#fafafa" font-size="18" font-weight="800" font-family="system-ui, -apple-system, Segoe UI, sans-serif" letter-spacing="0.5">SLOPCHECK</text>',
        f'<text x="156" y="52" fill="#a1a1aa" font-size="15" font-weight="600" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">/ {escape(_truncate(display_title, 34))}</text>',
        f'<rect x="530" y="34" width="110" height="24" rx="6" fill="#18181b" stroke="#27272a"/>',
        f'<text x="585" y="50" text-anchor="middle" fill="#a1a1aa" font-size="10.5" font-weight="700" font-family="system-ui, sans-serif">{escape(_truncate(mode_label, 16))}</text>',
        f'<rect x="650" y="34" width="134" height="24" rx="6" fill="{pill_bg}" stroke="{accent}"/>',
        f'<text x="717" y="50" text-anchor="middle" fill="{glow}" font-size="11" font-weight="800" font-family="system-ui, sans-serif" letter-spacing="0.8">{escape(result.verdict)}</text>',
        '<line x1="36" y1="74" x2="784" y2="74" stroke="#1f1f27"/>',
        f'<rect x="36" y="94" width="236" height="196" rx="14" fill="#0d1117" stroke="#1f2937"/>',
        f'<circle cx="154" cy="184" r="64" fill="none" stroke="{ring_bg_stroke}"{ring_bg_opacity} stroke-width="12"/>',
        f'<circle cx="154" cy="184" r="64" fill="none" stroke="{accent}" stroke-width="12" stroke-linecap="round" stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{dash_offset:.2f}" transform="rotate(-90 154 184)"/>',
        f'<text x="154" y="191" text-anchor="middle" fill="#fafafa" font-size="34" font-weight="800" font-family="system-ui, sans-serif">{result.score}%</text>',
        '<text x="154" y="213" text-anchor="middle" fill="#71717a" font-size="10.5" font-weight="700" letter-spacing="1.2" font-family="system-ui, sans-serif">SLOP SCORE</text>',
        '<text x="154" y="272" text-anchor="middle" fill="#9ca3af" font-size="11" font-family="system-ui, sans-serif">0-10% Clean · 11-35% Sus · 36+ Slop</text>',
        *metric_svg,
        *rule_svg,
        *hotspot_rows,
        f'<text x="36" y="{footer_y}" fill="#52525b" font-size="11" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">$ uvx sloplinter .</text>',
        f'<text x="784" y="{footer_y}" text-anchor="end" fill="#52525b" font-size="11" font-family="system-ui, sans-serif">github.com/an1zy/slopcheck</text>',
        '</svg>',
    ]
    return "\n".join(svg_parts) + "\n"
