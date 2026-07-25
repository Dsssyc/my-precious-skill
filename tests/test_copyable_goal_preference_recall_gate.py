import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/copyable_goal_preference_recall_gate.py").resolve()
REQUIRED_ONE_METRICS = {
    "correction_sequence_qualification_rate",
    "correction_induced_fact_materialization_rate",
    "correction_source_anchor_binding_rate",
    "goal_format_query_supported_recall",
    "supported_summary_fact_resolution_rate",
    "global_scope_accuracy",
    "current_turn_instruction_precedence_accuracy",
    "copyable_text_block_decision_accuracy",
    "nested_fence_collision_avoidance_accuracy",
}
REQUIRED_ZERO_METRICS = {
    "assistant_evidence_promotion_count",
    "non_target_memory_promotion_count",
    "free_form_answerability_use_count",
    "privacy_leak_count",
}


def load_gate():
    spec = importlib.util.spec_from_file_location("copyable_goal_preference_gate_test", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CopyableGoalPreferenceRecallGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load_gate()

    def test_gate_materializes_and_recalls_source_bound_preference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--work-dir", tmpdir],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=360,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "copyable_goal_preference_recall_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["baseline"]["failure_class"], "memory_not_materialized")
        self.assertTrue(report["baseline"]["updater_executed"])
        self.assertGreaterEqual(report["baseline"]["archived_session_count"], 1)
        self.assertEqual(report["baseline"]["supported_query_count"], 0)
        self.assertEqual(report["candidate"]["target_materialization_count"], 1)
        self.assertEqual(report["candidate"]["supported_query_count"], 4)
        self.assertGreaterEqual(report["candidate"]["bound_evidence_count"], 2)
        self.assertGreaterEqual(report["candidate"]["bound_source_anchor_count"], 2)
        self.assertGreaterEqual(report["candidate"]["bound_user_source_anchor_count"], 2)
        self.assertGreaterEqual(report["candidate"]["distinct_user_source_event_count"], 2)
        self.assertEqual(report["answerability_source"], "memory_recall_context_package")
        self.assertFalse(report["free_form_search_used"])
        for metric in REQUIRED_ONE_METRICS:
            self.assertEqual(report["metrics"][metric], 1.0, metric)
        for metric in REQUIRED_ZERO_METRICS:
            self.assertEqual(report["metrics"][metric], 0, metric)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertNotIn(str(Path(tmpdir)), result.stdout)

    def test_runtime_decision_uses_current_instruction_and_avoids_nested_fence_collision(self):
        gate = self.gate
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            summary = repo / "sessions/synthetic/summary.md"
            evidence = repo / "sessions/synthetic/evidence.md"
            other_summary = repo / "sessions/other/summary.md"
            summary.parent.mkdir(parents=True)
            other_summary.parent.mkdir(parents=True)
            summary.write_text(gate.TARGET_FACT + "\n", encoding="utf-8")
            evidence.write_text("ev_001: supported user event\n", encoding="utf-8")
            other_summary.write_text("Unrelated supported memory.\n", encoding="utf-8")
            supported = json.dumps(
                {
                    "report_kind": gate.CONTEXT_REPORT_KIND,
                    "answerability": {"status": "supported"},
                    "hits": [
                        {
                            "memory_id": "mem_target",
                            "active_current": True,
                            "answerability": {"status": "supported"},
                            "query_support": {"status": "supported"},
                            "summary_drill_paths": ["sessions/synthetic/summary.md"],
                            "evidence_drill_paths": ["sessions/synthetic/evidence.md"],
                        }
                    ],
                }
            )
            unrelated = json.dumps(
                {
                    "report_kind": gate.CONTEXT_REPORT_KIND,
                    "answerability": {"status": "supported"},
                    "hits": [
                        {
                            "memory_id": "mem_other",
                            "active_current": True,
                            "answerability": {"status": "supported"},
                            "query_support": {"status": "supported"},
                            "summary_drill_paths": ["sessions/other/summary.md"],
                            "evidence_drill_paths": ["sessions/synthetic/evidence.md"],
                        }
                    ],
                }
            )
            missing_evidence = json.dumps(
                {
                    "report_kind": gate.CONTEXT_REPORT_KIND,
                    "answerability": {"status": "supported"},
                    "hits": [
                        {
                            "memory_id": "mem_target",
                            "active_current": True,
                            "answerability": {"status": "supported"},
                            "query_support": {"status": "supported"},
                            "summary_drill_paths": ["sessions/synthetic/summary.md"],
                            "evidence_drill_paths": ["sessions/synthetic/missing-evidence.md"],
                        }
                    ],
                }
            )
            nested_goal = "# Goal\n\n```bash\npython3 verify.py\n```"
            target_ids = frozenset({"mem_target"})

            nested = gate.delivery_decision(
                supported,
                "请给出 goal。",
                nested_goal,
                memory_repo=repo,
                target_memory_ids=target_ids,
            )
            unrelated_decision = gate.delivery_decision(
                unrelated,
                "请给出 goal。",
                "# Goal",
                memory_repo=repo,
                target_memory_ids=target_ids,
            )
            missing_evidence_decision = gate.delivery_decision(
                missing_evidence,
                "请给出 goal。",
                "# Goal",
                memory_repo=repo,
                target_memory_ids=target_ids,
            )
            current = gate.delivery_decision(
                "{not-json",
                "请把完整 goal 放进 text 代码块。",
                "# Goal",
            )
            override = gate.delivery_decision(
                supported,
                "这次不要代码块，直接渲染 Markdown。",
                "# Goal",
                memory_repo=repo,
                target_memory_ids=target_ids,
            )

        self.assertEqual(nested.outer_fence, "````")
        self.assertIn(nested_goal, gate.render_copyable_goal(nested_goal, nested))
        self.assertEqual(unrelated_decision.history_action, "abstain")
        self.assertFalse(unrelated_decision.history_preference_used)
        self.assertEqual(missing_evidence_decision.history_action, "abstain")
        self.assertEqual(current.history_action, "abstain")
        self.assertEqual(current.copy_container, "text_fence")
        self.assertTrue(current.current_instruction_used)
        self.assertEqual(override.copy_container, "rendered_markdown")
        self.assertFalse(override.history_preference_used)

    def test_source_binding_requires_distinct_user_events(self):
        gate = self.gate
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            evidence = repo / "sessions/synthetic/evidence.md"
            source_map = repo / "sessions/synthetic/source-map.json"
            source_record = repo / "source.jsonl"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("ev_001: assistant text\n", encoding="utf-8")
            source_record.write_text(
                json.dumps({"role": "assistant", "content": "assistant text"}) + "\n",
                encoding="utf-8",
            )
            event_sha256 = hashlib.sha256(b"assistant text").hexdigest()
            source_map.write_text(
                json.dumps(
                    {
                        "source_record": str(source_record),
                        "evidence_source_anchors": [
                            {
                                "source_anchor_id": "srca_assistant",
                                "quote_id": "ev_001",
                                "line_number": 1,
                                "event_ordinal": 1,
                                "event_sha256": event_sha256,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            node = {
                "evidence_refs": [
                    {"path": "sessions/synthetic/evidence.md", "quote_id": "ev_001"}
                ],
                "raw_refs": [
                    {"path": "sessions/synthetic/source-map.json", "anchor": "srca_assistant"}
                ],
            }

            counts = gate.source_binding_counts(repo, node)

        self.assertEqual(counts.valid_evidence_count, 1)
        self.assertEqual(counts.valid_source_anchor_count, 1)
        self.assertEqual(counts.user_source_anchor_count, 0)
        self.assertEqual(counts.non_user_source_anchor_count, 1)
        self.assertEqual(counts.distinct_user_source_event_count, 0)

    def test_source_binding_recomputes_hash_and_deduplicates_event_locator(self):
        gate = self.gate
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            evidence = repo / "sessions/synthetic/evidence.md"
            source_map = repo / "sessions/synthetic/source-map.json"
            source_record = repo / "source.jsonl"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "ev_001: repeated user event\nev_002: repeated user event\n"
                "ev_003: repeated user event\n",
                encoding="utf-8",
            )
            source_record.write_text(
                json.dumps({"role": "user", "content": "repeated user event"}) + "\n",
                encoding="utf-8",
            )
            actual_sha256 = hashlib.sha256(b"repeated user event").hexdigest()
            source_map.write_text(
                json.dumps(
                    {
                        "source_record": str(source_record),
                        "evidence_source_anchors": [
                            {
                                "source_anchor_id": "srca_first",
                                "quote_id": "ev_001",
                                "line_number": 1,
                                "event_ordinal": 1,
                                "event_sha256": actual_sha256,
                            },
                            {
                                "source_anchor_id": "srca_duplicate",
                                "quote_id": "ev_002",
                                "line_number": 1,
                                "event_ordinal": 1,
                                "event_sha256": actual_sha256,
                            },
                            {
                                "source_anchor_id": "srca_forged_hash",
                                "quote_id": "ev_003",
                                "line_number": 1,
                                "event_ordinal": 1,
                                "event_sha256": "f" * 64,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            node = {
                "evidence_refs": [
                    {"path": "sessions/synthetic/evidence.md", "quote_id": quote_id}
                    for quote_id in ("ev_001", "ev_002", "ev_003")
                ],
                "raw_refs": [
                    {"path": "sessions/synthetic/source-map.json", "anchor": anchor}
                    for anchor in ("srca_first", "srca_duplicate", "srca_forged_hash")
                ],
            }

            counts = gate.source_binding_counts(repo, node)

        self.assertEqual(counts.valid_evidence_count, 3)
        self.assertEqual(counts.valid_source_anchor_count, 2)
        self.assertEqual(counts.user_source_anchor_count, 2)
        self.assertEqual(counts.non_user_source_anchor_count, 0)
        self.assertEqual(counts.distinct_user_source_event_count, 1)

    def test_private_ab_requires_paired_external_inputs(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--private-source-record", "/missing/source.jsonl"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stderr)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["failures"][0]["reason"],
            "private_ab_arguments_must_be_paired",
        )


if __name__ == "__main__":
    unittest.main()
