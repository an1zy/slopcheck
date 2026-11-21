import ast
from pathlib import Path
import tempfile
import unittest

from slopcheck.core import Issue, calculate_score, iter_source_files
from slopcheck.polyglot import check_polyglot
from slopcheck.rules import (
    check_ai_cliche,
    check_bloat_docstring,
    check_captain_comment,
    check_debug_print,
    check_deep_nesting,
    check_emoji_slop,
    check_redundant_boolean,
    check_silent_except,
    check_useless_wrapper,
    check_wildcard_import,
)


class TestRules(unittest.TestCase):
    def setUp(self):
        self.dummy_path = Path("sample.py")

    def _run(self, rule_fn, source: str):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        return rule_fn(self.dummy_path, source, tree)

    def test_silent_except_positive(self):
        source = "try:\n    step()\nexcept Exception:\n    pass\n"
        issues = self._run(check_silent_except, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "silent-except")

    def test_silent_except_negative(self):
        source = "try:\n    step()\nexcept ValueError:\n    pass\n"
        issues = self._run(check_silent_except, source)
        self.assertEqual(len(issues), 0)

    def test_bloat_docstring_positive(self):
        source = (
            "def fn():\n"
            '    """\n'
            "    Line 1\n"
            "    Line 2\n"
            "    Line 3\n"
            "    Line 4\n"
            '    """\n'
            "    return 1\n"
        )
        issues = self._run(check_bloat_docstring, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "bloat-docstring")

    def test_bloat_docstring_negative(self):
        source = 'def fn():\n    """Brief summary."""\n    return 1\n'
        issues = self._run(check_bloat_docstring, source)
        self.assertEqual(len(issues), 0)

    def test_ai_cliche_positive(self):
        source = "# TODO: implement validation logic\nval = 1\n"
        issues = self._run(check_ai_cliche, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "ai-cliche")

    def test_ai_cliche_negative(self):
        source = "# Buffer size must stay within allocation limits\nbuf = 1024\n"
        issues = self._run(check_ai_cliche, source)
        self.assertEqual(len(issues), 0)

    def test_captain_comment_positive(self):
        source = "# initialize database\ninit_database()\n"
        issues = self._run(check_captain_comment, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "captain-comment")

    def test_captain_comment_negative(self):
        source = "# SQLite WAL mode is required for concurrency\ndb.execute('PRAGMA journal_mode=WAL')\n"
        issues = self._run(check_captain_comment, source)
        self.assertEqual(len(issues), 0)

    def test_emoji_slop_positive(self):
        source = '# Ship it 🚀\nimport logging\nlogging.info("Done ✅")\n'
        issues = self._run(check_emoji_slop, source)
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i.rule == "emoji-slop" for i in issues))

    def test_emoji_slop_negative(self):
        source = '# Standard comment\nimport logging\nlogging.info("Operation succeeded")\n'
        issues = self._run(check_emoji_slop, source)
        self.assertEqual(len(issues), 0)

    def test_debug_print_positive(self):
        source = 'print("debug: inspecting state", data)\nprint("here")\n'
        issues = self._run(check_debug_print, source)
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i.rule == "debug-print" for i in issues))

    def test_debug_print_negative(self):
        source = 'print("Listening for connections on port 8080")\nprint(payload)\n'
        issues = self._run(check_debug_print, source)
        self.assertEqual(len(issues), 0)

    def test_redundant_boolean_positive(self):
        source = (
            "res = val == True\n"
            "if cond:\n"
            "    return True\n"
            "else:\n"
            "    return False\n"
        )
        issues = self._run(check_redundant_boolean, source)
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i.rule == "redundant-boolean" for i in issues))

    def test_redundant_boolean_negative(self):
        source = (
            "res = val == 1\n"
            "if cond:\n"
            "    return 1\n"
            "else:\n"
            "    return 2\n"
        )
        issues = self._run(check_redundant_boolean, source)
        self.assertEqual(len(issues), 0)

    def test_deep_nesting_positive(self):
        source = (
            "def deeply_nested():\n"
            "    if a:\n"
            "        for b in c:\n"
            "            while d:\n"
            "                with e:\n"
            "                    pass\n"
        )
        issues = self._run(check_deep_nesting, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "deep-nesting")

    def test_deep_nesting_negative(self):
        source = (
            "def shallow_with_elifs():\n"
            "    if a:\n"
            "        x = 1\n"
            "    elif b:\n"
            "        x = 2\n"
            "    elif c:\n"
            "        x = 3\n"
            "    else:\n"
            "        x = 4\n"
        )
        issues = self._run(check_deep_nesting, source)
        self.assertEqual(len(issues), 0)

    def test_wildcard_import_positive(self):
        source = "from math import *\n"
        issues = self._run(check_wildcard_import, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "wildcard-import")

    def test_wildcard_import_negative(self):
        source = "from math import sqrt, sin\n"
        issues = self._run(check_wildcard_import, source)
        self.assertEqual(len(issues), 0)

    def test_useless_wrapper_positive(self):
        source = (
            "def forward(a, b, *args, **kwargs):\n"
            '    """Docstring."""\n'
            "    return target(a, b, *args, **kwargs)\n"
        )
        issues = self._run(check_useless_wrapper, source)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "useless-wrapper")

    def test_useless_wrapper_negative(self):
        source = (
            "def transform(a, b):\n"
            "    return target(b, a)\n\n"
            "@decorator\n"
            "def decorated(a):\n"
            "    return target(a)\n"
        )
        issues = self._run(check_useless_wrapper, source)
        self.assertEqual(len(issues), 0)

    def test_polyglot_js_ts(self):
        pos_src = (
            "// TODO: implement caching\n"
            'console.log("debug: payload", data);\n'
            'console.log("Started 🚀");\n'
            "try { connect(); } catch (e) { }\n"
            "// initialize database\n"
            "initDatabase();\n"
        )
        pos_issues = check_polyglot(Path("test.ts"), pos_src)
        rules = {i.rule for i in pos_issues}
        self.assertIn("ai-cliche", rules)
        self.assertIn("debug-print", rules)
        self.assertIn("emoji-slop", rules)
        self.assertIn("silent-catch", rules)
        self.assertIn("captain-comment", rules)

        neg_src = (
            "// Request retry handler for network queries\n"
            "function retry(url) {\n"
            '    console.log("Attempting request");\n'
            "    try { fetch(url); } catch (e) { logError(e); }\n"
            "}\n"
        )
        neg_issues = check_polyglot(Path("test.ts"), neg_src)
        self.assertEqual(len(neg_issues), 0)

    def test_polyglot_cpp(self):
        pos_src = (
            'std::cout << "here" << std::endl;\n'
            'std::cout << "Success ✨\\n";\n'
            "try { run(); } catch (...) { // ignore\n}\n"
        )
        pos_issues = check_polyglot(Path("test.cpp"), pos_src)
        rules = {i.rule for i in pos_issues}
        self.assertIn("debug-print", rules)
        self.assertIn("emoji-slop", rules)
        self.assertIn("silent-catch", rules)

        neg_src = (
            "// Buffer allocation with bounds check\n"
            "void allocate() {\n"
            '    std::cout << "Allocating memory buffers\\n";\n'
            "}\n"
        )
        neg_issues = check_polyglot(Path("test.cpp"), neg_src)
        self.assertEqual(len(neg_issues), 0)

    def test_polyglot_csharp(self):
        pos_src = (
            'Console.WriteLine("works!");\n'
            "try { Run(); } catch (Exception ex) { }\n"
        )
        pos_issues = check_polyglot(Path("test.cs"), pos_src)
        rules = {i.rule for i in pos_issues}
        self.assertIn("debug-print", rules)
        self.assertIn("silent-catch", rules)

        neg_src = (
            "// Process incoming requests safely\n"
            "void Process() {\n"
            '    Console.WriteLine("Request completed successfully");\n'
            "}\n"
        )
        neg_issues = check_polyglot(Path("test.cs"), neg_src)
        self.assertEqual(len(neg_issues), 0)

    def test_polyglot_rust(self):
        pos_src = (
            "// Ship it 🔥\n"
            'println!("123 testing");\n'
        )
        pos_issues = check_polyglot(Path("test.rs"), pos_src)
        rules = {i.rule for i in pos_issues}
        self.assertIn("emoji-slop", rules)
        self.assertIn("debug-print", rules)

        neg_src = (
            "// Packet verification routine\n"
            "fn verify() {\n"
            '    println!("Packet verified");\n'
            "}\n"
        )
        neg_issues = check_polyglot(Path("test.rs"), neg_src)
        self.assertEqual(len(neg_issues), 0)

    def test_calculate_score_sensitivity(self):
        dummy_issues = [
            Issue(Path("x.py"), i, "silent-except", "msg", 15)
            for i in range(20)
        ]
        score = calculate_score(dummy_issues, 3500)
        self.assertGreaterEqual(score, 25)
        self.assertLessEqual(score, 35)

    def test_iter_source_files_skips_generated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "app.ts").write_text("console.log('hi');")
            (tmppath / "app.d.ts").write_text("declare var x: number;")
            (tmppath / "vendor.min.js").write_text("var a=1;")
            (tmppath / "bundle.bundle.js").write_text("var b=2;")

            found = {p.name for p in iter_source_files(tmppath)}
            self.assertEqual(found, {"app.ts"})


if __name__ == "__main__":
    unittest.main()
