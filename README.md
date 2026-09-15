# ctxpack

> Pack a codebase into a single **token-efficient, structured context file** for LLM-assisted development.

When you feed a repo to an LLM, most of it is irrelevant and blows straight past your context window. **ctxpack** walks your tree, respects `.gitignore` / `.ctxignore`, estimates tokens per file, scores each file's relevance to your task, and emits one ordered markdown document that **fits a token budget with the most-relevant code leading.**

## Install

```bash
pip install ctxpack        # from PyPI
# or: git clone + uv sync  # from source
```

## See it work

[`examples/example-context.md`](examples/example-context.md) is a real ctxpack output — 6 files packed at a 3,000-token budget, most-relevant code first. It starts like this:

```markdown
# Codebase context — `proj`

> Packed 6 file(s), ~2,821 tokens, 11,293 chars. Budget 3,000 tokens — truncated.

### Files included
...
```

That's the whole promise in one screen: a budget that **always fits**, with the important code kept and the noise dropped.

## Usage

```bash
# Pack the current repo, budget 50k tokens, ordered by relevance to a task
ctxpack . -b 50000 -p "refactor the auth module into a service"

# Write to a file instead of stdout
ctxpack ./my-project -o context.md

# Force-include a specific file that ignore rules would drop
ctxpack . --include 'deployment/prod.yaml'

# Carve out a huge dir before a deadline
ctxpack . --exclude 'tests/'

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
| `--include GLOB` | Force-include files matching GLOB, overriding ignore rules (repeatable) |
| `--exclude GLOB` | Also ignore files matching GLOB, in addition to ignore rules (repeatable) |
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