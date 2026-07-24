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
            self.assertEqual(report["metrics"]["runtime_support_coverage_accuracy"], 1.0)
            self.assertEqual(report["metrics"]["runtime_near_miss_abstention_accuracy"], 1.0)
            self.assertEqual(report["metrics"]["runtime_supported_decision_accuracy"], 1.0)
            self.assertEqual(report["metrics"]["runtime_abstention_accuracy"], 1.0)
            self.assertEqual(
                report["metrics"]["runtime_subject_preference_supported_accuracy"],
                1.0,
            )
            self.assertEqual(
                report["metrics"]["runtime_goal_delivery_contract_accuracy"],
                1.0,
            )
            self.assertEqual(
                report["metrics"]["runtime_exact_preference_delivery_contract_accuracy"],
                1.0,
            )
            self.assertEqual(
                report["metrics"]["runtime_candidate_only_rejection_count"],
                1,
            )
            self.assertEqual(
                report["metrics"][
                    "runtime_candidate_only_safety_eligible_count"
                ],
                1,
            )
            self.assertEqual(
                report["metrics"][
                    "runtime_candidate_only_subject_support_count"
                ],
                0,
            )
            self.assertEqual(
                report["metrics"]["runtime_bare_subject_rejection_count"],
                1,
            )
            self.assertEqual(
                report["metrics"]["runtime_wrong_scope_rejection_count"],
                1,
            )
            self.assertEqual(
                report["metrics"]["runtime_current_turn_preference_rejection_count"],
                1,
            )
            self.assertEqual(report["metrics"]["runtime_weak_active_rejection_count"], 2)
            self.assertEqual(report["metrics"]["runtime_inactive_rejection_count"], 1)
            self.assertEqual(report["metrics"]["runtime_malformed_fail_closed_count"], 1)
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertEqual(
                report["case_outcomes"],
                {
                    "supported_active_current": "answer",
                    "unsupported_no_hit": "abstain",
                    "inactive_superseded_only": "abstain",
                    "weak_active_current": "abstain",
                    "same_topic_near_miss": "abstain",
                    "source_bound_subject_preference": "answer",
                    "exact_source_bound_subject_preference": "answer",
                    "candidate_only_subject_preference": "abstain",
                    "bare_subject_preference": "abstain",
                    "wrong_scope_subject_preference": "abstain",
                    "current_turn_subject_preference": "abstain",
                    "malformed_package": "abstain",
                },
            )
            self.assertEqual(
                report["delivery_contract_outcomes"],
                {
                    "source_bound_subject_preference": (
                        "single_text_fence_no_outer_text"
                    ),
                    "exact_source_bound_subject_preference": (
                        "single_text_fence_no_outer_text"
                    ),
                },
            )

            combined = result.stdout + result.stderr
            for forbidden in (
                "packagefirst answerability marker active support",
                "staleonly zetaomega legacyonly stale support",
                "weakonly generic active memory with drill paths",
                "samealpha nearby topic active memory",
                "RAW TRANSCRIPT",
                "cookie=SHOULD_NOT_RENDER",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
