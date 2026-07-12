import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/scheduled_update_throughput_gate.py").resolve()


class ScheduledUpdateThroughputGateTests(unittest.TestCase):
    def test_gate_proves_single_inventory_single_finalization_and_output_parity(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "scheduled_update_throughput_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["metrics"]["source_inventory_amplification"], 1.0)
        self.assertEqual(report["metrics"]["source_root_rescan_count"], 0)
        self.assertEqual(report["metrics"]["nonselected_record_reparse_count"], 0)
        self.assertEqual(report["metrics"]["target_dispatch_accuracy"], 1.0)
        self.assertEqual(report["metrics"]["successful_run_finalization_count"], 1)
        self.assertEqual(report["metrics"]["failed_run_finalization_count"], 0)
        self.assertEqual(report["metrics"]["output_parity_rate"], 1.0)
        self.assertEqual(report["metrics"]["output_parity_scenario_count"], 4)
        self.assertEqual(report["metrics"]["fail_closed_inventory_rejection_rate"], 1.0)
        self.assertEqual(report["metrics"]["single_writer_regression_pass_rate"], 1.0)
        self.assertGreaterEqual(report["metrics"]["synthetic_redundant_work_reduction_rate"], 0.95)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["source_content_rendered"])


if __name__ == "__main__":
    unittest.main()
