#!/usr/bin/env python3
"""Incrementally archive session/source records into an agent memory repository.

The updater is intentionally conservative: it uses the current project path as
the high-water-mark key and writes searchable summaries plus short redacted
evidence snippets. Better source-specific summarizers can replace or refine
these summaries later without changing the archive shape.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


DEFAULT_PATTERNS = ("*.jsonl", "*.json", "*.md", "*.txt", "*.log")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "env"}
TIMESTAMP_KEYS = {"timestamp", "created_at", "updated_at", "started_at", "ended_at", "date"}
PROJECT_PATH_KEYS = {
    "cwd",
    "project_path",
    "working_directory",
    "current_working_directory",
    "workspace",
    "repo_path",
    "repository_path",
}
CONFIG_CANDIDATES = (
    "MY_PRECIOUS_CONFIG",
    "AGENT_SESSION_MEMORY_CONFIG",
)
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")
REDACTION_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    "bearer_token": re.compile(r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+"),
    "cookie": re.compile(r"(?i)(Cookie:\s*)[^\n]+"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


@dataclass
class SourceRecord:
    path: Path
    updated_at: datetime
    sha256: str


@dataclass
class MemoryEvent:
    kind: str
    text: str


NOISE_MARKERS = (
    "session_meta",
    "response_item",
    "event_msg",
    "base_instructions",
    "model_context_window",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def slugify(value: str, fallback: str = "project") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
    return slug[:80] or fallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_name_from_path(project_path: Path) -> str:
    return project_path.name or slugify(project_path.as_posix())


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.extend(configured_memory_repos())
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists() and (path / "index").exists() and (path / "sessions").exists():
            return path.resolve()
    raise SystemExit(
        "No memory repository found. Run setup-my-precious, pass --memory-repo, "
        "or set AGENT_SESSION_MEMORY_REPO."
    )


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


def iter_jsonl(path: Path) -> Iterable[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def archived_project_state(memory_repo: Path, project_path: Path) -> tuple[datetime | None, set[str]]:
    project_key = str(project_path.resolve())
    latest: datetime | None = None
    archived_hashes: set[str] = set()

    for record in iter_jsonl(memory_repo / "index" / "sessions.jsonl"):
        if record.get("project_path") != project_key:
            continue
        for key in ("source_updated_at", "ended_at", "updated_at", "started_at", "date"):
            parsed = parse_timestamp(record.get(key))
            if parsed and (latest is None or parsed > latest):
                latest = parsed

    for meta_path in (memory_repo / "sessions").glob("**/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("project_path") != project_key:
            continue
        source_hash = meta.get("source_record_sha256")
        if isinstance(source_hash, str) and source_hash:
            archived_hashes.add(source_hash)
        for key in ("source_updated_at", "ended_at", "updated_at", "started_at", "date"):
            parsed = parse_timestamp(meta.get(key))
            if parsed and (latest is None or parsed > latest):
                latest = parsed

    return latest, archived_hashes


def latest_archived_timestamp(memory_repo: Path, project_path: Path) -> datetime | None:
    latest, _ = archived_project_state(memory_repo, project_path)
    return latest


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def walk_json_values(value: object) -> Iterable[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from walk_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json_values(child)


def iter_source_json_values(path: Path, text: str) -> Iterable[object]:
    if path.suffix == ".jsonl":
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError:
                continue
        return

    if path.suffix == ".json":
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            return
        return

    try:
        yield json.loads(text)
        return
    except json.JSONDecodeError:
        pass

    for raw_line in text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            yield json.loads(raw_line)
        except json.JSONDecodeError:
            continue


def record_matches_project(path: Path, text: str, project_path: Path, require_project_metadata: bool = False) -> bool:
    discovered_paths: list[Path] = []
    for value in iter_source_json_values(path, text):
        for key, child in walk_json_values(value):
            if key in PROJECT_PATH_KEYS and isinstance(child, str) and child.strip():
                candidate = Path(child).expanduser()
                if candidate.is_absolute():
                    discovered_paths.append(candidate.resolve())
    if not discovered_paths:
        return not require_project_metadata
    project_key = project_path.resolve()
    return any(candidate == project_key for candidate in discovered_paths)


def timestamp_from_filename(path: Path) -> datetime | None:
    text = path.as_posix()
    patterns = (
        r"\d{4}-\d{2}-\d{2}T\d{2}[:_-]\d{2}[:_-]\d{2}Z?",
        r"\d{4}-\d{2}-\d{2}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(0)
        if "T" in value:
            date_part, time_part = value.split("T", 1)
            suffix = "Z" if time_part.endswith("Z") else ""
            if suffix:
                time_part = time_part[:-1]
            value = f"{date_part}T{re.sub(r'[-_]', ':', time_part)}{suffix}"
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = parse_timestamp(value)
        if parsed:
            return parsed
    return None


def direct_timestamp_candidates(value: object) -> Iterable[datetime]:
    if isinstance(value, dict):
        for key in TIMESTAMP_KEYS:
            parsed = parse_timestamp(value.get(key))
            if parsed:
                yield parsed
    elif isinstance(value, list):
        for item in value:
            yield from direct_timestamp_candidates(item)


def source_timestamp(path: Path, text: str) -> datetime:
    candidates: list[datetime] = []
    for value in iter_source_json_values(path, text):
        candidates.extend(direct_timestamp_candidates(value))
    filename_timestamp = timestamp_from_filename(path)
    if filename_timestamp:
        candidates.append(filename_timestamp)
    if candidates:
        return max(candidates)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def iter_candidate_files(source_dir: Path, patterns: tuple[str, ...]) -> Iterable[Path]:
    for pattern in patterns:
        for path in source_dir.rglob(pattern):
            if path.is_file() and not should_skip(path.relative_to(source_dir)):
                yield path


def discover_records(
    source_dir: Path,
    patterns: tuple[str, ...],
    after: datetime | None,
    project_path: Path,
    archived_hashes: set[str] | None = None,
    require_project_metadata: bool = False,
) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    seen: set[Path] = set()
    archived_hashes = archived_hashes or set()
    for path in iter_candidate_files(source_dir, patterns):
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        text = read_record_text(path)
        if not record_matches_project(path, text, project_path, require_project_metadata):
            continue
        updated_at = source_timestamp(path, text)
        source_hash = sha256_file(path)
        if after is not None:
            if updated_at < after:
                continue
            if updated_at == after and source_hash in archived_hashes:
                continue
        records.append(SourceRecord(path=path, updated_at=updated_at, sha256=source_hash))
    return sorted(records, key=lambda item: (item.updated_at, item.path.as_posix()))


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    redacted = text
    for name, pattern in REDACTION_PATTERNS.items():
        redacted, count = pattern.subn(lambda match: match.group(1) + f"[REDACTED_{name.upper()}]" if match.groups() else f"[REDACTED_{name.upper()}]", redacted)
        if count:
            counts[name] = count
    return redacted, counts


def read_record_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clip(text: str, limit: int = 240) -> str:
    text = compact_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def is_noisy_text(text: object) -> bool:
    if not isinstance(text, str):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def extract_text(value: object) -> str:
    if isinstance(value, str):
        return clip(value)
    if isinstance(value, list):
        return clip(" ".join(part for item in value if (part := extract_text(item))))
    if isinstance(value, dict):
        for key in ("text", "message", "summary", "output", "content"):
            if key in value:
                text = extract_text(value.get(key))
                if text:
                    return text
    return ""


def command_from_arguments(arguments: object) -> str:
    value = arguments
    if isinstance(arguments, str):
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError:
            return clip(arguments)
    if isinstance(value, dict):
        for key in ("cmd", "command", "script"):
            text = extract_text(value.get(key))
            if text:
                return text
        return clip(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return extract_text(value)


def events_from_value(value: object) -> list[MemoryEvent]:
    if isinstance(value, list):
        events: list[MemoryEvent] = []
        for item in value:
            events.extend(events_from_value(item))
        return events
    if not isinstance(value, dict):
        text = extract_text(value)
        return [MemoryEvent("record", text)] if text else []

    event_type = str(value.get("type") or "")
    if event_type in {"session_meta", "turn_context"}:
        return []

    payload = value.get("payload")
    body = payload if isinstance(payload, dict) else value
    body_type = str(body.get("type") or event_type)

    # Status-stream messages are useful during a live turn but too noisy for
    # long-term memory indexes. Durable outcomes still appear in assistant
    # response items and final messages.
    if event_type == "event_msg":
        return []

    if body_type == "function_call":
        name = extract_text(body.get("name")) or "tool"
        command = command_from_arguments(body.get("arguments"))
        text = f"{name}: {command}" if command else name
        return [MemoryEvent("command", clip(text))]

    if body_type == "function_call_output":
        text = extract_text(body.get("output"))
        return [MemoryEvent("command_output", text)] if text else []

    role = str(body.get("role") or value.get("role") or "").lower()
    text = extract_text(body.get("content")) or extract_text(body.get("text")) or extract_text(body.get("message"))
    if not text:
        return []
    if role in {"user", "human"}:
        return [MemoryEvent("user", text)]
    if role == "assistant":
        return [MemoryEvent("assistant", text)]
    return [MemoryEvent("record", text)]


def extract_source_events(path: Path, text: str) -> list[MemoryEvent]:
    events: list[MemoryEvent] = []
    parsed_any = False
    for value in iter_source_json_values(path, text):
        parsed_any = True
        events.extend(events_from_value(value))
    if not parsed_any:
        for line in text.splitlines():
            line = clip(line)
            if line:
                events.append(MemoryEvent("record", line))
    return [event for event in events if event.text and not is_noisy_text(event.text)]


def bullet_list(items: list[str], fallback: str) -> str:
    if not items:
        return f"- {fallback}\n"
    return "".join(f"- {item}\n" for item in items)


def is_process_update(text: str) -> bool:
    lowered = text.lower()
    prefixes = (
        "i am ",
        "i'm ",
        "i will ",
        "i’ll ",
        "next i",
        "now i",
        "i checked ",
        "i found ",
        "我先",
        "我会",
        "现在",
        "下一步",
    )
    return lowered.startswith(prefixes)


def event_texts(events: list[MemoryEvent], kinds: set[str] | None = None) -> list[str]:
    texts: list[str] = []
    for event in events:
        if kinds is not None and event.kind not in kinds:
            continue
        if event.text not in texts:
            texts.append(event.text)
    return texts


def select_event_texts(
    events: list[MemoryEvent],
    pattern: str,
    *,
    kinds: set[str] | None = None,
    limit: int = 5,
    skip_process: bool = True,
) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE)
    selected: list[str] = []
    for text in event_texts(events, kinds):
        if skip_process and is_process_update(text):
            continue
        if is_noisy_text(text):
            continue
        if regex.search(text):
            selected.append(text)
            if len(selected) >= limit:
                break
    return selected


def extract_tags(project_name: str, texts: list[str]) -> list[str]:
    tags = ["agent-memory", "my-precious", slugify(project_name)]
    stop_words = {
        "this",
        "that",
        "with",
        "from",
        "will",
        "should",
        "would",
        "could",
        "need",
        "root",
        "cause",
        "final",
        "state",
        "archive",
        "memory",
    }
    for text in texts:
        if is_noisy_text(text):
            continue
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{3,}", text.lower()):
            token = token.strip("._-")
            if not token or token in stop_words or token in tags:
                continue
            tags.append(token[:48])
            if len(tags) >= 16:
                return tags
    return tags


def summarize_events(events: list[MemoryEvent], project_name: str) -> dict[str, object]:
    user_lines = event_texts(events, {"user"})
    if not user_lines:
        user_lines = event_texts(events, {"record"})[:2]
    assistant_lines = event_texts(events, {"assistant", "record"})
    decisions = select_event_texts(
        events,
        r"\b(decision|decide|decided|chosen|selected|root cause|原因|决定|选择)\b",
        kinds={"assistant", "record"},
        limit=5,
    )
    problems = select_event_texts(
        events,
        r"\b(error|failed|failure|blocked|exception|traceback|problem|issue|bug|importerror|失败|错误|阻塞)\b",
        kinds={"assistant", "record", "command_output"},
        limit=5,
        skip_process=False,
    )
    unresolved = select_event_texts(
        events,
        r"\b(todo|follow[- ]?up|unresolved|remaining|still need|not completed|后续|未完成)\b",
        kinds={"assistant", "record"},
        limit=5,
    )
    commands = event_texts(events, {"command"})[:5]
    facts = select_event_texts(
        events,
        r"\b(root cause|verified|must|should|require|requires|constraint|convention|policy|rule|prefer|expected|原因|验证|约定|偏好|必须|应该)\b",
        kinds={"assistant", "record"},
        limit=5,
    )
    if not facts:
        facts = [text for text in assistant_lines if not is_process_update(text)][:3]
    evidence = []
    for group in (user_lines, decisions, facts, problems, unresolved):
        for line in group:
            if line not in evidence and not is_noisy_text(line):
                evidence.append(line)
            if len(evidence) >= 6:
                break
        if len(evidence) >= 6:
            break

    user_intent = user_lines[0] if user_lines else f"Archive source record for {project_name}."
    final_state = ""
    for text in reversed(assistant_lines):
        if not is_process_update(text):
            final_state = text
            break
    summary_items = []
    for line in [user_intent, *decisions[:1], *facts[:1], final_state]:
        if line not in summary_items:
            summary_items.append(line)
    summary = " ".join(summary_items) if summary_items else f"Archived source record for {project_name}."
    context = []
    for line in [user_intent, *facts[:2], *problems[:1], final_state]:
        if line and line not in context and not is_noisy_text(line):
            context.append(line)

    return {
        "user_intent": user_intent,
        "summary": summary,
        "context": context[:5],
        "facts": facts,
        "decisions": decisions,
        "problems": problems,
        "unresolved": unresolved,
        "commands": commands,
        "evidence": evidence,
        "tags": extract_tags(project_name, [summary, *user_lines, *facts, *decisions, *problems, *commands]),
        "final_state": final_state or summary,
    }


def record_dir(memory_repo: Path, project_slug: str, record: SourceRecord) -> Path:
    stamp = record.updated_at.strftime("%Y-%m-%dT%H%M%SZ")
    day = record.updated_at.strftime("%Y/%m/%d")
    return memory_repo / "sessions" / day / f"{stamp}_{project_slug}_{record.sha256[:10]}"


def write_record(
    memory_repo: Path,
    project_path: Path,
    project_name: str,
    source_agent: str,
    record: SourceRecord,
) -> Path:
    project_slug = slugify(project_name)
    destination = record_dir(memory_repo, project_slug, record)
    destination.mkdir(parents=True, exist_ok=True)

    source_text = read_record_text(record.path)
    redacted_text, redaction_counts = redact_text(source_text)
    source_events = extract_source_events(record.path, redacted_text)
    summary_data = summarize_events(source_events, project_name)
    archived_at = utc_now()
    rel_summary = destination.relative_to(memory_repo) / "summary.md"
    rel_evidence = destination.relative_to(memory_repo) / "evidence.md"

    title = f"{project_name}: {record.path.name}"
    archive_status = "summarized"
    redaction_status = "redacted" if redaction_counts else "none"
    tags = ", ".join(str(tag) for tag in summary_data["tags"])
    summary = f"""# Session: {title}

## Identity
- source_agent: {source_agent}
- project: {project_name}
- project_path: {project_path}
- source_record: {record.path}
- source_updated_at: {isoformat(record.updated_at)}
- source_sha256: {record.sha256}
- archive_status: {archive_status}
- redaction_status: {redaction_status}

## User Intent
{summary_data["user_intent"]}

## Context Recovered
{bullet_list(summary_data["context"], f"Source file `{record.path.name}` was newer than the latest archived timestamp for this project.")}

## Reusable Facts
{bullet_list(summary_data["facts"], "No reusable facts were detected automatically.")}

## Decisions Made
{bullet_list(summary_data["decisions"], "No decisions were detected automatically.")}

## Files And Code Touched
- source_record: `{record.path}`
- archive_entry: `{destination.relative_to(memory_repo)}`

## Commands And Tools Used
- `update_memory_archive.py`: created this summarized archive entry.
{bullet_list(summary_data["commands"], "No source commands were detected automatically.")}

## Problems Encountered
{bullet_list(summary_data["problems"], "No problems were detected automatically.")}

## Final State
{summary_data["final_state"]}

## Unresolved Tasks
{bullet_list(summary_data["unresolved"], "Review this generated summary and refine it if the source record needs higher fidelity.")}

## Search Tags
{tags}

## Evidence Pointers
See `evidence.md` for short redacted snippets that support the summary.
"""

    evidence_lines = summary_data["evidence"]
    if evidence_lines:
        evidence_body = "\n".join(f"- {line}" for line in evidence_lines)
    else:
        evidence_body = "- No specific evidence snippets were selected automatically."
    evidence = f"""# Evidence: {title}

Source record: `{record.path}`
Source updated at: {isoformat(record.updated_at)}
Source SHA-256: `{record.sha256}`
Policy: short redacted snippets only; raw source records are not copied by default.

{evidence_body}
"""

    meta = {
        "session_id": destination.name,
        "source_agent": source_agent,
        "project": project_name,
        "project_path": str(project_path),
        "source_record": str(record.path),
        "source_record_sha256": record.sha256,
        "source_updated_at": isoformat(record.updated_at),
        "archived_at": isoformat(archived_at),
        "summary_path": str(rel_summary),
        "evidence_path": str(rel_evidence),
        "archive_status": archive_status,
        "redaction_status": redaction_status,
        "contains_raw_transcript": False,
        "evidence_policy": "short_redacted_snippets",
        "user_intent": summary_data["user_intent"],
        "summary": summary_data["summary"],
        "reusable_facts": summary_data["facts"],
        "tags": summary_data["tags"],
        "decisions": summary_data["decisions"],
        "unresolved_tasks": summary_data["unresolved"],
        "redaction_counts": redaction_counts,
    }
    source_map = {
        "source_record": str(record.path),
        "source_record_sha256": record.sha256,
        "source_updated_at": isoformat(record.updated_at),
        "project_path": str(project_path),
        "archive_entry": str(destination.relative_to(memory_repo)),
        "summary_path": str(rel_summary),
        "evidence_path": str(rel_evidence),
        "contains_raw_transcript": False,
        "evidence_policy": "short_redacted_snippets",
    }

    redactions = "# Redactions\n\n"
    if redaction_counts:
        for name, count in sorted(redaction_counts.items()):
            redactions += f"- {name}: {count}\n"
    else:
        redactions += "- No redactions were applied to the source content.\n"

    (destination / "summary.md").write_text(summary, encoding="utf-8")
    (destination / "evidence.md").write_text(evidence, encoding="utf-8")
    (destination / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (destination / "redactions.md").write_text(redactions, encoding="utf-8")
    (destination / "source-map.json").write_text(json.dumps(source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def collect_meta(memory_repo: Path) -> list[dict]:
    rows: list[dict] = []
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict):
            rows.append(meta)
    rows.sort(key=lambda row: row.get("source_updated_at", ""), reverse=True)
    return rows


def rebuild_indexes(memory_repo: Path) -> None:
    index_dir = memory_repo / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_meta(memory_repo)

    sessions_lines: list[str] = []
    project_latest: dict[str, dict] = {}
    for row in rows:
        session_row = {
            "date": str(row.get("source_updated_at", ""))[:10],
            "session_id": row.get("session_id", ""),
            "source_agent": row.get("source_agent", ""),
            "project": row.get("project", ""),
            "project_path": row.get("project_path", ""),
            "title": f"{row.get('project', '')}: {Path(str(row.get('source_record', ''))).name}",
            "user_intent": row.get("user_intent", ""),
            "summary": row.get("summary", ""),
            "reusable_facts": row.get("reusable_facts", []),
            "summary_path": row.get("summary_path", ""),
            "evidence_path": row.get("evidence_path", ""),
            "source_updated_at": row.get("source_updated_at", ""),
            "archive_status": row.get("archive_status", ""),
            "unresolved_count": len(row.get("unresolved_tasks", [])) if isinstance(row.get("unresolved_tasks"), list) else 0,
            "tags": row.get("tags") or ["agent-memory", "my-precious", slugify(str(row.get("project", "")))],
        }
        sessions_lines.append(json.dumps(session_row, sort_keys=True))
        project_key = str(row.get("project_path", ""))
        if project_key and project_key not in project_latest:
            project_latest[project_key] = {
                "project": row.get("project", ""),
                "project_path": project_key,
                "latest_source_updated_at": row.get("source_updated_at", ""),
                "latest_summary_path": row.get("summary_path", ""),
            }

    (index_dir / "sessions.jsonl").write_text("\n".join(sessions_lines) + ("\n" if sessions_lines else ""), encoding="utf-8")
    (index_dir / "projects.jsonl").write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in project_latest.values()) + ("\n" if project_latest else ""),
        encoding="utf-8",
    )
    decision_lines: list[str] = []
    unresolved_lines: list[str] = []
    file_lines: list[str] = []
    tag_lines: list[str] = []
    for row in rows:
        common = {
            "date": str(row.get("source_updated_at", ""))[:10],
            "session_id": row.get("session_id", ""),
            "source_agent": row.get("source_agent", ""),
            "project": row.get("project", ""),
            "summary_path": row.get("summary_path", ""),
        }
        decisions = row.get("decisions", []) if isinstance(row.get("decisions"), list) else []
        unresolved_tasks = row.get("unresolved_tasks", []) if isinstance(row.get("unresolved_tasks"), list) else []
        tags = row.get("tags", []) if isinstance(row.get("tags"), list) else []
        for decision in decisions:
            if is_noisy_text(decision):
                continue
            decision_lines.append(json.dumps({**common, "decision": decision, "confidence": "medium"}, sort_keys=True))
        for task in unresolved_tasks:
            if is_noisy_text(task):
                continue
            unresolved_lines.append(json.dumps({**common, "task": task, "priority": "medium"}, sort_keys=True))
        source_record = row.get("source_record")
        if isinstance(source_record, str) and source_record:
            file_lines.append(json.dumps({**common, "path": source_record, "action": "archived-source-record"}, sort_keys=True))
        for tag in tags:
            if is_noisy_text(tag):
                continue
            tag_lines.append(json.dumps({**common, "tag": tag}, sort_keys=True))
    (index_dir / "decisions.jsonl").write_text("\n".join(decision_lines) + ("\n" if decision_lines else ""), encoding="utf-8")
    (index_dir / "unresolved.jsonl").write_text("\n".join(unresolved_lines) + ("\n" if unresolved_lines else ""), encoding="utf-8")
    (index_dir / "files.jsonl").write_text("\n".join(file_lines) + ("\n" if file_lines else ""), encoding="utf-8")
    (index_dir / "tags.jsonl").write_text("\n".join(tag_lines) + ("\n" if tag_lines else ""), encoding="utf-8")

    recent = rows[:10]
    index_md = "# Agent Memory Index\n\n## How To Search\n\n```bash\npython tools/search_memory.py \"<query>\"\n```\n\n## Recent Sessions\n\n"
    if recent:
        for row in recent:
            index_md += f"- {str(row.get('source_updated_at', ''))[:10]} - {row.get('project', '')} - [{row.get('session_id', '')}]({row.get('summary_path', '')})\n"
    else:
        index_md += "No sessions archived yet.\n"
    index_md += "\n## Active Unresolved Threads\n\n"
    unresolved_rows = [row for row in rows if row.get("unresolved_tasks")]
    if unresolved_rows:
        for row in unresolved_rows[:10]:
            index_md += f"- Review unresolved tasks: [{row.get('session_id', '')}]({row.get('summary_path', '')})\n"
    else:
        index_md += "No unresolved work indexed yet.\n"
    index_md += "\n## Important Decisions\n\n"
    if decision_lines:
        for line in decision_lines[:10]:
            decision = json.loads(line)
            index_md += f"- {decision.get('project', '')}: {decision.get('decision', '')}\n"
    else:
        index_md += "No decisions indexed yet.\n"
    (memory_repo / "INDEX.md").write_text(index_md, encoding="utf-8")
    render_daily_summaries(memory_repo, rows)


def render_daily_summaries(memory_repo: Path, rows: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        day = str(row.get("source_updated_at", ""))[:10]
        if day:
            grouped.setdefault(day, []).append(row)
    for day, day_rows in grouped.items():
        year = day[:4]
        daily_dir = memory_repo / "daily" / year
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_md = f"# Agent Memory Daily Summary: {day}\n\n## Sessions\n\n"
        for row in day_rows:
            daily_md += f"- {row.get('project', '')}: [{row.get('session_id', '')}]({row.get('summary_path', '')})\n"
            summary = row.get("summary")
            if isinstance(summary, str) and summary.strip():
                daily_md += f"  - {summary.strip()}\n"
        daily_md += "\n## Decisions\n\n"
        decisions = [
            decision
            for row in day_rows
            for decision in (row.get("decisions", []) if isinstance(row.get("decisions"), list) else [])
        ]
        if decisions:
            daily_md += "".join(f"- {decision}\n" for decision in decisions)
        else:
            daily_md += "No decisions indexed for this day.\n"
        daily_md += "\n## Unresolved Tasks\n\n"
        unresolved = [
            task
            for row in day_rows
            for task in (row.get("unresolved_tasks", []) if isinstance(row.get("unresolved_tasks"), list) else [])
        ]
        if unresolved:
            daily_md += "".join(f"- {task}\n" for task in unresolved)
        else:
            daily_md += "No unresolved tasks indexed for this day.\n"
        (daily_dir / f"{day}.md").write_text(daily_md, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--source-dir", required=True, help="Directory containing source records to scan")
    parser.add_argument("--project-path", default=os.getcwd(), help="Project path used as the high-water-mark key")
    parser.add_argument("--project", help="Human-readable project name")
    parser.add_argument("--source-agent", default="agent", help="Source agent/runtime label")
    parser.add_argument("--pattern", action="append", help="Glob pattern to scan; may be repeated")
    parser.add_argument("--max-records", type=int, default=50, help="Maximum records to archive in one run")
    parser.add_argument("--max-excerpt-bytes", type=int, default=12000, help="Deprecated compatibility option; raw excerpts are not copied by default")
    parser.add_argument("--allow-redacted-secrets", action="store_true", help="Archive records with detected secret patterns after redaction")
    parser.add_argument(
        "--require-project-metadata",
        action="store_true",
        help="Only archive source records that explicitly identify the current project path",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show records that would be archived")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_repo = resolve_memory_repo(args.memory_repo)
    source_dir = Path(args.source_dir).expanduser().resolve()
    project_path = Path(args.project_path).expanduser().resolve()
    project_name = args.project or project_name_from_path(project_path)
    patterns = tuple(args.pattern or DEFAULT_PATTERNS)

    if not source_dir.exists() or not source_dir.is_dir():
        raise SystemExit(f"source directory not found: {source_dir}")
    if source_dir == project_path:
        print("warning: source-dir equals project-path; ensure this directory contains session records, not general source files", file=sys.stderr)

    latest, archived_hashes = archived_project_state(memory_repo, project_path)
    records = discover_records(
        source_dir,
        patterns,
        latest,
        project_path,
        archived_hashes,
        require_project_metadata=args.require_project_metadata,
    )
    if args.max_records >= 0:
        records = records[: args.max_records]

    print(f"Memory repo: {memory_repo}")
    print(f"Project path: {project_path}")
    print(f"Source dir: {source_dir}")
    print(f"Latest archived timestamp: {isoformat(latest) if latest else '<none>'}")
    print(f"Records selected: {len(records)}")

    for record in records:
        print(f"- {isoformat(record.updated_at)} {record.path}")

    if args.dry_run:
        return 0

    sensitive_records: list[tuple[SourceRecord, dict[str, int]]] = []
    for record in records:
        _, counts = redact_text(read_record_text(record.path))
        if counts:
            sensitive_records.append((record, counts))
    if sensitive_records and not args.allow_redacted_secrets:
        print("Refusing to archive records that match secret redaction patterns.", file=sys.stderr)
        for record, counts in sensitive_records:
            labels = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
            print(f"- {record.path}: {labels}", file=sys.stderr)
        print("Review the source records or rerun with --allow-redacted-secrets to store redacted snippets.", file=sys.stderr)
        return 2

    for record in records:
        write_record(
            memory_repo=memory_repo,
            project_path=project_path,
            project_name=project_name,
            source_agent=args.source_agent,
            record=record,
        )
    rebuild_indexes(memory_repo)
    print("Archive update complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
