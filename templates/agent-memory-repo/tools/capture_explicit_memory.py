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
SAFE_SCOPE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,160}$")
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
        records.append(
            {
                "text": text,
                "layer": layer,
                "scope": safe_scope(row.get("scope"), layer),
                "source": safe_source(row.get("source")),
            }
        )
    if not records:
        raise CaptureFailure("input did not contain explicit memory records")
    return records


def write_support_files(memory_repo: Path, record: dict[str, str], now: datetime) -> tuple[str, str, str]:
    digest = hashlib.sha256(
        f"{record['layer']}|{record['scope']}|{record['text']}".encode("utf-8")
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
