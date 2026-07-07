import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/using_my_precious_runtime_gate.py").resolve()


class UsingMyPreciousRuntimeGateTests(unittest.TestCase):
    def test_runtime_gate_consumes_packaged_context_package(self):
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
            self.assertEqual(report["report_kind"], "using_my_precious_runtime_consumption_gate")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["package_source"], "clean_packaged_deployment_repo")
            self.assertTrue(report["free_form_search_used"] is False)
            self.assertEqual(report["metrics"]["runtime_context_package_parse_success_rate"], 1.0)
            self.assertEqual(report["metrics"]["runtime_supported_decision_accuracy"], 1.0)
            self.assertEqual(report["metrics"]["runtime_abstention_accuracy"], 1.0)
            self.assertEqual(report["metrics"]["runtime_inactive_rejection_count"], 1)
            self.assertEqual(report["metrics"]["runtime_malformed_fail_closed_count"], 1)
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertEqual(
                report["case_outcomes"],
                {
                    "supported_active_current": "answer",
                    "unsupported_no_hit": "abstain",
                    "inactive_superseded_only": "abstain",
                    "malformed_package": "abstain",
                },
            )

            combined = result.stdout + result.stderr
            for forbidden in (
                "packagefirst answerability marker active support",
                "staleonly zetaomega legacyonly stale support",
                "RAW TRANSCRIPT",
                "cookie=SHOULD_NOT_RENDER",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
