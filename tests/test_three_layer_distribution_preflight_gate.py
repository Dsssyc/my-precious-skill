import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/three_layer_distribution_preflight_gate.py").resolve()


class ThreeLayerDistributionPreflightGateTests(unittest.TestCase):
    def test_gate_reports_deterministic_fail_closed_distribution_metrics(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "three_layer_distribution_preflight_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["determinism"]["runs"], 2)
        self.assertTrue(report["determinism"]["reports_match"])
        self.assertTrue(report["determinism"]["bundle_hash_valid"])
        for metric in (
            "source_installed_parity_detection_accuracy",
            "installed_deployment_parity_detection_accuracy",
            "stale_installed_rejection_accuracy",
            "drifted_deployment_rejection_accuracy",
            "unsafe_deployment_rejection_accuracy",
            "malformed_preflight_rejection_accuracy",
            "preflight_blocks_update_accuracy",
            "current_preflight_allows_update_accuracy",
            "preflight_idempotence_rate",
            "archive_preservation_rate",
            "extra_tool_preservation_rate",
        ):
            self.assertEqual(report["metrics"][metric], 1.0, metric)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["tool_contents_rendered"])
        self.assertFalse(report["privacy"]["archive_text_rendered"])
        self.assertNotIn("PRIVATE_DISTRIBUTION_SENTINEL", result.stdout)
        self.assertNotIn("FAKE_UPDATER_SENTINEL", result.stdout)


if __name__ == "__main__":
    unittest.main()
