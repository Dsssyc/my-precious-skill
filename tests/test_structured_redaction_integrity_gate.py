import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/structured_redaction_integrity_gate.py").resolve()


class StructuredRedactionIntegrityGateTests(unittest.TestCase):
    def test_gate_proves_structure_preserving_redaction(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "structured_redaction_integrity_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["structured_source_parse_success_rate"], 1.0)
        self.assertEqual(metrics["structured_redaction_parse_success_rate"], 1.0)
        self.assertEqual(metrics["cookie_redaction_success_rate"], 1.0)
        self.assertEqual(metrics["jsonl_boundary_preservation_rate"], 1.0)
        self.assertEqual(metrics["selected_record_materialization_success_rate"], 1.0)
        self.assertEqual(metrics["malformed_source_fail_closed_rate"], 1.0)
        self.assertEqual(metrics["inventory_rejection_boundary_pass_rate"], 1.0)
        self.assertEqual(metrics["source_inventory_invalid_count"], 0)
        self.assertEqual(metrics["expected_source_inventory_rejection_count"], 3)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["source_content_rendered"])


if __name__ == "__main__":
    unittest.main()
