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


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int = 180) -> str:
    text = compact_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def is_generic_source_title(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return True
    if re.search(r"\brollout-\d{4}-\d{2}-\d{2}t", lowered):
        return True
    if re.search(r"\.(?:jsonl|json|log|txt|md)\b", lowered) and ":" in lowered:
        return True
    return False


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
            score += min(count, 5) * weight * token_importance(token)
    return score, matched


def token_importance(token: str) -> int:
    if any(ord(char) > 127 for char in token):
        return 5
    if "_" in token or "." in token or "-" in token:
        return 4
    if any(char.isdigit() for char in token) and len(token) >= 6:
        return 4
    if len(token) >= 10:
        return 3
    if len(token) >= 7:
        return 2
    return 1


def specific_query_tokens(query_tokens: list[str]) -> list[str]:
    return [token for token in query_tokens if token_importance(token) >= 4]


def important_query_tokens(query_tokens: list[str]) -> list[str]:
    return [
        token
        for token in query_tokens
        if token_importance(token) >= 2 or (any(char.isdigit() for char in token) and len(token) >= 3)
    ]


def iter_record_field_texts(record: dict, key: str) -> Iterable[str]:
    value = record.get(key)
    if isinstance(value, str) and value.strip():
        yield value
    elif isinstance(value, list):
        for item in value:
            text = str(item).strip()
            if text:
                yield text


def display_title(record: dict, query_tokens: list[str] | None = None) -> str:
    query_tokens = query_tokens or []
    if isinstance(record.get("summary"), str) and isinstance(record.get("title"), str):
        title = record["title"].strip()
        if title and not is_generic_source_title(title):
            return clip(title)
    candidates: list[tuple[int, int, str]] = []
    title_fields = (
        ("decision", 70),
        ("task", 65),
        ("summary", 60),
        ("reusable_facts", 55),
        ("decisions", 55),
        ("unresolved_tasks", 50),
        ("user_intent", 45),
        ("title", 30),
    )
    for key, priority in title_fields:
        for text in iter_record_field_texts(record, key):
            if key == "title" and is_generic_source_title(text):
                continue
            match_score, matched = score_text(query_tokens, text, weight=1) if query_tokens else (0, [])
            if query_tokens and key != "title" and not matched:
                continue
            candidates.append((match_score, priority, clip(text)))
    if candidates:
        return max(candidates, key=lambda item: (item[0], item[1], len(item[2])))[2]

    for text in iter_record_field_texts(record, "title"):
        return clip(text)
    return ""


def result_title_quality(text: str) -> int:
    compacted = compact_whitespace(text)
    if not compacted:
        return -10_000
    score = 0
    if len(compacted) <= 120:
        score += 20
    elif len(compacted) > 180:
        score -= 20
    if re.search(r"\b(root cause|decision|proxy|socks5|spurious|libx265|libheif|_gdal)\b|根因|原因|代理|记忆索引|高质量", compacted, re.IGNORECASE):
        score += 30
    if re.search(r"\b(?:dry run|live update|source record|secret gate|subagent)\b|默认 secret gate|产生新写入", compacted, re.IGNORECASE):
        score -= 80
    if is_generic_source_title(compacted):
        score -= 100
    return score


def score_index_record(query_tokens: list[str], record: dict) -> tuple[int, list[str]]:
    field_weights = (
        ("decision", 14),
        ("decisions", 14),
        ("task", 12),
        ("summary", 12),
        ("reusable_facts", 12),
        ("unresolved_tasks", 10),
        ("user_intent", 7),
        ("title", 5),
        ("rationale", 5),
        ("project", 3),
        ("repository", 3),
        ("tags", 2),
        ("files_touched", 2),
        ("source_agent", 1),
        ("summary_path", 1),
        ("evidence_path", 1),
        ("date", 1),
    )
    score = 0
    matched_tokens: list[str] = []
    structured_match_count = 0
    for key, weight in field_weights:
        field_weight = weight
        field_matched: set[str] = set()
        for text in iter_record_field_texts(record, key):
            if key == "title" and is_generic_source_title(text):
                field_weight = 1
            field_score, matched = score_text(query_tokens, text, weight=field_weight)
            if field_score:
                score += field_score
                field_matched.update(matched)
                for token in matched:
                    if token not in matched_tokens:
                        matched_tokens.append(token)
        if field_matched and key in {"decision", "decisions", "task", "summary", "reusable_facts", "unresolved_tasks"}:
            structured_match_count += len(field_matched)
    if matched_tokens:
        matched_importance = sum(token_importance(token) for token in set(matched_tokens))
        score += matched_importance * 6
        if len(matched_tokens) == len(query_tokens):
            score += 20
        if structured_match_count >= 2:
            score += 20 + structured_match_count * 3
        specific_tokens = specific_query_tokens(query_tokens)
        matched_specific = [token for token in specific_tokens if token in matched_tokens]
        if matched_specific:
            score += sum(token_importance(token) for token in matched_specific) * 25
            missing_specific = [token for token in specific_tokens if token not in matched_tokens]
            if missing_specific:
                score = max(1, score // (2 + len(missing_specific)))
        elif specific_tokens:
            score = max(1, score // 8)
        important_tokens = important_query_tokens(query_tokens)
        if len(important_tokens) >= 2:
            matched_important = [token for token in important_tokens if token in matched_tokens]
            required = max(1, (len(important_tokens) + 1) // 2)
            if len(matched_important) >= required:
                score += sum(token_importance(token) for token in matched_important) * 12
                score += len(matched_important) * 8
            else:
                missing_required = required - len(matched_important)
                score = max(1, score // (2 + missing_required * 2))
    return score, matched_tokens


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
            score, matched = score_index_record(query_tokens, record)
            if not score:
                continue
            path = safe_index_record_path(repo, index_path, record.get("summary_path") or record.get("path"))
            why = [f"index:{index_path.name}", f"matched:{', '.join(matched)}"]
            hits.append(Hit(path=path, score=score + 10, source="index", why=why, title=display_title(record, query_tokens)))
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
        if hit.title and (not current.title or result_title_quality(hit.title) > result_title_quality(current.title)):
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
