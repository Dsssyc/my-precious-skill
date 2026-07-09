import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/lifecycle_governance_gate.py").resolve()


class LifecycleGovernanceGateTests(unittest.TestCase):
    def test_lifecycle_governance_gate_reports_packaged_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--work-dir",
                    tmpdir,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "lifecycle_governance_gate")
            self.assertEqual(report["overall_status"], "pass")
            self.assertEqual(report["case_count"], 6)
            self.assertTrue(all(report["cases"].values()))
            metrics = report["metrics"]
            self.assertEqual(metrics["lifecycle_refresh_accuracy"], 1.0)
            self.assertEqual(metrics["lifecycle_deprecation_suppression_accuracy"], 1.0)
            self.assertEqual(metrics["lifecycle_deletion_tombstone_accuracy"], 1.0)
            self.assertEqual(metrics["lifecycle_partial_conflict_review_count"], 1)
            self.assertEqual(metrics["lifecycle_decay_or_stale_review_routing_accuracy"], 1.0)
            self.assertEqual(metrics["lifecycle_active_current_precision"], 1.0)
            self.assertEqual(metrics["lifecycle_inactive_search_suppression_rate"], 1.0)
            self.assertEqual(metrics["lifecycle_support_ref_coverage_rate"], 1.0)
            self.assertEqual(metrics["lifecycle_noisy_history_rejection_count"], 4)
            self.assertEqual(metrics["privacy_leak_count"], 0)

            combined = result.stdout + result.stderr
            for forbidden in (
                "V220 refresh routing keeps legacy",
                "V220 deleted lifecycle policy",
                "SYNTHETIC_V220_PRIVATE_TOKEN",
                "/Users/soku/private/lifecycle-source.jsonl",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
