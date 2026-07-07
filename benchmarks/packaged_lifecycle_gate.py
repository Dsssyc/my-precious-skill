#!/usr/bin/env python3
"""Run a clean-room packaged lifecycle gate for My Precious skills."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
QUERY = "packaged lifecycle clean-room archive audit"
EXPLICIT_CAPTURE_QUERY = "explicit memory capture adapter unsupported recollection"
EXPLICIT_CAPTURE_TEXT = "Prefer explicit memory capture adapter over unsupported recollection."
EXPLICIT_RAW_TRANSCRIPT_SENTINEL = "RAW TRANSCRIPT SHOULD NOT BE CAPTURED"
EXPLICIT_REVISION_QUERY = "explicit revision policy conflict handling"
EXPLICIT_REVISION_OLD_TEXT = "Prefer the legacy explicit revision policy for conflict handling."
EXPLICIT_REVISION_CURRENT_TEXT = "Prefer the current explicit revision policy for conflict handling."
EXPLICIT_WITHDRAW_QUERY = "obsolete explicit withdrawal policy conflict handling"
EXPLICIT_WITHDRAW_OLD_TEXT = "Prefer the obsolete explicit withdrawal policy for conflict handling."
EXPLICIT_WITHDRAW_MARKER_TEXT = "Withdraw obsolete explicit withdrawal policy for conflict handling."
EXPLICIT_UNSAFE_REVISION_SENTINEL = "mem_cookie_SHOULD_NOT_RENDER"
SOURCE_TEXT = (
    "Remember this: clean-room lifecycle fact validates packaged setup, update, "
    "search, and audit using public synthetic records."
)
AUTOMATION_NOISE_MARKERS = (
    "Automation run status",
    "No memory hits for: memory",
    "AGENTS/environment/policy blocks",
)
AUTOMATION_SOURCE_RECORDS = ("automation-thread.jsonl", "automation-noise.jsonl")


class GateFailure(Exception):
    def __init__(self, stage: str, reason: str, returncode: int | None = None) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def to_report(self) -> dict[str, object]:
        report: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            report["returncode"] = self.returncode
        return report


@dataclass(frozen=True)
class GatePaths:
    root: Path
    memory_repo: Path
    source_dir: Path
    project_path: Path


def run_command(command: list[str], stage: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result


def write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n", encoding="utf-8")


def write_synthetic_source_records(source_dir: Path, project_path: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    project_path.mkdir(parents=True, exist_ok=True)
    human_events: list[dict[str, object]] = [
        {
            "type": "session_meta",
            "timestamp": "2026-07-06T12:00:00Z",
            "payload": {
                "id": "packaged-lifecycle-clean-room",
                "cwd": str(project_path),
                "project_path": str(project_path),
                "thread_source": "local",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-06T12:00:01Z",
            "payload": {
                "role": "user",
                "content": [{"type": "input_text", "text": SOURCE_TEXT}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-06T12:00:02Z",
            "payload": {
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "Decision: packaged lifecycle smoke checks must cover setup, "
                            "update, search, and audit with synthetic public records."
                        ),
                    }
                ],
            },
        },
    ]
    write_jsonl(source_dir / "packaged-lifecycle.jsonl", human_events)

    automation_events: list[dict[str, object]] = [
        {
            "type": "session_meta",
            "timestamp": "2026-07-06T13:00:00Z",
            "payload": {
                "id": "packaged-lifecycle-automation-thread",
                "cwd": str(project_path),
                "project_path": str(project_path),
                "thread_source": "automation",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-06T13:00:01Z",
            "payload": {
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "Automation run status: updater completed. "
                            "AGENTS/environment/policy blocks were checked."
                        ),
                    }
                ],
            },
        },
    ]
    write_jsonl(source_dir / AUTOMATION_SOURCE_RECORDS[0], automation_events)

    automation_noise_events: list[dict[str, object]] = [
        {
            "type": "session_meta",
            "timestamp": "2026-07-06T14:00:00Z",
            "payload": {
                "id": "packaged-lifecycle-automation-noise",
                "cwd": str(project_path),
                "project_path": str(project_path),
                "thread_source": "automation",
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-07-06T14:00:01Z",
            "payload": {
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": (
                            "No memory hits for: memory. "
                            "This scheduled run note is not durable memory."
                        ),
                    }
                ],
            },
        },
    ]
    write_jsonl(source_dir / AUTOMATION_SOURCE_RECORDS[1], automation_noise_events)


def nonempty_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def session_dirs(memory_repo: Path) -> list[Path]:
    sessions_root = memory_repo / "sessions"
    if not sessions_root.exists():
        return []
    return sorted(path for path in sessions_root.glob("*/*/*/*") if path.is_dir())


def archived_record_session_dirs(memory_repo: Path) -> list[Path]:
    return [path for path in session_dirs(memory_repo) if not path.name.startswith("explicit-capture-")]


def validate_archive_artifacts(memory_repo: Path) -> list[str]:
    errors: list[str] = []
    required_files = (
        "INDEX.md",
        "index/sessions.jsonl",
        "index/memories.jsonl",
    )
    for rel_path in required_files:
        path = memory_repo / rel_path
        if not path.exists():
            errors.append(f"missing {rel_path}")
        elif path.stat().st_size == 0:
            errors.append(f"empty {rel_path}")

    sessions = archived_record_session_dirs(memory_repo)
    if not sessions:
        errors.append("missing sessions entry")
    for required in ("summary.md", "evidence.md", "meta.json", "source-map.json"):
        if sessions and not any((session / required).exists() for session in sessions):
            errors.append(f"missing sessions {required}")

    daily_files = sorted((memory_repo / "daily").glob("*/*.md")) if (memory_repo / "daily").exists() else []
    if not daily_files:
        errors.append("missing daily record")

    memory_files = sorted((memory_repo / "memories").glob("*.jsonl")) if (memory_repo / "memories").exists() else []
    if not memory_files:
        errors.append("missing memories jsonl")
    elif not any(nonempty_jsonl_count(path) for path in memory_files):
        errors.append("empty memories jsonl")

    if nonempty_jsonl_count(memory_repo / "index/memories.jsonl") <= 0:
        errors.append("empty searchable memory index")

    return errors


def setup_archive(paths: GatePaths) -> None:
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(paths.memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        "setup",
    )


def initialize_git_repo(memory_repo: Path, message: str) -> None:
    run_command(["git", "init", "-q"], "git:init", cwd=memory_repo)
    run_command(["git", "config", "user.email", "synthetic@example.invalid"], "git:config-email", cwd=memory_repo)
    run_command(["git", "config", "user.name", "Synthetic Gate"], "git:config-name", cwd=memory_repo)
    run_command(["git", "add", "."], "git:add", cwd=memory_repo)
    run_command(["git", "commit", "-m", message], "git:commit", cwd=memory_repo)


def update_archive(paths: GatePaths) -> None:
    update_script = paths.memory_repo / "tools/update_memory_archive.py"
    run_command(
        [
            sys.executable,
            str(update_script),
            "--memory-repo",
            str(paths.memory_repo),
            "--source-dir",
            str(paths.source_dir),
            "--project-path",
            str(paths.project_path),
            "--project",
            "packaged-lifecycle",
            "--source-agent",
            "synthetic",
            "--require-project-metadata",
        ],
        "update",
    )


def run_searches(paths: GatePaths) -> list[str]:
    search_script = paths.memory_repo / "tools/search_memory.py"
    completed_depths: list[str] = []
    for depth in ("memory", "session", "evidence", "source"):
        result = run_command(
            [
                sys.executable,
                str(search_script),
                QUERY,
                "--repo",
                str(paths.memory_repo),
                "--depth",
                depth,
                "--project-path",
                str(paths.project_path),
                "--limit",
                "5",
            ],
            f"search:{depth}",
        )
        lowered = result.stdout.lower()
        if "no memory hits" in lowered or "no hits" in lowered:
            raise GateFailure(f"search:{depth}", "no_hits")
        if depth == "source" and "raw_source_preview" in lowered:
            raise GateFailure("search:source", "rendered_raw_source_preview")
        completed_depths.append(depth)
    return completed_depths


def run_search_health_check(paths: GatePaths) -> None:
    search_script = paths.memory_repo / "tools/search_memory.py"
    run_command(
        [
            sys.executable,
            str(search_script),
            "--repo",
            str(paths.memory_repo),
            "--health-check",
        ],
        "search:health-check",
    )


def run_explicit_capture_adapter(paths: GatePaths) -> dict[str, object]:
    adapter_script = paths.memory_repo / "tools/capture_explicit_memory.py"
    valid_input = paths.root / "explicit-capture.jsonl"
    valid_input.write_text(
        json.dumps(
            {
                "text": EXPLICIT_CAPTURE_TEXT,
                "layer": "domain",
                "scope": "domain:agent-memory",
                "source": "explicit_request",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_command(
        [
            sys.executable,
            str(adapter_script),
            "--memory-repo",
            str(paths.memory_repo),
            "--input",
            str(valid_input),
        ],
        "explicit_capture:adapter",
    )
    try:
        adapter_report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("explicit_capture:adapter", "invalid_json") from exc
    if not isinstance(adapter_report, dict) or adapter_report.get("status") != "passed":
        raise GateFailure("explicit_capture:adapter", "report_not_passed")

    rejected_input = paths.root / "explicit-capture-raw.jsonl"
    rejected_input.write_text(
        json.dumps(
            {
                "text": "Prefer short explicit memory facts.",
                "raw_transcript": EXPLICIT_RAW_TRANSCRIPT_SENTINEL,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [
            sys.executable,
            str(adapter_script),
            "--memory-repo",
            str(paths.memory_repo),
            "--input",
            str(rejected_input),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if rejected.returncode == 0:
        raise GateFailure("explicit_capture:raw_refusal", "accepted_raw_transcript")
    if "raw transcript fields are not accepted" not in rejected.stderr:
        raise GateFailure("explicit_capture:raw_refusal", "unexpected_refusal_reason")

    explicit_nodes = [
        row
        for row in iter_jsonl(paths.memory_repo / "memories/explicit.jsonl")
        if row.get("text") == EXPLICIT_CAPTURE_TEXT
    ]
    search = run_command(
        [
            sys.executable,
            str(paths.memory_repo / "tools/search_memory.py"),
            EXPLICIT_CAPTURE_QUERY,
            "--repo",
            str(paths.memory_repo),
            "--depth",
            "source",
        ],
        "explicit_capture:search",
    )
    if explicit_nodes and f"memory_id: {explicit_nodes[0].get('memory_id')}" not in search.stdout:
        raise GateFailure("explicit_capture:search", "missing_explicit_memory_hit")
    if "raw_source_preview" in search.stdout:
        raise GateFailure("explicit_capture:search", "rendered_raw_source_preview")
    combined_output = "\n".join((result.stdout, result.stderr, rejected.stdout, rejected.stderr))
    privacy_leak_count = sum(
        1 for value in (EXPLICIT_CAPTURE_TEXT, EXPLICIT_RAW_TRANSCRIPT_SENTINEL) if value in combined_output
    )
    return {
        "status": "passed",
        "adapter_input_records": int(adapter_report.get("records_read", 0)),
        "captured_memory_nodes": len(explicit_nodes),
        "rejected_raw_transcript_records": 1,
        "search_hit_count": 1 if explicit_nodes else 0,
        "privacy_leak_count": privacy_leak_count,
    }


def run_explicit_revision_adapter(paths: GatePaths) -> dict[str, object]:
    adapter_script = paths.memory_repo / "tools/capture_explicit_memory.py"

    def run_adapter(record: dict[str, object], label: str) -> dict[str, object]:
        input_path = paths.root / f"{label}.jsonl"
        input_path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        result = run_command(
            [
                sys.executable,
                str(adapter_script),
                "--memory-repo",
                str(paths.memory_repo),
                "--input",
                str(input_path),
            ],
            f"explicit_revision:{label}",
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GateFailure(f"explicit_revision:{label}", "invalid_json") from exc
        if not isinstance(parsed, dict) or parsed.get("status") != "passed":
            raise GateFailure(f"explicit_revision:{label}", "report_not_passed")
        return parsed

    run_adapter(
        {
            "text": EXPLICIT_REVISION_OLD_TEXT,
            "layer": "domain",
            "scope": "domain:agent-memory",
            "source": "explicit_request",
        },
        "old-capture",
    )
    old_node = next(
        (row for row in iter_jsonl(paths.memory_repo / "memories/explicit.jsonl") if row.get("text") == EXPLICIT_REVISION_OLD_TEXT),
        None,
    )
    if not isinstance(old_node, dict):
        raise GateFailure("explicit_revision:old-capture", "missing_old_node")
    old_memory_id = str(old_node.get("memory_id") or "")

    replace_report = run_adapter(
        {
            "operation": "replace",
            "text": EXPLICIT_REVISION_CURRENT_TEXT,
            "layer": "domain",
            "scope": "domain:agent-memory",
            "source": "explicit_request",
            "replaces_memory_id": old_memory_id,
        },
        "replace",
    )
    run_adapter(
        {
            "text": EXPLICIT_WITHDRAW_OLD_TEXT,
            "layer": "domain",
            "scope": "domain:agent-memory",
            "source": "explicit_request",
        },
        "withdraw-old-capture",
    )
    withdrawn_old_node = next(
        (row for row in iter_jsonl(paths.memory_repo / "memories/explicit.jsonl") if row.get("text") == EXPLICIT_WITHDRAW_OLD_TEXT),
        None,
    )
    if not isinstance(withdrawn_old_node, dict):
        raise GateFailure("explicit_revision:withdraw-old-capture", "missing_withdraw_old_node")
    withdrawn_old_memory_id = str(withdrawn_old_node.get("memory_id") or "")

    withdraw_report = run_adapter(
        {
            "operation": "withdraw",
            "text": EXPLICIT_WITHDRAW_MARKER_TEXT,
            "layer": "domain",
            "scope": "domain:agent-memory",
            "source": "explicit_request",
            "deprecates_memory_id": withdrawn_old_memory_id,
        },
        "withdraw",
    )

    rejected_input = paths.root / "explicit-revision-unsafe.jsonl"
    rejected_input.write_text(
        json.dumps(
            {
                "operation": "replace",
                "text": "Prefer safe explicit memory revision targets.",
                "replaces_memory_id": EXPLICIT_UNSAFE_REVISION_SENTINEL,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [
            sys.executable,
            str(adapter_script),
            "--memory-repo",
            str(paths.memory_repo),
            "--input",
            str(rejected_input),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if rejected.returncode == 0:
        raise GateFailure("explicit_revision:unsafe_refusal", "accepted_unsafe_target")
    if "explicit memory revision target is unsafe" not in rejected.stderr:
        raise GateFailure("explicit_revision:unsafe_refusal", "unexpected_refusal_reason")

    explicit_rows = list(iter_jsonl(paths.memory_repo / "memories/explicit.jsonl"))
    rows_by_text = {row.get("text"): row for row in explicit_rows}
    old_node = rows_by_text.get(EXPLICIT_REVISION_OLD_TEXT)
    current_node = rows_by_text.get(EXPLICIT_REVISION_CURRENT_TEXT)
    withdrawn_old_node = rows_by_text.get(EXPLICIT_WITHDRAW_OLD_TEXT)
    withdrawal_node = rows_by_text.get(EXPLICIT_WITHDRAW_MARKER_TEXT)
    if not all(isinstance(row, dict) for row in (old_node, current_node, withdrawn_old_node, withdrawal_node)):
        raise GateFailure("explicit_revision:nodes", "missing_revision_nodes")
    if current_node.get("supersedes") != [old_node.get("memory_id")] or old_node.get("superseded_by") != current_node.get("memory_id"):
        raise GateFailure("explicit_revision:supersession", "missing_supersession_links")
    if withdrawal_node.get("deprecates") != [withdrawn_old_node.get("memory_id")] or withdrawn_old_node.get("deprecated_by") != withdrawal_node.get("memory_id"):
        raise GateFailure("explicit_revision:deprecation", "missing_deprecation_links")

    current_search = run_command(
        [
            sys.executable,
            str(paths.memory_repo / "tools/search_memory.py"),
            EXPLICIT_REVISION_QUERY,
            "--repo",
            str(paths.memory_repo),
            "--depth",
            "source",
        ],
        "explicit_revision:search-current",
    )
    withdrawn_search = run_command(
        [
            sys.executable,
            str(paths.memory_repo / "tools/search_memory.py"),
            EXPLICIT_WITHDRAW_QUERY,
            "--repo",
            str(paths.memory_repo),
        ],
        "explicit_revision:search-withdrawn",
    )
    current_id = str(current_node.get("memory_id") or "")
    old_id = str(old_node.get("memory_id") or "")
    withdrawn_old_id = str(withdrawn_old_node.get("memory_id") or "")
    if current_id not in current_search.stdout:
        raise GateFailure("explicit_revision:search-current", "missing_current_fact")
    if old_id in current_search.stdout or EXPLICIT_REVISION_OLD_TEXT in current_search.stdout:
        raise GateFailure("explicit_revision:search-current", "rendered_stale_fact")
    if withdrawn_old_id in withdrawn_search.stdout or EXPLICIT_WITHDRAW_OLD_TEXT in withdrawn_search.stdout:
        raise GateFailure("explicit_revision:search-withdrawn", "rendered_withdrawn_fact")
    evidence_reachability_count = sum(
        1
        for ref in current_node.get("evidence_refs", [])
        if isinstance(ref, dict) and f"{ref.get('path')}#{ref.get('quote_id')}" in current_search.stdout
    )
    combined_output = "\n".join((rejected.stdout, rejected.stderr))
    privacy_leak_count = sum(
        1
        for value in (
            EXPLICIT_REVISION_OLD_TEXT,
            EXPLICIT_REVISION_CURRENT_TEXT,
            EXPLICIT_WITHDRAW_OLD_TEXT,
            EXPLICIT_WITHDRAW_MARKER_TEXT,
            EXPLICIT_UNSAFE_REVISION_SENTINEL,
        )
        if value in combined_output
    )
    return {
        "status": "passed",
        "explicit_revision_input_records": int(replace_report.get("records_read", 0)) + int(withdraw_report.get("records_read", 0)),
        "explicit_revision_superseded_records": 1 if old_node.get("superseded_by") == current_id else 0,
        "explicit_revision_deprecated_records": 1 if withdrawn_old_node.get("deprecated_by") == withdrawal_node.get("memory_id") else 0,
        "current_fact_search_hit_count": 1 if current_id in current_search.stdout else 0,
        "stale_fact_default_search_hit_count": 1 if old_id in current_search.stdout or EXPLICIT_REVISION_OLD_TEXT in current_search.stdout else 0,
        "withdrawn_fact_default_search_hit_count": 1 if withdrawn_old_id in withdrawn_search.stdout or EXPLICIT_WITHDRAW_OLD_TEXT in withdrawn_search.stdout else 0,
        "revision_evidence_reachability_count": evidence_reachability_count,
        "privacy_leak_count": privacy_leak_count,
    }


def audit_archive(paths: GatePaths) -> None:
    audit_script = paths.memory_repo / "tools/audit_memory_archive.py"
    run_command(
        [
            sys.executable,
            str(audit_script),
            "--memory-repo",
            str(paths.memory_repo),
        ],
        "audit",
    )


def run_sync_dry_run(paths: GatePaths) -> None:
    sync_script = paths.memory_repo / "tools/sync_memory_archive.py"
    run_command(
        [
            sys.executable,
            str(sync_script),
            "--memory-repo",
            str(paths.memory_repo),
            "--dry-run",
        ],
        "sync:dry-run",
        cwd=paths.memory_repo,
    )


def file_contains_any(path: Path, markers: tuple[str, ...]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in text for marker in markers)


def count_files_with_markers(paths: list[Path], markers: tuple[str, ...]) -> int:
    return sum(1 for path in paths if path.is_file() and file_contains_any(path, markers))


def count_automation_source_records(source_dir: Path) -> int:
    return sum(1 for name in AUTOMATION_SOURCE_RECORDS if (source_dir / name).exists())


def count_archived_automation_sessions(memory_repo: Path) -> int:
    automation_names = set(AUTOMATION_SOURCE_RECORDS)
    count = 0
    for meta_path in (memory_repo / "sessions").glob("**/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_record = meta.get("source_record")
        if isinstance(source_record, str) and Path(source_record).name in automation_names:
            count += 1
    for row in iter_jsonl(memory_repo / "index/sessions.jsonl"):
        source_record = row.get("source_record")
        if isinstance(source_record, str) and Path(source_record).name in automation_names:
            count += 1
    return count


def iter_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def build_self_maintenance_report(paths: GatePaths) -> dict[str, object]:
    memory_files = sorted((paths.memory_repo / "memories").glob("*.jsonl"))
    daily_files = sorted((paths.memory_repo / "daily").glob("*/*.md"))
    index_files = [paths.memory_repo / "INDEX.md"]
    index_files.extend(sorted((paths.memory_repo / "index").glob("*.jsonl")))
    return {
        "status": "passed",
        "automation_source_records": count_automation_source_records(paths.source_dir),
        "automation_session_entries": count_archived_automation_sessions(paths.memory_repo),
        "automation_memory_nodes": count_files_with_markers(memory_files, AUTOMATION_NOISE_MARKERS),
        "automation_daily_noise_hits": count_files_with_markers(daily_files, AUTOMATION_NOISE_MARKERS),
        "automation_index_noise_hits": count_files_with_markers(index_files, AUTOMATION_NOISE_MARKERS),
    }


def validate_self_maintenance(report: dict[str, object]) -> None:
    expected = {
        "automation_source_records": 2,
        "automation_session_entries": 0,
        "automation_memory_nodes": 0,
        "automation_daily_noise_hits": 0,
        "automation_index_noise_hits": 0,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            raise GateFailure("self_maintenance", f"{key}_unexpected")


def validate_explicit_capture(report: dict[str, object]) -> None:
    expected = {
        "adapter_input_records": 1,
        "captured_memory_nodes": 1,
        "rejected_raw_transcript_records": 1,
        "search_hit_count": 1,
        "privacy_leak_count": 0,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            raise GateFailure("explicit_capture", f"{key}_unexpected")


def validate_explicit_revision(report: dict[str, object]) -> None:
    expected = {
        "explicit_revision_input_records": 2,
        "explicit_revision_superseded_records": 1,
        "explicit_revision_deprecated_records": 1,
        "current_fact_search_hit_count": 1,
        "stale_fact_default_search_hit_count": 0,
        "withdrawn_fact_default_search_hit_count": 0,
        "revision_evidence_reachability_count": 2,
        "privacy_leak_count": 0,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            raise GateFailure("explicit_revision", f"{key}_unexpected")


def build_report(
    paths: GatePaths,
    search_depths: list[str],
    self_maintenance: dict[str, object],
    explicit_capture: dict[str, object],
    explicit_revision: dict[str, object],
) -> dict[str, object]:
    sessions = archived_record_session_dirs(paths.memory_repo)
    daily_files = sorted((paths.memory_repo / "daily").glob("*/*.md"))
    memory_files = sorted((paths.memory_repo / "memories").glob("*.jsonl"))
    return {
        "status": "passed",
        "records_archived": len(sessions),
        "session_count": len(sessions),
        "daily_file_count": len(daily_files),
        "memory_count": nonempty_jsonl_count(paths.memory_repo / "index/memories.jsonl"),
        "memory_file_count": len(memory_files),
        "search_depths": search_depths,
        "audit": "passed",
        "search_health_check": "passed",
        "sync_dry_run": "passed",
        "self_maintenance": self_maintenance,
        "explicit_capture": explicit_capture,
        "explicit_revision": explicit_revision,
        "output_contract": "aggregate_only",
    }


def run_gate(root: Path) -> dict[str, object]:
    paths = GatePaths(
        root=root,
        memory_repo=root / "agent-memory",
        source_dir=root / "source-records",
        project_path=root / "synthetic-project",
    )
    setup_archive(paths)
    initialize_git_repo(paths.memory_repo, "Initial synthetic archive")
    write_synthetic_source_records(paths.source_dir, paths.project_path)
    update_archive(paths)
    explicit_capture = run_explicit_capture_adapter(paths)
    explicit_revision = run_explicit_revision_adapter(paths)
    artifact_errors = validate_archive_artifacts(paths.memory_repo)
    if artifact_errors:
        raise GateFailure("artifacts", artifact_errors[0])
    search_depths = run_searches(paths)
    run_search_health_check(paths)
    audit_archive(paths)
    self_maintenance = build_self_maintenance_report(paths)
    validate_self_maintenance(self_maintenance)
    validate_explicit_capture(explicit_capture)
    validate_explicit_revision(explicit_revision)
    initialize_git_repo(paths.memory_repo, "Synthetic archive after update")
    run_sync_dry_run(paths)
    return build_report(paths, search_depths, self_maintenance, explicit_capture, explicit_revision)


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-lifecycle-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-lifecycle-", dir=parent))
    return root, None, root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent directory for generated clean-room artifacts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    temp: tempfile.TemporaryDirectory[str] | None = None
    cleanup_root: Path | None = None
    try:
        root, temp, cleanup_root = make_work_root(args.work_dir)
        report = run_gate(root)
    except GateFailure as failure:
        print(
            json.dumps(
                {"status": "failed", "failures": [failure.to_report()]},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if temp is not None:
            temp.cleanup()
        elif cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)

    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
