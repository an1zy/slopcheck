---
name: slopcheck
description: Audit your own generated code changes with slopcheck (--diff) before finishing a task so no AI slop, silent catches, bloat docstrings, or leftover debug prints enter the repository.
---

# slopcheck Agent Skill

Run `slopcheck` against your uncommitted diff before handing code back to the user.

## Quick Verification Command

```bash
uvx sloplinter . --diff --max-score 10
```

If `slopcheck` is already installed locally:

```bash
slopcheck . --diff --max-score 10
```

## When to Run

1. After finishing code edits in Python, JS/TS, Rust, C/C++, C#, Go, or Java.
2. Before opening a pull request (`slopcheck . --base origin/main --max-score 10`).
3. When refactoring AI-generated modules (`slopcheck path/to/dir --json`).

## Rules to Fix Before Reporting Done

- `silent-except` / `silent-catch`: replace bare `pass`, `...`, or empty `catch {}` with real handling or explicit re-raise.
- `ai-cliche`: implement unfinished logic instead of leaving placeholder comments.
- `emoji-slop`: remove decorative emojis from source comments and log/print calls.
- `deep-nesting`: extract helpers or use early returns so nesting stays below 4 levels.
- `bloat-docstring`: keep docstrings concise rather than longer than the function body.
- `captain-comment`: replace comments that restate identifiers with comments explaining non-obvious why.
- `redundant-boolean` / `useless-wrapper` / `debug-print` / `wildcard-import`: simplify directly.
