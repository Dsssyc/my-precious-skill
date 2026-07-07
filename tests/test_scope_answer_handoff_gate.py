import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/scope_answer_handoff_gate.py").resolve()


class ScopeAnswerHandoffGateTests(unittest.TestCase):
    def test_scope_answer_handoff_gate_reports_packaged_handoff_metrics(self):
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
            self.assertEqual(report["report_kind"], "scope_answer_handoff_gate")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["package_source"], "clean_packaged_deployment_repo")
            self.assertFalse(report["free_form_search_used"])
            self.assertEqual(report["command_contract"]["answerability_source"], "memory_recall_context_package")
            self.assertEqual(report["command_contract"]["handoff_source"], "context_package_and_support_refs")
            self.assertEqual(report["command_contract"]["depth"], "evidence")
            self.assertTrue(report["command_contract"]["context_json"])
            self.assertTrue(report["command_contract"]["project_path_cases"])
            self.assertEqual(report["command_contract"]["preferred_scopes"], ["global", "domain", "project"])
            self.assertEqual(
                report["case_outcomes"],
                {
                    "global_foundational_handoff": "answer",
                    "domain_preference_handoff": "answer",
                    "project_override_handoff": "answer",
                    "wrong_project_same_topic_handoff": "abstain",
                    "missing_project_context_handoff": "abstain",
                    "stale_broad_handoff": "abstain",
                    "unsupported_no_hit_handoff": "abstain",
                    "malformed_package_handoff": "abstain",
                },
            )

            metrics = report["metrics"]
            self.assertEqual(metrics["scope_handoff_context_package_parse_success_rate"], 1.0)
            self.assertEqual(metrics["scope_handoff_supported_answer_accuracy"], 1.0)
            self.assertEqual(metrics["scope_handoff_abstention_accuracy"], 1.0)
            self.assertEqual(metrics["scope_handoff_support_ref_coverage_rate"], 1.0)
            self.assertEqual(metrics["scope_handoff_project_override_accuracy"], 1.0)
            self.assertEqual(metrics["scope_handoff_wrong_project_rejection_count"], 1)
            self.assertEqual(metrics["scope_handoff_missing_project_context_rejection_count"], 1)
            self.assertEqual(metrics["scope_handoff_stale_broad_rejection_count"], 1)
            self.assertEqual(metrics["scope_handoff_malformed_fail_closed_count"], 1)
            self.assertEqual(metrics["unsupported_claim_count"], 0)
            self.assertEqual(metrics["privacy_leak_count"], 0)

            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["context_packages_rendered"])
            self.assertFalse(report["privacy"]["queries_rendered"])
            self.assertFalse(report["privacy"]["memory_text_rendered"])
            self.assertFalse(report["privacy"]["generated_answers_rendered"])
            self.assertFalse(report["privacy"]["raw_refs_rendered"])
            self.assertFalse(report["privacy"]["raw_source_content_rendered"])

            combined = result.stdout + result.stderr
            for forbidden in (
                "v28global handoff answer value",
                "v28domain handoff answer value",
                "v28project handoff answer value",
                "v28wrong project handoff answer value",
                "v28second project handoff answer value",
                "v28stale broad handoff answer value",
                "RAW V28 TRANSCRIPT SHOULD NOT RENDER",
                "cookie=V28_SHOULD_NOT_RENDER",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
