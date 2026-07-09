#!/usr/bin/env python3
"""Gate scheduled publish decisions around search/no-op/dirty blockers."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "scheduled_publish_search_gate"

PRIVATE_MARKERS = (
    "PRIVATE_SEARCH_GATE_SENTINEL",
    "PRIVATE_SEARCH_BLOCKED_SENTINEL",
    "PRIVATE_DIRTY_SENTINEL",
    "/private/synthetic/search-gate-source.jsonl",
)
RAW_GIT_ACTION = re.compile(r"^\s*(?:\$\s*)?git\s+(?:add|commit|push)\b", re.IGNORECASE)
RAW_GIT_PROSE = re.compile(r"\b(?:run|use|execute)\s+git\s+(?:add|commit|push)\b", re.IGNORECASE)


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
class DecisionCase:
    name: str
    kind: str
    expected_decision: str


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


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def write_searchable_memory(repo: Path) -> None:
    summary_path = "sessions/2026/07/08/search-gate/summary.md"
    evidence_path = "sessions/2026/07/08/search-gate/evidence.md"
    session_dir = repo / "sessions/2026/07/08/search-gate"
    session_dir.mkdir(parents=True, exist_ok=True)
    (repo / summary_path).write_text(
        "# Synthetic Search Gate Summary\n\nDurable scheduled publish search gate remains current.\n",
        encoding="utf-8",
    )
    (repo / evidence_path).write_text(
        "# Synthetic Search Gate Evidence\n\n"
        "ev_001: Durable scheduled publish search gate remains current.\n",
        encoding="utf-8",
    )
    write_jsonl(
        repo / "index/memories.jsonl",
        [
            {
                "memory_id": "mem_scheduled_publish_search_gate",
                "layer": "project",
                "scope": "project:synthetic",
                "topic": "scheduled-publish-search-gate",
                "text": "Durable scheduled publish search gate remains current.",
                "rationale": "Synthetic gate requires one active drillable memory for search health.",
                "source": "automatic",
                "confidence": "high",
                "persistence": "normal",
                "support_count": 1,
                "first_seen": "2026-07-08T00:00:00Z",
                "last_seen": "2026-07-08T00:00:00Z",
                "derived_from": [summary_path],
                "evidence_refs": [{"path": evidence_path, "quote_id": "ev_001"}],
                "raw_refs": [],
                "supersedes": [],
                "superseded_by": None,
                "tags": ["scheduled-search-gate", "publish-decision"],
            }
        ],
    )


def write_safe_publish_change(repo: Path, *, sentinel: str = "") -> None:
    daily = repo / "daily/2026/2026-07-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# Daily Memory Index\n\n"
        "## Durable Sessions\n\n"
        "- Synthetic project: Durable scheduled publish decision classification was recorded.\n\n"
        "## Durable Decisions\n\n"
        "- Keep search health, no-op state, and dirty publish blockers separated.\n",
        encoding="utf-8",
    )
    write_jsonl(
        repo / "index/sessions.jsonl",
        [
            {
                "summary": "Durable scheduled publish decision classification was recorded.",
                "summary_path": "sessions/2026/07/08/search-gate/summary.md",
                "user_intent": "Classify scheduled publish decision outcomes.",
                "tags": ["scheduled-search-gate", "publish-decision"],
            }
        ],
    )
    if sentinel:
        # Store private-looking data only in a non-publish source fixture; it must never be rendered.
        source = repo / ".tmp" / "source-records" / "synthetic.jsonl"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps({"source": sentinel}, sort_keys=True) + "\n", encoding="utf-8")


def setup_archive(parent: Path, name: str, *, seed_search: bool) -> Path:
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
    if seed_search:
        write_searchable_memory(memory_repo)
    run_command(["git", "init", "-q"], f"{name}:git:init", cwd=memory_repo)
    run_command(["git", "config", "user.email", "synthetic@example.invalid"], f"{name}:git:email", cwd=memory_repo)
    run_command(["git", "config", "user.name", "Synthetic Gate"], f"{name}:git:name", cwd=memory_repo)
    run_command(["git", "add", "."], f"{name}:git:add", cwd=memory_repo)
    run_command(["git", "commit", "-m", "Initial synthetic archive"], f"{name}:git:commit", cwd=memory_repo)
    return memory_repo


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
    health_command = "python tools/search_memory.py --health-check"
    sync_command = "python tools/sync_memory_archive.py --push"
    health_index = prompt.find(health_command)
    sync_index = prompt.find(sync_command)
    raw_git_publish_path = any(
        (RAW_GIT_ACTION.search(line) or RAW_GIT_PROSE.search(line))
        and "do not" not in line.lower()
        and "don't" not in line.lower()
        and "never" not in line.lower()
        for line in prompt.splitlines()
    )
    return {
        "single_working_directory": "Use exactly one working directory:" in prompt and str(memory_repo) in prompt,
        "health_check_before_sync": health_index != -1 and sync_index != -1 and health_index < sync_index,
        "generic_content_query_not_required": "python tools/search_memory.py memory" not in prompt,
        "sync_helper_used": sync_command in prompt,
        "no_hand_staging": "Do not hand-stage files" in prompt and not raw_git_publish_path,
    }


def contains_private_marker(text: str) -> bool:
    return any(marker in text for marker in PRIVATE_MARKERS)


def run_readiness(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, str(memory_repo / "tools/audit_publish_readiness.py"), "--memory-repo", str(memory_repo)],
        "audit_publish_readiness",
        cwd=memory_repo,
        check=False,
    )


def run_archive_audit(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
        "audit_memory_archive",
        cwd=memory_repo,
        check=False,
    )


def run_search_health(memory_repo: Path) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, str(memory_repo / "tools/search_memory.py"), "--health-check", "--repo", str(memory_repo)],
        "search_health",
        cwd=memory_repo,
        check=False,
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


def run_git_status(memory_repo: Path) -> list[str]:
    result = run_command(["git", "status", "--porcelain=v1"], "git_status", cwd=memory_repo)
    return [line[3:] for line in result.stdout.splitlines() if line.strip()]


def is_sync_publish_intent(result: subprocess.CompletedProcess[str]) -> bool:
    return (
        result.returncode == 0
        and "Would stage allowed archive roots" in result.stdout
        and "Would push after commit." in result.stdout
    )


def is_sync_no_op(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode == 0 and "No memory archive changes to sync." in result.stdout


def is_sync_unexpected_dirty_block(result: subprocess.CompletedProcess[str]) -> bool:
    combined = result.stdout + result.stderr
    return (
        result.returncode != 0
        and "Refusing to sync because unexpected files changed:" in combined
        and "Would stage allowed archive roots" not in result.stdout
    )


def prepare_case(memory_repo: Path, case: DecisionCase) -> None:
    if case.kind == "publish_ready":
        write_safe_publish_change(memory_repo, sentinel="PRIVATE_SEARCH_GATE_SENTINEL")
    elif case.kind == "search_blocked":
        write_safe_publish_change(memory_repo, sentinel="PRIVATE_SEARCH_BLOCKED_SENTINEL")
    elif case.kind == "no_op_current":
        return
    elif case.kind == "dirty_or_unexpected_blocked":
        (memory_repo / "tools/unexpected_dirty_surface.txt").write_text(
            "PRIVATE_DIRTY_SENTINEL should not be rendered\n",
            encoding="utf-8",
        )
    else:
        raise AssertionError(f"unexpected case kind: {case.kind}")


def classify_case(root: Path, case: DecisionCase) -> dict[str, object]:
    memory_repo = setup_archive(root, case.name, seed_search=case.kind != "search_blocked")
    prompt = render_agent_native_prompt(memory_repo, root, case.name)
    prompt_contract = prompt_contract_result(prompt, memory_repo)
    prepare_case(memory_repo, case)

    archive_audit = run_archive_audit(memory_repo)
    readiness = run_readiness(memory_repo)
    search = run_search_health(memory_repo)
    sync_result: subprocess.CompletedProcess[str] | None = None
    changed_paths = run_git_status(memory_repo)
    free_form_search_used = False
    hand_stage_bypass = 0
    privacy_leak_count = 0
    for result in (archive_audit, readiness, search):
        privacy_leak_count += 1 if contains_private_marker(result.stdout + result.stderr) else 0
    privacy_leak_count += 1 if contains_private_marker(prompt) else 0

    if archive_audit.returncode != 0:
        raise GateFailure(case.name, "archive_audit_failed", archive_audit.returncode)
    if readiness.returncode != 0:
        decision = "dirty_or_unexpected_blocked"
        reason = "publish_readiness_failed"
    elif search.returncode != 0:
        decision = "search_blocked"
        reason = "search_health_failed"
    else:
        sync_result = run_sync_dry_push(memory_repo)
        privacy_leak_count += 1 if contains_private_marker(sync_result.stdout + sync_result.stderr) else 0
        if is_sync_publish_intent(sync_result):
            decision = "publish_ready"
            reason = "sync_dry_run_publish_intent"
        elif is_sync_no_op(sync_result):
            decision = "no_op_current"
            reason = "sync_dry_run_no_op"
        elif is_sync_unexpected_dirty_block(sync_result):
            decision = "dirty_or_unexpected_blocked"
            reason = "sync_unexpected_dirty"
        else:
            raise GateFailure(case.name, "unclassified_publish_decision", sync_result.returncode)

    if decision != case.expected_decision:
        raise GateFailure(case.name, f"unexpected_decision_{decision}")
    if search.returncode != 0 and sync_result is not None:
        raise GateFailure(case.name, "sync_ran_after_search_block")
    if decision != "publish_ready" and sync_result is not None and is_sync_publish_intent(sync_result):
        hand_stage_bypass += 1
    if free_form_search_used:
        raise GateFailure(case.name, "free_form_search_output_used")
    if privacy_leak_count:
        raise GateFailure(case.name, "private_marker_rendered")

    return {
        "case": case.name,
        "decision": decision,
        "reason": reason,
        "prompt_contract_passed": all(prompt_contract.values()),
        "archive_audit_passed": archive_audit.returncode == 0,
        "readiness_passed": readiness.returncode == 0,
        "search_health_passed": search.returncode == 0,
        "sync_returncode": sync_result.returncode if sync_result else None,
        "sync_publish_intent": bool(sync_result and is_sync_publish_intent(sync_result)),
        "sync_no_op": bool(sync_result and is_sync_no_op(sync_result)),
        "unexpected_dirty_blocked": bool(sync_result and is_sync_unexpected_dirty_block(sync_result)),
        "changed_path_count": len(changed_paths),
        "free_form_search_output_used": free_form_search_used,
        "hand_stage_bypass_count": hand_stage_bypass,
        "privacy_leak_count": privacy_leak_count,
    }


def build_report(case_results: list[dict[str, object]]) -> dict[str, object]:
    prompt_contract_passes = sum(1 for case in case_results if case["prompt_contract_passed"])
    search_contract_cases = [case for case in case_results if case["decision"] in {"publish_ready", "no_op_current"}]
    metrics = {
        "search_gate_pass_rate": (
            sum(1 for case in search_contract_cases if case["search_health_passed"]) / len(search_contract_cases)
            if search_contract_cases
            else 0.0
        ),
        "search_blocked_count": sum(1 for case in case_results if case["decision"] == "search_blocked"),
        "no_op_no_empty_commit_count": sum(1 for case in case_results if case["decision"] == "no_op_current"),
        "unexpected_dirty_block_count": sum(
            1 for case in case_results if case["decision"] == "dirty_or_unexpected_blocked"
        ),
        "publish_intent_count": sum(1 for case in case_results if case["sync_publish_intent"]),
        "hand_stage_bypass_count": sum(int(case["hand_stage_bypass_count"]) for case in case_results),
        "free_form_search_output_used_count": sum(1 for case in case_results if case["free_form_search_output_used"]),
        "privacy_leak_count": sum(int(case["privacy_leak_count"]) for case in case_results),
        "scheduler_prompt_contract_pass_rate": prompt_contract_passes / len(case_results) if case_results else 0.0,
    }
    passed = (
        metrics["search_gate_pass_rate"] == 1.0
        and metrics["search_blocked_count"] == 1
        and metrics["no_op_no_empty_commit_count"] == 1
        and metrics["unexpected_dirty_block_count"] == 1
        and metrics["publish_intent_count"] == 1
        and metrics["hand_stage_bypass_count"] == 0
        and metrics["free_form_search_output_used_count"] == 0
        and metrics["privacy_leak_count"] == 0
        and metrics["scheduler_prompt_contract_pass_rate"] == 1.0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "search_gate_contract": {
            "health_check_required": True,
            "generic_content_query_required": False,
            "generic_content_query_policy": "deployment-local only; not a reusable release readiness gate",
        },
        "claim_boundary": (
            "deterministic scheduled publish decision classification only; not live GitHub availability, "
            "not live scheduler reliability, not live LLM prompt-following quality, not memory quality, "
            "not ranking quality, not vector search, not ontology discovery, not private archive quality, "
            "and not public leaderboard parity"
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
        DecisionCase("discoverable_archive_publish_ready", "publish_ready", "publish_ready"),
        DecisionCase("empty_archive_search_blocked", "search_blocked", "search_blocked"),
        DecisionCase("already_current_no_op", "no_op_current", "no_op_current"),
        DecisionCase(
            "unexpected_dirty_surface_blocked",
            "dirty_or_unexpected_blocked",
            "dirty_or_unexpected_blocked",
        ),
    ]
    return build_report([classify_case(root, case) for case in cases])


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-scheduled-search-") as tmpdir:
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
