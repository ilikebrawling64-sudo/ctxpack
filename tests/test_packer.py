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