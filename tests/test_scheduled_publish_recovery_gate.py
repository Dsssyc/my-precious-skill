import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/scheduled_publish_recovery_gate.py").resolve()


class ScheduledPublishRecoveryGateTests(unittest.TestCase):
    def test_scheduled_publish_recovery_gate_reports_recovery_metrics(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "scheduled_publish_recovery_gate")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["privacy"]["aggregate_only"])
        metrics = report["metrics"]
        self.assertEqual(metrics["scheduler_prompt_contract_pass_rate"], 1.0)
        self.assertEqual(metrics["pre_repair_sync_block_count"], 2)
        self.assertEqual(metrics["repair_apply_success_count"], 1)
        self.assertEqual(metrics["post_repair_publish_intent_count"], 1)
        self.assertEqual(metrics["ambiguous_fail_closed_count"], 1)
        self.assertEqual(metrics["malformed_fail_closed_count"], 1)
        self.assertEqual(metrics["hand_stage_bypass_count"], 0)
        self.assertEqual(metrics["privacy_leak_count"], 0)


if __name__ == "__main__":
    unittest.main()
