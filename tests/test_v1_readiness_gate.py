import json
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import benchmarks.v1_readiness_gate as readiness_gate

SCRIPT = Path("benchmarks/v1_readiness_gate.py").resolve()


class V1ReadinessGateTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return path

    def passing_layered_report(self) -> dict:
        return {
            "report_kind": "layered_recall_benchmark",
            "cases": 45,
            "case_pass_rate": 1.0,
            "memory_recall_at_5": 1.0,
            "layer_path_success_rate": 1.0,
            "drilldown_success_rate": 1.0,
            "source_ref_reachability": 1.0,
            "source_depth_policy_pass_rate": 1.0,
            "raw_preview_redaction_pass_rate": 1.0,
            "raw_preview_authorization_pass_rate": 1.0,
            "source_drilldown_privacy_pass_rate": 1.0,
            "memory_graph_drilldown_rate": 1.0,
            "memory_graph_invalid_edge_suppression_rate": 1.0,
            "privacy_leak_count": 0,
            "failed_case_count": 0,
        }

    def passing_public_report(self) -> dict:
        payload = self.passing_layered_report()
        payload.update(
            {
                "source_benchmarks": {"LongMemEval": 2},
                "case_origins": {"public_benchmark_adapter": 2},
                "cases_sha256": "a" * 64,
                "search_script_sha256": "b" * 64,
            }
        )
        return payload

    def passing_updater_report(self) -> dict:
        return {
            "report_kind": "updater_induction_benchmark",
            "case_pass_rate": 1.0,
            "natural_induction_success_rate": 1.0,
            "cross_project_generalization_rate": 1.0,
            "project_scope_precision": 1.0,
            "induction_review_routing_rate": 1.0,
            "induction_review_decision_apply_rate": 1.0,
            "forced_memory_capture_rate": 1.0,
            "privacy_refusal_pass_rate": 1.0,
            "privacy_redaction_pass_rate": 1.0,
            "privacy_leak_count": 0,
            "failed_case_count": 0,
        }

    def passing_e2e_report(self) -> dict:
        return {
            "report_kind": "e2e_induction_recall_benchmark",
            "case_pass_rate": 1.0,
            "natural_induction_success_rate": 1.0,
            "e2e_memory_recall_at_5": 1.0,
            "e2e_layer_assignment_accuracy": 1.0,
            "e2e_session_drilldown_rate": 1.0,
            "e2e_evidence_reachability_rate": 1.0,
            "e2e_source_policy_pass_rate": 1.0,
            "e2e_forced_memory_recall_rate": 1.0,
            "privacy_leak_count": 0,
            "failed_case_count": 0,
        }

    def passing_source_stream_report(self) -> dict:
        return {
            "report_kind": "source_stream_registry_benchmark",
            "case_pass_rate": 1.0,
            "source_stream_update_rate": 1.0,
            "project_registry_independence_rate": 1.0,
            "metadata_free_source_record_rate": 1.0,
            "archive_scope_assignment_rate": 1.0,
            "source_partition_assignment_rate": 1.0,
            "source_stream_memory_recall_at_5": 1.0,
            "source_stream_session_drilldown_rate": 1.0,
            "source_stream_evidence_reachability_rate": 1.0,
            "source_stream_source_policy_pass_rate": 1.0,
            "privacy_leak_count": 0,
            "failed_case_count": 0,
            "privacy": {
                "aggregate_only": True,
                "case_details_rendered": False,
                "memory_text_rendered": False,
                "source_content_rendered": False,
                "source_paths_rendered": False,
                "raw_refs_rendered": False,
            },
        }

    def passing_answer_report(self) -> dict:
        return {
            "report_kind": "generated_answer_benchmark",
            "case_pass_rate": 1.0,
            "answer_normalized_match_rate": 1.0,
            "abstention_accuracy": 1.0,
            "privacy_leak_count": 0,
            "failed_case_count": 0,
            "missing_answer_count": 0,
            "duplicate_answer_count": 0,
            "unknown_answer_count": 0,
            "source_benchmarks": {"MyPreciousGeneratedAnswerSynthetic": 3},
            "case_origins": {"packaged_generated_answer_fixture": 3},
            "privacy": {
                "aggregate_only": True,
                "queries_rendered": False,
                "generated_answers_rendered": False,
                "reference_answers_rendered": False,
            },
        }

    def passing_shadow_report(self) -> dict:
        return {
            "report_kind": "real_archive_shadow_evaluation",
            "metrics": {
                "memory_recall_at_5": 1.0,
                "memory_precision_at_5": 0.42424242424242425,
                "top_k_noise_at_5": 0.5757575757575757,
                "noise_sources_at_5": {
                    "broad_lexical_match": 35,
                    "inactive_lifecycle": 0,
                    "low_signal_memory_node": 0,
                    "scope_mixed": 3,
                },
                "abstain_pass_rate": 1.0,
                "active_memory_suppression": 1.0,
                "privacy_boundary_pass_rate": 1.0,
                "forbidden_output_violations": 0,
                "provenance_coverage": {"score": 1.0},
                "lifecycle_integrity": {"score": 1.0},
            },
            "privacy": {
                "aggregate_only": True,
                "private_probe_cases_rendered": False,
                "queries_rendered": False,
                "memory_ids_rendered": False,
                "memory_text_rendered": False,
                "source_refs_rendered": False,
                "source_content_rendered": False,
                "source_paths_rendered": False,
                "raw_refs_rendered": False,
            },
        }

    def test_core_synthetic_reports_produce_bounded_readiness_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["report_kind"], "v1_layered_memory_readiness_gate")
            self.assertEqual(payload["overall_status"], "core_synthetic_ready")
            self.assertEqual(
                payload["claim_boundary"],
                "core synthetic gates passed, including explicit source streams; full v1 target remains unproven",
            )
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["private_probe_cases_rendered"])
            self.assertEqual(payload["dimensions"]["layered_recall"]["status"], "passed")
            self.assertEqual(payload["dimensions"]["automatic_induction"]["status"], "passed")
            self.assertEqual(payload["dimensions"]["e2e_induction_to_recall"]["status"], "passed")
            self.assertEqual(payload["dimensions"]["source_stream_registry"]["status"], "passed")
            self.assertEqual(payload["dimensions"]["public_benchmark_adapter"]["status"], "not_run_optional")
            self.assertEqual(payload["dimensions"]["real_archive_shadow_eval"]["status"], "not_run_optional")
            self.assertEqual(payload["dimensions"]["generated_answer_eval"]["status"], "not_run_optional")
            self.assertEqual(payload["scorecard"]["required_dimensions"], 4)
            self.assertEqual(payload["scorecard"]["required_passed"], 4)
            self.assertEqual(payload["scorecard"]["optional_passed"], 0)

    def test_missing_core_source_stream_report_fails_readiness(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["source_stream_registry"]["status"], "missing_required")
            self.assertIn("source_stream_registry", result.stderr)

    def test_source_stream_report_requires_aggregate_privacy_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream_payload = self.passing_source_stream_report()
            source_stream_payload.pop("privacy")
            source_stream = self.write_json(root, "source-stream.json", source_stream_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["source_stream_registry"]["status"], "failed")
            failures = payload["dimensions"]["source_stream_registry"]["failures"]
            self.assertTrue(any(failure["metric"] == "privacy.aggregate_only" for failure in failures))

    def test_source_stream_report_rejects_rendered_source_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream_payload = self.passing_source_stream_report()
            source_stream_payload["privacy"]["source_paths_rendered"] = True
            source_stream = self.write_json(root, "source-stream.json", source_stream_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["source_stream_registry"]["status"], "failed")
            failures = payload["dimensions"]["source_stream_registry"]["failures"]
            self.assertTrue(any(failure["metric"] == "privacy.source_paths_rendered" for failure in failures))

    def test_layered_report_requires_raw_preview_authorization_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered_payload = self.passing_layered_report()
            layered_payload["raw_preview_authorization_pass_rate"] = 0.0
            layered = self.write_json(root, "layered.json", layered_payload)
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["layered_recall"]["status"], "failed")
            self.assertEqual(
                payload["dimensions"]["layered_recall"]["failures"][0]["metric"],
                "raw_preview_authorization_pass_rate",
            )

    def test_required_optional_public_report_makes_missing_public_eval_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--require-public",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["public_benchmark_adapter"]["status"], "missing_required")
            self.assertIn("public_benchmark_adapter", result.stderr)

    def test_required_public_report_rejects_generic_layered_report_without_public_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            generic_public = self.write_json(root, "generic-public.json", self.passing_layered_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--public-report",
                    str(generic_public),
                    "--require-public",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["public_benchmark_adapter"]["status"], "failed")
            failures = payload["dimensions"]["public_benchmark_adapter"]["failures"]
            self.assertTrue(any(failure["metric"] == "source_benchmarks" for failure in failures))

    def test_required_public_report_accepts_layered_report_with_public_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            public = self.write_json(root, "public.json", self.passing_public_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--public-report",
                    str(public),
                    "--require-public",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["overall_status"], "extended_evidence_ready")
            self.assertEqual(payload["dimensions"]["public_benchmark_adapter"]["status"], "passed")

    def test_required_shadow_report_accepts_privacy_safe_shadow_eval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            shadow = self.write_json(root, "shadow.json", self.passing_shadow_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--shadow-report",
                    str(shadow),
                    "--require-shadow",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["overall_status"], "extended_evidence_ready")
            self.assertEqual(payload["dimensions"]["real_archive_shadow_eval"]["status"], "passed")

    def test_required_shadow_report_requires_retrieval_quality_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            shadow_payload = self.passing_shadow_report()
            shadow_payload["metrics"].pop("memory_precision_at_5")
            shadow = self.write_json(root, "shadow.json", shadow_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--shadow-report",
                    str(shadow),
                    "--require-shadow",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["real_archive_shadow_eval"]["status"], "failed")
            failures = payload["dimensions"]["real_archive_shadow_eval"]["failures"]
            self.assertTrue(any(failure["metric"] == "metrics.memory_precision_at_5" for failure in failures))

    def test_required_shadow_report_rejects_retrieval_quality_regression(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            shadow_payload = self.passing_shadow_report()
            shadow_payload["metrics"]["memory_precision_at_5"] = 0.39
            shadow_payload["metrics"]["top_k_noise_at_5"] = 0.61
            shadow_payload["metrics"]["abstain_pass_rate"] = 0.5
            shadow_payload["metrics"]["active_memory_suppression"] = 0.5
            shadow_payload["metrics"]["noise_sources_at_5"]["scope_mixed"] = 4
            shadow_payload["metrics"]["noise_sources_at_5"]["inactive_lifecycle"] = 1
            shadow = self.write_json(root, "shadow.json", shadow_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--shadow-report",
                    str(shadow),
                    "--require-shadow",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            failures = payload["dimensions"]["real_archive_shadow_eval"]["failures"]
            failed_metrics = {failure["metric"] for failure in failures}
            self.assertIn("metrics.memory_precision_at_5", failed_metrics)
            self.assertIn("metrics.top_k_noise_at_5", failed_metrics)
            self.assertIn("metrics.abstain_pass_rate", failed_metrics)
            self.assertIn("metrics.active_memory_suppression", failed_metrics)
            self.assertIn("metrics.noise_sources_at_5.scope_mixed", failed_metrics)
            self.assertIn("metrics.noise_sources_at_5.inactive_lifecycle", failed_metrics)

    def test_required_shadow_report_requires_privacy_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            shadow_payload = self.passing_shadow_report()
            shadow_payload["privacy"].pop("queries_rendered")
            shadow = self.write_json(root, "shadow.json", shadow_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--shadow-report",
                    str(shadow),
                    "--require-shadow",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["real_archive_shadow_eval"]["status"], "failed")
            failures = payload["dimensions"]["real_archive_shadow_eval"]["failures"]
            self.assertTrue(any(failure["metric"] == "privacy.queries_rendered" for failure in failures))

    def test_required_shadow_report_rejects_rendered_source_refs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            shadow_payload = self.passing_shadow_report()
            shadow_payload["privacy"]["source_refs_rendered"] = True
            shadow = self.write_json(root, "shadow.json", shadow_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--shadow-report",
                    str(shadow),
                    "--require-shadow",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["real_archive_shadow_eval"]["status"], "failed")
            failures = payload["dimensions"]["real_archive_shadow_eval"]["failures"]
            self.assertTrue(any(failure["metric"] == "privacy.source_refs_rendered" for failure in failures))

    def test_required_answer_report_makes_missing_answer_eval_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--require-answer",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["generated_answer_eval"]["status"], "missing_required")
            self.assertIn("generated_answer_eval", result.stderr)

    def test_required_answer_report_accepts_passing_generated_answer_eval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            answer = self.write_json(root, "answer.json", self.passing_answer_report())

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--answer-report",
                    str(answer),
                    "--require-answer",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["overall_status"], "extended_evidence_ready")
            self.assertEqual(payload["dimensions"]["generated_answer_eval"]["status"], "passed")
            self.assertEqual(payload["scorecard"]["required_dimensions"], 5)
            self.assertEqual(payload["scorecard"]["required_passed"], 5)
            self.assertFalse(payload["privacy"]["generated_answers_rendered"])
            self.assertFalse(payload["privacy"]["reference_answers_rendered"])

    def test_required_answer_report_rejects_missing_answer_source_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            answer_payload = self.passing_answer_report()
            answer_payload.pop("source_benchmarks")
            answer_payload.pop("case_origins")
            answer = self.write_json(root, "answer.json", answer_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--answer-report",
                    str(answer),
                    "--require-answer",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            failures = payload["dimensions"]["generated_answer_eval"]["failures"]
            self.assertTrue(any(failure["metric"] == "source_benchmarks" for failure in failures))
            self.assertTrue(any(failure["metric"] == "case_origins" for failure in failures))

    def test_required_answer_report_rejects_failed_generated_answer_metric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            layered = self.write_json(root, "layered.json", self.passing_layered_report())
            updater = self.write_json(root, "updater.json", self.passing_updater_report())
            e2e = self.write_json(root, "e2e.json", self.passing_e2e_report())
            source_stream = self.write_json(root, "source-stream.json", self.passing_source_stream_report())
            answer_payload = self.passing_answer_report()
            answer_payload["case_pass_rate"] = 0.5
            answer = self.write_json(root, "answer.json", answer_payload)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--layered-report",
                    str(layered),
                    "--updater-report",
                    str(updater),
                    "--e2e-report",
                    str(e2e),
                    "--source-stream-report",
                    str(source_stream),
                    "--answer-report",
                    str(answer),
                    "--require-answer",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(payload["overall_status"], "not_ready")
            self.assertEqual(payload["dimensions"]["generated_answer_eval"]["status"], "failed")
            failures = payload["dimensions"]["generated_answer_eval"]["failures"]
            self.assertTrue(any(failure["metric"] == "case_pass_rate" for failure in failures))

    def test_run_packaged_require_answer_uses_packaged_answer_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir) / "work"
            packaged_reports = {
                "layered": self.passing_layered_report(),
                "updater": self.passing_updater_report(),
                "e2e": self.passing_e2e_report(),
                "source_stream": self.passing_source_stream_report(),
                "answer": self.passing_answer_report(),
            }
            stdout = io.StringIO()

            with mock.patch.object(readiness_gate, "run_packaged_reports", return_value=packaged_reports) as runner:
                with redirect_stdout(stdout):
                    return_code = readiness_gate.main(
                        [
                            "--run-packaged",
                            "--work-dir",
                            str(work_dir),
                            "--require-answer",
                        ]
                    )

            runner.assert_called_once_with(work_dir.resolve(), include_answer=True)
            self.assertEqual(return_code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["overall_status"], "extended_evidence_ready")
            self.assertEqual(payload["dimensions"]["generated_answer_eval"]["status"], "passed")
            self.assertEqual(payload["scorecard"]["required_dimensions"], 5)


if __name__ == "__main__":
    unittest.main()
