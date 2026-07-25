import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/live_automation_prompt_alignment_gate.py").resolve()


class LiveAutomationPromptAlignmentGateTests(unittest.TestCase):
    def test_gate_reports_alignment_metrics_without_prompt_text(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "live_automation_prompt_alignment_gate")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["prompt_text_rendered"])
        metrics = report["metrics"]
        self.assertTrue(metrics["rendered_prompt_alignment_pass"])
        self.assertTrue(metrics["publish_readiness_gate_present"])
        self.assertTrue(metrics["repair_step_present"])
        self.assertTrue(metrics["post_repair_recheck_present"])
        self.assertTrue(metrics["sync_dry_run_before_push_present"])
        self.assertTrue(metrics["sync_only_publish_path_present"])
        self.assertTrue(metrics["synthetic_preflight_alignment_pass"])
        self.assertTrue(metrics["transaction_adapter_alignment_pass"])
        self.assertTrue(metrics["single_transaction_adapter_invocation_present"])
        self.assertTrue(metrics["strict_transaction_report_contract_present"])
        self.assertEqual(metrics["transaction_direct_publish_chain_count"], 0)
        self.assertEqual(metrics["duplicate_transaction_adapter_rejection_count"], 1)
        self.assertEqual(metrics["same_line_duplicate_transaction_adapter_rejection_count"], 1)
        self.assertEqual(metrics["missing_transaction_report_rejection_count"], 1)
        self.assertTrue(metrics["preflight_before_update_present"])
        self.assertTrue(metrics["preflight_fail_closed_contract_present"])
        self.assertTrue(metrics["clean_worktree_flag_present"])
        self.assertTrue(metrics["publication_receipt_contract_present"])
        self.assertTrue(metrics["terminal_status_contract_present"])
        self.assertTrue(metrics["task_completion_not_publish_success_present"])
        self.assertEqual(metrics["updater_before_preflight_rejection_count"], 1)
        self.assertEqual(metrics["auto_refresh_rejection_count"], 1)
        self.assertEqual(metrics["missing_readiness_rejection_count"], 1)
        self.assertEqual(metrics["raw_git_rejection_count"], 1)
        self.assertEqual(metrics["missing_clean_worktree_rejection_count"], 1)
        self.assertEqual(metrics["missing_publication_receipt_rejection_count"], 1)
        self.assertEqual(metrics["raw_git_publish_path_count"], 0)
        self.assertEqual(metrics["private_archive_content_committed_count"], 0)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertNotIn("PRIVATE_AUTOMATION_PROMPT_SENTINEL", result.stdout)
        self.assertNotIn("tools/run_memory_updates.py --memory-repo", result.stdout)
        self.assertNotIn("run_scheduled_memory_transaction.py --memory-repo", result.stdout)


if __name__ == "__main__":
    unittest.main()
