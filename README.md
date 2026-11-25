<div align="center">

# slopcheck

**Fast CLI linter, GitHub Action & Agent Skill that catches AI-generated code slop and enforces a Slop Score in CI.**

[![CI](https://github.com/an1zy/slopcheck/actions/workflows/ci.yml/badge.svg)](https://github.com/an1zy/slopcheck/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sloplinter?style=flat-square&color=3775A9)](https://pypi.org/project/sloplinter/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![Agent Skill](https://img.shields.io/badge/agent_skill-slopcheck-purple.svg?style=flat-square)](skills/slopcheck/SKILL.md)
[![Slop Score: 0%](https://img.shields.io/badge/slop_score-0%25_clean-brightgreen.svg?style=flat-square)](assets/scorecard-clean.svg)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg?style=flat-square)](LICENSE)

**English** · [Русский](README.ru.md)

<br/>

<img src="assets/demo.svg" alt="slopcheck terminal output" width="840" />

</div>

---

## Why slopcheck?

AI coding assistants ship fast, but unreviewed generations leave unmistakable artifacts: empty `except Exception: pass` / `catch (e) {}` blocks, leftover `TODO: implement` placeholders, bloated docstrings longer than a one-line wrapper, decorative emojis inside comments and logs, and tautological `# initialize database` comments.

`slopcheck` runs deep Python AST + tokenizer analysis alongside a zero-dependency polyglot scanner for **JS/TS, Rust, C/C++, C#, Go, and Java**, outputting a weighted **Slop Score (0–100%)** in milliseconds.

---

## Quick Start

Install via pip:

```bash
pip install sloplinter
```

Or run ephemerally with `uvx`:

```bash
uvx sloplinter .
```

Install as an **Agent Skill** so Claude Code, Cursor, or Codex self-audit their own diffs before finishing:

```bash
npx skills add an1zy/slopcheck
```

---

## CLI Usage

```bash
# Scan a repository or file
slopcheck .

# Scan only uncommitted changes (or PR branch diff against origin/main)
slopcheck . --diff
slopcheck . --base origin/main --max-score 10
slopcheck . --staged

# Enforce a quality gate in CI (exit code 1 when score exceeds threshold)
slopcheck . --max-score 20

# Export a dark-neon SVG scorecard or JSON report
slopcheck . --svg assets/scorecard.svg --title "owner/repo"
slopcheck . --json

# Print a shields.io markdown badge or compact summary
slopcheck . --badge
slopcheck . --summary --exclude vendor --exclude migrations
```

<details>
<summary>Preview generated SVG scorecard (--svg)</summary>

<p align="center">
  <img src="assets/scorecard-clean.svg" alt="slopcheck SVG scorecard" width="820" />
</p>

</details>

---

## GitHub Action (PR Gate + Sticky Comment)

Drop this into `.github/workflows/slopcheck.yml` to scan only newly added/modified lines on every pull request and post an automatic Slop Score report:

```yaml
name: Slopcheck

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  slopcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: an1zy/slopcheck@v1
        with:
          max-score: 20
          diff-only: true
          comment-pr: true
```

<details>
<summary>Action inputs &amp; outputs</summary>

| Input | Default | Description |
| :--- | :---: | :--- |
| `path` | `.` | Directory or file to scan |
| `max-score` | `20` | Maximum allowed Slop Score (0–100) |
| `diff-only` | `false` | Scan only lines modified against `base_ref` on PRs |
| `comment-pr` | `true` | Create or update a sticky Slop Score comment on PRs |
| `fail-on-exceed` | `true` | Fail the step when score exceeds `max-score` |
| `exclude` | `""` | Comma-separated directory or prefix exclusions |
| `svg-path` | `""` | Optional output path for a dark-neon SVG scorecard |

Outputs: `score`, `verdict`, `badge-url`, `issues-count`.

</details>

---

## Empirical Benchmark (55 Repos · 3.83M Lines)

We scanned **55 popular public repositories** (`18,138` files, `3,834,720` lines, `13,333` findings) across three cohorts to calibrate `slopcheck` heuristics against real-world codebases:

<p align="center">
  <img src="assets/benchmark.svg" alt="slopcheck empirical benchmark across 55 repos" width="840" />
</p>

| Cohort | Repos | Mean Score | Median | Clean (`<=10%`) | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Classic Pre-AI OSS** (`flask`, `ripgrep`, `serde`, `express`, `hono`, ...) | 18 | **8.0%** | 8.5% | 66.7% | Zero repos above 15%; minimal noise |
| **2025 AI / MCP / Agent Boom** | 19 | **15.7%** | 12.0% | 47.4% | **~2x higher** mean slop score; 86.9% of all `emoji-slop` hits |
| **2026 Trending Repos** | 18 | **8.3%** | 7.0% | 72.2% | Heavily Rust/TS CLI wave (`claw-code` 2%, `rtk` 2%, `agent-browser` 3%) |

Language breakdown in the sample: **Rust** (`3.4%` avg across 8 repos) and **TypeScript** (`5.5%` avg across 11 repos) scored markedly cleaner than **Python** (`14.7%` avg across 32 repos). Even in the AI cohort, engineered tools like `anthropics/claude-code` (`1%`) and `ChromeDevTools/chrome-devtools-mcp` (`4%`) scored `CLEAN`, while rushed community skill/wrapper repos spiked to `23%–59%`.

---

## Scoring & Rules

Score thresholds:
- `0–10%`: `CLEAN`
- `11–35%`: `SUSPICIOUS`
- `36–65%`: `VIBE-CODED`
- `66–100%`: `PURE SLOP`

| Rule | Weight | Languages | What it catches |
| :--- | :---: | :--- | :--- |
| `security-slop` | 15 | Python, JS/TS | `verify=False`, dynamic `shell=True`, `eval`/`exec`, CORS `*`+creds, hardcoded tokens |
| `silent-except` | 15 | Python | Catch handler containing only `pass`, `...`, or lone `print` |
| `silent-catch` | 15 | JS/TS, Rust, C/C++, C#, Go, Java | Empty or suppressed catch blocks |
| `ai-cliche` | 12 | All supported | Markers like `TODO: implement`, `placeholder`, `in a real-world`, `for brevity` |
| `duplicate-helper` | 12 | Python | Cross-file normalized AST clone reimplementing an existing helper |
| `test-theatre` | 12 | Python, JS/TS | Tests with zero assertions or constant tautologies (`assert True`, `expect(true).toBe(true)`) |
| `emoji-slop` | 10 | All supported | Decorative emojis in comments and log/print statements |
| `deep-nesting` | 10 | Python | Control structure nesting depth >= 4 (ignoring `elif`) |
| `debug-print` | 8 | All supported | Print calls with debug prefixes (`debug`, `here`, `test`, `asdf`, etc.) |
| `wildcard-import` | 8 | Python | `from ... import *` imports |
| `bloat-docstring` | 8 | Python | Unstructured docstrings larger than the actual function body |
| `useless-wrapper` | 7 | Python | Thin wrappers forwarding exact arguments without modification |
| `captain-comment` | 6 | All supported | Short tautological comments echoing identifiers on the next line |
| `redundant-boolean` | 6 | Python | Comparisons with `True`/`False` or `if/else` returning boolean literals |

---

## License

MIT © 2026 [an1zy](https://github.com/an1zy)
