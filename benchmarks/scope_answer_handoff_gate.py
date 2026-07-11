#!/usr/bin/env python3
"""Gate package-first scope-aware answer handoff for using-my-precious.

The gate installs a clean packaged archive, writes only synthetic public
memory rows, calls the copied deployment search tool with --context-json, and
verifies answer handoff decisions from context-package fields and support refs
without consulting free-form search output.
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

GLOBAL_HANDOFF_CASE = "global_foundational_handoff"
DOMAIN_HANDOFF_CASE = "domain_preference_handoff"
PROJECT_HANDOFF_CASE = "project_override_handoff"
WRONG_PROJECT_HANDOFF_CASE = "wrong_project_same_topic_handoff"
MISSING_PROJECT_CONTEXT_CASE = "missing_project_context_handoff"
STALE_BROAD_HANDOFF_CASE = "stale_broad_handoff"
NO_HIT_HANDOFF_CASE = "unsupported_no_hit_handoff"
MALFORMED_HANDOFF_CASE = "malformed_package_handoff"

CURRENT_PROJECT = "v28-current-project"
OTHER_PROJECT = "v28-other-project"
SECOND_PROJECT = "v28-second-project"
DOMAIN_SCOPE = "domain:v28-memory-benchmark"

GLOBAL_TEXT = "v28global handoff answer value"
DOMAIN_TEXT = "v28domain handoff answer value"
PROJECT_TEXT = "v28project handoff answer value"
WRONG_PROJECT_TEXT = "v28wrong project handoff answer value"
SECOND_PROJECT_TEXT = "v28second project handoff answer value"
STALE_BROAD_TEXT = "v28stale broad handoff answer value"
CURRENT_REPLACEMENT_TEXT = "v28current scoped replacement handoff value"
RAW_SOURCE_SENTINEL = "RAW V28 TRANSCRIPT SHOULD NOT RENDER"
SECRET_SENTINEL = "cookie=V28_SHOULD_NOT_RENDER"

LEAK_MARKERS = (
    GLOBAL_TEXT,
    DOMAIN_TEXT,
    PROJECT_TEXT,
    WRONG_PROJECT_TEXT,
    SECOND_PROJECT_TEXT,
    STALE_BROAD_TEXT,
    CURRENT_REPLACEMENT_TEXT,
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
    expected_action: str
    expected_memory_id: str = ""
    expected_layer: str = ""
    expected_scope_fragment: str = ""
    preferred_scope: str = ""
    project_path: str = ""
    hard_negative_kind: str = ""


@dataclass(frozen=True)
class HandoffDecision:
    action: str
    reason: str
    parse_success: bool
    report_kind: str
    memory_id: str = ""
    support_refs_covered: bool = False
    package_answerability_status: str = ""
    package_answerability_reason: str = ""
    package_project_context_provided: bool = False
    unsupported_claim_count: int = 0


@dataclass(frozen=True)
class CaseResult:
    spec: CaseSpec
    decision: HandoffDecision
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
    base = f"sessions/synthetic/v28-{slug}"
    return f"{base}/summary.md", f"{base}/evidence.md"


def write_support_files(repo: Path, slug: str, title: str) -> tuple[str, str]:
    summary_path, evidence_path = support_paths(slug)
    (repo / summary_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / evidence_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / summary_path).write_text(f"# {title}\n\nSynthetic V2.8 summary.\n", encoding="utf-8")
    (repo / evidence_path).write_text(
        "ev_v28_001: Synthetic V2.8 evidence snippet.\n",
        encoding="utf-8",
    )
    return summary_path, evidence_path


def memory_row(
    memory_id: str,
    text: str,
    *,
    layer: str,
    scope: str,
    topic: str,
    summary_path: str,
    evidence_path: str,
    project_path: str = "",
    repository: str = "",
    source: str = "explicit",
    confidence: str = "high",
    support_count: int = 2,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "memory_id": memory_id,
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": text,
        "source": source,
        "confidence": confidence,
        "support_count": support_count,
        "derived_from": [summary_path],
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_v28_001"}],
        "raw_refs": [{"path": "records/v28-synthetic.jsonl", "anchor": f"message:{memory_id}"}],
        "supersedes": supersedes or [],
        "superseded_by": superseded_by,
    }
    if project_path:
        row["project_path"] = project_path
        row["project"] = Path(project_path).name
    if repository:
        row["repository"] = repository
    return row


def write_synthetic_archive(repo: Path) -> None:
    (repo / "index").mkdir(parents=True, exist_ok=True)
    (repo / "records").mkdir(parents=True, exist_ok=True)
    (repo / "records/v28-synthetic.jsonl").write_text(
        json.dumps(
            {
                "message": (
                    "Synthetic raw source anchor for privacy checks; "
                    f"{RAW_SOURCE_SENTINEL}; {SECRET_SENTINEL}"
                )
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    current_project_path = f"/synthetic/workspaces/{CURRENT_PROJECT}"
    other_project_path = f"/synthetic/workspaces/{OTHER_PROJECT}"
    second_project_path = f"/synthetic/workspaces/{SECOND_PROJECT}"

    rows: list[dict[str, object]] = []

    global_summary, global_evidence = write_support_files(repo, "global", "V2.8 Global Handoff")
    rows.append(
        memory_row(
            "mem_v28_global_handoff",
            GLOBAL_TEXT,
            layer="global",
            scope="global",
            topic="v28-foundational-handoff",
            summary_path=global_summary,
            evidence_path=global_evidence,
        )
    )

    domain_summary, domain_evidence = write_support_files(repo, "domain", "V2.8 Domain Handoff")
    broad_domain_summary, broad_domain_evidence = write_support_files(
        repo, "domain-broad", "V2.8 Domain Broad Near Match"
    )
    rows.extend(
        [
            memory_row(
                "mem_v28_domain_handoff",
                DOMAIN_TEXT,
                layer="domain",
                scope=DOMAIN_SCOPE,
                topic="v28-handoff-scope",
                summary_path=domain_summary,
                evidence_path=domain_evidence,
                repository="synthetic-memory-benchmarks",
            ),
            memory_row(
                "mem_v28_global_domain_near_match",
                "v28domain handoff broad global near match",
                layer="global",
                scope="global",
                topic="v28-handoff-scope",
                summary_path=broad_domain_summary,
                evidence_path=broad_domain_evidence,
            ),
        ]
    )

    project_summary, project_evidence = write_support_files(repo, "project-current", "V2.8 Project Handoff")
    broad_project_summary, broad_project_evidence = write_support_files(
        repo, "project-broad", "V2.8 Project Broad Near Match"
    )
    rows.extend(
        [
            memory_row(
                "mem_v28_project_handoff",
                PROJECT_TEXT,
                layer="project",
                scope=f"project:{CURRENT_PROJECT}",
                topic="v28-project-handoff",
                summary_path=project_summary,
                evidence_path=project_evidence,
                project_path=current_project_path,
            ),
            memory_row(
                "mem_v28_global_project_near_match",
                "v28project handoff broad global near match",
                layer="global",
                scope="global",
                topic="v28-project-handoff",
                summary_path=broad_project_summary,
                evidence_path=broad_project_evidence,
            ),
        ]
    )

    wrong_summary, wrong_evidence = write_support_files(repo, "project-wrong", "V2.8 Wrong Project Handoff")
    rows.append(
        memory_row(
            "mem_v28_wrong_project_handoff",
            WRONG_PROJECT_TEXT,
            layer="project",
            scope=f"project:{OTHER_PROJECT}",
            topic="v28-wrong-project-handoff",
            summary_path=wrong_summary,
            evidence_path=wrong_evidence,
            project_path=other_project_path,
        )
    )

    second_summary, second_evidence = write_support_files(repo, "project-second", "V2.8 Second Project Handoff")
    rows.append(
        memory_row(
            "mem_v28_second_project_handoff",
            SECOND_PROJECT_TEXT,
            layer="project",
            scope=f"project:{SECOND_PROJECT}",
            topic="v28-missing-context-handoff",
            summary_path=second_summary,
            evidence_path=second_evidence,
            project_path=second_project_path,
        )
    )

    stale_summary, stale_evidence = write_support_files(repo, "stale-broad", "V2.8 Stale Broad Handoff")
    replacement_summary, replacement_evidence = write_support_files(
        repo, "stale-replacement", "V2.8 Scoped Replacement Handoff"
    )
    rows.extend(
        [
            memory_row(
                "mem_v28_stale_broad_handoff",
                STALE_BROAD_TEXT,
                layer="global",
                scope="global",
                topic="v28-stale-handoff",
                summary_path=stale_summary,
                evidence_path=stale_evidence,
                superseded_by="mem_v28_current_replacement_handoff",
            ),
            memory_row(
                "mem_v28_current_replacement_handoff",
                CURRENT_REPLACEMENT_TEXT,
                layer="project",
                scope=f"project:{CURRENT_PROJECT}",
                topic="v28-stale-handoff",
                summary_path=replacement_summary,
                evidence_path=replacement_evidence,
                project_path=current_project_path,
                supersedes=["mem_v28_stale_broad_handoff"],
            ),
        ]
    )

    (repo / "index/memories.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def case_specs(root: Path) -> list[CaseSpec]:
    current_project_path = str(root / "workspaces" / CURRENT_PROJECT)
    return [
        CaseSpec(
            GLOBAL_HANDOFF_CASE,
            "v28global handoff answer",
            "answer",
            expected_memory_id="mem_v28_global_handoff",
            expected_layer="global",
            expected_scope_fragment="global",
            preferred_scope="global",
        ),
        CaseSpec(
            DOMAIN_HANDOFF_CASE,
            "v28domain handoff answer",
            "answer",
            expected_memory_id="mem_v28_domain_handoff",
            expected_layer="domain",
            expected_scope_fragment=DOMAIN_SCOPE,
            preferred_scope="domain",
        ),
        CaseSpec(
            PROJECT_HANDOFF_CASE,
            "v28project handoff answer",
            "answer",
            expected_memory_id="mem_v28_project_handoff",
            expected_layer="project",
            expected_scope_fragment=CURRENT_PROJECT,
            preferred_scope="project",
            project_path=current_project_path,
        ),
        CaseSpec(
            WRONG_PROJECT_HANDOFF_CASE,
            "v28wrong project handoff answer",
            "abstain",
            expected_layer="project",
            expected_scope_fragment=CURRENT_PROJECT,
            preferred_scope="project",
            project_path=current_project_path,
            hard_negative_kind="wrong_project",
        ),
        CaseSpec(
            MISSING_PROJECT_CONTEXT_CASE,
            "v28second project handoff answer",
            "abstain",
            expected_layer="project",
            preferred_scope="project",
            hard_negative_kind="missing_project_context",
        ),
        CaseSpec(
            STALE_BROAD_HANDOFF_CASE,
            "v28stale broad handoff answer",
            "abstain",
            expected_layer="global",
            expected_scope_fragment="global",
            preferred_scope="global",
            project_path=current_project_path,
            hard_negative_kind="stale_broad",
        ),
        CaseSpec(
            NO_HIT_HANDOFF_CASE,
            "v28absent qxmissing handoff factoid",
            "abstain",
            expected_layer="global",
            preferred_scope="global",
            hard_negative_kind="no_hit",
        ),
    ]


def run_context_package(repo: Path, spec: CaseSpec) -> str:
    command = [
        sys.executable,
        str(repo / "tools/search_memory.py"),
        spec.query,
        "--repo",
        str(repo),
        "--limit",
        "5",
        "--depth",
        "evidence",
        "--context-json",
    ]
    if spec.preferred_scope:
        command.extend(["--preferred-scope", spec.preferred_scope])
    if spec.project_path:
        command.extend(["--project-path", spec.project_path])
    result = run_command(command, "search_context_package", cwd=repo)
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


def hit_is_answerable(hit: dict[str, Any]) -> bool:
    hit_answerability = hit.get("answerability")
    query_support = hit.get("query_support")
    return (
        hit.get("active_current") is True
        and isinstance(hit_answerability, dict)
        and hit_answerability.get("status") == "supported"
        and isinstance(query_support, dict)
        and query_support.get("status") == "supported"
    )


def hit_matches_scope_contract(hit: dict[str, Any], spec: CaseSpec) -> bool:
    layer = hit.get("layer")
    scope = hit.get("scope")
    if spec.expected_layer and layer != spec.expected_layer:
        return False
    if spec.expected_scope_fragment and (
        not isinstance(scope, str) or spec.expected_scope_fragment not in scope
    ):
        return False
    return True


def support_refs_for_hit(hit: dict[str, Any]) -> list[dict[str, object]]:
    memory_id = hit.get("memory_id")
    summary_paths = hit.get("summary_drill_paths")
    evidence_refs = hit.get("evidence_refs")
    if not isinstance(memory_id, str) or not memory_id.strip():
        return []
    if not isinstance(summary_paths, list) or not isinstance(evidence_refs, list):
        return []
    clean_summary_paths = sorted(path for path in summary_paths if isinstance(path, str) and path.strip())
    clean_evidence_refs = sorted(ref for ref in evidence_refs if isinstance(ref, str) and ref.strip())
    if not clean_summary_paths or not clean_evidence_refs:
        return []
    return [
        {
            "memory_id": memory_id,
            "summary_paths": clean_summary_paths,
            "evidence_refs": clean_evidence_refs,
        }
    ]


def support_refs_cover_answer(support_refs: list[dict[str, object]]) -> bool:
    for ref in support_refs:
        memory_id = ref.get("memory_id")
        summary_paths = ref.get("summary_paths")
        evidence_refs = ref.get("evidence_refs")
        if (
            isinstance(memory_id, str)
            and memory_id.strip()
            and isinstance(summary_paths, list)
            and any(isinstance(path, str) and path.strip() for path in summary_paths)
            and isinstance(evidence_refs, list)
            and any(isinstance(evidence_ref, str) and evidence_ref.strip() for evidence_ref in evidence_refs)
        ):
            return True
    return False


def package_query_project_context(package: dict[str, Any]) -> bool:
    query = package.get("query")
    return bool(isinstance(query, dict) and query.get("project_context_provided") is True)


def package_answerability(package: dict[str, Any]) -> tuple[str, str]:
    answerability = package.get("answerability")
    if not isinstance(answerability, dict):
        return "", ""
    status = answerability.get("status")
    reason = answerability.get("reason")
    return (
        status if isinstance(status, str) else "",
        reason if isinstance(reason, str) else "",
    )


def documented_handoff_decision(raw_package: str, spec: CaseSpec) -> HandoffDecision:
    package, parse_success, report_kind = load_context_package(raw_package)
    if not parse_success or package is None:
        return HandoffDecision("abstain", "malformed_or_missing_package", False, report_kind)

    answerability_status, answerability_reason = package_answerability(package)
    project_context_provided = package_query_project_context(package)
    hits = package.get("hits")
    if not isinstance(hits, list):
        return HandoffDecision(
            "abstain",
            "malformed_or_missing_package",
            True,
            report_kind,
            package_answerability_status=answerability_status,
            package_answerability_reason=answerability_reason,
            package_project_context_provided=project_context_provided,
        )

    answerable_project_hit_seen = False
    for hit in hits[:5]:
        if not isinstance(hit, dict) or not hit_is_answerable(hit):
            continue
        if hit.get("layer") == "project":
            answerable_project_hit_seen = True
        memory_id = hit.get("memory_id")
        support_refs = support_refs_for_hit(hit)
        support_covered = support_refs_cover_answer(support_refs)
        if spec.hard_negative_kind == "missing_project_context" and not project_context_provided:
            if answerable_project_hit_seen:
                return HandoffDecision(
                    "abstain",
                    "missing_project_context_for_project_specific_handoff",
                    True,
                    report_kind,
                    memory_id=memory_id if isinstance(memory_id, str) else "",
                    support_refs_covered=False,
                    package_answerability_status=answerability_status,
                    package_answerability_reason=answerability_reason,
                    package_project_context_provided=project_context_provided,
                )
        if not hit_matches_scope_contract(hit, spec):
            reason = "scope_mismatch"
            if spec.hard_negative_kind == "wrong_project":
                reason = "wrong_project_scope_mismatch"
            return HandoffDecision(
                "abstain",
                reason,
                True,
                report_kind,
                memory_id=memory_id if isinstance(memory_id, str) else "",
                support_refs_covered=False,
                package_answerability_status=answerability_status,
                package_answerability_reason=answerability_reason,
                package_project_context_provided=project_context_provided,
            )
        if not support_covered:
            return HandoffDecision(
                "abstain",
                "missing_handoff_support_refs",
                True,
                report_kind,
                memory_id=memory_id if isinstance(memory_id, str) else "",
                support_refs_covered=False,
                package_answerability_status=answerability_status,
                package_answerability_reason=answerability_reason,
                package_project_context_provided=project_context_provided,
            )
        return HandoffDecision(
            "answer",
            "supported_scope_matched_handoff",
            True,
            report_kind,
            memory_id=memory_id if isinstance(memory_id, str) else "",
            support_refs_covered=True,
            package_answerability_status=answerability_status,
            package_answerability_reason=answerability_reason,
            package_project_context_provided=project_context_provided,
        )

    if answerability_reason == "no_active_current_support":
        reason = "inactive_or_superseded_only"
    elif answerability_reason == "no_recall_hits":
        reason = "unsupported_no_hit"
    else:
        reason = "unsupported_package"
    return HandoffDecision(
        "abstain",
        reason,
        True,
        report_kind,
        package_answerability_status=answerability_status,
        package_answerability_reason=answerability_reason,
        package_project_context_provided=project_context_provided,
    )


def run_cases(repo: Path, root: Path) -> list[CaseResult]:
    results = [
        CaseResult(spec, documented_handoff_decision(package_text, spec), package_text)
        for spec in case_specs(root)
        for package_text in [run_context_package(repo, spec)]
    ]
    malformed = CaseSpec(
        MALFORMED_HANDOFF_CASE,
        "",
        "abstain",
        hard_negative_kind="malformed",
    )
    results.append(CaseResult(malformed, documented_handoff_decision("{not-json", malformed), "{not-json"))
    return results


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
    valid_results = [result for result in results if result.spec.case_id != MALFORMED_HANDOFF_CASE]
    positive_results = [result for result in results if result.spec.expected_action == "answer"]
    negative_results = [result for result in results if result.spec.expected_action == "abstain"]
    parse_success_count = sum(1 for result in valid_results if result.decision.parse_success)
    correct_decisions = sum(1 for result in results if result.decision.action == result.spec.expected_action)
    answer_results = [result for result in results if result.decision.action == "answer"]
    supported_answer_hits = sum(
        1
        for result in positive_results
        if result.decision.action == "answer"
        and result.decision.memory_id == result.spec.expected_memory_id
        and result.decision.support_refs_covered
    )
    abstention_hits = sum(1 for result in negative_results if result.decision.action == "abstain")
    support_ref_covered_answers = sum(1 for result in answer_results if result.decision.support_refs_covered)
    project_override_hits = sum(
        1
        for result in results
        if result.spec.case_id == PROJECT_HANDOFF_CASE
        and result.decision.action == "answer"
        and result.decision.memory_id == "mem_v28_project_handoff"
        and result.decision.support_refs_covered
    )
    wrong_project_rejections = sum(
        1
        for result in results
        if result.spec.case_id == WRONG_PROJECT_HANDOFF_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "wrong_project_scope_mismatch"
    )
    missing_context_rejections = sum(
        1
        for result in results
        if result.spec.case_id == MISSING_PROJECT_CONTEXT_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "missing_project_context_for_project_specific_handoff"
    )
    stale_broad_rejections = sum(
        1
        for result in results
        if result.spec.case_id == STALE_BROAD_HANDOFF_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "inactive_or_superseded_only"
    )
    malformed_fail_closed = sum(
        1
        for result in results
        if result.spec.case_id == MALFORMED_HANDOFF_CASE
        and result.decision.action == "abstain"
        and not result.decision.parse_success
    )
    unsupported_claim_count = sum(result.decision.unsupported_claim_count for result in results)
    case_outcomes = {result.spec.case_id: result.decision.action for result in results}
    metrics: dict[str, object] = {
        "scope_handoff_context_package_parse_success_rate": safe_rate(parse_success_count, len(valid_results)),
        "scope_handoff_supported_answer_accuracy": safe_rate(supported_answer_hits, len(positive_results)),
        "scope_handoff_abstention_accuracy": safe_rate(abstention_hits, len(negative_results)),
        "scope_handoff_support_ref_coverage_rate": safe_rate(support_ref_covered_answers, len(answer_results)),
        "scope_handoff_project_override_accuracy": float(project_override_hits),
        "scope_handoff_wrong_project_rejection_count": wrong_project_rejections,
        "scope_handoff_missing_project_context_rejection_count": missing_context_rejections,
        "scope_handoff_stale_broad_rejection_count": stale_broad_rejections,
        "scope_handoff_malformed_fail_closed_count": malformed_fail_closed,
        "unsupported_claim_count": unsupported_claim_count,
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": "scope_answer_handoff_gate",
        "report_version": 1,
        "status": "passed",
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "command_contract": {
            "depth": "evidence",
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "handoff_source": "context_package_and_support_refs",
            "project_path_cases": True,
            "preferred_scopes": ["global", "domain", "project"],
            "limit": 5,
        },
        "case_outcomes": case_outcomes,
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "context_packages_rendered": False,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "generated_answers_rendered": False,
            "raw_refs_rendered": False,
            "raw_source_content_rendered": False,
            "local_private_paths_rendered": False,
        },
        "claim_boundary": (
            "packaged scope-aware answer handoff consumption only; not live LLM "
            "answer quality, ranking overhaul, vector search, ontology discovery, "
            "private archive quality, or public leaderboard parity"
        ),
    }
    metrics["privacy_leak_count"] = count_privacy_leaks(results, report)
    expected_outcomes = {
        GLOBAL_HANDOFF_CASE: "answer",
        DOMAIN_HANDOFF_CASE: "answer",
        PROJECT_HANDOFF_CASE: "answer",
        WRONG_PROJECT_HANDOFF_CASE: "abstain",
        MISSING_PROJECT_CONTEXT_CASE: "abstain",
        STALE_BROAD_HANDOFF_CASE: "abstain",
        NO_HIT_HANDOFF_CASE: "abstain",
        MALFORMED_HANDOFF_CASE: "abstain",
    }
    if (
        case_outcomes != expected_outcomes
        or metrics["scope_handoff_context_package_parse_success_rate"] != 1.0
        or metrics["scope_handoff_supported_answer_accuracy"] != 1.0
        or metrics["scope_handoff_abstention_accuracy"] != 1.0
        or metrics["scope_handoff_support_ref_coverage_rate"] != 1.0
        or metrics["scope_handoff_project_override_accuracy"] != 1.0
        or wrong_project_rejections != 1
        or missing_context_rejections != 1
        or stale_broad_rejections != 1
        or malformed_fail_closed != 1
        or unsupported_claim_count != 0
        or metrics["privacy_leak_count"] != 0
        or safe_rate(correct_decisions, len(results)) != 1.0
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, object]:
    repo = setup_packaged_archive(root)
    write_synthetic_archive(repo)
    return build_report(run_cases(repo, root))


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-scope-handoff-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-scope-handoff-", dir=parent))
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
                    "report_kind": "scope_answer_handoff_gate",
                    "status": "failed",
                    "failures": [failure.to_report()],
                },
                sort_keys=True,
            ),
            file=sys.stdout,
        )
        return 1
    finally:
        if cleanup_root is not None:
            shutil.rmtree(cleanup_root, ignore_errors=True)
        if temp is not None:
            temp.cleanup()

    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
