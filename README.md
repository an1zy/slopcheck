# slopcheck

![Slop Score](https://img.shields.io/badge/slop_score-0%25-brightgreen)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)

Fast CLI linter that detects AI-generated code slop and calculates a Slop Score (deep AST analysis for Python + polyglot scanner for JS/TS, Rust, C/C++, C#, Go, Java).

<!-- DEMO_SCREENSHOT -->

## Install

```bash
pip install sloplinter
```

Or run ephemerally with `uvx`:

```bash
uvx sloplinter .
```

## Usage

Run a scan against the current repository or a specific directory:

```bash
slopcheck .
```

Enforce quality gates in CI (exit code 1 if score exceeds threshold):

```bash
slopcheck . --max-score 20
```

Generate a Markdown badge for your repository `README.md`:

```bash
slopcheck . --badge
```

Score thresholds:
- 0-10%: `CLEAN`
- 11-35%: `SUSPICIOUS`
- 36-65%: `VIBE-CODED`
- 66-100%: `PURE SLOP`

## Rules

| Rule | Weight | Languages | What it catches |
| :--- | :---: | :--- | :--- |
| `silent-except` | 15 | Python | Catch handler containing only `pass`, `...`, or lone `print` |
| `silent-catch` | 15 | JS/TS, C++, C#, Java | Empty or suppressed catch blocks |
| `ai-cliche` | 12 | All supported | Markers like `TODO: implement`, `placeholder`, `in a real-world`, `for brevity` |
| `emoji-slop` | 10 | All supported | Decorative emojis in comments and log/print statements |
| `deep-nesting` | 10 | Python | Control structure nesting depth >= 4 (ignoring `elif`) |
| `debug-print` | 8 | All supported | Print calls with debug prefixes (`debug`, `here`, `test`, `asdf`, etc.) |
| `wildcard-import` | 8 | Python | `from ... import *` imports |
| `bloat-docstring` | 8 | Python | Docstrings larger than the actual function body |
| `useless-wrapper` | 7 | Python | Thin wrappers forwarding exact arguments without modification |
| `captain-comment` | 6 | All supported | Standalone comment echoing identifiers on the line directly below |
| `redundant-boolean` | 6 | Python | Comparisons with `True`/`False` or `if/else` returning boolean literals |

## License

MIT
