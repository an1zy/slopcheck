import ast
import io
from pathlib import Path
import re
import tokenize

from slopcheck.core import Issue

AI_CLICHES = (
    "todo: implement",
    "placeholder",
    "in a real-world",
    "replace with actual",
    "your logic here",
    "for brevity",
)

AI_EMOJIS = ("🚀", "✨", "✅", "❌", "🔥", "🎉", "💡", "⚡", "🛠️", "🛠")

DEBUG_MARKERS = ("debug", "here", "test", "123", "asdf", "todo", "works")

BOOLEAN_OPS = (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)

CONTROL_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    getattr(ast, "TryStar", ast.Try),
)

STOPWORDS = frozenset({
    "this", "that", "with", "from", "into", "some", "none",
    "true", "false", "self", "args", "kwargs", "return", "pass",
})


def _extract_words(text: str) -> set[str]:
    words: set[str] = set()
    for tok in re.findall(r"[A-Za-z0-9]+", text):
        parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z0-9]|\b)", tok) or [tok]
        for part in parts:
            w = part.lower()
            if len(w) > 3 and w not in STOPWORDS:
                words.add(w)
    return words


def _count_word_matches(comment_words: set[str], code_words: set[str]) -> int:
    matched: set[str] = set()
    for cw in comment_words:
        for rw in code_words:
            if rw not in matched and (cw == rw or (len(rw) > 3 and rw in cw) or (len(cw) > 3 and cw in rw)):
                matched.add(rw)
                break
    return len(matched)


def _extract_strings(expr: ast.expr) -> list[str]:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.JoinedStr):
        return [
            part.value
            for part in expr.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
    return []


def _is_log_or_print(func: ast.expr) -> bool:
    if isinstance(func, ast.Name) and func.id == "print":
        return True
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "logging"
    )


def _has_emoji_arg(call: ast.Call) -> bool:
    for arg in call.args:
        if any(any(e in s for e in AI_EMOJIS) for s in _extract_strings(arg)):
            return True
    for kw in call.keywords:
        if any(any(e in s for e in AI_EMOJIS) for s in _extract_strings(kw.value)):
            return True
    return False


def _match_ai_cliche(comment: str) -> str | None:
    comment_lower = comment.lower()
    for marker in AI_CLICHES:
        if marker in comment_lower:
            return marker
    return None


def _calc_nesting_depth(node: ast.AST, current_depth: int = 0) -> int:
    max_depth = current_depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue

        # In AST elif is an If node directly inside parent If orelse
        is_elif = (
            isinstance(node, ast.If)
            and len(node.orelse) == 1
            and node.orelse[0] is child
        )
        if isinstance(child, CONTROL_NODES):
            next_depth = current_depth if is_elif else current_depth + 1
        else:
            next_depth = current_depth

        child_depth = _calc_nesting_depth(child, next_depth)
        if child_depth > max_depth:
            max_depth = child_depth
    return max_depth


def _is_useless_wrapper(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if node.decorator_list:
        return False
    if node.name.startswith("__") and node.name.endswith("__"):
        return False

    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]

    if len(body) != 1:
        return False

    stmt = body[0]
    if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Call):
        return False

    call = stmt.value
    if isinstance(call.func, ast.Name) and call.func.id == node.name:
        return False

    fn_args = node.args
    pos_params = [a.arg for a in fn_args.posonlyargs + fn_args.args]
    expected_call_pos_len = len(pos_params) + (1 if fn_args.vararg else 0)
    if len(call.args) != expected_call_pos_len:
        return False

    for param_name, call_arg in zip(pos_params, call.args):
        if not (isinstance(call_arg, ast.Name) and call_arg.id == param_name):
            return False

    if fn_args.vararg:
        star_arg = call.args[len(pos_params)]
        if not (
            isinstance(star_arg, ast.Starred)
            and isinstance(star_arg.value, ast.Name)
            and star_arg.value.id == fn_args.vararg.arg
        ):
            return False

    kwonly_params = [a.arg for a in fn_args.kwonlyargs]
    expected_kw_len = len(kwonly_params) + (1 if fn_args.kwarg else 0)
    if len(call.keywords) != expected_kw_len:
        return False

    for param_name, kw in zip(kwonly_params, call.keywords):
        if kw.arg != param_name or not (
            isinstance(kw.value, ast.Name) and kw.value.id == param_name
        ):
            return False

    if fn_args.kwarg:
        dict_kw = call.keywords[len(kwonly_params)]
        if dict_kw.arg is not None or not (
            isinstance(dict_kw.value, ast.Name) and dict_kw.value.id == fn_args.kwarg.arg
        ):
            return False

    return True


def _is_redundant_compare(node: ast.Compare) -> bool:
    if not any(isinstance(op, BOOLEAN_OPS) for op in node.ops):
        return False
    if isinstance(node.left, ast.Constant) and type(node.left.value) is bool:
        return True
    return any(
        isinstance(c, ast.Constant) and type(c.value) is bool
        for c in node.comparators
    )


def _is_redundant_boolean_if(node: ast.If) -> bool:
    if len(node.body) != 1 or len(node.orelse) != 1:
        return False
    b_stmt, e_stmt = node.body[0], node.orelse[0]
    if not isinstance(b_stmt, ast.Return) or not isinstance(e_stmt, ast.Return):
        return False
    b_val, e_val = b_stmt.value, e_stmt.value
    if not (isinstance(b_val, ast.Constant) and type(b_val.value) is bool):
        return False
    if not (isinstance(e_val, ast.Constant) and type(e_val.value) is bool):
        return False
    return b_val.value != e_val.value


def check_silent_except(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue

        if node.type is not None and not (
            isinstance(node.type, ast.Name) and node.type.id == "Exception"
        ):
            continue

        if len(node.body) != 1:
            continue

        stmt = node.body[0]
        is_silent = False
        if isinstance(stmt, ast.Pass):
            is_silent = True
        elif (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        ):
            is_silent = True
        elif (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "print"
        ):
            is_silent = True

        if is_silent:
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="silent-except",
                    message="Suppressed exception handler with pass, ellipsis, or print",
                    weight=15,
                )
            )
    return issues


def check_bloat_docstring(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue

        first = node.body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue

        if first.end_lineno is None or node.end_lineno is None:
            continue

        doc_lines = first.end_lineno - first.lineno + 1
        if doc_lines < 5:
            continue

        rest_lines = (node.end_lineno - first.end_lineno) if len(node.body) > 1 else 0
        if doc_lines > rest_lines:
            issues.append(
                Issue(
                    path=path,
                    line=first.lineno,
                    rule="bloat-docstring",
                    message=f"Docstring ({doc_lines} lines) exceeds function body ({rest_lines} lines)",
                    weight=8,
                )
            )
    return issues


def check_ai_cliche(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    issues: list[Issue] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []

    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            matched = _match_ai_cliche(tok.string)
            if matched:
                issues.append(
                    Issue(
                        path=path,
                        line=tok.start[0],
                        rule="ai-cliche",
                        message=f"AI cliché comment detected: '{matched}'",
                        weight=12,
                    )
                )
    return issues


def check_captain_comment(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    issues: list[Issue] = []
    lines = source.splitlines()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []

    for tok in tokens:
        if tok.type != tokenize.COMMENT or tok.line[:tok.start[1]].strip():
            continue

        line_no = tok.start[0]
        if line_no >= len(lines):
            continue

        next_line = lines[line_no].strip()
        if not next_line or next_line.startswith("#"):
            continue

        comment_words = _extract_words(tok.string)
        code_words = _extract_words(next_line)
        if len(comment_words) >= 2 and code_words:
            if _count_word_matches(comment_words, code_words) >= 2:
                issues.append(
                    Issue(
                        path=path,
                        line=line_no,
                        rule="captain-comment",
                        message=f"Comment duplicates code on line {line_no + 1}",
                        weight=6,
                    )
                )
    return issues


def check_emoji_slop(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    issues: list[Issue] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT and any(e in tok.string for e in AI_EMOJIS):
                issues.append(
                    Issue(
                        path=path,
                        line=tok.start[0],
                        rule="emoji-slop",
                        message="AI emoji detected in comment",
                        weight=10,
                    )
                )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_log_or_print(node.func) and _has_emoji_arg(node):
                issues.append(
                    Issue(
                        path=path,
                        line=node.lineno,
                        rule="emoji-slop",
                        message="AI emoji detected in output/log statement",
                        weight=10,
                    )
                )
    return issues


def check_debug_print(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "print"):
            continue
        if not node.args:
            continue

        first_arg_strings = _extract_strings(node.args[0])
        if not first_arg_strings:
            continue

        raw_text = first_arg_strings[0]
        cleaned = raw_text.strip().lower()
        if any(cleaned == m or cleaned.startswith(m) for m in DEBUG_MARKERS):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="debug-print",
                    message=f"Debug print statement detected: '{raw_text[:20]}'",
                    weight=8,
                )
            )
    return issues


def check_redundant_boolean(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and _is_redundant_compare(node):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="redundant-boolean",
                    message="Redundant explicit comparison with boolean literal",
                    weight=6,
                )
            )
        elif isinstance(node, ast.If) and _is_redundant_boolean_if(node):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="redundant-boolean",
                    message="Redundant boolean return pattern in if/else",
                    weight=6,
                )
            )
    return issues


def check_deep_nesting(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            depth = _calc_nesting_depth(node)
            if depth >= 4:
                issues.append(
                    Issue(
                        path=path,
                        line=node.lineno,
                        rule="deep-nesting",
                        message=f"Deep control nesting (depth {depth} >= 4)",
                        weight=10,
                    )
                )
    return issues


def check_wildcard_import(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                issues.append(
                    Issue(
                        path=path,
                        line=node.lineno,
                        rule="wildcard-import",
                        message=f"Wildcard import 'from {node.module or '.'} import *'",
                        weight=8,
                    )
                )
    return issues


def check_useless_wrapper(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_useless_wrapper(node):
                issues.append(
                    Issue(
                        path=path,
                        line=node.lineno,
                        rule="useless-wrapper",
                        message=f"Function '{node.name}' is a useless wrapper forwarding arguments",
                        weight=7,
                    )
                )
    return issues


ALL_RULES = (
    check_silent_except,
    check_bloat_docstring,
    check_ai_cliche,
    check_captain_comment,
    check_emoji_slop,
    check_debug_print,
    check_redundant_boolean,
    check_deep_nesting,
    check_wildcard_import,
    check_useless_wrapper,
)
