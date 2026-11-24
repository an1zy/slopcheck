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

RATIONALE_WORDS = frozenset({
    "because", "since", "avoid", "prevent", "ensure", "required",
    "otherwise", "workaround", "instead", "must", "need", "needs",
    "unless", "without", "legacy", "compat",
})

DOC_DIRECTIVES = (
    ":param",
    ":type",
    ":return",
    ":rtype",
    ":raises",
    ".. version",
    ".. note::",
    ".. warning::",
    ".. deprecated::",
    ">>>",
)


def _is_sphinx_or_doctest(doc_text: str) -> bool:
    lower = doc_text.lower()
    return any(marker in lower for marker in DOC_DIRECTIVES)


def _is_tautological_comment(comment_text: str, next_line: str) -> bool:
    stripped = comment_text.lstrip()
    if stripped.startswith(("#:", "///", "//!")):
        return False
    lower = stripped.lower()
    if any(word in lower.split() for word in RATIONALE_WORDS):
        return False
    c_words = _extract_words(comment_text)
    code_words = _extract_words(next_line)
    if len(c_words) < 2 or len(c_words) > 6 or not code_words:
        return False
    matches = _count_word_matches(c_words, code_words)
    return matches >= 2 and (matches / len(c_words)) >= 0.5


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
        if isinstance(node, ast.ExceptHandler):
            issues.extend(_inspect_except_handler(path, node))
    return issues


def check_bloat_docstring(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            issues.extend(_inspect_function_def(path, node, check_doc=True, check_nesting=False, check_wrapper=False))
    return issues


def _safe_tokenize(source: str) -> list[tokenize.TokenInfo]:
    try:
        return list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return []


def _check_comment_tokens(
    path: Path,
    source: str,
    tokens: list[tokenize.TokenInfo],
    check_cliche: bool = True,
    check_captain: bool = True,
    check_emoji: bool = True,
) -> list[Issue]:
    issues: list[Issue] = []
    lines = source.splitlines() if check_captain else []
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        line_no = tok.start[0]
        if check_cliche:
            matched = _match_ai_cliche(tok.string)
            if matched:
                issues.append(
                    Issue(
                        path=path,
                        line=line_no,
                        rule="ai-cliche",
                        message=f"AI cliché comment detected: '{matched}'",
                        weight=12,
                    )
                )
        if check_emoji and any(e in tok.string for e in AI_EMOJIS):
            issues.append(
                Issue(
                    path=path,
                    line=line_no,
                    rule="emoji-slop",
                    message="AI emoji detected in comment",
                    weight=10,
                )
            )
        if check_captain and not tok.line[:tok.start[1]].strip() and line_no < len(lines):
            next_line = lines[line_no].strip()
            if next_line and not next_line.startswith("#") and _is_tautological_comment(tok.string, next_line):
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


def _inspect_except_handler(path: Path, node: ast.ExceptHandler) -> list[Issue]:
    if node.type is not None and not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
        return []
    if len(node.body) != 1:
        return []
    stmt = node.body[0]
    is_pass = isinstance(stmt, ast.Pass)
    is_ellipsis = isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis
    is_print = (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "print"
    )
    if is_pass or is_ellipsis or is_print:
        return [
            Issue(
                path=path,
                line=node.lineno,
                rule="silent-except",
                message="Suppressed exception handler with pass, ellipsis, or print",
                weight=15,
            )
        ]
    return []


def _inspect_function_def(
    path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    check_doc: bool = True,
    check_nesting: bool = True,
    check_wrapper: bool = True,
) -> list[Issue]:
    issues: list[Issue] = []
    if check_doc and node.body:
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
            and node.end_lineno is not None
        ):
            doc_lines = first.end_lineno - first.lineno + 1
            rest_lines = (node.end_lineno - first.end_lineno) if len(node.body) > 1 else 0
            if doc_lines >= 5 and not _is_sphinx_or_doctest(first.value.value) and doc_lines > rest_lines:
                issues.append(
                    Issue(
                        path=path,
                        line=first.lineno,
                        rule="bloat-docstring",
                        message=f"Docstring ({doc_lines} lines) exceeds function body ({rest_lines} lines)",
                        weight=8,
                    )
                )
    if check_nesting:
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
    if check_wrapper and _is_useless_wrapper(node):
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


def _inspect_call_node(
    path: Path,
    node: ast.Call,
    check_emoji: bool = True,
    check_debug: bool = True,
) -> list[Issue]:
    issues: list[Issue] = []
    if check_emoji and _is_log_or_print(node.func) and _has_emoji_arg(node):
        issues.append(
            Issue(
                path=path,
                line=node.lineno,
                rule="emoji-slop",
                message="AI emoji detected in output/log statement",
                weight=10,
            )
        )
    if check_debug and isinstance(node.func, ast.Name) and node.func.id == "print" and node.args:
        first_arg_strings = _extract_strings(node.args[0])
        if first_arg_strings:
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


def scan_python(path: Path, source: str, tree: ast.AST | None) -> list[Issue]:
    """Run all Python comment and AST slop checks in a single pass."""
    tokens = _safe_tokenize(source)
    issues = _check_comment_tokens(path, source, tokens)
    if tree is None:
        return issues

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            issues.extend(_inspect_except_handler(path, node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            issues.extend(_inspect_function_def(path, node))
        elif isinstance(node, ast.Call):
            issues.extend(_inspect_call_node(path, node))
        elif isinstance(node, ast.Compare) and _is_redundant_compare(node):
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
        elif isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
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


def check_ai_cliche(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    return _check_comment_tokens(path, source, _safe_tokenize(source), check_cliche=True, check_captain=False, check_emoji=False)


def check_captain_comment(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    return _check_comment_tokens(path, source, _safe_tokenize(source), check_cliche=False, check_captain=True, check_emoji=False)


def check_emoji_slop(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    issues = _check_comment_tokens(path, source, _safe_tokenize(source), check_cliche=False, check_captain=False, check_emoji=True)
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                issues.extend(_inspect_call_node(path, node, check_emoji=True, check_debug=False))
    return issues


def check_debug_print(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            issues.extend(_inspect_call_node(path, node, check_emoji=False, check_debug=True))
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
            issues.extend(_inspect_function_def(path, node, check_doc=False, check_nesting=True, check_wrapper=False))
    return issues


def check_wildcard_import(path: Path, source: str, tree: ast.AST) -> list[Issue]:
    if tree is None:
        return []
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
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
            issues.extend(_inspect_function_def(path, node, check_doc=False, check_nesting=False, check_wrapper=True))
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
