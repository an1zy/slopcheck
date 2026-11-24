import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from slopcheck import __version__, scan_target
from slopcheck.diff import collect_diff_lines, parse_unified_diff
from slopcheck.github_action import COMMENT_MARKER, format_markdown_report
from slopcheck.polyglot import check_polyglot
from slopcheck.rules import ALL_RULES, check_ai_cliche, check_bloat_docstring, check_captain_comment, check_emoji_slop, scan_python
from slopcheck.svg import render_scorecard_svg


class TestNewFeatures(unittest.TestCase):
    def test_parse_unified_diff_ranges(self):
        diff_text = (
            "diff --git a/app.py b/app.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -10,0 +11,3 @@ def foo():\n"
            "+line11\n"
            "+line12\n"
            "+line13\n"
            "@@ -25 +28 @@ def bar():\n"
            "+line28\n"
        )
        root = Path("E:/fake_repo")
        parsed = parse_unified_diff(diff_text, root)
        expected_path = (root / "app.py").resolve()
        self.assertIn(expected_path, parsed)
        self.assertEqual(parsed[expected_path], {11, 12, 13, 28})

    def test_rust_lifetime_does_not_swallow_comments(self):
        src = (
            "fn borrow<'a>(s: &'a str) -> &'a str {\n"
            "    // TODO: implement proper parser\n"
            "    s\n"
            "}\n"
        )
        issues = check_polyglot(Path("lib.rs"), src)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].rule, "ai-cliche")

    def test_diff_mode_ignores_untouched_legacy_slop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "ci"], cwd=repo, check=True, capture_output=True)

            target_file = repo / "module.py"
            target_file.write_text(
                "try:\n"
                "    risky()\n"
                "except Exception:\n"
                "    pass\n\n"
                "def clean():\n"
                "    return 1\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

            target_file.write_text(
                "try:\n"
                "    risky()\n"
                "except Exception:\n"
                "    pass\n\n"
                "def clean():\n"
                "    return 2\n",
                encoding="utf-8",
            )

            full_res = scan_target(repo)
            self.assertGreater(full_res.score, 0)

            diff_res = scan_target(repo, diff_mode=True)
            self.assertTrue(diff_res.diff_mode)
            self.assertEqual(diff_res.score, 0)
            self.assertEqual(diff_res.total_lines, 1)

            changed = collect_diff_lines(repo)
            self.assertEqual(changed[target_file.resolve()], {7})

    def test_svg_scorecard_is_valid_xml_clean_and_dirty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            clean_file = root / "clean.py"
            clean_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            clean_res = scan_target(root)
            clean_svg = render_scorecard_svg(clean_res, title="demo-repo")
            ET.fromstring(clean_svg)
            self.assertIn("CLEAN", clean_svg)
            self.assertIn("demo-repo", clean_svg)

            dirty_file = root / "dirty.py"
            dirty_file.write_text(
                "# TODO: implement auth\n"
                "def ok(x):\n"
                "    if x:\n"
                "        return True\n"
                "    else:\n"
                "        return False\n",
                encoding="utf-8",
            )
            dirty_res = scan_target(root)
            dirty_svg = render_scorecard_svg(dirty_res, title="dirty & <test>")
            ET.fromstring(dirty_svg)
            self.assertIn("ai-cliche", dirty_svg)
            self.assertIn("dirty.py", dirty_svg)

    def test_cli_json_and_action_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "ok.py").write_text("x = 42\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "slopcheck.cli", str(root), "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["version"], __version__)
            self.assertEqual(payload["score"], 0)
            self.assertEqual(payload["verdict"], "CLEAN")

            res = scan_target(root)
            md = format_markdown_report(res, max_score=20)
            self.assertIn(COMMENT_MARKER, md)
            self.assertIn("PASSED", md)

    def test_sphinx_docstrings_and_rationale_comments_not_flagged(self):
        doc_src = (
            "def send(req, timeout=None):\n"
            '    """\n'
            "    Send a prepared HTTP request.\n\n"
            "    :param req: Request object to dispatch.\n"
            "    :param timeout: Optional timeout in seconds.\n"
            "    :return: Response instance.\n"
            '    """\n'
            "    return _dispatch(req, timeout)\n"
        )
        self.assertEqual(check_bloat_docstring(Path("api.py"), doc_src, ast.parse(doc_src)), [])

        comment_src = (
            "#: Sphinx attribute documentation.\n"
            "response_class = Response\n"
            "# Must ensure server_name is populated before building URL.\n"
            "server_name = cfg['SERVER_NAME']\n"
        )
        self.assertEqual(check_captain_comment(Path("api.py"), comment_src, None), [])

    def test_malformed_control_chars_do_not_crash_tokenizer(self):
        bad_src = "x = 1\n\x1b[31m# TODO: implement\n"
        self.assertEqual(check_ai_cliche(Path("bad.py"), bad_src, None), [])
        self.assertEqual(check_captain_comment(Path("bad.py"), bad_src, None), [])
        self.assertEqual(check_emoji_slop(Path("bad.py"), bad_src, None), [])

    def test_github_action_outputs_and_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            code_dir = root / "repo"
            code_dir.mkdir()
            (code_dir / "clean.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
            out_file = root / "gh_output.txt"
            sum_file = root / "gh_summary.md"
            svg_file = root / "action_card.svg"

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "slopcheck.github_action",
                    "--path",
                    str(code_dir),
                    "--max-score",
                    "0",
                    "--comment-pr",
                    "false",
                    "--svg-path",
                    str(svg_file),
                ],
                env={
                    **os.environ,
                    "GITHUB_OUTPUT": str(out_file),
                    "GITHUB_STEP_SUMMARY": str(sum_file),
                },
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Slop Score: 0%", proc.stdout)
            self.assertIn("score=0", out_file.read_text(encoding="utf-8"))
            self.assertIn("PASSED", sum_file.read_text(encoding="utf-8"))
            ET.fromstring(svg_file.read_text(encoding="utf-8"))

    def test_scan_python_matches_individual_rules(self):
        sample = (
            "# initialize client\n"
            "init_client()\n"
            "def f(a):\n"
            "    return g(a)\n"
            "try:\n"
            "    run()\n"
            "except Exception:\n"
            "    pass\n"
        )
        p = Path("parity.py")
        tree = ast.parse(sample)
        single = sorted(scan_python(p, sample, tree), key=lambda i: (i.line, i.rule))
        combined = []
        for fn in ALL_RULES:
            combined.extend(fn(p, sample, tree))
        combined.sort(key=lambda i: (i.line, i.rule))
        self.assertEqual(single, combined)


if __name__ == "__main__":
    unittest.main()
