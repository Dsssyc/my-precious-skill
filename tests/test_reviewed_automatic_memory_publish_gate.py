import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/reviewed_automatic_memory_publish_gate.py").resolve()


class ReviewedAutomaticMemoryPublishGateTests(unittest.TestCase):
    def test_gate_proves_reviewed_publish_and_fail_closed_cases(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "reviewed_automatic_memory_publish_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["default_mode_automatic_memory_rejection_rate"], 1.0)
        self.assertEqual(metrics["reviewed_mode_safe_dry_run_pass_rate"], 1.0)
        self.assertEqual(metrics["reviewed_mode_live_push_success_rate"], 1.0)
        self.assertEqual(metrics["reviewed_mode_exact_stage_scope_rate"], 1.0)
        self.assertEqual(metrics.get("reviewed_mode_exact_add_pathspec_rate"), 1.0)
        self.assertEqual(metrics["reviewed_mode_unsafe_rejection_accuracy"], 1.0)
        self.assertEqual(metrics["reviewed_mode_index_parity_rejection_count"], 1)
        self.assertEqual(metrics["reviewed_mode_lifecycle_rejection_count"], 1)
        self.assertEqual(metrics["reviewed_mode_content_noise_rejection_count"], 1)
        self.assertEqual(metrics.get("reviewed_mode_publish_readiness_rejection_count"), 1)
        self.assertEqual(metrics["reviewed_mode_secret_rejection_count"], 1)
        self.assertEqual(metrics["reviewed_mode_unexpected_path_rejection_count"], 5)
        self.assertEqual(metrics.get("reviewed_mode_dry_run_index_preservation_rate"), 1.0)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["synthetic_only"])
        self.assertFalse(report["privacy"]["command_output_rendered"])


if __name__ == "__main__":
    unittest.main()
