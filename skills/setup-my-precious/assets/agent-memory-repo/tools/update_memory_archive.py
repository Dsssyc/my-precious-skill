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
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists() and (path / "index").exists() and (path / "sessions").exists():
            return path.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


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


def latest_archived_timestamp(memory_repo: Path, project_path: Path) -> datetime | None:
    project_key = str(project_path.resolve())
    latest: datetime | None = None

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
        for key in ("source_updated_at", "ended_at", "updated_at", "started_at", "date"):
            parsed = parse_timestamp(meta.get(key))
            if parsed and (latest is None or parsed > latest):
                latest = parsed

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
    elif path.suffix == ".json":
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            return


def record_matches_project(path: Path, text: str, project_path: Path) -> bool:
    discovered_paths: list[Path] = []
    for value in iter_source_json_values(path, text):
        for key, child in walk_json_values(value):
            if key in PROJECT_PATH_KEYS and isinstance(child, str) and child.strip():
                candidate = Path(child).expanduser()
                if candidate.is_absolute():
                    discovered_paths.append(candidate.resolve())
    if not discovered_paths:
        return True
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


def source_timestamp(path: Path, text: str) -> datetime:
    candidates: list[datetime] = []
    for value in iter_source_json_values(path, text):
        for key, child in walk_json_values(value):
            if key in TIMESTAMP_KEYS:
                parsed = parse_timestamp(child)
                if parsed:
                    candidates.append(parsed)
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


def discover_records(source_dir: Path, patterns: tuple[str, ...], after: datetime | None, project_path: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    seen: set[Path] = set()
    for path in iter_candidate_files(source_dir, patterns):
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        text = read_record_text(path)
        if not record_matches_project(path, text, project_path):
            continue
        updated_at = source_timestamp(path, text)
        if after is not None and updated_at <= after:
            continue
        records.append(SourceRecord(path=path, updated_at=updated_at, sha256=sha256_file(path)))
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


def value_to_line(value: object) -> str:
    if isinstance(value, dict):
        role = value.get("role") or value.get("type") or value.get("source") or "record"
        content = value.get("content") or value.get("text") or value.get("message") or value.get("summary")
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False, sort_keys=True)
        if isinstance(content, str) and content.strip():
            return f"{role}: {content}"
        return f"{role}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}"
    if isinstance(value, list):
        return " ".join(value_to_line(item) for item in value)
    return str(value)


def extract_source_lines(path: Path, text: str) -> list[str]:
    lines: list[str] = []
    if path.suffix == ".jsonl":
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                lines.append(value_to_line(json.loads(raw_line)))
            except json.JSONDecodeError:
                lines.append(raw_line)
    elif path.suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            lines.extend(text.splitlines())
        else:
            if isinstance(value, list):
                lines.extend(value_to_line(item) for item in value)
            else:
                lines.append(value_to_line(value))
    else:
        lines.extend(text.splitlines())
    return [clip(line) for line in lines if compact_whitespace(line)]


def select_lines(lines: list[str], pattern: str, limit: int = 5) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE)
    selected: list[str] = []
    for line in lines:
        if regex.search(line):
            selected.append(line)
            if len(selected) >= limit:
                break
    return selected


def bullet_list(items: list[str], fallback: str) -> str:
    if not items:
        return f"- {fallback}\n"
    return "".join(f"- {item}\n" for item in items)


def summarize_lines(lines: list[str], project_name: str) -> dict[str, object]:
    user_lines = select_lines(lines, r"^(user|human|request|prompt)\s*:", limit=3)
    if not user_lines:
        user_lines = lines[:2]
    decisions = select_lines(lines, r"\b(decision|decide|decided|choose|chosen|use|selected|决定|选择)\b", limit=5)
    problems = select_lines(lines, r"\b(error|failed|failure|blocked|exception|traceback|problem|issue|bug|失败|错误|阻塞)\b", limit=5)
    unresolved = select_lines(lines, r"\b(todo|next|follow[- ]?up|unresolved|remaining|later|下一步|后续|未完成)\b", limit=5)
    commands = select_lines(lines, r"(^|\s)(python|uv|git|npm|pnpm|yarn|cargo|go|pytest|make|rg|sed|awk)\b|`[^`]+`", limit=5)
    facts = select_lines(lines, r"\b(prefer|must|should|require|constraint|convention|policy|rule|约定|偏好|必须|应该)\b", limit=5)
    evidence = []
    for group in (user_lines, decisions, facts, problems, unresolved):
        for line in group:
            if line not in evidence:
                evidence.append(line)
            if len(evidence) >= 6:
                break
        if len(evidence) >= 6:
            break

    user_intent = user_lines[0] if user_lines else f"Archive source record for {project_name}."
    summary_items = []
    for line in [*user_lines[:2], *decisions[:2], *facts[:2]]:
        if line not in summary_items:
            summary_items.append(line)
    summary = " ".join(summary_items) if summary_items else f"Archived source record for {project_name}."
    tags = ["agent-memory", "my-precious", slugify(project_name)]
    for line in lines[:20]:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", line.lower()):
            if token not in tags and len(tags) < 12:
                tags.append(token)

    return {
        "user_intent": user_intent,
        "summary": summary,
        "context": lines[:5],
        "facts": facts,
        "decisions": decisions,
        "problems": problems,
        "unresolved": unresolved,
        "commands": commands,
        "evidence": evidence,
        "tags": tags,
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
    source_lines = extract_source_lines(record.path, redacted_text)
    summary_data = summarize_lines(source_lines, project_name)
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
{summary_data["summary"]}

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
            decision_lines.append(json.dumps({**common, "decision": decision, "confidence": "medium"}, sort_keys=True))
        for task in unresolved_tasks:
            unresolved_lines.append(json.dumps({**common, "task": task, "priority": "medium"}, sort_keys=True))
        source_record = row.get("source_record")
        if isinstance(source_record, str) and source_record:
            file_lines.append(json.dumps({**common, "path": source_record, "action": "archived-source-record"}, sort_keys=True))
        for tag in tags:
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

    latest = latest_archived_timestamp(memory_repo, project_path)
    records = discover_records(source_dir, patterns, latest, project_path)
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
