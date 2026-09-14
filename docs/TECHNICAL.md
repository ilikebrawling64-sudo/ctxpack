# ctxpack — technical notes

## Architecture
`ctxpack` is a dependency-light Python CLI. Two layers:

### 1. Discovery + scoring (`src/ctxpack/__init__.py`)
- **Ignore handling**: merges built-in defaults (`.venv`, `node_modules`, `.git`,
  build output, locks, editor/os files) with the repo's `.gitignore` / `.ctxignore`
  via `pathspec`.
- **Token estimation**: offline heuristic ~4 chars/token (no tokenizer download).
  Deliberate: fast, offline, deterministic. Trade-off: not byte-exact with any
  single model's BPE; labeled as an estimate.
- **Importance scoring** `_score()`:
  - +boost for entrypoints/config/core substrings (`__init__`, `main`, `cli`,
    `index`, `router`, `config`, `settings`, `schema`, `app`, ...)
  - *penalty for generated/vendor/minified/lock-ish paths
  - + gentle preference for larger, substantive files
  - + strong boost (x1.6) when the `--priority` phrase words appear in the path
- **Budgeting** `entries_fit_budget()`: greedy fill of importance-sorted files up to
  the token budget — always fits, most relevant first.

### 2. Rendering (`PackResult.markdown()` + `cli.py`)
Emits one markdown doc: stats header (files, tokens, chars, budget/truncation),
a file tree, then each included file in a fenced block, most-relevant first.

## Design decisions
- **relevance-first ordering** is the differentiation vs repo2txt/repomix: budget is
  about *what you're about to do*, not just what fits.
- **Single responsibility, few deps**: only `pathspec`. Easy audit, easy install.
- **Offline**: no tokenizer download, no network at pack time.

## Future / monetization candidates
- `--language` tokenizer-specific estimates (importable, optional heavy tokenizer).
- **Pro** heuristics / per-language importance; `--include`/`--exclude` globs;
  multiple-format output (XML like repomix, JSONL).
- Commercial use license / sponsorship as the OSS grows.

## Testing
- 7 unit tests (`tests/`) cover: token estimation, gitignore respect, built-in
  ignores, budget truncation, priority ordering, ignore-pattern reporting,
  markdown shape.
- CI: GitHub Actions on Python 3.11/3.12/3.13.