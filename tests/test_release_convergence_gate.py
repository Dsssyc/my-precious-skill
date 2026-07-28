import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/release_convergence_gate.py").resolve()


class ReleaseConvergenceGateTests(unittest.TestCase):
    def test_gate_rejects_stale_release_identity_and_is_deterministic(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "release_convergence_gate")
        self.assertEqual(report["report_version"], 1)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["determinism"]["runs"], 2)
        self.assertTrue(report["determinism"]["reports_match"])
        for metric in (
            "current_release_acceptance_accuracy",
            "old_but_mutually_consistent_rejection_accuracy",
            "stale_installed_rejection_accuracy",
            "stale_private_runtime_rejection_accuracy",
            "unreleased_source_ref_rejection_accuracy",
            "automation_path_mismatch_rejection_accuracy",
            "automation_self_update_rejection_accuracy",
            "malformed_release_evidence_rejection_accuracy",
            "approved_search_runtime_acceptance_accuracy",
            "historical_no_go_runtime_rejection_accuracy",
        ):
            self.assertEqual(report["metrics"][metric], 1.0, metric)
        self.assertEqual(report["metrics"]["audit_mutation_count"], 0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["absolute_paths_rendered"])
        self.assertFalse(report["privacy"]["automation_prompt_rendered"])
        self.assertFalse(report["privacy"]["file_contents_rendered"])


if __name__ == "__main__":
    unittest.main()
