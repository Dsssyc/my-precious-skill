import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/legacy_source_anchor_upgrade_gate.py").resolve()


class LegacySourceAnchorUpgradeGateTests(unittest.TestCase):
    def test_gate_proves_transactional_provenance_only_upgrade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--work-dir", tmpdir],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "legacy_source_anchor_upgrade_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["source_record_count"], 6)
        self.assertEqual(metrics["source_event_count"], 24)
        for name, value in metrics.items():
            if name.endswith("_rate") or name.endswith("_accuracy"):
                self.assertEqual(value, 1.0, name)
        for name in (
            "unexpected_semantic_change_count",
            "partial_upgrade_count",
            "wrong_event_preview_count",
            "unredacted_secret_count",
            "raw_path_leak_count",
            "raw_ref_leak_count",
            "privacy_leak_count",
        ):
            self.assertEqual(metrics[name], 0, name)
        self.assertLess(metrics["runtime_seconds"], 90.0)
        self.assertTrue(all(report["observations"].values()))
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertNotIn("V230 automatic fact", result.stdout + result.stderr)
        self.assertNotIn("V230_SHOULD_NEVER_RENDER", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
