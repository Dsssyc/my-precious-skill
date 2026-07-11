import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/scope_arbitration_gate.py").resolve()


class ScopeArbitrationGateTests(unittest.TestCase):
    def test_scope_arbitration_gate_reports_packaged_runtime_metrics(self):
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
            self.assertEqual(report["report_kind"], "scope_arbitration_gate")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["package_source"], "clean_packaged_deployment_repo")
            self.assertFalse(report["free_form_search_used"])
            self.assertEqual(report["command_contract"]["answerability_source"], "memory_recall_context_package")
            self.assertEqual(report["command_contract"]["depth"], "evidence")
            self.assertTrue(report["command_contract"]["context_json"])
            self.assertTrue(report["command_contract"]["project_path_cases"])
            self.assertEqual(report["command_contract"]["preferred_scopes"], ["global", "domain", "project"])
            self.assertEqual(
                report["case_outcomes"],
                {
                    "global_foundational_fallback": "answer",
                    "domain_preference": "answer",
                    "project_override": "answer",
                    "wrong_project_same_topic": "abstain",
                    "broad_stale_rejected": "abstain",
                    "missing_project_context_ambiguous": "abstain",
                    "unsupported_no_hit": "abstain",
                    "malformed_package": "abstain",
                },
            )

            metrics = report["metrics"]
            self.assertEqual(metrics["scope_context_package_parse_success_rate"], 1.0)
            self.assertEqual(metrics["global_fallback_answerability_rate"], 1.0)
            self.assertEqual(metrics["domain_preference_accuracy"], 1.0)
            self.assertEqual(metrics["project_override_accuracy"], 1.0)
            self.assertEqual(metrics["wrong_project_rejection_count"], 1)
            self.assertEqual(metrics["broad_stale_rejection_count"], 1)
            self.assertEqual(metrics["missing_project_context_abstention_accuracy"], 1.0)
            self.assertEqual(metrics["scope_arbitration_decision_accuracy"], 1.0)
            self.assertGreaterEqual(metrics["scope_mixed_related_hit_count_at_5"], 1)
            self.assertEqual(metrics["privacy_leak_count"], 0)

            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["context_packages_rendered"])
            self.assertFalse(report["privacy"]["queries_rendered"])
            self.assertFalse(report["privacy"]["memory_text_rendered"])
            self.assertFalse(report["privacy"]["raw_refs_rendered"])
            self.assertFalse(report["privacy"]["raw_source_content_rendered"])

            combined = result.stdout + result.stderr
            for forbidden in (
                "v27global base answer value",
                "v27domain benchmark answer value",
                "v27project override answer value",
                "v27wrong project answer value",
                "v27stale broad answer value",
                "RAW V27 TRANSCRIPT SHOULD NOT RENDER",
                "cookie=V27_SHOULD_NOT_RENDER",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
