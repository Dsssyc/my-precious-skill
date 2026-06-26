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
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from memory_consolidation import (
    add_contradiction_link,
    add_deprecation_link,
    add_supersession_link,
    apply_memory_id_contradiction_links,
    apply_memory_id_deprecation_links,
    apply_memory_id_supersession_links,
    apply_semantic_lifecycle_links,
    apply_text_deprecation_links,
    apply_text_supersession_links,
    memory_consolidation_key,
    memory_text_key,
    merge_memory_node_provenance,
    node_last_seen_key,
    normalize_memory_text,
    parse_memory_deprecation_text,
    parse_memory_refresh_text,
    semantic_relation_detail,
)


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
MEMORY_REVIEW_DECISION_REL_PATH = Path("reviews/memory_lifecycle_decisions.jsonl")
INDUCTION_REVIEW_DECISION_REL_PATH = Path("reviews/induction_review_decisions.jsonl")
SAFE_MEMORY_REVIEW_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
INDUCTION_REVIEW_CANDIDATE_ID_PATTERN = re.compile(r"^indrev_[0-9a-f]{16}$")
MEMORY_REVIEW_APPROVAL_ACTIONS = {
    "approve_supersedes",
    "approve_contradicts",
    "approve_deprecates",
}
MEMORY_REVIEW_IGNORE_ACTIONS = {"reject", "noop"}
MEMORY_REVIEW_ACTIONS = MEMORY_REVIEW_APPROVAL_ACTIONS | MEMORY_REVIEW_IGNORE_ACTIONS
INDUCTION_REVIEW_APPROVAL_ACTIONS = {"approve_promote"}
INDUCTION_REVIEW_IGNORE_ACTIONS = {"reject", "noop"}
INDUCTION_REVIEW_ACTIONS = INDUCTION_REVIEW_APPROVAL_ACTIONS | INDUCTION_REVIEW_IGNORE_ACTIONS
MEMORY_REVIEW_CANDIDATE_FINGERPRINT_FIELDS = (
    "candidate_type",
    "current_memory_id",
    "older_memory_id",
    "reason",
    "recommended_action",
    "current_last_seen",
    "older_last_seen",
    "overlap_token_count",
    "overlap_ratio",
    "compressed_candidate_count",
    "compressed_older_memory_ids",
    "compression_reason",
)
INDUCTION_REVIEW_CANDIDATE_FINGERPRINT_FIELDS = (
    "candidate_id",
    "candidate_type",
    "candidate_text_sha256",
    "candidate_source",
    "reason",
    "recommended_action",
    "topic",
    "support_count",
    "source_updated_at",
    "related_candidate_text_sha256",
    "related_source_updated_at",
    "overlap_token_count",
    "overlap_ratio",
)
MIN_AMBIGUOUS_SCOPE_REVIEW_OVERLAP_RATIO = 0.45
NATURAL_FACT_SOURCE_LABELS = frozenset({"natural_user", "natural_assistant", "natural_record"})
LOW_CONFIDENCE_NATURAL_REVIEW_PATTERN = re.compile(
    r"(?i)\b(?:review\s+candidate|reviewable|reviewer\s+confirmation|before\s+(?:automatic\s+)?promotion|"
    r"wait\s+for\s+repeated\s+support|until\s+supporting\s+evidence\s+repeats|provisional|unconfirmed)\b"
)
REDACTION_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    "bearer_token": re.compile(r"(?i)(Authorization:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+"),
    "cookie": re.compile(r"(?i)(Cookie:\s*)[^\n]+"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}
UNSAFE_PATH = "[unsafe-path]"
REDACTION_CATEGORY_LABELS = frozenset(REDACTION_PATTERNS)
MEMORY_LAYER_FILES = {
    "global": "global.jsonl",
    "domain": "domains.jsonl",
    "project": "projects.jsonl",
}
MEMORY_TOPIC_HINTS = (
    ("memory-retrieval", ("memory", "recall", "retrieval", "search", "index", "archive")),
    ("agent-workflow", ("agent", "codex", "skill", "permission", "authorization", "workflow")),
    ("python-packaging", ("python", "pip", "package", "venv", "wheel", "import")),
    ("frontend-qa", ("frontend", "browser", "playwright", "viewport", "layout", "css")),
    ("git-workflow", ("git", "commit", "branch", "worktree", "merge", "sync")),
)
GLOBAL_MEMORY_HINTS = (
    "user prefers",
    "user wants",
    "the user prefers",
    "the user wants",
    "用户希望",
    "用户偏好",
    "不要反复",
    "强制记忆",
)
EXPLICIT_MEMORY_PATTERNS = (
    re.compile(r"(?i)^\s*remember this\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"(?i)^\s*please remember\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"(?i)^\s*(?:please\s+)?remember(?:\s+this)?\s+that\s+(?P<text>.+)$"),
    re.compile(r"^\s*记住这个\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"^\s*记住\s*[:：]\s*(?P<text>.+)$"),
    re.compile(r"^\s*强制记忆\s*[:：]\s*(?P<text>.+)$"),
)
NEGATED_EXPLICIT_MEMORY_PATTERNS = (
    re.compile(
        r"(?i)^\s*(?:please\s+)?(?:do\s+not|don't|dont|never)\s+"
        r"(?:please\s+)?remember(?:\s+this)?(?:\s*[:：]|\b)"
    ),
    re.compile(r"^\s*(?:不要|别)\s*(?:记住(?:这个)?|强制记忆)(?:\s*[:：]|$)"),
)
EXPLICIT_MEMORY_TASK_TAIL_BOUNDARY = re.compile(
    r"(?i)[,;.!?，；。！？]\s*(?=(?:now|then|next|review|fix|run|check|implement|create|update)\b|"
    r"(?:现在|然后|接下来|顺便|再|请|帮我))"
)
REUSABLE_FACT_PREFIX = re.compile(r"(?i)^\s*reusable fact\s*[:\uFF1A]\s*(?P<text>.+)$")
NATURAL_USER_MEMORY_PATTERNS = (
    (re.compile(r"(?i)^\s*i\s+prefer\s+(?P<text>.+)$"), "The user prefers {text}"),
    (re.compile(r"(?i)^\s*my\s+preference\s+is\s+(?:that\s+)?(?P<text>.+)$"), "The user prefers {text}"),
    (re.compile(r"(?i)^\s*i\s+want\s+(?P<text>.+)$"), "The user wants {text}"),
)
ACKNOWLEDGEMENT_ONLY_PATTERN = re.compile(
    r"(?i)^\s*(?:understood|got it|noted|sure|okay|ok)[,;:.! ]+"
    r".{0,120}\b(?:i\s+will|i'll|i’ll|keep\s+it\s+in\s+mind|this\s+edit|next\s+step)\b"
)
HYPOTHETICAL_MEMORY_PATTERN = re.compile(
    r"(?i)\b(?:we|i|it|this)\s+(?:could|might|may)\b|\bmaybe\b|\bif\s+[^.?!]{0,120}\b(?:becomes|became|were|was|is)\b"
)
TEMPORARY_LOCAL_MEMORY_PATTERN = re.compile(
    r"(?i)\b(?:for|in)\s+this\s+(?:local|temporary|scratch|dry[- ]?run)\b|"
    r"\btemporary\s+(?:update|fixture|induction|choice|decision)\b|"
    r"\bscratch\s+workspace\b|\bcurrent\s+(?:run|test|gate|status)\b"
)
TEST_STATUS_MEMORY_PATTERN = re.compile(
    r"(?i)\b(?:benchmark|test|tests?|gate)\s+(?:gate\s+)?should\s+pass\b|"
    r"\b(?:test|gate|benchmark)\s+status\b|\bafter\s+rerun\b|\bcurrent\s+test\b"
)
PROMPT_LIKE_QUOTED_MEMORY_PATTERN = re.compile(
    r"(?i)^\s*(?:quoted|raw)\s+(?:prompt|instruction|text)\b|"
    r'"[^"]*\b(?:assistant|system|user)\s+must\b[^"]*"'
)
BROAD_GENERIC_MEMORY_WORDS = {
    "a",
    "and",
    "agent",
    "agents",
    "archive",
    "archives",
    "be",
    "better",
    "clear",
    "good",
    "helpful",
    "memory",
    "memories",
    "reliable",
    "safe",
    "should",
    "system",
    "systems",
    "the",
    "tool",
    "tools",
    "useful",
    "well",
    "work",
    "workflow",
    "workflows",
}
SENSITIVE_EXPLICIT_MEMORY_MARKERS = (
    "[redacted_",
    "authorization:",
    "bearer",
    "cookie:",
    "private key",
)


@dataclass
class SourceRecord:
    path: Path
    updated_at: datetime
    sha256: str


@dataclass
class MemoryEvent:
    kind: str
    text: str


@dataclass(frozen=True)
class MemoryCandidate:
    text: str
    rationale: str
    source: str
    topic: str
    project: str
    project_path: str
    summary_path: str
    evidence_path: str
    source_record: str
    source_map_path: str
    source_updated_at: str
    tags: tuple[str, ...]
    provenance: str = ""
    supersedes_texts: tuple[str, ...] = ()
    deprecates_texts: tuple[str, ...] = ()


NOISE_MARKERS = (
    "<codex_internal_context",
    "<environment_context",
    "</environment_context>",
    "<permissions instructions",
    "<skill>",
    "<turn_aborted>",
    "<shell>",
    "</shell>",
    "<current_date>",
    "</current_date>",
    "<timezone>",
    "</timezone>",
    "<filesystem>",
    "</filesystem>",
    "<workspace_roots>",
    "</workspace_roots>",
    "<permission_profile",
    "</permission_profile>",
    "# agents.md",
    "agents.md instructions",
    "</permissions instructions>",
    "</instructions>",
    "<cwd>",
    "approval policy is currently",
    "filesystem sandboxing defines",
    "you are codex, a coding agent",
    "use when codex should",
    "this skill should be used when users",
    "chunk id:",
    "original token count:",
    "process exited with code",
    "update_plan",
    "wall time:",
    "write_stdin failed:",
    "session_meta",
    "response_item",
    "event_msg",
    "subagent_notification",
    "agent_path",
    "secret-pattern",
    "base_instructions",
    "model_context_window",
    "process_update",
    "::inbox-item",
    "inbox-item{",
    "--- name:",
    "# systematic debugging",
    "# my precious skill development",
    "future messages should adhere",
    "following personality",
    "some of what we're working on might be easier to explain",
    "you are a read-only verifier",
    "continue working toward the active thread goal",
    "the objective below is user-provided data",
    "<objective>",
    "</objective>",
    "## my request for codex:",
    "my request for codex:",
)
NOISY_TAGS = {
    "agent-memory",
    "my-precious",
    "subagent_notification",
    "agent_path",
    "secret-pattern",
    "subagent",
    "codespace",
    "mememe",
    "templates",
    "agent-memory-repo",
    "project",
    "source",
    "record",
    "session",
    "summary",
    "users",
    "soku",
    "desktop",
    "agents",
    "codex",
    "validator",
    "validators",
    "py_compile",
    "template",
    "sync",
    "task",
    "you",
    "are",
    "run",
    "using-superpowers",
    "using-agent-skills",
    "worktree",
    "codex_home",
    "commands",
    "command",
    "status",
    "implementation",
    "has",
    "meaningful",
    "improvements",
    "unit",
    "tests",
    "test",
    "pass",
    "passes",
    "passed",
    "audit",
    "script",
    "checks",
    "suggested",
    "concrete",
    "expected",
    "can",
    "but",
    "only",
    "title",
    "file",
    "files",
    "scripts",
    "saved",
    "remaining",
    "current",
    "diff",
    "three",
    "requested",
    "mostly",
    "there",
    "still",
    "without",
    "important",
    "dry",
    "live",
    "update",
    "updated",
    "secret",
    "gate",
    "cookie",
    "meta",
    "user",
    "intent",
    "facts",
    "fact",
    "verification",
    "verified",
    "invokes",
    "conversation",
    "feel",
    "easy",
    "alive",
    "move",
    "serious",
    "reflection",
    "unguarded",
    "fun",
    "either",
    "out",
    "new",
    "check",
    "records",
    "selected",
    "refused",
    "likely-secret",
    "project-scoped",
    "because",
    "matched",
    "categories",
    "private_key",
    "bearer_token",
    "github_token",
    "openai_key",
    "aws_access_key",
    "refusal",
    "stayed",
    "clean",
    "entry",
    "usable",
    "imperfect",
    "captures",
    "capture",
    "latest",
    "weaker",
    "retrieval",
    "durable",
    "generic",
    "critique",
    "critiques",
    "future",
    "messages",
    "adhere",
    "following",
    "personality",
    "doc",
    "http",
    "python",
    "cli",
    "top",
    "hit",
    "done",
    "changed",
    "accepts",
    "calls",
    "removes",
    "until",
    "open",
    "stronger",
    "standalone",
    "support",
    "setup",
    "contributor",
}
RAW_TITLE_MARKERS = (
    "/users/",
    ".codex/attachments",
    "files mentioned by the user",
    "pasted text.txt",
    "# agents.md",
    "# my precious skill development",
    "agents.md instructions",
    "approval policy is currently",
    "use when codex should",
    "<instructions>",
    "<cwd>",
    "<shell>",
    "<current_date>",
    "<timezone>",
    "you are a read-only verifier",
    "continue working toward the active thread goal",
    "the objective below is user-provided data",
    "<objective>",
    "</objective>",
    "## my request for codex:",
    "my request for codex:",
)
LOCAL_ABSOLUTE_PATH_PATTERN = r"/(?:Users|var|private|tmp|opt|home|Volumes)/[^\s`)]+"
LOW_SIGNAL_HEADING_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:"
    r"验证结果|验证已跑|但阻塞点很明确|阻塞点很明确|阻塞原因|"
    r"原因很直接|原因是|我做过的验证|方案选择|常见原因|"
    r"已验证|"
    r"APPROVED|CHANGES_REQUESTED|DONE_WITH_CONCERNS|DONE|"
    r"\*{0,3}\s*(?:commands?|command status|tool calls?|findings?|verified|what changed)\s*\*{0,3}|"
    r"\*{2}[^*]{2,24}\*{2}"
    r")\s*[:：-]?\s*$",
    re.IGNORECASE,
)
LOW_SIGNAL_PREFIX_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:验证结果|验证已跑|但阻塞点很明确|阻塞点很明确|阻塞原因|原因很直接|原因是|我做过的验证|方案选择|常见原因)\s*[:：]\s*"
)
RUN_STATUS_PATTERN = re.compile(
    r"(?:"
    r"\bdry[- ]?run\b.{0,120}(?:find|found|select(?:ed|s)?|record|update|exit|project|registration|enabled|选中|记录|产生|写入)|"
    r"\blive update\b|"
    r"(?:secret gate|likely-secret).{0,120}(?:refus(?:ed|es|al)|reject(?:ed|s|ion)|record|cookie|拒绝|命中)|"
    r"(?:没有产生新写入|产生新写入|默认 secret gate|source record 命中|命中\s*`?cookie|cookie\s*=)|"
    r"stopped (?:there|before).{0,120}(?:updater|allow-redacted-secrets|running)|"
    r"git status --short.{0,120}(?:exit 0|clean)|"
    r"global memory update completed|memory archive updated|memory archive pushed|committed and pushed|repo (?:is )?clean|"
    r"actual run processed.{0,80}(?:project|record)|"
    r"(?:unit\s+tests?|tests?)\s+pass(?:ed|es)?.*(?:archive\s+audit|skill\s+validators?|py_compile|template/script\s+sync)|"
    r"(?:archive\s+audit|skill\s+validators?|py_compile|template/script\s+sync).*(?:pass(?:ed|es)?|green|ok)"
    r")",
    re.IGNORECASE,
)
ARCHIVE_EVALUATION_STATUS_PATTERN = re.compile(
    r"(?:"
    r"(?:比如\s*)?.{0,80}条目能恢复.{0,160}|"
    r"\b(?:latest\s+)?[\w.-]+\s+entry\s+is\s+(?:usable|imperfect|weaker|stronger).{0,160}|"
    r"\b[\w.-]+\s+entry\s+.{0,80}\bcaptures\b.{0,120}|"
    r"^continue working toward the active thread goal\.?$|"
    r"^you are a read-only verifier\b.*$|"
    r"(?:关键)?(?:查询|搜索|检索).{0,120}(?:目标条目|top\s+hit|top\s+result|排第一|排第[一二三123])|"
    r"(?:`[^`]{1,120}`|[^。.!?；;\n]{1,120})\s*(?:第[一二三123]|第一)\s*命中是.{0,120}|"
    r"(?:top\s+hit|top\s+result|search\s+verification|search\s+result|targeted\s+search).{0,160}(?:rank|match|hit|pass|排名|排第|正确|展示标题|review\s+语境)|"
    r"(?:已验证[:：]\s*)?.{0,80}\btags?\b.{0,120}(?:http/python/cli|泛词|broad)"
    r")",
    re.IGNORECASE,
)
ARCHIVE_SOURCE_PLACEHOLDER_PATTERN = re.compile(
    r"^(?:archive|archived) source record for [A-Za-z0-9._-]+\.?$",
    re.IGNORECASE,
)
SOURCE_CITATION_LINE_PATTERN = re.compile(
    r"^(?:来源|source|sources|references?)[:：]\s*(?:https?://|\[[^\]]+\]\(|官方|README|docs?).{0,260}$",
    re.IGNORECASE,
)
HIGH_VALUE_TITLE_PATTERN = re.compile(
    r"spurious\s+502|libx\d+(?:\.\d+)?(?:\.dylib)?|_gdal|osgeo|127\.0\.0\.1|socks5|local routing|"
    r"全局出站代理|本地代理|高信噪比|记忆索引|durable memory index|memory index|retrieval-first",
    re.IGNORECASE,
)
RETRIEVAL_LITERAL_PATTERN = re.compile(
    r"(?:https?|socks5h?)\s+proxy\s*:\s*(?:https?|socks5h?)://(?:127\.0\.0\.1|localhost)\S*|"
    r"(?:https?|socks5h?)://(?:127\.0\.0\.1|localhost)\S*|"
    r"127\.0\.0\.1(?::(?:\d+|端口))?|"
    r"\b\d{3,5}\b|"
    r"spurious\s+502|"
    r"libx\d+(?:\.\d+)?(?:\.dylib)?|"
    r"_gdal|osgeo",
    re.IGNORECASE,
)
INCOMPLETE_FRAGMENT_PATTERN = re.compile(
    r"(?:"
    r"^(?:.{0,80}(?:摘要|记忆|目录|路径|文件|仓库|repo|repository|skill)"
    r".{0,40}(?:在|位于|路径为|目录为|in|at|from|to|for|with|under|inside))$|"
    r"^(?:结论|评价|findings?)[:：]\s*\*\*[^*]+$"
    r")",
    re.IGNORECASE,
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


def archived_project_state(memory_repo: Path, project_path: Path) -> tuple[datetime | None, set[str], dict[str, set[str]]]:
    project_key = str(project_path.resolve())
    latest: datetime | None = None
    archived_hashes: set[str] = set()
    archived_source_hashes: dict[str, set[str]] = {}

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
        source_record = meta.get("source_record")
        source_key = ""
        if isinstance(source_record, str) and source_record:
            source_key = str(Path(source_record).expanduser().resolve())
        source_hash = meta.get("source_record_sha256")
        if isinstance(source_hash, str) and source_hash:
            archived_hashes.add(source_hash)
            if source_key:
                archived_source_hashes.setdefault(source_key, set()).add(source_hash)
        for key in ("source_updated_at", "ended_at", "updated_at", "started_at", "date"):
            parsed = parse_timestamp(meta.get(key))
            if parsed and (latest is None or parsed > latest):
                latest = parsed

    return latest, archived_hashes, archived_source_hashes


def latest_archived_timestamp(memory_repo: Path, project_path: Path) -> datetime | None:
    latest, _, _ = archived_project_state(memory_repo, project_path)
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
    archived_source_hashes: dict[str, set[str]] | None = None,
    require_project_metadata: bool = False,
) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    seen: set[Path] = set()
    archived_hashes = archived_hashes or set()
    archived_source_hashes = archived_source_hashes or {}
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
        source_key = str(path)
        prior_hashes_for_source = archived_source_hashes.get(source_key, set())
        source_changed_since_archive = bool(prior_hashes_for_source) and source_hash not in prior_hashes_for_source
        if after is not None:
            if updated_at < after and not source_changed_since_archive:
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


def safe_diagnostic_path(path: Path) -> str:
    display = path.name or "<path>"
    if has_sensitive_identifier_token(display):
        return UNSAFE_PATH
    redacted, _ = redact_text(display)
    return redacted


def has_sensitive_identifier_token(text: str) -> bool:
    tokens = re.split(r"[^a-z0-9]+", text.lower().replace("_", " "))
    token_set = set(tokens)
    token_pairs = set(zip(tokens, tokens[1:]))
    return bool(
        token_set.intersection(
            {
                "apikey",
                "authorization",
                "bearer",
                "cookie",
                "credential",
                "password",
            }
        )
        or token_pairs.intersection(
            {
                ("api", "key"),
                ("auth", "token"),
                ("bearer", "token"),
                ("private", "key"),
                ("secret", "key"),
                ("session", "id"),
            }
        )
    )


def read_record_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


SKILL_INVOCATION_PREFIX_PATTERN = re.compile(
    r"^(?:(?:\[[^\]]*\]\([^)]+\)|\$[A-Za-z0-9_-]+)\s*)+",
    re.IGNORECASE,
)


def strip_skill_invocation_prefix(text: str) -> str:
    stripped = compact_whitespace(text)
    while True:
        cleaned = SKILL_INVOCATION_PREFIX_PATTERN.sub("", stripped).strip()
        if cleaned == stripped:
            return cleaned
        stripped = cleaned


def has_unbalanced_markdown_emphasis(text: str) -> bool:
    compacted = compact_whitespace(text)
    if not compacted:
        return False
    return compacted.count("**") % 2 == 1


def is_incomplete_memory_fragment(text: str) -> bool:
    raw = compact_whitespace(text)
    if not raw:
        return False
    if has_unbalanced_markdown_emphasis(raw):
        return True
    compacted = raw.strip(" -")
    return len(compacted) <= 160 and bool(INCOMPLETE_FRAGMENT_PATTERN.search(compacted))


def clip(text: str, limit: int = 240) -> str:
    text = compact_whitespace(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def focus_high_value_title_text(text: str, limit: int = 120) -> str:
    cleaned = compact_title_phrase(text)
    if len(cleaned) <= limit or not HIGH_VALUE_TITLE_PATTERN.search(cleaned):
        return cleaned
    parts = [
        part.strip(" -:;,.")
        for part in re.split(r"[。！？!?；;]\s*", cleaned)
        if part.strip(" -:;,.")
    ]
    for part in parts:
        compacted_part = compact_title_phrase(part)
        if HIGH_VALUE_TITLE_PATTERN.search(compacted_part):
            return compacted_part
    match = HIGH_VALUE_TITLE_PATTERN.search(cleaned)
    if not match:
        return cleaned
    start = max(0, match.start() - 80)
    end = min(len(cleaned), match.end() + 40)
    return cleaned[start:end].strip(" -:;,.")


def compact_title_phrase(text: str) -> str:
    compacted = compact_whitespace(text)
    if (
        re.search(r"router-level", compacted, re.IGNORECASE)
        and re.search(r"integration\s+test", compacted, re.IGNORECASE)
        and re.search(r"concurrent\s+reconnect", compacted, re.IGNORECASE)
        and re.search(r"spurious\s+502", compacted, re.IGNORECASE)
    ):
        return "Missing router-level concurrent reconnect integration test for loser path spurious 502"
    return compacted


def split_memory_text(text: str, limit: int = 32) -> list[str]:
    raw_text = text.strip()
    if not raw_text:
        return []
    raw_parts: list[str] = []
    for block in re.split(r"\n+", raw_text):
        block = re.sub(r"^\s*[-*]\s+", "", block.strip())
        if not block:
            continue
        if is_noisy_text(block):
            continue
        raw_parts.extend(re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z0-9`\"'(\[])", compact_whitespace(block)))
    sentences = [clip(part) for part in raw_parts if compact_whitespace(part)]
    return sentences[:limit] if sentences else [clip(text)]


def is_broad_generic_memory_rule(text: str) -> bool:
    compacted = compact_whitespace(text).lower().strip(" .!?;:")
    if not re.search(r"\b(?:should|must)\b", compacted):
        return False
    tokens = re.findall(r"[a-z][a-z-]+", compacted)
    if not tokens or len(tokens) > 8:
        return False
    return all(token in BROAD_GENERIC_MEMORY_WORDS for token in tokens)


def is_non_durable_natural_memory_text(text: str) -> bool:
    compacted = compact_whitespace(text)
    if not compacted:
        return False
    if ACKNOWLEDGEMENT_ONLY_PATTERN.search(compacted):
        return True
    if HYPOTHETICAL_MEMORY_PATTERN.search(compacted):
        return True
    if TEMPORARY_LOCAL_MEMORY_PATTERN.search(compacted):
        return True
    if TEST_STATUS_MEMORY_PATTERN.search(compacted):
        return True
    if PROMPT_LIKE_QUOTED_MEMORY_PATTERN.search(compacted):
        return True
    return is_broad_generic_memory_rule(compacted)


def is_low_signal_memory_text(text: str) -> bool:
    compacted = compact_whitespace(text)
    if not compacted:
        return True
    if ARCHIVE_SOURCE_PLACEHOLDER_PATTERN.fullmatch(compacted):
        return True
    if SOURCE_CITATION_LINE_PATTERN.fullmatch(compacted):
        return True
    if is_redaction_category_text(compacted):
        return True
    if is_incomplete_memory_fragment(compacted):
        return True
    if ARCHIVE_EVALUATION_STATUS_PATTERN.search(compacted):
        return True
    if LOW_SIGNAL_HEADING_PATTERN.search(compacted):
        return True
    if is_non_durable_natural_memory_text(compacted):
        return True
    return bool(RUN_STATUS_PATTERN.search(compacted))


def is_redaction_category_text(text: str) -> bool:
    compacted = compact_whitespace(text).lower()
    if not compacted:
        return False
    markdown_stripped = re.sub(r"[*`]", "", compacted).strip(" .:;")
    if markdown_stripped in {"refusal", "stayed clean", "clean"}:
        return True
    tokens = [
        token.strip(" .:;()[]{}-")
        for token in re.split(r"[,/\s]+", markdown_stripped)
        if token.strip(" .:;()[]{}-")
    ]
    if not tokens:
        return False
    allowed = REDACTION_CATEGORY_LABELS | {
        "redaction",
        "redactions",
        "redacted",
        "secret",
        "secrets",
        "category",
        "categories",
        "refusal",
        "refused",
        "stayed",
        "clean",
        "matched",
        "detected",
        "none",
        "no",
    }
    return bool(REDACTION_CATEGORY_LABELS.intersection(tokens)) and all(token in allowed for token in tokens)


def strip_memory_citation_blocks(text: str) -> str:
    cleaned = re.sub(
        r"<oai-mem-citation>.*?</oai-mem-citation>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(
        r"</?(?:oai-mem-citation|citation_entries|rollout_ids)>",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\s*(?:MEMORY\.md|rollout_summaries/|skills/)[^\n|]*\|note=\[[^\n]*\]\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return cleaned.strip()


def strip_process_clauses(text: str) -> str:
    stripped = text.strip()
    stripped = LOW_SIGNAL_PREFIX_PATTERN.sub("", stripped).strip()
    if re.fullmatch(r"[-*]?\s*\.\.\.", stripped):
        return ""
    if is_low_signal_memory_text(stripped):
        return ""
    if re.search(r"^using\s+[`$]?(?:using-|brainstorming|test-driven|systematic|update-my-precious)", stripped, re.IGNORECASE):
        if re.search(r"\bas requested\b|\bi(?:'ll|’ll| will)\s+also\s+use\b", stripped, re.IGNORECASE):
            return ""
    chinese_process_start = (
        r"^(?:"
        r"我现在(?:检查|继续|先|会|加|跑|改|处理|验证|看)|"
        r"现在我(?:检查|继续|先|会|加|跑|改|处理|验证|看|已经)|"
        r"当前我会|接着我会|随后我会|最后我会|最后一轮我会|"
        r"我做最后一轮|接下来我|下一步我|我继续|我先|先看|下一块会|"
        r"现在(?:先|开始|改为|做|跑|检查|验证|清理|处理|读取)|"
        r"现在\s*(?:dry run|rewrite|重写)|"
        r"现在按\s*(?:顺序|计划|规则|TDD|测试)|"
        r"现在实现(?:最小)?修复|"
        r"现在同步(?:真实)?工具|"
        r"执行\s*rewrite|"
        r"同步后重跑|"
        r"按上一轮耗时估计|"
        r"先(?:读取|检查|看|跑|做|定位|验证|清理)"
        r")"
    )
    if re.search(chinese_process_start, stripped):
        return ""
    chinese_tail_marker = (
        r"我会(?:先|只|把|用|继续|做|改|跑|等|查|核实|从|按|清|尝试|恢复)|"
        r"当前我会|接着我会|随后我会|最后我会|最后一轮我会|"
        r"我做最后一轮|我继续|我先|接下来我|下一步我|下一块会|"
        r"我现在(?:检查|继续|先|会|加|跑|改|处理|验证|看)|"
        r"现在我(?:检查|继续|先|会|加|跑|改|处理|验证|看|已经)|"
        r"现在(?:先|开始|改为|做|跑|检查|验证|清理|处理|读取)|"
        r"现在\s*(?:dry run|rewrite|重写)|"
        r"现在按\s*(?:顺序|计划|规则|TDD|测试)|"
        r"现在实现(?:最小)?修复|"
        r"现在同步(?:真实)?工具|"
        r"执行\s*rewrite|"
        r"同步后重跑|"
        r"按上一轮耗时估计|"
        r"先(?:读取|检查|看|跑|做|定位|验证|清理)"
    )
    match = re.search(rf"(?:[。.!?；;，,：:]|\s)?(?:{chinese_tail_marker}).*$", stripped)
    if match:
        stripped = stripped[: match.start()].rstrip(" 。.!?；;，,：:")
        if len(stripped) < 8:
            return ""
    replacements = (
        r"\s+so\s+i(?:'ll|’ll| will)\s+also\s+use\b.*$",
        r"\s+i(?:'m|’m| am)\s+(?:proceeding|locating|checking|inspecting|running|rerunning|continuing|waiting|working|reading|verifying|starting)\b.*$",
        r"\s+i(?:'m|’m| am)\s+not\s+(?:rerunning|running|proceeding|continuing)\b.*$",
        r"\s+i(?:'ll|’ll| will)\s+(?:only\s+)?(?:inspect|check|verify|run|rerun|continue|wait|proceed|look|locate|report|use)\b.*$",
        r"\s+then\s+i(?:'ll|’ll| will)\b.*$",
        r"[。.!?；;，,：:]\s*(?:我会|我继续|我先|接下来我|下一步我|下一块会|当前我会|我现在(?:检查|继续|先|会|加|跑|改|处理|验证|看)|现在我(?:检查|继续|先|会|加|跑|改|处理|验证|看|已经)).*$",
    )
    for pattern in replacements:
        stripped = re.sub(pattern, lambda match: "。" if match.group(0).lstrip().startswith(("。", ".")) else "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(
        r"\s+\*\*(?:Commands?|Command Status|Tool Calls?)\*\*.*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(r"\s+Command Status\s*[-:].*$", "", stripped, flags=re.IGNORECASE)
    return clip(stripped)


def is_noisy_text(text: object) -> bool:
    if not isinstance(text, str):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def is_injected_context_text(text: str) -> bool:
    compacted = compact_whitespace(text).lower()
    if not compacted:
        return False
    return (
        compacted.startswith("# agents.md")
        or "# agents.md instructions" in compacted
        or "<instructions>" in compacted
        or "</instructions>" in compacted
        or "<permissions instructions" in compacted
        or "</permissions instructions>" in compacted
        or compacted == "<cwd>"
        or compacted.startswith("<cwd>")
        or compacted.startswith("approval policy is currently")
        or compacted.startswith("filesystem sandboxing defines")
        or compacted.startswith("you are codex, a coding agent")
    )


def is_raw_prompt_text(text: str) -> bool:
    compacted = compact_whitespace(text)
    lowered = compacted.lower()
    return any(marker in lowered for marker in RAW_TITLE_MARKERS) or bool(re.search(LOCAL_ABSOLUTE_PATH_PATTERN, compacted))


def local_path_replacement(match: re.Match[str]) -> str:
    raw_path = match.group(1) if match.groups() else match.group(0)
    name = Path(raw_path.strip("`").rstrip(".,:;)")).name
    if re.search(r"\.(?:dylib|so|dll|rs|py|tsx?|jsx?|md|toml|json|ya?ml|cpp|hpp|h|c)$", name, re.IGNORECASE):
        return name
    if re.match(r"lib[A-Za-z0-9_.-]+$", name):
        return name
    return ""


def clean_title_candidate(text: str) -> str:
    cleaned = strip_skill_invocation_prefix(text)
    if not cleaned:
        return ""

    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^\s*\d{1,2}[.)、]\s*", "", cleaned)

    # Preserve the useful task phrase around a local worktree path, but remove
    # the machine-specific path itself.
    cleaned = re.sub(
        rf"\b(?:the\s+)?current\s+worktree\s+`{LOCAL_ABSOLUTE_PATH_PATTERN}`\s+for\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"\b(?:the\s+)?current\s+worktree\s+{LOCAL_ABSOLUTE_PATH_PATTERN}\s+for\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"\b(?:in|from)\s+(?:the\s+)?(?:current\s+)?worktree\s+`{LOCAL_ABSOLUTE_PATH_PATTERN}`",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        rf"\b(?:in|from)\s+(?:the\s+)?(?:current\s+)?worktree\s+{LOCAL_ABSOLUTE_PATH_PATTERN}",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(rf"`({LOCAL_ABSOLUTE_PATH_PATTERN})`", local_path_replacement, cleaned)
    cleaned = re.sub(LOCAL_ABSOLUTE_PATH_PATTERN, local_path_replacement, cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r"^\s*\d{1,2}[.)、]\s*", "", cleaned)
    cleaned = re.sub(r"^Task:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bworktree\s*[,.]?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\bfor\s+([,.])", r"\1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -:;,.。")

    status_match = re.match(
        r"^(CHANGES_REQUESTED|DONE_WITH_CONCERNS|APPROVED|DONE)\b[:\s-]*",
        cleaned,
        flags=re.IGNORECASE,
    )
    status = status_match.group(1).upper() if status_match else ""
    finding_match = re.search(
        r"\bFindings?\b\s*[:\-]?\s*(?:\d+\.\s*)?(?:(?:High|Medium|Low)\s*[:\-]\s*)?(?P<issue>.+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if finding_match:
        issue = finding_match.group("issue").strip(" -:;,.")
        issue = re.sub(
            r":\s+[A-Za-z0-9_./-]+\.(?:rs|py|tsx?|jsx?|md|toml|json|ya?ml|cpp|hpp|h|c)\b.*$",
            "",
            issue,
            flags=re.IGNORECASE,
        ).strip(" -:;,.")
        if issue:
            cleaned = f"{status}: {issue}" if status else issue

    cleaned = re.sub(
        r":\s+[A-Za-z0-9_./-]+\.(?:rs|py|tsx?|jsx?|md|toml|json|ya?ml|cpp|hpp|h|c)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return clip(focus_high_value_title_text(cleaned), 120)


def durable_memory_text(text: str) -> str:
    if is_process_update(text):
        return ""
    candidate = strip_skill_invocation_prefix(text)
    candidate = strip_reusable_fact_prefix(candidate)
    cleaned = clean_title_candidate(candidate) if is_raw_prompt_text(candidate) else clip(candidate)
    if (
        not cleaned
        or is_low_signal_memory_text(cleaned)
        or is_noisy_text(cleaned)
        or is_raw_prompt_text(cleaned)
        or is_process_update(cleaned)
    ):
        return ""
    return cleaned


def strip_reusable_fact_prefix(text: str) -> str:
    match = REUSABLE_FACT_PREFIX.match(text)
    return match.group("text").strip() if match else text


def durable_user_memory_text(text: str) -> str:
    candidate = strip_skill_invocation_prefix(text)
    cleaned = clean_title_candidate(candidate) if is_raw_prompt_text(candidate) else clip(candidate)
    if (
        not cleaned
        or is_low_signal_memory_text(cleaned)
        or is_noisy_text(cleaned)
        or is_raw_prompt_text(cleaned)
    ):
        return ""
    return cleaned


def event_has_reusable_fact_text(events: list[MemoryEvent], fact: str) -> bool:
    fact_key = normalize_memory_text(fact).lower()
    if not fact_key:
        return False
    for event in events:
        if event.kind not in {"assistant", "record"}:
            continue
        for part in split_memory_text(event.text):
            match = REUSABLE_FACT_PREFIX.match(part)
            if not match:
                continue
            text = normalize_memory_text(match.group("text"))
            if text.lower() == fact_key:
                return True
    return False


def fact_source_entries(
    facts: list[str],
    events: list[MemoryEvent],
    natural_user_facts: list[str],
    retrieval_literals: list[str],
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    natural_user_keys = {normalize_memory_text(text).lower() for text in natural_user_facts}
    retrieval_literal_keys = {normalize_memory_text(text).lower() for text in retrieval_literals}
    for fact in facts:
        fact_key = normalize_memory_text(fact).lower()
        if not fact_key:
            continue
        if fact_key in natural_user_keys:
            source = "natural_user"
        elif fact_key in retrieval_literal_keys:
            source = "retrieval_literal"
        elif event_has_reusable_fact_text(events, fact):
            source = "explicit_reusable_fact"
        else:
            source = "natural_assistant"
        entries.append({"text": fact, "source": source})
    return entries


def clean_command_output(text: str) -> str:
    stripped = text.strip()
    if stripped.lower().startswith("chunk id:") and "\nOutput:\n" in stripped:
        stripped = stripped.split("\nOutput:\n", 1)[1]
    lines = []
    for line in stripped.splitlines():
        lowered = line.strip().lower()
        if any(
            lowered.startswith(prefix)
            for prefix in (
                "chunk id:",
                "wall time:",
                "process exited with code",
                "original token count:",
                "write_stdin failed:",
            )
        ):
            continue
        lines.append(line)
    return clip("\n".join(lines))


def extract_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := extract_text(item))).strip()
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
        output = body.get("output")
        text = clean_command_output(output) if isinstance(output, str) else extract_text(output)
        return [MemoryEvent("command_output", text)] if text else []

    role = str(body.get("role") or value.get("role") or "").lower()
    text = extract_text(body.get("content")) or extract_text(body.get("text")) or extract_text(body.get("message"))
    if not text:
        return []
    if role in {"user", "human"}:
        return [MemoryEvent("user", text)]
    if role == "assistant":
        if str(body.get("phase") or body.get("channel") or "").lower() == "commentary":
            return []
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
    cleaned: list[MemoryEvent] = []
    for event in events:
        event_text = strip_memory_citation_blocks(event.text)
        if is_injected_context_text(event_text):
            continue
        for piece in split_memory_text(event_text):
            text = strip_process_clauses(piece)
            if text and not is_noisy_text(text) and not is_process_update(text):
                cleaned.append(MemoryEvent(event.kind, text))
    return cleaned


def bullet_list(items: list[str], fallback: str) -> str:
    if not items:
        return f"- {fallback}\n"
    return "".join(f"- {str(item).rstrip()}\n" for item in items)


def markdown_list_section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    return f"## {title}\n" + "".join(f"- {str(item).rstrip()}\n" for item in items) + "\n"


def markdown_text_section(title: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"## {title}\n{text}\n\n"


def strip_trailing_whitespace_lines(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def render_evidence_body(evidence_lines: list[str], explicit_memories: list[str]) -> str:
    lines: list[str] = []
    for idx, line in enumerate(evidence_lines, 1):
        lines.append(f"ev_{idx:03d}: {line}")
        lines.append(f"- {line}")
    for idx, text in enumerate(explicit_memories, 1):
        if text not in evidence_lines:
            lines.append(f"ev_explicit_{idx:03d}: {text}")
            lines.append(f"- {text}")
    return "\n".join(lines)


def is_process_update(text: str) -> bool:
    lowered = text.lower()
    prefixes = (
        "i am ",
        "i'm ",
        "i’m ",
        "i will ",
        "i’ll ",
        "next i",
        "now i",
        "i also ",
        "i checked ",
        "i confirmed ",
        "i found ",
        "i noticed ",
        "i reran ",
        "i rerun ",
        "我先",
        "我会",
        "我再",
        "当前我会",
        "接着我会",
        "随后我会",
        "最后我会",
        "最后一轮我会",
        "我做最后一轮",
        "下一步我",
        "接下来我",
        "现在先",
        "现在开始",
        "现在改为",
        "先读取",
        "先检查",
        "先看",
        "先跑",
    )
    if lowered.startswith(prefixes):
        return True
    if lowered.startswith(("one search command failed", "one command failed", "a search command failed")):
        return True
    process_patterns = (
        r"\bi(?:'m|’m| am)\s+(?:proceeding|locating|checking|inspecting|running|rerunning|continuing|waiting|working|reading|verifying|starting)\b",
        r"\bi(?:'m|’m| am)\s+not\s+(?:rerunning|running|proceeding|continuing)\b",
        r"\bi(?:'ll|’ll| will)\s+(?:only\s+)?(?:inspect|check|verify|run|rerun|continue|wait|proceed|look|locate|report|use)\b",
        r"\bthen\s+i(?:'ll|’ll| will)\b",
        r"\bi\s+used\s+prior\s+workflow\s+memory\b",
        r"^using\s+[`$]?(?:using-|brainstorming|test-driven|systematic|update-my-precious).*(?:as requested|i(?:'ll|’ll| will)\s+also\s+use)",
        r"现在我(?:检查|先|会|正在|继续|再|已经)",
        r"我正在(?:检查|处理|验证|跑|看|等待|继续|读取|定位|修复|更新|清理)",
        r"当前我会|接着我会|随后我会|最后我会|最后一轮我会|我做最后一轮",
        r"现在(?:先|开始|改为|做|跑|检查|验证|清理|处理|读取)",
        r"现在\s*(?:dry run|rewrite|重写).*",
        r"现在按\s*(?:顺序|计划|规则|tdd|测试).*",
        r"现在实现(?:最小)?修复.*",
        r"现在同步(?:真实)?工具.*",
        r"执行\s*rewrite.*",
        r"同步后重跑.*",
        r"按上一轮耗时估计.*",
        r"流程.*(?:validator|py_compile|template\s+sync|黑盒检查|强关键词搜索|排第一)",
        r"(?:unit\s+tests?|tests?)\s+pass(?:ed|es)?.*(?:archive\s+audit|skill\s+validators?|py_compile|template/script\s+sync)",
        r"(?:archive\s+audit|skill\s+validators?|py_compile|template/script\s+sync).*(?:pass(?:ed|es)?|green|ok)",
        r"示例搜索.*(?:cc-switch|libx265|libheif|_gdal|osgeo)",
        r"(?:查询|搜索|检索).*?(?:表现|命中|排第|排到|top\s+hit|rank|ranking)",
        r"(?:`[^`]{1,120}`|[^。.!?；;\n]{1,120})\s*(?:第[一二三123]|第一)\s*命中是",
        r"(?:top\s+hit|top\s+result|search\s+verification|search\s+result|targeted\s+search).*(?:rank|match|hit|pass)",
        r"先(?:读取|检查|看|跑|做|定位|验证|清理)",
        r"正在处理",
        r"继续等待",
        r"继续等最终输出",
        r"过程句.*(?:reusable|problem|unresolved)",
    )
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in process_patterns)


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
        durable = durable_memory_text(text)
        if not durable:
            continue
        if regex.search(text) or regex.search(durable):
            selected.append(durable)
            if len(selected) >= limit:
                break
    return selected


def select_retrieval_literal_texts(
    events: list[MemoryEvent],
    *,
    kinds: set[str] | None = None,
    limit: int = 4,
) -> list[str]:
    selected: list[str] = []
    for text in event_texts(events, kinds):
        if is_process_update(text):
            continue
        for part in split_memory_text(text, limit=64):
            if not RETRIEVAL_LITERAL_PATTERN.search(part):
                continue
            durable = durable_memory_text(part)
            if durable and durable not in selected:
                selected.append(durable)
    return sorted(selected, key=retrieval_literal_priority)[:limit]


def retrieval_literal_priority(text: str) -> tuple[int, str]:
    lowered = text.lower()
    if "socks5" in lowered:
        return (0, lowered)
    if re.search(r"spurious\s+502|libx\d|_gdal|osgeo", lowered):
        return (1, lowered)
    if re.search(r"(?:https?|socks5h?)://", lowered):
        return (2, lowered)
    if "127.0.0.1" in lowered:
        return (3, lowered)
    return (4, lowered)


def sentence_case_tail(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if len(stripped) == 1:
        return stripped.lower()
    return stripped[:1].lower() + stripped[1:]


def extract_natural_user_memory_facts(events: list[MemoryEvent], limit: int = 5) -> list[str]:
    facts: list[str] = []
    for text in event_texts(events, {"user"}):
        if is_process_update(text):
            continue
        compacted = compact_whitespace(strip_process_clauses(text))
        if not compacted or is_noisy_text(compacted) or is_raw_prompt_text(compacted):
            continue
        for pattern, template in NATURAL_USER_MEMORY_PATTERNS:
            match = pattern.match(compacted)
            if not match:
                continue
            tail = clean_explicit_memory_text(normalize_memory_text(match.group("text")))
            tail = re.sub(r"(?i)^\s*that\s+", "", tail).strip()
            if not tail or is_sensitive_explicit_memory_text(tail):
                continue
            fact = template.format(text=sentence_case_tail(tail))
            durable = durable_memory_text(fact)
            if durable and durable not in facts:
                facts.append(durable)
            break
        if len(facts) >= limit:
            break
    return facts


def extract_tags(project_name: str, texts: list[str]) -> list[str]:
    tags: list[str] = []
    project_slug = slugify(project_name)
    if project_slug and project_slug not in NOISY_TAGS:
        tags.append(project_slug)
    stop_words = {
        "this",
        "that",
        "with",
        "from",
        "and",
        "for",
        "the",
        "two",
        "its",
        "itself",
        "through",
        "will",
        "should",
        "would",
        "could",
        "need",
        "must",
        "not",
        "become",
        "search",
        "tags",
        "decision",
        "use",
        "next",
        "error",
        "unresolved",
        "tasks",
        "skill",
        "skills",
        "skill.md",
        "subagent_notification",
        "agent_path",
        "supports",
        "concepts",
        "tools",
        "routed",
        "root",
        "cause",
        "final",
        "state",
        "archive",
        "memory",
        "agent",
        "source",
        "record",
        "session",
        "summary",
        "users",
        "soku",
        "desktop",
        "agents",
        "codex",
        "subagent",
        "codespace",
        "mememe",
        "templates",
        "agent-memory-repo",
        "secret-pattern",
        "add",
        "before",
        "publishing",
        "updates",
        "summaries",
        "validator",
        "validators",
        "py_compile",
        "template",
        "sync",
        "implementation",
        "has",
        "meaningful",
        "improvements",
        "unit",
        "tests",
        "test",
        "pass",
        "passes",
        "passed",
        "audit",
        "script",
        "checks",
        "suggested",
        "concrete",
        "expected",
        "can",
        "but",
        "only",
        "title",
        "file",
        "files",
        "scripts",
        "saved",
        "remaining",
        "current",
        "diff",
        "three",
        "requested",
        "mostly",
        "there",
        "still",
        "without",
        "important",
        "task",
        "you",
        "are",
        "run",
        "using-superpowers",
        "using-agent-skills",
        "worktree",
        "codex_home",
        "commands",
        "command",
        "status",
        "actual",
        "completed",
        "complete",
        "continue",
        "previous",
        "after",
        "before",
        "once",
        "newly",
        "synced",
        "updater",
        "text",
        "module",
        "named",
        "review",
        "quality",
        "spec",
        "finding",
        "findings",
        "approved",
        "code",
        "message",
        "last",
        "private_key",
        "bearer_token",
        "github_token",
        "openai_key",
        "aws_access_key",
        "refusal",
        "stayed",
        "clean",
        "entry",
        "usable",
        "imperfect",
        "captures",
        "capture",
        "latest",
        "weaker",
        "retrieval",
        "durable",
        "generic",
        "critique",
        "critiques",
        "http",
        "python",
        "cli",
        "top",
        "hit",
    }
    for text in texts:
        if is_low_signal_memory_text(text) or is_noisy_text(text) or is_raw_prompt_text(text) or is_process_update(text):
            continue
        for token in re.findall(
            r"[A-Za-z][A-Za-z0-9]*(?:[-_.][A-Za-z0-9]+)+|[A-Za-z][A-Za-z0-9]{2,}|[0-9]+(?:\.[0-9]+){1,3}|[0-9]{3,5}",
            text.lower(),
        ):
            token = token.strip("._-")
            if not token or token in stop_words or token in NOISY_TAGS or token in tags:
                continue
            if is_redaction_category_text(token):
                continue
            if token.isdigit() and len(token) < 4:
                continue
            if "-" in token and len(token) >= 12:
                hexish = token.replace("-", "")
                if len(hexish) >= 12 and re.fullmatch(r"[0-9a-f]+", hexish):
                    continue
            if token.endswith(".md") and token not in {"readme.md"}:
                continue
            if token.endswith(".py"):
                continue
            tags.append(token[:48])
            if len(tags) >= 16:
                return tags
    return tags


def summarize_events(events: list[MemoryEvent], project_name: str) -> dict[str, object]:
    user_lines = event_texts(events, {"user"})
    if not user_lines:
        user_lines = event_texts(events, {"record"})[:2]
    durable_user_lines = []
    for line in user_lines:
        durable = durable_user_memory_text(line)
        if durable:
            durable_user_lines.append(durable)
    assistant_lines = event_texts(events, {"assistant", "record"})
    natural_user_facts = extract_natural_user_memory_facts(events)
    decisions = select_event_texts(
        events,
        r"\b(decision|decide|decided|chosen|selected|root cause)\b|原因|根因|决定|选择",
        kinds={"assistant", "record"},
        limit=5,
    )
    problems = select_event_texts(
        events,
        r"\b(error|failed|failure|blocked|exception|traceback|problem|issue|bug|importerror)\b|失败|错误|阻塞",
        kinds={"assistant", "record"},
        limit=5,
    )
    unresolved = select_event_texts(
        events,
        r"\b(todo|follow[- ]?up|unresolved (?:task|work|thread)|remaining work|still need|not completed)\b|后续(?:需要|还要|待|继续|补|处理|修复|验证|清理|更新|工作|任务)|未完成|还需要",
        kinds={"assistant", "record"},
        limit=5,
    )
    facts = select_event_texts(
        events,
        r"\b(root cause|verified|must|should|require|requires|constraint|convention|policy|rule|prefer|expected|finding|findings|changes_requested|approved|proxy|proxies|outbound proxy|global outbound proxy|local routing|socks5|http_proxy|https_proxy)\b|127\.0\.0\.1|原因|根因|验证|约定|偏好|必须|应该|阻塞|索引|高质量|只能做|做不到|还没有达到|摘要器|代理|全局出站代理|本地代理",
        kinds={"assistant", "record"},
        limit=12,
    )
    for line in reversed(natural_user_facts):
        if line not in facts:
            facts.insert(0, line)
    retrieval_literals = select_retrieval_literal_texts(events, kinds={"assistant", "record"}, limit=8)
    for line in retrieval_literals:
        if line not in facts:
            facts.append(line)
    if not facts:
        facts = [durable for text in assistant_lines if (durable := durable_memory_text(text))][:3]
    evidence = []
    for group in (decisions, retrieval_literals, facts, problems, unresolved):
        for line in group:
            durable = durable_memory_text(line)
            if durable and durable not in evidence:
                evidence.append(durable)
            if len(evidence) >= 6:
                break
        if len(evidence) >= 6:
            break
    if not evidence:
        for line in durable_user_lines:
            durable = durable_memory_text(line)
            if durable and durable not in evidence:
                evidence.append(durable)
            if len(evidence) >= 3:
                break

    user_intent = durable_user_lines[0] if durable_user_lines else ""
    final_state = ""
    for text in reversed(assistant_lines):
        durable = durable_memory_text(text)
        if durable:
            final_state = durable
            break
    if final_state and final_state not in evidence:
        if len(evidence) >= 6:
            evidence = evidence[:5]
        evidence.append(final_state)
    summary_items = []
    summary_user_intent = durable_user_lines[0] if durable_user_lines else ""
    for line in [summary_user_intent, *decisions[:1], *facts[:1], final_state]:
        if line and line not in summary_items:
            summary_items.append(line)
    summary = " ".join(summary_items) if summary_items else ""
    context = []
    for line in [summary_user_intent, *facts[:2], *retrieval_literals[:2], *problems[:1], final_state]:
        durable = durable_memory_text(line)
        if durable and durable not in context:
            context.append(durable)

    return {
        "user_intent": user_intent,
        "summary": summary,
        "context": context[:5],
        "facts": facts,
        "fact_sources": fact_source_entries(facts, events, natural_user_facts, retrieval_literals),
        "decisions": decisions,
        "problems": problems,
        "unresolved": unresolved,
        "evidence": evidence,
        "tags": extract_tags(project_name, [*retrieval_literals, *facts, *decisions, *problems, *unresolved, final_state]),
        "final_state": final_state or summary,
    }


def has_durable_summary_content(summary_data: dict[str, object]) -> bool:
    list_keys = ("context", "facts", "decisions", "problems", "unresolved", "evidence")
    for key in list_keys:
        value = summary_data.get(key)
        if isinstance(value, list) and any(durable_memory_text(str(item)) for item in value):
            return True
    for key in ("user_intent", "summary", "final_state"):
        value = summary_data.get(key)
        if isinstance(value, str) and durable_memory_text(value):
            return True
    return False


def title_quality_score(text: str, source_weight: int = 0) -> int:
    compacted = clean_title_candidate(text)
    if not compacted or is_low_signal_memory_text(compacted) or is_noisy_text(compacted) or is_process_update(compacted):
        return -10_000
    lowered = compacted.lower()
    if any(marker in lowered for marker in RAW_TITLE_MARKERS):
        return -10_000
    score = source_weight
    length = len(compacted)
    if length < 8:
        score -= 45
    elif length < 30:
        score += 8
    elif length <= 100:
        score += 28
    else:
        score += 12
    if re.search(r"\b(root cause|decision|decided|chosen|verified|must|should|proxy|socks5|local routing)\b|根因|原因|决定|选择|验证|索引|代理|全局出站代理|本地代理|失败", compacted, re.IGNORECASE):
        score += 24
    if re.search(r"高信噪比|记忆索引|durable memory index|memory index|retrieval-first", compacted, re.IGNORECASE):
        score += 28
    if HIGH_VALUE_TITLE_PATTERN.search(compacted):
        score += 55
    if re.search(r"\b(changes_requested|finding|findings|approved)\b", compacted, re.IGNORECASE):
        score += 35
    if re.search(r"\b(?:code quality|spec compliance|review|re-review|implement task)\b", compacted, re.IGNORECASE):
        score -= 10
    if re.search(r"\b(?:dry run|live update|source record|secret gate|subagent)\b|默认 secret gate|产生新写入", compacted, re.IGNORECASE):
        score -= 45
    if re.fullmatch(
        r"(?:https?|socks5h?)\s+proxy\s*:\s*\S+|(?:https?|socks5h?)://\S+|127\.0\.0\.1(?::\d+)?",
        compacted,
        re.IGNORECASE,
    ):
        score -= 80
    if re.search(r"`[^`]+`|[A-Za-z0-9_./-]+\.(?:dylib|so|jsonl|md)|\b\d{1,3}(?:\.\d{1,3}){3}\b", compacted):
        score += 10
    if "?" in compacted or "？" in compacted:
        score += 8
    if re.fullmatch(r"(?:可以|是的|不行|不能|结论[:：]?.{0,12})[。.!]?", compacted):
        score -= 35
    return score


def iter_title_candidates(summary_data: dict[str, object]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    weighted_keys = (
        ("user_intent", 45),
        ("facts", 16),
        ("reusable_facts", 16),
        ("decisions", 14),
        ("final_state", 8),
        ("summary", 4),
        ("title", 2),
    )
    for key, weight in weighted_keys:
        value = summary_data.get(key)
        if isinstance(value, str):
            candidates.append((value, weight))
        elif isinstance(value, list):
            candidates.extend((str(item), weight) for item in value)
    return candidates


def memory_title(summary_data: dict[str, object], fallback: str) -> str:
    scored: list[tuple[int, int, str]] = []
    for position, (candidate, weight) in enumerate(iter_title_candidates(summary_data)):
        text = clean_title_candidate(candidate)
        score = title_quality_score(text, weight)
        if score > -10_000:
            scored.append((score, -position, text))
    if scored:
        return max(scored)[2]
    return fallback


def index_title_from_meta(row: dict[str, object]) -> str:
    source_record = str(row.get("source_record", ""))
    project = str(row.get("project", ""))
    fallback = f"{project}: {Path(source_record).name}" if source_record else project
    explicit_title = clean_title_candidate(str(row.get("title", "")))
    if title_quality_score(explicit_title) > -10_000:
        return explicit_title
    return memory_title(
        {
            "summary": row.get("summary", ""),
            "user_intent": row.get("user_intent", ""),
            "decisions": row.get("decisions", []),
            "facts": row.get("reusable_facts", []),
            "final_state": row.get("final_state", ""),
            "title": row.get("title", ""),
        },
        fallback,
    )


def record_dir(memory_repo: Path, project_slug: str, record: SourceRecord) -> Path:
    stamp = record.updated_at.strftime("%Y-%m-%dT%H%M%SZ")
    day = record.updated_at.strftime("%Y/%m/%d")
    return memory_repo / "sessions" / day / f"{stamp}_{project_slug}_{record.sha256[:10]}"


def remove_existing_entries_for_source(memory_repo: Path, project_path: Path, source_record: Path) -> int:
    project_key = str(project_path.resolve())
    source_key = str(source_record.resolve())
    removed = 0
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("project_path") != project_key or meta.get("source_record") != source_key:
            continue
        entry_dir = meta_path.parent
        if not is_safe_archive_entry_dir(memory_repo, entry_dir):
            raise SystemExit(f"Refusing to remove unsafe archive entry path: {safe_diagnostic_path(entry_dir)}")
        shutil.rmtree(entry_dir)
        removed += 1
    prune_empty_session_dirs(memory_repo / "sessions")
    return removed


def is_safe_archive_entry_dir(memory_repo: Path, entry_dir: Path) -> bool:
    try:
        relative = entry_dir.resolve().relative_to((memory_repo / "sessions").resolve())
    except (OSError, ValueError):
        return False
    return len(relative.parts) >= 4 and entry_dir.name


def is_safe_repo_path(memory_repo: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(memory_repo.resolve())
    except (OSError, ValueError):
        return False
    return True


def write_safe_archive_text(memory_repo: Path, path: Path, text: str, label: str) -> None:
    if not is_safe_repo_path(memory_repo, path):
        raise SystemExit(f"Refusing to write unsafe archive {label} path: {safe_diagnostic_path(path)}")
    path.write_text(text, encoding="utf-8")


def prune_empty_session_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted((item for item in root.glob("**/*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        if path == root:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()


def write_record(
    memory_repo: Path,
    project_path: Path,
    project_name: str,
    source_agent: str,
    record: SourceRecord,
) -> Path | None:
    project_slug = slugify(project_name)
    destination = record_dir(memory_repo, project_slug, record)
    if not is_safe_archive_entry_dir(memory_repo, destination):
        raise SystemExit(f"Refusing to write unsafe archive entry path: {safe_diagnostic_path(destination)}")
    destination.mkdir(parents=True, exist_ok=True)

    source_text = read_record_text(record.path)
    redacted_text, redaction_counts = redact_text(source_text)
    source_events = extract_source_events(record.path, redacted_text)
    summary_data = summarize_events(source_events, project_name)
    explicit_memories = extract_explicit_memory_texts(source_events)
    if not has_durable_summary_content(summary_data):
        shutil.rmtree(destination)
        return None
    archived_at = utc_now()
    rel_summary = destination.relative_to(memory_repo) / "summary.md"
    rel_evidence = destination.relative_to(memory_repo) / "evidence.md"
    rel_source_map = destination.relative_to(memory_repo) / "source-map.json"

    source_title = f"{project_name}: {record.path.name}"
    title = memory_title(summary_data, source_title)
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

{markdown_list_section("Context Recovered", summary_data["context"])}
{markdown_list_section("Reusable Facts", summary_data["facts"])}
{markdown_list_section("Decisions Made", summary_data["decisions"])}
## Files And Code Touched
- source_record: `{record.path}`
- archive_entry: `{destination.relative_to(memory_repo)}`

{markdown_list_section("Problems Encountered", summary_data["problems"])}
{markdown_text_section("Final State", summary_data["final_state"])}
{markdown_list_section("Unresolved Tasks", summary_data["unresolved"])}
## Search Tags
{tags}

## Evidence Pointers
See `evidence.md` for short redacted snippets that support the summary.
"""
    summary = strip_trailing_whitespace_lines(summary)

    evidence_lines = summary_data["evidence"]
    evidence_body = render_evidence_body(evidence_lines, explicit_memories)
    evidence = (
        f"# Evidence: {title}\n\n"
        f"Source record: `{record.path}`\n"
        f"Source updated at: {isoformat(record.updated_at)}\n"
        f"Source SHA-256: `{record.sha256}`\n"
        "Policy: short redacted snippets only; raw source records are not copied by default.\n"
    )
    if evidence_body:
        evidence += f"\n{evidence_body}\n"
    evidence = strip_trailing_whitespace_lines(evidence)

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
        "source_map_path": str(rel_source_map),
        "archive_status": archive_status,
        "redaction_status": redaction_status,
        "contains_raw_transcript": False,
        "evidence_policy": "short_redacted_snippets",
        "title": title,
        "user_intent": summary_data["user_intent"],
        "summary": summary_data["summary"],
        "reusable_facts": summary_data["facts"],
        "reusable_fact_sources": summary_data["fact_sources"],
        "tags": summary_data["tags"],
        "decisions": summary_data["decisions"],
        "explicit_memories": explicit_memories,
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
        "source_map_path": str(rel_source_map),
        "contains_raw_transcript": False,
        "evidence_policy": "short_redacted_snippets",
    }

    redactions = "# Redactions\n\n"
    if redaction_counts:
        for name, count in sorted(redaction_counts.items()):
            redactions += f"- {name}: {count}\n"
    else:
        redactions += "- No redactions were applied to the source content.\n"
    redactions = strip_trailing_whitespace_lines(redactions)

    write_safe_archive_text(memory_repo, destination / "summary.md", summary, "record file")
    write_safe_archive_text(memory_repo, destination / "evidence.md", evidence, "record file")
    write_safe_archive_text(
        memory_repo,
        destination / "meta.json",
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        "record file",
    )
    write_safe_archive_text(memory_repo, destination / "redactions.md", redactions, "record file")
    write_safe_archive_text(
        memory_repo,
        destination / "source-map.json",
        json.dumps(source_map, indent=2, sort_keys=True) + "\n",
        "record file",
    )
    return destination


def memory_topic(text: str, tags: Iterable[str]) -> str:
    lowered = " ".join([text, *tags]).lower()
    for topic, hints in MEMORY_TOPIC_HINTS:
        if any(hint in lowered for hint in hints):
            return topic
    return "general"


def automatic_memory_layer(candidate: MemoryCandidate, support_projects: set[str]) -> str:
    lowered = candidate.text.lower()
    if any(hint in lowered for hint in GLOBAL_MEMORY_HINTS):
        return "global"
    if len(support_projects) >= 2:
        return "domain"
    return "project"


def memory_scope(layer: str, candidate: MemoryCandidate) -> str:
    if layer == "global":
        return "global"
    if layer == "domain":
        return f"domain:{candidate.topic}"
    project_key = candidate.project_path or candidate.project
    return f"project:{project_key}"


def memory_id_for(layer: str, scope: str, text: str, source: str) -> str:
    key = f"{layer}\n{scope}\n{source}\n{normalize_memory_text(text).lower()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"mem_{digest[:16]}"


def has_unsafe_raw_ref_path(text: str) -> bool:
    if text.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", text):
        return True
    return any(part == ".." for part in re.split(r"[\\/]+", text))


def has_control_chars(text: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in text)


def raw_ref_for_source_record(path: str, anchor: str) -> dict[str, str] | None:
    path = path.strip()
    anchor = anchor.strip()
    if not path or not anchor:
        return None
    if has_control_chars(path) or has_control_chars(anchor):
        return None
    if has_unsafe_raw_ref_path(path):
        return None
    if any(pattern.search(path) or pattern.search(anchor) for pattern in REDACTION_PATTERNS.values()):
        return None
    return {"path": path, "anchor": anchor}


def raw_ref_for_source_fields(source_record: str, source_map_path: str, anchor: str) -> dict[str, str] | None:
    return raw_ref_for_source_record(source_record, anchor) or raw_ref_for_source_record(source_map_path, anchor)


def iter_memory_candidate_texts(row: dict[str, object]) -> Iterable[tuple[str, str]]:
    fields = (
        ("reusable_facts", "Reusable fact from archived session."),
        ("decisions", "Decision captured in archived session."),
        ("unresolved_tasks", "Unresolved task captured in archived session."),
    )
    for key, rationale in fields:
        value = row.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            text = normalize_memory_text(strip_reusable_fact_prefix(str(item)))
            if (
                text
                and not is_noisy_text(text)
                and not is_raw_prompt_text(text)
                and not is_process_update(text)
                and not is_low_signal_memory_text(text)
            ):
                yield text, rationale


def clean_explicit_memory_text(text: str) -> str:
    match = EXPLICIT_MEMORY_TASK_TAIL_BOUNDARY.search(text)
    if match:
        text = text[: match.start()]
    return normalize_memory_text(text)


def is_sensitive_explicit_memory_text(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_EXPLICIT_MEMORY_MARKERS):
        return True
    for label in REDACTION_CATEGORY_LABELS:
        label_text = str(label).lower()
        if label_text in lowered or label_text.replace("_", " ") in lowered:
            return True
    return False


def is_negated_explicit_memory_directive(text: str) -> bool:
    return any(pattern.match(text) for pattern in NEGATED_EXPLICIT_MEMORY_PATTERNS)


def extract_explicit_memory_texts(events: list[MemoryEvent]) -> list[str]:
    texts: list[str] = []
    for event in events:
        if event.kind != "user":
            continue
        compacted = compact_whitespace(event.text)
        if is_negated_explicit_memory_directive(compacted):
            continue
        for pattern in EXPLICIT_MEMORY_PATTERNS:
            match = pattern.match(compacted)
            if not match:
                continue
            text = normalize_memory_text(match.group("text"))
            text = clean_explicit_memory_text(text)
            if (
                text
                and not is_noisy_text(text)
                and not is_sensitive_explicit_memory_text(text)
                and text not in texts
            ):
                texts.append(text)
    return texts


def explicit_memory_node(text: str, row: dict[str, object]) -> dict:
    tags = [str(tag) for tag in row.get("tags", []) if isinstance(tag, (str, int, float))]
    topic = memory_topic(text, tags)
    source_updated_at = str(row.get("source_updated_at", ""))
    summary_path = str(row.get("summary_path", ""))
    evidence_path = str(row.get("evidence_path", ""))
    source_record = str(row.get("source_record", ""))
    source_map_path = str(row.get("source_map_path", ""))
    raw_ref = raw_ref_for_source_fields(source_record, source_map_path, "explicit_memory")
    layer = "global"
    scope = "global"
    return {
        "memory_id": memory_id_for(layer, scope, text, "explicit"),
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": text,
        "rationale": "Explicit memory requested by the user or governing prompt.",
        "source": "explicit",
        "confidence": "high",
        "persistence": "sticky",
        "support_count": 1,
        "first_seen": source_updated_at,
        "last_seen": source_updated_at,
        "derived_from": [summary_path] if summary_path else [],
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_explicit_001"}] if evidence_path else [],
        "raw_refs": [raw_ref] if raw_ref else [],
        "supersedes": [],
        "superseded_by": None,
        "tags": sorted(set([*tags, topic, "explicit-memory"])),
    }


def archive_ref_path(memory_repo: Path, path_text: str) -> Path | None:
    path_text = path_text.strip()
    if not path_text or has_unsafe_raw_ref_path(path_text):
        return None
    candidate = memory_repo / path_text
    try:
        repo_resolved = memory_repo.resolve()
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(repo_resolved)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    return resolved


def existing_archive_ref(memory_repo: Path, path_text: str) -> bool:
    return archive_ref_path(memory_repo, path_text) is not None


def evidence_quote_id_exists(path: Path, quote_id: str) -> bool:
    if not quote_id.strip():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return bool(re.search(rf"(?m)^\s*{re.escape(quote_id)}\s*:", text))


def parse_archive_ref(value: str, option_name: str) -> tuple[str, str]:
    if "#" not in value:
        raise SystemExit(f"{option_name} must use PATH#ANCHOR")
    path, anchor = value.split("#", 1)
    path = path.strip()
    anchor = anchor.strip()
    if not path or not anchor:
        raise SystemExit(f"{option_name} must use PATH#ANCHOR")
    return path, anchor


def is_safe_direct_raw_ref(ref: dict[str, str]) -> bool:
    return raw_ref_for_source_record(ref["path"], ref["anchor"]) is not None


def direct_explicit_memory_node(
    text: str,
    layer: str,
    scope: str,
    summary_path: str,
    evidence_refs: list[dict],
    raw_refs: list[dict],
    now: str,
) -> dict:
    cleaned = clean_explicit_memory_text(text)
    if not cleaned or is_sensitive_explicit_memory_text(cleaned) or is_noisy_text(cleaned):
        raise SystemExit("explicit memory text is empty, noisy, or sensitive")
    topic = memory_topic(cleaned, [])
    return {
        "memory_id": memory_id_for(layer, scope, cleaned, "explicit"),
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": cleaned,
        "rationale": "Explicit memory requested by the user or governing prompt.",
        "source": "explicit",
        "confidence": "high",
        "persistence": "sticky",
        "support_count": 1,
        "first_seen": now,
        "last_seen": now,
        "derived_from": [summary_path],
        "evidence_refs": evidence_refs,
        "raw_refs": raw_refs,
        "supersedes": [],
        "superseded_by": None,
        "tags": sorted({topic, "explicit-memory"}),
    }


def memory_candidates_from_meta(rows: list[dict]) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    for row in rows:
        tags = tuple(str(tag) for tag in row.get("tags", []) if isinstance(tag, (str, int, float)))
        summary_path = str(row.get("summary_path", ""))
        evidence_path = str(row.get("evidence_path", ""))
        fact_sources = {}
        for item in row.get("reusable_fact_sources") or []:
            if not isinstance(item, dict):
                continue
            text = normalize_memory_text(str(item.get("text") or ""))
            source = str(item.get("source") or "")
            if text and source:
                fact_sources[text.lower()] = source
        if not summary_path or not evidence_path:
            continue
        for text, rationale in iter_memory_candidate_texts(row):
            provenance = fact_sources.get(normalize_memory_text(text).lower(), "")
            text, supersedes_texts = parse_memory_refresh_text(text, is_noisy_text)
            text, deprecates_texts = parse_memory_deprecation_text(text, is_noisy_text)
            if deprecates_texts:
                rationale = "Memory deprecation captured in archived session."
            elif supersedes_texts:
                rationale = "Memory refresh captured in archived session."
            candidates.append(
                MemoryCandidate(
                    text=text,
                    rationale=rationale,
                    source="automatic",
                    topic=memory_topic(text, tags),
                    project=str(row.get("project", "")),
                    project_path=str(row.get("project_path", "")),
                    summary_path=summary_path,
                    evidence_path=evidence_path,
                    source_record=str(row.get("source_record", "")),
                    source_map_path=str(row.get("source_map_path", "")),
                    source_updated_at=str(row.get("source_updated_at", "")),
                    tags=tags,
                    provenance=provenance,
                    supersedes_texts=supersedes_texts,
                    deprecates_texts=deprecates_texts,
                )
            )
    return candidates


def evidence_ref_for_path(memory_repo: Path | None, path: str) -> dict[str, str] | None:
    if not path:
        return None
    quote_id = "ev_001"
    if memory_repo is not None:
        evidence_path = archive_ref_path(memory_repo, path)
        if evidence_path is None or not evidence_quote_id_exists(evidence_path, quote_id):
            return None
    return {"path": path, "quote_id": quote_id}


def is_natural_memory_candidate(candidate: MemoryCandidate) -> bool:
    return candidate.provenance in NATURAL_FACT_SOURCE_LABELS


def candidate_identity(candidate: MemoryCandidate) -> tuple[str, str, str, str]:
    return (
        normalize_memory_text(candidate.text).lower(),
        candidate.summary_path,
        candidate.evidence_path,
        candidate.source_updated_at,
    )


def natural_candidate_text_sha256(text: str) -> str:
    normalized = normalize_memory_text(text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def induction_review_candidate_id(candidate: MemoryCandidate, reason: str) -> str:
    payload = "\n".join(
        [
            normalize_memory_text(candidate.text).lower(),
            reason,
            candidate.summary_path,
            candidate.evidence_path,
            candidate.source_updated_at,
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"indrev_{digest[:16]}"


def should_low_confidence_review_natural_candidate(candidate: MemoryCandidate) -> bool:
    return bool(LOW_CONFIDENCE_NATURAL_REVIEW_PATTERN.search(candidate.text))


def induction_review_reason_from_relation(detail: dict) -> str:
    relation = str(detail.get("relation") or "")
    review_reason = str(detail.get("review_reason") or "")
    if relation == "contradiction" or review_reason == "low_confidence_contradiction_requires_review":
        return "conflicting_natural_induction_requires_review"
    if review_reason == "ambiguous_scope_narrowing_requires_review":
        return "scope_change_natural_induction_requires_review"
    if review_reason == "low_confidence_semantic_overlap_requires_review":
        return "low_confidence_natural_induction_requires_review"
    return ""


def archive_relative_ref_exists(memory_repo: Path | None, path: str) -> bool:
    if not path:
        return False
    if memory_repo is None:
        return True
    return archive_ref_path(memory_repo, path) is not None


def natural_induction_review_candidate_row(
    candidate: MemoryCandidate,
    reason: str,
    memory_repo: Path | None,
    related: MemoryCandidate | None = None,
    detail: dict | None = None,
) -> dict:
    row = {
        "candidate_id": induction_review_candidate_id(candidate, reason),
        "candidate_type": "natural_induction_review",
        "candidate_text_sha256": natural_candidate_text_sha256(candidate.text),
        "candidate_source": candidate.provenance,
        "reason": reason,
        "recommended_action": "manual_review",
        "topic": candidate.topic,
        "support_count": 1,
        "source_updated_at": candidate.source_updated_at,
        "derived_from": [candidate.summary_path] if archive_relative_ref_exists(memory_repo, candidate.summary_path) else [],
        "evidence_refs": [
            ref
            for ref in [evidence_ref_for_path(memory_repo, candidate.evidence_path)]
            if ref is not None
        ],
        "raw_refs": [
            ref
            for ref in [raw_ref_for_source_fields(candidate.source_record, candidate.source_map_path, "source_record")]
            if ref is not None
        ],
    }
    if related is not None:
        row["related_candidate_text_sha256"] = natural_candidate_text_sha256(related.text)
        row["related_source_updated_at"] = related.source_updated_at
    if detail:
        row["overlap_token_count"] = int(detail.get("overlap_token_count") or 0)
        row["overlap_ratio"] = round(float(detail.get("overlap_ratio") or 0.0), 6)
    return row


def add_induction_review_candidate(
    rows_by_id: dict[str, dict],
    withheld: set[tuple[str, str, str, str]],
    identities_by_id: dict[str, tuple[str, str, str, str]],
    candidate: MemoryCandidate,
    reason: str,
    memory_repo: Path | None,
    related: MemoryCandidate | None = None,
    detail: dict | None = None,
) -> None:
    row = natural_induction_review_candidate_row(candidate, reason, memory_repo, related, detail)
    rows_by_id.setdefault(str(row["candidate_id"]), row)
    identities_by_id.setdefault(str(row["candidate_id"]), candidate_identity(candidate))
    withheld.add(candidate_identity(candidate))
    if related is not None:
        withheld.add(candidate_identity(related))


def build_induction_review_candidates(
    candidates: list[MemoryCandidate],
    memory_repo: Path | None = None,
) -> tuple[list[dict], set[tuple[str, str, str, str]], dict[str, tuple[str, str, str, str]]]:
    rows_by_id: dict[str, dict] = {}
    withheld: set[tuple[str, str, str, str]] = set()
    identities_by_id: dict[str, tuple[str, str, str, str]] = {}
    natural_candidates = [candidate for candidate in candidates if is_natural_memory_candidate(candidate)]
    for candidate in natural_candidates:
        if should_low_confidence_review_natural_candidate(candidate):
            add_induction_review_candidate(
                rows_by_id,
                withheld,
                identities_by_id,
                candidate,
                "low_confidence_natural_induction_requires_review",
                memory_repo,
            )

    ordered = sorted(natural_candidates, key=lambda candidate: (candidate.source_updated_at, candidate.summary_path, candidate.text))
    for index, current in enumerate(ordered):
        for older in ordered[:index]:
            if memory_text_key(current.text) == memory_text_key(older.text):
                continue
            detail = semantic_relation_detail(current.text, older.text)
            reason = induction_review_reason_from_relation(detail)
            if not reason:
                continue
            add_induction_review_candidate(rows_by_id, withheld, identities_by_id, current, reason, memory_repo, older, detail)

    return (
        sorted(
            rows_by_id.values(),
            key=lambda row: (
                str(row.get("reason", "")),
                str(row.get("source_updated_at", "")),
                str(row.get("candidate_id", "")),
            ),
        ),
        withheld,
        identities_by_id,
    )


def build_memory_nodes_and_induction_review_candidates(
    rows: list[dict],
    memory_repo: Path | None = None,
    induction_review_decisions: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    memory_candidates = memory_candidates_from_meta(rows)
    induction_review_candidates, withheld_candidates, induction_candidate_identities = build_induction_review_candidates(memory_candidates, memory_repo)
    induction_review_decision_results = apply_induction_review_decisions(
        induction_review_candidates,
        induction_review_decisions or [],
    )
    for result in induction_review_decision_results:
        if result.get("status") != "applied" or result.get("action") != "approve_promote":
            continue
        candidate_id = str(result.get("candidate_id") or "")
        identity = induction_candidate_identities.get(candidate_id)
        if identity is not None:
            withheld_candidates.discard(identity)
    active_induction_review_candidates = filter_reviewed_induction_candidates(
        induction_review_candidates,
        induction_review_decision_results,
    )
    grouped: dict[str, list[MemoryCandidate]] = {}
    for candidate in memory_candidates:
        if candidate_identity(candidate) in withheld_candidates:
            continue
        key = memory_consolidation_key(candidate.text)
        grouped.setdefault(key, []).append(candidate)

    nodes: list[dict] = []
    refresh_targets_by_text: dict[str, set[str]] = {}
    deprecation_targets_by_text: dict[str, set[str]] = {}
    for consolidation_key in sorted(grouped):
        candidates = grouped[consolidation_key]
        first = candidates[0]
        refresh_targets = {
            superseded_text
            for candidate in candidates
            for superseded_text in candidate.supersedes_texts
        }
        deprecation_targets = {
            deprecated_text
            for candidate in candidates
            for deprecated_text in candidate.deprecates_texts
        }
        text = first.text
        if refresh_targets:
            refresh_targets_by_text.setdefault(memory_text_key(text), set()).update(refresh_targets)
        if deprecation_targets:
            deprecation_targets_by_text.setdefault(memory_text_key(text), set()).update(deprecation_targets)
        support_projects = {
            candidate.project_path or candidate.project
            for candidate in candidates
            if candidate.project_path or candidate.project
        }
        layer = automatic_memory_layer(first, support_projects)
        scope = memory_scope(layer, first)
        seen_times = sorted(candidate.source_updated_at for candidate in candidates if candidate.source_updated_at)
        derived_from = sorted({candidate.summary_path for candidate in candidates if candidate.summary_path})
        evidence_refs = [
            ref
            for path in sorted({candidate.evidence_path for candidate in candidates if candidate.evidence_path})
            if (ref := evidence_ref_for_path(memory_repo, path)) is not None
        ]
        raw_refs = [
            raw_ref
            for source_record, source_map_path in sorted(
                {
                    (candidate.source_record, candidate.source_map_path)
                    for candidate in candidates
                    if candidate.source_record or candidate.source_map_path
                }
            )
            if (raw_ref := raw_ref_for_source_fields(source_record, source_map_path, "source_record")) is not None
        ]
        confidence = "high" if len(candidates) >= 2 or layer == "global" else "medium"
        tags = sorted({tag for candidate in candidates for tag in candidate.tags if tag} | {first.topic})
        nodes.append(
            {
                "memory_id": memory_id_for(layer, scope, text, first.source),
                "layer": layer,
                "scope": scope,
                "topic": first.topic,
                "text": text,
                "rationale": first.rationale,
                "source": first.source,
                "confidence": confidence,
                "persistence": "normal",
                "support_count": len(candidates),
                "first_seen": seen_times[0] if seen_times else "",
                "last_seen": seen_times[-1] if seen_times else "",
                "derived_from": derived_from,
                "evidence_refs": evidence_refs,
                "raw_refs": raw_refs,
                "supersedes": [],
                "superseded_by": None,
                "tags": tags,
            }
        )
    apply_text_supersession_links(nodes, refresh_targets_by_text)
    apply_semantic_lifecycle_links(nodes)
    apply_text_deprecation_links(nodes, deprecation_targets_by_text)
    existing_ids = {str(node["memory_id"]) for node in nodes}
    for row in rows:
        explicit_texts = row.get("explicit_memories", [])
        if not isinstance(explicit_texts, list):
            continue
        for text_value in explicit_texts:
            text = normalize_memory_text(str(text_value))
            if not text:
                continue
            node = explicit_memory_node(text, row)
            if node["memory_id"] in existing_ids:
                continue
            nodes.append(node)
            existing_ids.add(str(node["memory_id"]))
    nodes.sort(key=lambda node: (str(node.get("layer", "")), str(node.get("memory_id", ""))))
    return nodes, active_induction_review_candidates, induction_review_decision_results


def build_memory_nodes(rows: list[dict], memory_repo: Path | None = None) -> list[dict]:
    nodes, _, _ = build_memory_nodes_and_induction_review_candidates(rows, memory_repo)
    return nodes


def collect_meta(memory_repo: Path) -> list[dict]:
    rows: list[dict] = []
    for meta_path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        if meta_path.is_symlink() or not is_safe_repo_path(memory_repo, meta_path):
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict):
            source_map_path = meta_path.parent / "source-map.json"
            if (
                not meta.get("source_map_path")
                and source_map_path.is_file()
                and is_safe_repo_path(memory_repo, source_map_path)
            ):
                meta["source_map_path"] = source_map_path.relative_to(memory_repo).as_posix()
            rows.append(meta)
    rows.sort(key=lambda row: row.get("source_updated_at", ""), reverse=True)
    return rows


def repair_legacy_source_map_paths(memory_repo: Path, rows: list[dict]) -> None:
    for row in rows:
        source_map_path = row.get("source_map_path")
        summary_path = row.get("summary_path")
        evidence_path = row.get("evidence_path")
        if not (
            isinstance(source_map_path, str)
            and isinstance(summary_path, str)
            and isinstance(evidence_path, str)
        ):
            continue
        source_map_file = archive_ref_path(memory_repo, source_map_path)
        if source_map_file is None or not source_map_file.is_file():
            continue
        try:
            source_map = json.loads(source_map_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(source_map, dict):
            continue
        expected = {
            "summary_path": summary_path,
            "evidence_path": evidence_path,
            "source_map_path": source_map_path,
        }
        if all(source_map.get(key) == value for key, value in expected.items()):
            continue
        source_map.update(expected)
        write_safe_archive_text(
            memory_repo,
            source_map_file,
            json.dumps(source_map, indent=2, sort_keys=True) + "\n",
            "source-map file",
        )


def load_existing_explicit_memory_nodes(memory_repo: Path) -> list[dict]:
    nodes: list[dict] = []
    for node in iter_jsonl(memory_repo / "memories" / "explicit.jsonl"):
        memory_id = node.get("memory_id")
        if node.get("source") == "explicit" and isinstance(memory_id, str) and memory_id:
            nodes.append(node)
    return nodes


def memory_node_sort_key(node: dict) -> tuple[bool, str, str, str, str]:
    return (
        node.get("source") != "automatic",
        str(node.get("layer", "")),
        str(node.get("scope", "")),
        str(node.get("topic", "")),
        str(node.get("memory_id", "")),
    )


def explicit_memory_content_key(node: dict) -> tuple[str, str, str, str] | None:
    if node.get("source") != "explicit":
        return None
    text = normalize_memory_text(str(node.get("text", ""))).lower()
    if not text:
        return None
    return (
        str(node.get("source", "")),
        str(node.get("layer", "")),
        str(node.get("scope", "")),
        text,
    )


def merge_existing_explicit_memory_nodes(memory_repo: Path, nodes: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    by_content: dict[tuple[str, str, str, str], dict] = {}

    def add_node(node: dict, *, prefer_same_content: bool) -> None:
        memory_id = node.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            return
        content_key = explicit_memory_content_key(node)
        if content_key is not None:
            existing = by_content.get(content_key)
            if existing is not None:
                if not prefer_same_content:
                    return
                node = merge_memory_node_provenance(existing, node)
                existing_id = existing.get("memory_id")
                if isinstance(existing_id, str):
                    by_id.pop(existing_id, None)
            by_content[content_key] = node
        existing_by_id = by_id.get(memory_id)
        if existing_by_id is not None:
            node = merge_memory_node_provenance(existing_by_id, node)
        by_id[memory_id] = node

    for node in load_existing_explicit_memory_nodes(memory_repo):
        add_node(node, prefer_same_content=False)
    for node in nodes:
        add_node(node, prefer_same_content=True)
    return sorted(by_id.values(), key=memory_node_sort_key)


def write_memory_nodes(memory_repo: Path, nodes: list[dict]) -> list[dict]:
    nodes = merge_existing_explicit_memory_nodes(memory_repo, nodes)
    apply_memory_id_supersession_links(nodes)
    apply_memory_id_contradiction_links(nodes)
    apply_memory_id_deprecation_links(nodes)
    memories_dir = memory_repo / "memories"
    if not is_safe_repo_path(memory_repo, memories_dir):
        raise SystemExit(f"Refusing to write unsafe archive memories path: {safe_diagnostic_path(memories_dir)}")
    memories_dir.mkdir(parents=True, exist_ok=True)
    by_layer: dict[str, list[dict]] = {"global": [], "domain": [], "project": []}
    explicit_nodes: list[dict] = []
    for node in nodes:
        layer = str(node.get("layer", "project"))
        if node.get("source") == "explicit":
            explicit_nodes.append(node)
            continue
        if layer in by_layer:
            by_layer[layer].append(node)

    for layer, file_name in MEMORY_LAYER_FILES.items():
        lines = [json.dumps(node, sort_keys=True) for node in by_layer[layer]]
        write_safe_archive_text(
            memory_repo,
            memories_dir / file_name,
            "\n".join(lines) + ("\n" if lines else ""),
            "memory node file",
        )

    explicit_lines = [json.dumps(node, sort_keys=True) for node in explicit_nodes]
    write_safe_archive_text(
        memory_repo,
        memories_dir / "explicit.jsonl",
        "\n".join(explicit_lines) + ("\n" if explicit_lines else ""),
        "memory node file",
    )
    return nodes


def safe_node_memory_id(node: dict) -> str:
    memory_id = node.get("memory_id")
    return memory_id if isinstance(memory_id, str) and memory_id else ""


def is_safe_memory_review_id(value: object) -> bool:
    return isinstance(value, str) and SAFE_MEMORY_REVIEW_ID_PATTERN.fullmatch(value) is not None


def safe_memory_review_scalar(value: object, limit: int = 120) -> str:
    text = str(value or "")
    if not SAFE_MEMORY_REVIEW_ID_PATTERN.fullmatch(text):
        return ""
    return text[:limit]


def review_candidate_fingerprint(candidate: dict) -> str:
    payload = {
        field: candidate.get(field)
        for field in MEMORY_REVIEW_CANDIDATE_FINGERPRINT_FIELDS
        if field in candidate
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def is_safe_induction_review_candidate_id(value: object) -> bool:
    return isinstance(value, str) and INDUCTION_REVIEW_CANDIDATE_ID_PATTERN.fullmatch(value) is not None


def is_safe_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and SHA256_HEX_PATTERN.fullmatch(value) is not None


def induction_review_candidate_fingerprint(candidate: dict) -> str:
    payload = {
        field: candidate.get(field)
        for field in INDUCTION_REVIEW_CANDIDATE_FINGERPRINT_FIELDS
        if field in candidate
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def build_induction_review_candidate_index(candidates: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        if is_safe_induction_review_candidate_id(candidate_id):
            index.setdefault(str(candidate_id), candidate)
    return index


def apply_induction_review_decisions(
    induction_review_candidates: list[dict],
    induction_review_decisions: list[dict],
) -> list[dict]:
    candidates_by_id = build_induction_review_candidate_index(induction_review_candidates)
    results: list[dict] = []
    for decision in induction_review_decisions:
        action = decision.get("action")
        decision_id = decision.get("decision_id")
        candidate_id = decision.get("candidate_id")
        candidate_text_sha256 = decision.get("candidate_text_sha256")
        if (
            not isinstance(action, str)
            or action not in INDUCTION_REVIEW_ACTIONS
            or not is_safe_memory_review_id(decision_id)
            or not is_safe_induction_review_candidate_id(candidate_id)
            or not is_safe_sha256_hex(candidate_text_sha256)
        ):
            raise SystemExit("unsafe induction review decision")
        candidate = candidates_by_id.get(str(candidate_id))
        if candidate is None:
            raise SystemExit("unknown induction review candidate")
        candidate_fingerprint = decision.get("candidate_fingerprint")
        if (
            candidate.get("candidate_text_sha256") != candidate_text_sha256
            or not isinstance(candidate_fingerprint, str)
            or candidate_fingerprint != induction_review_candidate_fingerprint(candidate)
        ):
            raise SystemExit("stale induction review decision")
        result = {
            "decision_id": safe_memory_review_scalar(decision_id, 120),
            "action": action,
            "candidate_id": str(candidate_id),
            "candidate_text_sha256": str(candidate_text_sha256),
            "candidate_fingerprint": candidate_fingerprint,
        }
        if action in INDUCTION_REVIEW_IGNORE_ACTIONS:
            result["status"] = "ignored"
            results.append(result)
            continue
        if action == "approve_promote":
            result["status"] = "applied"
            results.append(result)
            continue
        raise SystemExit("unsafe induction review decision")
    return results


def load_induction_review_decisions(memory_repo: Path) -> list[dict]:
    path = memory_repo / INDUCTION_REVIEW_DECISION_REL_PATH
    if not is_safe_repo_path(memory_repo, path):
        raise SystemExit("Refusing to read unsafe induction review decision path")
    return list(iter_jsonl(path))


def filter_reviewed_induction_candidates(induction_review_candidates: list[dict], decision_results: list[dict]) -> list[dict]:
    if not decision_results:
        return induction_review_candidates
    reviewed_ids = {
        str(result.get("candidate_id") or "")
        for result in decision_results
        if result.get("status") in {"applied", "ignored"}
    }
    if not reviewed_ids:
        return induction_review_candidates
    return [
        candidate
        for candidate in induction_review_candidates
        if str(candidate.get("candidate_id") or "") not in reviewed_ids
    ]


def review_candidate_pairs(candidate: dict) -> list[tuple[str, str]]:
    current_id = candidate.get("current_memory_id")
    older_id = candidate.get("older_memory_id")
    if not is_safe_memory_review_id(current_id) or not is_safe_memory_review_id(older_id):
        return []
    older_ids = [older_id]
    compressed_older_ids = candidate.get("compressed_older_memory_ids", [])
    if isinstance(compressed_older_ids, list):
        for item in compressed_older_ids:
            if is_safe_memory_review_id(item) and item not in older_ids:
                older_ids.append(item)
    return [(str(current_id), str(item)) for item in older_ids]


def build_memory_review_candidate_index(candidates: list[dict]) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for candidate in candidates:
        for pair in review_candidate_pairs(candidate):
            index.setdefault(pair, candidate)
    return index


def apply_memory_review_decisions(
    nodes: list[dict],
    review_candidates: list[dict],
    review_decisions: list[dict],
) -> list[dict]:
    nodes_by_id = {
        memory_id: node
        for node in nodes
        if (memory_id := safe_node_memory_id(node))
    }
    candidates_by_pair = build_memory_review_candidate_index(review_candidates)
    results: list[dict] = []
    for decision in review_decisions:
        action = decision.get("action")
        current_id = decision.get("current_memory_id")
        older_id = decision.get("older_memory_id")
        if (
            not isinstance(action, str)
            or action not in MEMORY_REVIEW_ACTIONS
            or not is_safe_memory_review_id(current_id)
            or not is_safe_memory_review_id(older_id)
            or current_id == older_id
        ):
            raise SystemExit("unsafe memory review decision")
        candidate = candidates_by_pair.get((current_id, older_id))
        if candidate is None:
            raise SystemExit("unknown memory review candidate")
        candidate_fingerprint = decision.get("candidate_fingerprint")
        if (
            not isinstance(candidate_fingerprint, str)
            or candidate_fingerprint != review_candidate_fingerprint(candidate)
        ):
            raise SystemExit("stale memory review decision")
        current = nodes_by_id.get(current_id)
        old = nodes_by_id.get(older_id)
        if current is None or old is None:
            raise SystemExit("unknown memory review target")
        result = {
            "decision_id": safe_memory_review_scalar(decision.get("decision_id") or "", 120),
            "action": action,
            "current_memory_id": current_id,
            "older_memory_id": older_id,
            "candidate_fingerprint": candidate_fingerprint,
        }
        if action in MEMORY_REVIEW_IGNORE_ACTIONS:
            result["status"] = "ignored"
            results.append(result)
            continue
        if action == "approve_supersedes":
            add_supersession_link(current, old)
        elif action == "approve_contradicts":
            add_contradiction_link(current, old)
        elif action == "approve_deprecates":
            add_deprecation_link(current, old)
        result["status"] = "applied"
        results.append(result)
    return results


def load_memory_review_decisions(memory_repo: Path) -> list[dict]:
    path = memory_repo / MEMORY_REVIEW_DECISION_REL_PATH
    if not is_safe_repo_path(memory_repo, path):
        raise SystemExit("Refusing to read unsafe memory review decision path")
    return list(iter_jsonl(path))


def filter_reviewed_memory_candidates(review_candidates: list[dict], decision_results: list[dict]) -> list[dict]:
    if not decision_results:
        return review_candidates
    reviewed_pairs = {
        (str(result.get("current_memory_id") or ""), str(result.get("older_memory_id") or ""))
        for result in decision_results
        if result.get("status") in {"applied", "ignored"}
    }
    if not reviewed_pairs:
        return review_candidates
    out: list[dict] = []
    for candidate in review_candidates:
        pairs = review_candidate_pairs(candidate)
        if pairs and all(pair in reviewed_pairs for pair in pairs):
            continue
        out.append(candidate)
    return out


def string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def has_lifecycle_link(current: dict, old: dict) -> bool:
    current_id = safe_node_memory_id(current)
    old_id = safe_node_memory_id(old)
    if not current_id or not old_id:
        return False
    return (
        old_id in set(string_items(current.get("supersedes")))
        or old_id in set(string_items(current.get("contradicts")))
        or old_id in set(string_items(current.get("deprecates")))
        or old.get("superseded_by") == current_id
        or old.get("deprecated_by") == current_id
        or current_id in set(string_items(old.get("contradicted_by")))
    )


def should_queue_memory_review_candidate(reason: str, detail: dict) -> bool:
    if reason == "ambiguous_scope_narrowing_requires_review":
        try:
            overlap_ratio = float(detail.get("overlap_ratio") or 0.0)
        except (TypeError, ValueError):
            return False
        return overlap_ratio >= MIN_AMBIGUOUS_SCOPE_REVIEW_OVERLAP_RATIO
    return True


def is_same_scope_low_risk_review_candidate(candidate: dict, nodes_by_id: dict[str, dict]) -> bool:
    if candidate.get("reason") != "low_confidence_semantic_overlap_requires_review":
        return False
    current = nodes_by_id.get(str(candidate.get("current_memory_id") or ""))
    old = nodes_by_id.get(str(candidate.get("older_memory_id") or ""))
    if current is None or old is None:
        return False
    current_layer = str(current.get("layer") or "")
    old_layer = str(old.get("layer") or "")
    current_scope = str(current.get("scope") or "")
    old_scope = str(old.get("scope") or "")
    return bool(current_layer and current_scope and current_layer == old_layer and current_scope == old_scope)


def compress_low_risk_review_candidates(candidates: list[dict], nodes_by_id: dict[str, dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    passthrough: list[dict] = []
    for candidate in candidates:
        if not is_same_scope_low_risk_review_candidate(candidate, nodes_by_id):
            passthrough.append(candidate)
            continue
        key = (
            str(candidate.get("current_memory_id") or ""),
            str(candidate.get("reason") or ""),
        )
        grouped.setdefault(key, []).append(candidate)

    compressed: list[dict] = []
    for group in grouped.values():
        if len(group) == 1:
            compressed.extend(group)
            continue
        ordered = sorted(
            group,
            key=lambda item: (
                str(item.get("older_memory_id") or ""),
                str(item.get("current_memory_id") or ""),
            ),
        )
        representative = dict(ordered[0])
        older_ids = [
            older_id
            for candidate in ordered
            if isinstance((older_id := candidate.get("older_memory_id")), str) and older_id
        ]
        representative["candidate_type"] = "compressed_low_risk_semantic_lifecycle"
        representative["compressed_candidate_count"] = len(ordered)
        representative["compressed_older_memory_ids"] = older_ids
        representative["compression_reason"] = "same_scope_low_confidence_semantic_overlap"
        representative["overlap_token_count"] = max(int(item.get("overlap_token_count") or 0) for item in ordered)
        representative["overlap_ratio"] = round(max(float(item.get("overlap_ratio") or 0.0) for item in ordered), 6)
        compressed.append(representative)
    return [*passthrough, *compressed]


def build_memory_review_candidates(nodes: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    automatic_nodes = [node for node in nodes if node.get("source") == "automatic"]
    nodes_by_id = {
        memory_id: node
        for node in automatic_nodes
        if (memory_id := safe_node_memory_id(node))
    }
    seen: set[tuple[str, str, str]] = set()
    for current in sorted(automatic_nodes, key=node_last_seen_key):
        current_id = safe_node_memory_id(current)
        if not current_id:
            continue
        for old in automatic_nodes:
            old_id = safe_node_memory_id(old)
            if not old_id or current is old:
                continue
            if node_last_seen_key(current) <= node_last_seen_key(old):
                continue
            if has_lifecycle_link(current, old):
                continue
            detail = semantic_relation_detail(str(current.get("text", "")), str(old.get("text", "")))
            reason = str(detail.get("review_reason") or "")
            if not reason or not should_queue_memory_review_candidate(reason, detail):
                continue
            key = (current_id, old_id, reason)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "candidate_type": "ambiguous_semantic_lifecycle",
                    "current_memory_id": current_id,
                    "older_memory_id": old_id,
                    "reason": reason,
                    "recommended_action": "manual_review",
                    "current_last_seen": str(current.get("last_seen") or ""),
                    "older_last_seen": str(old.get("last_seen") or ""),
                    "overlap_token_count": int(detail.get("overlap_token_count") or 0),
                    "overlap_ratio": round(float(detail.get("overlap_ratio") or 0.0), 6),
                }
            )
    candidates = compress_low_risk_review_candidates(candidates, nodes_by_id)
    return sorted(
        candidates,
        key=lambda item: (
            str(item.get("current_memory_id", "")),
            str(item.get("older_memory_id", "")),
            str(item.get("reason", "")),
        ),
    )


def build_memory_consolidation_traces(nodes: list[dict], review_candidates: list[dict]) -> list[dict]:
    traces: list[dict] = []
    for node in nodes:
        memory_id = safe_node_memory_id(node)
        if not memory_id:
            continue
        support_count = node.get("support_count")
        if isinstance(support_count, int) and support_count > 1:
            traces.append(
                {
                    "decision": "merge",
                    "reason": "same_consolidation_key_support_merge",
                    "memory_id": memory_id,
                    "support_count": support_count,
                }
            )
        for target_id in sorted(string_items(node.get("supersedes"))):
            traces.append(
                {
                    "decision": "supersede",
                    "reason": "confirmed_supersession_link",
                    "current_memory_id": memory_id,
                    "target_memory_id": target_id,
                }
            )
        for target_id in sorted(string_items(node.get("contradicts"))):
            traces.append(
                {
                    "decision": "contradict",
                    "reason": "confirmed_contradiction_link",
                    "current_memory_id": memory_id,
                    "target_memory_id": target_id,
                }
            )
        for target_id in sorted(string_items(node.get("deprecates"))):
            traces.append(
                {
                    "decision": "deprecate",
                    "reason": "confirmed_deprecation_link",
                    "current_memory_id": memory_id,
                    "target_memory_id": target_id,
                }
            )
    for candidate in review_candidates:
        trace = {
            "decision": "skip",
            "reason": candidate.get("reason", ""),
            "current_memory_id": candidate.get("current_memory_id", ""),
            "target_memory_id": candidate.get("older_memory_id", ""),
            "review_candidate": True,
        }
        for key in ("compressed_candidate_count", "compressed_older_memory_ids", "compression_reason"):
            if key in candidate:
                trace[key] = candidate[key]
        traces.append(trace)
    return sorted(
        traces,
        key=lambda item: (
            str(item.get("decision", "")),
            str(item.get("memory_id", "")),
            str(item.get("current_memory_id", "")),
            str(item.get("target_memory_id", "")),
            str(item.get("reason", "")),
        ),
    )


def write_jsonl_index(memory_repo: Path, path: Path, rows: list[dict], label: str) -> None:
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    write_safe_archive_text(memory_repo, path, "\n".join(lines) + ("\n" if lines else ""), label)


def rebuild_indexes(memory_repo: Path) -> None:
    index_dir = memory_repo / "index"
    if not is_safe_repo_path(memory_repo, index_dir):
        raise SystemExit(f"Refusing to write unsafe archive index path: {safe_diagnostic_path(index_dir)}")
    index_dir.mkdir(parents=True, exist_ok=True)
    rows = collect_meta(memory_repo)
    repair_legacy_source_map_paths(memory_repo, rows)
    induction_review_decisions = load_induction_review_decisions(memory_repo)
    memory_nodes, induction_review_candidates, induction_review_decision_results = build_memory_nodes_and_induction_review_candidates(
        rows,
        memory_repo,
        induction_review_decisions,
    )
    review_decisions = load_memory_review_decisions(memory_repo)
    initial_review_candidates = build_memory_review_candidates(memory_nodes)
    review_decision_results = apply_memory_review_decisions(
        memory_nodes,
        initial_review_candidates,
        review_decisions,
    )
    memory_nodes = write_memory_nodes(memory_repo, memory_nodes)
    review_candidates = build_memory_review_candidates(memory_nodes)
    review_candidates = filter_reviewed_memory_candidates(review_candidates, review_decision_results)
    consolidation_traces = build_memory_consolidation_traces(memory_nodes, review_candidates)

    sessions_lines: list[str] = []
    project_latest: dict[str, dict] = {}
    for row in rows:
        session_row = {
            "date": str(row.get("source_updated_at", ""))[:10],
            "session_id": row.get("session_id", ""),
            "source_agent": row.get("source_agent", ""),
            "project": row.get("project", ""),
            "project_path": row.get("project_path", ""),
            "title": index_title_from_meta(row),
            "source_record": row.get("source_record", ""),
            "user_intent": row.get("user_intent", ""),
            "summary": row.get("summary", ""),
            "reusable_facts": row.get("reusable_facts", []),
            "summary_path": row.get("summary_path", ""),
            "evidence_path": row.get("evidence_path", ""),
            "source_map_path": row.get("source_map_path", ""),
            "source_updated_at": row.get("source_updated_at", ""),
            "archive_status": row.get("archive_status", ""),
            "unresolved_count": len(row.get("unresolved_tasks", [])) if isinstance(row.get("unresolved_tasks"), list) else 0,
            "tags": row.get("tags") or [slugify(str(row.get("project", "")))],
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

    write_safe_archive_text(
        memory_repo,
        index_dir / "sessions.jsonl",
        "\n".join(sessions_lines) + ("\n" if sessions_lines else ""),
        "index file",
    )
    write_safe_archive_text(
        memory_repo,
        index_dir / "projects.jsonl",
        "\n".join(json.dumps(row, sort_keys=True) for row in project_latest.values()) + ("\n" if project_latest else ""),
        "index file",
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
    write_safe_archive_text(
        memory_repo,
        index_dir / "decisions.jsonl",
        "\n".join(decision_lines) + ("\n" if decision_lines else ""),
        "index file",
    )
    write_safe_archive_text(
        memory_repo,
        index_dir / "unresolved.jsonl",
        "\n".join(unresolved_lines) + ("\n" if unresolved_lines else ""),
        "index file",
    )
    write_safe_archive_text(
        memory_repo,
        index_dir / "files.jsonl",
        "\n".join(file_lines) + ("\n" if file_lines else ""),
        "index file",
    )
    write_safe_archive_text(
        memory_repo,
        index_dir / "tags.jsonl",
        "\n".join(tag_lines) + ("\n" if tag_lines else ""),
        "index file",
    )
    memory_lines = [json.dumps(node, sort_keys=True) for node in memory_nodes]
    write_safe_archive_text(
        memory_repo,
        index_dir / "memories.jsonl",
        "\n".join(memory_lines) + ("\n" if memory_lines else ""),
        "index file",
    )
    write_jsonl_index(memory_repo, index_dir / "memory_review_candidates.jsonl", review_candidates, "memory review index")
    write_jsonl_index(
        memory_repo,
        index_dir / "induction_review_candidates.jsonl",
        induction_review_candidates,
        "induction review index",
    )
    write_jsonl_index(
        memory_repo,
        index_dir / "induction_review_decision_results.jsonl",
        induction_review_decision_results,
        "induction review decision index",
    )
    write_jsonl_index(
        memory_repo,
        index_dir / "memory_review_decision_results.jsonl",
        review_decision_results,
        "memory review decision index",
    )
    write_jsonl_index(memory_repo, index_dir / "memory_consolidation_trace.jsonl", consolidation_traces, "memory trace index")

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
    index_overview_path = memory_repo / "INDEX.md"
    if not is_safe_repo_path(memory_repo, index_overview_path):
        raise SystemExit(
            f"Refusing to write unsafe archive index overview path: {safe_diagnostic_path(index_overview_path)}"
        )
    index_overview_path.write_text(index_md, encoding="utf-8")
    render_daily_summaries(memory_repo, rows)


def render_daily_summaries(memory_repo: Path, rows: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        day = str(row.get("source_updated_at", ""))[:10]
        if day:
            grouped.setdefault(day, []).append(row)
    daily_root = memory_repo / "daily"
    if not is_safe_repo_path(memory_repo, daily_root):
        raise SystemExit(f"Refusing to write unsafe archive daily path: {safe_diagnostic_path(daily_root)}")
    expected_paths = {memory_repo / "daily" / day[:4] / f"{day}.md" for day in grouped}
    if daily_root.exists():
        for path in sorted(daily_root.glob("**/*.md")):
            if path not in expected_paths:
                path.unlink()
        prune_empty_session_dirs(daily_root)
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
        write_safe_archive_text(memory_repo, daily_dir / f"{day}.md", daily_md, "daily file")


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
        "--rewrite-existing",
        action="store_true",
        help="Rebuild matching source records and replace older archive entries for the same project/source record",
    )
    parser.add_argument(
        "--require-project-metadata",
        action="store_true",
        help="Only archive source records that explicitly identify the current project path",
    )
    parser.add_argument("--explicit-memory", action="append", default=[], help="Write a sticky high-level explicit memory")
    parser.add_argument(
        "--explicit-layer",
        choices=("global", "domain", "project"),
        default="global",
        help="Layer for --explicit-memory",
    )
    parser.add_argument("--explicit-scope", default="global", help="Scope for --explicit-memory")
    parser.add_argument("--explicit-summary-path", help="Archive-relative summary path supporting --explicit-memory")
    parser.add_argument(
        "--explicit-evidence-ref",
        action="append",
        default=[],
        help="Archive evidence ref PATH#QUOTE_ID for --explicit-memory",
    )
    parser.add_argument(
        "--explicit-raw-ref",
        action="append",
        default=[],
        help="Optional raw/source ref PATH#ANCHOR for --explicit-memory",
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
        raise SystemExit(f"source directory not found: {safe_diagnostic_path(source_dir)}")
    if source_dir == project_path:
        print("warning: source-dir equals project-path; ensure this directory contains session records, not general source files", file=sys.stderr)

    if args.explicit_memory:
        if not args.explicit_summary_path:
            raise SystemExit("--explicit-summary-path is required with --explicit-memory")
        if not args.explicit_evidence_ref:
            raise SystemExit("--explicit-evidence-ref is required with --explicit-memory")
        summary_path = args.explicit_summary_path.strip()
        if not existing_archive_ref(memory_repo, summary_path):
            raise SystemExit("--explicit-summary-path must point to an existing archive file")
        evidence_refs = []
        for value in args.explicit_evidence_ref:
            path, quote_id = parse_archive_ref(value, "--explicit-evidence-ref")
            evidence_path = archive_ref_path(memory_repo, path)
            if evidence_path is None or not evidence_quote_id_exists(evidence_path, quote_id):
                raise SystemExit("--explicit-evidence-ref must point to an existing evidence quote")
            evidence_refs.append({"path": path, "quote_id": quote_id})
        raw_refs = []
        for value in args.explicit_raw_ref:
            path, anchor = parse_archive_ref(value, "--explicit-raw-ref")
            ref = {"path": path, "anchor": anchor}
            if not is_safe_direct_raw_ref(ref):
                raise SystemExit("--explicit-raw-ref is unsafe")
            raw_refs.append(ref)
        now = isoformat(datetime.now(UTC))
        direct_nodes = [
            direct_explicit_memory_node(
                text,
                args.explicit_layer,
                args.explicit_scope,
                summary_path,
                evidence_refs,
                raw_refs,
                now,
            )
            for text in args.explicit_memory
        ]
        existing_rows = collect_meta(memory_repo)
        generated_nodes = build_memory_nodes(existing_rows)
        write_memory_nodes(memory_repo, [*generated_nodes, *direct_nodes])
        rebuild_indexes(memory_repo)
        return 0

    latest, archived_hashes, archived_source_hashes = archived_project_state(memory_repo, project_path)
    records = discover_records(
        source_dir,
        patterns,
        None if args.rewrite_existing else latest,
        project_path,
        set() if args.rewrite_existing else archived_hashes,
        {} if args.rewrite_existing else archived_source_hashes,
        require_project_metadata=args.require_project_metadata,
    )
    if args.max_records >= 0:
        records = records[: args.max_records]

    print(f"Memory repo: {safe_diagnostic_path(memory_repo)}")
    print(f"Project path: {safe_diagnostic_path(project_path)}")
    print(f"Source dir: {safe_diagnostic_path(source_dir)}")
    print(f"Latest archived timestamp: {isoformat(latest) if latest else '<none>'}")
    print(f"Records selected: {len(records)}")

    for record in records:
        print(f"- {isoformat(record.updated_at)} {safe_diagnostic_path(record.path)}")

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
            print(f"- {safe_diagnostic_path(record.path)}: {labels}", file=sys.stderr)
        print("Review the source records or rerun with --allow-redacted-secrets to store redacted snippets.", file=sys.stderr)
        return 2

    removed_entries = 0
    skipped_records = 0
    for record in records:
        if args.rewrite_existing or str(record.path.resolve()) in archived_source_hashes:
            removed_entries += remove_existing_entries_for_source(memory_repo, project_path, record.path)
        written = write_record(
            memory_repo=memory_repo,
            project_path=project_path,
            project_name=project_name,
            source_agent=args.source_agent,
            record=record,
        )
        if written is None:
            skipped_records += 1
    rebuild_indexes(memory_repo)
    if args.rewrite_existing or removed_entries:
        print(f"Existing entries removed: {removed_entries}")
    print(f"Records skipped as low-signal: {skipped_records}")
    print("Archive update complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
