<div align="center">

# slopcheck.
### *Быстрый AST и полиглот-линтер, Semantic PR Gate и GitHub Action для поиска ИИ-слопа в коде*

[![CI](https://github.com/an1zy/slopcheck/actions/workflows/ci.yml/badge.svg?style=for-the-badge)](https://github.com/an1zy/slopcheck/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sloplinter?style=for-the-badge&color=18181b)](https://pypi.org/project/sloplinter/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-18181b.svg?style=for-the-badge)](https://www.python.org/downloads/)
[![Agent Skill](https://img.shields.io/badge/agent_skill-slopcheck-18181b.svg?style=for-the-badge)](skills/slopcheck/SKILL.md)
[![Slop Score: 0%](https://img.shields.io/badge/slop_score-0%25_clean-18181b.svg?style=for-the-badge)](assets/scorecard-clean.svg)
[![License: MIT](https://img.shields.io/badge/license-MIT-18181b.svg?style=for-the-badge)](LICENSE)

[English](README.md) · **Русский**

<br/>

<img src="assets/demo.svg" alt="Демо вывода slopcheck" width="840" />

</div>

---

Быстрый статический линтер под типичные артефакты LLM-правок без ревью: пустые `except Exception: pass` / `catch (e) {}`, заглушки `TODO: implement`, раздутые докстринги, дублирующиеся хелперы между файлами, тесты без ассертов и костыли вроде `verify=False` или `shell=True`.

Работает на Python AST + токенизаторе плюс полиглот-сканере для **JS/TS, Rust, C/C++, C#, Go и Java**, выставляя `0–100%` Slop Score локально или в CI.

## Быстрый старт

```bash
pip install sloplinter
# или без установки:
uvx sloplinter .
```

Установка как Agent Skill:

```bash
npx skills add an1zy/slopcheck
```

## CLI

```bash
# Скан папки или файла
slopcheck .

# Проверка только изменённых строк (diff, ветка, staged)
slopcheck . --diff
slopcheck . --base origin/main --max-score 10
slopcheck . --staged

# Порог для CI
slopcheck . --max-score 20

# Монохромная SVG-карточка и JSON-отчёт
slopcheck . --svg assets/scorecard.svg --title "owner/repo"
slopcheck . --json
slopcheck . --badge
slopcheck . --summary --exclude vendor --exclude migrations
```

## GitHub Action (`an1zy/slopcheck@v1`)

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

## Бенчмарк (55 репозиториев · 3.83M строк)

Прогон по **55 публичным репозиториям** (`18,138` файлов, `3,834,720` строк, `13,333` срабатывания):

<p align="center">
  <img src="assets/benchmark.svg" alt="Бенчмарк slopcheck по 55 репозиториям" width="840" />
</p>

| Когорта | Репозиториев | Средний балл | Медиана | Чистых (`<=10%`) | Наблюдение |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Классический OSS до ИИ-бума** | 18 | **8.0%** | 8.5% | 66.7% | Ни одного выше 15% |
| **Бум AI / MCP / агентов 2025** | 19 | **15.7%** | 12.0% | 47.4% | Почти в 2x выше; 86.9% всех `emoji-slop` |
| **Трендовые репо 2026** | 18 | **8.3%** | 7.0% | 72.2% | Сдвиг в сторону Rust/TS CLI (`claw-code` 2%, `rtk` 2%) |

## Пороги и правила

Пороги: `0–10%` `CLEAN` · `11–35%` `SUSPICIOUS` · `36–65%` `VIBE-CODED` · `66–100%` `PURE SLOP`.

| Правило | Вес | Языки | Что ловит |
| :--- | :---: | :--- | :--- |
| `security-slop` | 15 | Python, JS/TS | `verify=False`, динамический `shell=True`, `eval`/`exec`, CORS `*`+creds, зашитые токены |
| `silent-except` | 15 | Python | Обработчик исключений с `pass`, `...` или одиночным `print` |
| `silent-catch` | 15 | JS/TS, Rust, C/C++, C#, Go, Java | Пустые блоки `catch` |
| `ai-cliche` | 12 | Все | Маркеры вроде `TODO: implement`, `placeholder`, `for brevity` |
| `duplicate-helper` | 12 | Python | Кросс-файловый AST-клон существующего хелпера в репозитории |
| `test-theatre` | 12 | Python, JS/TS | Тесты без проверок или с тавтологиями (`assert True`, `expect(true).toBe(true)`) |
| `emoji-slop` | 10 | Все | Декоративные эмодзи в комментариях и логах |
| `deep-nesting` | 10 | Python | Вложенность конструкций >= 4 (игнорируя `elif`) |
| `debug-print` | 8 | Все | Отладочный вывод (`debug`, `here`, `test`, `asdf` и др.) |
| `wildcard-import` | 8 | Python | `from ... import *` |
| `bloat-docstring` | 8 | Python | Докстринг длиннее тела функции (кроме Sphinx/doctest) |
| `useless-wrapper` | 7 | Python | Пустые функции-обёртки, просто пробрасывающие аргументы |
| `captain-comment` | 6 | Все | Короткие комментарии, повторяющие код строкой ниже |
| `redundant-boolean` | 6 | Python | Лишние `== True` / `if ...: return True else: return False` |

## Лицензия

MIT © 2026 [an1zy](https://github.com/an1zy)
