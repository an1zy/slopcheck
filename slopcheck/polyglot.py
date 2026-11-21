from pathlib import Path
import re

from slopcheck.core import Issue
from slopcheck.rules import (
    _count_word_matches,
    _extract_words,
    _match_ai_cliche,
    AI_EMOJIS,
    DEBUG_MARKERS,
)

TOKEN_SPEC = re.compile(
    r'(?P<BLOCK_COMMENT>/\*.*?\*/)'
    r'|(?P<LINE_COMMENT>//[^\n]*)'
    r'|(?P<STRING_DOUBLE>"(\\.|[^"\\])*")'
    r'|(?P<STRING_SINGLE>\'(\\.|[^\'\\])*\')'
    r'|(?P<STRING_BACKTICK>`(\\.|[^`\\])*`)',
    re.DOTALL
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
    c_words = _extract_words(comment_text)
    code_words = _extract_words(next_line)
    if len(c_words) < 2 or not code_words:
        return False
    return _count_word_matches(c_words, code_words) >= 2


def _extract_c_tokens(source: str) -> tuple[list[dict], str]:
    comments: list[dict] = []

    def repl(m: re.Match) -> str:
        kind = m.lastgroup
        start = m.start()
        prev_nl = source.rfind('\n', 0, start)
        prefix = source[prev_nl + 1:start]
        line = source[:start].count('\n') + 1

        if kind == "LINE_COMMENT":
            comments.append({
                "type": "line",
                "text": m.group(0),
                "line": line,
                "standalone": prefix.strip() == "",
            })
            return " " * len(m.group(0))

        if kind == "BLOCK_COMMENT":
            comments.append({
                "type": "block",
                "text": m.group(0),
                "line": line,
                "standalone": prefix.strip() == "",
            })
            return "".join('\n' if c == '\n' else ' ' for c in m.group(0))

        return m.group(0)

    clean_code = TOKEN_SPEC.sub(repl, source)
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


def _check_output_calls(path: Path, clean_code: str) -> list[Issue]:
    issues: list[Issue] = []
    for m in CALL_PATTERN.finditer(clean_code):
        args_text = m.group("args") if m.group("call") else m.group("cout_args")
        strs = _extract_c_strings(args_text)
        line = clean_code[:m.start()].count('\n') + 1

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


def _check_silent_catch(path: Path, clean_code: str) -> list[Issue]:
    issues: list[Issue] = []
    for m in CATCH_PATTERN.finditer(clean_code):
        line = clean_code[:m.start()].count('\n') + 1
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
    comments, clean_code = _extract_c_tokens(source)
    lines = source.splitlines()

    issues: list[Issue] = []
    issues.extend(_check_comments(path, comments, lines))
    issues.extend(_check_output_calls(path, clean_code))
    issues.extend(_check_silent_catch(path, clean_code))
    issues.sort(key=lambda i: (i.line, i.rule))
    return issues
