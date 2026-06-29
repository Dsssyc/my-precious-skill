import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/source_stream_registry_benchmark.py").resolve()
CASES = Path("benchmarks/cases/source_stream_registry_synthetic.jsonl").resolve()


class SourceStreamRegistryBenchmarkTests(unittest.TestCase):
    def test_source_stream_registry_benchmark_reports_non_project_layered_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--cases",
                    str(CASES),
                    "--work-dir",
                    str(Path(tmpdir) / "work"),
                    "--fail-under",
                    "case_pass_rate=1.0",
                    "--fail-under",
                    "source_stream_update_rate=1.0",
                    "--fail-under",
                    "project_registry_independence_rate=1.0",
                    "--fail-under",
                    "source_stream_memory_recall_at_5=1.0",
                    "--fail-under",
                    "source_stream_evidence_reachability_rate=1.0",
                    "--fail-under",
                    "source_stream_source_policy_pass_rate=1.0",
                    "--fail-over",
                    "privacy_leak_count=0",
                    "--fail-over",
                    "failed_case_count=0",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["report_kind"], "source_stream_registry_benchmark")
            self.assertEqual(payload["cases"], 1)
            self.assertEqual(payload["source_records_without_project_metadata"], 1)
            self.assertEqual(payload["category_counts"]["source_stream_registry"], 1)
            self.assertEqual(payload["source_stream_update_rate"], 1.0)
            self.assertEqual(payload["project_registry_independence_rate"], 1.0)
            self.assertEqual(payload["archive_scope_assignment_rate"], 1.0)
            self.assertEqual(payload["source_partition_assignment_rate"], 1.0)
            self.assertEqual(payload["source_stream_memory_recall_at_5"], 1.0)
            self.assertEqual(payload["source_stream_session_drilldown_rate"], 1.0)
            self.assertEqual(payload["source_stream_evidence_reachability_rate"], 1.0)
            self.assertEqual(payload["source_stream_source_policy_pass_rate"], 1.0)
            self.assertEqual(payload["privacy_leak_count"], 0)
            self.assertEqual(payload["failed_case_count"], 0)
            self.assertTrue(payload["privacy"]["aggregate_only"])
            self.assertFalse(payload["privacy"]["source_paths_rendered"])
            self.assertFalse(payload["privacy"]["memory_text_rendered"])


if __name__ == "__main__":
    unittest.main()
