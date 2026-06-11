#!/usr/bin/env python3
"""Search a private agent-session memory archive.

The script is intentionally dependency-free so it can run inside a copied
deployment repository or from a skill bundle.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_REPO_CANDIDATES = (
    "AGENT_SESSION_MEMORY_REPO",
    "AGENT_MEMORY_REPO",
)
CONFIG_CANDIDATES = (
    "MY_PRECIOUS_CONFIG",
    "AGENT_SESSION_MEMORY_CONFIG",
)
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")


@dataclass
class Hit:
    path: Path
    score: int
    source: str
    why: list[str]
    title: str = ""


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[\w.-]+", text) if token.strip()]


def unique_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in tokenize(text):
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def configured_memory_repos() -> list[str]:
    config_paths: list[str] = []
    for name in CONFIG_CANDIDATES:
        value = os.environ.get(name)
        if value:
            config_paths.append(value)
    config_paths.append(str(DEFAULT_CONFIG_PATH))

    repos: list[str] = []
    for candidate in config_paths:
        path = Path(candidate).expanduser()
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        value = payload.get("memory_repo")
        if isinstance(value, str) and value.strip():
            repos.append(value)
    return repos


def resolve_repo(repo_arg: str | None) -> Path:
    candidates: list[str] = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for name in DEFAULT_REPO_CANDIDATES:
        value = os.environ.get(name)
        if value:
            candidates.append(value)
    candidates.extend(configured_memory_repos())
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")

    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "index").exists() and (repo / "sessions").exists():
            return repo.resolve()

    raise SystemExit(
        "No agent memory archive found. Run setup-my-precious, set "
        "AGENT_SESSION_MEMORY_REPO, or pass --repo /path/to/archive."
    )


def iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"warning: skipped invalid JSON at {path}:{line_no}: {exc}", file=sys.stderr)
                continue
            if isinstance(value, dict):
                yield value


def score_text(query_tokens: list[str], text: str, *, weight: int = 1) -> tuple[int, list[str]]:
    haystack = text.lower()
    matched: list[str] = []
    score = 0
    for token in query_tokens:
        count = haystack.count(token)
        if count:
            matched.append(token)
            score += min(count, 5) * weight
    return score, matched


def display_title(record: dict) -> str:
    for key in ("title", "decision", "task", "summary", "user_intent"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def record_search_text(record: dict) -> str:
    parts: list[str] = []
    for key in (
        "date",
        "source_agent",
        "project",
        "repository",
        "title",
        "decision",
        "rationale",
        "task",
        "summary",
        "user_intent",
        "summary_path",
        "evidence_path",
    ):
        value = record.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("tags", "files_touched", "reusable_facts", "decisions", "unresolved_tasks"):
        value = record.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return "\n".join(parts)


def safe_index_record_path(repo: Path, index_path: Path, path_text: object) -> Path:
    if not isinstance(path_text, str) or not path_text.strip():
        return index_path
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = repo / candidate
    try:
        repo_resolved = repo.resolve()
        resolved = candidate.resolve(strict=False)
        relative = resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        return index_path
    return repo / relative


def collect_index_hits(repo: Path, query_tokens: list[str]) -> list[Hit]:
    hits: list[Hit] = []
    for index_path in sorted((repo / "index").glob("*.jsonl")):
        for record in iter_jsonl(index_path):
            text = record_search_text(record)
            score, matched = score_text(query_tokens, text, weight=4)
            if not score:
                continue
            path = safe_index_record_path(repo, index_path, record.get("summary_path") or record.get("path"))
            why = [f"index:{index_path.name}", f"matched:{', '.join(matched)}"]
            hits.append(Hit(path=path, score=score + 10, source="index", why=why, title=display_title(record)))
    return hits


def iter_markdown_files(repo: Path, include_evidence: bool) -> Iterable[Path]:
    paths: list[Path] = []
    for name in ("INDEX.md",):
        path = repo / name
        if path.exists():
            paths.append(path)
    paths.extend(sorted((repo / "daily").glob("**/*.md")))
    paths.extend(sorted((repo / "sessions").glob("**/summary.md")))
    if include_evidence:
        paths.extend(sorted((repo / "sessions").glob("**/evidence.md")))
    seen: set[Path] = set()
    for path in paths:
        if path not in seen and path.is_file():
            seen.add(path)
            yield path


def collect_markdown_hits(repo: Path, query_tokens: list[str], include_evidence: bool) -> list[Hit]:
    hits: list[Hit] = []
    for path in iter_markdown_files(repo, include_evidence):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        weight = 1 if path.name == "evidence.md" else 2
        score, matched = score_text(query_tokens, text, weight=weight)
        if not score:
            continue
        title = ""
        for line in text.splitlines():
            if line.startswith("# "):
                title = line.lstrip("#").strip()
                break
        hits.append(
            Hit(
                path=path,
                score=score,
                source="markdown",
                why=[f"matched:{', '.join(matched)}"],
                title=title,
            )
        )
    return hits


def merge_hits(repo: Path, hits: Iterable[Hit]) -> list[Hit]:
    merged: dict[Path, Hit] = {}
    for hit in hits:
        key = hit.path.resolve() if hit.path.exists() else hit.path
        current = merged.get(key)
        if current is None:
            merged[key] = hit
            continue
        current.score += hit.score
        current.why.extend(reason for reason in hit.why if reason not in current.why)
        if not current.title and hit.title:
            current.title = hit.title
        if current.source != hit.source:
            current.source = "mixed"
    return sorted(
        merged.values(),
        key=lambda item: (item.score, item.path.as_posix()),
        reverse=True,
    )


def format_hit(repo: Path, hit: Hit, idx: int) -> str:
    try:
        rel = hit.path.relative_to(repo)
    except ValueError:
        rel = hit.path
    title = f"\n   title: {hit.title}" if hit.title else ""
    why = "; ".join(hit.why)
    next_step = "open summary.md first; inspect evidence.md only if needed"
    if rel.name == "evidence.md":
        next_step = "use only to verify a specific claim"
    elif rel.name == "INDEX.md" or str(rel).startswith("daily/"):
        next_step = "use as overview; then open the linked session summary"
    return (
        f"{idx}. {rel}\n"
        f"   score: {hit.score}\n"
        f"   source: {hit.source}{title}\n"
        f"   why: {why}\n"
        f"   next: {next_step}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Search query")
    parser.add_argument("--repo", help="Path to the agent memory archive")
    parser.add_argument("--limit", type=int, default=8, help="Maximum hits to print")
    parser.add_argument(
        "--include-evidence",
        action="store_true",
        help="Search evidence.md files as well as summaries and indexes",
    )
    args = parser.parse_args(argv)

    query_tokens = unique_tokens(args.query)
    if not query_tokens:
        raise SystemExit("query must contain at least one searchable token")

    repo = resolve_repo(args.repo)
    hits = merge_hits(
        repo,
        [
            *collect_index_hits(repo, query_tokens),
            *collect_markdown_hits(repo, query_tokens, args.include_evidence),
        ],
    )

    if not hits:
        print(f"No memory hits for: {args.query}")
        return 1

    print(f"Top memory hits for: {args.query}")
    print(f"Archive: {repo}")
    print()
    for idx, hit in enumerate(hits[: args.limit], 1):
        print(format_hit(repo, hit, idx))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
