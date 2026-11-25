import ast
from pathlib import Path
import tempfile
import unittest

from slopcheck.scanner import scan_target
from slopcheck.semantic import (
    check_duplicate_helpers,
    check_security_slop_python,
    check_semantic_polyglot,
    check_test_theatre_python,
)


class TestSemanticRules(unittest.TestCase):
    def test_duplicate_helper_detects_renamed_copy(self):
        fn_a = (
            "def parse_user_cfg(raw):\n"
            "    items = raw.strip().splitlines()\n"
            "    out = {}\n"
            "    for line in items:\n"
            "        if '=' in line:\n"
            "            k, v = line.split('=', 1)\n"
            "            out[k.strip()] = v.strip()\n"
            "    return out\n"
        )
        fn_b = (
            "def load_admin_settings(blob):\n"
            "    items = blob.strip().splitlines()\n"
            "    out = {}\n"
            "    for line in items:\n"
            "        if '=' in line:\n"
            "            k, v = line.split('=', 1)\n"
            "            out[k.strip()] = v.strip()\n"
            "    return out\n"
        )
        p1, p2 = Path("a_utils.py"), Path("b_service.py")
        trees = [(p1, ast.parse(fn_a)), (p2, ast.parse(fn_b))]
        issues = check_duplicate_helpers(trees)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "duplicate-helper")
        self.assertEqual(issues[0].path, p2)

    def test_test_theatre_catches_no_assert_and_tautology(self):
        src = (
            "def test_empty():\n"
            "    val = 1 + 1\n\n"
            "def test_fake():\n"
            "    assert True\n\n"
            "def test_real():\n"
            "    assert sum([1, 2]) == 3\n"
        )
        issues = check_test_theatre_python(Path("tests/test_sample.py"), ast.parse(src))
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i.rule == "test-theatre" for i in issues))

    def test_security_slop_python_and_polyglot(self):
        py_src = (
            "import subprocess\n"
            "API_TOKEN = 'ghp_1234567890abcdef1234567890abcdef'\n"
            "def fetch(url, cmd):\n"
            "    requests.get(url, verify=False)\n"
            "    subprocess.run(cmd, shell=True)\n"
            "    return eval(cmd)\n"
        )
        py_issues = check_security_slop_python(Path("app/client.py"), py_src, ast.parse(py_src))
        self.assertEqual(len(py_issues), 4)
        self.assertTrue(all(i.rule == "security-slop" for i in py_issues))

        ts_issues = check_semantic_polyglot(
            Path("src/app.test.ts"),
            "test('fake', () => { expect(true).toBe(true); });\n",
        )
        self.assertEqual(len(ts_issues), 1)
        self.assertEqual(ts_issues[0].rule, "test-theatre")

    def test_scan_target_supports_no_semantic_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("def test_noop():\n    x = 1\n", encoding="utf-8")
            with_sem = scan_target(root, semantic=True)
            no_sem = scan_target(root, semantic=False)
            self.assertEqual(len(with_sem.issues), 1)
            self.assertEqual(len(no_sem.issues), 0)


if __name__ == "__main__":
    unittest.main()
