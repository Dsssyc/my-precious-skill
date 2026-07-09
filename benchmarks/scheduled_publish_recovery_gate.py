#!/usr/bin/env python3
"""Gate deterministic scheduled publish recovery before archive sync."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "scheduled_publish_recovery_gate"


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
class RecoveryCase:
    name: str
    kind: str
    expect_repair_success: bool
    expect_pre_sync_block: bool


PRIVATE_MARKERS = (
    "PRIVATE_SCHEDULED_REPAIR_SENTINEL",
    "PRIVATE_SCHEDULED_TAG_SENTINEL",
    "PRIVATE_SCHEDULED_AMBIGUOUS_SENTINEL",
    "/private/synthetic/scheduled-source.jsonl",
)


def run_command(
    command: list[str],
    stage: str,
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
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


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_agent_native_prompt(memory_repo: Path, root: Path, name: str) -> str:
    source_dir = root / name / "source-records"
    source_dir.mkdir(parents=True, exist_ok=True)
    output = root / name / "agent-native.txt"
    run_command(
        [
            sys.executable,
            str(memory_repo / "tools/render_scheduler.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
            "--backend",
            "agent-native",
            "--allow-redacted-secrets",
            "--push-after-update",
            "--output",
            str(output),
        ],
        f"{name}:render_prompt",
        cwd=memory_repo,
    )
    return output.read_text(encoding="utf-8")


def prompt_contract_result(prompt: str, memory_repo: Path) -> dict[str, bool]:
    health_index = prompt.find("python tools/search_memory.py --health-check")
    sync_index = prompt.find("python tools/sync_memory_archive.py --push")
    return {
        "single_working_directory": "Use exactly one working directory:" in prompt and str(memory_repo) in prompt,
        "health_check_before_sync": health_index != -1 and sync_index != -1 and health_index < sync_index,
        "sync_helper_used": "python tools/sync_memory_archive.py --push" in prompt,
        "no_hand_staging": "Do not hand-stage files" in prompt and "git add" not in prompt,
        "repair_contract": (
            "python tools/repair_publish_surfaces.py --apply" in prompt
            and "publish readiness blocks" in prompt
            and "stop if the helper reports `blocked`" in prompt
        ),
    }


def write_session(memory_repo: Path, case: RecoveryCase) -> None:
    session_dir = memory_repo / "sessions/2026/07/08/synthetic"
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = "sessions/2026/07/08/synthetic/summary.md"
    evidence_path = "sessions/2026/07/08/synthetic/evidence.md"
    source_map_path = "sessions/2026/07/08/synthetic/source-map.json"
    (memory_repo / summary_path).write_text(
        "# Synthetic Summary\n\nDurable scheduled recovery decision remains current.\n",
        encoding="utf-8",
    )
    (memory_repo / evidence_path).write_text(
        "# Synthetic Evidence\n\n- ev_001: Durable scheduled recovery decision remains current.\n",
        encoding="utf-8",
    )
    write_json(
        memory_repo / source_map_path,
        {
            "summary_path": summary_path,
            "evidence_path": evidence_path,
            "source_map_path": source_map_path,
        },
    )
    meta: dict[str, object] = {
        "session_id": f"synthetic-{case.name}",
        "source_agent": "synthetic",
        "project": "synthetic-project",
        "project_path": "/tmp/synthetic-project",
        "archive_scope": "/tmp/synthetic-project",
        "source_partition": "/tmp/synthetic-project",
        "source_updated_at": "2026-07-08T00:00:00Z",
        "archive_status": "summarized",
        "redaction_status": "redacted",
        "summary_path": summary_path,
        "evidence_path": evidence_path,
        "source_map_path": source_map_path,
        "user_intent": "Preserve deterministic scheduled publish recovery behavior.",
        "decisions": [],
        "unresolved_tasks": [],
        "explicit_memories": [],
    }
    if case.kind == "repairable":
        meta.update(
            {
                "summary": (
                    "Durable scheduled recovery decision remains current. "
                    "Command Status: dry-run would push after commit PRIVATE_SCHEDULED_REPAIR_SENTINEL."
                ),
                "tags": [
                    "scheduled-recovery",
                    "unit tests PRIVATE_SCHEDULED_TAG_SENTINEL",
                    "raw source path: /private/synthetic/scheduled-source.jsonl",
                ],
            }
        )
    elif case.kind == "ambiguous":
        meta.update(
            {
                "user_intent": "",
                "summary": (
                    "Durable scheduled recovery decision remains current while command status dry-run would push "
                    "PRIVATE_SCHEDULED_AMBIGUOUS_SENTINEL"
                ),
                "tags": ["scheduled-recovery"],
            }
        )
    else:
        raise AssertionError(f"unexpected case kind: {case.kind}")
    write_json(session_dir / "meta.json", meta)


def write_malformed_meta(memory_repo: Path) -> None:
    meta = memory_repo / "sessions/2026/07/08/malformed/meta.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text('{"summary": "Command Status: dry-run would push"', encoding="utf-8")


def rebuild_indexes(memory_repo: Path, stage: str) -> None:
    empty_source = memory_repo / ".empty-source"
    empty_source.mkdir(exist_ok=True)
    run_command(
        [
            sys.executable,
            str(memory_repo / "tools/update_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(empty_source),
            "--project-path",
            str(memory_repo),
            "--max-records",
            "0",
        ],
        stage,
        cwd=memory_repo,
    )


def run_sync_dry_push(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [
            sys.executable,
            str(memory_repo / "tools/sync_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--dry-run",
            "--push",
        ],
        "sync_dry_push",
        cwd=memory_repo,
        check=False,
    )


def run_repair(memory_repo: Path, *, apply: bool) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = run_command(
        [
            sys.executable,
            str(memory_repo / "tools/repair_publish_surfaces.py"),
            "--memory-repo",
            str(memory_repo),
            *(["--apply"] if apply else []),
        ],
        "repair_publish_surfaces",
        cwd=memory_repo,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("repair_publish_surfaces", "invalid_json", result.returncode) from exc
    return result, report


def run_readiness(
    memory_repo: Path,
    *,
    expect_pass: bool,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = run_command(
        [sys.executable, str(memory_repo / "tools/audit_publish_readiness.py"), "--memory-repo", str(memory_repo)],
        "audit_publish_readiness",
        cwd=memory_repo,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GateFailure("audit_publish_readiness", "invalid_json", result.returncode) from exc
    if expect_pass and result.returncode != 0:
        raise GateFailure("audit_publish_readiness", "expected_pass", result.returncode)
    if not expect_pass and result.returncode == 0:
        raise GateFailure("audit_publish_readiness", "expected_failure", result.returncode)
    return result, report


def contains_private_marker(text: str) -> bool:
    return any(marker in text for marker in PRIVATE_MARKERS)


def sync_blocked_before_stage(result: subprocess.CompletedProcess[str]) -> bool:
    combined = result.stdout + result.stderr
    return (
        result.returncode != 0
        and "publish_readiness_audit" in combined
        and "Would stage allowed archive roots" not in result.stdout
    )


def sync_publish_intent(result: subprocess.CompletedProcess[str]) -> bool:
    return (
        result.returncode == 0
        and "Would stage allowed archive roots" in result.stdout
        and "Would push after commit." in result.stdout
    )


def run_case(root: Path, case: RecoveryCase) -> dict[str, object]:
    memory_repo = setup_archive(root, case.name)
    prompt = render_agent_native_prompt(memory_repo, root, case.name)
    prompt_contract = prompt_contract_result(prompt, memory_repo)
    pre_sync_block = False
    repair_success = False
    post_publish_intent = False
    ambiguous_fail_closed = False
    malformed_fail_closed = False
    hand_stage_bypass = 0
    privacy_leak_count = 1 if contains_private_marker(prompt) else 0

    if case.kind == "malformed":
        write_malformed_meta(memory_repo)
        repair_result, repair_report = run_repair(memory_repo, apply=True)
        privacy_leak_count += 1 if contains_private_marker(repair_result.stdout + repair_result.stderr) else 0
        malformed_fail_closed = repair_result.returncode != 0 and repair_report.get("status") == "blocked"
        post_sync = run_sync_dry_push(memory_repo)
        privacy_leak_count += 1 if contains_private_marker(post_sync.stdout + post_sync.stderr) else 0
        post_publish_intent = sync_publish_intent(post_sync)
        return {
            "case": case.name,
            "prompt_contract_passed": all(prompt_contract.values()),
            "pre_repair_sync_blocked": False,
            "repair_apply_success": False,
            "post_repair_publish_intent": post_publish_intent,
            "ambiguous_fail_closed": False,
            "malformed_fail_closed": malformed_fail_closed,
            "hand_stage_bypass_count": hand_stage_bypass,
            "privacy_leak_count": privacy_leak_count,
        }

    write_session(memory_repo, case)
    rebuild_indexes(memory_repo, f"{case.name}:rebuild-before")
    pre_sync = run_sync_dry_push(memory_repo)
    privacy_leak_count += 1 if contains_private_marker(pre_sync.stdout + pre_sync.stderr) else 0
    pre_sync_block = sync_blocked_before_stage(pre_sync)
    hand_stage_bypass += 1 if case.expect_pre_sync_block and sync_publish_intent(pre_sync) else 0
    if not pre_sync_block:
        raise GateFailure(case.name, "sync_did_not_block_before_stage", pre_sync.returncode)

    repair_result, repair_report = run_repair(memory_repo, apply=True)
    privacy_leak_count += 1 if contains_private_marker(repair_result.stdout + repair_result.stderr) else 0
    repair_success = repair_result.returncode == 0 and repair_report.get("status") == "repaired"
    ambiguous_fail_closed = (
        case.kind == "ambiguous"
        and repair_result.returncode != 0
        and repair_report.get("status") == "blocked"
    )

    if case.expect_repair_success:
        if not repair_success:
            raise GateFailure(case.name, "repair_did_not_apply", repair_result.returncode)
        readiness_result, _ = run_readiness(memory_repo, expect_pass=True)
    else:
        if not ambiguous_fail_closed:
            raise GateFailure(case.name, "repair_did_not_fail_closed", repair_result.returncode)
        readiness_result, _ = run_readiness(memory_repo, expect_pass=False)
    privacy_leak_count += 1 if contains_private_marker(readiness_result.stdout + readiness_result.stderr) else 0

    post_sync = run_sync_dry_push(memory_repo)
    privacy_leak_count += 1 if contains_private_marker(post_sync.stdout + post_sync.stderr) else 0
    post_publish_intent = sync_publish_intent(post_sync)
    if case.expect_repair_success and not post_publish_intent:
        raise GateFailure(case.name, "post_repair_missing_publish_intent", post_sync.returncode)
    if not case.expect_repair_success and post_publish_intent:
        raise GateFailure(case.name, "blocked_case_reached_publish_intent", post_sync.returncode)

    return {
        "case": case.name,
        "prompt_contract_passed": all(prompt_contract.values()),
        "pre_repair_sync_blocked": pre_sync_block,
        "repair_apply_success": repair_success,
        "post_repair_publish_intent": post_publish_intent,
        "ambiguous_fail_closed": ambiguous_fail_closed,
        "malformed_fail_closed": False,
        "hand_stage_bypass_count": hand_stage_bypass,
        "privacy_leak_count": privacy_leak_count,
    }


def build_report(case_results: list[dict[str, object]]) -> dict[str, object]:
    prompt_pass_count = sum(1 for case in case_results if case["prompt_contract_passed"])
    metrics = {
        "scheduler_prompt_contract_pass_rate": prompt_pass_count / len(case_results) if case_results else 0.0,
        "pre_repair_sync_block_count": sum(1 for case in case_results if case["pre_repair_sync_blocked"]),
        "repair_apply_success_count": sum(1 for case in case_results if case["repair_apply_success"]),
        "post_repair_publish_intent_count": sum(1 for case in case_results if case["post_repair_publish_intent"]),
        "ambiguous_fail_closed_count": sum(1 for case in case_results if case["ambiguous_fail_closed"]),
        "malformed_fail_closed_count": sum(1 for case in case_results if case["malformed_fail_closed"]),
        "hand_stage_bypass_count": sum(int(case["hand_stage_bypass_count"]) for case in case_results),
        "privacy_leak_count": sum(int(case["privacy_leak_count"]) for case in case_results),
    }
    passed = (
        metrics["scheduler_prompt_contract_pass_rate"] == 1.0
        and metrics["pre_repair_sync_block_count"] == 2
        and metrics["repair_apply_success_count"] == 1
        and metrics["post_repair_publish_intent_count"] == 1
        and metrics["ambiguous_fail_closed_count"] == 1
        and metrics["malformed_fail_closed_count"] == 1
        and metrics["hand_stage_bypass_count"] == 0
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "claim_boundary": (
            "deterministic scheduled automation recovery drill only; not live scheduler reliability, "
            "LLM prompt-following quality, GitHub availability, memory quality, ranking, vector search, "
            "ontology discovery, private archive quality, or public leaderboard parity"
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
        RecoveryCase("repairable_metadata_noise", "repairable", True, True),
        RecoveryCase("ambiguous_scalar_noise", "ambiguous", False, True),
        RecoveryCase("malformed_metadata", "malformed", False, False),
    ]
    return build_report([run_case(root, case) for case in cases])


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-scheduled-recovery-") as tmpdir:
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
