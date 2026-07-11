import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/runtime_tool_bundle_parity_gate.py").resolve()


class RuntimeToolBundleParityGateTests(unittest.TestCase):
    def test_gate_reports_deterministic_full_bundle_repair(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "runtime_tool_bundle_parity_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["expected_tool_count"], 19)
        self.assertTrue(report["determinism"]["reports_match"])
        self.assertTrue(report["determinism"]["bundle_hash_valid"])
        for key, value in report["metrics"].items():
            if key.endswith("_rate") or key.endswith("_accuracy"):
                self.assertEqual(value, 1.0, key)
        self.assertEqual(report["metrics"]["absolute_path_leak_count"], 0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["archive_text_rendered"])
        self.assertFalse(report["privacy"]["absolute_paths_rendered"])


if __name__ == "__main__":
    unittest.main()
