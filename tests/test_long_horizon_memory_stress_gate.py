import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import benchmarks.long_horizon_memory_stress_gate as gate


GATE_SCRIPT = Path("benchmarks/long_horizon_memory_stress_gate.py").resolve()

REQUIRED_RATE_METRICS = (
    "long_horizon_ingest_success_rate",
    "long_horizon_checkpoint_answer_accuracy",
    "long_horizon_abstention_accuracy",
    "long_horizon_active_current_recall_at_5",
    "long_horizon_stale_suppression_rate",
    "long_horizon_cross_project_generalization_rate",
    "long_horizon_paraphrase_consolidation_rate",
    "long_horizon_noise_rejection_rate",
    "long_horizon_explicit_memory_survival_rate",
    "long_horizon_idempotent_replay_rate",
    "long_horizon_session_drilldown_rate",
    "long_horizon_evidence_drilldown_rate",
    "long_horizon_source_ref_reachability_rate",
    "long_horizon_lifecycle_reciprocity_rate",
    "long_horizon_index_parity_rate",
)


class LongHorizonMemoryStressGateTests(unittest.TestCase):
    def test_packaged_long_horizon_gate_reports_bounded_aggregate_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--work-dir", tmpdir],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=180,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "long_horizon_memory_stress_gate")
            self.assertEqual(report["report_version"], 1)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(
                report["workload"],
                {
                    "seed": 228,
                    "event_count": 240,
                    "epoch_count": 6,
                    "events_per_epoch": 40,
                    "project_context_count": 12,
                    "domain_count": 3,
                    "non_project_source_stream_count": 2,
                },
            )
            self.assertEqual(report["package_source"], "clean_packaged_deployment_repo")
            self.assertFalse(report["free_form_search_used"])
            self.assertEqual(
                report["context_package_report_kind"],
                "memory_recall_context_package",
            )
            self.assertEqual(
                report["pipeline"],
                {
                    "setup_invoked": True,
                    "incremental_epoch_updates": 6,
                    "automatic_induction_invoked": True,
                    "explicit_capture_invoked": True,
                    "consolidation_invoked": True,
                    "deployment_search_invoked": True,
                },
            )

            metrics = report["metrics"]
            for metric in REQUIRED_RATE_METRICS:
                self.assertEqual(metrics[metric], 1.0, metric)
            self.assertEqual(metrics["duplicate_active_memory_count"], 0)
            self.assertEqual(metrics["unexpected_active_memory_count"], 0)
            self.assertEqual(metrics["privacy_leak_count"], 0)
            self.assertIsInstance(metrics["runtime_seconds"], float)
            self.assertLess(metrics["runtime_seconds"], 180.0)

            self.assertEqual(report["checkpoint_case_count"], 16)
            self.assertEqual(report["answer_checkpoint_count"], 9)
            self.assertEqual(report["abstention_checkpoint_count"], 7)
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["queries_rendered"])
            self.assertFalse(report["privacy"]["memory_text_rendered"])
            self.assertFalse(report["privacy"]["source_paths_rendered"])
            self.assertFalse(report["privacy"]["raw_refs_rendered"])
            self.assertFalse(report["privacy"]["raw_source_content_rendered"])

            combined = result.stdout + result.stderr
            for forbidden in (
                "V228 rolling retention policy",
                "V228 conflict policy",
                "V228 induction summaries",
                "V228 explicit long horizon",
                "v228process",
                str(Path(tmpdir)),
            ):
                self.assertNotIn(forbidden, combined)
            self.assertNotIn('"memory_id":', combined)
            self.assertNotIn('"query":', combined)
            self.assertNotIn('"raw_refs":', combined)
            self.assertNotIn('"source_ref_id":', combined)
            self.assertNotIn("sessions/2026", combined)
            self.assertNotIn("v228-e00-", combined)

    def test_index_parity_rejects_equal_length_cross_index_drift(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_repo = Path(tmpdir)
            index_dir = memory_repo / "index"
            support_dir = memory_repo / "sessions/support"
            index_dir.mkdir(parents=True)
            support_dir.mkdir(parents=True)
            for name in ("summary.md", "evidence.md", "source-map.json"):
                (support_dir / name).write_text("{}\n", encoding="utf-8")

            session_rows = []
            file_rows = []
            for index in range(gate.EVENT_COUNT):
                session_id = f"session-{index:03d}"
                source_record = f"source-{index:03d}.jsonl"
                meta_dir = memory_repo / "sessions/meta" / session_id
                meta_dir.mkdir(parents=True)
                (meta_dir / "meta.json").write_text(
                    json.dumps({"session_id": session_id, "source_record": source_record}) + "\n",
                    encoding="utf-8",
                )
                session_rows.append(
                    {
                        "session_id": session_id,
                        "source_record": source_record,
                        "summary_path": "sessions/support/summary.md",
                        "evidence_path": "sessions/support/evidence.md",
                        "source_map_path": "sessions/support/source-map.json",
                    }
                )
                file_rows.append({"session_id": session_id, "path": source_record})

            final_file_row = dict(file_rows[-1])
            file_rows[-1] = dict(file_rows[0])
            partitions = gate.all_partitions()
            scope_rows = [
                {"archive_scope": scope}
                for scope in sorted({partition.archive_scope for partition in partitions})
            ]
            partition_rows = [
                {
                    "archive_scope": partition.archive_scope,
                    "source_partition": partition.source_partition,
                }
                for partition in partitions
            ]

            def write_jsonl(name, rows):
                (index_dir / name).write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8",
                )

            write_jsonl("sessions.jsonl", session_rows)
            write_jsonl("files.jsonl", file_rows)
            write_jsonl("scopes.jsonl", scope_rows)
            write_jsonl("source_partitions.jsonl", partition_rows)

            self.assertFalse(gate.index_parity_pass(memory_repo, partitions))

            file_rows[-1] = final_file_row
            scope_rows.append(dict(scope_rows[0]))
            partition_rows.append(dict(partition_rows[0]))
            write_jsonl("files.jsonl", file_rows)
            write_jsonl("scopes.jsonl", scope_rows)
            write_jsonl("source_partitions.jsonl", partition_rows)

            self.assertFalse(gate.index_parity_pass(memory_repo, partitions))


if __name__ == "__main__":
    unittest.main()
