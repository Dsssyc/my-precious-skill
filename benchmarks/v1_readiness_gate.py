#!/usr/bin/env python3
"""Aggregate My Precious v1 readiness evidence without rendering private data.

This gate is intentionally a convergence aid, not a public leaderboard score.
It can either read existing aggregate JSON reports or run the packaged
synthetic gates locally with ``--run-packaged``.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


@dataclass(frozen=True)
class MetricGate:
    metric: str
    comparison: str
    threshold: float


LAYERED_GATES = (
    MetricGate("case_pass_rate", "min", 1.0),
    MetricGate("memory_recall_at_5", "min", 1.0),
    MetricGate("layer_path_success_rate", "min", 1.0),
    MetricGate("drilldown_success_rate", "min", 1.0),
    MetricGate("source_ref_reachability", "min", 1.0),
    MetricGate("source_depth_policy_pass_rate", "min", 1.0),
    MetricGate("raw_preview_redaction_pass_rate", "min", 1.0),
    MetricGate("source_drilldown_privacy_pass_rate", "min", 1.0),
    MetricGate("memory_graph_drilldown_rate", "min", 1.0),
    MetricGate("memory_graph_invalid_edge_suppression_rate", "min", 1.0),
    MetricGate("privacy_leak_count", "max", 0.0),
    MetricGate("failed_case_count", "max", 0.0),
)

UPDATER_GATES = (
    MetricGate("case_pass_rate", "min", 1.0),
    MetricGate("natural_induction_success_rate", "min", 1.0),
    MetricGate("cross_project_generalization_rate", "min", 1.0),
    MetricGate("project_scope_precision", "min", 1.0),
    MetricGate("induction_review_routing_rate", "min", 1.0),
    MetricGate("induction_review_decision_apply_rate", "min", 1.0),
    MetricGate("forced_memory_capture_rate", "min", 1.0),
    MetricGate("privacy_refusal_pass_rate", "min", 1.0),
    MetricGate("privacy_redaction_pass_rate", "min", 1.0),
    MetricGate("privacy_leak_count", "max", 0.0),
    MetricGate("failed_case_count", "max", 0.0),
)

E2E_GATES = (
    MetricGate("case_pass_rate", "min", 1.0),
    MetricGate("natural_induction_success_rate", "min", 1.0),
    MetricGate("e2e_memory_recall_at_5", "min", 1.0),
    MetricGate("e2e_layer_assignment_accuracy", "min", 1.0),
    MetricGate("e2e_session_drilldown_rate", "min", 1.0),
    MetricGate("e2e_evidence_reachability_rate", "min", 1.0),
    MetricGate("e2e_source_policy_pass_rate", "min", 1.0),
    MetricGate("e2e_forced_memory_recall_rate", "min", 1.0),
    MetricGate("privacy_leak_count", "max", 0.0),
    MetricGate("failed_case_count", "max", 0.0),
)

SHADOW_GATES = (
    MetricGate("metrics.memory_recall_at_5", "min", 1.0),
    MetricGate("metrics.privacy_boundary_pass_rate", "min", 1.0),
    MetricGate("metrics.forbidden_output_violations", "max", 0.0),
    MetricGate("metrics.provenance_coverage.score", "min", 1.0),
    MetricGate("metrics.lifecycle_integrity.score", "min", 1.0),
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"unable to read JSON report {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON report {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON report must be an object: {path.name}")
    return payload


def nested_value(payload: dict[str, Any], key: str) -> Any:
    value: Any = payload
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(key)
        value = value[part]
    return value


def numeric_value(payload: dict[str, Any], key: str) -> float | None:
    try:
        value = nested_value(payload, key)
    except KeyError:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return value


def gate_failures(payload: dict[str, Any], gates: tuple[MetricGate, ...]) -> list[dict[str, Any]]:
    failures = []
    for gate in gates:
        value = numeric_value(payload, gate.metric)
        if value is None:
            failures.append(
                {
                    "metric": gate.metric,
                    "comparison": gate.comparison,
                    "threshold": gate.threshold,
                    "reason": "missing_or_non_numeric",
                }
            )
            continue
        failed = value < gate.threshold if gate.comparison == "min" else value > gate.threshold
        if failed:
            failures.append(
                {
                    "metric": gate.metric,
                    "comparison": gate.comparison,
                    "threshold": gate.threshold,
                    "value": value,
                }
            )
    return failures


def selected_metrics(payload: dict[str, Any], gates: tuple[MetricGate, ...]) -> dict[str, float]:
    out = {}
    for gate in gates:
        value = numeric_value(payload, gate.metric)
        if value is not None:
            out[gate.metric] = value
    return out


def assess_report(
    payload: dict[str, Any] | None,
    *,
    expected_kind: str,
    gates: tuple[MetricGate, ...],
    evidence_level: str,
    required: bool,
) -> dict[str, Any]:
    if payload is None:
        return {
            "status": "missing_required" if required else "not_run_optional",
            "evidence_level": evidence_level,
            "required": required,
            "metrics": {},
        }
    failures = []
    kind = payload.get("report_kind")
    if kind is not None and kind != expected_kind:
        failures.append(
            {
                "metric": "report_kind",
                "expected": expected_kind,
                "actual": str(kind),
                "reason": "unexpected_report_kind",
            }
        )
    failures.extend(gate_failures(payload, gates))
    return {
        "status": "passed" if not failures else "failed",
        "evidence_level": evidence_level,
        "required": required,
        "metrics": selected_metrics(payload, gates),
        "failures": failures,
    }


def assess_public_report(payload: dict[str, Any] | None, *, required: bool) -> dict[str, Any]:
    # A public-adapter score is a layered recall report produced from converted
    # public cases. Converter-only output is not enough evidence for recall.
    result = assess_report(
        payload,
        expected_kind="layered_recall_benchmark",
        gates=(
            MetricGate("case_pass_rate", "min", 1.0),
            MetricGate("memory_recall_at_5", "min", 1.0),
            MetricGate("privacy_leak_count", "max", 0.0),
            MetricGate("failed_case_count", "max", 0.0),
        ),
        evidence_level="public_adapter_local",
        required=required,
    )
    result["claim_boundary"] = "adapted local score only; not a public leaderboard claim"
    return result


def assess_shadow_report(payload: dict[str, Any] | None, *, required: bool) -> dict[str, Any]:
    result = assess_report(
        payload,
        expected_kind="real_archive_shadow_evaluation",
        gates=SHADOW_GATES,
        evidence_level="private_real_archive_aggregate",
        required=required,
    )
    if payload is not None:
        privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
        if privacy.get("aggregate_only") is not True:
            result.setdefault("failures", []).append(
                {
                    "metric": "privacy.aggregate_only",
                    "expected": True,
                    "actual": privacy.get("aggregate_only"),
                    "reason": "shadow_report_not_aggregate_only",
                }
            )
            result["status"] = "failed"
    return result


def run_command(command: list[str], *, cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise SystemExit(
            "packaged readiness command failed: "
            + " ".join(command)
            + "\n"
            + result.stderr.strip()
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("packaged readiness command did not emit JSON") from exc
    if not isinstance(payload, dict):
        raise SystemExit("packaged readiness command emitted non-object JSON")
    return payload


def run_packaged_reports(work_dir: Path) -> dict[str, dict[str, Any]]:
    archive = work_dir / "layered-synthetic-archive"
    details = work_dir / "layered-details.jsonl"
    run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "build_synthetic_recall_archive.py"),
            "--repo",
            str(archive),
            "--cases",
            str(SCRIPT_DIR / "cases/layered_recall_synthetic.jsonl"),
            "--include-superseded-distractors",
        ],
        cwd=REPO_ROOT,
    )
    layered = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "layered_recall_benchmark.py"),
            "--repo",
            str(archive),
            "--cases",
            str(SCRIPT_DIR / "cases/layered_recall_synthetic.jsonl"),
            "--search-script",
            str(REPO_ROOT / "templates/agent-memory-repo/tools/search_memory.py"),
            "--details-jsonl",
            str(details),
            "--fail-under-file",
            str(SCRIPT_DIR / "quality-gates/layered_recall_synthetic.json"),
            "--fail-over-file",
            str(SCRIPT_DIR / "quality-gates/layered_recall_synthetic_max.json"),
        ],
        cwd=REPO_ROOT,
    )
    updater = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "updater_induction_benchmark.py"),
            "--cases",
            str(SCRIPT_DIR / "cases/updater_induction_synthetic.jsonl"),
            "--fail-under-file",
            str(SCRIPT_DIR / "quality-gates/updater_induction_synthetic.json"),
            "--fail-over-file",
            str(SCRIPT_DIR / "quality-gates/updater_induction_synthetic_max.json"),
        ],
        cwd=REPO_ROOT,
    )
    e2e = run_command(
        [
            sys.executable,
            str(SCRIPT_DIR / "e2e_induction_recall_benchmark.py"),
            "--cases",
            str(SCRIPT_DIR / "cases/e2e_induction_recall_synthetic.jsonl"),
            "--work-dir",
            str(work_dir / "e2e"),
            "--fail-under-file",
            str(SCRIPT_DIR / "quality-gates/e2e_induction_recall_synthetic.json"),
            "--fail-over-file",
            str(SCRIPT_DIR / "quality-gates/e2e_induction_recall_synthetic_max.json"),
        ],
        cwd=REPO_ROOT,
    )
    return {"layered": layered, "updater": updater, "e2e": e2e}


def build_report(
    *,
    layered: dict[str, Any] | None,
    updater: dict[str, Any] | None,
    e2e: dict[str, Any] | None,
    public: dict[str, Any] | None,
    shadow: dict[str, Any] | None,
    require_public: bool,
    require_shadow: bool,
) -> dict[str, Any]:
    dimensions = {
        "layered_recall": assess_report(
            layered,
            expected_kind="layered_recall_benchmark",
            gates=LAYERED_GATES,
            evidence_level="packaged_synthetic",
            required=True,
        ),
        "automatic_induction": assess_report(
            updater,
            expected_kind="updater_induction_benchmark",
            gates=UPDATER_GATES,
            evidence_level="packaged_synthetic",
            required=True,
        ),
        "e2e_induction_to_recall": assess_report(
            e2e,
            expected_kind="e2e_induction_recall_benchmark",
            gates=E2E_GATES,
            evidence_level="packaged_synthetic",
            required=True,
        ),
        "public_benchmark_adapter": assess_public_report(public, required=require_public),
        "real_archive_shadow_eval": assess_shadow_report(shadow, required=require_shadow),
    }
    required = [dimension for dimension in dimensions.values() if dimension["required"]]
    optional = [dimension for dimension in dimensions.values() if not dimension["required"]]
    required_passed = sum(1 for dimension in required if dimension["status"] == "passed")
    optional_passed = sum(1 for dimension in optional if dimension["status"] == "passed")
    required_ready = required_passed == len(required)
    if not required_ready:
        overall_status = "not_ready"
    elif require_public or require_shadow:
        overall_status = "extended_evidence_ready"
    else:
        overall_status = "core_synthetic_ready"
    return {
        "report_kind": "v1_layered_memory_readiness_gate",
        "report_version": 1,
        "overall_status": overall_status,
        "claim_boundary": (
            "core synthetic gates passed; full v1 target remains unproven"
            if overall_status == "core_synthetic_ready"
            else "extended evidence gates passed; generated-answer and long-horizon governance remain bounded claims"
            if overall_status == "extended_evidence_ready"
            else "one or more required readiness dimensions are missing or failed"
        ),
        "privacy": {
            "aggregate_only": True,
            "private_probe_cases_rendered": False,
            "queries_rendered": False,
            "memory_text_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "scorecard": {
            "required_dimensions": len(required),
            "required_passed": required_passed,
            "optional_dimensions": len(optional),
            "optional_passed": optional_passed,
        },
        "dimensions": dimensions,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layered-report", help="Existing layered recall aggregate JSON report")
    parser.add_argument("--updater-report", help="Existing updater induction aggregate JSON report")
    parser.add_argument("--e2e-report", help="Existing e2e induction-to-recall aggregate JSON report")
    parser.add_argument("--public-report", help="Optional adapted public benchmark layered recall aggregate JSON report")
    parser.add_argument("--shadow-report", help="Optional private real-archive shadow aggregate JSON report")
    parser.add_argument("--require-public", action="store_true", help="Fail when --public-report is absent or failed")
    parser.add_argument("--require-shadow", action="store_true", help="Fail when --shadow-report is absent or failed")
    parser.add_argument("--run-packaged", action="store_true", help="Run packaged synthetic gates instead of reading core reports")
    parser.add_argument("--work-dir", help="Scratch directory for --run-packaged")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.run_packaged:
            work_dir = Path(args.work_dir).expanduser().resolve() if args.work_dir else None
            if work_dir is None:
                temp_dir = tempfile.TemporaryDirectory(prefix="my-precious-v1-readiness-")
                work_dir = Path(temp_dir.name)
            work_dir.mkdir(parents=True, exist_ok=True)
            if any(work_dir.iterdir()):
                raise SystemExit("--work-dir must be empty when using --run-packaged")
            core = run_packaged_reports(work_dir)
            layered = core["layered"]
            updater = core["updater"]
            e2e = core["e2e"]
        else:
            layered = read_json(Path(args.layered_report).expanduser()) if args.layered_report else None
            updater = read_json(Path(args.updater_report).expanduser()) if args.updater_report else None
            e2e = read_json(Path(args.e2e_report).expanduser()) if args.e2e_report else None
        public = read_json(Path(args.public_report).expanduser()) if args.public_report else None
        shadow = read_json(Path(args.shadow_report).expanduser()) if args.shadow_report else None
        report = build_report(
            layered=layered,
            updater=updater,
            e2e=e2e,
            public=public,
            shadow=shadow,
            require_public=args.require_public,
            require_shadow=args.require_shadow,
        )
        print(json.dumps(report, sort_keys=True))
        if report["overall_status"] == "not_ready":
            failed = [
                name
                for name, dimension in report["dimensions"].items()
                if dimension["required"] and dimension["status"] != "passed"
            ]
            print("readiness gate failed: " + ", ".join(failed), file=sys.stderr)
            return 1
        return 0
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
