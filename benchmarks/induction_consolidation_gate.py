#!/usr/bin/env python3
"""Gate deterministic reviewable automatic induction consolidation.

The gate creates a clean packaged memory archive, feeds it synthetic source
records through the copied deployment update tool, and scores only structured
memory/review indexes. It does not rely on free-form summaries as evidence.
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


REPORT_KIND = "induction_consolidation_gate"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"

DUPLICATE_TEXT = "V219 duplicate consolidation should preserve evidence refs across archive sessions."
PARAPHRASE_ALPHA = "V219 induction memories should preserve source citations during evidence recall."
PARAPHRASE_BETA = "V219 induction memory should keep source refs during evidence retrieval."
CONTRADICTION_POSITIVE = "V219 contradiction memory must preserve source refs for induced evidence nodes."
CONTRADICTION_NEGATIVE = "V219 contradiction memory must not preserve source refs for induced evidence nodes."
SCOPE_OLDER = "V219 scoped recall should preserve evidence refs for project-specific induced memories."
SCOPE_CURRENT = "V219 scoped recall should preserve evidence refs for induced memories."

NOISE_MARKERS = (
    "checked the failing tests",
    "sandbox approval policy",
    "assistant must save",
    "command status",
)
PRIVATE_LEAK_MARKERS = (
    "/Users/soku/private/source.jsonl",
    "SYNTHETIC_PRIVATE_TOKEN",
)


@dataclass(frozen=True)
class GateRun:
    memory_repo: Path
    update_failures: int
    command_outputs: list[induction.CommandResult]


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
            "v219_duplicate_alpha",
            "v219-duplicate-alpha",
            "2026-06-29T10:00:00Z",
            f"Reusable fact: {DUPLICATE_TEXT}",
        ),
        make_record(
            "v219_duplicate_beta",
            "v219-duplicate-beta",
            "2026-06-29T10:10:00Z",
            f"Reusable fact: {DUPLICATE_TEXT}",
        ),
        make_record(
            "v219_paraphrase_alpha",
            "v219-paraphrase-alpha",
            "2026-06-29T10:20:00Z",
            PARAPHRASE_ALPHA,
        ),
        make_record(
            "v219_paraphrase_beta",
            "v219-paraphrase-beta",
            "2026-06-29T10:30:00Z",
            PARAPHRASE_BETA,
        ),
        make_record(
            "v219_contradiction_positive",
            "v219-contradiction-positive",
            "2026-06-29T10:40:00Z",
            f"Reusable fact: {CONTRADICTION_POSITIVE}",
        ),
        make_record(
            "v219_contradiction_negative",
            "v219-contradiction-negative",
            "2026-06-29T10:50:00Z",
            f"Reusable fact: {CONTRADICTION_NEGATIVE}",
        ),
        make_record(
            "v219_scope_older",
            "v219-scope-older",
            "2026-06-29T11:00:00Z",
            SCOPE_OLDER,
        ),
        make_record(
            "v219_scope_current",
            "v219-scope-current",
            "2026-06-29T11:10:00Z",
            SCOPE_CURRENT,
        ),
        make_record(
            "v219_noise_process",
            "v219-noise-process",
            "2026-06-29T11:20:00Z",
            "Reusable fact: I checked the failing tests and will now inspect the archive.",
        ),
        make_record(
            "v219_noise_permission",
            "v219-noise-permission",
            "2026-06-29T11:30:00Z",
            "Reusable fact: Codex sandbox approval policy and full access permissions changed during this run.",
        ),
        make_record(
            "v219_noise_prompt",
            "v219-noise-prompt",
            "2026-06-29T11:40:00Z",
            (
                "Reusable fact: Prompt echo: the assistant must save "
                "/Users/soku/private/source.jsonl as memory."
            ),
        ),
        make_record(
            "v219_noise_automation",
            "v219-noise-automation",
            "2026-06-29T11:50:00Z",
            (
                "Reusable fact: Scheduled automation is running; command status: "
                "dry-run would push after commit. SYNTHETIC_PRIVATE_TOKEN"
            ),
        ),
    ]


def run_packaged_update(run_root: Path) -> GateRun:
    case_root = run_root / "v219-induction-consolidation"
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
    return GateRun(memory_repo, update_failures, command_outputs)


def text_key(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def automatic_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [node for node in nodes if node.get("source") == "automatic"]


def nodes_with_text(nodes: list[dict[str, Any]], texts: set[str]) -> list[dict[str, Any]]:
    wanted = {text_key(text) for text in texts}
    return [node for node in automatic_nodes(nodes) if text_key(node.get("text")) in wanted]


def first_node_with_text(nodes: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    matches = nodes_with_text(nodes, {text})
    return matches[0] if matches else None


def list_len(node: dict[str, Any] | None, key: str) -> int:
    value = node.get(key) if isinstance(node, dict) else None
    return len(value) if isinstance(value, list) else 0


def support_refs_covered(node: dict[str, Any] | None, minimum: int) -> bool:
    return bool(
        node is not None
        and int(node.get("support_count") or 0) >= minimum
        and list_len(node, "derived_from") >= minimum
        and list_len(node, "evidence_refs") >= minimum
        and list_len(node, "raw_refs") >= minimum
    )


def duplicate_merge_hit(nodes: list[dict[str, Any]]) -> bool:
    matches = nodes_with_text(nodes, {DUPLICATE_TEXT})
    return len(matches) == 1 and support_refs_covered(matches[0], 2)


def paraphrase_merge_hit(nodes: list[dict[str, Any]]) -> bool:
    matches = nodes_with_text(nodes, {PARAPHRASE_ALPHA, PARAPHRASE_BETA})
    return len(matches) == 1 and support_refs_covered(matches[0], 2)


def contradiction_preserved(nodes: list[dict[str, Any]], review_candidates: list[dict[str, Any]]) -> bool:
    positive = first_node_with_text(nodes, CONTRADICTION_POSITIVE)
    negative = first_node_with_text(nodes, CONTRADICTION_NEGATIVE)
    if positive is not None and negative is not None:
        positive_id = str(positive.get("memory_id") or "")
        negative_id = str(negative.get("memory_id") or "")
        return bool(
            positive_id
            and negative_id
            and (
                negative_id in list(positive.get("contradicts") or [])
                or positive_id in list(negative.get("contradicts") or [])
                or negative_id in list(positive.get("contradicted_by") or [])
                or positive_id in list(negative.get("contradicted_by") or [])
            )
        )
    return any(
        candidate.get("reason") == "conflicting_natural_induction_requires_review"
        for candidate in review_candidates
    )


def scope_review_hit(
    nodes: list[dict[str, Any]],
    induction_review_candidates: list[dict[str, Any]],
) -> bool:
    current_not_active = first_node_with_text(nodes, SCOPE_CURRENT) is None
    scope_reviewed = any(
        candidate.get("reason") == "scope_change_natural_induction_requires_review"
        for candidate in induction_review_candidates
    )
    return current_not_active and scope_reviewed


def process_noise_rejection_count(nodes: list[dict[str, Any]]) -> int:
    active_text = "\n".join(str(node.get("text") or "") for node in automatic_nodes(nodes)).lower()
    return sum(1 for marker in NOISE_MARKERS if marker.lower() not in active_text)


def false_active_count(nodes: list[dict[str, Any]]) -> int:
    active_texts = [str(node.get("text") or "") for node in automatic_nodes(nodes)]
    false_count = 0
    for text in active_texts:
        lowered = text.lower()
        if any(marker.lower() in lowered for marker in NOISE_MARKERS):
            false_count += 1
        if text_key(text) == text_key(SCOPE_CURRENT):
            false_count += 1
    return false_count


def support_ref_coverage_rate(nodes: list[dict[str, Any]]) -> float:
    checks = [
        support_refs_covered(first_node_with_text(nodes, DUPLICATE_TEXT), 2),
        any(support_refs_covered(node, 2) for node in nodes_with_text(nodes, {PARAPHRASE_ALPHA, PARAPHRASE_BETA})),
        support_refs_covered(first_node_with_text(nodes, CONTRADICTION_POSITIVE), 1),
        support_refs_covered(first_node_with_text(nodes, CONTRADICTION_NEGATIVE), 1),
    ]
    return sum(int(value) for value in checks) / len(checks)


def privacy_leak_count(memory_repo: Path, command_outputs: list[induction.CommandResult]) -> int:
    haystacks = [result.stdout + "\n" + result.stderr for result in command_outputs]
    for rel_path in (
        "index/memories.jsonl",
        "index/induction_review_candidates.jsonl",
        "index/memory_review_candidates.jsonl",
        "index/memory_consolidation_trace.jsonl",
        "memories/global.jsonl",
        "memories/domains.jsonl",
        "memories/projects.jsonl",
    ):
        path = memory_repo / rel_path
        if path.is_file():
            haystacks.append(path.read_text(encoding="utf-8"))
    combined = "\n".join(haystacks)
    return sum(1 for marker in PRIVATE_LEAK_MARKERS if marker in combined)


def build_report(gate_run: GateRun) -> dict[str, Any]:
    nodes = induction.load_nodes(gate_run.memory_repo)
    review_candidates = induction.load_review_candidates(gate_run.memory_repo)
    induction_review_candidates = induction.load_induction_review_candidates(gate_run.memory_repo)

    duplicate_hit = duplicate_merge_hit(nodes)
    paraphrase_hit = paraphrase_merge_hit(nodes)
    contradiction_hit = contradiction_preserved(nodes, induction_review_candidates)
    scope_hit = scope_review_hit(nodes, induction_review_candidates)
    noise_rejections = process_noise_rejection_count(nodes)
    false_count = false_active_count(nodes)
    leak_count = privacy_leak_count(gate_run.memory_repo, gate_run.command_outputs)

    active_memory_precision = 1.0 if false_count == 0 else 0.0
    review_routing_accuracy = 1.0 if scope_hit else 0.0
    metrics = {
        "induction_duplicate_merge_accuracy": 1.0 if duplicate_hit else 0.0,
        "induction_paraphrase_merge_accuracy": 1.0 if paraphrase_hit else 0.0,
        "induction_contradiction_preservation_count": 1 if contradiction_hit else 0,
        "induction_ambiguous_scope_review_count": 1 if scope_hit else 0,
        "induction_process_noise_rejection_count": noise_rejections,
        "induction_active_memory_precision": active_memory_precision,
        "induction_support_ref_coverage_rate": support_ref_coverage_rate(nodes),
        "review_routing_accuracy": review_routing_accuracy,
        "privacy_leak_count": leak_count,
    }
    cases = {
        "repeated_fact_consolidation": duplicate_hit,
        "paraphrased_fact_consolidation": paraphrase_hit,
        "contradiction_preservation": contradiction_hit,
        "ambiguous_scope_review_routing": scope_hit,
        "process_noise_rejection": noise_rejections == len(NOISE_MARKERS),
    }
    failed = (
        gate_run.update_failures > 0
        or not all(cases.values())
        or false_count != 0
        or leak_count != 0
        or metrics["induction_support_ref_coverage_rate"] < 1.0
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
            "induction_review_candidate_count": len(induction_review_candidates),
            "memory_review_candidate_count": len(review_candidates),
            "false_active_count": false_count,
        },
    }


def prepare_work_dir(path_text: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if path_text:
        root = Path(path_text).expanduser().resolve()
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        return root, None
    temp_handle = tempfile.TemporaryDirectory(prefix="my-precious-v219-")
    return Path(temp_handle.name), temp_handle


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional deterministic work directory to keep for inspection")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_root, temp_handle = prepare_work_dir(args.work_dir)
    try:
        report = build_report(run_packaged_update(run_root))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report.get("overall_status") == "pass" else 1
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
