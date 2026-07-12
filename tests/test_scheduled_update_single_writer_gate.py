import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/scheduled_update_single_writer_gate.py").resolve()


class ScheduledUpdateSingleWriterGateTests(unittest.TestCase):
    def test_gate_proves_single_writer_and_interrupted_run_closure(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "scheduled_update_single_writer_gate")
        self.assertEqual(report["report_version"], 1)
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        for name in (
            "single_writer_acceptance_rate",
            "concurrent_writer_rejection_rate",
            "dirty_startup_rejection_rate",
            "first_failure_fail_fast_rate",
            "parent_termination_child_cleanup_rate",
            "orphan_child_lock_retention_rate",
            "lock_release_after_exit_rate",
        ):
            self.assertEqual(metrics[name], 1.0, name)
        for name in (
            "post_failure_child_launch_count",
            "publish_attempt_after_failed_update_count",
            "privacy_leak_count",
        ):
            self.assertEqual(metrics[name], 0, name)
        self.assertTrue(report["privacy"]["aggregate_only"])
        rendered = json.dumps(report, sort_keys=True)
        for forbidden in (
            "PRIVATE_SINGLE_WRITER_SENTINEL",
            "child-pids",
            "source-records",
            "/Users/",
            "/private/",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
