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
    p.add_argument("--include", action="append", metavar="GLOB", default=[],
                   help="force-include files matching GLOB, overriding ignore rules (repeatable)")
    p.add_argument("--exclude", action="append", metavar="GLOB", default=[],
                   help="also ignore files matching GLOB, in addition to ignore rules (repeatable)")
    p.add_argument("--max-file-bytes", type=int, default=512 * 1024,
                   help="skip files larger than this many bytes (default: 524288)")
    p.add_argument("--no-tree", action="store_true",
                   help="omit the 'Files included' tree section")
    p.add_argument("--json", action="store_true",
                   help="print a machine-readable summary instead of the markdown")
    p.add_argument("--version", action="version", version="ctxpack 0.2.0")
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
        include_globs=tuple(args.include),
        exclude_globs=tuple(args.exclude),
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