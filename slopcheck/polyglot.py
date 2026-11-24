import bisect
from pathlib import Path
import re

from slopcheck.core import Issue
from slopcheck.rules import (
    _is_tautological_comment,
    _match_ai_cliche,
    AI_EMOJIS,
    DEBUG_MARKERS,
)

TOKEN_SPEC = re.compile(
    r'(?P<BLOCK_COMMENT>/\*.*?\*/)'
    r'|(?P<LINE_COMMENT>//[^\n]*)'
    r'|(?P<STRING_DOUBLE>"(?:\\.|[^"\\\n])*")'
    r'|(?P<STRING_SINGLE>\'(?:\\.|[^\'\\\n])*\')'
    r'|(?P<STRING_BACKTICK>`(?:\\.|[^`\\])*`)',
    re.DOTALL,
)

# Rust lifetimes like 'a share single quotes, so only treat single-char literals as strings
RUST_TOKEN_SPEC = re.compile(
    r'(?P<BLOCK_COMMENT>/\*.*?\*/)'
    r'|(?P<LINE_COMMENT>//[^\n]*)'
    r'|(?P<STRING_DOUBLE>"(?:\\.|[^"\\\n])*")'
    r'|(?P<STRING_SINGLE>\'(?:\\[^\n]|[^\'\\\n])\')',
    re.DOTALL,
)

CALL_PATTERN = re.compile(
    r"\b(?P<call>console\.log|println!|Console\.WriteLine|printf|fmt\.Println|System\.out\.println)\s*\((?P<args>[^)]*)\)"
    r"|"
    r"\b(?P<cout>(?:std::)?cout)\s*<<\s*(?P<cout_args>[^;]+);",
    re.MULTILINE
)

CATCH_PATTERN = re.compile(
    r"\bcatch\s*(?:\([^{]*\))?\s*\{(?:\s*|(?:\s*;\s*))\}",
    re.MULTILINE
)

STR_EXTRACT_PATTERN = re.compile(
    r'"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'|`((?:\\.|[^`\\])*)`'
)


def _extract_c_strings(text: str) -> list[str]:
    strings: list[str] = []
    for m in STR_EXTRACT_PATTERN.finditer(text):
        for g in m.groups():
            if g is not None:
                strings.append(g)
                break
    return strings


def _is_captain_comment(comment_text: str, next_line: str) -> bool:
    if not next_line or next_line.startswith(("//", "/*", "*")):
        return False
    return _is_tautological_comment(comment_text, next_line)


def _build_line_offsets(text: str) -> list[int]:
    offsets = [0]
    idx = text.find("\n")
    while idx != -1:
        offsets.append(idx + 1)
        idx = text.find("\n", idx + 1)
    return offsets


def _extract_c_tokens(source: str, suffix: str = "", line_offsets: list[int] | None = None) -> tuple[list[dict], str]:
    comments: list[dict] = []
    spec = RUST_TOKEN_SPEC if suffix == ".rs" else TOKEN_SPEC
    offsets = line_offsets if line_offsets is not None else _build_line_offsets(source)

    def repl(m: re.Match) -> str:
        kind = m.lastgroup
        if kind not in ("LINE_COMMENT", "BLOCK_COMMENT"):
            return m.group(0)

        start = m.start()
        prev_nl = source.rfind('\n', 0, start)
        prefix = source[prev_nl + 1:start]
        line = bisect.bisect_right(offsets, start)

        if kind == "LINE_COMMENT":
            comments.append({
                "type": "line",
                "text": m.group(0),
                "line": line,
                "standalone": prefix.strip() == "",
            })
            return " " * len(m.group(0))

        comments.append({
            "type": "block",
            "text": m.group(0),
            "line": line,
            "standalone": prefix.strip() == "",
        })
        return "".join('\n' if c == '\n' else ' ' for c in m.group(0))

    clean_code = spec.sub(repl, source)
    return comments, clean_code


def _check_comments(path: Path, comments: list[dict], lines: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for c in comments:
        text, line, is_standalone = c["text"], c["line"], c["standalone"]

        matched = _match_ai_cliche(text)
        if matched:
            issues.append(
                Issue(
                    path=path,
                    line=line,
                    rule="ai-cliche",
                    message=f"AI cliché comment detected: '{matched}'",
                    weight=12,
                )
            )

        if any(e in text for e in AI_EMOJIS):
            issues.append(
                Issue(
                    path=path,
                    line=line,
                    rule="emoji-slop",
                    message="AI emoji detected in comment",
                    weight=10,
                )
            )

        if c["type"] == "line" and is_standalone and line < len(lines):
            next_line = lines[line].strip()
            if _is_captain_comment(text, next_line):
                issues.append(
                    Issue(
                        path=path,
                        line=line,
                        rule="captain-comment",
                        message=f"Comment duplicates code on line {line + 1}",
                        weight=6,
                    )
                )
    return issues


def _check_output_calls(path: Path, clean_code: str, offsets: list[int]) -> list[Issue]:
    issues: list[Issue] = []
    for m in CALL_PATTERN.finditer(clean_code):
        args_text = m.group("args") if m.group("call") else m.group("cout_args")
        strs = _extract_c_strings(args_text)
        line = bisect.bisect_right(offsets, m.start())

        if any(any(e in s for e in AI_EMOJIS) for s in strs):
            issues.append(
                Issue(
                    path=path,
                    line=line,
                    rule="emoji-slop",
                    message="AI emoji detected in output call",
                    weight=10,
                )
            )

        if strs:
            head = strs[0].strip().lower()
            if any(head == marker or head.startswith(marker) for marker in DEBUG_MARKERS):
                issues.append(
                    Issue(
                        path=path,
                        line=line,
                        rule="debug-print",
                        message=f"Debug print statement detected: '{strs[0][:20]}'",
                        weight=8,
                    )
                )
    return issues


def _check_silent_catch(path: Path, clean_code: str, offsets: list[int]) -> list[Issue]:
    issues: list[Issue] = []
    for m in CATCH_PATTERN.finditer(clean_code):
        line = bisect.bisect_right(offsets, m.start())
        issues.append(
            Issue(
                path=path,
                line=line,
                rule="silent-catch",
                message="Empty or suppressed catch block",
                weight=15,
            )
        )
    return issues


def check_polyglot(path: Path, source: str) -> list[Issue]:
    offsets = _build_line_offsets(source)
    comments, clean_code = _extract_c_tokens(source, path.suffix.lower(), offsets)
    lines = source.splitlines()

    issues: list[Issue] = []
    issues.extend(_check_comments(path, comments, lines))
    issues.extend(_check_output_calls(path, clean_code, offsets))
    issues.extend(_check_silent_catch(path, clean_code, offsets))
    issues.sort(key=lambda i: (i.line, i.rule))
    return issues
