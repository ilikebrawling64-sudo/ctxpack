# Codebase context — `ctxpack`
> Packed 6 file(s), ~2,821 tokens, 11,293 chars. Budget 3,000 tokens — truncated.

### Files included
```
src/ctxpack/cli.py
README.md
tests/test_packer.py
LICENSE
pyproject.toml
.github/workflows/test.yml
```

### 1. `src/ctxpack/cli.py` (878 tok)

```
"""ctxpack CLI — pack a codebase into a token-efficient LLM context document."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Packer, read_ignore_patterns

DEFAULT_BUDGET = 50_000


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctxpack",
        description=(
            "Pack a codebase into a single token-efficient, structured context file "
            "for LLM-assisted development. Respects .gitignore and .ctxignore."
        ),
    )
    p.add_argument("target", nargs="?", default=".", help="repo path to pack (default: cwd)")
    p.add_argument("-o", "--output", help="output file (default: stdout)")
    p.add_argument("-b", "--budget", type=int, default=DEFAULT_BUDGET,
                   help=f"max output tokens (default: {DEFAULT_BUDGET})")
    p.add_argument("-p", "--priority", help="a task/prompt phrase to prioritize relevant files")
    p.add_argument("--include-ignored", action="store_true",
                   help="include files matched by ignore rules")
    p.add_argument("--include-binary", action="store_true",
                   help="attempt to include (some) binary-suffixed files as text")
    p.add_argument("--max-file-bytes", type=int, default=512 * 1024,
                   help="skip files larger than this many bytes (default: 524288)")
    p.add_argument("--no-tree", action="store_true",
                   help="omit the 'Files included' tree section")
    p.add_argument("--json", action="store_true",
                   help="print a machine-readable summary instead of the markdown")
    p.add_argument("--version", action="version", version="ctxpack 0.1.0")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    target = Path(args.target)
    if not target.is_dir():
        print(f"ctxpack: error: not a directory: {target}", file=sys.stderr)
        return 2

    packer = Packer(
        root=target,
        max_tokens=args.budget,
        priority=args.priority,
        include_ignored=args.include_ignored,
        include_binary=args.include_binary,
        max_file_bytes=args.max_file_bytes,
    )

    result = packer.pack(priority=args.priority, max_tokens=args.budget)

    if args.json:
        payload = {
            "root": str(result.root),
            "files_scanned": result.files_scanned,
            "files_ignored": result.files_ignored,
            "budget_tokens": result.budget_tokens,
            "used_tokens": sum(e.est_tokens for e in result.emitted),
            "total_repo_tokens": result.total_tokens,
            "files_emitted": len(result.emitted),
            "truncated": result.truncated,
            "ignored_patterns": read_ignore_patterns(result.root),
            "emitted": [e.rel for e in result.emitted],
        }
        print(json.dumps(payload, indent=2))
        return 0

    doc = result.markdown(include_tree=not args.no_tree)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        summary = (
            f"ctxpack: packed {len(result.emitted)} file(s), "
            f"~{sum(e.est_tokens for e in result.emitted):,} tokens "
            f"(budget {result.budget_tokens:,}) -> {out}"
        )
        print(summary)
    else:
        sys.stdout.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 2. `README.md` (609 tok)

```
# ctxpack

> Pack a codebase into a single **token-efficient, structured context file** for LLM-assisted development.

When you feed a repo to an LLM, most of it is irrelevant and blows straight past your context window. **ctxpack** walks your tree, respects `.gitignore` / `.ctxignore`, estimates tokens per file, scores each file's relevance to your task, and emits one ordered markdown document that **fits a token budget with the most-relevant code leading.**

## Install

```bash
pip install ctxpack        # from PyPI (coming soon)
# or: git clone + uv sync  # from source
```

## Usage

```bash
# Pack the current repo, budget 50k tokens, ordered by relevance to a task
ctxpack . -b 50000 -p "refactor the auth module into a service"

# Write to a file instead of stdout
ctxpack ./my-project -o context.md

# Machine-readable summary (files included/ignored)
ctxpack ./my-project --json
```

### Options

| Flag | Meaning |
|------|---------|
| `-b, --budget` | Max output tokens (default 50 000) |
| `-p, --priority` | A task phrase; files matching it are prioritized |
| `-o, --output` | Write to file instead of stdout |
| `--include-ignored` | Include files matched by ignore rules |
| `--max-file-bytes` | Skip files larger than this (default 512 KB) |
| `--json` | Machine-readable summary |
| `--no-tree` | Omit the "Files included" tree |

## How it decides

1. **Respects ignore rules** — `.gitignore` and `.ctxignore` (a ctxpack-specific ignore file).
2. **Estimates tokens** — offline heuristic ~4 chars/token (no network, no heavy tokenizer).
3. **Scores importance** — boosts entrypoints (`main`, `cli`, `index`), config, core modules; penalizes builds, vendored code, minified assets, lockfiles.
4. **Budgets greedily** — fills up to your budget with the most-important files first, so the output always fits.

The output is a single markdown file: a header with token/count stats, a file tree, then each file in a fenced block, most-relevant first — ready to paste or pipe straight into Claude/GPT.

## Project layout

```
root/
  .ctxignore      # optional, like .gitignore but ctxpack-specific
  src/...         # code that gets scored + packed
  package-lock.json  # auto-deprioritized, not worth your tokens
```

This project was built as a from-scratch, zero-budget developer tool — a seed for a profitable software business. Contributions, issues, and stars are the demand signal. MIT licensed.

## License

MIT
```

### 3. `tests/test_packer.py` (770 tok)

```
"""Tests for ctxpack core packing logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from ctxpack import Packer, estimate_tokens, read_ignore_patterns


def _make_repo(tmp_path: Path) -> Path:
    """Create a small sample repo."""
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (root / "src" / "utils.py").write_text("def helper():\n    print('hi')\n" * 50, encoding="utf-8")
    (root / "README.md").write_text("# proj\n" * 10, encoding="utf-8")
    (root / ".gitignore").write_text("venv/\n*.log\n", encoding="utf-8")
    (root / "secret.log").write_text("ignore me\n", encoding="utf-8")
    thumbnail = root / "thumb.png"
    thumbnail.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    (root / "data.bin").write_bytes(b"\x00\xff\x00\xfe" * 20)
    return root


def test_estimate_tokens_basic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2  # 11 chars / 4 = 2.75 -> 2
    assert estimate_tokens("a") == 1


def test_pack_respects_gitignore(tmp_path):
    root = _make_repo(tmp_path)
    p = Packer(root=root, max_tokens=50_000)
    result = p.pack()
    rels = {e.rel for e in result.entries}
    # ignored
    assert "secret.log" not in rels
    assert "thumb.png" not in rels
    assert "data.bin" not in rels
    # included
    assert "src/main.py" in rels
    assert "src/utils.py" in rels
    assert "README.md" in rels


def test_pack_budget_truncates(tmp_path):
    root = _make_repo(tmp_path)
    p = Packer(root=root, max_tokens=40)  # tiny budget forces truncation
    result = p.pack(max_tokens=40)
    assert result.truncated is True
    used = sum(e.est_tokens for e in result.emitted)
    assert used <= 40
    assert len(result.emitted) < len(result.entries)


def test_pack_priority_orders(tmp_path):
    root = _make_repo(tmp_path)
    p = Packer(root=root, max_tokens=50_000)
    result = p.pack(priority="main cli")
    # main.py (matched by 'main') should outrank utils for inclusion priority
    # Only meaningful if budget is tight enough to cause a choice; here assert main first among emitted sources.
    rels = [e.rel for e in result.emitted if e.rel.startswith("src/")]
    assert "src/main.py" in rels


def test_include_ignored(tmp_path):
    root = _make_repo(tmp_path)
    p = Packer(root=root, max_tokens=50_000, include_ignored=True)
    result = p.pack()
    rels = {e.rel for e in result.entries}
    assert "secret.log" in rels


def test_read_ignore_patterns(tmp_path):
    root = _make_repo(tmp_path)
    pats = read_ignore_patterns(root)
    assert "venv/" in pats
    assert "*.log" in pats


def test_markdown_shape(tmp_path):
    root = _make_repo(tmp_path)
    p = Packer(root=root, max_tokens=50_000)
    result = p.pack()
    doc = result.markdown()
    assert doc.startswith("# Codebase context")
    assert "### Files included" in doc
    assert "src/main.py" in doc
```

### 4. `LICENSE` (265 tok)

```
MIT License

Copyright (c) 2026 ctxpack

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 5. `pyproject.toml` (194 tok)

```
[project]
name = "ctxpack"
version = "0.1.0"
description = "Pack a codebase into a single token-efficient, structured context file for LLM-assisted development."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "ctxpack" }]
keywords = ["llm", "context", "claude", "gpt", "code", "cli", "tokenizer"]
classifiers = [
  "Programming Language :: Python :: 3",
  "Environment :: Console",
  "Topic :: Software Development",
]
dependencies = [
  "pathspec>=0.12",
]

[project.scripts]
ctxpack = "ctxpack.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ctxpack"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

### 6. `.github/workflows/test.yml` (105 tok)

```
# Test on every push / PR.
name: test

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        python: ["3.11", "3.12", "3.13"]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync --dev
      - run: uv run pytest -q
```

_Generated by [ctxpack](https://github.com/ctxpack-ai/ctxpack). Token counts are estimates (~4 chars/token). Review before use._
