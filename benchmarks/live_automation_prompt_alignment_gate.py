#!/usr/bin/env python3
"""Gate scheduled automation prompt alignment without rendering prompt text."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "live_automation_prompt_alignment_gate"

PRIVATE_MARKERS = (
    "PRIVATE_AUTOMATION_PROMPT_SENTINEL",
    "PRIVATE_ARCHIVE_CONTENT_SENTINEL",
)

RAW_GIT_ACTION = re.compile(r"^\s*(?:\$\s*)?git\s+(?:add|commit|push)\b", re.IGNORECASE)
RAW_GIT_PROSE = re.compile(r"\b(?:run|use|execute)\s+git\s+(?:add|commit|push)\b", re.IGNORECASE)
GENERIC_SEARCH_ACTION = re.compile(r"\btools/search_memory\.py\s+memory\b")


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
class PromptCase:
    name: str
    prompt: str
    expected_aligned: bool
    is_live: bool = False
    requires_preflight: bool = False
    requires_transaction_adapter: bool = False


def run_command(command: list[str], stage: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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


def setup_archive(parent: Path) -> Path:
    memory_repo = parent / "agent-memory"
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
        "setup",
    )
    return memory_repo


def render_agent_native_prompt(memory_repo: Path, root: Path) -> str:
    source_dir = root / "source-records"
    source_dir.mkdir(parents=True, exist_ok=True)
    output = root / "agent-native.txt"
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
        "render_agent_native_prompt",
        cwd=memory_repo,
    )
    return output.read_text(encoding="utf-8")


def prompt_from_automation_config(path: Path) -> str:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GateFailure("automation_config", "unreadable") from exc
    except tomllib.TOMLDecodeError as exc:
        raise GateFailure("automation_config", "invalid_toml") from exc
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise GateFailure("automation_config", "missing_prompt")
    return prompt


def command_positions(lines: list[str], *needles: str, excluded: tuple[str, ...] = ()) -> list[int]:
    positions: list[int] = []
    for index, line in enumerate(lines):
        if all(needle in line for needle in needles) and not any(token in line for token in excluded):
            positions.append(index)
    return positions


def python_action_positions(lines: list[str], script_name: str) -> list[int]:
    positions: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("$ "):
            stripped = stripped[2:].lstrip()
        if re.match(r"python(?:3)?\s+", stripped) and script_name in stripped:
            positions.extend([index] * stripped.count(script_name))
    return positions


def first_after(positions: list[int], previous: int) -> int | None:
    return next((position for position in positions if position > previous), None)


def actionable_raw_git_publish_path_count(prompt: str) -> int:
    count = 0
    for line in prompt.splitlines():
        lowered = line.lower()
        if "do not" in lowered or "don't" in lowered or "never" in lowered or "refusing" in lowered:
            continue
        if RAW_GIT_ACTION.search(line) or RAW_GIT_PROSE.search(line):
            count += 1
    return count


def actionable_generic_content_query_count(prompt: str) -> int:
    count = 0
    for line in prompt.splitlines():
        lowered = line.lower()
        if "do not" in lowered or "don't" in lowered or "never" in lowered or "not use" in lowered:
            continue
        if GENERIC_SEARCH_ACTION.search(line):
            count += 1
    return count


def actionable_tool_refresh_count(prompt: str) -> int:
    count = 0
    for line in prompt.splitlines():
        lowered = line.lower()
        if "--refresh-tools" not in lowered:
            continue
        if "setup_memory_archive.py" in lowered or lowered.lstrip().startswith(("python ", "$ python ")):
            count += 1
            continue
        if any(token in lowered for token in ("do not", "don't", "never", "must not", "forbid")):
            continue
        count += 1
    return count


def preflight_fail_closed_contract_present(prompt: str) -> bool:
    lowered = prompt.lower()
    required_tokens = (
        "report_kind",
        "report_version",
        "status=current",
        "nonzero",
        "missing",
        "stale",
        "unsafe",
        "malformed",
        "unparsable",
        "failed",
        "drifted",
        "blocked",
    )
    stop_language = (
        "stop before updater" in lowered and "do not run the updater" in lowered
    ) or (
        "stop before transaction adapter" in lowered
        and "do not run the transaction adapter" in lowered
    )
    return stop_language and all(token in lowered for token in required_tokens)


def terminal_status_contract_present(prompt: str) -> bool:
    lowered = prompt.lower()
    legacy_tokens = (
        "finish with exactly one terminal status",
        "`published`",
        "`no_op_current`",
        "`blocked`",
        "worktree is clean",
        "head equals origin/main",
    )
    transaction_tokens = (
        "finish with exactly one terminal status",
        "`published`",
        "`no_op_current`",
        "`deferred`",
        "`blocked`",
        "source_batch_complete",
        "canonical worktree is clean",
        "canonical head equals origin/main",
    )
    return all(token in lowered for token in legacy_tokens) or all(
        token in lowered for token in transaction_tokens
    )


def strict_transaction_report_contract_present(prompt: str) -> bool:
    lowered = prompt.lower()
    required_tokens = (
        "exactly one json",
        "report_kind",
        "scheduled_memory_transaction",
        "report_version 1",
        "`published`",
        "`no_op_current`",
        "`deferred`",
        "`blocked`",
        "source_batch_complete",
        "failure_stage",
        "deferred",
        "missing",
        "malformed",
        "unparsable",
        "nonzero",
    )
    return all(token in lowered for token in required_tokens)


def transaction_semantics_present(prompt: str) -> bool:
    lowered = prompt.lower()
    required_tokens = (
        "exclusive transaction lock",
        "persistent staging clone",
        "rejects a dirty canonical",
        "archive audit",
        "publish-readiness",
        "search health",
        "sync dry-run",
        "remote publication receipt",
        "fast-forward",
    )
    return all(token in lowered for token in required_tokens)


def private_marker_count(prompt: str) -> int:
    return sum(1 for marker in PRIVATE_MARKERS if marker in prompt)


def evaluate_prompt(prompt: str) -> dict[str, object]:
    lines = prompt.splitlines()
    preflight_positions = command_positions(
        lines,
        "setup_memory_archive.py",
        "--check-tools",
        "--report-json",
        "--skip-config",
    )
    runner_update_positions = command_positions(lines, "tools/run_memory_updates.py")
    update_positions = [
        *runner_update_positions,
        *command_positions(lines, "tools/update_memory_archive.py"),
    ]
    transaction_positions = python_action_positions(
        lines,
        "run_scheduled_memory_transaction.py",
    )
    direct_tool_positions = [
        position
        for script_name in (
            "run_memory_updates.py",
            "update_memory_archive.py",
            "audit_memory_archive.py",
            "audit_publish_readiness.py",
            "repair_publish_surfaces.py",
            "search_memory.py",
            "sync_memory_archive.py",
        )
        for position in python_action_positions(lines, script_name)
    ]
    archive_positions = command_positions(lines, "tools/audit_memory_archive.py")
    readiness_positions = command_positions(lines, "tools/audit_publish_readiness.py")
    repair_positions = command_positions(lines, "tools/repair_publish_surfaces.py", "--apply")
    search_positions = command_positions(lines, "tools/search_memory.py", "--health-check")
    sync_dry_positions = command_positions(lines, "tools/sync_memory_archive.py", "--dry-run", "--push")
    sync_live_positions = command_positions(
        lines,
        "tools/sync_memory_archive.py",
        "--push",
        excluded=("--dry-run",),
    )
    head_positions = command_positions(lines, "git rev-parse HEAD")
    fetch_positions = command_positions(lines, "git fetch origin main")
    origin_head_positions = command_positions(lines, "git rev-parse origin/main")
    clean_status_positions = command_positions(
        lines,
        "git status --porcelain=v1 --untracked-files=all",
    )
    generic_search_count = actionable_generic_content_query_count(prompt)
    raw_git_count = actionable_raw_git_publish_path_count(prompt)
    private_count = private_marker_count(prompt)
    refresh_count = actionable_tool_refresh_count(prompt)

    update = min(update_positions) if update_positions else None
    transaction = min(transaction_positions) if transaction_positions else None
    operation = transaction if transaction is not None else update
    preflight = min(preflight_positions) if preflight_positions else None
    archive_before = first_after(archive_positions, update) if update is not None else None
    readiness_before = first_after(readiness_positions, archive_before) if archive_before is not None else None
    repair = first_after(repair_positions, readiness_before) if readiness_before is not None else None
    archive_after = first_after(archive_positions, repair) if repair is not None else None
    readiness_after = first_after(readiness_positions, archive_after) if archive_after is not None else None
    search_after = first_after(search_positions, readiness_after) if readiness_after is not None else None
    sync_dry = first_after(sync_dry_positions, search_after) if search_after is not None else None
    sync_live = first_after(sync_live_positions, sync_dry) if sync_dry is not None else None
    initial_head = (
        max((position for position in head_positions if update is not None and position < update), default=None)
        if update is not None
        else None
    )
    receipt_fetch = first_after(fetch_positions, sync_live) if sync_live is not None else None
    receipt_head = first_after(head_positions, receipt_fetch) if receipt_fetch is not None else None
    receipt_origin_head = (
        first_after(origin_head_positions, receipt_head) if receipt_head is not None else None
    )
    receipt_clean_status = (
        first_after(clean_status_positions, receipt_origin_head)
        if receipt_origin_head is not None
        else None
    )

    publish_readiness_gate_present = readiness_before is not None and readiness_after is not None
    repair_step_present = repair is not None
    post_repair_recheck_present = archive_after is not None and readiness_after is not None and search_after is not None
    sync_dry_run_before_push_present = sync_dry is not None and sync_live is not None and sync_dry < sync_live
    sync_only_publish_path_present = sync_live is not None and raw_git_count == 0
    preflight_before_update_present = (
        preflight is not None and operation is not None and preflight < operation
    )
    fail_closed_present = preflight_fail_closed_contract_present(prompt)
    legacy_clean_worktree_flag_present = bool(runner_update_positions) and all(
        "--require-clean-worktree" in lines[position]
        for position in runner_update_positions
    )
    receipt_language_present = all(
        token in prompt.lower()
        for token in (
            "publication receipt",
            "live sync helper returned zero",
            "final head differs from the starting commit",
            "head equals origin/main",
            "worktree is clean",
        )
    )
    legacy_publication_receipt_contract_present = (
        initial_head is not None
        and receipt_fetch is not None
        and receipt_head is not None
        and receipt_origin_head is not None
        and receipt_clean_status is not None
        and receipt_language_present
    )
    terminal_contract_present = terminal_status_contract_present(prompt)
    strict_transaction_report = strict_transaction_report_contract_present(prompt)
    transaction_semantics = transaction_semantics_present(prompt)
    single_transaction_adapter = (
        len(transaction_positions) == 1
        and all(
            token in lines[transaction_positions[0]]
            for token in (
                "--memory-repo",
                "--source-dir",
                "--state-dir",
                "--push",
                "--include-reviewed-memory-nodes",
            )
        )
    )
    transaction_direct_publish_chain_count = len(direct_tool_positions)
    transaction_publication_receipt = (
        transaction_semantics
        and strict_transaction_report
        and "canonical head equals origin/main" in prompt.lower()
        and "canonical worktree is clean" in prompt.lower()
    )
    transaction_aligned = (
        single_transaction_adapter
        and transaction_direct_publish_chain_count == 0
        and transaction_semantics
        and strict_transaction_report
        and transaction_publication_receipt
        and terminal_contract_present
    )
    clean_worktree_flag_present = (
        transaction_semantics if transaction is not None else legacy_clean_worktree_flag_present
    )
    publication_receipt_contract_present = (
        transaction_publication_receipt
        if transaction is not None
        else legacy_publication_receipt_contract_present
    )
    task_completion_not_publish_success_present = (
        "task completion is not publish success" in prompt.lower()
        and "task state alone" in prompt.lower()
    )
    preflight_aligned = preflight_before_update_present and fail_closed_present and refresh_count == 0
    legacy_aligned = (
        update is not None
        and archive_before is not None
        and publish_readiness_gate_present
        and repair_step_present
        and post_repair_recheck_present
        and sync_dry_run_before_push_present
        and sync_only_publish_path_present
        and generic_search_count == 0
        and private_count == 0
        and clean_worktree_flag_present
        and publication_receipt_contract_present
        and terminal_contract_present
        and task_completion_not_publish_success_present
    )
    aligned = (
        transaction_aligned
        and generic_search_count == 0
        and raw_git_count == 0
        and private_count == 0
        and task_completion_not_publish_success_present
    ) if transaction is not None else legacy_aligned
    if transaction is not None:
        publish_readiness_gate_present = transaction_semantics
        repair_step_present = transaction_semantics
        post_repair_recheck_present = transaction_semantics
        sync_dry_run_before_push_present = transaction_semantics
        sync_only_publish_path_present = (
            single_transaction_adapter and transaction_direct_publish_chain_count == 0
        )
    return {
        "aligned": aligned,
        "update_present": update is not None,
        "archive_audit_present": archive_before is not None,
        "publish_readiness_gate_present": publish_readiness_gate_present,
        "repair_step_present": repair_step_present,
        "post_repair_recheck_present": post_repair_recheck_present,
        "search_health_present": search_after is not None,
        "sync_dry_run_before_push_present": sync_dry_run_before_push_present,
        "sync_only_publish_path_present": sync_only_publish_path_present,
        "generic_content_query_required": generic_search_count > 0,
        "raw_git_publish_path_count": raw_git_count,
        "private_archive_content_committed_count": private_count,
        "preflight_before_update_present": preflight_before_update_present,
        "preflight_fail_closed_contract_present": fail_closed_present,
        "actionable_tool_refresh_count": refresh_count,
        "preflight_aligned": preflight_aligned,
        "clean_worktree_flag_present": clean_worktree_flag_present,
        "publication_receipt_contract_present": publication_receipt_contract_present,
        "terminal_status_contract_present": terminal_contract_present,
        "task_completion_not_publish_success_present": task_completion_not_publish_success_present,
        "transaction_adapter_present": transaction is not None,
        "single_transaction_adapter_invocation_present": single_transaction_adapter,
        "strict_transaction_report_contract_present": strict_transaction_report,
        "transaction_direct_publish_chain_count": transaction_direct_publish_chain_count,
    }


def synthetic_preflight_prompt(
    *,
    updater_first: bool = False,
    auto_refresh: bool = False,
    require_clean_worktree: bool = True,
    include_publication_receipt: bool = True,
) -> str:
    preflight = (
        "python /installed/setup-my-precious/scripts/setup_memory_archive.py "
        "--path /tmp/agent-memory --check-tools --report-json --skip-config"
    )
    update = "python tools/run_memory_updates.py --memory-repo /tmp/agent-memory --source-dir /tmp/source"
    if require_clean_worktree:
        update += " --require-clean-worktree"
    prefix = [
        "Run the runtime parity preflight before updater execution.",
        "Before running the updater, record the starting commit with:",
        "git rev-parse HEAD",
        update if updater_first else preflight,
        preflight if updater_first else (
            "Require exit zero and valid JSON with report_kind runtime_tool_bundle_parity, "
            "report_version 1, status=current, matching expected counts, equal hashes, and zero privacy leaks."
        ),
    ]
    if updater_first:
        prefix.append(
            "Require exit zero and valid JSON with report_kind runtime_tool_bundle_parity, "
            "report_version 1, status=current, matching expected counts, equal hashes, and zero privacy leaks."
        )
    prefix.extend(
        [
            "If exit is nonzero or the report is missing, stale, unsafe, malformed, unparsable, "
            "failed, drifted, or blocked, stop before updater and do not run the updater.",
            "Never run --refresh-tools from scheduled automation.",
        ]
    )
    if auto_refresh:
        prefix.append(
            "python /installed/setup-my-precious/scripts/setup_memory_archive.py "
            "--path /tmp/agent-memory --refresh-tools --skip-config"
        )
    if not updater_first:
        prefix.append(update)
    prefix.extend(
        [
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/repair_publish_surfaces.py --memory-repo /tmp/agent-memory --apply",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --dry-run --push",
            "python tools/sync_memory_archive.py --push",
        ]
    )
    if include_publication_receipt:
        prefix.extend(
            [
                "Task completion is not publish success. Verify the publication receipt after sync.",
                "git fetch origin main",
                "git rev-parse HEAD",
                "git rev-parse origin/main",
                "git status --porcelain=v1 --untracked-files=all",
                "Finish with exactly one terminal status:",
                "- `published`: only when the live sync helper returned zero, the worktree is clean, HEAD equals origin/main, and final HEAD differs from the starting commit.",
                "- `no_op_current`: only for a confirmed no-op when the worktree is clean and HEAD equals origin/main.",
                "- `blocked`: for every other result.",
                "Do not infer publication from task state alone.",
            ]
        )
    return "\n".join(prefix)


def synthetic_transaction_prompt(
    *,
    duplicate_adapter: bool = False,
    same_line_duplicate_adapter: bool = False,
    include_report_contract: bool = True,
) -> str:
    adapter_command = (
        "python /installed/update-my-precious/scripts/run_scheduled_memory_transaction.py "
        "--memory-repo /tmp/agent-memory --source-dir /tmp/source "
        "--state-dir /tmp/transaction-state --push --include-reviewed-memory-nodes"
    )
    lines = [
        "Run the runtime parity preflight before transaction adapter execution.",
        "python /installed/setup-my-precious/scripts/setup_memory_archive.py "
        "--path /tmp/agent-memory --check-tools --report-json --skip-config",
        "Require exit zero and valid JSON with report_kind runtime_tool_bundle_parity, "
        "report_version 1, status=current, matching expected counts, equal hashes, and zero privacy leaks.",
        "If exit is nonzero or the report is missing, stale, unsafe, malformed, unparsable, "
        "failed, drifted, or blocked, stop before transaction adapter and do not run the transaction adapter.",
        "Never run --refresh-tools from scheduled automation.",
        "Run exactly one transaction adapter invocation:",
        f"{adapter_command}; {adapter_command}" if same_line_duplicate_adapter else adapter_command,
        "The adapter uses an exclusive transaction lock and persistent staging clone, rejects a dirty canonical, "
        "and runs archive audit, publish-readiness, bounded repair, search health, sync dry-run, live sync, "
        "remote publication receipt verification, and canonical fast-forward in that order.",
    ]
    if duplicate_adapter:
        lines.append(adapter_command)
    if include_report_contract:
        lines.extend(
            [
                "Require exactly one JSON object with report_kind scheduled_memory_transaction, "
                "report_version 1, and status `published`, `no_op_current`, `deferred`, or `blocked`.",
                "A nonzero exit or missing, malformed, or unparsable adapter report is `blocked`.",
                "Consume failure_stage and aggregate processed/deferred/child-failure counts only; "
                "never render child output or source paths.",
                "Task completion is not publish success; never infer success from task state alone.",
                "Finish with exactly one terminal status:",
                "- `published`: only when the adapter verified the remote publication receipt, "
                "the canonical worktree is clean, and canonical HEAD equals origin/main; "
                "source_batch_complete may be false when stable siblings were published.",
                "- `no_op_current`: only when the adapter confirmed no changes, the canonical worktree is clean, "
                "canonical HEAD equals origin/main, source_batch_complete is true, and deferred counts are zero.",
                "- `deferred`: successful zero-exit with no publication when source_batch_complete is false "
                "and aggregate deferred record/target counts are nonzero.",
                "- `blocked`: for every other result.",
            ]
        )
    return "\n".join(lines)


def negative_missing_readiness_prompt() -> str:
    return "\n".join(
        [
            "Run the My Precious memory update from this memory repository workspace.",
            "python tools/run_memory_updates.py --memory-repo /tmp/agent-memory --source-dir /tmp/source",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --push",
        ]
    )


def negative_raw_git_prompt() -> str:
    return "\n".join(
        [
            "Run the My Precious memory update from this memory repository workspace.",
            "python tools/run_memory_updates.py --memory-repo /tmp/agent-memory --source-dir /tmp/source",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/repair_publish_surfaces.py --memory-repo /tmp/agent-memory --apply",
            "python tools/audit_memory_archive.py --memory-repo /tmp/agent-memory",
            "python tools/audit_publish_readiness.py --memory-repo /tmp/agent-memory",
            "python tools/search_memory.py --health-check",
            "python tools/sync_memory_archive.py --dry-run --push",
            "git add .",
            "git commit -m update",
            "git push",
        ]
    )


def case_result(case: PromptCase) -> dict[str, object]:
    evaluation = evaluate_prompt(case.prompt)
    aligned = bool(evaluation["aligned"]) and (
        not case.requires_preflight or bool(evaluation["preflight_aligned"])
    ) and (
        not case.requires_transaction_adapter
        or bool(evaluation["transaction_adapter_present"])
    )
    if aligned != case.expected_aligned:
        raise GateFailure(case.name, f"unexpected_alignment_{aligned}")
    return {
        "case": case.name,
        "expected_aligned": case.expected_aligned,
        "actual_aligned": aligned,
        "is_live": case.is_live,
        "publish_readiness_gate_present": bool(evaluation["publish_readiness_gate_present"]),
        "repair_step_present": bool(evaluation["repair_step_present"]),
        "post_repair_recheck_present": bool(evaluation["post_repair_recheck_present"]),
        "sync_dry_run_before_push_present": bool(evaluation["sync_dry_run_before_push_present"]),
        "sync_only_publish_path_present": bool(evaluation["sync_only_publish_path_present"]),
        "generic_content_query_required": bool(evaluation["generic_content_query_required"]),
        "raw_git_publish_path_count": int(evaluation["raw_git_publish_path_count"]),
        "private_archive_content_committed_count": int(evaluation["private_archive_content_committed_count"]),
        "requires_preflight": case.requires_preflight,
        "requires_transaction_adapter": case.requires_transaction_adapter,
        "preflight_before_update_present": bool(evaluation["preflight_before_update_present"]),
        "preflight_fail_closed_contract_present": bool(
            evaluation["preflight_fail_closed_contract_present"]
        ),
        "actionable_tool_refresh_count": int(evaluation["actionable_tool_refresh_count"]),
        "clean_worktree_flag_present": bool(evaluation["clean_worktree_flag_present"]),
        "publication_receipt_contract_present": bool(
            evaluation["publication_receipt_contract_present"]
        ),
        "terminal_status_contract_present": bool(evaluation["terminal_status_contract_present"]),
        "task_completion_not_publish_success_present": bool(
            evaluation["task_completion_not_publish_success_present"]
        ),
        "transaction_adapter_present": bool(evaluation["transaction_adapter_present"]),
        "single_transaction_adapter_invocation_present": bool(
            evaluation["single_transaction_adapter_invocation_present"]
        ),
        "strict_transaction_report_contract_present": bool(
            evaluation["strict_transaction_report_contract_present"]
        ),
        "transaction_direct_publish_chain_count": int(
            evaluation["transaction_direct_publish_chain_count"]
        ),
    }


def build_report(case_results: list[dict[str, object]], *, live_requested: bool) -> dict[str, object]:
    rendered = next(case for case in case_results if case["case"] == "rendered_agent_native_prompt")
    live_cases = [case for case in case_results if case["is_live"]]
    positive_cases = [case for case in case_results if case["expected_aligned"]]
    negative_cases = [case for case in case_results if not case["expected_aligned"]]
    preflight_cases = [case for case in positive_cases if case["requires_preflight"]]
    synthetic_preflight = next(
        case for case in case_results if case["case"] == "synthetic_preflight_prompt"
    )
    synthetic_transaction = next(
        case for case in case_results if case["case"] == "synthetic_transaction_prompt"
    )
    transaction_positive_cases = [
        case for case in positive_cases if case["requires_transaction_adapter"]
    ]
    raw_git_count = sum(int(case["raw_git_publish_path_count"]) for case in positive_cases)
    private_count = sum(int(case["private_archive_content_committed_count"]) for case in positive_cases)
    metrics = {
        "live_automation_contract_checked": 1 if live_cases else 0,
        "live_automation_contract_requested": 1 if live_requested else 0,
        "rendered_prompt_alignment_pass": bool(rendered["actual_aligned"]),
        "live_automation_alignment_pass": bool(live_cases and all(case["actual_aligned"] for case in live_cases)),
        "publish_readiness_gate_present": all(case["publish_readiness_gate_present"] for case in positive_cases),
        "repair_step_present": all(case["repair_step_present"] for case in positive_cases),
        "post_repair_recheck_present": all(case["post_repair_recheck_present"] for case in positive_cases),
        "sync_dry_run_before_push_present": all(case["sync_dry_run_before_push_present"] for case in positive_cases),
        "sync_only_publish_path_present": all(case["sync_only_publish_path_present"] for case in positive_cases),
        "synthetic_preflight_alignment_pass": bool(synthetic_preflight["actual_aligned"]),
        "transaction_adapter_alignment_pass": bool(synthetic_transaction["actual_aligned"]),
        "single_transaction_adapter_invocation_present": all(
            case["single_transaction_adapter_invocation_present"]
            for case in transaction_positive_cases
        ),
        "strict_transaction_report_contract_present": all(
            case["strict_transaction_report_contract_present"]
            for case in transaction_positive_cases
        ),
        "transaction_direct_publish_chain_count": sum(
            int(case["transaction_direct_publish_chain_count"])
            for case in transaction_positive_cases
        ),
        "preflight_before_update_present": all(
            case["preflight_before_update_present"] for case in preflight_cases
        ),
        "preflight_fail_closed_contract_present": all(
            case["preflight_fail_closed_contract_present"] for case in preflight_cases
        ),
        "clean_worktree_flag_present": all(
            case["clean_worktree_flag_present"] for case in positive_cases
        ),
        "publication_receipt_contract_present": all(
            case["publication_receipt_contract_present"] for case in positive_cases
        ),
        "terminal_status_contract_present": all(
            case["terminal_status_contract_present"] for case in positive_cases
        ),
        "task_completion_not_publish_success_present": all(
            case["task_completion_not_publish_success_present"] for case in positive_cases
        ),
        "updater_before_preflight_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_updater_before_preflight_prompt"
            and not case["actual_aligned"]
        ),
        "auto_refresh_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_auto_refresh_prompt" and not case["actual_aligned"]
        ),
        "missing_readiness_rejection_count": sum(
            1 for case in negative_cases if case["case"] == "negative_missing_readiness_prompt" and not case["actual_aligned"]
        ),
        "raw_git_rejection_count": sum(
            1 for case in negative_cases if case["case"] == "negative_raw_git_prompt" and not case["actual_aligned"]
        ),
        "missing_clean_worktree_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_missing_clean_worktree_prompt"
            and not case["actual_aligned"]
        ),
        "missing_publication_receipt_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_missing_publication_receipt_prompt"
            and not case["actual_aligned"]
        ),
        "duplicate_transaction_adapter_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_duplicate_transaction_adapter_prompt"
            and not case["actual_aligned"]
        ),
        "same_line_duplicate_transaction_adapter_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_same_line_duplicate_transaction_adapter_prompt"
            and not case["actual_aligned"]
        ),
        "missing_transaction_report_rejection_count": sum(
            1
            for case in negative_cases
            if case["case"] == "negative_missing_transaction_report_prompt"
            and not case["actual_aligned"]
        ),
        "raw_git_publish_path_count": raw_git_count,
        "private_archive_content_committed_count": private_count,
        "generic_content_query_required_count": sum(
            1 for case in positive_cases if case["generic_content_query_required"]
        ),
        "privacy_leak_count": private_count,
    }
    passed = (
        metrics["rendered_prompt_alignment_pass"]
        and (not live_requested or metrics["live_automation_alignment_pass"])
        and metrics["publish_readiness_gate_present"]
        and metrics["repair_step_present"]
        and metrics["post_repair_recheck_present"]
        and metrics["sync_dry_run_before_push_present"]
        and metrics["sync_only_publish_path_present"]
        and metrics["synthetic_preflight_alignment_pass"]
        and metrics["transaction_adapter_alignment_pass"]
        and metrics["single_transaction_adapter_invocation_present"]
        and metrics["strict_transaction_report_contract_present"]
        and metrics["transaction_direct_publish_chain_count"] == 0
        and metrics["preflight_before_update_present"]
        and metrics["preflight_fail_closed_contract_present"]
        and metrics["clean_worktree_flag_present"]
        and metrics["publication_receipt_contract_present"]
        and metrics["terminal_status_contract_present"]
        and metrics["task_completion_not_publish_success_present"]
        and metrics["updater_before_preflight_rejection_count"] == 1
        and metrics["auto_refresh_rejection_count"] == 1
        and metrics["missing_readiness_rejection_count"] == 1
        and metrics["raw_git_rejection_count"] == 1
        and metrics["missing_clean_worktree_rejection_count"] == 1
        and metrics["missing_publication_receipt_rejection_count"] == 1
        and metrics["duplicate_transaction_adapter_rejection_count"] == 1
        and metrics["same_line_duplicate_transaction_adapter_rejection_count"] == 1
        and metrics["missing_transaction_report_rejection_count"] == 1
        and metrics["raw_git_publish_path_count"] == 0
        and metrics["private_archive_content_committed_count"] == 0
        and metrics["generic_content_query_required_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "claim_boundary": (
            "deterministic scheduled prompt contract alignment only; not live scheduler reliability, "
            "not live GitHub availability, not LLM answer quality, not ranking quality, not vector search, "
            "not ontology discovery, not private archive quality, and not public leaderboard parity"
        ),
        "metrics": metrics,
        "cases": case_results,
        "privacy": {
            "aggregate_only": True,
            "prompt_text_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
    }


def run_gate(root: Path, *, automation_config: Path | None = None) -> dict[str, object]:
    memory_repo = setup_archive(root)
    cases = [
        PromptCase("rendered_agent_native_prompt", render_agent_native_prompt(memory_repo, root), True),
        PromptCase(
            "synthetic_preflight_prompt",
            synthetic_preflight_prompt(),
            True,
            requires_preflight=True,
        ),
        PromptCase(
            "synthetic_transaction_prompt",
            synthetic_transaction_prompt(),
            True,
            requires_preflight=True,
            requires_transaction_adapter=True,
        ),
        PromptCase("negative_missing_readiness_prompt", negative_missing_readiness_prompt(), False),
        PromptCase("negative_raw_git_prompt", negative_raw_git_prompt(), False),
        PromptCase(
            "negative_updater_before_preflight_prompt",
            synthetic_preflight_prompt(updater_first=True),
            False,
            requires_preflight=True,
        ),
        PromptCase(
            "negative_auto_refresh_prompt",
            synthetic_preflight_prompt(auto_refresh=True),
            False,
            requires_preflight=True,
        ),
        PromptCase(
            "negative_missing_clean_worktree_prompt",
            synthetic_preflight_prompt(require_clean_worktree=False),
            False,
            requires_preflight=True,
        ),
        PromptCase(
            "negative_missing_publication_receipt_prompt",
            synthetic_preflight_prompt(include_publication_receipt=False),
            False,
            requires_preflight=True,
        ),
        PromptCase(
            "negative_duplicate_transaction_adapter_prompt",
            synthetic_transaction_prompt(duplicate_adapter=True),
            False,
            requires_preflight=True,
            requires_transaction_adapter=True,
        ),
        PromptCase(
            "negative_same_line_duplicate_transaction_adapter_prompt",
            synthetic_transaction_prompt(same_line_duplicate_adapter=True),
            False,
            requires_preflight=True,
            requires_transaction_adapter=True,
        ),
        PromptCase(
            "negative_missing_transaction_report_prompt",
            synthetic_transaction_prompt(include_report_contract=False),
            False,
            requires_preflight=True,
            requires_transaction_adapter=True,
        ),
    ]
    if automation_config is not None:
        cases.append(
            PromptCase(
                "live_automation_config",
                prompt_from_automation_config(automation_config),
                True,
                True,
                True,
                True,
            )
        )
    return build_report([case_result(case) for case in cases], live_requested=automation_config is not None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--automation-config",
        type=Path,
        help="Optional local Codex automation.toml to validate without rendering prompt text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="my-precious-live-automation-alignment-") as tmpdir:
            report = run_gate(Path(tmpdir), automation_config=args.automation_config)
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": exc.to_report(),
            "privacy": {
                "aggregate_only": True,
                "prompt_text_rendered": False,
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
