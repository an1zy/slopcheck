from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from slopcheck.scanner import ScanResult

VERDICT_THEMES = {
    "CLEAN": ("#34d399", "#6ee7b7"),
    "SUSPICIOUS": ("#fbbf24", "#fde68a"),
    "VIBE-CODED": ("#f87171", "#fecaca"),
    "PURE SLOP": ("#f87171", "#fecaca"),
}

RULE_BAR_GRAY = "#d4d4d4"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3):]


def _build_rule_bars(result: ScanResult, x_start: int, y_start: int) -> list[str]:
    sans = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    if not result.rule_counts:
        return [
            f'<rect x="{x_start}" y="{y_start}" width="486" height="96" rx="12" fill="#ffffff" fill-opacity="0.03" stroke="#ffffff" stroke-opacity="0.075"/>',
            f'<text x="{x_start + 243}" y="{y_start + 42}" text-anchor="middle" fill="#6ee7b7" font-size="13.5" font-weight="600" font-family="{sans}">ZERO SLOP PATTERNS DETECTED</text>',
            f'<text x="{x_start + 243}" y="{y_start + 64}" text-anchor="middle" fill="#8e8e8e" font-size="12" font-family="{sans}">AST &amp; polyglot heuristics found zero bloat, clichés, or silent catches.</text>',
        ]

    lines: list[str] = []
    top_rules = list(result.rule_counts.items())[:5]
    max_count = max(count for _, count in top_rules) or 1
    bar_max_w = 260

    for idx, (rule, count) in enumerate(top_rules):
        y = y_start + idx * 26
        fill_w = max(8, int(round((count / max_count) * bar_max_w)))
        lines.append(
            f'<text x="{x_start}" y="{y + 13}" fill="#e5e5e5" font-size="12" font-family="{mono}">{escape(rule)}</text>'
        )
        lines.append(
            f'<rect x="{x_start + 150}" y="{y + 4}" width="{bar_max_w}" height="8" rx="4" fill="#ffffff" fill-opacity="0.07"/>'
        )
        lines.append(
            f'<rect x="{x_start + 150}" y="{y + 4}" width="{fill_w}" height="8" rx="4" fill="{RULE_BAR_GRAY}"/>'
        )
        lines.append(
            f'<text x="{x_start + 482}" y="{y + 13}" text-anchor="end" fill="#8e8e8e" font-size="12" font-weight="600" font-family="{mono}">{count}</text>'
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
    sans = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    parts = [
        f'<text x="36" y="{y_start}" fill="#8e8e8e" font-size="10.5" font-weight="600" letter-spacing="1" font-family="{sans}">TOP HOTSPOTS</text>'
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
            f'<rect x="36" y="{y}" width="746" height="20" rx="5" fill="#ffffff" fill-opacity="0.03" stroke="#ffffff" stroke-opacity="0.05"/>'
        )
        parts.append(
            f'<text x="46" y="{y + 14}" fill="#e5e5e5" font-size="11.5" font-family="{mono}">{escape(_truncate(rel.replace(chr(92), "/"), 46))}</text>'
        )
        parts.append(
            f'<text x="495" y="{y + 14}" fill="#8e8e8e" font-size="11" font-family="{mono}">{escape(top_rule)}</text>'
        )
        parts.append(
            f'<text x="772" y="{y + 14}" text-anchor="end" fill="#fbbf24" font-size="11" font-weight="600" font-family="{mono}">{len(issues)} issues (+{weight})</text>'
        )
    return parts


def render_scorecard_svg(result: ScanResult, title: str | None = None) -> str:
    """Render a standalone matte monochrome glass SVG scorecard summarizing scan results."""
    accent, pill_text = VERDICT_THEMES.get(result.verdict, ("#34d399", "#6ee7b7"))
    resolved = result.target.resolve()
    display_title = title or resolved.name or str(result.target)
    mode_label = f"DIFF: {result.diff_base}" if result.diff_base else ("GIT DIFF" if result.diff_mode else "FULL REPO")

    hotspot_rows = _build_hotspot_rows(result, 310)
    hotspot_count = min(3, len(result.file_issues))
    height = 360 if not hotspot_rows else 356 + hotspot_count * 24 + 28

    radius = 64
    circumference = 2 * 3.14159265 * radius
    dash_offset = circumference * (1.0 - (result.score / 100.0))
    ring_stroke = "#ffffff" if result.score == 0 else accent

    metric_items = [
        ("FILES", f"{result.files_scanned:,}"),
        ("LINES", f"{result.total_lines:,}"),
        ("ISSUES", f"{len(result.issues):,}"),
        ("TIME", f"{result.elapsed:.2f}s"),
    ]
    sans = "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    metric_svg: list[str] = []
    for idx, (label, value) in enumerate(metric_items):
        mx = 296 + idx * 124
        metric_svg.append(f'<rect x="{mx}" y="94" width="114" height="54" rx="10" fill="#ffffff" fill-opacity="0.035" stroke="#ffffff" stroke-opacity="0.075"/>')
        metric_svg.append(f'<text x="{mx + 14}" y="114" fill="#8e8e8e" font-size="10" font-weight="600" letter-spacing="0.8" font-family="{sans}">{label}</text>')
        metric_svg.append(f'<text x="{mx + 14}" y="137" fill="#ffffff" font-size="17" font-weight="700" font-family="{sans}">{escape(value)}</text>')

    rule_svg = _build_rule_bars(result, 296, 174)
    footer_y = height - 20

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="{height}" viewBox="0 0 820 {height}">',
        '<defs>',
        '<radialGradient id="scGlow" cx="16%" cy="8%" r="55%">',
        '<stop offset="0%" stop-color="#ffffff" stop-opacity="0.075"/>',
        '<stop offset="100%" stop-color="#0a0a0a" stop-opacity="0"/>',
        '</radialGradient>',
        '<linearGradient id="scGlass" x1="0%" y1="0%" x2="0%" y2="100%">',
        '<stop offset="0%" stop-color="#ffffff" stop-opacity="0.065"/>',
        '<stop offset="100%" stop-color="#ffffff" stop-opacity="0.02"/>',
        '</linearGradient>',
        '</defs>',
        f'<rect width="820" height="{height}" rx="16" fill="#0a0a0a"/>',
        f'<rect width="820" height="{height}" rx="16" fill="url(#scGlow)"/>',
        f'<rect x="12" y="12" width="796" height="{height - 24}" rx="14" fill="url(#scGlass)" stroke="#ffffff" stroke-opacity="0.1"/>',
        '<line x1="24" y1="13" x2="796" y2="13" stroke="#ffffff" stroke-opacity="0.18"/>',
        f'<text x="36" y="52" fill="#ffffff" font-size="17" font-weight="700" font-family="{sans}" letter-spacing="-0.3">slopcheck<tspan fill="#71717a">.</tspan></text>',
        f'<text x="132" y="52" fill="#8e8e8e" font-size="14" font-weight="500" font-family="{mono}">/ {escape(_truncate(display_title, 34))}</text>',
        '<rect x="530" y="34" width="110" height="24" rx="12" fill="#ffffff" fill-opacity="0.04" stroke="#ffffff" stroke-opacity="0.08"/>',
        f'<text x="585" y="50" text-anchor="middle" fill="#8e8e8e" font-size="10.5" font-weight="600" font-family="{sans}">{escape(_truncate(mode_label, 16))}</text>',
        f'<rect x="650" y="34" width="134" height="24" rx="12" fill="{accent}" fill-opacity="0.12" stroke="{accent}" stroke-opacity="0.34"/>',
        f'<text x="717" y="50" text-anchor="middle" fill="{pill_text}" font-size="10.5" font-weight="700" font-family="{sans}" letter-spacing="0.8">{escape(result.verdict)}</text>',
        '<line x1="36" y1="74" x2="784" y2="74" stroke="#ffffff" stroke-opacity="0.08"/>',
        '<rect x="36" y="94" width="236" height="196" rx="12" fill="#ffffff" fill-opacity="0.03" stroke="#ffffff" stroke-opacity="0.08"/>',
        '<circle cx="154" cy="184" r="64" fill="none" stroke="#ffffff" stroke-opacity="0.08" stroke-width="11"/>',
        f'<circle cx="154" cy="184" r="64" fill="none" stroke="{ring_stroke}" stroke-width="11" stroke-linecap="round" stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{dash_offset:.2f}" transform="rotate(-90 154 184)"/>',
        f'<text x="154" y="191" text-anchor="middle" fill="#ffffff" font-size="33" font-weight="700" font-family="{sans}">{result.score}%</text>',
        f'<text x="154" y="213" text-anchor="middle" fill="#8e8e8e" font-size="10" font-weight="600" letter-spacing="1.1" font-family="{sans}">SLOP SCORE</text>',
        f'<text x="154" y="272" text-anchor="middle" fill="#737373" font-size="10.5" font-family="{sans}">0-10% Clean · 11-35% Sus · 36+ Slop</text>',
        *metric_svg,
        *rule_svg,
        *hotspot_rows,
        f'<text x="36" y="{footer_y}" fill="#5a5a5a" font-size="11" font-family="{mono}">$ uvx sloplinter .</text>',
        f'<text x="784" y="{footer_y}" text-anchor="end" fill="#5a5a5a" font-size="11" font-family="{sans}">github.com/an1zy/slopcheck</text>',
        '</svg>',
    ]
    return "\n".join(svg_parts) + "\n"
