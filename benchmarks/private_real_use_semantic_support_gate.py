#!/usr/bin/env python3
"""Run the one-shot aggregate-only private semantic-support admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks import real_use_semantic_support_gate as public_gate


REPORT_KIND = "private_real_use_semantic_support_gate"
MANIFEST_KIND = "private_real_use_semantic_support_manifest"
SEMANTIC_POLICY = public_gate.SEMANTIC_POLICY
MODEL_FINGERPRINT = public_gate.SEMANTIC_MODEL_FINGERPRINT
SEARCH_SCRIPT = REPO_ROOT / "skills/using-my-precious/scripts/search_memory.py"
PRIVATE_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    ),
    re.compile(r"\bmem_[A-Za-z0-9_.:-]+"),
)


class PrivateGateFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class PrivateCase:
    case_key: str
    category: str
    expected_action: str
    query: str
    project_path: str | None = None


@dataclass(frozen=True)
class PrivateManifest:
    archive_repo: Path
    cases: tuple[PrivateCase, ...]


def validate_manifest(value: object) -> PrivateManifest:
    if (
        not isinstance(value, dict)
        or value.get("report_kind") != MANIFEST_KIND
        or value.get("report_version") != 1
    ):
        raise PrivateGateFailure("invalid_private_manifest")
    archive_repo = value.get("archive_repo")
    raw_cases = value.get("cases")
    if (
        not isinstance(archive_repo, str)
        or not archive_repo.strip()
        or not isinstance(raw_cases, list)
        or len(raw_cases) < 2
    ):
        raise PrivateGateFailure("invalid_private_manifest")
    cases: list[PrivateCase] = []
    seen: set[str] = set()
    for item in raw_cases:
        if not isinstance(item, dict):
            raise PrivateGateFailure("invalid_private_manifest")
        case_key = item.get("case_key")
        category = item.get("category")
        expected_action = item.get("expected_action")
        query = item.get("query")
        project_path = item.get("project_path")
        if (
            not isinstance(case_key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", case_key)
            or case_key in seen
            or not isinstance(category, str)
            or not category
            or expected_action not in {"answer", "abstain"}
            or not isinstance(query, str)
            or not query.strip()
            or len(query) > 1000
            or (
                project_path is not None
                and (not isinstance(project_path, str) or not project_path.strip())
            )
        ):
            raise PrivateGateFailure("invalid_private_manifest")
        seen.add(case_key)
        cases.append(
            PrivateCase(
                case_key=case_key,
                category=category,
                expected_action=expected_action,
                query=query,
                project_path=project_path,
            )
        )
    if not any(
        case.category == "goal_preference" and case.expected_action == "answer"
        for case in cases
    ) or not any(case.expected_action == "abstain" for case in cases):
        raise PrivateGateFailure("invalid_private_manifest")
    return PrivateManifest(
        archive_repo=Path(archive_repo).expanduser(),
        cases=tuple(cases),
    )


def ensure_external(path: Path, *, must_exist: bool = False) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise PrivateGateFailure("private_artifact_must_be_outside_repository")
    if must_exist and not resolved.exists():
        raise PrivateGateFailure("required_private_artifact_missing")
    return resolved


def reserve_once(path: Path, manifest_sha256: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "report_kind": "private_real_use_semantic_support_once_ledger",
            "report_version": 1,
            "status": "reserved",
            "manifest_sha256": manifest_sha256,
        },
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise PrivateGateFailure("private_holdout_already_reserved") from exc
    except OSError as exc:
        raise PrivateGateFailure("private_holdout_reservation_failed") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)


def finalize_once(
    path: Path,
    manifest_sha256: str,
    report: dict[str, Any],
) -> None:
    summary = {
        "report_kind": "private_real_use_semantic_support_once_ledger",
        "report_version": 1,
        "status": "completed",
        "manifest_sha256": manifest_sha256,
        "decision": report.get("decision"),
        "report_sha256": hashlib.sha256(
            json.dumps(
                report,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    }
    path.write_text(json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def documented_decision(package: object) -> dict[str, object]:
    if (
        not isinstance(package, dict)
        or package.get("report_kind") != "memory_recall_context_package"
        or not isinstance(package.get("answerability"), dict)
        or package["answerability"].get("status") != "supported"
        or not isinstance(package.get("hits"), list)
    ):
        return {
            "action": "abstain",
            "semantic_supported": False,
            "summary_evidence_resolved": False,
        }
    for hit in package["hits"]:
        if not isinstance(hit, dict):
            continue
        query_support = hit.get("query_support")
        answerability = hit.get("answerability")
        semantic_supported = bool(
            hit.get("active_current")
            and isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and query_support.get("policy") == SEMANTIC_POLICY
            and isinstance(answerability, dict)
            and answerability.get("status") == "supported"
        )
        summary_evidence_resolved = bool(
            hit.get("summary_drill_paths") and hit.get("evidence_drill_paths")
        )
        if semantic_supported and summary_evidence_resolved:
            return {
                "action": "answer",
                "semantic_supported": True,
                "summary_evidence_resolved": True,
            }
    return {
        "action": "abstain",
        "semantic_supported": False,
        "summary_evidence_resolved": False,
    }


def validate_public_holdout(report: object) -> None:
    if (
        not isinstance(report, dict)
        or report.get("report_kind") != public_gate.REPORT_KIND
        or report.get("cohort") != "holdout"
        or report.get("status") != "go"
        or report.get("decision") != "public_holdout_go"
        or report.get("candidate_commit") != public_gate.CANDIDATE_COMMIT
        or report.get("case_file_fingerprint") != public_gate.CASE_FILE_SHA256
        or not isinstance(report.get("provider_identity"), dict)
        or report["provider_identity"].get("model_fingerprint") != MODEL_FINGERPRINT
        or not isinstance(report.get("policy"), dict)
        or report["policy"].get("name") != SEMANTIC_POLICY
        or report["policy"].get("threshold") != public_gate.SEMANTIC_THRESHOLD
        or report["policy"].get("candidate_limit") != 5
    ):
        raise PrivateGateFailure("public_holdout_not_admitted")


def validate_candidate_runtime(path: Path) -> None:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PrivateGateFailure("candidate_runtime_missing") from exc
    if (
        hashlib.sha256(content).hexdigest()
        != public_gate.CANDIDATE_SEARCH_SHA256
        or SEMANTIC_POLICY.encode("utf-8") not in content
    ):
        raise PrivateGateFailure("candidate_runtime_missing")


def run_private_search(
    archive_repo: Path,
    case: PrivateCase,
    semantic_socket: Path,
) -> tuple[dict[str, object] | None, float, int]:
    command = [
        sys.executable,
        str(SEARCH_SCRIPT),
        case.query,
        "--repo",
        str(archive_repo),
        "--depth",
        "evidence",
        "--context-json",
        "--limit",
        "5",
        "--semantic-provider-socket",
        str(semantic_socket),
    ]
    if case.project_path:
        command.extend(["--project-path", case.project_path])
    started = time.perf_counter()
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = time.perf_counter() - started
    if result.returncode:
        return None, elapsed, 0
    try:
        package = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, elapsed, 0
    candidate_count = 0
    if isinstance(package, dict) and isinstance(package.get("semantic_support"), dict):
        value = package["semantic_support"].get("candidate_evaluation_count")
        if isinstance(value, int):
            candidate_count = value
    return package if isinstance(package, dict) else None, elapsed, candidate_count


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def privacy_leak_count(
    report: dict[str, Any],
    manifest: PrivateManifest,
) -> int:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = sum(bool(pattern.search(rendered)) for pattern in PRIVATE_PATTERNS)
    private_values = [
        str(manifest.archive_repo),
        *(
            value
            for case in manifest.cases
            for value in (case.case_key, case.query, case.project_path or "")
            if value
        ),
    ]
    return leaks + sum(value in rendered for value in private_values)


def build_report(
    manifest: PrivateManifest,
    manifest_sha256: str,
    observations: list[tuple[PrivateCase, dict[str, object], float, int]],
) -> dict[str, Any]:
    positives = [
        (case, decision)
        for case, decision, _elapsed, _count in observations
        if case.expected_action == "answer"
    ]
    goal_positives = [
        (case, decision)
        for case, decision in positives
        if case.category == "goal_preference"
    ]
    negatives = [
        (case, decision)
        for case, decision, _elapsed, _count in observations
        if case.expected_action == "abstain"
    ]
    answered = [
        (case, decision)
        for case, decision, _elapsed, _count in observations
        if decision["action"] == "answer"
    ]
    metrics: dict[str, int | float] = {
        "private_real_use_goal_preference_supported_recall": (
            sum(decision["action"] == "answer" for _case, decision in goal_positives)
            / len(goal_positives)
        ),
        "supported_decision_precision": (
            sum(case.expected_action == "answer" for case, _decision in answered)
            / len(answered)
            if answered
            else 0.0
        ),
        "hard_negative_rejection_rate": (
            sum(decision["action"] == "abstain" for _case, decision in negatives)
            / len(negatives)
        ),
        "summary_evidence_resolution_rate": (
            sum(
                decision["action"] == "answer"
                and decision["summary_evidence_resolved"]
                for _case, decision in positives
            )
            / len(positives)
        ),
        "private_warm_query_p95_seconds": round(
            percentile_95([elapsed for _case, _decision, elapsed, _count in observations]),
            6,
        ),
        "semantic_candidate_evaluation_count_per_query": max(
            (count for _case, _decision, _elapsed, count in observations),
            default=0,
        ),
        "false_support_count": sum(
            decision["action"] == "answer" for _case, decision in negatives
        ),
        "free_form_answerability_use_count": 0,
        "privacy_leak_count": 0,
    }
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed",
        "decision": "private_holdout_go",
        "manifest_sha256": manifest_sha256,
        "case_counts": {
            "total": len(observations),
            "positive": len(positives),
            "goal_preference_positive": len(goal_positives),
            "negative": len(negatives),
        },
        "provider_identity": {
            "model_fingerprint": MODEL_FINGERPRINT,
            "network_at_query_time": False,
        },
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "memory_ids_rendered": False,
            "paths_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": (
            "one-shot private top-five weak-hit semantic-support admission only; "
            "not private archive mutation, no-hit retrieval, vector search, "
            "induction quality, or LLM answer quality"
        ),
    }
    metrics["privacy_leak_count"] = privacy_leak_count(report, manifest)
    if (
        any(
            metrics[name] != 1.0
            for name in (
                "private_real_use_goal_preference_supported_recall",
                "supported_decision_precision",
                "hard_negative_rejection_rate",
                "summary_evidence_resolution_rate",
            )
        )
        or metrics["private_warm_query_p95_seconds"] > 2.0
        or metrics["semantic_candidate_evaluation_count_per_query"] > 5
        or any(
            metrics[name] != 0
            for name in (
                "false_support_count",
                "free_form_answerability_use_count",
                "privacy_leak_count",
            )
        )
    ):
        report["status"] = "failed"
        report["decision"] = "no_go"
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-manifest", required=True)
    parser.add_argument("--public-holdout-report", required=True)
    parser.add_argument("--provider-python", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--once-ledger", required=True)
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--work-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ledger: Path | None = None
    manifest_sha256 = ""
    try:
        holdout_path = ensure_external(
            Path(args.public_holdout_report),
            must_exist=True,
        )
        validate_public_holdout(json.loads(holdout_path.read_text(encoding="utf-8")))
        validate_candidate_runtime(SEARCH_SCRIPT)
        manifest_path = ensure_external(
            Path(args.private_manifest),
            must_exist=True,
        )
        ledger = ensure_external(Path(args.once_ledger))
        report_path = ensure_external(Path(args.report_file))
        work_dir = ensure_external(Path(args.work_dir))
        provider_python = Path(args.provider_python).expanduser()
        model_dir = Path(args.model_dir).expanduser()
        if (
            not provider_python.is_file()
            or not model_dir.is_dir()
        ):
            raise PrivateGateFailure("candidate_runtime_missing")
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = validate_manifest(json.loads(manifest_bytes))
        archive_repo = ensure_external(manifest.archive_repo, must_exist=True)
        if not (archive_repo / "index").is_dir() or not (archive_repo / "sessions").is_dir():
            raise PrivateGateFailure("private_archive_invalid")
        reserve_once(ledger, manifest_sha256)
        work_dir.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="v258-private-", dir=work_dir))
        try:
            observations = []
            with public_gate.packaged_provider(
                root,
                provider_python,
                model_dir,
            ) as semantic_socket:
                for case in manifest.cases:
                    package, elapsed, candidate_count = run_private_search(
                        archive_repo,
                        case,
                        semantic_socket,
                    )
                    observations.append(
                        (
                            case,
                            documented_decision(package),
                            elapsed,
                            candidate_count,
                        )
                    )
            report = build_report(manifest, manifest_sha256, observations)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path.chmod(0o600)
        finalize_once(ledger, manifest_sha256, report)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    except (
        PrivateGateFailure,
        OSError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        reason = (
            str(exc)
            if isinstance(exc, PrivateGateFailure)
            else "private_gate_io_or_parse_failure"
        )
        failure = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "decision": "no_go",
            "failure_reason": reason,
            "privacy": {"aggregate_only": True, "paths_rendered": False},
        }
        if ledger is not None and ledger.exists() and manifest_sha256:
            finalize_once(ledger, manifest_sha256, failure)
        print(json.dumps(failure, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
