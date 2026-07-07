#!/usr/bin/env python3
"""Gate package-first progressive source drilldown for using-my-precious.

The gate installs a clean packaged archive, writes only synthetic memory rows,
calls the copied deployment search tool with --context-json at evidence and
source depths, and verifies answer/drill/abstain decisions without consulting
free-form search output.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
CONTEXT_REPORT_KIND = "memory_recall_context_package"

SUPPORTED_ANSWER_CASE = "supported_answer"
SUPPORTED_SOURCE_CASE = "supported_source_drilldown"
MULTIHOP_SOURCE_CASE = "multihop_source_drilldown"
EVIDENCE_ONLY_CASE = "evidence_only_original_source"
INACTIVE_SOURCE_CASE = "inactive_source_only"
UNSAFE_SOURCE_CASE = "unsafe_source_ref"
MALFORMED_CASE = "malformed_package"

DIRECT_TEXT = "v26direct source anchor durable answer value"
HIGHLEVEL_TEXT = "v26graph highlevel source drilldown answer"
LEAF_TEXT = "v26leaf support carries source anchor"
EVIDENCE_ONLY_TEXT = "v26evidenceonly original source request answer"
INACTIVE_TEXT = "v26retired source only obsolete answer"
UNSAFE_TEXT = "v26unsafe source ref reachable blocked answer"
RAW_SOURCE_SENTINEL = "RAW V26 TRANSCRIPT SHOULD NOT RENDER"
SECRET_SENTINEL = "cookie=V26_SHOULD_NOT_RENDER"

LEAK_MARKERS = (
    DIRECT_TEXT,
    HIGHLEVEL_TEXT,
    LEAF_TEXT,
    EVIDENCE_ONLY_TEXT,
    INACTIVE_TEXT,
    UNSAFE_TEXT,
    RAW_SOURCE_SENTINEL,
    SECRET_SENTINEL,
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
class CaseSpec:
    case_id: str
    query: str
    depth: str
    expected_action: str
    expected_memory_id: str = ""
    require_source: bool = False
    require_multihop: bool = False


@dataclass(frozen=True)
class DrilldownDecision:
    action: str
    reason: str
    parse_success: bool
    report_kind: str
    summary_reachable: bool = False
    evidence_reachable: bool = False
    source_ref_reachable: bool = False
    source_ref_blocked: bool = False
    multihop_source_resolved: bool = False
    raw_source_default_blocked: bool = False


@dataclass(frozen=True)
class CaseResult:
    spec: CaseSpec
    decision: DrilldownDecision
    package_text: str


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


def setup_packaged_archive(root: Path) -> Path:
    memory_repo = root / "agent-memory"
    run_command(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--skip-config",
        ],
        "setup_packaged_archive",
    )
    if not (memory_repo / "tools/search_memory.py").is_file():
        raise GateFailure("setup_packaged_archive", "search_tool_missing")
    return memory_repo


def support_paths(slug: str) -> tuple[str, str]:
    base = f"sessions/synthetic/v26-{slug}"
    return f"{base}/summary.md", f"{base}/evidence.md"


def write_support_files(repo: Path, slug: str, title: str) -> tuple[str, str]:
    summary_path, evidence_path = support_paths(slug)
    (repo / summary_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / evidence_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / summary_path).write_text(f"# {title}\n\nSynthetic V2.6 summary.\n", encoding="utf-8")
    (repo / evidence_path).write_text(
        "ev_v26_001: Synthetic V2.6 evidence snippet.\n",
        encoding="utf-8",
    )
    return summary_path, evidence_path


def memory_row(
    memory_id: str,
    text: str,
    *,
    summary_path: str | None = None,
    evidence_path: str | None = None,
    raw_refs: list[dict[str, str]] | None = None,
    derived_from: list[str] | None = None,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "memory_id": memory_id,
        "layer": "domain",
        "scope": "domain:v26-source-drilldown",
        "topic": "v26-progressive-source-drilldown",
        "text": text,
        "source": "synthetic",
        "confidence": "high",
        "support_count": 2,
        "derived_from": derived_from or [],
        "evidence_refs": [],
        "raw_refs": raw_refs or [],
        "supersedes": supersedes or [],
        "superseded_by": superseded_by,
    }
    if summary_path:
        row["derived_from"] = [*list(row["derived_from"]), summary_path]
    if evidence_path:
        row["evidence_refs"] = [{"path": evidence_path, "quote_id": "ev_v26_001"}]
    return row


def write_synthetic_archive(repo: Path) -> None:
    (repo / "index").mkdir(parents=True, exist_ok=True)
    (repo / "records").mkdir(parents=True, exist_ok=True)
    (repo / "records/v26-source.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "message:direct",
                        "text": f"Direct source anchor exists. {RAW_SOURCE_SENTINEL}; {SECRET_SENTINEL}",
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "id": "message:multi",
                        "text": f"Multi-hop source anchor exists. {RAW_SOURCE_SENTINEL}; {SECRET_SENTINEL}",
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "id": "message:inactive",
                        "text": f"Inactive source anchor exists. {RAW_SOURCE_SENTINEL}; {SECRET_SENTINEL}",
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    direct_summary, direct_evidence = write_support_files(repo, "direct", "V2.6 Direct Source")
    leaf_summary, leaf_evidence = write_support_files(repo, "leaf", "V2.6 Leaf Support")
    high_summary, high_evidence = write_support_files(repo, "high", "V2.6 High-Level Memory")
    evidence_summary, evidence_evidence = write_support_files(repo, "evidence-only", "V2.6 Evidence Only")
    inactive_summary, inactive_evidence = write_support_files(repo, "inactive", "V2.6 Inactive Source")
    current_summary, current_evidence = write_support_files(repo, "current", "V2.6 Current Replacement")
    unsafe_summary, unsafe_evidence = write_support_files(repo, "unsafe", "V2.6 Unsafe Source")

    rows = [
        memory_row(
            "mem_v26_direct_source",
            DIRECT_TEXT,
            summary_path=direct_summary,
            evidence_path=direct_evidence,
            raw_refs=[{"path": "records/v26-source.jsonl", "anchor": "message:direct"}],
        ),
        memory_row(
            "mem_v26_leaf_source",
            LEAF_TEXT,
            summary_path=leaf_summary,
            evidence_path=leaf_evidence,
            raw_refs=[{"path": "records/v26-source.jsonl", "anchor": "message:multi"}],
        ),
        memory_row(
            "mem_v26_highlevel_source",
            HIGHLEVEL_TEXT,
            summary_path=high_summary,
            evidence_path=high_evidence,
            derived_from=["mem_v26_leaf_source"],
        ),
        memory_row(
            "mem_v26_evidence_only",
            EVIDENCE_ONLY_TEXT,
            summary_path=evidence_summary,
            evidence_path=evidence_evidence,
        ),
        memory_row(
            "mem_v26_inactive_source",
            INACTIVE_TEXT,
            summary_path=inactive_summary,
            evidence_path=inactive_evidence,
            raw_refs=[{"path": "records/v26-source.jsonl", "anchor": "message:inactive"}],
            superseded_by="mem_v26_current_replacement",
        ),
        memory_row(
            "mem_v26_current_replacement",
            "v26current replacement uses active unrelated source wording",
            summary_path=current_summary,
            evidence_path=current_evidence,
            supersedes=["mem_v26_inactive_source"],
        ),
        memory_row(
            "mem_v26_unsafe_source",
            UNSAFE_TEXT,
            summary_path=unsafe_summary,
            evidence_path=unsafe_evidence,
            raw_refs=[{"path": "records/cookie=V26_SHOULD_NOT_RENDER.jsonl", "anchor": "message:unsafe"}],
        ),
    ]
    (repo / "index/memories.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def run_context_package(repo: Path, query: str, depth: str) -> str:
    result = run_command(
        [
            sys.executable,
            str(repo / "tools/search_memory.py"),
            query,
            "--repo",
            str(repo),
            "--limit",
            "5",
            "--depth",
            depth,
            "--context-json",
        ],
        f"search_context_package:{depth}",
        cwd=repo,
    )
    return result.stdout


def load_context_package(raw_package: str) -> tuple[dict[str, Any] | None, bool, str]:
    try:
        payload = json.loads(raw_package)
    except json.JSONDecodeError:
        return None, False, ""
    if not isinstance(payload, dict):
        return None, False, ""
    report_kind = payload.get("report_kind")
    if not isinstance(report_kind, str):
        return None, False, ""
    return payload, report_kind == CONTEXT_REPORT_KIND, report_kind


def supported_hit_for(package: dict[str, Any], memory_id: str) -> dict[str, Any] | None:
    hits = package.get("hits")
    if not isinstance(hits, list):
        return None
    for hit in hits:
        if not isinstance(hit, dict) or hit.get("memory_id") != memory_id:
            continue
        hit_answerability = hit.get("answerability")
        query_support = hit.get("query_support")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
        ):
            return hit
    return None


def source_ref_available(hit: dict[str, Any]) -> bool:
    source_refs = hit.get("source_refs")
    if not isinstance(source_refs, list):
        return False
    return any(
        isinstance(ref, dict)
        and ref.get("status") == "available"
        and ref.get("reason") in {"archive_source_anchor_reachable", "source_map_reachable"}
        and ref.get("unsafe_ref") is False
        for ref in source_refs
    )


def source_ref_blocked(hit: dict[str, Any]) -> bool:
    source_refs = hit.get("source_refs")
    if not isinstance(source_refs, list):
        return False
    return any(
        isinstance(ref, dict)
        and (ref.get("status") == "blocked" or ref.get("unsafe_ref") is True)
        for ref in source_refs
    )


def package_raw_source_default_blocked(package: dict[str, Any]) -> bool:
    privacy = package.get("privacy")
    return isinstance(privacy, dict) and privacy.get("raw_source_content_rendered") is False


def documented_drilldown_decision(raw_package: str, spec: CaseSpec) -> DrilldownDecision:
    package, parse_success, report_kind = load_context_package(raw_package)
    if not parse_success or package is None:
        return DrilldownDecision("abstain", "malformed_or_missing_package", False, report_kind)
    raw_blocked = package_raw_source_default_blocked(package)

    answerability = package.get("answerability")
    if not isinstance(answerability, dict):
        return DrilldownDecision(
            "abstain",
            "malformed_or_missing_package",
            True,
            report_kind,
            raw_source_default_blocked=raw_blocked,
        )
    if answerability.get("reason") == "no_active_current_support":
        return DrilldownDecision(
            "abstain",
            "inactive_source_only",
            True,
            report_kind,
            raw_source_default_blocked=raw_blocked,
        )
    if answerability.get("status") != "supported":
        return DrilldownDecision(
            "abstain",
            "unsupported_package",
            True,
            report_kind,
            raw_source_default_blocked=raw_blocked,
        )

    hit = supported_hit_for(package, spec.expected_memory_id)
    if hit is None:
        return DrilldownDecision(
            "abstain",
            "missing_supported_hit",
            True,
            report_kind,
            raw_source_default_blocked=raw_blocked,
        )

    summary_reachable = bool(hit.get("summary_drill_paths"))
    evidence_reachable = bool(hit.get("evidence_drill_paths"))
    source_reachable = source_ref_available(hit)
    source_blocked = source_ref_blocked(hit)
    multihop_resolved = bool(
        spec.require_multihop
        and "sessions/synthetic/v26-leaf/summary.md" in hit.get("summary_drill_paths", [])
        and "sessions/synthetic/v26-leaf/evidence.md" in hit.get("evidence_drill_paths", [])
        and source_reachable
    )
    if not spec.require_source:
        action = "answer" if summary_reachable and evidence_reachable else "abstain"
        reason = "supported_answer_context" if action == "answer" else "missing_summary_or_evidence"
    elif source_reachable:
        action = "drill"
        reason = "source_ref_reachable"
    elif source_blocked:
        action = "block"
        reason = "unsafe_source_ref_blocked"
    else:
        action = "abstain"
        reason = "evidence_only_original_source_missing"

    return DrilldownDecision(
        action,
        reason,
        True,
        report_kind,
        summary_reachable,
        evidence_reachable,
        source_reachable,
        source_blocked,
        multihop_resolved,
        raw_blocked,
    )


def case_specs(repo: Path) -> list[tuple[CaseSpec, str]]:
    specs = [
        CaseSpec(
            SUPPORTED_ANSWER_CASE,
            "v26direct source anchor durable answer",
            "evidence",
            "answer",
            "mem_v26_direct_source",
        ),
        CaseSpec(
            SUPPORTED_SOURCE_CASE,
            "v26direct source anchor durable answer",
            "source",
            "drill",
            "mem_v26_direct_source",
            require_source=True,
        ),
        CaseSpec(
            MULTIHOP_SOURCE_CASE,
            "v26graph highlevel source drilldown answer",
            "source",
            "drill",
            "mem_v26_highlevel_source",
            require_source=True,
            require_multihop=True,
        ),
        CaseSpec(
            EVIDENCE_ONLY_CASE,
            "v26evidenceonly original source request",
            "source",
            "abstain",
            "mem_v26_evidence_only",
            require_source=True,
        ),
        CaseSpec(
            INACTIVE_SOURCE_CASE,
            "v26retired source only obsolete answer",
            "source",
            "abstain",
            "mem_v26_inactive_source",
            require_source=True,
        ),
        CaseSpec(
            UNSAFE_SOURCE_CASE,
            "v26unsafe source ref blocked answer",
            "source",
            "block",
            "mem_v26_unsafe_source",
            require_source=True,
        ),
    ]
    return [(spec, run_context_package(repo, spec.query, spec.depth)) for spec in specs] + [
        (
            CaseSpec(
                MALFORMED_CASE,
                "",
                "source",
                "abstain",
                require_source=True,
            ),
            "{not-json",
        )
    ]


def run_cases(repo: Path) -> list[CaseResult]:
    return [
        CaseResult(
            spec=spec,
            decision=documented_drilldown_decision(raw_package, spec),
            package_text=raw_package,
        )
        for spec, raw_package in case_specs(repo)
    ]


def safe_rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def count_privacy_leaks(results: list[CaseResult], report: dict[str, object] | None = None) -> int:
    package_fragments: list[str] = []
    for result in results:
        package, parse_success, _report_kind = load_context_package(result.package_text)
        if parse_success and isinstance(package, dict):
            package_fragments.append(
                json.dumps(
                    {key: value for key, value in package.items() if key != "query"},
                    sort_keys=True,
                )
            )
        else:
            package_fragments.append(result.package_text)
    rendered = "".join(package_fragments)
    if report is not None:
        rendered += json.dumps(report, sort_keys=True)
    return sum(1 for marker in LEAK_MARKERS if marker in rendered)


def build_report(results: list[CaseResult]) -> dict[str, object]:
    valid_results = [result for result in results if result.spec.case_id != MALFORMED_CASE]
    parse_success = sum(1 for result in valid_results if result.decision.parse_success)
    correct_decisions = sum(1 for result in results if result.decision.action == result.spec.expected_action)
    source_success_results = [
        result for result in results if result.spec.case_id in {SUPPORTED_SOURCE_CASE, MULTIHOP_SOURCE_CASE}
    ]
    source_available = sum(1 for result in source_success_results if result.decision.source_ref_reachable)
    summary_reachable = sum(1 for result in source_success_results if result.decision.summary_reachable)
    evidence_reachable = sum(1 for result in source_success_results if result.decision.evidence_reachable)
    multihop_resolved = sum(
        1
        for result in results
        if result.spec.case_id == MULTIHOP_SOURCE_CASE and result.decision.multihop_source_resolved
    )
    evidence_only_rejections = sum(
        1
        for result in results
        if result.spec.case_id == EVIDENCE_ONLY_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "evidence_only_original_source_missing"
    )
    inactive_rejections = sum(
        1
        for result in results
        if result.spec.case_id == INACTIVE_SOURCE_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "inactive_source_only"
    )
    unsafe_blocks = sum(
        1
        for result in results
        if result.spec.case_id == UNSAFE_SOURCE_CASE
        and result.decision.action == "block"
        and result.decision.reason == "unsafe_source_ref_blocked"
    )
    source_depth_results = [result for result in valid_results if result.spec.depth == "source"]
    raw_default_blocks = sum(1 for result in source_depth_results if result.decision.raw_source_default_blocked)
    case_outcomes = {result.spec.case_id: result.decision.action for result in results}
    metrics: dict[str, object] = {
        "source_context_package_parse_success_rate": safe_rate(parse_success, len(valid_results)),
        "source_drilldown_decision_accuracy": safe_rate(correct_decisions, len(results)),
        "memory_to_summary_drilldown_rate": safe_rate(summary_reachable, len(source_success_results)),
        "summary_to_evidence_drilldown_rate": safe_rate(evidence_reachable, len(source_success_results)),
        "evidence_to_source_ref_reachability_rate": safe_rate(source_available, len(source_success_results)),
        "memory_graph_multihop_source_resolution_rate": float(multihop_resolved),
        "evidence_only_original_source_rejection_count": evidence_only_rejections,
        "inactive_source_rejection_count": inactive_rejections,
        "unsafe_source_ref_block_count": unsafe_blocks,
        "raw_source_content_default_block_rate": safe_rate(raw_default_blocks, len(source_depth_results)),
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": "progressive_source_drilldown_gate",
        "report_version": 1,
        "status": "passed",
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "command_contract": {
            "depths": ["evidence", "source"],
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "source_reachability_source": CONTEXT_REPORT_KIND,
            "raw_source_preview_requested": False,
        },
        "case_outcomes": case_outcomes,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "context_packages_rendered": False,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "raw_refs_rendered": False,
            "raw_source_content_rendered": False,
            "local_private_paths_rendered": False,
        },
        "claim_boundary": (
            "packaged progressive source drilldown consumption only; not raw transcript "
            "ingestion, private archive quality, LLM answer quality, vector search, "
            "ranking quality, or ontology discovery"
        ),
    }
    metrics["privacy_leak_count"] = count_privacy_leaks(results, report)
    expected_outcomes = {
        SUPPORTED_ANSWER_CASE: "answer",
        SUPPORTED_SOURCE_CASE: "drill",
        MULTIHOP_SOURCE_CASE: "drill",
        EVIDENCE_ONLY_CASE: "abstain",
        INACTIVE_SOURCE_CASE: "abstain",
        UNSAFE_SOURCE_CASE: "block",
        MALFORMED_CASE: "abstain",
    }
    if (
        case_outcomes != expected_outcomes
        or metrics["source_context_package_parse_success_rate"] != 1.0
        or metrics["source_drilldown_decision_accuracy"] != 1.0
        or metrics["memory_to_summary_drilldown_rate"] != 1.0
        or metrics["summary_to_evidence_drilldown_rate"] != 1.0
        or metrics["evidence_to_source_ref_reachability_rate"] != 1.0
        or metrics["memory_graph_multihop_source_resolution_rate"] != 1.0
        or evidence_only_rejections != 1
        or inactive_rejections != 1
        or unsafe_blocks != 1
        or metrics["raw_source_content_default_block_rate"] != 1.0
        or metrics["privacy_leak_count"] != 0
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, object]:
    repo = setup_packaged_archive(root)
    write_synthetic_archive(repo)
    return build_report(run_cases(repo))


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-source-drilldown-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-source-drilldown-", dir=parent))
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
                {
                    "report_kind": "progressive_source_drilldown_gate",
                    "status": "failed",
                    "failures": [failure.to_report()],
                },
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
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
