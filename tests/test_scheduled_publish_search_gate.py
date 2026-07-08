import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/scheduled_publish_search_gate.py").resolve()


class ScheduledPublishSearchGateTests(unittest.TestCase):
    def test_scheduled_publish_search_gate_reports_decision_metrics(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "scheduled_publish_search_gate")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertTrue(report["search_gate_contract"]["health_check_required"])
        self.assertFalse(report["search_gate_contract"]["generic_content_query_required"])
        self.assertEqual(
            {case["decision"] for case in report["cases"]},
            {"publish_ready", "search_blocked", "no_op_current", "dirty_or_unexpected_blocked"},
        )
        self.assertTrue(all(case["archive_audit_passed"] for case in report["cases"]))
        metrics = report["metrics"]
        self.assertEqual(metrics["search_gate_pass_rate"], 1.0)
        self.assertEqual(metrics["search_blocked_count"], 1)
        self.assertEqual(metrics["no_op_no_empty_commit_count"], 1)
        self.assertEqual(metrics["unexpected_dirty_block_count"], 1)
        self.assertEqual(metrics["publish_intent_count"], 1)
        self.assertEqual(metrics["hand_stage_bypass_count"], 0)
        self.assertEqual(metrics["free_form_search_output_used_count"], 0)
        self.assertEqual(metrics["privacy_leak_count"], 0)


if __name__ == "__main__":
    unittest.main()
