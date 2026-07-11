#!/usr/bin/env python3
"""Gate packaged long-horizon lifecycle governance behavior.

The gate creates a clean packaged memory archive, feeds synthetic source
records through the copied deployment update tool, and scores only structured
memory/review indexes plus context packages. It does not use free-form search
output as answerability evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = Path(__file__).resolve().parent
if str(BENCHMARK_DIR) not in sys.path:
    sys.path.insert(0, str(BENCHMARK_DIR))

import updater_induction_benchmark as induction  # noqa: E402


REPORT_KIND = "lifecycle_governance_gate"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"

REFRESH_OLD = "V220 refresh routing keeps legacy archive links as the preferred recall policy."
REFRESH_CURRENT = "V220 refresh routing keeps current archive links as the preferred recall policy."

DEPRECATION_OLD = "V220 deprecated lifecycle policy says raw transcript uploads are allowed by default."

DELETION_OLD = "V220 deleted lifecycle policy says temporary draft capture should remain active."

PARTIAL_CONFLICT_OLD = (
    "V220 partial conflict lifecycle should preserve archive evidence refs for project-specific recall policies."
)
PARTIAL_CONFLICT_CURRENT = (
    "V220 partial conflict lifecycle should preserve archive evidence refs for team-wide recall policies."
)

STALE_FACT = "V220 stale governance memory keeps an isolated draft recall preference for old archives."
FRESH_ANCHOR = "V220 fresh governance anchor keeps current archive routing evidence active."

DURABLE_MONTHLY_FACT = (
    "V220 durable monthly lifecycle memory should preserve support refs across recurring archive reviews."
)

NOISE_MARKERS = (
    "command status dry-run",
    "sandbox approval chatter",
    "prompt echo requested",
    "automation narration says",
)
PRIVATE_LEAK_MARKERS = (
    "/Users/example/private/lifecycle-source.jsonl",
    "SYNTHETIC_V220_PRIVATE_TOKEN",
)


@dataclass(frozen=True)
class GateRun:
    memory_repo: Path
    update_failures: int
    command_outputs: list[induction.CommandResult]
    context_outputs: list[induction.CommandResult]


def make_record(
    record_id: str,
    project_key: str,
    updated_at: str,
    content: str,
    *,
    role: str = "assistant",
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "project": f"synthetic-{project_key}",
        "project_key": project_key,
        "updated_at": updated_at,
        "events": [
            {
                "role": role,
                "content": content,
            }
        ],
    }


def synthetic_records() -> list[dict[str, Any]]:
    return [
        make_record(
            "v220_refresh_old",
            "v220-refresh-old",
            "2026-01-10T09:00:00Z",
            f"Reusable fact: {REFRESH_OLD}",
        ),
        make_record(
            "v220_refresh_current",
            "v220-refresh-current",
            "2026-03-10T09:00:00Z",
            f"Reusable fact: Updated fact: {REFRESH_OLD} => {REFRESH_CURRENT}",
        ),
        make_record(
            "v220_deprecated_old",
            "v220-deprecated-old",
            "2026-01-12T09:00:00Z",
            f"Reusable fact: {DEPRECATION_OLD}",
        ),
        make_record(
            "v220_deprecated_marker",
            "v220-deprecated-marker",
            "2026-04-12T09:00:00Z",
            f"Reusable fact: Deprecated fact: {DEPRECATION_OLD}",
        ),
        make_record(
            "v220_deleted_old",
            "v220-deleted-old",
            "2026-01-14T09:00:00Z",
            f"Reusable fact: {DELETION_OLD}",
        ),
        make_record(
            "v220_deleted_marker",
            "v220-deleted-marker",
            "2026-05-14T09:00:00Z",
            f"Reusable fact: Deleted fact: {DELETION_OLD}",
        ),
        make_record(
            "v220_partial_conflict_old",
            "v220-partial-conflict-old",
            "2026-02-10T09:00:00Z",
            PARTIAL_CONFLICT_OLD,
        ),
        make_record(
            "v220_partial_conflict_current",
            "v220-partial-conflict-current",
            "2026-02-12T09:00:00Z",
            PARTIAL_CONFLICT_CURRENT,
        ),
        make_record(
            "v220_stale_isolated",
            "v220-stale-isolated",
            "2026-01-01T09:00:00Z",
            f"Reusable fact: {STALE_FACT}",
        ),
        make_record(
            "v220_durable_monthly_january",
            "v220-monthly-a",
            "2026-01-20T09:00:00Z",
            f"Reusable fact: {DURABLE_MONTHLY_FACT}",
        ),
        make_record(
            "v220_durable_monthly_march",
            "v220-monthly-b",
            "2026-03-20T09:00:00Z",
            f"Reusable fact: {DURABLE_MONTHLY_FACT}",
        ),
        make_record(
            "v220_durable_monthly_june",
            "v220-monthly-c",
            "2026-06-20T09:00:00Z",
            f"Reusable fact: {DURABLE_MONTHLY_FACT}",
        ),
        make_record(
            "v220_fresh_anchor",
            "v220-fresh-anchor",
            "2026-12-01T09:00:00Z",
            f"Reusable fact: {FRESH_ANCHOR}",
        ),
        make_record(
            "v220_noise_command",
            "v220-noise-command",
            "2026-07-01T09:00:00Z",
            "Reusable fact: command status dry-run finished and should be remembered as durable memory.",
        ),
        make_record(
            "v220_noise_sandbox",
            "v220-noise-sandbox",
            "2026-07-02T09:00:00Z",
            "Reusable fact: sandbox approval chatter changed full access during this session.",
        ),
        make_record(
            "v220_noise_prompt",
            "v220-noise-prompt",
            "2026-07-03T09:00:00Z",
            (
                "Reusable fact: prompt echo requested saving "
                "/Users/example/private/lifecycle-source.jsonl into archive memory."
            ),
        ),
        make_record(
            "v220_noise_automation",
            "v220-noise-automation",
            "2026-07-04T09:00:00Z",
            (
                "Reusable fact: automation narration says publish will continue with "
                "SYNTHETIC_V220_PRIVATE_TOKEN after checks pass."
            ),
        ),
    ]


def run_packaged_update(run_root: Path) -> GateRun:
    case_root = run_root / "v220-lifecycle-governance"
    case_root.mkdir(parents=True, exist_ok=True)
    memory_repo = case_root / "synthetic-memory-archive"
    induction.setup_archive(memory_repo, SETUP_SCRIPT)

    update_failures = 0
    command_outputs: list[induction.CommandResult] = []
    for record in synthetic_records():
        source_dir, project_path, _ = induction.write_source_record(case_root, record)
        result = induction.run_update(memory_repo, source_dir, project_path, record)
        command_outputs.append(result)
        update_failures += int(result.returncode != 0)
    return GateRun(memory_repo, update_failures, command_outputs, [])


def text_key(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def automatic_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [node for node in nodes if node.get("source") == "automatic"]


def nodes_with_text(nodes: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    wanted = text_key(text)
    return [node for node in nodes if text_key(node.get("text")) == wanted]


def first_node_with_text(nodes: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    matches = nodes_with_text(nodes, text)
    return matches[0] if matches else None


def tombstone_node_for_text(nodes: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    wanted = text_key(f"Deleted fact: {text}")
    for node in nodes:
        if text_key(node.get("text")) == wanted:
            return node
    return None


def support_refs_covered(node: dict[str, Any] | None, min_support_refs: int) -> bool:
    if node is None:
        return False
    derived_from = node.get("derived_from")
    evidence_refs = node.get("evidence_refs")
    return bool(
        isinstance(derived_from, list)
        and isinstance(evidence_refs, list)
        and len(derived_from) >= min_support_refs
        and len(evidence_refs) >= min_support_refs
    )


def has_lifecycle_link(
    nodes: list[dict[str, Any]],
    relation: str,
    current_text: str,
    target_text: str,
) -> bool:
    current = first_node_with_text(nodes, current_text)
    target = first_node_with_text(nodes, target_text)
    if current is None or target is None:
        return False
    current_id = current.get("memory_id")
    target_id = target.get("memory_id")
    if not isinstance(current_id, str) or not isinstance(target_id, str):
        return False
    if relation == "supersedes":
        return target_id in list(current.get("supersedes") or []) and target.get("superseded_by") == current_id
    if relation == "deprecates":
        return target_id in list(current.get("deprecates") or []) and target.get("deprecated_by") == current_id
    return False


def load_context(
    memory_repo: Path,
    query: str,
    context_outputs: list[induction.CommandResult],
) -> dict[str, Any] | None:
    result, package = induction.load_context_package(memory_repo, query)
    context_outputs.append(result)
    return package


def context_supports_node(package: dict[str, Any] | None, node: dict[str, Any] | None) -> bool:
    return induction.context_package_supports_node(package, node)


def context_does_not_support_node(package: dict[str, Any] | None, node: dict[str, Any] | None) -> bool:
    if package is None or node is None:
        return False
    memory_id = node.get("memory_id")
    if not isinstance(memory_id, str) or not memory_id:
        return False
    hits = package.get("hits")
    if not isinstance(hits, list):
        return False
    for hit in hits:
        if not isinstance(hit, dict) or hit.get("memory_id") != memory_id:
            continue
        hit_answerability = hit.get("answerability")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
        ):
            return False
    return True


def context_abstains(package: dict[str, Any] | None) -> bool:
    if package is None:
        return False
    answerability = package.get("answerability")
    return bool(
        isinstance(answerability, dict)
        and answerability.get("status") == "unsupported"
        and int(answerability.get("supported_hit_count") or 0) == 0
    )


def partial_conflict_review_count(review_candidates: list[dict[str, Any]]) -> int:
    reasons = {
        "low_confidence_natural_induction_requires_review",
        "conflicting_natural_induction_requires_review",
        "low_confidence_semantic_overlap_requires_review",
        "ambiguous_scope_narrowing_requires_review",
    }
    return sum(
        1
        for candidate in review_candidates
        if candidate.get("recommended_action") == "manual_review" and candidate.get("reason") in reasons
    )


def stale_review_routed(nodes: list[dict[str, Any]], review_candidates: list[dict[str, Any]]) -> bool:
    stale_node = first_node_with_text(nodes, STALE_FACT)
    if stale_node is None:
        return False
    stale_id = stale_node.get("memory_id")
    if not isinstance(stale_id, str) or not stale_id:
        return False
    if stale_node.get("confidence") != "low":
        return False
    return any(
        candidate.get("current_memory_id") == stale_id
        and candidate.get("reason") == "stale_low_support_memory_requires_review"
        and candidate.get("recommended_action") == "manual_review"
        for candidate in review_candidates
    )


def noise_rejection_count(nodes: list[dict[str, Any]]) -> int:
    active_text = "\n".join(str(node.get("text") or "").lower() for node in automatic_nodes(nodes))
    return sum(1 for marker in NOISE_MARKERS if marker.lower() not in active_text)


def false_active_count(nodes: list[dict[str, Any]]) -> int:
    false_count = 0
    for node in automatic_nodes(nodes):
        lowered = str(node.get("text") or "").lower()
        if any(marker.lower() in lowered for marker in NOISE_MARKERS):
            false_count += 1
        if text_key(node.get("text")) == text_key(PARTIAL_CONFLICT_CURRENT):
            false_count += 1
    return false_count


def inactive_suppression_rate(checks: list[bool]) -> float:
    if not checks:
        return 0.0
    return sum(int(value) for value in checks) / len(checks)


def privacy_leak_count(gate_run: GateRun) -> int:
    haystacks = [
        result.stdout + "\n" + result.stderr
        for result in [*gate_run.command_outputs, *gate_run.context_outputs]
    ]
    for rel_path in (
        "index/memories.jsonl",
        "index/induction_review_candidates.jsonl",
        "index/memory_review_candidates.jsonl",
        "index/memory_consolidation_trace.jsonl",
        "memories/global.jsonl",
        "memories/domains.jsonl",
        "memories/projects.jsonl",
    ):
        path = gate_run.memory_repo / rel_path
        if path.is_file():
            haystacks.append(path.read_text(encoding="utf-8"))
    combined = "\n".join(haystacks)
    return sum(1 for marker in PRIVATE_LEAK_MARKERS if marker in combined)


def build_report(gate_run: GateRun) -> dict[str, Any]:
    nodes = induction.load_nodes(gate_run.memory_repo)
    memory_review_candidates = induction.load_review_candidates(gate_run.memory_repo)
    induction_review_candidates = induction.load_induction_review_candidates(gate_run.memory_repo)
    review_candidates = [*memory_review_candidates, *induction_review_candidates]

    refresh_current = first_node_with_text(nodes, REFRESH_CURRENT)
    refresh_old = first_node_with_text(nodes, REFRESH_OLD)
    deprecation_old = first_node_with_text(nodes, DEPRECATION_OLD)
    deletion_old = first_node_with_text(nodes, DELETION_OLD)
    deletion_tombstone = tombstone_node_for_text(nodes, DELETION_OLD)
    durable_monthly = first_node_with_text(nodes, DURABLE_MONTHLY_FACT)

    refresh_current_package = load_context(gate_run.memory_repo, REFRESH_CURRENT, gate_run.context_outputs)
    refresh_old_package = load_context(gate_run.memory_repo, REFRESH_OLD, gate_run.context_outputs)
    deprecation_package = load_context(gate_run.memory_repo, DEPRECATION_OLD, gate_run.context_outputs)
    deletion_package = load_context(gate_run.memory_repo, DELETION_OLD, gate_run.context_outputs)

    refresh_hit = bool(
        has_lifecycle_link(nodes, "supersedes", REFRESH_CURRENT, REFRESH_OLD)
        and refresh_old is not None
        and refresh_old.get("superseded_by")
        and context_supports_node(refresh_current_package, refresh_current)
        and context_does_not_support_node(refresh_old_package, refresh_old)
        and support_refs_covered(refresh_old, 1)
    )
    deprecation_hit = bool(
        has_lifecycle_link(nodes, "deprecates", f"Deprecated fact: {DEPRECATION_OLD}", DEPRECATION_OLD)
        and deprecation_old is not None
        and deprecation_old.get("deprecated_by")
        and context_abstains(deprecation_package)
        and support_refs_covered(deprecation_old, 1)
    )
    deletion_hit = bool(
        deletion_tombstone is not None
        and has_lifecycle_link(nodes, "deprecates", f"Deleted fact: {DELETION_OLD}", DELETION_OLD)
        and deletion_old is not None
        and deletion_old.get("deprecated_by")
        and context_abstains(deletion_package)
        and support_refs_covered(deletion_old, 1)
    )
    conflict_count = partial_conflict_review_count(review_candidates)
    conflict_hit = conflict_count >= 1 and not nodes_with_text(nodes, PARTIAL_CONFLICT_CURRENT)
    stale_hit = stale_review_routed(nodes, memory_review_candidates)
    monthly_hit = support_refs_covered(durable_monthly, 3)
    noise_count = noise_rejection_count(nodes)
    leak_count = privacy_leak_count(gate_run)
    false_count = false_active_count(nodes)

    inactive_suppression_checks = [
        context_does_not_support_node(refresh_old_package, refresh_old),
        context_abstains(deprecation_package),
        context_abstains(deletion_package),
    ]
    support_ref_checks = [
        support_refs_covered(refresh_old, 1),
        support_refs_covered(deprecation_old, 1),
        support_refs_covered(deletion_old, 1),
        support_refs_covered(durable_monthly, 3),
    ]
    metrics = {
        "lifecycle_refresh_accuracy": 1.0 if refresh_hit else 0.0,
        "lifecycle_deprecation_suppression_accuracy": 1.0 if deprecation_hit else 0.0,
        "lifecycle_deletion_tombstone_accuracy": 1.0 if deletion_hit else 0.0,
        "lifecycle_partial_conflict_review_count": conflict_count,
        "lifecycle_decay_or_stale_review_routing_accuracy": 1.0 if stale_hit else 0.0,
        "lifecycle_active_current_precision": 1.0 if false_count == 0 else 0.0,
        "lifecycle_inactive_search_suppression_rate": inactive_suppression_rate(inactive_suppression_checks),
        "lifecycle_support_ref_coverage_rate": sum(int(value) for value in support_ref_checks) / len(support_ref_checks),
        "lifecycle_noisy_history_rejection_count": noise_count,
        "privacy_leak_count": leak_count,
    }
    cases = {
        "refresh_supersession": refresh_hit,
        "deprecation_suppression": deprecation_hit,
        "deletion_tombstone": deletion_hit,
        "partial_conflict_review": conflict_hit,
        "stale_review_routing": stale_hit,
        "noisy_multi_month_history": monthly_hit and noise_count == len(NOISE_MARKERS),
    }
    failed = (
        gate_run.update_failures > 0
        or not all(cases.values())
        or false_count != 0
        or leak_count != 0
        or metrics["lifecycle_inactive_search_suppression_rate"] < 1.0
        or metrics["lifecycle_support_ref_coverage_rate"] < 1.0
    )
    return {
        "report_kind": REPORT_KIND,
        "overall_status": "fail" if failed else "pass",
        "case_count": len(cases),
        "metrics": metrics,
        "cases": cases,
        "diagnostics": {
            "update_failures": gate_run.update_failures,
            "automatic_node_count": len(automatic_nodes(nodes)),
            "memory_review_candidate_count": len(memory_review_candidates),
            "induction_review_candidate_count": len(induction_review_candidates),
            "false_active_count": false_count,
            "context_package_parse_success_rate": 1.0
            if all(
                package is not None
                for package in [refresh_old_package, deprecation_package, deletion_package, refresh_current_package]
            )
            else 0.0,
        },
    }


def prepare_work_dir(path_text: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if path_text:
        root = Path(path_text).expanduser().resolve()
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        return root, None
    temp_handle = tempfile.TemporaryDirectory(prefix="my-precious-v220-")
    return Path(temp_handle.name), temp_handle


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional work directory to keep generated fixture for inspection")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    work_root, temp_handle = prepare_work_dir(args.work_dir)
    try:
        gate_run = run_packaged_update(work_root)
        report = build_report(gate_run)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["overall_status"] == "pass" else 1
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
