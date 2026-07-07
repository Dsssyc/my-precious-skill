import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/progressive_source_drilldown_gate.py").resolve()


class ProgressiveSourceDrilldownGateTests(unittest.TestCase):
    def test_progressive_source_drilldown_gate_reports_context_package_metrics(self):
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
            self.assertEqual(report["report_kind"], "progressive_source_drilldown_gate")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["package_source"], "clean_packaged_deployment_repo")
            self.assertFalse(report["free_form_search_used"])
            self.assertEqual(report["command_contract"]["answerability_source"], "memory_recall_context_package")
            self.assertEqual(report["command_contract"]["depths"], ["evidence", "source"])
            self.assertTrue(report["command_contract"]["context_json"])
            self.assertEqual(
                report["case_outcomes"],
                {
                    "supported_answer": "answer",
                    "supported_source_drilldown": "drill",
                    "multihop_source_drilldown": "drill",
                    "evidence_only_original_source": "abstain",
                    "inactive_source_only": "abstain",
                    "unsafe_source_ref": "block",
                    "malformed_package": "abstain",
                },
            )

            metrics = report["metrics"]
            self.assertEqual(metrics["source_context_package_parse_success_rate"], 1.0)
            self.assertEqual(metrics["source_drilldown_decision_accuracy"], 1.0)
            self.assertEqual(metrics["memory_to_summary_drilldown_rate"], 1.0)
            self.assertEqual(metrics["summary_to_evidence_drilldown_rate"], 1.0)
            self.assertEqual(metrics["evidence_to_source_ref_reachability_rate"], 1.0)
            self.assertEqual(metrics["memory_graph_multihop_source_resolution_rate"], 1.0)
            self.assertEqual(metrics["evidence_only_original_source_rejection_count"], 1)
            self.assertEqual(metrics["inactive_source_rejection_count"], 1)
            self.assertEqual(metrics["unsafe_source_ref_block_count"], 1)
            self.assertEqual(metrics["raw_source_content_default_block_rate"], 1.0)
            self.assertEqual(metrics["privacy_leak_count"], 0)

            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["context_packages_rendered"])
            self.assertFalse(report["privacy"]["memory_text_rendered"])
            self.assertFalse(report["privacy"]["raw_refs_rendered"])
            self.assertFalse(report["privacy"]["raw_source_content_rendered"])

            combined = result.stdout + result.stderr
            for forbidden in (
                "v26direct source anchor durable answer value",
                "v26graph highlevel source drilldown answer",
                "v26leaf support carries source anchor",
                "v26evidenceonly original source request answer",
                "v26retired source only obsolete answer",
                "v26unsafe source ref reachable blocked answer",
                "RAW V26 TRANSCRIPT SHOULD NOT RENDER",
                "cookie=V26_SHOULD_NOT_RENDER",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
