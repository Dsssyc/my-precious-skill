#!/usr/bin/env python3
"""Capture short explicit memories from agent-neutral JSONL input."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RAW_TRANSCRIPT_KEYS = {
    "events",
    "messages",
    "raw_source",
    "raw_source_content",
    "raw_transcript",
    "source_content",
    "transcript",
}
VALID_LAYERS = {"global", "domain", "project"}
VALID_OPERATIONS = {"capture", "replace", "withdraw"}
SAFE_SCOPE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,160}$")
SAFE_MEMORY_ID = re.compile(r"^[A-Za-z0-9_.:@+-]{1,160}$")
UNSAFE_MEMORY_ID_TOKENS = re.compile(r"(?i)(cookie|password|secret|should_not_render|token)")
MAX_TEXT_CHARS = 500


class CaptureFailure(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates: list[str] = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.append(os.getcwd())
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise CaptureFailure("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def compact_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def row_has_raw_transcript_fields(row: dict[str, Any]) -> bool:
    return any(key in row for key in RAW_TRANSCRIPT_KEYS)


def safe_layer(value: object) -> str:
    layer = compact_text(value) or "global"
    if layer not in VALID_LAYERS:
        raise CaptureFailure("explicit memory layer must be global, domain, or project")
    return layer


def safe_scope(value: object, layer: str) -> str:
    scope = compact_text(value) or ("global" if layer == "global" else layer)
    if not SAFE_SCOPE.fullmatch(scope):
        raise CaptureFailure("explicit memory scope contains unsupported characters")
    return scope


def safe_source(value: object) -> str:
    source = compact_text(value) or "explicit_request"
    if not SAFE_SCOPE.fullmatch(source):
        raise CaptureFailure("explicit memory source contains unsupported characters")
    return source


def safe_operation(value: object) -> str:
    operation = compact_text(value) or "capture"
    if operation not in VALID_OPERATIONS:
        raise CaptureFailure("explicit memory operation must be capture, replace, or withdraw")
    return operation


def safe_memory_id(value: object) -> str:
    memory_id = compact_text(value)
    if (
        not memory_id
        or not SAFE_MEMORY_ID.fullmatch(memory_id)
        or ".." in memory_id
        or UNSAFE_MEMORY_ID_TOKENS.search(memory_id)
    ):
        raise CaptureFailure("explicit memory revision target is unsafe")
    return memory_id


def parse_input(path: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaptureFailure(f"input row {line_number} is not valid JSON") from exc
        if not isinstance(row, dict):
            raise CaptureFailure(f"input row {line_number} must be a JSON object")
        if row_has_raw_transcript_fields(row):
            raise CaptureFailure("raw transcript fields are not accepted")
        text = compact_text(row.get("text"))
        if not text:
            raise CaptureFailure(f"input row {line_number} missing text")
        if len(text) > MAX_TEXT_CHARS:
            raise CaptureFailure("explicit memory text must be a short fact")
        layer = safe_layer(row.get("layer"))
        operation = safe_operation(row.get("operation"))
        record = {
            "operation": operation,
            "text": text,
            "layer": layer,
            "scope": safe_scope(row.get("scope"), layer),
            "source": safe_source(row.get("source")),
            "replaces_memory_id": "",
            "deprecates_memory_id": "",
        }
        if operation == "replace":
            if "deprecates_memory_id" in row:
                raise CaptureFailure("explicit memory replace cannot deprecate a target")
            record["replaces_memory_id"] = safe_memory_id(row.get("replaces_memory_id"))
        elif operation == "withdraw":
            if "replaces_memory_id" in row:
                raise CaptureFailure("explicit memory withdraw cannot replace a target")
            record["deprecates_memory_id"] = safe_memory_id(row.get("deprecates_memory_id"))
        elif "replaces_memory_id" in row or "deprecates_memory_id" in row:
            raise CaptureFailure("explicit memory capture cannot include revision targets")
        records.append(record)
    if not records:
        raise CaptureFailure("input did not contain explicit memory records")
    return records


def write_support_files(memory_repo: Path, record: dict[str, str], now: datetime) -> tuple[str, str, str]:
    digest = hashlib.sha256(
        (
            f"{record['operation']}|{record['layer']}|{record['scope']}|"
            f"{record['replaces_memory_id']}|{record['deprecates_memory_id']}|{record['text']}"
        ).encode("utf-8")
    ).hexdigest()[:12]
    day = now.strftime("%Y/%m/%d")
    entry_dir = memory_repo / "sessions" / day / f"explicit-capture-{digest}"
    entry_dir.mkdir(parents=True, exist_ok=True)
    summary_rel = entry_dir.relative_to(memory_repo).as_posix() + "/summary.md"
    evidence_rel = entry_dir.relative_to(memory_repo).as_posix() + "/evidence.md"
    quote_id = "ev_explicit_001"
    (memory_repo / summary_rel).write_text(
        "# Explicit Memory Capture\n\n"
        f"Captured a short explicit memory request for `{record['scope']}`.\n",
        encoding="utf-8",
    )
    (memory_repo / evidence_rel).write_text(
        "# Evidence\n\n"
        f"{quote_id}: {record['text']}\n",
        encoding="utf-8",
    )
    return summary_rel, evidence_rel, quote_id


def run_update(memory_repo: Path, record: dict[str, str], summary_rel: str, evidence_rel: str, quote_id: str) -> None:
    command = [
        sys.executable,
        str(memory_repo / "tools" / "update_memory_archive.py"),
        "--memory-repo",
        str(memory_repo),
        "--source-dir",
        str(memory_repo),
        "--project-path",
        str(memory_repo),
        "--explicit-memory",
        record["text"],
        "--explicit-layer",
        record["layer"],
        "--explicit-scope",
        record["scope"],
        "--explicit-summary-path",
        summary_rel,
        "--explicit-evidence-ref",
        f"{evidence_rel}#{quote_id}",
    ]
    if record["operation"] == "replace":
        command.extend(["--explicit-supersedes", record["replaces_memory_id"]])
    elif record["operation"] == "withdraw":
        command.extend(["--explicit-deprecates", record["deprecates_memory_id"]])
    result = subprocess.run(
        command,
        cwd=memory_repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise CaptureFailure("explicit memory updater failed")


def capture_records(memory_repo: Path, records: list[dict[str, str]]) -> int:
    now = datetime.now(UTC)
    captured = 0
    for record in records:
        summary_rel, evidence_rel, quote_id = write_support_files(memory_repo, record, now)
        run_update(memory_repo, record, summary_rel, evidence_rel, quote_id)
        captured += 1
    return captured


def count_records(records: list[dict[str, str]], operation: str) -> int:
    return sum(1 for record in records if record.get("operation") == operation)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--input", required=True, help="JSONL file of explicit memory records")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        memory_repo = resolve_memory_repo(args.memory_repo)
        records = parse_input(Path(args.input).expanduser())
        captured = capture_records(memory_repo, records)
    except CaptureFailure as exc:
        print(exc.reason, file=sys.stderr)
        return 1
    except OSError:
        print("explicit memory capture I/O failed", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "passed",
                "records_read": len(records),
                "captured": captured,
                "revised": count_records(records, "replace"),
                "withdrawn": count_records(records, "withdraw"),
                "refused": 0,
                "privacy": {
                    "aggregate_only": True,
                    "memory_text_rendered": False,
                    "raw_transcript_rendered": False,
                    "source_paths_rendered": False,
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
