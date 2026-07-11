import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/packaged_lifecycle_gate.py").resolve()


def load_gate_module():
    spec = importlib.util.spec_from_file_location("packaged_lifecycle_gate_under_test", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PackagedLifecycleGateTests(unittest.TestCase):
    def test_packaged_lifecycle_gate_runs_clean_room_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--work-dir",
                    tmpdir,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["records_archived"], 1)
            self.assertGreaterEqual(report["session_count"], 1)
            self.assertGreaterEqual(report["memory_count"], 1)
            self.assertEqual(report["audit"], "passed")
            self.assertEqual(report["search_health_check"], "passed")
            self.assertEqual(report["sync_dry_run"], "passed")
            self.assertEqual(
                report["self_maintenance"],
                {
                    "status": "passed",
                    "automation_source_records": 2,
                    "automation_session_entries": 0,
                    "automation_memory_nodes": 0,
                    "automation_daily_noise_hits": 0,
                    "automation_index_noise_hits": 0,
                },
            )
            self.assertEqual(
                report["explicit_capture"],
                {
                    "status": "passed",
                    "adapter_input_records": 1,
                    "captured_memory_nodes": 1,
                    "rejected_raw_transcript_records": 1,
                    "search_hit_count": 1,
                    "privacy_leak_count": 0,
                },
            )
            self.assertEqual(
                report["explicit_revision"],
                {
                    "status": "passed",
                    "explicit_revision_input_records": 2,
                    "explicit_revision_superseded_records": 1,
                    "explicit_revision_deprecated_records": 1,
                    "current_fact_search_hit_count": 1,
                    "stale_fact_default_search_hit_count": 0,
                    "withdrawn_fact_default_search_hit_count": 0,
                    "revision_evidence_reachability_count": 2,
                    "privacy_leak_count": 0,
                },
            )
            self.assertEqual(
                report["explicit_governance"],
                {
                    "status": "passed",
                    "explicit_context_package_parse_success_rate": 1.0,
                    "explicit_current_fact_answerability_rate": 1.0,
                    "explicit_replaced_fact_abstention_rate": 1.0,
                    "explicit_withdrawn_fact_abstention_rate": 1.0,
                    "explicit_revision_link_integrity_rate": 1.0,
                    "explicit_bulk_duplicate_suppression_rate": 1.0,
                    "explicit_conflict_fail_closed_count": 1,
                    "explicit_unsafe_target_refusal_count": 1,
                    "explicit_unknown_target_refusal_count": 1,
                    "privacy_leak_count": 0,
                },
            )
            self.assertEqual(set(report["search_depths"]), {"memory", "session", "evidence", "source"})
            self.assertNotIn("clean-room lifecycle fact", result.stdout)
            self.assertNotIn("clean-room lifecycle fact", result.stderr)
            self.assertNotIn("Automation run status", result.stdout)
            self.assertNotIn("Automation run status", result.stderr)
            self.assertNotIn("No memory hits", result.stdout)
            self.assertNotIn("No memory hits", result.stderr)
            self.assertNotIn("Prefer explicit memory capture adapter", result.stdout)
            self.assertNotIn("Prefer explicit memory capture adapter", result.stderr)
            self.assertNotIn("legacy explicit revision policy", result.stdout)
            self.assertNotIn("legacy explicit revision policy", result.stderr)
            self.assertNotIn("obsolete explicit withdrawal policy", result.stdout)
            self.assertNotIn("obsolete explicit withdrawal policy", result.stderr)
            self.assertNotIn("explicit memory revision target was not found", result.stdout)
            self.assertNotIn("explicit memory cannot both supersede and deprecate", result.stdout)
            self.assertTrue(Path(tmpdir).exists())
            self.assertEqual(list(Path(tmpdir).iterdir()), [])

    def test_packaged_lifecycle_gate_reports_missing_required_artifact(self):
        module = load_gate_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir) / "agent-memory"
            (memory_repo / "sessions/2026/07/06/example").mkdir(parents=True)
            (memory_repo / "index").mkdir(parents=True)
            (memory_repo / "daily/2026").mkdir(parents=True)
            (memory_repo / "memories").mkdir(parents=True)
            (memory_repo / "INDEX.md").write_text("# Agent Memory\n", encoding="utf-8")
            (memory_repo / "index/sessions.jsonl").write_text("{}\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text("{}\n", encoding="utf-8")
            (memory_repo / "daily/2026/2026-07-06.md").write_text("# Daily\n", encoding="utf-8")
            (memory_repo / "memories/global.jsonl").write_text("{}\n", encoding="utf-8")

            errors = module.validate_archive_artifacts(memory_repo)

            self.assertIn("missing sessions evidence.md", errors)


if __name__ == "__main__":
    unittest.main()
