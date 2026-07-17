import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/scheduled_reboot_replay_gate.py").resolve()


def run_gate() -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"gate failed: stdout={result.stdout!r} stderr={result.stderr!r}")
    return json.loads(result.stdout)


class ScheduledRebootReplayGateTests(unittest.TestCase):
    def test_gate_proves_reboot_safe_transaction_metrics_deterministically(self):
        first = run_gate()
        second = run_gate()

        self.assertEqual(first["report_kind"], "scheduled_reboot_replay_gate")
        self.assertEqual(first["report_version"], 1)
        self.assertEqual(first["status"], "passed")
        self.assertTrue(first["privacy"]["aggregate_only"])
        self.assertEqual(first["metrics"], second["metrics"])

        metrics = first["metrics"]
        self.assertEqual(metrics["transaction_case_count"], 16)
        self.assertGreaterEqual(metrics["receipted_remote_tracked_overlap_count"], 1)
        self.assertGreaterEqual(metrics["receipted_remote_untracked_overlap_count"], 1)
        for name in (
            "clean_publish_accuracy",
            "no_op_decision_accuracy",
            "reboot_replay_success_rate",
            "canonical_clean_after_interruption_rate",
            "stale_staging_recovery_rate",
            "post_push_receipt_reconciliation_rate",
            "concurrent_transaction_rejection_rate",
            "dirty_canonical_rejection_rate",
            "malformed_state_rejection_rate",
            "unsafe_state_path_rejection_rate",
            "remote_race_rejection_rate",
            "repository_scoped_lock_rejection_rate",
            "git_common_dir_lock_rejection_rate",
            "nested_writer_lock_rejection_rate",
            "canonical_fast_forward_recovery_rate",
            "unreceipted_remote_rejection_rate",
            "receipted_remote_advance_replay_rate",
        ):
            self.assertEqual(metrics[name], 1.0, name)
        for name in (
            "partial_remote_publish_count",
            "duplicate_publish_commit_count",
            "canonical_unverified_mutation_count",
            "deployed_v238_tool_mutation_count",
            "raw_source_copy_count",
            "privacy_leak_count",
        ):
            self.assertEqual(metrics[name], 0, name)

        self.assertEqual(
            set(first["cases"]),
            {
                "clean_publish",
                "no_op_current",
                "kill_during_update",
                "interrupted_update_receipted_remote_advance",
                "kill_after_commit_before_push",
                "kill_after_push_before_fast_forward",
                "kill_during_canonical_fast_forward",
                "concurrent_transaction",
                "concurrent_different_state_dir",
                "concurrent_linked_worktree",
                "orphan_nested_writer",
                "dirty_canonical",
                "malformed_state",
                "unsafe_staging_path",
                "remote_race",
                "unreceipted_remote_advance",
            },
        )


if __name__ == "__main__":
    unittest.main()
