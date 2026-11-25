import ast
import copy
import hashlib
from pathlib import Path
import re

from slopcheck.core import Issue

SECRET_PATTERNS = (
    ("OpenAI/Anthropic key", re.compile(r"\bsk-(?:proj-|ant-api\d+-)[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{24,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}")),
)

JS_TAUTOLOGY_RE = re.compile(
    r"\b(?:expect\s*\(\s*(?:true|false|1)\s*\)\s*\.\s*(?:toBe|toEqual)\s*\(\s*(?:true|false|1)\s*\)|assert\.(?:ok|strictEqual)\s*\(\s*true\s*\))"
)

JS_EVAL_RE = re.compile(r"\beval\s*\(\s*[A-Za-z_$]")

SUBPROCESS_NAMES = frozenset({"run", "Popen", "call", "check_call", "check_output"})
TAUTOLOGY_METHODS = frozenset({"assertTrue", "assertFalse"})


def is_test_file(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    return any(part.lower() in {"tests", "test", "__tests__"} for part in path.parts)


class _BodyNormalizer(ast.NodeTransformer):
    def __init__(self, param_map: dict[str, str]) -> None:
        self.param_map = param_map

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.param_map:
            node.id = self.param_map[node.id]
        return node


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _count_statements(stmts: list[ast.stmt]) -> int:
    total = 0
    for stmt in stmts:
        total += 1
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                total += 1
    return total


def _fingerprint_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    if node.name.startswith("__") and node.name.endswith("__"):
        return None
    body = _strip_docstring(node.body)
    if _count_statements(body) < 5:
        return None

    all_args = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
    if node.args.vararg:
        all_args.append(node.args.vararg.arg)
    if node.args.kwarg:
        all_args.append(node.args.kwarg.arg)

    param_map = {name: f"_arg{idx}" for idx, name in enumerate(all_args) if name != "self"}
    normalizer = _BodyNormalizer(param_map)
    normalized_stmts = [normalizer.visit(copy.deepcopy(s)) for s in body]
    dump = "|".join(ast.dump(s, include_attributes=False) for s in normalized_stmts)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def collect_function_fingerprints(
    file_trees: list[tuple[Path, ast.AST]],
) -> dict[str, list[tuple[Path, int, str]]]:
    """Index structural AST hashes for non-test Python functions across files."""
    index: dict[str, list[tuple[Path, int, str]]] = {}
    for path, tree in file_trees:
        if is_test_file(path):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            digest = _fingerprint_function(node)
            if digest:
                index.setdefault(digest, []).append((path, node.lineno, node.name))
    return index


def check_duplicate_helpers(
    file_trees: list[tuple[Path, ast.AST]],
    all_trees: list[tuple[Path, ast.AST]] | None = None,
) -> list[Issue]:
    """Flag functions whose normalized AST body duplicates an existing function."""
    corpus = all_trees if all_trees is not None else file_trees
    index = collect_function_fingerprints(corpus)
    issues: list[Issue] = []

    for path, tree in file_trees:
        if is_test_file(path):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            digest = _fingerprint_function(node)
            if not digest:
                continue
            matches = index.get(digest, [])
            if len(matches) < 2:
                continue
            canonical = min(matches, key=lambda m: (str(m[0]), m[1]))
            if canonical[0] == path and canonical[1] == node.lineno:
                continue
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="duplicate-helper",
                    message=f"Duplicates logic of '{canonical[2]}' ({canonical[0].name}:{canonical[1]})",
                    weight=12,
                )
            )
    return issues


def _is_constant_equal(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Constant):
        return isinstance(expr.value, bool) or expr.value in (1, 0)
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1 and len(expr.comparators) == 1:
        left, right = expr.left, expr.comparators[0]
        if isinstance(left, ast.Name) and isinstance(right, ast.Name) and left.id == right.id:
            return isinstance(expr.ops[0], (ast.Eq, ast.Is))
        if isinstance(left, ast.Constant) and isinstance(right, ast.Constant):
            return left.value == right.value and isinstance(expr.ops[0], (ast.Eq, ast.Is))
    return False


def _inspect_assert_call(node: ast.Call) -> tuple[bool, bool]:
    if isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        is_assert = attr.startswith("assert") or attr in {"raises", "warns", "fail"}
        is_tautology = (
            attr in TAUTOLOGY_METHODS
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
        )
        return is_assert, is_tautology
    if isinstance(node.func, ast.Name) and node.func.id.startswith(("assert", "check_")):
        return True, False
    return False, False


def _has_assertion_activity(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, int | None]:
    has_assert = False
    tautology_line: int | None = None

    for node in ast.walk(fn_node):
        if isinstance(node, ast.Assert):
            has_assert = True
            if tautology_line is None and _is_constant_equal(node.test):
                tautology_line = node.lineno
            continue
        if not isinstance(node, ast.Call):
            continue
        is_assert, is_tautology = _inspect_assert_call(node)
        if is_assert:
            has_assert = True
        if is_tautology and tautology_line is None:
            tautology_line = node.lineno
    return has_assert, tautology_line


def check_test_theatre_python(path: Path, tree: ast.AST | None) -> list[Issue]:
    """Detect Python test functions with zero assertions or constant tautologies."""
    if tree is None or not is_test_file(path):
        return []

    issues: list[Issue] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        has_assert, tautology_line = _has_assertion_activity(node)
        if not has_assert:
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="test-theatre",
                    message=f"Test '{node.name}' has no assertions",
                    weight=12,
                )
            )
        elif tautology_line is not None:
            issues.append(
                Issue(
                    path=path,
                    line=tautology_line,
                    rule="test-theatre",
                    message=f"Tautological assertion in '{node.name}' always passes",
                    weight=12,
                )
            )
    return issues


def _is_bool_constant(expr: ast.expr, expected: bool) -> bool:
    if not isinstance(expr, ast.Constant):
        return False
    val = expr.value
    if type(val) is not bool:
        return False
    return val if expected else not val


def _is_dynamic_shell_call(node: ast.Call) -> bool:
    func = node.func
    is_subprocess = (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in SUBPROCESS_NAMES
    )
    if not is_subprocess:
        return False
    shell_true = any(
        kw.arg == "shell" and _is_bool_constant(kw.value, True)
        for kw in node.keywords
    )
    if not shell_true or not node.args:
        return False
    return not isinstance(node.args[0], ast.Constant)


def _is_insecure_tls_call(node: ast.Call) -> bool:
    return any(
        kw.arg == "verify" and _is_bool_constant(kw.value, False)
        for kw in node.keywords
    )


def _is_dynamic_eval(node: ast.Call) -> bool:
    if not (isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}):
        return False
    return bool(node.args) and not isinstance(node.args[0], ast.Constant)


def _is_wildcard_cors_with_creds(node: ast.Call) -> bool:
    has_creds = any(
        kw.arg == "allow_credentials" and _is_bool_constant(kw.value, True)
        for kw in node.keywords
    )
    if not has_creds:
        return False
    for kw in node.keywords:
        if kw.arg == "allow_origins" and isinstance(kw.value, ast.List):
            if any(isinstance(el, ast.Constant) and el.value == "*" for el in kw.value.elts):
                return True
    return False


def check_security_slop_python(path: Path, source: str, tree: ast.AST | None) -> list[Issue]:
    """Flag unreviewed security shortcuts and hardcoded secrets in Python code."""
    if is_test_file(path):
        return []

    issues: list[Issue] = []
    for line_no, line in enumerate(source.splitlines(), 1):
        for label, pat in SECRET_PATTERNS:
            if pat.search(line):
                issues.append(
                    Issue(
                        path=path,
                        line=line_no,
                        rule="security-slop",
                        message=f"Potential hardcoded {label} detected",
                        weight=15,
                    )
                )

    if tree is None:
        return issues

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_dynamic_shell_call(node):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="security-slop",
                    message="Dynamic command passed to subprocess(..., shell=True)",
                    weight=15,
                )
            )
        elif _is_insecure_tls_call(node):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="security-slop",
                    message="TLS certificate verification disabled (verify=False)",
                    weight=15,
                )
            )
        elif _is_dynamic_eval(node):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="security-slop",
                    message=f"Dynamic '{node.func.id}(...)' execution detected",
                    weight=15,
                )
            )
        elif _is_wildcard_cors_with_creds(node):
            issues.append(
                Issue(
                    path=path,
                    line=node.lineno,
                    rule="security-slop",
                    message="Wildcard CORS allow_origins=['*'] with allow_credentials=True",
                    weight=15,
                )
            )
    return issues


def _scan_polyglot_security_line(path: Path, line_no: int, line: str) -> list[Issue]:
    issues: list[Issue] = []
    for label, pat in SECRET_PATTERNS:
        if pat.search(line):
            issues.append(
                Issue(
                    path=path,
                    line=line_no,
                    rule="security-slop",
                    message=f"Potential hardcoded {label} detected",
                    weight=15,
                )
            )
    if JS_EVAL_RE.search(line):
        issues.append(
            Issue(
                path=path,
                line=line_no,
                rule="security-slop",
                message="Dynamic eval(...) execution detected",
                weight=15,
            )
        )
    return issues


def check_semantic_polyglot(path: Path, source: str) -> list[Issue]:
    """Run security and test-theatre checks across JS/TS/Rust/Go/C#/Java files."""
    issues: list[Issue] = []
    test_file = is_test_file(path)

    for line_no, line in enumerate(source.splitlines(), 1):
        if test_file and JS_TAUTOLOGY_RE.search(line):
            issues.append(
                Issue(
                    path=path,
                    line=line_no,
                    rule="test-theatre",
                    message="Tautological test assertion always passes",
                    weight=12,
                )
            )
        if not test_file:
            issues.extend(_scan_polyglot_security_line(path, line_no, line))
    return issues
