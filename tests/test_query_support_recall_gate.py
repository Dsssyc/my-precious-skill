import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/query_support_recall_gate.py").resolve()


class QuerySupportRecallGateTests(unittest.TestCase):
    def test_query_support_recall_gate_reports_hard_negative_metrics(self):
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
            self.assertEqual(report["report_kind"], "query_support_hard_negative_recall_gate")
            self.assertEqual(report["status"], "passed")
            self.assertFalse(report["free_form_search_used"])
            self.assertEqual(report["command_contract"]["answerability_source"], "memory_recall_context_package")
            self.assertEqual(report["command_contract"]["depth"], "evidence")
            self.assertTrue(report["command_contract"]["context_json"])

            metrics = report["metrics"]
            self.assertEqual(metrics["supported_context_recall_at_5"], 1.0)
            self.assertEqual(metrics["answerable_precision_at_5"], 1.0)
            self.assertEqual(metrics["query_support_boundary_pass_rate"], 1.0)
            self.assertEqual(metrics["weak_support_rejection_count"], 2)
            self.assertEqual(metrics["scope_mixed_noise_at_5"], 0.0)
            self.assertEqual(metrics["inactive_lifecycle_rejection_count"], 1)
            self.assertEqual(metrics["runtime_abstention_accuracy"], 1.0)
            self.assertEqual(metrics["privacy_leak_count"], 0)

            self.assertEqual(
                report["case_outcomes"],
                {
                    "supported_active_current": "answer",
                    "same_topic_wrong_scope": "abstain",
                    "weak_active_current": "abstain",
                    "broad_lexical_overlap": "abstain",
                    "inactive_superseded_only": "abstain",
                    "unsupported_no_hit": "abstain",
                    "malformed_package": "abstain",
                },
            )

            combined = result.stdout + result.stderr
            for forbidden in (
                "v23alpha supported anchor durable answer value",
                "v23wrongscope nearby active memory from the wrong layer",
                "v23weakonly generic active memory with support files",
                "v23ledger policy generic archive overlap without the answer",
                "v23retired zeta legacy inactive answer",
                "RAW V23 TRANSCRIPT SHOULD NOT RENDER",
                "cookie=V23_SHOULD_NOT_RENDER",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
