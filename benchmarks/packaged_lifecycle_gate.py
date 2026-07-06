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
SOURCE_TEXT = (
    "Remember this: clean-room lifecycle fact validates packaged setup, update, "
    "search, and audit using public synthetic records."
)


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


def write_synthetic_source_record(source_dir: Path, project_path: Path) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    project_path.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "type": "session_meta",
            "timestamp": "2026-07-06T12:00:00Z",
            "payload": {
                "id": "packaged-lifecycle-clean-room",
                "cwd": str(project_path),
                "project_path": str(project_path),
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
    record = source_dir / "packaged-lifecycle.jsonl"
    record.write_text("\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n", encoding="utf-8")


def nonempty_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def session_dirs(memory_repo: Path) -> list[Path]:
    sessions_root = memory_repo / "sessions"
    if not sessions_root.exists():
        return []
    return sorted(path for path in sessions_root.glob("*/*/*/*") if path.is_dir())


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

    sessions = session_dirs(memory_repo)
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


def build_report(paths: GatePaths, search_depths: list[str]) -> dict[str, object]:
    sessions = session_dirs(paths.memory_repo)
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
    write_synthetic_source_record(paths.source_dir, paths.project_path)
    update_archive(paths)
    artifact_errors = validate_archive_artifacts(paths.memory_repo)
    if artifact_errors:
        raise GateFailure("artifacts", artifact_errors[0])
    search_depths = run_searches(paths)
    audit_archive(paths)
    return build_report(paths, search_depths)


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
