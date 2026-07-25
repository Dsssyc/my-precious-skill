#!/usr/bin/env python3
"""Gate package-first runtime consumption for using-my-precious.

The gate installs a clean packaged archive, writes only synthetic memory rows,
calls the copied deployment search tool with --depth evidence --context-json,
and verifies the documented answer-or-abstain recipe without consulting
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

SUPPORTED_CASE = "supported_active_current"
UNSUPPORTED_CASE = "unsupported_no_hit"
INACTIVE_CASE = "inactive_superseded_only"
WEAK_ACTIVE_CASE = "weak_active_current"
SAME_TOPIC_NEAR_MISS_CASE = "same_topic_near_miss"
SUBJECT_PREFERENCE_CASE = "source_bound_subject_preference"
EXACT_SUBJECT_PREFERENCE_CASE = "exact_source_bound_subject_preference"
CANDIDATE_ONLY_PREFERENCE_CASE = "candidate_only_subject_preference"
BARE_SUBJECT_PREFERENCE_CASE = "bare_subject_preference"
WRONG_SCOPE_PREFERENCE_CASE = "wrong_scope_subject_preference"
CURRENT_TURN_PREFERENCE_CASE = "current_turn_subject_preference"
MALFORMED_CASE = "malformed_package"

SUPPORTED_QUERY = "packagefirst answerability marker"
UNSUPPORTED_QUERY = "zzabsent qxmissing factoid"
INACTIVE_QUERY = "staleonly zetaomega legacyonly"
WEAK_ACTIVE_QUERY = "weakonly support coverage marker"
SAME_TOPIC_QUERY = "samealpha exactbeta answerdelta"
SUBJECT_PREFERENCE_QUERY = "release note提示词 可直接复制 纯文本"
EXACT_SUBJECT_PREFERENCE_QUERY = "release note 提示词 可直接复制 纯文本"
CANDIDATE_ONLY_PREFERENCE_QUERY = "AuditNimbus preference"
BARE_SUBJECT_PREFERENCE_QUERY = "release note提示词"
WRONG_SCOPE_PREFERENCE_QUERY = "status brief 提示词 可直接复制 纯文本"
CURRENT_TURN_PREFERENCE_QUERY = (
    "For this task, status briefs use lists with compact headings."
)

ACTIVE_MEMORY_TEXT = "packagefirst answerability marker active support"
INACTIVE_MEMORY_TEXT = "staleonly zetaomega legacyonly stale support"
WEAK_ACTIVE_MEMORY_TEXT = "weakonly generic active memory with drill paths"
SAME_TOPIC_MEMORY_TEXT = "samealpha nearby topic active memory"
SUBJECT_PREFERENCE_MEMORY_TEXT = (
    "用户偏好：release note 提示词默认以可直接复制的纯文本形式交付，"
    "完整内容放入单独的 text 代码围栏。"
)
CANDIDATE_ONLY_PREFERENCE_MEMORY_TEXT = (
    "The user prefers AuditNimbus reports to be directly copyable."
)
WRONG_SCOPE_PREFERENCE_MEMORY_TEXT = (
    "用户偏好：status brief 提示词默认以可直接复制的纯文本形式交付。"
)
CURRENT_TURN_PREFERENCE_MEMORY_TEXT = (
    "The user prefers status briefs to use tables with compact headings."
)
RAW_SOURCE_SENTINEL = "RAW TRANSCRIPT SHOULD NOT RENDER"
SECRET_SENTINEL = "cookie=SHOULD_NOT_RENDER"
LEAK_MARKERS = (
    ACTIVE_MEMORY_TEXT,
    INACTIVE_MEMORY_TEXT,
    WEAK_ACTIVE_MEMORY_TEXT,
    SAME_TOPIC_MEMORY_TEXT,
    SUBJECT_PREFERENCE_MEMORY_TEXT,
    CANDIDATE_ONLY_PREFERENCE_MEMORY_TEXT,
    WRONG_SCOPE_PREFERENCE_MEMORY_TEXT,
    CURRENT_TURN_PREFERENCE_MEMORY_TEXT,
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
class RuntimeDecision:
    action: str
    reason: str
    parse_success: bool
    report_kind: str
    delivery_contract: str = "none"


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected_action: str
    decision: RuntimeDecision
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
    search_script = memory_repo / "tools/search_memory.py"
    if not search_script.is_file():
        raise GateFailure("setup_packaged_archive", "search_tool_missing")
    return memory_repo


def write_support_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def memory_row(
    memory_id: str,
    text: str,
    *,
    summary_path: str,
    evidence_path: str,
    topic: str = "using-my-precious-runtime-gate",
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
    layer: str = "domain",
    scope: str = "domain:runtime-gate",
    source: str = "synthetic",
) -> dict[str, object]:
    row: dict[str, object] = {
        "memory_id": memory_id,
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": text,
        "source": source,
        "confidence": "high",
        "support_count": 2,
        "derived_from": [summary_path],
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_runtime_gate_001"}],
        "raw_refs": [{"path": "records/synthetic-runtime.jsonl", "anchor": "message:1"}],
        "supersedes": supersedes or [],
        "superseded_by": superseded_by,
    }
    return row


def write_synthetic_archive(memory_repo: Path) -> None:
    supported_summary = "sessions/synthetic/runtime-supported/summary.md"
    supported_evidence = "sessions/synthetic/runtime-supported/evidence.md"
    inactive_summary = "sessions/synthetic/runtime-inactive/summary.md"
    inactive_evidence = "sessions/synthetic/runtime-inactive/evidence.md"
    current_summary = "sessions/synthetic/runtime-current/summary.md"
    current_evidence = "sessions/synthetic/runtime-current/evidence.md"
    weak_summary = "sessions/synthetic/runtime-weak/summary.md"
    weak_evidence = "sessions/synthetic/runtime-weak/evidence.md"
    same_topic_summary = "sessions/synthetic/runtime-same-topic/summary.md"
    same_topic_evidence = "sessions/synthetic/runtime-same-topic/evidence.md"

    write_support_file(memory_repo / supported_summary, "# Synthetic Runtime Support\n")
    write_support_file(
        memory_repo / supported_evidence,
        "ev_runtime_gate_001: Synthetic evidence for packaged runtime support.\n",
    )
    write_support_file(memory_repo / inactive_summary, "# Synthetic Inactive Support\n")
    write_support_file(
        memory_repo / inactive_evidence,
        "ev_runtime_gate_001: Synthetic evidence for stale runtime support.\n",
    )
    write_support_file(memory_repo / current_summary, "# Synthetic Current Replacement\n")
    write_support_file(
        memory_repo / current_evidence,
        "ev_runtime_gate_001: Synthetic evidence for the current replacement.\n",
    )
    write_support_file(memory_repo / weak_summary, "# Synthetic Weak Active Support\n")
    write_support_file(
        memory_repo / weak_evidence,
        "ev_runtime_gate_001: Synthetic evidence for a weak active near miss.\n",
    )
    write_support_file(memory_repo / same_topic_summary, "# Synthetic Same Topic Near Miss\n")
    write_support_file(
        memory_repo / same_topic_evidence,
        "ev_runtime_gate_001: Synthetic evidence for a same-topic near miss.\n",
    )
    write_support_file(
        memory_repo / "records/synthetic-runtime.jsonl",
        json.dumps(
            {
                "message": (
                    "source anchor is reachable but raw content stays private; "
                    f"{RAW_SOURCE_SENTINEL}; {SECRET_SENTINEL}"
                )
            },
            sort_keys=True,
        )
        + "\n",
    )

    rows = [
        memory_row(
            "runtime_gate_active_current",
            ACTIVE_MEMORY_TEXT,
            summary_path=supported_summary,
            evidence_path=supported_evidence,
        ),
        memory_row(
            "runtime_gate_inactive_old",
            INACTIVE_MEMORY_TEXT,
            summary_path=inactive_summary,
            evidence_path=inactive_evidence,
            superseded_by="runtime_gate_current_replacement",
        ),
        memory_row(
            "runtime_gate_current_replacement",
            "current replacement uses unrelated wording for the stale marker",
            summary_path=current_summary,
            evidence_path=current_evidence,
            supersedes=["runtime_gate_inactive_old"],
        ),
        memory_row(
            "runtime_gate_weak_active",
            WEAK_ACTIVE_MEMORY_TEXT,
            summary_path=weak_summary,
            evidence_path=weak_evidence,
            topic="weak nearby miss",
        ),
        memory_row(
            "runtime_gate_same_topic_near_miss",
            SAME_TOPIC_MEMORY_TEXT,
            summary_path=same_topic_summary,
            evidence_path=same_topic_evidence,
            topic="samealpha",
        ),
        memory_row(
            "runtime_gate_source_bound_preference",
            SUBJECT_PREFERENCE_MEMORY_TEXT,
            summary_path=supported_summary,
            evidence_path=supported_evidence,
            layer="global",
            scope="global",
            source="automatic",
        ),
        memory_row(
            "runtime_gate_candidate_only_preference",
            CANDIDATE_ONLY_PREFERENCE_MEMORY_TEXT,
            summary_path=supported_summary,
            evidence_path=supported_evidence,
            layer="global",
            scope="global",
            source="automatic",
        ),
        memory_row(
            "runtime_gate_wrong_scope_preference",
            WRONG_SCOPE_PREFERENCE_MEMORY_TEXT,
            summary_path=supported_summary,
            evidence_path=supported_evidence,
            layer="project",
            scope="project:runtime-gate",
            source="automatic",
        ),
        memory_row(
            "runtime_gate_current_turn_preference",
            CURRENT_TURN_PREFERENCE_MEMORY_TEXT,
            summary_path=supported_summary,
            evidence_path=supported_evidence,
            layer="global",
            scope="global",
            source="automatic",
        ),
    ]
    index_path = memory_repo / "index/memories.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def run_context_package(memory_repo: Path, query: str) -> str:
    result = run_command(
        [
            sys.executable,
            str(memory_repo / "tools/search_memory.py"),
            query,
            "--repo",
            str(memory_repo),
            "--depth",
            "evidence",
            "--context-json",
        ],
        "search_context_package",
        cwd=memory_repo,
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


def documented_runtime_decision(raw_package: str) -> RuntimeDecision:
    package, parse_success, report_kind = load_context_package(raw_package)
    if not parse_success or package is None:
        return RuntimeDecision("abstain", "malformed_or_missing_package", False, report_kind)

    answerability = package.get("answerability")
    if not isinstance(answerability, dict):
        return RuntimeDecision("abstain", "malformed_or_missing_package", True, report_kind)
    if answerability.get("reason") == "no_active_current_support":
        return RuntimeDecision("abstain", "inactive_superseded_only", True, report_kind)
    if answerability.get("status") != "supported":
        return RuntimeDecision("abstain", "unsupported_package", True, report_kind)

    hits = package.get("hits")
    if not isinstance(hits, list):
        return RuntimeDecision("abstain", "malformed_or_missing_package", True, report_kind)
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_answerability = hit.get("answerability")
        query_support = hit.get("query_support")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and hit.get("summary_drill_paths")
            and hit.get("evidence_drill_paths")
        ):
            candidate_match = hit.get("candidate_match")
            delivery_contract = "none"
            if (
                query_support.get("subject_preference_support") is True
                and query_support.get("preference_memory") is True
                and isinstance(candidate_match, dict)
                and candidate_match.get("focused_preference_intent") is True
                and candidate_match.get("polarity_match") is True
                and candidate_match.get("stable_subject_anchor") is True
            ):
                delivery_contract = "single_text_fence_no_outer_text"
            return RuntimeDecision(
                "answer",
                "supported_active_current_package_with_query_support",
                True,
                report_kind,
                delivery_contract,
            )

    return RuntimeDecision("abstain", "unsupported_package", True, report_kind)


def run_cases(memory_repo: Path) -> list[CaseResult]:
    cases = [
        (SUPPORTED_CASE, "answer", run_context_package(memory_repo, SUPPORTED_QUERY)),
        (UNSUPPORTED_CASE, "abstain", run_context_package(memory_repo, UNSUPPORTED_QUERY)),
        (INACTIVE_CASE, "abstain", run_context_package(memory_repo, INACTIVE_QUERY)),
        (WEAK_ACTIVE_CASE, "abstain", run_context_package(memory_repo, WEAK_ACTIVE_QUERY)),
        (SAME_TOPIC_NEAR_MISS_CASE, "abstain", run_context_package(memory_repo, SAME_TOPIC_QUERY)),
        (
            SUBJECT_PREFERENCE_CASE,
            "answer",
            run_context_package(memory_repo, SUBJECT_PREFERENCE_QUERY),
        ),
        (
            EXACT_SUBJECT_PREFERENCE_CASE,
            "answer",
            run_context_package(memory_repo, EXACT_SUBJECT_PREFERENCE_QUERY),
        ),
        (
            CANDIDATE_ONLY_PREFERENCE_CASE,
            "abstain",
            run_context_package(memory_repo, CANDIDATE_ONLY_PREFERENCE_QUERY),
        ),
        (
            BARE_SUBJECT_PREFERENCE_CASE,
            "abstain",
            run_context_package(memory_repo, BARE_SUBJECT_PREFERENCE_QUERY),
        ),
        (
            WRONG_SCOPE_PREFERENCE_CASE,
            "abstain",
            run_context_package(memory_repo, WRONG_SCOPE_PREFERENCE_QUERY),
        ),
        (
            CURRENT_TURN_PREFERENCE_CASE,
            "abstain",
            run_context_package(memory_repo, CURRENT_TURN_PREFERENCE_QUERY),
        ),
        (MALFORMED_CASE, "abstain", "{not-json"),
    ]
    return [
        CaseResult(
            case_id=case_id,
            expected_action=expected_action,
            decision=documented_runtime_decision(package_text),
            package_text=package_text,
        )
        for case_id, expected_action, package_text in cases
    ]


def safe_rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def preference_support_flags(raw_package: str) -> tuple[bool, bool]:
    package, parse_success, _ = load_context_package(raw_package)
    if not parse_success or package is None:
        return False, False
    hits = package.get("hits")
    if not isinstance(hits, list):
        return False, False
    preference_support = [
        hit.get("query_support")
        for hit in hits
        if isinstance(hit, dict)
        and isinstance(hit.get("query_support"), dict)
        and hit["query_support"].get("preference_memory") is True
    ]
    return (
        any(
            support.get("preference_safety_eligible") is True
            for support in preference_support
        ),
        any(
            support.get("subject_preference_support") is True
            for support in preference_support
        ),
    )


def count_privacy_leaks(results: list[CaseResult], final_report: dict[str, object] | None = None) -> int:
    rendered = "".join(result.package_text for result in results)
    if final_report is not None:
        rendered += json.dumps(final_report, sort_keys=True)
    return sum(1 for marker in LEAK_MARKERS if marker in rendered)


def build_report(results: list[CaseResult]) -> dict[str, object]:
    valid_package_results = [result for result in results if result.case_id != MALFORMED_CASE]
    parse_success_count = sum(1 for result in valid_package_results if result.decision.parse_success)
    supported_results = [result for result in results if result.expected_action == "answer"]
    abstain_results = [result for result in results if result.expected_action == "abstain"]
    supported_correct = sum(
        1 for result in supported_results if result.decision.action == result.expected_action
    )
    abstain_correct = sum(1 for result in abstain_results if result.decision.action == result.expected_action)
    inactive_rejection_count = sum(
        1
        for result in results
        if result.case_id == INACTIVE_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "inactive_superseded_only"
    )
    malformed_fail_closed_count = sum(
        1
        for result in results
        if result.case_id == MALFORMED_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "malformed_or_missing_package"
    )
    support_coverage_case_ids = {SUPPORTED_CASE, WEAK_ACTIVE_CASE, SAME_TOPIC_NEAR_MISS_CASE}
    support_coverage_results = [
        result for result in results if result.case_id in support_coverage_case_ids
    ]
    support_coverage_correct = sum(
        1 for result in support_coverage_results if result.decision.action == result.expected_action
    )
    near_miss_results = [
        result for result in results if result.case_id in {WEAK_ACTIVE_CASE, SAME_TOPIC_NEAR_MISS_CASE}
    ]
    near_miss_abstentions = sum(1 for result in near_miss_results if result.decision.action == "abstain")
    weak_active_rejection_count = near_miss_abstentions
    case_outcomes = {result.case_id: result.decision.action for result in results}
    preference_result = next(
        result for result in results if result.case_id == SUBJECT_PREFERENCE_CASE
    )
    exact_preference_result = next(
        result
        for result in results
        if result.case_id == EXACT_SUBJECT_PREFERENCE_CASE
    )
    candidate_only_rejection_count = sum(
        1
        for result in results
        if result.case_id == CANDIDATE_ONLY_PREFERENCE_CASE
        and result.decision.action == "abstain"
    )
    candidate_only_result = next(
        result
        for result in results
        if result.case_id == CANDIDATE_ONLY_PREFERENCE_CASE
    )
    (
        candidate_only_safety_eligible,
        candidate_only_subject_support,
    ) = preference_support_flags(candidate_only_result.package_text)
    bare_subject_rejection_count = sum(
        1
        for result in results
        if result.case_id == BARE_SUBJECT_PREFERENCE_CASE
        and result.decision.action == "abstain"
    )
    wrong_scope_rejection_count = sum(
        1
        for result in results
        if result.case_id == WRONG_SCOPE_PREFERENCE_CASE
        and result.decision.action == "abstain"
    )
    current_turn_preference_rejection_count = sum(
        1
        for result in results
        if result.case_id == CURRENT_TURN_PREFERENCE_CASE
        and result.decision.action == "abstain"
    )
    delivery_contract_outcomes = {
        SUBJECT_PREFERENCE_CASE: preference_result.decision.delivery_contract,
        EXACT_SUBJECT_PREFERENCE_CASE: (
            exact_preference_result.decision.delivery_contract
        ),
    }
    metrics: dict[str, object] = {
        "runtime_context_package_parse_success_rate": safe_rate(
            parse_success_count,
            len(valid_package_results),
        ),
        "runtime_support_coverage_accuracy": safe_rate(
            support_coverage_correct,
            len(support_coverage_results),
        ),
        "runtime_near_miss_abstention_accuracy": safe_rate(
            near_miss_abstentions,
            len(near_miss_results),
        ),
        "runtime_supported_decision_accuracy": safe_rate(supported_correct, len(supported_results)),
        "runtime_abstention_accuracy": safe_rate(abstain_correct, len(abstain_results)),
        "runtime_subject_preference_supported_accuracy": float(
            preference_result.decision.action == "answer"
        ),
        "runtime_goal_delivery_contract_accuracy": float(
            preference_result.decision.delivery_contract
            == "single_text_fence_no_outer_text"
        ),
        "runtime_exact_preference_delivery_contract_accuracy": float(
            exact_preference_result.decision.action == "answer"
            and exact_preference_result.decision.delivery_contract
            == "single_text_fence_no_outer_text"
        ),
        "runtime_candidate_only_rejection_count": candidate_only_rejection_count,
        "runtime_candidate_only_safety_eligible_count": int(
            candidate_only_safety_eligible
        ),
        "runtime_candidate_only_subject_support_count": int(
            candidate_only_subject_support
        ),
        "runtime_bare_subject_rejection_count": bare_subject_rejection_count,
        "runtime_wrong_scope_rejection_count": wrong_scope_rejection_count,
        "runtime_current_turn_preference_rejection_count": (
            current_turn_preference_rejection_count
        ),
        "runtime_weak_active_rejection_count": weak_active_rejection_count,
        "runtime_inactive_rejection_count": inactive_rejection_count,
        "runtime_malformed_fail_closed_count": malformed_fail_closed_count,
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": "using_my_precious_runtime_consumption_gate",
        "report_version": 2,
        "status": "passed",
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "command_contract": {
            "depth": "evidence",
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "query_support_required": True,
        },
        "case_outcomes": case_outcomes,
        "delivery_contract_outcomes": delivery_contract_outcomes,
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
    }
    metrics["privacy_leak_count"] = count_privacy_leaks(results, report)
    if (
        metrics["runtime_context_package_parse_success_rate"] != 1.0
        or metrics["runtime_support_coverage_accuracy"] != 1.0
        or metrics["runtime_near_miss_abstention_accuracy"] != 1.0
        or metrics["runtime_supported_decision_accuracy"] != 1.0
        or metrics["runtime_abstention_accuracy"] != 1.0
        or metrics["runtime_subject_preference_supported_accuracy"] != 1.0
        or metrics["runtime_goal_delivery_contract_accuracy"] != 1.0
        or metrics["runtime_exact_preference_delivery_contract_accuracy"] != 1.0
        or candidate_only_rejection_count != 1
        or not candidate_only_safety_eligible
        or candidate_only_subject_support
        or bare_subject_rejection_count != 1
        or wrong_scope_rejection_count != 1
        or current_turn_preference_rejection_count != 1
        or weak_active_rejection_count != 2
        or inactive_rejection_count != 1
        or malformed_fail_closed_count != 1
        or metrics["privacy_leak_count"] != 0
        or case_outcomes
        != {
            SUPPORTED_CASE: "answer",
            UNSUPPORTED_CASE: "abstain",
            INACTIVE_CASE: "abstain",
            WEAK_ACTIVE_CASE: "abstain",
            SAME_TOPIC_NEAR_MISS_CASE: "abstain",
            SUBJECT_PREFERENCE_CASE: "answer",
            EXACT_SUBJECT_PREFERENCE_CASE: "answer",
            CANDIDATE_ONLY_PREFERENCE_CASE: "abstain",
            BARE_SUBJECT_PREFERENCE_CASE: "abstain",
            WRONG_SCOPE_PREFERENCE_CASE: "abstain",
            CURRENT_TURN_PREFERENCE_CASE: "abstain",
            MALFORMED_CASE: "abstain",
        }
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, object]:
    memory_repo = setup_packaged_archive(root)
    write_synthetic_archive(memory_repo)
    return build_report(run_cases(memory_repo))


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-runtime-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-runtime-", dir=parent))
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
                    "report_kind": "using_my_precious_runtime_consumption_gate",
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
