import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/archive_regeneration_closure_gate.py").resolve()


class ArchiveRegenerationClosureGateTests(unittest.TestCase):
    def test_gate_proves_packaged_regeneration_closure(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "archive_regeneration_closure_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["regeneration_bundle_reconciliation_accuracy"], 1.0)
        self.assertEqual(metrics["stale_derived_ref_count"], 0)
        self.assertEqual(metrics["stale_evidence_ref_count"], 0)
        self.assertEqual(metrics["stale_raw_ref_count"], 0)
        self.assertEqual(metrics["support_count_consistency_rate"], 1.0)
        self.assertEqual(metrics["orphan_explicit_fail_closed_accuracy"], 1.0)
        self.assertEqual(metrics["daily_structure_safe_clip_accuracy"], 1.0)
        self.assertEqual(metrics["daily_durable_fact_retention_rate"], 1.0)
        self.assertEqual(metrics["post_regeneration_archive_audit_pass_rate"], 1.0)
        self.assertEqual(metrics["post_regeneration_search_health_pass_rate"], 1.0)
        self.assertEqual(metrics["reviewed_sync_dry_run_pass_rate"], 1.0)
        self.assertEqual(metrics["idempotent_replay_rate"], 1.0)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["determinism"]["reports_match"])
        self.assertTrue(report["privacy"]["synthetic_only"])
        self.assertFalse(report["privacy"]["private_content_rendered"])


if __name__ == "__main__":
    unittest.main()
