import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/jsonl_record_boundary_recovery_gate.py").resolve()


class JsonlRecordBoundaryRecoveryGateTests(unittest.TestCase):
    def test_gate_proves_physical_line_recovery_and_fail_closed_boundary(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "jsonl_record_boundary_recovery_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["unicode_separator_inventory_acceptance_rate"], 1.0)
        self.assertEqual(metrics["unicode_separator_materialization_rate"], 1.0)
        self.assertEqual(metrics["physical_record_count_accuracy"], 1.0)
        self.assertEqual(metrics["crlf_compatibility_rate"], 1.0)
        self.assertEqual(metrics["malformed_jsonl_fail_closed_rate"], 1.0)
        self.assertEqual(metrics["stale_replay_recovery_rate"], 1.0)
        self.assertEqual(metrics["valid_case_source_inventory_invalid_count"], 0)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["source_content_rendered"])


if __name__ == "__main__":
    unittest.main()
