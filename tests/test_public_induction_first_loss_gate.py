import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE = Path("benchmarks/public_induction_first_loss_gate.py").resolve()
FIXTURE = Path("benchmarks/cases/public_induction_recall_fixture.json").resolve()


def load_gate():
    spec = importlib.util.spec_from_file_location("public_induction_first_loss_gate", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load public induction first-loss gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicInductionFirstLossGateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GATE.is_file(), "public induction first-loss gate is missing")
        self.gate = load_gate()

    def test_classifies_exactly_one_ordered_first_loss(self):
        self.assertEqual(
            self.gate.FIRST_LOSS_TAXONOMY,
            (
                "source_rejected",
                "update_failed",
                "archive_audit_failed",
                "session_support_omitted",
                "memory_induction_omitted_or_overcompressed",
                "memory_present_not_top5",
                "top1_not_query_supported",
                "supported",
            ),
        )
        base = {
            "source_rejected": 0,
            "packaged_setup_success": 1,
            "updater_success": 1,
            "archive_audit_success": 1,
            "expected_support_event_count": 1,
            "preserved_support_event_count": 1,
            "active_support_memory_count": 1,
            "support_candidate_at_5_count": 1,
            "supported_gold_package": 1,
        }
        cases = (
            ({**base, "source_rejected": 1, "updater_success": 0}, "source_rejected"),
            ({**base, "packaged_setup_success": 0}, "update_failed"),
            ({**base, "updater_success": 0}, "update_failed"),
            ({**base, "archive_audit_success": 0}, "archive_audit_failed"),
            ({**base, "preserved_support_event_count": 0}, "session_support_omitted"),
            (
                {**base, "active_support_memory_count": 0},
                "memory_induction_omitted_or_overcompressed",
            ),
            ({**base, "support_candidate_at_5_count": 0}, "memory_present_not_top5"),
            ({**base, "supported_gold_package": 0}, "top1_not_query_supported"),
            (base, "supported"),
        )

        for observation, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.gate.classify_first_loss(observation), expected)

    def test_maps_scorer_only_support_ordinals_to_archive_evidence_refs(self):
        row = {
            "question_id": "fixture_multi",
            "question_type": "multi-session",
            "question": "What was combined?",
            "answer": "A combined result",
            "haystack_session_ids": ["gold-a", "gold-b"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00", "2026/01/02 (Fri) 09:00"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "Filler."},
                    {"role": "assistant", "content": "First support.", "has_answer": True},
                ],
                [{"role": "user", "content": "Second support.", "has_answer": True}],
            ],
            "answer_session_ids": ["gold-a", "gold-b"],
        }
        expected = self.gate.scorer_support_event_ordinals(row)
        self.assertEqual(expected, {("gold-a", 2), ("gold-b", 1)})

        with tempfile.TemporaryDirectory() as tmpdir:
            case_root = Path(tmpdir)
            case = self.gate.public_gate.convert_longmemeval_case(row, case_ordinal=1)
            source_a = case_root / "source-records/session-0001/record.jsonl"
            source_b = case_root / "source-records/session-0002/record.jsonl"
            source_a.parent.mkdir(parents=True)
            source_b.parent.mkdir(parents=True)
            source_a.write_text("{}\n", encoding="utf-8")
            source_b.write_text("{}\n", encoding="utf-8")
            archive = case_root / "archive"
            first = archive / "sessions/2026/01/first"
            second = archive / "sessions/2026/01/second"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "meta.json").write_text(
                json.dumps(
                    {
                        "source_record": str(source_a.resolve()),
                        "evidence_path": "sessions/2026/01/first/evidence.md",
                        "source_map_path": "sessions/2026/01/first/source-map.json",
                    }
                ),
                encoding="utf-8",
            )
            (first / "source-map.json").write_text(
                json.dumps(
                    {
                        "evidence_source_anchors": [
                            {"quote_id": "ev_001", "event_ordinal": 2}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (second / "meta.json").write_text(
                json.dumps(
                    {
                        "source_record": str(source_b.resolve()),
                        "evidence_path": "sessions/2026/01/second/evidence.md",
                        "source_map_path": "sessions/2026/01/second/source-map.json",
                    }
                ),
                encoding="utf-8",
            )
            (second / "source-map.json").write_text(
                json.dumps(
                    {
                        "evidence_source_anchors": [
                            {"quote_id": "ev_001", "event_ordinal": 2}
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = self.gate.archived_support_refs(case, case_root, expected)

        self.assertEqual(result["expected_support_event_count"], 2)
        self.assertEqual(result["preserved_support_event_count"], 1)
        self.assertEqual(
            result["support_refs"],
            {("sessions/2026/01/first/evidence.md", "ev_001")},
        )

    def test_tracks_only_active_automatic_support_memories_into_top_five_package(self):
        support_refs = {("sessions/example/evidence.md", "ev_002")}
        records = [
            {
                "memory_id": "mem_active",
                "source": "automatic",
                "evidence_refs": [
                    {"path": "sessions/example/evidence.md", "quote_id": "ev_002"}
                ],
            },
            {
                "memory_id": "mem_inactive",
                "source": "automatic",
                "evidence_refs": ["sessions/example/evidence.md#ev_002"],
            },
            {
                "memory_id": "mem_explicit",
                "source": "explicit",
                "evidence_refs": ["sessions/example/evidence.md#ev_002"],
            },
        ]
        memory_state = self.gate.support_memory_state(
            records,
            support_refs,
            inactive_ids={"mem_inactive"},
        )

        self.assertEqual(memory_state["support_memory_count"], 2)
        self.assertEqual(memory_state["active_support_memory_count"], 1)
        self.assertEqual(memory_state["inactive_support_memory_count"], 1)
        self.assertEqual(memory_state["active_support_memory_ids"], {"mem_active"})

        package = {
            "report_kind": "memory_recall_context_package",
            "answerability": {"status": "supported"},
            "hits": [
                {
                    "rank": 1,
                    "memory_id": "mem_other",
                    "active_current": True,
                    "answerability": {"status": "supported"},
                    "query_support": {"status": "supported"},
                    "summary_drill_paths": ["sessions/other/summary.md"],
                    "evidence_drill_paths": ["sessions/other/evidence.md"],
                },
                {
                    "rank": 2,
                    "memory_id": "mem_active",
                    "active_current": True,
                    "answerability": {"status": "supported"},
                    "query_support": {"status": "supported"},
                    "summary_drill_paths": ["sessions/example/summary.md"],
                    "evidence_drill_paths": ["sessions/example/evidence.md"],
                },
            ],
        }
        package_state = self.gate.package_support_state(
            package,
            memory_state["active_support_memory_ids"],
        )

        self.assertEqual(package_state["context_package_parse_success"], 1)
        self.assertEqual(package_state["support_candidate_at_1_count"], 0)
        self.assertEqual(package_state["support_candidate_at_5_count"], 1)
        self.assertEqual(package_state["supported_gold_package"], 1)

    def test_observes_real_packaged_supported_case_end_to_end(self):
        rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
        row = next(value for value in rows if value["question_id"] == "fixture_temporal")

        with tempfile.TemporaryDirectory() as tmpdir:
            observation = self.gate.observe_packaged_case(
                row,
                case_ordinal=1,
                case_root=Path(tmpdir) / "case",
                runtime_root=Path.cwd(),
            )

        self.assertEqual(observation["packaged_setup_success"], 1)
        self.assertEqual(observation["updater_success"], 1)
        self.assertEqual(observation["archive_audit_success"], 1)
        self.assertIn("baseline_retrievable", observation)
        self.assertEqual(observation["expected_support_event_count"], 1)
        self.assertEqual(observation["preserved_support_event_count"], 1)
        self.assertGreaterEqual(observation["active_support_memory_count"], 1)
        self.assertGreaterEqual(observation["support_candidate_at_5_count"], 1)
        self.assertEqual(observation["supported_gold_package"], 1)
        self.assertEqual(observation["first_loss"], "supported")
        self.assertEqual(observation["gold_label_ingestion_count"], 0)
        self.assertEqual(observation["direct_memory_injection_count"], 0)

    def test_observes_packaged_secret_refusal_as_source_rejected(self):
        fake_secret = "sk-" + "firstlosstest" + ("0" * 20)
        row = {
            "question_id": "fixture_secret",
            "question_type": "single-session-user",
            "question": "What value was provided?",
            "answer": "A value",
            "haystack_session_ids": ["gold-secret"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00"],
            "haystack_sessions": [
                [
                    {
                        "role": "user",
                        "content": f"Use this credential {fake_secret}.",
                        "has_answer": True,
                    }
                ]
            ],
            "answer_session_ids": ["gold-secret"],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            observation = self.gate.observe_packaged_case(
                row,
                case_ordinal=1,
                case_root=Path(tmpdir) / "case",
                runtime_root=Path.cwd(),
            )

        self.assertEqual(observation["updater_success"], 0)
        self.assertEqual(observation["source_rejected"], 1)
        self.assertEqual(observation["first_loss"], "source_rejected")
        self.assertNotIn(fake_secret, json.dumps(observation, sort_keys=True))

    def test_aggregates_exhaustive_taxonomy_and_predeclares_repair_threshold(self):
        observations = []
        for category in self.gate.FIRST_LOSS_TAXONOMY:
            observations.append(
                {
                    "question_type": "synthetic-positive",
                    "is_abstention": 0,
                    "first_loss": category,
                    "packaged_setup_success": 1,
                    "updater_success": 1,
                    "archive_audit_success": 1,
                    "context_package_parse_success": 1,
                    "expected_support_event_count": 1,
                    "preserved_support_event_count": 1,
                    "scorer_support_label_missing_count": 0,
                    "gold_label_ingestion_count": 0,
                    "answer_ingestion_count": 0,
                    "direct_memory_injection_count": 0,
                    "false_promotion_count": 0,
                    "privacy_leak_count": 0,
                }
            )
        observations.extend(
            {
                "question_type": "synthetic-negative",
                "is_abstention": 1,
                "packaged_setup_success": 1,
                "updater_success": 1,
                "archive_audit_success": 1,
                "context_package_parse_success": 1,
                "expected_support_event_count": 0,
                "preserved_support_event_count": 0,
                "abstention_correct": 1,
                "hard_negative_rejected": 1,
                "scorer_support_label_missing_count": 0,
                "gold_label_ingestion_count": 0,
                "answer_ingestion_count": 0,
                "direct_memory_injection_count": 0,
                "false_promotion_count": 0,
                "privacy_leak_count": 0,
            }
            for _ in range(2)
        )

        metrics, counts = self.gate.aggregate_metrics(observations)

        self.assertEqual(metrics["positive_first_loss_attribution_coverage_rate"], 1.0)
        self.assertEqual(metrics["first_loss_partition_invariant_violation_count"], 0)
        for category in self.gate.FIRST_LOSS_TAXONOMY:
            self.assertEqual(metrics[f"{category}_count"], 1)
            self.assertEqual(metrics[f"{category}_rate"], 1 / 8)
            self.assertEqual(counts[f"{category}_rate"], {"numerator": 1, "denominator": 8})
        self.assertEqual(metrics["pre_retrieval_induction_loss_count"], 2)
        self.assertEqual(metrics["retrieval_first_loss_count"], 1)
        self.assertEqual(metrics["query_support_first_loss_count"], 1)
        self.assertEqual(metrics["supported_case_count"], 1)
        self.assertEqual(metrics["hard_negative_rejection_rate"], 1.0)
        self.assertEqual(metrics["abstention_accuracy"], 1.0)

        eligible = self.gate.select_repair_target(
            {
                "session_support_omitted_count": 5,
                "memory_induction_omitted_or_overcompressed_count": 5,
                "source_rejected_count": 0,
                "update_failed_count": 0,
                "archive_audit_failed_count": 0,
                "memory_present_not_top5_count": 0,
                "top1_not_query_supported_count": 0,
            }
        )
        self.assertEqual(eligible["repair_eligible"], 1)
        self.assertEqual(eligible["targeted_defect"], "session_support_omitted")
        self.assertEqual(eligible["targeted_defect_count"], 5)
        self.assertEqual(eligible["targeted_defect_share"], 0.5)

        ineligible = self.gate.select_repair_target(
            {
                "session_support_omitted_count": 4,
                "memory_induction_omitted_or_overcompressed_count": 4,
                "source_rejected_count": 0,
                "update_failed_count": 0,
                "archive_audit_failed_count": 0,
                "memory_present_not_top5_count": 20,
                "top1_not_query_supported_count": 0,
            }
        )
        self.assertEqual(ineligible["repair_eligible"], 0)
        self.assertEqual(ineligible["decision_reason"], "dominant_loss_outside_induction")

    def test_accounts_for_previously_unexplained_positive_partition(self):
        observations = [
            {
                "is_abstention": 0,
                "baseline_retrievable": 0,
                "first_loss": "session_support_omitted",
                "expected_support_event_count": 1,
                "preserved_support_event_count": 0,
            },
            {
                "is_abstention": 0,
                "baseline_retrievable": 0,
                "first_loss": "memory_present_not_top5",
                "expected_support_event_count": 1,
                "preserved_support_event_count": 1,
            },
            {
                "is_abstention": 0,
                "baseline_retrievable": 1,
                "first_loss": "supported",
                "expected_support_event_count": 1,
                "preserved_support_event_count": 1,
            },
        ]

        metrics, counts = self.gate.aggregate_metrics(observations)

        self.assertEqual(metrics["baseline_retrievable_positive_count"], 1)
        self.assertEqual(metrics["previously_unexplained_positive_count"], 2)
        self.assertEqual(
            metrics["previously_unexplained_first_loss_attribution_coverage_rate"],
            1.0,
        )
        self.assertEqual(
            metrics[
                "previously_unexplained_first_loss_partition_invariant_violation_count"
            ],
            0,
        )
        self.assertEqual(
            metrics["previously_unexplained_session_support_omitted_count"],
            1,
        )
        self.assertEqual(
            metrics["previously_unexplained_memory_present_not_top5_count"],
            1,
        )
        self.assertEqual(
            counts["previously_unexplained_session_support_omitted_rate"],
            {"numerator": 1, "denominator": 2},
        )

    def test_fingerprints_runtime_and_emits_aggregate_only_report(self):
        bundle = self.gate.runtime_bundle_fingerprint(Path.cwd())
        self.assertEqual(len(bundle["fingerprint_sha256"]), 64)
        self.assertEqual(bundle["component_count"], len(bundle["components"]))
        self.assertNotIn(str(Path.cwd()), json.dumps(bundle, sort_keys=True))

        observations = [
            {
                "question_type": "single-session-user",
                "is_abstention": 0,
                "first_loss": "session_support_omitted",
                "packaged_setup_success": 1,
                "updater_success": 1,
                "archive_audit_success": 1,
                "context_package_parse_success": 1,
                "expected_support_event_count": 1,
                "preserved_support_event_count": 0,
                "scorer_support_label_missing_count": 0,
                "gold_label_ingestion_count": 0,
                "answer_ingestion_count": 0,
                "direct_memory_injection_count": 0,
                "false_promotion_count": 0,
                "privacy_leak_count": 0,
            },
            {
                "question_type": "single-session-user",
                "is_abstention": 1,
                "packaged_setup_success": 1,
                "updater_success": 1,
                "archive_audit_success": 1,
                "context_package_parse_success": 1,
                "expected_support_event_count": 0,
                "preserved_support_event_count": 0,
                "abstention_correct": 1,
                "hard_negative_rejected": 1,
                "scorer_support_label_missing_count": 0,
                "gold_label_ingestion_count": 0,
                "answer_ingestion_count": 0,
                "direct_memory_injection_count": 0,
                "false_promotion_count": 0,
                "privacy_leak_count": 0,
            },
        ]
        report = self.gate.build_report(
            cohort="calibration",
            mode="synthetic_contract",
            observations=observations,
            dataset={
                "source": "synthetic",
                "source_url": "offline",
                "sha256": "0" * 64,
                "input_record_count": 2,
            },
            selection={
                "cohort": "calibration",
                "selected_case_count": 2,
                "selected_fingerprint_sha256": "1" * 64,
                "cohort_overlap_count": 0,
                "holdout_selection_fingerprint_match": 1,
                "calibration_selection_fingerprint_match": 1,
            },
            runtime_bundle=bundle,
            selected_rows=[],
            local_paths=[],
        )

        self.assertEqual(report["report_kind"], "public_induction_first_loss_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["readiness_status"], "induction_no_go")
        self.assertEqual(len(report["configuration"]["fingerprint_sha256"]), 64)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertNotIn('"question":', json.dumps(report, sort_keys=True))
        self.assertNotIn('"answer":', json.dumps(report, sort_keys=True))

    def test_holdout_decision_requires_gain_and_all_safety_invariants(self):
        baseline = {
            "session_support_omitted_count": 8,
            "memory_induction_omitted_or_overcompressed_count": 0,
            "pre_retrieval_induction_loss_count": 8,
            "source_rejected_count": 0,
            "update_failed_count": 0,
            "archive_audit_failed_count": 0,
            "packaged_setup_success_rate": 1.0,
            "updater_success_rate": 1.0,
            "archive_audit_success_rate": 1.0,
        }
        candidate = {
            "session_support_omitted_count": 6,
            "memory_induction_omitted_or_overcompressed_count": 0,
            "pre_retrieval_induction_loss_count": 6,
            "source_rejected_count": 0,
            "update_failed_count": 0,
            "archive_audit_failed_count": 0,
            "packaged_setup_success_rate": 1.0,
            "updater_success_rate": 1.0,
            "archive_audit_success_rate": 1.0,
            "positive_first_loss_attribution_coverage_rate": 1.0,
            "first_loss_partition_invariant_violation_count": 0,
            "hard_negative_rejection_rate": 1.0,
            "abstention_accuracy": 1.0,
            "false_promotion_count": 0,
            "gold_label_ingestion_count": 0,
            "direct_memory_injection_count": 0,
            "privacy_leak_count": 0,
        }

        passed = self.gate.evaluate_holdout_decision(
            "session_support_omitted",
            baseline,
            candidate,
        )
        self.assertEqual(passed["readiness_status"], "induction_repair_go")
        self.assertEqual(passed["recovered_holdout_positive_count"], 2)
        self.assertEqual(passed["targeted_holdout_loss_reduction_rate"], 0.25)

        insufficient = self.gate.evaluate_holdout_decision(
            "session_support_omitted",
            baseline,
            {**candidate, "session_support_omitted_count": 7},
        )
        self.assertEqual(insufficient["readiness_status"], "induction_no_go")
        self.assertEqual(insufficient["decision_reason"], "insufficient_holdout_gain")

        stage_shift = self.gate.evaluate_holdout_decision(
            "session_support_omitted",
            baseline,
            {
                **candidate,
                "memory_induction_omitted_or_overcompressed_count": 2,
                "pre_retrieval_induction_loss_count": 8,
            },
        )
        self.assertEqual(stage_shift["readiness_status"], "induction_no_go")
        self.assertEqual(stage_shift["decision_reason"], "insufficient_holdout_gain")
        self.assertEqual(stage_shift["recovered_pre_retrieval_positive_count"], 0)

        unsafe = self.gate.evaluate_holdout_decision(
            "session_support_omitted",
            baseline,
            {**candidate, "privacy_leak_count": 1},
        )
        self.assertEqual(unsafe["readiness_status"], "induction_no_go")
        self.assertEqual(unsafe["decision_reason"], "safety_regression")

        masked_pipeline_failure = self.gate.evaluate_holdout_decision(
            "session_support_omitted",
            baseline,
            {**candidate, "updater_success_rate": 0.975},
        )
        self.assertEqual(
            masked_pipeline_failure["readiness_status"],
            "induction_no_go",
        )
        self.assertEqual(
            masked_pipeline_failure["decision_reason"],
            "safety_regression",
        )

    def test_offline_cli_runs_packaged_fixture_and_emits_required_metrics(self):
        result = subprocess.run(
            [sys.executable, str(GATE), "--offline-fixture"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "public_induction_first_loss_gate")
        self.assertEqual(report["mode"], "offline_fixture")
        self.assertEqual(report["cohort"], "offline")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["readiness_status"], "induction_no_go")
        self.assertEqual(report["metrics"]["positive_case_count"], 6)
        self.assertEqual(report["metrics"]["abstention_case_count"], 2)
        self.assertEqual(
            report["metrics"]["positive_first_loss_attribution_coverage_rate"],
            1.0,
        )
        self.assertEqual(
            report["metrics"]["first_loss_partition_invariant_violation_count"],
            0,
        )
        for category in self.gate.FIRST_LOSS_TAXONOMY:
            self.assertIn(f"{category}_count", report["metrics"])
            self.assertIn(f"{category}_rate", report["metrics"])
        for metric in (
            "baseline_retrievable_positive_count",
            "previously_unexplained_positive_count",
            "previously_unexplained_first_loss_attribution_coverage_rate",
            "previously_unexplained_first_loss_partition_invariant_violation_count",
            "pre_retrieval_induction_loss_count",
            "retrieval_first_loss_count",
            "query_support_first_loss_count",
            "supported_case_count",
            "gold_label_ingestion_count",
            "direct_memory_injection_count",
            "false_promotion_count",
            "privacy_leak_count",
        ):
            self.assertIn(metric, report["metrics"])
        self.assertEqual(report["metrics"]["gold_label_ingestion_count"], 0)
        self.assertEqual(report["metrics"]["direct_memory_injection_count"], 0)
        self.assertEqual(report["metrics"]["false_promotion_count"], 0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertEqual(
            report["metrics"][
                "previously_unexplained_first_loss_attribution_coverage_rate"
            ],
            1.0,
        )
        self.assertEqual(
            report["metrics"][
                "previously_unexplained_first_loss_partition_invariant_violation_count"
            ],
            0,
        )
        self.assertEqual(len(report["dataset"]["sha256"]), 64)
        self.assertEqual(len(report["selection"]["selected_fingerprint_sha256"]), 64)
        self.assertEqual(len(report["runtime_bundle"]["fingerprint_sha256"]), 64)
        self.assertEqual(len(report["configuration"]["fingerprint_sha256"]), 64)

    def test_public_cli_fails_closed_on_unpinned_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "wrong.json"
            public_input.write_text("[]\n", encoding="utf-8")
            work_dir = root / "work"
            report_file = root / "report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "--public-input",
                    str(public_input),
                    "--dataset-source-url",
                    "https://example.invalid/pinned.json",
                    "--cohort",
                    "calibration",
                    "--work-dir",
                    str(work_dir),
                    "--report-file",
                    str(report_file),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report, json.loads(report_file.read_text(encoding="utf-8")))
            self.assertEqual(report["report_kind"], "public_induction_first_loss_gate")
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["readiness_status"], "induction_no_go")
            self.assertEqual(report["decision_reason"], "safety_regression")
            self.assertEqual(report["failure_reason"], "dataset_sha_mismatch")
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertNotIn(str(public_input), json.dumps(report, sort_keys=True))

    def test_rejects_failed_aggregate_report_as_frozen_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "calibration.json"
            report_path.write_text(
                json.dumps(
                    {
                        "report_kind": "public_induction_first_loss_gate",
                        "cohort": "calibration",
                        "status": "failed",
                        "dataset": {"sha256": self.gate.OFFICIAL_DATASET_SHA256},
                        "selection": {
                            "selected_fingerprint_sha256": self.gate.CALIBRATION_FINGERPRINT
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "contract mismatch"):
                self.gate._load_aggregate_report(
                    str(report_path),
                    cohort="calibration",
                )

    def test_rejects_candidate_holdout_report_as_frozen_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "candidate-holdout.json"
            report_path.write_text(
                json.dumps(
                    {
                        "report_kind": "public_induction_first_loss_gate",
                        "cohort": "holdout",
                        "status": "passed",
                        "readiness_status": "induction_repair_go",
                        "dataset": {"sha256": self.gate.OFFICIAL_DATASET_SHA256},
                        "selection": {
                            "selected_fingerprint_sha256": self.gate.HOLDOUT_FINGERPRINT
                        },
                        "configuration": {"candidate_strategy_count": 1},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "frozen baseline contract mismatch"):
                self.gate._load_aggregate_report(
                    str(report_path),
                    cohort="holdout",
                )


if __name__ == "__main__":
    unittest.main()
