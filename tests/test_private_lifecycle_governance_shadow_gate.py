import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/private_lifecycle_governance_shadow_gate.py").resolve()
ACTIVE_SUPPORT_FAILURE_COUNTERS = (
    "active_support_expected_node_missing_count",
    "active_support_package_unsupported_count",
    "active_support_query_support_missing_count",
    "active_support_summary_drill_missing_count",
    "active_support_evidence_drill_missing_count",
    "active_support_wrong_active_hit_count",
    "archive_search_tool_context_package_failure_count",
    "template_search_tool_fallback_success_count",
    "unknown_privacy_preserved_failure_count",
)


def load_gate_module():
    spec = importlib.util.spec_from_file_location("private_lifecycle_gate_under_test", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrivateLifecycleGovernanceShadowGateTests(unittest.TestCase):
    def test_synthetic_fixture_reports_aggregate_only_private_lifecycle_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--synthetic-fixture",
                    "--work-dir",
                    tmpdir,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "private_lifecycle_governance_shadow_gate")
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["mode"], "synthetic_fixture")
            self.assertTrue(report["privacy"]["aggregate_only"])

            metrics = report["metrics"]
            self.assertEqual(metrics["private_lifecycle_relation_integrity_score"], 1.0)
            self.assertEqual(metrics["private_inactive_search_suppression_sample_rate"], 1.0)
            self.assertEqual(metrics["private_active_current_support_sample_rate"], 1.0)
            self.assertEqual(metrics["private_context_package_parse_success_rate"], 1.0)
            self.assertGreaterEqual(metrics["private_tombstone_marker_count"], 1)
            self.assertGreaterEqual(metrics["private_stale_review_candidate_count"], 1)
            self.assertEqual(metrics["private_support_ref_reachability_sample_rate"], 1.0)
            self.assertEqual(metrics["private_review_queue_actionability_rate"], 1.0)
            self.assertEqual(metrics["privacy_leak_count"], 0)
            self.assertEqual(metrics["rendered_private_query_count"], 0)
            self.assertEqual(metrics["rendered_memory_text_count"], 0)
            self.assertEqual(metrics["rendered_source_path_count"], 0)
            self.assertEqual(metrics["rendered_raw_ref_count"], 0)
            for counter in ACTIVE_SUPPORT_FAILURE_COUNTERS:
                self.assertEqual(metrics[counter], 0)

            combined = result.stdout + result.stderr
            for forbidden in (
                "V220 refresh routing keeps legacy",
                "V220 deleted lifecycle policy",
                "SYNTHETIC_V220_PRIVATE_TOKEN",
                "/Users/example/private/lifecycle-source.jsonl",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)
            self.assertIsNone(re.search(r"\bmem_[A-Za-z0-9_.:-]+", combined))

    def test_unsafe_report_validation_fails_closed_without_rendering_private_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            unsafe_report = Path(tmpdir) / "unsafe-report.json"
            unsafe_report.write_text(
                json.dumps(
                    {
                        "report_kind": "private_lifecycle_governance_shadow_gate",
                        "status": "passed",
                        "metrics": {"privacy_leak_count": 0},
                        "privacy": {
                            "aggregate_only": True,
                            "memory_text_rendered": True,
                        },
                        "unsafe_memory_id": "mem_private_rendered_123",
                        "unsafe_path": "/Users/example/private/archive/source-map.json",
                        "unsafe_text": "SYNTHETIC_V220_PRIVATE_TOKEN",
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--validate-report",
                    str(unsafe_report),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "private_lifecycle_governance_shadow_gate_validation")
            self.assertEqual(report["status"], "failed")
            self.assertGreater(report["metrics"]["privacy_leak_count"], 0)
            combined = result.stdout + result.stderr
            self.assertNotIn("SYNTHETIC_V220_PRIVATE_TOKEN", combined)
            self.assertNotIn("mem_private_rendered_123", combined)
            self.assertNotIn("/Users/example/private/archive/source-map.json", combined)

    def test_context_package_falls_back_to_template_tool_without_rendering_context(self):
        module = load_gate_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            gate_run = module.lifecycle.run_packaged_update(Path(tmpdir))
            broken_tool = gate_run.memory_repo / "tools/search_memory.py"
            broken_tool.write_text(
                "import sys\nsys.stderr.write('context package unsupported')\nsys.exit(2)\n",
                encoding="utf-8",
            )

            package, outcome = module.load_context_package(
                gate_run.memory_repo,
                module.lifecycle.FRESH_ANCHOR,
                sys.executable,
            )

            self.assertEqual(outcome, "parsed_fallback")
            self.assertIsInstance(package, dict)
            self.assertEqual(package["report_kind"], "memory_recall_context_package")

            report = module.build_gate_report(
                repo=gate_run.memory_repo,
                mode="synthetic_fixture",
                update_failures=0,
                sample_limit=6,
                python=sys.executable,
            )
            self.assertEqual(report["status"], "passed")
            query_count = report["diagnostics"]["context_package_query_count"]
            metrics = report["metrics"]
            self.assertEqual(metrics["archive_search_tool_context_package_failure_count"], query_count)
            self.assertEqual(metrics["template_search_tool_fallback_success_count"], query_count)
            rendered = json.dumps(report, sort_keys=True)
            self.assertNotIn("context package unsupported", rendered)
            self.assertIsNone(re.search(r"\bmem_[A-Za-z0-9_.:-]+", rendered))

    def test_corrupted_active_support_reports_aggregate_failure_category(self):
        module = load_gate_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            gate_run = module.lifecycle.run_packaged_update(Path(tmpdir))
            memories_path = gate_run.memory_repo / "index/memories.jsonl"
            rows = [
                json.loads(line)
                for line in memories_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            corrupted = False
            for row in rows:
                if row.get("text") == module.lifecycle.FRESH_ANCHOR:
                    row["derived_from"] = []
                    row["evidence_refs"] = []
                    row["raw_refs"] = []
                    corrupted = True
                    break
            self.assertTrue(corrupted)
            memories_path.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
                encoding="utf-8",
            )

            report = module.build_gate_report(
                repo=gate_run.memory_repo,
                mode="synthetic_fixture",
                update_failures=0,
                sample_limit=6,
                python=sys.executable,
            )

            self.assertEqual(report["status"], "failed")
            metrics = report["metrics"]
            self.assertGreater(metrics["active_support_package_unsupported_count"], 0)
            self.assertGreater(metrics["active_support_summary_drill_missing_count"], 0)
            self.assertGreater(metrics["active_support_evidence_drill_missing_count"], 0)
            self.assertEqual(metrics["privacy_leak_count"], 0)
            rendered = json.dumps(report, sort_keys=True)
            self.assertNotIn(module.lifecycle.FRESH_ANCHOR, rendered)
            self.assertIsNone(re.search(r"\bmem_[A-Za-z0-9_.:-]+", rendered))

    def test_output_path_outside_tmp_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            unsafe_output = Path.cwd() / "private-lifecycle-shadow-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--synthetic-fixture",
                    "--work-dir",
                    tmpdir,
                    "--output",
                    str(unsafe_output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertNotEqual(result.returncode, 0)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["diagnostics"]["blocker_categories"], ["unsafe_output_path"])
            self.assertFalse(unsafe_output.exists())


if __name__ == "__main__":
    unittest.main()
