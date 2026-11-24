import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

from slopcheck.scanner import ScanResult, get_badge_url, scan_target
from slopcheck.svg import render_scorecard_svg

COMMENT_MARKER = "<!-- slopcheck-pr-comment -->"


def format_markdown_report(result: ScanResult, max_score: int) -> str:
    """Build a GitHub Markdown summary and PR comment body from a ScanResult."""
    badge = f"![Slop Score]({get_badge_url(result.score)})"
    scope = f"Diff (`{result.diff_base}`)" if result.diff_base else "Full repository"
    status = "PASSED" if result.score <= max_score else f"FAILED (exceeds max-score {max_score}%)"

    lines = [
        COMMENT_MARKER,
        f"## slopcheck Report {badge}",
        "",
        f"- **Status:** {status}",
        f"- **Verdict:** `{result.verdict}` (`{result.score}%`)",
        f"- **Scope:** {scope} — `{result.files_scanned}` files, `{result.total_lines:,}` lines, `{len(result.issues)}` issues ({result.elapsed:.2f}s)",
        "",
    ]

    if result.rule_counts:
        lines.extend([
            "| Rule | Hits |",
            "| :--- | :---: |",
        ])
        for rule, count in result.rule_counts.items():
            lines.append(f"| `{rule}` | {count} |")
        lines.append("")

    if result.issues:
        resolved_target = result.target.resolve()
        base = resolved_target if resolved_target.is_dir() else resolved_target.parent
        lines.extend([
            "<details>",
            f"<summary>Top findings ({min(25, len(result.issues))} of {len(result.issues)})</summary>",
            "",
            "| File | Line | Rule | Message |",
            "| :--- | :---: | :--- | :--- |",
        ])
        for issue in result.issues[:25]:
            try:
                rel = str(issue.path.resolve().relative_to(base))
            except ValueError:
                rel = issue.path.name
            safe_msg = issue.message.replace("|", "\\|")
            lines.append(f"| `{rel.replace(chr(92), '/')}` | {issue.line} | `{issue.rule}` | {safe_msg} |")
        lines.extend(["", "</details>", ""])
    else:
        lines.append("Zero AI slop patterns detected.\n")

    return "\n".join(lines)


def _github_api(method: str, url: str, token: str, payload: dict | None = None) -> dict | list:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "slopcheck-action",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _find_existing_comment_id(comments_url: str, token: str) -> int | None:
    existing = _github_api("GET", comments_url, token)
    if not isinstance(existing, list):
        return None
    for item in existing:
        if COMMENT_MARKER in (item.get("body") or ""):
            return item.get("id")
    return None


def _upsert_pr_comment(body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not (token and repo and event_path and Path(event_path).is_file()):
        return

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request")
    if not pr or "number" not in pr:
        return

    pr_number = pr["number"]
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    comments_url = f"{api_base}/repos/{repo}/issues/{pr_number}/comments?per_page=100"

    try:
        target_id = _find_existing_comment_id(comments_url, token)
        if target_id is not None:
            _github_api("PATCH", f"{api_base}/repos/{repo}/issues/comments/{target_id}", token, {"body": body})
        else:
            _github_api("POST", f"{api_base}/repos/{repo}/issues/{pr_number}/comments", token, {"body": body})
    except (urllib.error.URLError, OSError, KeyError) as exc:
        print(f"::warning::Failed to post PR comment: {exc}", file=sys.stderr)


def _write_action_outputs(result: ScanResult) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as fh:
        fh.write(f"score={result.score}\n")
        fh.write(f"verdict={result.verdict}\n")
        fh.write(f"badge-url={get_badge_url(result.score)}\n")
        fh.write(f"issues-count={len(result.issues)}\n")


def _write_step_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as fh:
        fh.write(markdown + "\n")


def _ensure_base_ref(path: Path, base_ref: str) -> str | None:
    target_ref = f"origin/{base_ref}"
    cwd = path if path.is_dir() else path.parent
    check = subprocess.run(
        ["git", "rev-parse", "--verify", target_ref],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check.returncode == 0:
        return target_ref
    fetched = subprocess.run(
        ["git", "fetch", "--no-tags", "--depth=50", "origin", f"{base_ref}:refs/remotes/origin/{base_ref}"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if fetched.returncode == 0:
        return target_ref
    print(f"::warning::Could not fetch {target_ref}; falling back to full scan.", file=sys.stderr)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Action runner for slopcheck")
    parser.add_argument("--path", default=".", type=Path)
    parser.add_argument("--max-score", default=20, type=int)
    parser.add_argument("--diff-only", default="false")
    parser.add_argument("--comment-pr", default="true")
    parser.add_argument("--fail-on-exceed", default="true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--svg-path", default="")
    args = parser.parse_args()

    diff_only = args.diff_only.lower() == "true"
    comment_pr = args.comment_pr.lower() == "true"
    fail_on_exceed = args.fail_on_exceed.lower() == "true"
    excludes = tuple(p.strip() for p in args.exclude.split(",") if p.strip())

    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    diff_base = _ensure_base_ref(args.path, base_ref) if (diff_only and base_ref) else None

    result = scan_target(
        args.path,
        diff_mode=bool(diff_base),
        diff_base=diff_base,
        excludes=excludes,
    )
    if args.svg_path.strip():
        svg_out = Path(args.svg_path.strip())
        svg_out.parent.mkdir(parents=True, exist_ok=True)
        svg_out.write_text(render_scorecard_svg(result, title=os.environ.get("GITHUB_REPOSITORY") or None), encoding="utf-8")

    markdown = format_markdown_report(result, args.max_score)
    _write_action_outputs(result)
    _write_step_summary(markdown)
    if comment_pr:
        _upsert_pr_comment(markdown)

    print(f"Slop Score: {result.score}% ({result.verdict}) across {result.files_scanned} files")
    if fail_on_exceed and result.score > args.max_score:
        print(f"::error::Slop score {result.score}% exceeds max-score {args.max_score}%", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
