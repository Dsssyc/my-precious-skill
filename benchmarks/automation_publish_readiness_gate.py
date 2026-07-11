#!/usr/bin/env python3
"""Gate deterministic automation publish readiness before archive sync."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "automation_publish_readiness_gate"


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
class CaseSpec:
    name: str
    writer: Callable[[Path], list[str]]
    expected_status: str
    expected_category: str | None = None
    run_sync: bool = False


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


def setup_archive(parent: Path, name: str) -> Path:
    memory_repo = parent / name / "agent-memory"
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        f"{name}:setup",
    )
    run_command(["git", "init", "-q"], f"{name}:git:init", cwd=memory_repo)
    run_command(["git", "config", "user.email", "synthetic@example.invalid"], f"{name}:git:email", cwd=memory_repo)
    run_command(["git", "config", "user.name", "Synthetic Gate"], f"{name}:git:name", cwd=memory_repo)
    run_command(["git", "add", "."], f"{name}:git:add", cwd=memory_repo)
    run_command(["git", "commit", "-m", "Initial synthetic archive"], f"{name}:git:commit", cwd=memory_repo)
    return memory_repo


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def write_clean_daily(repo: Path) -> list[str]:
    daily = repo / "daily/2026/2026-07-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# Daily Memory Index\n\n"
        "## Durable Sessions\n\n"
        "- Synthetic project: Durable automation publish readiness was recorded.\n\n"
        "## Durable Decisions\n\n"
        "- Keep automatic publish decisions behind aggregate-only readiness gates.\n",
        encoding="utf-8",
    )
    return []


def write_clean_indexed_summary(repo: Path) -> list[str]:
    write_jsonl(
        repo / "index/sessions.jsonl",
        [
            {
                "summary": "Durable automation publish readiness was recorded.",
                "user_intent": "Capture synthetic publish readiness behavior.",
                "summary_path": "sessions/2026/07/08/synthetic/summary.md",
                "project_path": "/tmp/structured-project-path-not-a-summary-field",
            }
        ],
    )
    return []


def write_noisy_daily_command_progress(repo: Path) -> list[str]:
    sentinel = "PRIVATE_DAILY_COMMAND_PROGRESS_SHOULD_NOT_RENDER"
    daily = repo / "daily/2026/2026-07-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# Daily Memory Index\n\n"
        f"Command Status: dry-run would push after commit. {sentinel}\n",
        encoding="utf-8",
    )
    return [sentinel]


def write_noisy_index_prompt_environment(repo: Path) -> list[str]:
    sentinel = "PRIVATE_PROMPT_ENV_SHOULD_NOT_RENDER"
    write_jsonl(
        repo / "index/sessions.jsonl",
        [
            {
                "summary": f"<environment_context>{sentinel}</environment_context>",
                "summary_path": "sessions/2026/07/08/synthetic/summary.md",
            }
        ],
    )
    return [sentinel]


def write_noisy_index_source_path_and_query(repo: Path) -> list[str]:
    sentinel = "/Users/example/private/synthetic-source-record.jsonl"
    write_jsonl(
        repo / "index/sessions.jsonl",
        [
            {
                "summary": f"raw source path: {sentinel}",
                "full_query": "synthetic private query should not be indexed",
                "project_path": "/Users/example/structured-project-path-not-scanned",
            }
        ],
    )
    return [sentinel, "/Users/example/structured-project-path-not-scanned"]


def write_noisy_daily_secret_like(repo: Path) -> list[str]:
    fake_key = "sk-" + ("notreal" * 4)
    daily = repo / "daily/2026/2026-07-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(f"# Daily Memory Index\n\nDo not publish {fake_key}.\n", encoding="utf-8")
    return [fake_key]


def run_audit(memory_repo: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [sys.executable, str(memory_repo / "tools/audit_publish_readiness.py"), "--memory-repo", str(memory_repo)],
        cwd=memory_repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("audit_publish_readiness", "invalid_json", result.returncode) from exc
    if not isinstance(payload, dict):
        raise GateFailure("audit_publish_readiness", "non_object_json", result.returncode)
    return result, payload


def run_sync_dry_push(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(memory_repo / "tools/sync_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--dry-run",
            "--push",
        ],
        cwd=memory_repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def case_has_category(report: dict[str, object], category: str) -> bool:
    counts = report.get("category_counts")
    return isinstance(counts, dict) and int(counts.get(category, 0)) > 0


def run_case(root: Path, case: CaseSpec) -> dict[str, object]:
    memory_repo = setup_archive(root, case.name)
    sentinels = case.writer(memory_repo)
    audit_result, audit_report = run_audit(memory_repo)
    combined = audit_result.stdout + audit_result.stderr
    leak_count = sum(1 for sentinel in sentinels if sentinel and sentinel in combined)
    status = audit_report.get("status")
    if status != case.expected_status:
        raise GateFailure(case.name, f"unexpected_status_{status}", audit_result.returncode)
    if case.expected_category and not case_has_category(audit_report, case.expected_category):
        raise GateFailure(case.name, f"missing_category_{case.expected_category}", audit_result.returncode)
    if leak_count:
        raise GateFailure(case.name, "rendered_private_text", audit_result.returncode)

    sync_result: subprocess.CompletedProcess[str] | None = None
    sync_publish_intent = False
    sync_blocked_before_stage = False
    sync_leak_count = 0
    if case.run_sync:
        sync_result = run_sync_dry_push(memory_repo)
        sync_combined = sync_result.stdout + sync_result.stderr
        sync_leak_count = sum(1 for sentinel in sentinels if sentinel and sentinel in sync_combined)
        sync_publish_intent = (
            sync_result.returncode == 0
            and "Would stage allowed archive roots" in sync_result.stdout
            and "Would push after commit." in sync_result.stdout
        )
        sync_blocked_before_stage = (
            sync_result.returncode != 0
            and "publish_readiness_audit" in sync_combined
            and "Would stage allowed archive roots" not in sync_result.stdout
        )
        if sync_leak_count:
            raise GateFailure(case.name, "sync_rendered_private_text", sync_result.returncode)
        if case.expected_status == "passed" and not sync_publish_intent:
            raise GateFailure(case.name, "sync_missing_publish_intent", sync_result.returncode)
        if case.expected_status == "failed" and not sync_blocked_before_stage:
            raise GateFailure(case.name, "sync_missing_pre_publish_block", sync_result.returncode)

    return {
        "case": case.name,
        "expected_status": case.expected_status,
        "actual_status": status,
        "expected_category": case.expected_category,
        "audit_returncode": audit_result.returncode,
        "sync_returncode": sync_result.returncode if sync_result else None,
        "sync_publish_intent": sync_publish_intent,
        "sync_blocked_before_stage": sync_blocked_before_stage,
        "privacy_leak_count": leak_count + sync_leak_count,
        "aggregate_only": bool(audit_report.get("privacy", {}).get("aggregate_only")),
    }


def build_report(case_results: list[dict[str, object]]) -> dict[str, object]:
    clean_cases = [case for case in case_results if case["expected_status"] == "passed"]
    noisy_cases = [case for case in case_results if case["expected_status"] == "failed"]
    clean_passes = sum(1 for case in clean_cases if case["actual_status"] == "passed")
    noisy_rejections = sum(1 for case in noisy_cases if case["actual_status"] == "failed")
    privacy_leak_count = sum(int(case["privacy_leak_count"]) for case in case_results)
    metrics = {
        "publish_readiness_clean_pass_rate": clean_passes / len(clean_cases) if clean_cases else 0.0,
        "publish_readiness_noise_rejection_rate": noisy_rejections / len(noisy_cases) if noisy_cases else 0.0,
        "sync_clean_publish_intent_count": sum(1 for case in case_results if case["sync_publish_intent"]),
        "sync_noisy_block_count": sum(1 for case in case_results if case["sync_blocked_before_stage"]),
        "automation_noise_rejection_count": sum(
            1
            for case in noisy_cases
            if case["expected_category"] in {"command_progress", "prompt_or_environment", "automation_run_narration"}
        ),
        "raw_source_reference_rejection_count": sum(
            1 for case in noisy_cases if case["expected_category"] == "raw_source_reference"
        ),
        "secret_like_rejection_count": sum(1 for case in noisy_cases if case["expected_category"] == "secret_like_value"),
        "aggregate_only_report_count": sum(1 for case in case_results if case["aggregate_only"]),
        "privacy_leak_count": privacy_leak_count,
    }
    required_passed = (
        metrics["publish_readiness_clean_pass_rate"] == 1.0
        and metrics["publish_readiness_noise_rejection_rate"] == 1.0
        and metrics["sync_clean_publish_intent_count"] == 1
        and metrics["sync_noisy_block_count"] == 1
        and metrics["raw_source_reference_rejection_count"] == 1
        and metrics["secret_like_rejection_count"] == 1
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if required_passed else "failed",
        "claim_boundary": (
            "deterministic packaged automation publish readiness only; "
            "not memory quality, LLM answer quality, GitHub availability, ranking, vector search, or ontology discovery"
        ),
        "metrics": metrics,
        "cases": case_results,
        "privacy": {
            "aggregate_only": True,
            "snippets_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
    }


def run_gate(root: Path) -> dict[str, object]:
    cases = [
        CaseSpec("clean_daily", write_clean_daily, "passed", run_sync=True),
        CaseSpec("clean_indexed_summary", write_clean_indexed_summary, "passed"),
        CaseSpec(
            "noisy_daily_command_progress",
            write_noisy_daily_command_progress,
            "failed",
            "command_progress",
            run_sync=True,
        ),
        CaseSpec(
            "noisy_index_prompt_environment",
            write_noisy_index_prompt_environment,
            "failed",
            "prompt_or_environment",
        ),
        CaseSpec(
            "noisy_index_source_path_and_query",
            write_noisy_index_source_path_and_query,
            "failed",
            "raw_source_reference",
        ),
        CaseSpec("noisy_daily_secret_like", write_noisy_daily_secret_like, "failed", "secret_like_value"),
    ]
    return build_report([run_case(root, case) for case in cases])


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-publish-readiness-") as tmpdir:
            report = run_gate(Path(tmpdir))
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": exc.to_report(),
            "privacy": {
                "aggregate_only": True,
                "snippets_rendered": False,
                "memory_text_rendered": False,
                "source_paths_rendered": False,
                "raw_refs_rendered": False,
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
