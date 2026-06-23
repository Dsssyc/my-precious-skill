import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/e2e_induction_recall_benchmark.py").resolve()
CASES = Path("benchmarks/cases/e2e_induction_recall_synthetic.jsonl").resolve()
QUALITY_GATES = Path("benchmarks/quality-gates/e2e_induction_recall_synthetic.json").resolve()
MAX_QUALITY_GATES = Path("benchmarks/quality-gates/e2e_induction_recall_synthetic_max.json").resolve()


class E2EInductionRecallBenchmarkTests(unittest.TestCase):
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

    def test_packaged_e2e_cases_produce_aggregate_recall_metrics(self):
        result = self.run_benchmark(
            "--fail-under-file",
            str(QUALITY_GATES),
            "--fail-over-file",
            str(MAX_QUALITY_GATES),
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["report_kind"], "e2e_induction_recall_benchmark")
        self.assertEqual(payload["cases"], 6)
        self.assertEqual(payload["source_records"], 12)
        self.assertEqual(payload["recall_cases"], 6)
        self.assertEqual(payload["e2e_memory_recall_at_1"], 1.0)
        self.assertEqual(payload["e2e_memory_recall_at_5"], 1.0)
        self.assertEqual(payload["e2e_layer_assignment_accuracy"], 1.0)
        self.assertEqual(payload["e2e_session_drilldown_rate"], 1.0)
        self.assertEqual(payload["e2e_evidence_reachability_rate"], 1.0)
        self.assertEqual(payload["e2e_source_policy_pass_rate"], 1.0)
        self.assertEqual(payload["e2e_lifecycle_active_suppression_rate"], 1.0)
        self.assertEqual(payload["e2e_forced_memory_recall_rate"], 1.0)
        self.assertEqual(payload["privacy_leak_count"], 0)
        self.assertEqual(payload["failed_case_count"], 0)
        self.assertEqual(payload["case_pass_rate"], 1.0)
        self.assertTrue(payload["privacy"]["aggregate_only"])
        self.assertFalse(payload["privacy"]["memory_text_rendered"])
        self.assertFalse(payload["privacy"]["source_content_rendered"])
        self.assertFalse(payload["privacy"]["source_paths_rendered"])
        self.assertNotIn("Synthetic induction domain rule", result.stdout)
        self.assertNotIn("syntheticnotreal", result.stdout + result.stderr)

    def test_packaged_e2e_quality_gates_cover_required_metrics(self):
        lower = json.loads(QUALITY_GATES.read_text(encoding="utf-8"))
        upper = json.loads(MAX_QUALITY_GATES.read_text(encoding="utf-8"))

        self.assertEqual(lower["cases"], 6)
        self.assertEqual(lower["source_records"], 12)
        self.assertEqual(lower["recall_cases"], 6)
        self.assertEqual(lower["e2e_memory_recall_at_1"], 1.0)
        self.assertEqual(lower["e2e_memory_recall_at_5"], 1.0)
        self.assertEqual(lower["e2e_layer_assignment_accuracy"], 1.0)
        self.assertEqual(lower["e2e_session_drilldown_rate"], 1.0)
        self.assertEqual(lower["e2e_evidence_reachability_rate"], 1.0)
        self.assertEqual(lower["e2e_source_policy_pass_rate"], 1.0)
        self.assertEqual(lower["e2e_lifecycle_active_suppression_rate"], 1.0)
        self.assertEqual(lower["e2e_forced_memory_recall_rate"], 1.0)
        self.assertEqual(upper["privacy_leak_count"], 0)
        self.assertEqual(upper["failed_case_count"], 0)


if __name__ == "__main__":
    unittest.main()
