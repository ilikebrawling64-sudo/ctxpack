# Changelog

All notable changes to ctxpack are documented here.

## [0.1.0] - 2026-09-14
### Added
- Gitignore/.ctxignore-aware file discovery (`pathspec`)
- Built-in default ignore patterns (`.venv`, `node_modules`, `.git`, build output, locks, editor/os files) merged with repo ignore files
- Offline token estimation (~4 chars/token)
- Task-relevance importance scoring (`-p` priority phrase; boosts entrypoints/config/core; penalizes vendored/minified/lockfiles)
- Greedy token-budget packing — output always fits, most-relevant files first
- Single-file markdown output with stats header, file tree, and fenced codeblocks
- `--json` machine-readable summary
- Unit tests (7) + GitHub Actions CI on Python 3.11/3.12/3.13