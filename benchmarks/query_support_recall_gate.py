#!/usr/bin/env python3
"""Gate query-support-aware hard-negative recall for context packages."""

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
SEARCH_SCRIPT = REPO_ROOT / "templates/agent-memory-repo/tools/search_memory.py"
CONTEXT_REPORT_KIND = "memory_recall_context_package"

SUPPORTED_CASE = "supported_active_current"
WRONG_SCOPE_CASE = "same_topic_wrong_scope"
WEAK_ACTIVE_CASE = "weak_active_current"
BROAD_LEXICAL_CASE = "broad_lexical_overlap"
INACTIVE_CASE = "inactive_superseded_only"
NO_HIT_CASE = "unsupported_no_hit"
MALFORMED_CASE = "malformed_package"

SUPPORTED_TEXT = "v23alpha supported anchor durable answer value"
WRONG_SCOPE_TEXT = "v23wrongscope nearby active memory from the wrong layer"
WEAK_ACTIVE_TEXT = "v23weakonly generic active memory with support files"
BROAD_LEXICAL_TEXT = "v23ledger policy generic archive overlap without the answer"
INACTIVE_TEXT = "v23retired zeta legacy inactive answer obsolete value"
RAW_SOURCE_SENTINEL = "RAW V23 TRANSCRIPT SHOULD NOT RENDER"
SECRET_SENTINEL = "cookie=V23_SHOULD_NOT_RENDER"

LEAK_MARKERS = (
    SUPPORTED_TEXT,
    WRONG_SCOPE_TEXT,
    WEAK_ACTIVE_TEXT,
    BROAD_LEXICAL_TEXT,
    INACTIVE_TEXT,
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
    expected_supported_ids: frozenset[str]
    expected_layer: str
    preferred_scope: str = ""
    hard_negative_kind: str = ""


@dataclass(frozen=True)
class PackageDecision:
    action: str
    reason: str
    parse_success: bool
    report_kind: str
    answerable_hit_ids: tuple[str, ...]
    weak_hit_count: int
    scope_mixed_answerable_noise_count: int
    scope_mixed_related_hit_count: int


@dataclass(frozen=True)
class CaseResult:
    spec: CaseSpec
    decision: PackageDecision
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


def support_paths(case_slug: str) -> tuple[str, str]:
    base = f"sessions/synthetic/v23-{case_slug}"
    return f"{base}/summary.md", f"{base}/evidence.md"


def write_support_file(path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {title}\n\n"
        "ev_v23_001: Synthetic support file for V2.3 recall gating.\n",
        encoding="utf-8",
    )


def memory_row(
    memory_id: str,
    text: str,
    *,
    layer: str,
    scope: str,
    topic: str,
    summary_path: str,
    evidence_path: str,
    source: str = "explicit",
    confidence: str = "high",
    support_count: int = 2,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "layer": layer,
        "scope": scope,
        "topic": topic,
        "text": text,
        "source": source,
        "confidence": confidence,
        "support_count": support_count,
        "derived_from": [summary_path],
        "evidence_refs": [{"path": evidence_path, "quote_id": "ev_v23_001"}],
        "raw_refs": [{"path": "records/v23-synthetic.jsonl", "anchor": f"message:{memory_id}"}],
        "supersedes": supersedes or [],
        "superseded_by": superseded_by,
    }


def write_synthetic_archive(repo: Path) -> None:
    (repo / "index").mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    specs = [
        (
            "supported",
            memory_row(
                "mem_v23_supported_active",
                SUPPORTED_TEXT,
                layer="global",
                scope="global",
                topic="v23-supported-topic",
                summary_path=support_paths("supported")[0],
                evidence_path=support_paths("supported")[1],
            ),
        ),
        (
            "wrong-scope",
            memory_row(
                "mem_v23_wrong_scope_near_miss",
                WRONG_SCOPE_TEXT,
                layer="global",
                scope="global",
                topic="v23-shared-topic",
                summary_path=support_paths("wrong-scope")[0],
                evidence_path=support_paths("wrong-scope")[1],
            ),
        ),
        (
            "weak-active",
            memory_row(
                "mem_v23_weak_active",
                WEAK_ACTIVE_TEXT,
                layer="domain",
                scope="domain:v23-hard-negative",
                topic="v23-weak-support",
                summary_path=support_paths("weak-active")[0],
                evidence_path=support_paths("weak-active")[1],
            ),
        ),
        (
            "broad-lexical",
            memory_row(
                "mem_v23_broad_lexical",
                BROAD_LEXICAL_TEXT,
                layer="domain",
                scope="domain:v23-hard-negative",
                topic="v23-broad-lexical",
                summary_path=support_paths("broad-lexical")[0],
                evidence_path=support_paths("broad-lexical")[1],
            ),
        ),
        (
            "inactive",
            memory_row(
                "mem_v23_inactive_old",
                INACTIVE_TEXT,
                layer="global",
                scope="global",
                topic="v23-inactive-topic",
                summary_path=support_paths("inactive-old")[0],
                evidence_path=support_paths("inactive-old")[1],
                superseded_by="mem_v23_current_replacement",
            ),
        ),
        (
            "current",
            memory_row(
                "mem_v23_current_replacement",
                "current replacement uses unrelated active wording for lifecycle verification",
                layer="global",
                scope="global",
                topic="v23-current-topic",
                summary_path=support_paths("current")[0],
                evidence_path=support_paths("current")[1],
                supersedes=["mem_v23_inactive_old"],
            ),
        ),
    ]
    for slug, row in specs:
        summary_path, evidence_path = support_paths(slug)
        write_support_file(repo / summary_path, f"V2.3 {slug} summary")
        write_support_file(repo / evidence_path, f"V2.3 {slug} evidence")
        rows.append(row)

    (repo / "records").mkdir(parents=True, exist_ok=True)
    (repo / "records/v23-synthetic.jsonl").write_text(
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
    (repo / "index/memories.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def case_specs() -> list[CaseSpec]:
    return [
        CaseSpec(
            SUPPORTED_CASE,
            "v23alpha supported anchor",
            "answer",
            frozenset({"mem_v23_supported_active"}),
            "global",
            preferred_scope="global",
        ),
        CaseSpec(
            WRONG_SCOPE_CASE,
            "v23wrongscope targetlayer answerdelta",
            "abstain",
            frozenset(),
            "domain",
            preferred_scope="domain",
            hard_negative_kind="wrong_scope",
        ),
        CaseSpec(
            WEAK_ACTIVE_CASE,
            "v23weakonly support coverage marker",
            "abstain",
            frozenset(),
            "domain",
            preferred_scope="domain",
            hard_negative_kind="weak_support",
        ),
        CaseSpec(
            BROAD_LEXICAL_CASE,
            "v23ledger policy exactanswer",
            "abstain",
            frozenset(),
            "domain",
            preferred_scope="domain",
            hard_negative_kind="broad_lexical",
        ),
        CaseSpec(
            INACTIVE_CASE,
            "v23retired zeta legacy inactive answer",
            "abstain",
            frozenset(),
            "global",
            preferred_scope="global",
            hard_negative_kind="inactive",
        ),
        CaseSpec(
            NO_HIT_CASE,
            "v23absent qxmissing factoid",
            "abstain",
            frozenset(),
            "global",
            preferred_scope="global",
            hard_negative_kind="no_hit",
        ),
    ]


def run_context_package(repo: Path, spec: CaseSpec) -> str:
    command = [
        sys.executable,
        str(SEARCH_SCRIPT),
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


def documented_decision(raw_package: str, spec: CaseSpec) -> PackageDecision:
    package, parse_success, report_kind = load_context_package(raw_package)
    if not parse_success or package is None:
        return PackageDecision("abstain", "malformed_or_missing_package", False, report_kind, (), 0, 0, 0)

    hits = package.get("hits")
    if not isinstance(hits, list):
        return PackageDecision("abstain", "malformed_or_missing_package", True, report_kind, (), 0, 0, 0)

    answerable_hit_ids: list[str] = []
    weak_hit_count = 0
    scope_mixed_answerable_noise_count = 0
    scope_mixed_related_hit_count = 0
    for hit in hits[:5]:
        if not isinstance(hit, dict):
            continue
        memory_id = hit.get("memory_id")
        hit_layer = hit.get("layer")
        query_support = hit.get("query_support")
        is_answerable = hit_is_answerable(hit)
        if isinstance(query_support, dict) and query_support.get("status") == "weak":
            weak_hit_count += 1
        if hit_layer and hit_layer != spec.expected_layer:
            scope_mixed_related_hit_count += 1
            if is_answerable:
                scope_mixed_answerable_noise_count += 1
        if is_answerable and isinstance(memory_id, str):
            answerable_hit_ids.append(memory_id)

    answerability = package.get("answerability")
    if not isinstance(answerability, dict):
        return PackageDecision(
            "abstain",
            "malformed_or_missing_package",
            True,
            report_kind,
            tuple(answerable_hit_ids),
            weak_hit_count,
            scope_mixed_answerable_noise_count,
            scope_mixed_related_hit_count,
        )
    if answerability.get("status") == "supported" and answerable_hit_ids:
        return PackageDecision(
            "answer",
            "supported_active_current_package_with_query_support",
            True,
            report_kind,
            tuple(answerable_hit_ids),
            weak_hit_count,
            scope_mixed_answerable_noise_count,
            scope_mixed_related_hit_count,
        )
    if answerability.get("reason") == "no_active_current_support":
        reason = "inactive_superseded_only"
    elif answerability.get("reason") == "no_recall_hits":
        reason = "unsupported_no_hit"
    else:
        reason = "unsupported_package"
    return PackageDecision(
        "abstain",
        reason,
        True,
        report_kind,
        tuple(answerable_hit_ids),
        weak_hit_count,
        scope_mixed_answerable_noise_count,
        scope_mixed_related_hit_count,
    )


def run_cases(repo: Path) -> list[CaseResult]:
    results = [
        CaseResult(spec, documented_decision(package_text, spec), package_text)
        for spec in case_specs()
        for package_text in [run_context_package(repo, spec)]
    ]
    malformed = CaseSpec(
        MALFORMED_CASE,
        "",
        "abstain",
        frozenset(),
        "global",
        hard_negative_kind="malformed",
    )
    results.append(CaseResult(malformed, documented_decision("{not-json", malformed), "{not-json"))
    return results


def safe_rate(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def count_privacy_leaks(results: list[CaseResult], final_report: dict[str, object] | None = None) -> int:
    rendered = "".join(result.package_text for result in results)
    if final_report is not None:
        rendered += json.dumps(final_report, sort_keys=True)
    return sum(1 for marker in LEAK_MARKERS if marker in rendered)


def build_report(results: list[CaseResult]) -> dict[str, object]:
    positive_results = [result for result in results if result.spec.expected_action == "answer"]
    negative_results = [result for result in results if result.spec.expected_action == "abstain"]
    correct_actions = sum(
        1 for result in results if result.decision.action == result.spec.expected_action
    )
    supported_hits_found = sum(
        1
        for result in positive_results
        if any(hit_id in result.spec.expected_supported_ids for hit_id in result.decision.answerable_hit_ids)
    )
    answerable_hit_ids = [
        hit_id
        for result in results
        for hit_id in result.decision.answerable_hit_ids
    ]
    correct_answerable_hit_ids = [
        hit_id
        for result in results
        for hit_id in result.decision.answerable_hit_ids
        if hit_id in result.spec.expected_supported_ids
    ]
    weak_support_rejection_count = sum(
        1
        for result in results
        if result.spec.hard_negative_kind in {"weak_support", "broad_lexical"}
        and result.decision.action == "abstain"
        and result.decision.weak_hit_count > 0
    )
    inactive_lifecycle_rejection_count = sum(
        1
        for result in results
        if result.spec.hard_negative_kind == "inactive"
        and result.decision.action == "abstain"
        and result.decision.reason == "inactive_superseded_only"
    )
    abstention_count = sum(
        1 for result in negative_results if result.decision.action == "abstain"
    )
    valid_package_results = [result for result in results if result.spec.case_id != MALFORMED_CASE]
    parse_success_count = sum(1 for result in valid_package_results if result.decision.parse_success)
    scope_mixed_answerable_noise_count = sum(
        result.decision.scope_mixed_answerable_noise_count for result in results
    )
    scope_mixed_related_hit_count = sum(
        result.decision.scope_mixed_related_hit_count for result in results
    )
    case_outcomes = {result.spec.case_id: result.decision.action for result in results}
    metrics: dict[str, object] = {
        "supported_context_recall_at_5": safe_rate(supported_hits_found, len(positive_results)),
        "answerable_precision_at_5": safe_rate(
            len(correct_answerable_hit_ids),
            len(answerable_hit_ids),
        ),
        "query_support_boundary_pass_rate": safe_rate(correct_actions, len(results)),
        "weak_support_rejection_count": weak_support_rejection_count,
        "scope_mixed_noise_at_5": safe_rate(
            scope_mixed_answerable_noise_count,
            max(1, scope_mixed_answerable_noise_count + len(answerable_hit_ids)),
        ),
        "scope_mixed_related_hit_count_at_5": scope_mixed_related_hit_count,
        "inactive_lifecycle_rejection_count": inactive_lifecycle_rejection_count,
        "runtime_abstention_accuracy": safe_rate(abstention_count, len(negative_results)),
        "context_package_parse_success_rate": safe_rate(parse_success_count, len(valid_package_results)),
        "privacy_leak_count": 0,
    }
    report: dict[str, object] = {
        "report_kind": "query_support_hard_negative_recall_gate",
        "report_version": 1,
        "status": "passed",
        "archive_source": "synthetic_public_archive",
        "free_form_search_used": False,
        "command_contract": {
            "depth": "evidence",
            "context_json": True,
            "answerability_source": CONTEXT_REPORT_KIND,
            "query_support_required": True,
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
            "query-support-aware hard-negative recall diagnostics only; "
            "not live LLM answer quality, vector search, ontology discovery, "
            "public leaderboard parity, or solved long-horizon memory decay"
        ),
    }
    metrics["privacy_leak_count"] = count_privacy_leaks(results, report)
    if (
        metrics["supported_context_recall_at_5"] != 1.0
        or metrics["answerable_precision_at_5"] != 1.0
        or metrics["query_support_boundary_pass_rate"] != 1.0
        or weak_support_rejection_count != 2
        or metrics["scope_mixed_noise_at_5"] != 0.0
        or inactive_lifecycle_rejection_count != 1
        or metrics["runtime_abstention_accuracy"] != 1.0
        or metrics["context_package_parse_success_rate"] != 1.0
        or metrics["privacy_leak_count"] != 0
        or case_outcomes
        != {
            SUPPORTED_CASE: "answer",
            WRONG_SCOPE_CASE: "abstain",
            WEAK_ACTIVE_CASE: "abstain",
            BROAD_LEXICAL_CASE: "abstain",
            INACTIVE_CASE: "abstain",
            NO_HIT_CASE: "abstain",
            MALFORMED_CASE: "abstain",
        }
    ):
        report["status"] = "failed"
    return report


def run_gate(root: Path) -> dict[str, object]:
    repo = root / "agent-memory"
    repo.mkdir(parents=True, exist_ok=True)
    write_synthetic_archive(repo)
    return build_report(run_cases(repo))


def make_work_root(work_dir: str | None) -> tuple[Path, tempfile.TemporaryDirectory[str] | None, Path | None]:
    if work_dir is None:
        temp = tempfile.TemporaryDirectory(prefix="my-precious-query-support-")
        return Path(temp.name), temp, None
    parent = Path(work_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="my-precious-query-support-", dir=parent))
    return root, None, root


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", help="Optional parent directory for generated synthetic artifacts")
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
                    "report_kind": "query_support_hard_negative_recall_gate",
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
