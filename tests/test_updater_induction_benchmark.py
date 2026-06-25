import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/updater_induction_benchmark.py").resolve()
CASES = Path("benchmarks/cases/updater_induction_synthetic.jsonl").resolve()
QUALITY_GATES = Path("benchmarks/quality-gates/updater_induction_synthetic.json").resolve()
MAX_QUALITY_GATES = Path("benchmarks/quality-gates/updater_induction_synthetic_max.json").resolve()


class UpdaterInductionBenchmarkTests(unittest.TestCase):
    def run_benchmark(self, *extra_args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(CASES),
                    "--work-dir",
                    tmpdir,
                    *extra_args,
                ],
                check=check,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def test_packaged_updater_induction_cases_produce_aggregate_metrics(self):
        result = self.run_benchmark(
            "--fail-under-file",
            str(QUALITY_GATES),
            "--fail-over-file",
            str(MAX_QUALITY_GATES),
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["report_kind"], "updater_induction_benchmark")
        self.assertEqual(payload["cases"], 20)
        self.assertEqual(payload["source_records"], 29)
        self.assertEqual(payload["induction_success_rate"], 1.0)
        self.assertEqual(payload["natural_induction_success_rate"], 1.0)
        self.assertEqual(payload["natural_false_promotion_rate"], 0.0)
        self.assertEqual(payload["cross_project_generalization_rate"], 1.0)
        self.assertEqual(payload["project_scope_precision"], 1.0)
        self.assertEqual(payload["ambiguous_candidate_review_rate"], 1.0)
        self.assertEqual(payload["review_routing_rate"], 1.0)
        self.assertEqual(payload["ephemeral_status_rejection_rate"], 1.0)
        self.assertEqual(payload["hypothetical_rejection_rate"], 1.0)
        self.assertEqual(payload["acknowledgement_only_rejection_rate"], 1.0)
        self.assertEqual(payload["temporary_local_decision_rejection_rate"], 1.0)
        self.assertEqual(payload["generic_rule_rejection_rate"], 1.0)
        self.assertEqual(payload["process_noise_rejection_rate"], 1.0)
        self.assertEqual(payload["layer_assignment_accuracy"], 1.0)
        self.assertEqual(payload["evidence_retention_rate"], 1.0)
        self.assertEqual(payload["source_ref_policy_pass_rate"], 1.0)
        self.assertEqual(payload["lifecycle_link_accuracy"], 1.0)
        self.assertEqual(payload["forced_memory_capture_rate"], 1.0)
        self.assertEqual(payload["privacy_refusal_pass_rate"], 1.0)
        self.assertEqual(payload["privacy_redaction_pass_rate"], 1.0)
        self.assertEqual(payload["privacy_leak_count"], 0)
        self.assertEqual(payload["failed_case_count"], 0)
        self.assertEqual(payload["case_pass_rate"], 1.0)
        self.assertEqual(payload["category_counts"]["automatic_induction"], 2)
        self.assertEqual(payload["category_counts"]["forced_memory"], 1)
        self.assertEqual(payload["category_counts"]["lifecycle"], 1)
        self.assertEqual(payload["category_counts"]["natural_induction"], 6)
        self.assertEqual(payload["category_counts"]["natural_precision"], 8)
        self.assertEqual(payload["category_counts"]["privacy"], 2)
        self.assertTrue(payload["privacy"]["aggregate_only"])
        self.assertFalse(payload["privacy"]["memory_text_rendered"])
        self.assertFalse(payload["privacy"]["source_content_rendered"])
        self.assertFalse(payload["privacy"]["source_paths_rendered"])
        self.assertNotIn("Synthetic induction domain rule", result.stdout)
        self.assertNotIn("syntheticnotreal", result.stdout + result.stderr)

    def test_packaged_updater_induction_quality_gates_cover_required_metrics(self):
        lower = json.loads(QUALITY_GATES.read_text(encoding="utf-8"))
        upper = json.loads(MAX_QUALITY_GATES.read_text(encoding="utf-8"))

        self.assertEqual(lower["cases"], 20)
        self.assertEqual(lower["source_records"], 29)
        self.assertEqual(lower["induction_success_rate"], 1.0)
        self.assertEqual(lower["natural_induction_success_rate"], 1.0)
        self.assertEqual(lower["cross_project_generalization_rate"], 1.0)
        self.assertEqual(lower["project_scope_precision"], 1.0)
        self.assertEqual(lower["ambiguous_candidate_review_rate"], 1.0)
        self.assertEqual(lower["review_routing_rate"], 1.0)
        self.assertEqual(lower["ephemeral_status_rejection_rate"], 1.0)
        self.assertEqual(lower["hypothetical_rejection_rate"], 1.0)
        self.assertEqual(lower["acknowledgement_only_rejection_rate"], 1.0)
        self.assertEqual(lower["temporary_local_decision_rejection_rate"], 1.0)
        self.assertEqual(lower["generic_rule_rejection_rate"], 1.0)
        self.assertEqual(lower["process_noise_rejection_rate"], 1.0)
        self.assertEqual(lower["layer_assignment_accuracy"], 1.0)
        self.assertEqual(lower["evidence_retention_rate"], 1.0)
        self.assertEqual(lower["source_ref_policy_pass_rate"], 1.0)
        self.assertEqual(lower["lifecycle_link_accuracy"], 1.0)
        self.assertEqual(lower["forced_memory_capture_rate"], 1.0)
        self.assertEqual(lower["privacy_refusal_pass_rate"], 1.0)
        self.assertEqual(lower["privacy_redaction_pass_rate"], 1.0)
        self.assertEqual(upper["natural_false_promotion_rate"], 0)
        self.assertEqual(upper["privacy_leak_count"], 0)
        self.assertEqual(upper["failed_case_count"], 0)


if __name__ == "__main__":
    unittest.main()
