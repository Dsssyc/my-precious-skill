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
UNSAFE_SOURCE_REF = "[unsafe-source-ref]"


@dataclass
class Hit:
    path: Path
    score: int
    source: str
    why: list[str]
    title: str = ""
    memory_id: str = ""
    layer: str = ""
    scope: str = ""
    text: str = ""
    drill_paths: tuple[str, ...] = ()
    raw_refs: tuple[str, ...] = ()


HIGH_SIGNAL_FIELDS = {
    "decision",
    "decisions",
    "task",
    "summary",
    "text",
    "rationale",
    "topic",
    "reusable_facts",
    "unresolved_tasks",
    "user_intent",
}
CONTEXT_FIELDS = ("project_path", "cwd", "repository", "project")
GENERIC_SEARCH_TOKENS = {
    "agent",
    "archive",
    "entry",
    "memory",
    "project",
    "review",
    "session",
    "source",
    "summary",
    "task",
    "test",
    "update",
    "workflow",
}


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


def query_phrases(query_tokens: list[str]) -> list[str]:
    phrases: list[str] = []
    for length in range(4, 1, -1):
        if len(query_tokens) < length:
            continue
        for idx in range(0, len(query_tokens) - length + 1):
            phrase = " ".join(query_tokens[idx : idx + length])
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases


def phrase_score(phrase: str) -> int:
    return sum(token_importance(token) for token in phrase.split()) * 18


def add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def project_context_terms(project_path: str | None) -> list[str]:
    if not project_path:
        return []
    text = str(Path(project_path).expanduser())
    terms = [text.lower()]
    basename = Path(text).name.lower()
    if basename and basename not in terms:
        terms.append(basename)
    return terms


def context_query_token_set(context_terms: list[str]) -> set[str]:
    tokens: set[str] = set()
    for term in context_terms:
        tokens.update(tokenize(term))
    return tokens


def non_context_query_tokens(query_tokens: list[str], context_terms: list[str] | None = None) -> list[str]:
    context_tokens = context_query_token_set(context_terms or [])
    return [token for token in query_tokens if token not in context_tokens]


def should_keep_match(query_tokens: list[str], matched_tokens: list[str], context_terms: list[str] | None = None) -> bool:
    content_tokens = non_context_query_tokens(query_tokens, context_terms)
    important_tokens = important_query_tokens(content_tokens)
    if not important_tokens:
        return True
    return any(token in matched_tokens for token in important_tokens)


def record_context_values(record: dict) -> list[str]:
    values: list[str] = []
    for key in CONTEXT_FIELDS:
        for text in iter_record_field_texts(record, key):
            lowered = text.lower()
            if lowered and lowered not in values:
                values.append(lowered)
    return values


def project_context_match(record: dict, context_terms: list[str]) -> bool:
    if not context_terms:
        return False
    values = record_context_values(record)
    if not values:
        return False
    for value in values:
        value_path_name = Path(value).name.lower()
        for term in context_terms:
            term_name = Path(term).name.lower()
            if value == term or value.endswith(f"/{term_name}") or term.endswith(f"/{value_path_name}"):
                return True
            if value_path_name and value_path_name == term_name:
                return True
            if key_like_project_match(value, term_name):
                return True
    return False


def search_quality_noise_reason(record: dict) -> str:
    parts: list[str] = []
    for key in ("title", "summary", "user_intent", "decision", "task"):
        parts.extend(iter_record_field_texts(record, key))
    combined = compact_whitespace(" ".join(parts)).lower()
    if not combined:
        return ""
    if re.search(
        r"\b(?:good hit|top hit|ranked first|search verification|search example|memory-quality|expected title|actual title)\b",
        combined,
    ):
        return "quality-penalty:search-verification"
    if re.search(r"\b(?:captures?|should include|should rank|result stdout|assertin)\b", combined):
        if re.search(r"\b(?:search|hit|title|rank|query|result)\b", combined):
            return "quality-penalty:search-verification"
    return ""


def key_like_project_match(value: str, term_name: str) -> bool:
    return bool(term_name and re.search(rf"(^|[/\s:_-]){re.escape(term_name)}($|[/\s:_-])", value))


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


def score_index_record(query_tokens: list[str], record: dict, context_terms: list[str] | None = None) -> tuple[int, list[str], list[str]]:
    field_weights = (
        ("text", 15),
        ("decision", 14),
        ("decisions", 14),
        ("task", 12),
        ("summary", 12),
        ("reusable_facts", 12),
        ("unresolved_tasks", 10),
        ("rationale", 8),
        ("user_intent", 7),
        ("topic", 6),
        ("scope", 6),
        ("title", 5),
        ("layer", 4),
        ("project", 3),
        ("repository", 3),
        ("tags", 2),
        ("memory_id", 1),
        ("files_touched", 2),
        ("source_agent", 1),
        ("summary_path", 1),
        ("evidence_path", 1),
        ("date", 1),
    )
    score = 0
    matched_tokens: list[str] = []
    structured_match_count = 0
    structured_matched_tokens: set[str] = set()
    reasons: list[str] = []
    phrases = query_phrases(query_tokens)
    phrase_matches = 0
    content_query_tokens = non_context_query_tokens(query_tokens, context_terms)
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
                if key in HIGH_SIGNAL_FIELDS:
                    structured_matched_tokens.update(matched)
                    add_reason(reasons, f"field:{key}")
                for token in matched:
                    if token not in matched_tokens:
                        matched_tokens.append(token)
                lowered = text.lower()
                for phrase in phrases:
                    if phrase_matches >= 3:
                        break
                    if phrase in lowered:
                        score += phrase_score(phrase) * max(1, field_weight // 4)
                        phrase_matches += 1
                        add_reason(reasons, f"phrase:{phrase}")
        if field_matched and key in HIGH_SIGNAL_FIELDS:
            structured_match_count += len(field_matched)
    if matched_tokens:
        matched_importance = sum(token_importance(token) for token in set(matched_tokens))
        score += matched_importance * 6
        if len(matched_tokens) == len(query_tokens):
            score += 20
        if structured_match_count >= 2:
            score += 20 + structured_match_count * 3
        specific_tokens = specific_query_tokens(content_query_tokens)
        matched_specific = [token for token in specific_tokens if token in matched_tokens]
        if matched_specific:
            score += sum(token_importance(token) for token in matched_specific) * 25
            missing_specific = [token for token in specific_tokens if token not in matched_tokens]
            if missing_specific:
                score = max(1, score // (2 + len(missing_specific)))
        elif specific_tokens:
            score = max(1, score // 8)
        important_tokens = important_query_tokens(content_query_tokens)
        if important_tokens:
            matched_important = [token for token in important_tokens if token in matched_tokens]
            required = max(1, (len(important_tokens) + 1) // 2)
            if len(matched_important) >= required:
                score += sum(token_importance(token) for token in matched_important) * 12
                score += len(matched_important) * 8
                add_reason(reasons, "important-token-coverage")
            else:
                missing_required = required - len(matched_important)
                score = max(1, score // (2 + missing_required * 2))
        low_signal_only = not structured_matched_tokens
        broad_only = low_signal_only and all(token in GENERIC_SEARCH_TOKENS for token in matched_tokens)
        if low_signal_only:
            score = max(1, score // 4)
            add_reason(reasons, "low-signal-only")
        if broad_only and any(token not in GENERIC_SEARCH_TOKENS for token in query_tokens):
            score = max(1, score // 4)
            add_reason(reasons, "broad-field-only")
    if structured_matched_tokens and project_context_match(record, context_terms or []):
        score += 1200
        add_reason(reasons, "project-context")
    quality_reason = search_quality_noise_reason(record)
    if quality_reason:
        add_reason(reasons, quality_reason)
        return 0, matched_tokens, reasons
    if matched_tokens and not should_keep_match(query_tokens, matched_tokens, context_terms):
        return 0, matched_tokens, reasons
    return score, matched_tokens, reasons


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


def safe_repo_relative_path(repo: Path, path_text: object) -> str:
    if not isinstance(path_text, str) or not path_text.strip():
        return ""
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = repo / candidate
    try:
        repo_resolved = repo.resolve()
        resolved = candidate.resolve(strict=False)
        relative = resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        return ""
    return relative.as_posix()


def unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


def iter_ref_paths(value: object) -> Iterable[str]:
    if isinstance(value, str) and value.strip():
        yield value.strip()
    elif isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, str) and path.strip():
            yield path.strip()
    elif isinstance(value, list):
        for item in value:
            yield from iter_ref_paths(item)


def has_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def sanitize_raw_ref(repo: Path, value: object) -> str:
    if isinstance(value, str):
        path_text = value.strip()
        anchor_text = ""
    elif isinstance(value, dict):
        path = value.get("path")
        if not isinstance(path, str):
            return UNSAFE_SOURCE_REF
        path_text = path.strip()
        anchor = value.get("anchor")
        anchor_text = anchor.strip() if isinstance(anchor, str) else ""
    else:
        return UNSAFE_SOURCE_REF
    if not path_text or has_control_chars(path_text) or has_control_chars(anchor_text):
        return UNSAFE_SOURCE_REF
    safe_path = safe_repo_relative_path(repo, path_text)
    if not safe_path:
        return UNSAFE_SOURCE_REF
    if anchor_text:
        return f"{safe_path}#{anchor_text}"
    return safe_path


def sanitized_raw_refs(repo: Path, value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        refs = [sanitize_raw_ref(repo, item) for item in value]
    elif value:
        refs = [sanitize_raw_ref(repo, value)]
    else:
        refs = []
    return unique_ordered(refs)


def memory_drill_paths(repo: Path, record: dict) -> tuple[str, ...]:
    paths: list[str] = []
    for path in iter_ref_paths(record.get("derived_from")):
        safe_path = safe_repo_relative_path(repo, path)
        if safe_path:
            paths.append(safe_path)
    for path in iter_ref_paths(record.get("evidence_refs")):
        safe_path = safe_repo_relative_path(repo, path)
        if safe_path:
            paths.append(safe_path)
    return unique_ordered(paths)


def memory_hit_path(repo: Path, memory_id: str, line_no: int) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", memory_id).strip("._")
    if not safe_id:
        safe_id = f"line-{line_no}"
    return repo / "index" / "memories.jsonl" / safe_id[:120]


def collect_memory_hits(
    repo: Path,
    query_tokens: list[str],
    context_terms: list[str] | None = None,
    scope: str = "all",
) -> list[Hit]:
    hits: list[Hit] = []
    index_path = repo / "index" / "memories.jsonl"
    for line_no, record in enumerate(iter_jsonl(index_path), 1):
        layer = str(record.get("layer") or "")
        if scope != "all" and layer != scope:
            continue
        if record.get("superseded_by"):
            continue
        score, matched, reasons = score_index_record(query_tokens, record, context_terms)
        if not score:
            continue
        text = compact_whitespace(str(record.get("text") or ""))
        title = clip(text or display_title(record, query_tokens))
        memory_id = str(record.get("memory_id") or "")
        source_kind = str(record.get("source") or "")
        confidence = str(record.get("confidence") or "")
        support_count = record.get("support_count")
        why = [f"index:{index_path.name}"]
        if layer:
            why.append(f"layer:{layer}")
        if source_kind:
            why.append(f"source:{source_kind}")
        if confidence:
            why.append(f"confidence:{confidence}")
        if isinstance(support_count, int) or isinstance(support_count, str):
            why.append(f"support_count:{support_count}")
        why.extend(reasons)
        why.append(f"matched:{', '.join(matched)}")
        hits.append(
            Hit(
                path=memory_hit_path(repo, memory_id, line_no),
                score=score + 30,
                source="memory",
                why=why,
                title=title,
                memory_id=memory_id,
                layer=layer,
                scope=str(record.get("scope") or ""),
                text=text,
                drill_paths=memory_drill_paths(repo, record),
                raw_refs=sanitized_raw_refs(repo, record.get("raw_refs")),
            )
        )
    return hits


def collect_index_hits(repo: Path, query_tokens: list[str], context_terms: list[str] | None = None) -> list[Hit]:
    hits: list[Hit] = []
    for index_path in sorted((repo / "index").glob("*.jsonl")):
        if index_path.name == "memories.jsonl":
            continue
        for record in iter_jsonl(index_path):
            score, matched, reasons = score_index_record(query_tokens, record, context_terms)
            if not score:
                continue
            path = safe_index_record_path(repo, index_path, record.get("summary_path") or record.get("path"))
            why = [f"index:{index_path.name}", *reasons, f"matched:{', '.join(matched)}"]
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
        if not should_keep_match(query_tokens, matched):
            continue
        if search_quality_noise_reason({"summary": text}):
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
        current.score = max(current.score, hit.score) + duplicate_hit_bonus(hit)
        current.why.extend(reason for reason in hit.why if reason not in current.why)
        if hit.title and (not current.title or result_title_quality(hit.title) > result_title_quality(current.title)):
            current.title = hit.title
        if hit.text and not current.text:
            current.text = hit.text
        if hit.memory_id and not current.memory_id:
            current.memory_id = hit.memory_id
        current.drill_paths = unique_ordered((*current.drill_paths, *hit.drill_paths))
        current.raw_refs = unique_ordered((*current.raw_refs, *hit.raw_refs))
        if current.source != hit.source:
            current.source = "mixed"
    return sorted(
        merged.values(),
        key=lambda item: (item.score, item.path.as_posix()),
        reverse=True,
    )


def duplicate_hit_bonus(hit: Hit) -> int:
    """Give tiny corroboration credit without letting duplicate rows dominate."""
    if "low-signal-only" in hit.why:
        return 0
    if not any(reason.startswith("field:") for reason in hit.why):
        return min(5, max(1, hit.score // 50))
    return min(12, max(1, hit.score // 25))


def is_evidence_drill_path(path: str) -> bool:
    return Path(path).name == "evidence.md"


def memory_drill_paths_for_depth(hit: Hit, depth: str) -> tuple[str, ...]:
    if depth in ("evidence", "source"):
        return hit.drill_paths
    return tuple(path for path in hit.drill_paths if not is_evidence_drill_path(path))


def format_memory_hit(hit: Hit, idx: int, depth: str) -> str:
    layer = hit.layer or "memory"
    title = clip(hit.text or hit.title or "Untitled memory", 160)
    why = "; ".join(hit.why)
    lines = [
        f"{idx}. [{layer}] {title}",
        f"   score: {hit.score}",
        "   source: memory",
    ]
    if hit.memory_id:
        lines.append(f"   memory_id: {hit.memory_id}")
    if hit.scope:
        lines.append(f"   scope: {hit.scope}")
    lines.append(f"   why: {why}")
    drill_paths = memory_drill_paths_for_depth(hit, depth)
    if drill_paths:
        lines.append("   drill:")
        lines.extend(f"     - {path}" for path in drill_paths)
    if depth == "source" and hit.raw_refs:
        lines.append("   source anchors:")
        lines.extend(f"     - {raw_ref}" for raw_ref in hit.raw_refs)
    lines.append("   next: use drill paths for supporting sessions and evidence")
    return "\n".join(lines)


def format_hit(repo: Path, hit: Hit, idx: int, depth: str = "memory") -> str:
    if hit.source == "memory":
        return format_memory_hit(hit, idx, depth)
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
    parser.add_argument(
        "--depth",
        choices=("memory", "session", "evidence", "source"),
        default="memory",
        help="Recall depth: memory nodes, sessions, evidence snippets, or source anchors",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "global", "domain", "project"),
        default="all",
        help="Memory node layer to search; not applied to legacy session fallback",
    )
    parser.add_argument(
        "--legacy-sessions",
        action="store_true",
        help="Bypass memory nodes and use the legacy session/index/markdown search path",
    )
    parser.add_argument(
        "--project-path",
        help="Optional current project path used to boost matching archive records",
    )
    args = parser.parse_args(argv)

    query_tokens = unique_tokens(args.query)
    if not query_tokens:
        raise SystemExit("query must contain at least one searchable token")

    repo = resolve_repo(args.repo)
    context_terms = project_context_terms(args.project_path)
    include_evidence = args.include_evidence or args.depth in ("evidence", "source")
    session_hits = [
        *collect_index_hits(repo, query_tokens, context_terms),
        *collect_markdown_hits(repo, query_tokens, include_evidence),
    ]
    if args.legacy_sessions:
        selected_hits = session_hits
    else:
        memory_hits = collect_memory_hits(repo, query_tokens, context_terms, args.scope)
        if memory_hits and (args.depth in ("session", "evidence", "source") or args.include_evidence):
            selected_hits = [*memory_hits, *session_hits]
        elif memory_hits:
            selected_hits = memory_hits
        else:
            selected_hits = session_hits
    hits = merge_hits(repo, selected_hits)

    if not hits:
        print(f"No memory hits for: {args.query}")
        return 1

    print(f"Top memory hits for: {args.query}")
    print(f"Archive: {repo}")
    print()
    for idx, hit in enumerate(hits[: args.limit], 1):
        print(format_hit(repo, hit, idx, args.depth))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
