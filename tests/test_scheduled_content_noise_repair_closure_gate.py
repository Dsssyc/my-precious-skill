import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/scheduled_content_noise_repair_closure_gate.py").resolve()


class ScheduledContentNoiseRepairClosureGateTests(unittest.TestCase):
    def test_scheduled_content_noise_repair_closure_gate_reports_metrics(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "scheduled_content_noise_repair_closure_gate")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertTrue(report["content_noise_contract"]["search_health_is_necessary_not_sufficient"])
        self.assertFalse(report["content_noise_contract"]["generic_content_query_required"])
        self.assertEqual(
            {case["case"] for case in report["cases"]},
            {
                "search_healthy_noise_repaired_publish_ready",
                "search_healthy_ambiguous_noise_blocked",
                "search_healthy_malformed_meta_blocked",
                "clean_after_repair_no_empty_commit",
                "durable_content_preserved",
            },
        )
        metrics = report["metrics"]
        self.assertEqual(metrics["search_health_pre_repair_pass_rate"], 1.0)
        self.assertEqual(metrics["content_noise_block_count"], 4)
        self.assertEqual(metrics["repair_apply_success_count"], 2)
        self.assertEqual(metrics["post_repair_readiness_pass_count"], 3)
        self.assertEqual(metrics["post_repair_search_health_pass_count"], 3)
        self.assertEqual(metrics["post_repair_publish_intent_count"], 1)
        self.assertEqual(metrics["ambiguous_fail_closed_count"], 1)
        self.assertEqual(metrics["malformed_fail_closed_count"], 1)
        self.assertEqual(metrics["no_empty_commit_count"], 1)
        self.assertEqual(metrics["durable_content_preservation_count"], 1)
        self.assertEqual(metrics["hand_stage_bypass_count"], 0)
        self.assertEqual(metrics["free_form_search_output_used_count"], 0)
        self.assertEqual(metrics["privacy_leak_count"], 0)


if __name__ == "__main__":
    unittest.main()
