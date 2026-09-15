"""ctxpack — pack a codebase into a single token-efficient, structured context file
for LLM-assisted development.

The core idea: instead of pasting a whole repo (most of it irrelevant, blowing past
context limits), ctxpack walks the tree, respects .gitignore/.ctxignore, estimates
tokens per file, scores each file's *relevance to a task*, and emits a single ordered
markdown document that fits a token budget with the most-relevant code leading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import pathspec

__all__ = [
    "Packer",
    "PackResult",
    "FileEntry",
    "estimate_tokens",
    "read_ignore_patterns",
    "IMPORTANCE_FOOTNOTE",
]

# Rough token estimate: for code, ~4 chars/token tends toward the safe (high)
# side on many tokenizers; guarded against pathological strings with a floor.
CHARS_PER_TOKEN = 4.0
MIN_TOKENS = 1

# Heuristic importance hints: substrings of a file's relative path that signal
# entrypoints, config, or central logic. Lower cost wins ordering boosts.
IMPORTANT_SUBSTRINGS = (
    "__init__", "main", "cli", "index", "router", "config", "settings",
    "commands", "handlers", "core", "schema", "app", "server", "store",
)

# Substrings that signal generated/lock/junk content worth deprioritizing.
DEPRIORITIZE_SUBSTRINGS = (
    "node_modules", ".git/", "lockfile", "package-lock", "yarn.lock",
    "poetry.lock", "requirements.lock", "vendor/", "dist/", "build/",
    ".min.js", ".min.css", "chunk", "snapshot", "generated", "pb.go",
)

# File extensions considered binary / not useful as text context.
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".woff", ".woff2", ".ttf",
    ".otf", ".mp3", ".mp4", ".mov", ".wav", ".ogg", ".exe", ".dll", ".so",
    ".dylib", ".class", ".jar", ".pyc", ".pyo", ".bin", ".dat", ".db", ".sqlite",
    ".lock", ".map", ".woff2", ".eot",
}

# Extensions that are text but rarely useful as context (still listed, not packed).
# Kept minimal to avoid false positives; big ones are handled by deprioritize logic.

IGNORE_FILE_NAMES = (".gitignore", ".ctxignore")

# Built-in defaults always applied (merged with repo ignore files), so the tool
# stays useful on repos with no .gitignore.
DEFAULT_IGNORE_PATTERNS = (
    ".git/", ".venv/", "venv/", "env/", ".env",  # vcs + virtualenvs
    "node_modules/", "bower_components/", "vendor/",  # deps
    "__pycache__/", "*.pyc", "*.pyo",  # python bytecode
    "dist/", "build/", "target/", ".next/", ".nuxt/",  # build output
    "*.lock", "package-lock.json", "yarn.lock", "poetry.lock",  # locks
    ".idea/", ".vscode/", ".DS_Store",  # editor/os
    "coverage/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",  # tooling
    "*.egg-info/", ".eggs/",
)


@dataclass
class FileEntry:
    """A single file selected for inclusion."""

    path: Path  # absolute path
    rel: str  # path relative to the repo root, "/"-separated
    size_bytes: int
    est_tokens: int
    importance: float  # higher = more worth including
    content: str


@dataclass
class PackResult:
    """The output of a pack run."""

    root: Path
    entries: list[FileEntry] = field(default_factory=list)
    total_chars: int = 0
    total_tokens: int = 0
    files_scanned: int = 0
    files_ignored: int = 0
    budget_tokens: int | None = None
    truncated: bool = False
    emitted: list[FileEntry] = field(default_factory=list)

    def markdown(self, include_tree: bool = True, include_footnote: bool = True) -> str:
        """Render the pack as a single markdown document for LLM consumption."""
        parts: list[str] = []
        parts.append(f"# Codebase context — `{self.root.name}`")
        emitted_tokens = sum(e.est_tokens for e in self.emitted)
        parts.append(f"> Packed {len(self.emitted)} file(s), ~{emitted_tokens:,} tokens, "
                     f"{sum(len(e.content) for e in self.emitted):,} chars. "
                     + (f"Budget {self.budget_tokens:,} tokens — truncated." if self.truncated else "Within budget."))
        if include_tree and self.emitted:
            parts.append("")
            parts.append("### Files included")
            parts.append("```")
            for e in self.emitted:
                parts.append(e.rel)
            parts.append("```")
        parts.append("")
        for i, e in enumerate(self.emitted, 1):
            parts.append(f"### {i}. `{e.rel}` ({e.est_tokens:,} tok)")
            parts.append("")
            parts.append("```")
            parts.append(e.content.rstrip("\n"))
            parts.append("```")
            parts.append("")
        if include_footnote:
            parts.append(IMPORTANCE_FOOTNOTE)
        return "\n".join(parts).rstrip() + "\n"


@dataclass
class Packer:
    """Discover and pack files from a repository within a token budget."""

    root: Path
    max_tokens: int = 50_000
    priority: str | None = None  # a task/phrase to boost relevant files
    include_ignored: bool = False
    include_binary: bool = False
    max_file_bytes: int = 512 * 1024  # skip enormous files
    tokenizer_chars_per_token: float = CHARS_PER_TOKEN
    include_globs: tuple[str, ...] = ()  # force-include matching files (overrides ignores)
    exclude_globs: tuple[str, ...] = ()  # extra ignores beyond defaults + .gitignore/.ctxignore

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.files_scanned: int = 0
        self.files_ignored: int = 0
        self._spec = self._load_ignore_spec()

    # ---- ignore handling ----
    def _load_ignore_spec(self) -> pathspec.PathSpec:
        # Merge built-in defaults + repo ignore files, then apply user overrides.
        # `--include <glob>` is appended as a `!<glob>` negation AFTER everything,
        # so gitignore precedence lets "include" win over any ignore rule.
        lines: list[str] = list(DEFAULT_IGNORE_PATTERNS)
        for name in IGNORE_FILE_NAMES:
            f = self.root / name
            if f.is_file():
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for raw in text.splitlines():
                    line = raw.strip()
                    if line and not line.startswith("#"):
                        lines.append(line)
        for g in self.exclude_globs:
            lines.append(g)
        for g in self.include_globs:
            if not g.startswith("!"):
                lines.append(f"!{g}")
        return pathspec.PathSpec.from_lines("gitignore", lines)

    def _ignored(self, rel: str, is_dir: bool = False) -> bool:
        r = rel.replace("\\", "/")
        # `--include-ignored` is a blanket bypass (everything is kept).
        if self.include_ignored:
            return False
        if self._spec is None:
            return False
        # `--include <glob>` is already baked into `self._spec` as a `!<glob>`
        # negation after all ignore rules; pathspec gitignore semantics resolve
        # precedence so a forced-include path matches as "not ignored".
        if self._spec.match_file(r):
            return True
        if is_dir and self._spec.match_file(r + "/"):
            return True
        return False

    # ---- discovery ----
    def _iter_files(self) -> Iterator[Path]:
        """Yield candidate files under root, skipping ignored dirs/files eagerly."""
        for path in self.root.rglob("*"):
            try:
                rel = path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if path.is_dir():
                continue
            # Skip file system sync/OS noise.
            if any(part.startswith(".") and part not in {".github", ".ctxignore"} for part in path.parts):
                if ".git" in path.parts or ".gitignore" == path.name or ".ctxignore" == path.name:
                    continue
            if self._ignored(rel):
                self.files_ignored += 1
                continue
            yield path

    def scan(self) -> list[FileEntry]:
        """Walk the repo and produce FileEntry for every text, non-ignored file."""
        entries: list[FileEntry] = []
        for path in self._iter_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            if not path.is_file():
                continue
            if stat.st_size > self.max_file_bytes:
                self.files_ignored += 1
                continue
            ext = path.suffix.lower()
            if ext in BINARY_EXTENSIONS and not self.include_binary:
                self.files_ignored += 1
                continue
            rel = path.relative_to(self.root).as_posix()
            try:
                content = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError):
                # Fall back to replacement for genuinely weird-but-text files.
                continue
            if content == "" and path.name not in IGNORE_FILE_NAMES:
                # keep ignore files out of context unless substantial
                if stat.st_size == 0:
                    self.files_ignored += 1
                    continue
            self.files_scanned += 1
            est = estimate_tokens(content, self.tokenizer_chars_per_token)
            imp = self._score(rel, est)
            entries.append(
                FileEntry(
                    path=path,
                    rel=rel,
                    size_bytes=stat.st_size,
                    est_tokens=est,
                    importance=imp,
                    content=content,
                )
            )
        return entries

    def _score(self, rel: str, tokens: int) -> float:
        """Score a file's usefulness for context, 0..1+ (higher = better)."""
        low = rel.lower()
        score = 1.0
        # Boost entrypoints/config/core.
        for sub in IMPORTANT_SUBSTRINGS:
            if sub in low:
                score += 0.6
                break
        # Penalize generated/vendor/lock-ish.
        for sub in DEPRIORITIZE_SUBSTRINGS:
            if sub in low:
                score *= 0.15
                break
        # Gentle preference for larger files (more substance), capped.
        score += min(tokens / 800.0, 0.6)
        # Tiny files (readmes, dot-files) slightly downweighted unless core.
        if tokens < 20 and not any(s in low for s in IMPORTANT_SUBSTRINGS):
            score *= 0.8
        # Priority-relevant titles get a strong boost.
        if self.priority is not None and self.priority:
            words = [w for w in self.priority.lower().split() if len(w) > 2]
            if any(w in low for w in words):
                score *= 1.6
        return score

    def pack(
        self,
        priority: str | None = None,
        max_tokens: int | None = None,
    ) -> PackResult:
        """Select entries to fit the budget and return an ordered PackResult."""
        if priority is not None:
            self.priority = priority
        if max_tokens is not None:
            self.max_tokens = max_tokens

        entries = self.scan()
        # Sort: importance desc, then tokens asc (prefer packed relevance).
        entries.sort(key=lambda e: (-e.importance, e.est_tokens))

        budget = self.entries_fit_budget(entries, self.max_tokens)
        result = PackResult(
            root=self.root,
            entries=entries,
            total_chars=sum(e.size_bytes for e in entries),
            total_tokens=sum(e.est_tokens for e in entries),
            files_scanned=self.files_scanned,
            files_ignored=self.files_ignored,
            budget_tokens=self.max_tokens,
            truncated=sum(e.est_tokens for e in entries) > self.max_tokens,
            emitted=budget,
        )
        return result

    def entries_fit_budget(self, entries: Sequence[FileEntry], budget: int) -> list[FileEntry]:
        """Greedily select entries (already importance-sorted) that fit the budget."""
        selected: list[FileEntry] = []
        used = 0
        for e in entries:
            if used + e.est_tokens > budget:
                continue
            selected.append(e)
            used += e.est_tokens
        # Keep importance-desc order; that's how we iterated.
        return selected


def estimate_tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    """Estimate token count from character count. Tokenizer-agnostic heuristic."""
    if not text:
        return 0
    n = max(1, int(len(text) / chars_per_token))
    return n if n >= MIN_TOKENS else MIN_TOKENS


def read_ignore_patterns(root: Path) -> list[str]:
    """Return the effective ignore patterns (built-in defaults + repo files)."""
    out: list[str] = list(DEFAULT_IGNORE_PATTERNS)
    for name in IGNORE_FILE_NAMES:
        f = root / name
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for raw in text.splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    out.append(line)
    return out


IMPORTANCE_FOOTNOTE = (
    "_Generated by [ctxpack](https://github.com/ilikebrawling64-sudo/ctxpack). "
    "Token counts are estimates (~4 chars/token). Review before use._"
)