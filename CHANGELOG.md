# Changelog

## 0.3.0 (2026-11-25)

### Added
- **Semantic PR Gate (`duplicate-helper`, `test-theatre`, `security-slop`):**
  - `duplicate-helper`: cross-file normalized AST structural fingerprinting detects newly added functions that reimplement existing helpers across the repository (works in `--diff` mode too).
  - `test-theatre`: detects Python `test_*` functions without assertions and tautological assertions (`assert True`, `expect(true).toBe(true)`).
  - `security-slop`: catches unreviewed AI security shortcuts (`verify=False`, dynamic `subprocess(..., shell=True)`, dynamic `eval`/`exec`, `allow_origins=["*"]` with `allow_credentials=True`, hardcoded API tokens).
- `--no-semantic` flag to run only fast syntactic/AST style heuristics.

## 0.2.0 (2026-11-25)

### Added
- `--diff`, `--base <ref>`, and `--staged` modes to scan only added/modified lines in git diffs and pull requests.
- `--svg <path>` and `--title <name>` to generate standalone dark-neon SVG scorecards.
- `--json` structured output for CI pipelines and automation.
- `--exclude`, `--summary`, `--top`, and `--version` CLI flags.
- Composite GitHub Action (`action.yml`) with PR sticky comments, workflow job summaries, and action outputs.
- Agent Skill manifest (`skills/slopcheck/SKILL.md`) for coding assistants (`npx skills add an1zy/slopcheck`).

### Improved
- Reduced false positives on Sphinx/reST documentation docstrings, doctests, `#:` doc comments, and rationale comments.
- Guarded Python tokenizer against malformed control characters (`U+001B`) and suppressed target `SyntaxWarning` noise.
- Prevented Rust lifetimes (`'a`) from swallowing subsequent comments in the polyglot scanner.
- Expanded ignored cache/build directories and added a 512 KB file size guard.

## 0.1.0

- Initial release with Python AST rules, polyglot scanner, `--max-score`, and `--badge`.
