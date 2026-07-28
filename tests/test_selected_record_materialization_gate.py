import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/selected_record_materialization_gate.py").resolve()


class SelectedRecordMaterializationGateTests(unittest.TestCase):
    def test_gate_proves_bounded_selected_record_materialization(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "selected_record_materialization_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["selected_record_source_read_amplification"], 1.0)
        self.assertEqual(metrics["selected_record_redaction_amplification"], 1.0)
        self.assertLessEqual(metrics["selected_record_json_decode_amplification"], 2.0)
        self.assertEqual(metrics["selected_record_preparation_before_mutation_rate"], 1.0)
        self.assertEqual(metrics["selected_record_raw_payload_retention_count"], 0)
        self.assertEqual(metrics["selected_record_output_parity_rate"], 1.0)
        self.assertEqual(metrics["selected_record_source_anchor_parity_rate"], 1.0)
        self.assertEqual(metrics["selected_record_secret_policy_parity_rate"], 1.0)
        self.assertEqual(metrics["selected_record_mutation_rejection_rate"], 1.0)
        self.assertEqual(metrics["selected_record_mutation_deferral_rate"], 1.0)
        self.assertEqual(metrics["direct_cli_regression_pass_rate"], 1.0)
        self.assertEqual(metrics["v239_throughput_regression_pass_rate"], 1.0)
        self.assertEqual(metrics["v238_single_writer_regression_pass_rate"], 1.0)
        self.assertGreaterEqual(metrics["synthetic_materialization_work_reduction_rate"], 0.60)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["source_content_rendered"])


if __name__ == "__main__":
    unittest.main()
