import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/search_tool_drift_repair_gate.py").resolve()


class SearchToolDriftRepairGateTests(unittest.TestCase):
    def test_gate_repairs_stale_search_tool_without_template_fallback_or_data_mutation(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "search_tool_drift_repair_gate")
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["template_fallback_used_after_repair"])

        metrics = report["metrics"]
        self.assertEqual(metrics["stale_search_tool_detected_count"], 1)
        self.assertEqual(metrics["repair_attempt_count"], 2)
        self.assertEqual(metrics["post_repair_context_package_success_count"], 1)
        self.assertEqual(metrics["template_fallback_used_after_repair_count"], 0)
        self.assertEqual(metrics["archive_data_mutation_count"], 0)
        self.assertEqual(metrics["unsafe_repair_fail_closed_count"], 1)
        self.assertEqual(metrics["privacy_leak_count"], 0)

        rendered = result.stdout + result.stderr
        self.assertNotIn("packagefirst answerability marker active support", rendered)
        self.assertNotIn("context package unsupported", rendered)
        self.assertIsNone(re.search(r"\bmem_[A-Za-z0-9_.:-]+", rendered))


if __name__ == "__main__":
    unittest.main()
