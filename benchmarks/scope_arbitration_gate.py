#!/usr/bin/env python3
"""Gate package-first scope arbitration for using-my-precious.

The gate installs a clean packaged archive, writes only synthetic public
memory rows, calls the copied deployment search tool with --context-json, and
verifies global/domain/project answer-or-abstain decisions without consulting
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

GLOBAL_FALLBACK_CASE = "global_foundational_fallback"
DOMAIN_PREFERENCE_CASE = "domain_preference"
PROJECT_OVERRIDE_CASE = "project_override"
WRONG_PROJECT_CASE = "wrong_project_same_topic"
BROAD_STALE_CASE = "broad_stale_rejected"
MISSING_PROJECT_CONTEXT_CASE = "missing_project_context_ambiguous"
NO_HIT_CASE = "unsupported_no_hit"
MALFORMED_CASE = "malformed_package"

CURRENT_PROJECT = "v27-current-project"
OTHER_PROJECT = "v27-other-project"
SECOND_PROJECT = "v27-second-project"
DOMAIN_SCOPE = "domain:v27-memory-benchmark"

GLOBAL_TEXT = "v27global base answer value"
DOMAIN_TEXT = "v27domain benchmark answer value"
PROJECT_TEXT = "v27project override answer value"
WRONG_PROJECT_TEXT = "v27wrong project answer value"
SECOND_PROJECT_TEXT = "v27second project answer value"
STALE_BROAD_TEXT = "v27stale broad answer value"
CURRENT_REPLACEMENT_TEXT = "v27current replacement answer value"
RAW_SOURCE_SENTINEL = "RAW V27 TRANSCRIPT SHOULD NOT RENDER"
SECRET_SENTINEL = "cookie=V27_SHOULD_NOT_RENDER"

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
    expected_memory_ids: frozenset[str]
    expected_layer: str = ""
    expected_scope_fragment: str = ""
    preferred_scope: str = ""
    project_path: str = ""
    hard_negative_kind: str = ""


@dataclass(frozen=True)
class ScopeDecision:
    action: str
    reason: str
    parse_success: bool
    report_kind: str
    answerable_hit_ids: tuple[str, ...]
    acceptable_hit_ids: tuple[str, ...]
    scope_mismatch_count: int
    project_specific_hit_count: int
    package_project_context_provided: bool
    package_answerability_reason: str


@dataclass(frozen=True)
class CaseResult:
    spec: CaseSpec
    decision: ScopeDecision
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
    base = f"sessions/synthetic/v27-{slug}"
    return f"{base}/summary.md", f"{base}/evidence.md"


def write_support_files(repo: Path, slug: str, title: str) -> tuple[str, str]:
    summary_path, evidence_path = support_paths(slug)
    (repo / summary_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / evidence_path).parent.mkdir(parents=True, exist_ok=True)
    (repo / summary_path).write_text(f"# {title}\n\nSynthetic V2.7 summary.\n", encoding="utf-8")
    (repo / evidence_path).write_text(
        "ev_v27_001: Synthetic V2.7 evidence snippet.\n",
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
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_v27_001"}],
        "raw_refs": [{"path": "records/v27-synthetic.jsonl", "anchor": f"message:{memory_id}"}],
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
    (repo / "records/v27-synthetic.jsonl").write_text(
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

    global_summary, global_evidence = write_support_files(repo, "global", "V2.7 Global Fallback")
    rows.append(
        memory_row(
            "mem_v27_global_foundation",
            GLOBAL_TEXT,
            layer="global",
            scope="global",
            topic="v27-foundational-scope",
            summary_path=global_summary,
            evidence_path=global_evidence,
        )
    )

    domain_summary, domain_evidence = write_support_files(repo, "domain", "V2.7 Domain Preference")
    broad_summary, broad_evidence = write_support_files(repo, "domain-broad", "V2.7 Domain Broad Near Match")
    rows.extend(
        [
            memory_row(
                "mem_v27_domain_benchmark",
                DOMAIN_TEXT,
                layer="domain",
                scope=DOMAIN_SCOPE,
                topic="v27-scope-arbitration",
                summary_path=domain_summary,
                evidence_path=domain_evidence,
                repository="synthetic-memory-benchmarks",
            ),
            memory_row(
                "mem_v27_global_broad_benchmark",
                "v27domain benchmark broad global near match",
                layer="global",
                scope="global",
                topic="v27-scope-arbitration",
                summary_path=broad_summary,
                evidence_path=broad_evidence,
            ),
        ]
    )

    project_summary, project_evidence = write_support_files(repo, "project-current", "V2.7 Project Override")
    project_global_summary, project_global_evidence = write_support_files(
        repo, "project-global", "V2.7 Broader Project Near Match"
    )
    rows.extend(
        [
            memory_row(
                "mem_v27_project_override",
                PROJECT_TEXT,
                layer="project",
                scope=f"project:{CURRENT_PROJECT}",
                topic="v27-override-topic",
                summary_path=project_summary,
                evidence_path=project_evidence,
                project_path=current_project_path,
            ),
            memory_row(
                "mem_v27_global_override_old",
                "v27project override broad global near match",
                layer="global",
                scope="global",
                topic="v27-override-topic",
                summary_path=project_global_summary,
                evidence_path=project_global_evidence,
            ),
        ]
    )

    wrong_summary, wrong_evidence = write_support_files(repo, "project-wrong", "V2.7 Wrong Project")
    rows.append(
        memory_row(
            "mem_v27_wrong_project",
            WRONG_PROJECT_TEXT,
            layer="project",
            scope=f"project:{OTHER_PROJECT}",
            topic="v27-project-only-topic",
            summary_path=wrong_summary,
            evidence_path=wrong_evidence,
            project_path=other_project_path,
        )
    )

    stale_summary, stale_evidence = write_support_files(repo, "stale-broad", "V2.7 Stale Broad")
    replacement_summary, replacement_evidence = write_support_files(
        repo, "stale-replacement", "V2.7 Current Replacement"
    )
    rows.extend(
        [
            memory_row(
                "mem_v27_stale_broad",
                STALE_BROAD_TEXT,
                layer="global",
                scope="global",
                topic="v27-stale-topic",
                summary_path=stale_summary,
                evidence_path=stale_evidence,
                superseded_by="mem_v27_current_replacement",
            ),
            memory_row(
                "mem_v27_current_replacement",
                CURRENT_REPLACEMENT_TEXT,
                layer="project",
                scope=f"project:{CURRENT_PROJECT}",
                topic="v27-stale-topic",
                summary_path=replacement_summary,
                evidence_path=replacement_evidence,
                project_path=current_project_path,
                supersedes=["mem_v27_stale_broad"],
            ),
        ]
    )

    second_summary, second_evidence = write_support_files(repo, "project-second", "V2.7 Second Project")
    rows.append(
        memory_row(
            "mem_v27_second_project",
            SECOND_PROJECT_TEXT,
            layer="project",
            scope=f"project:{SECOND_PROJECT}",
            topic="v27-project-only-topic",
            summary_path=second_summary,
            evidence_path=second_evidence,
            project_path=second_project_path,
        )
    )

    (repo / "index/memories.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def case_specs(root: Path) -> list[CaseSpec]:
    current_project_path = str(root / "workspaces" / CURRENT_PROJECT)
    return [
        CaseSpec(
            GLOBAL_FALLBACK_CASE,
            "v27global base answer",
            "answer",
            frozenset({"mem_v27_global_foundation"}),
            expected_layer="global",
            expected_scope_fragment="global",
            preferred_scope="global",
        ),
        CaseSpec(
            DOMAIN_PREFERENCE_CASE,
            "v27domain benchmark answer",
            "answer",
            frozenset({"mem_v27_domain_benchmark"}),
            expected_layer="domain",
            expected_scope_fragment=DOMAIN_SCOPE,
            preferred_scope="domain",
        ),
        CaseSpec(
            PROJECT_OVERRIDE_CASE,
            "v27project override answer",
            "answer",
            frozenset({"mem_v27_project_override"}),
            expected_layer="project",
            expected_scope_fragment=CURRENT_PROJECT,
            preferred_scope="project",
            project_path=current_project_path,
        ),
        CaseSpec(
            WRONG_PROJECT_CASE,
            "v27wrong project answer",
            "abstain",
            frozenset(),
            expected_layer="project",
            expected_scope_fragment=CURRENT_PROJECT,
            preferred_scope="project",
            project_path=current_project_path,
            hard_negative_kind="wrong_project",
        ),
        CaseSpec(
            BROAD_STALE_CASE,
            "v27stale broad answer",
            "abstain",
            frozenset(),
            expected_layer="global",
            expected_scope_fragment="global",
            preferred_scope="global",
            project_path=current_project_path,
            hard_negative_kind="broad_stale",
        ),
        CaseSpec(
            MISSING_PROJECT_CONTEXT_CASE,
            "v27second project answer",
            "abstain",
            frozenset(),
            expected_layer="project",
            preferred_scope="project",
            hard_negative_kind="missing_project_context",
        ),
        CaseSpec(
            NO_HIT_CASE,
            "v27absent qxmissing factoid",
            "abstain",
            frozenset(),
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
        and bool(hit.get("summary_drill_paths"))
        and bool(hit.get("evidence_drill_paths"))
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


def documented_scope_decision(raw_package: str, spec: CaseSpec) -> ScopeDecision:
    package, parse_success, report_kind = load_context_package(raw_package)
    if not parse_success or package is None:
        return ScopeDecision("abstain", "malformed_or_missing_package", False, report_kind, (), (), 0, 0, False, "")

    hits = package.get("hits")
    if not isinstance(hits, list):
        return ScopeDecision(
            "abstain",
            "malformed_or_missing_package",
            True,
            report_kind,
            (),
            (),
            0,
            0,
            False,
            "",
        )

    query = package.get("query")
    package_project_context_provided = bool(
        isinstance(query, dict) and query.get("project_context_provided") is True
    )
    answerability = package.get("answerability")
    package_answerability_reason = (
        str(answerability.get("reason"))
        if isinstance(answerability, dict) and isinstance(answerability.get("reason"), str)
        else ""
    )

    answerable_hit_ids: list[str] = []
    acceptable_hit_ids: list[str] = []
    scope_mismatch_count = 0
    project_specific_hit_count = 0
    for hit in hits[:5]:
        if not isinstance(hit, dict):
            continue
        memory_id = hit.get("memory_id")
        if hit.get("layer") == "project":
            project_specific_hit_count += 1
        if not hit_is_answerable(hit) or not isinstance(memory_id, str):
            continue
        answerable_hit_ids.append(memory_id)
        if hit_matches_scope_contract(hit, spec):
            acceptable_hit_ids.append(memory_id)
        else:
            scope_mismatch_count += 1

    if spec.hard_negative_kind == "missing_project_context" and not package_project_context_provided:
        if project_specific_hit_count:
            return ScopeDecision(
                "abstain",
                "missing_project_context_for_project_specific_support",
                True,
                report_kind,
                tuple(answerable_hit_ids),
                tuple(acceptable_hit_ids),
                max(scope_mismatch_count, 1),
                project_specific_hit_count,
                package_project_context_provided,
                package_answerability_reason,
            )

    if acceptable_hit_ids:
        return ScopeDecision(
            "answer",
            "supported_scope_matched_package",
            True,
            report_kind,
            tuple(answerable_hit_ids),
            tuple(acceptable_hit_ids),
            scope_mismatch_count,
            project_specific_hit_count,
            package_project_context_provided,
            package_answerability_reason,
        )

    if answerable_hit_ids:
        reason = "scope_mismatch"
        if spec.hard_negative_kind == "wrong_project":
            reason = "wrong_project_scope_mismatch"
        elif spec.hard_negative_kind == "missing_project_context":
            reason = "missing_project_context_for_project_specific_support"
        return ScopeDecision(
            "abstain",
            reason,
            True,
            report_kind,
            tuple(answerable_hit_ids),
            tuple(acceptable_hit_ids),
            max(scope_mismatch_count, 1),
            project_specific_hit_count,
            package_project_context_provided,
            package_answerability_reason,
        )

    if package_answerability_reason == "no_active_current_support":
        reason = "inactive_or_superseded_only"
    elif package_answerability_reason == "no_recall_hits":
        reason = "unsupported_no_hit"
    else:
        reason = "unsupported_package"
    return ScopeDecision(
        "abstain",
        reason,
        True,
        report_kind,
        tuple(answerable_hit_ids),
        tuple(acceptable_hit_ids),
        scope_mismatch_count,
        project_specific_hit_count,
        package_project_context_provided,
        package_answerability_reason,
    )


def run_cases(repo: Path, root: Path) -> list[CaseResult]:
    results = [
        CaseResult(spec, documented_scope_decision(package_text, spec), package_text)
        for spec in case_specs(root)
        for package_text in [run_context_package(repo, spec)]
    ]
    malformed = CaseSpec(
        MALFORMED_CASE,
        "",
        "abstain",
        frozenset(),
        hard_negative_kind="malformed",
    )
    results.append(CaseResult(malformed, documented_scope_decision("{not-json", malformed), "{not-json"))
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
    valid_results = [result for result in results if result.spec.case_id != MALFORMED_CASE]
    parse_success_count = sum(1 for result in valid_results if result.decision.parse_success)
    correct_decisions = sum(1 for result in results if result.decision.action == result.spec.expected_action)
    case_outcomes = {result.spec.case_id: result.decision.action for result in results}

    global_fallback_hits = sum(
        1
        for result in results
        if result.spec.case_id == GLOBAL_FALLBACK_CASE
        and result.decision.action == "answer"
        and "mem_v27_global_foundation" in result.decision.acceptable_hit_ids
    )
    domain_preference_hits = sum(
        1
        for result in results
        if result.spec.case_id == DOMAIN_PREFERENCE_CASE
        and result.decision.action == "answer"
        and "mem_v27_domain_benchmark" in result.decision.acceptable_hit_ids
    )
    project_override_hits = sum(
        1
        for result in results
        if result.spec.case_id == PROJECT_OVERRIDE_CASE
        and result.decision.action == "answer"
        and "mem_v27_project_override" in result.decision.acceptable_hit_ids
    )
    wrong_project_rejections = sum(
        1
        for result in results
        if result.spec.case_id == WRONG_PROJECT_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "wrong_project_scope_mismatch"
    )
    broad_stale_rejections = sum(
        1
        for result in results
        if result.spec.case_id == BROAD_STALE_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "inactive_or_superseded_only"
    )
    missing_project_context_abstentions = sum(
        1
        for result in results
        if result.spec.case_id == MISSING_PROJECT_CONTEXT_CASE
        and result.decision.action == "abstain"
        and result.decision.reason == "missing_project_context_for_project_specific_support"
    )
    scope_mixed_related_hit_count = sum(
        result.decision.scope_mismatch_count for result in results
    )

    metrics: dict[str, object] = {
        "scope_context_package_parse_success_rate": safe_rate(parse_success_count, len(valid_results)),
        "global_fallback_answerability_rate": float(global_fallback_hits),
        "domain_preference_accuracy": float(domain_preference_hits),
        "project_override_accuracy": float(project_override_hits),
        "wrong_project_rejection_count": wrong_project_rejections,
        "broad_stale_rejection_count": broad_stale_rejections,
        "missing_project_context_abstention_accuracy": float(missing_project_context_abstentions),
        "scope_arbitration_decision_accuracy": safe_rate(correct_decisions, len(results)),
        "scope_mixed_related_hit_count_at_5": scope_mixed_related_hit_count,
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": "scope_arbitration_gate",
        "report_version": 1,
        "status": "passed",
        "package_source": "clean_packaged_deployment_repo",
        "free_form_search_used": False,
        "command_contract": {
            "depth": "evidence",
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "scope_contract_source": CONTEXT_REPORT_KIND,
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
            "raw_refs_rendered": False,
            "raw_source_content_rendered": False,
            "local_private_paths_rendered": False,
        },
        "claim_boundary": (
            "packaged scope arbitration and override decision behavior only; "
            "not LLM answer quality, vector search, ontology discovery, "
            "ranking overhaul, private archive quality, or public leaderboard parity"
        ),
    }
    metrics["privacy_leak_count"] = count_privacy_leaks(results, report)
    expected_outcomes = {
        GLOBAL_FALLBACK_CASE: "answer",
        DOMAIN_PREFERENCE_CASE: "answer",
        PROJECT_OVERRIDE_CASE: "answer",
        WRONG_PROJECT_CASE: "abstain",
        BROAD_STALE_CASE: "abstain",
        MISSING_PROJECT_CONTEXT_CASE: "abstain",
        NO_HIT_CASE: "abstain",
        MALFORMED_CASE: "abstain",
    }
    if (
        case_outcomes != expected_outcomes
        or metrics["scope_context_package_parse_success_rate"] != 1.0
        or metrics["global_fallback_answerability_rate"] != 1.0
        or metrics["domain_preference_accuracy"] != 1.0
        or metrics["project_override_accuracy"] != 1.0
        or wrong_project_rejections != 1
        or broad_stale_rejections != 1
        or metrics["missing_project_context_abstention_accuracy"] != 1.0
        or metrics["scope_arbitration_decision_accuracy"] != 1.0
        or metrics["scope_mixed_related_hit_count_at_5"] < 1
        or metrics["privacy_leak_count"] != 0
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, object]:
    repo = setup_packaged_archive(root)
    write_synthetic_archive(repo)
    return build_report(run_cases(repo, root))


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-scope-arbitration-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-scope-arbitration-", dir=parent))
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
                    "report_kind": "scope_arbitration_gate",
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
