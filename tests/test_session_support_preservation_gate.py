import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


GATE = Path("benchmarks/session_support_preservation_gate.py").resolve()


def load_gate():
    spec = importlib.util.spec_from_file_location("session_support_preservation_gate", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load session support preservation gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SessionSupportPreservationGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load_gate()

    def test_classifies_exactly_one_ordered_support_event_loss(self):
        self.assertEqual(
            self.gate.SUPPORT_EVENT_TAXONOMY,
            (
                "source_event_missing_after_extraction",
                "durability_filter_rejected",
                "no_summary_channel_candidate",
                "evidence_budget_evicted",
                "evidence_bound_to_wrong_ordinal",
                "evidence_source_entry_missing",
                "source_anchor_materialization_failed",
                "preserved",
            ),
        )
        base = {
            "source_event_present": 1,
            "durability_candidate_present": 1,
            "summary_channel_candidate_present": 1,
            "evidence_candidate_present": 1,
            "evidence_bound_to_expected_locator": 1,
            "evidence_source_entry_present": 1,
            "source_anchor_present": 1,
        }
        cases = (
            ({**base, "source_event_present": 0}, "source_event_missing_after_extraction"),
            ({**base, "durability_candidate_present": 0}, "durability_filter_rejected"),
            ({**base, "summary_channel_candidate_present": 0}, "no_summary_channel_candidate"),
            ({**base, "evidence_candidate_present": 0}, "evidence_budget_evicted"),
            ({**base, "evidence_bound_to_expected_locator": 0}, "evidence_bound_to_wrong_ordinal"),
            ({**base, "evidence_source_entry_present": 0}, "evidence_source_entry_missing"),
            ({**base, "source_anchor_present": 0}, "source_anchor_materialization_failed"),
            (base, "preserved"),
        )
        for trace, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.gate.classify_support_event_trace(trace), expected)

    def test_maps_longmemeval_turns_to_complete_jsonl_source_locators(self):
        row = {
            "haystack_session_ids": ["session-a"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "Filler."},
                    {"role": "assistant", "content": "Support.", "has_answer": True},
                ]
            ],
            "answer_session_ids": ["session-a"],
        }
        self.assertEqual(
            self.gate.scorer_support_source_locators(row),
            {("session-a", 2, 1)},
        )
        self.assertNotEqual(
            self.gate.scorer_support_source_locators(row),
            {("session-a", 1, 2)},
        )

    def test_detects_same_text_binding_to_an_earlier_event(self):
        events = [
            self.gate.EventProbe("assistant", "Repeated support.", 1, 1),
            self.gate.EventProbe("assistant", "Repeated support.", 2, 1),
        ]
        summary = {
            "facts": ["Repeated support."],
            "evidence": ["Repeated support."],
            "evidence_sources": [
                {"quote_id": "ev_001", "line_number": 1, "event_ordinal": 1}
            ],
        }
        trace = self.gate.trace_support_event(
            expected_locator=(2, 1),
            events=events,
            summary_data=summary,
            source_anchors=[
                {"quote_id": "ev_001", "line_number": 1, "event_ordinal": 1}
            ],
            text_key=lambda value: value.strip().lower(),
            durable_keys=lambda event: {event.text.strip().lower()},
        )
        self.assertEqual(trace["category"], "evidence_bound_to_wrong_ordinal")
        self.assertEqual(trace["evidence_candidate_present"], 1)
        self.assertEqual(trace["evidence_source_entry_present"], 1)
        self.assertEqual(trace["evidence_bound_to_expected_locator"], 0)

    def test_packaged_sidecar_uses_complete_locator_and_corrects_v244_false_omission(self):
        row = {
            "question_id": "fixture_complete_locator",
            "question_type": "single-session-assistant",
            "question": "Which source-anchor rule was verified?",
            "answer": "Use stable source anchors for durable evidence.",
            "haystack_session_ids": ["support-session"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "State the source-anchor rule."},
                    {
                        "role": "assistant",
                        "content": "Verified rule: use stable source anchors for durable evidence.",
                        "has_answer": True,
                    },
                ]
            ],
            "answer_session_ids": ["support-session"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            observation = self.gate.observe_packaged_case(
                row,
                case_ordinal=1,
                case_root=Path(tmpdir) / "case",
                runtime_root=Path.cwd(),
            )

        self.assertEqual(observation["gold_label_ingestion_count"], 0)
        self.assertEqual(observation["answer_ingestion_count"], 0)
        self.assertEqual(observation["expected_support_event_count"], 1)
        self.assertEqual(observation["preserved_support_event_count"], 1)
        self.assertEqual(observation["v244_preserved_support_event_count"], 0)
        self.assertEqual(observation["support_event_traces"][0]["category"], "preserved")

    def test_packaged_sidecar_detects_duplicate_text_wrong_ordinal(self):
        row = {
            "question_id": "fixture_duplicate_locator",
            "question_type": "single-session-assistant",
            "question": "Which rule was repeated?",
            "answer": "Use stable source anchors.",
            "haystack_session_ids": ["duplicate-session"],
            "haystack_dates": ["2026/01/01 (Thu) 09:00"],
            "haystack_sessions": [
                [
                    {
                        "role": "assistant",
                        "content": "Verified rule: use stable source anchors.",
                    },
                    {
                        "role": "assistant",
                        "content": "Verified rule: use stable source anchors.",
                        "has_answer": True,
                    },
                ]
            ],
            "answer_session_ids": ["duplicate-session"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            observation = self.gate.observe_packaged_case(
                row,
                case_ordinal=1,
                case_root=Path(tmpdir) / "case",
                runtime_root=Path.cwd(),
            )

        self.assertEqual(observation["expected_support_event_count"], 1)
        self.assertEqual(observation["preserved_support_event_count"], 0)
        self.assertEqual(
            observation["support_event_traces"][0]["category"],
            "evidence_bound_to_wrong_ordinal",
        )

    def test_aggregates_event_partition_and_selects_dominant_allowed_loss(self):
        observations = []
        for index in range(6):
            observations.append(
                {
                    "is_abstention": 0,
                    "first_loss": "session_support_omitted",
                    "support_event_traces": [
                        {"category": "evidence_bound_to_wrong_ordinal"}
                    ],
                    "expected_support_event_count": 1,
                    "preserved_support_event_count": 0,
                }
            )
        observations.extend(
            {
                "is_abstention": 0,
                "first_loss": "session_support_omitted",
                "support_event_traces": [
                    {"category": "no_summary_channel_candidate"}
                ],
                "expected_support_event_count": 1,
                "preserved_support_event_count": 0,
            }
            for _ in range(4)
        )
        metrics, counts = self.gate.aggregate_support_metrics(observations)
        decision = self.gate.select_session_repair_target(observations, metrics)

        self.assertEqual(metrics["support_event_attribution_coverage_rate"], 1.0)
        self.assertEqual(metrics["support_event_partition_invariant_violation_count"], 0)
        self.assertEqual(metrics["evidence_bound_to_wrong_ordinal_count"], 6)
        self.assertEqual(
            counts["evidence_bound_to_wrong_ordinal_rate"],
            {"numerator": 6, "denominator": 10},
        )
        self.assertEqual(decision["repair_eligible"], 1)
        self.assertEqual(decision["targeted_defect"], "evidence_bound_to_wrong_ordinal")
        self.assertEqual(decision["targeted_defect_case_count"], 6)
        self.assertEqual(decision["targeted_defect_case_share"], 0.6)

    def test_aggregates_v244_locator_disagreement_without_changing_frozen_baseline(self):
        observations = [
            {
                "is_abstention": 0,
                "first_loss": "supported",
                "v244_first_loss": "session_support_omitted",
                "support_event_traces": [{"category": "preserved"}],
                "expected_support_event_count": 1,
                "preserved_support_event_count": 1,
                "v244_preserved_support_event_count": 0,
            },
            {
                "is_abstention": 0,
                "first_loss": "session_support_omitted",
                "v244_first_loss": "session_support_omitted",
                "support_event_traces": [
                    {"category": "no_summary_channel_candidate"}
                ],
                "expected_support_event_count": 1,
                "preserved_support_event_count": 0,
                "v244_preserved_support_event_count": 0,
            },
        ]
        metrics, _ = self.gate.aggregate_support_metrics(observations)
        self.assertEqual(metrics["v244_preserved_support_event_count"], 0)
        self.assertEqual(metrics["v244_session_support_omitted_count"], 2)
        self.assertEqual(metrics["v244_locator_support_status_disagreement_count"], 1)

    def test_validates_exact_v244_frozen_baseline_contract(self):
        report = {
            "report_kind": "public_induction_first_loss_gate",
            "cohort": "calibration",
            "status": "passed",
            "dataset": {"sha256": self.gate.OFFICIAL_DATASET_SHA256},
            "selection": {
                "selected_fingerprint_sha256": self.gate.CALIBRATION_FINGERPRINT
            },
            "runtime_bundle": {
                "fingerprint_sha256": self.gate.V244_BASELINE_RUNTIME_FINGERPRINT
            },
            "metrics": {
                "session_support_omitted_count": 15,
                "preserved_support_event_count": 19,
                "expected_support_event_count": 56,
            },
        }
        contract = self.gate.validate_v244_baseline_report(report, cohort="calibration")
        self.assertEqual(contract["status"], "reproduced")
        self.assertEqual(contract["session_support_omitted_count"], 15)

        drifted = json.loads(json.dumps(report))
        drifted["metrics"]["preserved_support_event_count"] = 20
        with self.assertRaisesRegex(SystemExit, "V2.44 baseline contract mismatch"):
            self.gate.validate_v244_baseline_report(drifted, cohort="calibration")

    def test_public_runner_reports_v244_baseline_mismatch_as_terminal_no_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_input = root / "longmemeval.json"
            v244_report = root / "v244.json"
            public_input.write_text("[]\n", encoding="utf-8")
            v244_report.write_text("{}\n", encoding="utf-8")
            args = argparse.Namespace(
                public_input=str(public_input),
                dataset_source_url="https://example.invalid/longmemeval.json",
                cohort="calibration",
                work_dir=str(root / "work"),
                report_file=str(root / "report.json"),
                runtime_root=str(Path.cwd()),
                v244_report=str(v244_report),
                calibration_report=None,
                baseline_report=None,
                candidate_strategy=None,
            )
            selection = {
                "holdout_selection_fingerprint_match": 1,
                "calibration_selection_fingerprint_match": 1,
                "cohort_overlap_count": 0,
            }
            with (
                mock.patch.object(
                    self.gate.first_loss_gate.public_gate,
                    "_file_sha256",
                    return_value=self.gate.OFFICIAL_DATASET_SHA256,
                ),
                mock.patch.object(
                    self.gate.first_loss_gate.query_calibration_gate,
                    "select_disjoint_cohorts",
                    return_value=([], []),
                ),
                mock.patch.object(
                    self.gate,
                    "_selection_payload",
                    return_value=selection,
                ),
            ):
                report = self.gate.run_public_dataset(args)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["decision_reason"], "baseline_not_reproducible")
        self.assertEqual(report["failure_reason"], "v244_baseline_contract_mismatch")

    def test_validates_candidate_freeze_against_runtime_strategy_and_configuration(self):
        runtime = {"fingerprint_sha256": "a" * 64}
        configuration_fingerprint = self.gate.candidate_configuration_fingerprint(
            "stable_event_identity_v1"
        )
        calibration = {
            "report_kind": "session_support_preservation_gate",
            "cohort": "calibration",
            "status": "passed",
            "readiness_status": "candidate_frozen",
            "configuration": {"fingerprint_sha256": configuration_fingerprint},
            "candidate_freeze": {
                "candidate_strategy": "stable_event_identity_v1",
                "runtime_bundle_fingerprint_sha256": "a" * 64,
                "candidate_strategy_fingerprint_sha256": self.gate.sha256_text(
                    "stable_event_identity_v1"
                ),
                "configuration_fingerprint_sha256": configuration_fingerprint,
            },
        }
        self.gate.validate_candidate_freeze(
            calibration,
            candidate_strategy="stable_event_identity_v1",
            runtime_bundle=runtime,
        )
        with self.assertRaisesRegex(SystemExit, "candidate freeze mismatch"):
            self.gate.validate_candidate_freeze(
                calibration,
                candidate_strategy="different_strategy",
                runtime_bundle=runtime,
            )
        drifted = json.loads(json.dumps(calibration))
        drifted["candidate_freeze"]["configuration_fingerprint_sha256"] = "b" * 64
        with self.assertRaisesRegex(SystemExit, "candidate freeze mismatch"):
            self.gate.validate_candidate_freeze(
                drifted,
                candidate_strategy="stable_event_identity_v1",
                runtime_bundle=runtime,
            )

    def test_candidate_configuration_fingerprint_covers_all_decision_policy(self):
        payload = self.gate.candidate_configuration_payload(
            "stable_event_identity_v1"
        )

        self.assertEqual(payload["minimum_case_count"], 5)
        self.assertEqual(payload["minimum_case_share"], 0.40)
        self.assertEqual(payload["minimum_calibration_recovery"], 3)
        self.assertEqual(payload["minimum_calibration_event_gain"], 3)
        self.assertEqual(payload["minimum_holdout_recovery"], 4)
        self.assertEqual(payload["minimum_holdout_reduction"], 0.25)
        self.assertEqual(payload["minimum_holdout_event_gain"], 4)
        self.assertIn(
            "no_summary_channel_candidate",
            payload["allowed_repair_surfaces"],
        )
        self.assertIn(
            "archive_audit_failed_count",
            payload["safety_nonincreasing_count_metrics"],
        )
        self.assertIn(
            "privacy_leak_count",
            payload["safety_zero_count_metrics"],
        )

    def test_public_cli_requires_v244_report_and_candidate_pairing(self):
        common = [
            "--public-input",
            "/tmp/input.json",
            "--dataset-source-url",
            "https://example.invalid/dataset.json",
            "--cohort",
            "calibration",
            "--work-dir",
            "/tmp/work",
            "--report-file",
            "/tmp/report.json",
        ]
        with self.assertRaises(SystemExit):
            self.gate.parse_args(common)
        args = self.gate.parse_args(
            [*common, "--v244-report", "/tmp/v244.json"]
        )
        self.assertEqual(args.cohort, "calibration")
        with self.assertRaises(SystemExit):
            self.gate.parse_args(
                [
                    *common,
                    "--v244-report",
                    "/tmp/v244.json",
                    "--candidate-strategy",
                    "stable_event_identity_v1",
                ]
            )

    def test_rejects_a_dominant_loss_outside_the_allowed_repair_surface(self):
        observations = [
            {
                "is_abstention": 0,
                "first_loss": "session_support_omitted",
                "support_event_traces": [
                    {"category": "source_event_missing_after_extraction"}
                ],
                "expected_support_event_count": 1,
                "preserved_support_event_count": 0,
            }
            for _ in range(6)
        ]
        metrics, _ = self.gate.aggregate_support_metrics(observations)
        decision = self.gate.select_session_repair_target(observations, metrics)
        self.assertEqual(decision["repair_eligible"], 0)
        self.assertEqual(decision["targeted_defect"], "source_event_missing_after_extraction")
        self.assertEqual(decision["decision_reason"], "dominant_loss_outside_allowed_surface")

    def test_reports_no_target_when_no_session_support_case_is_omitted(self):
        metrics, _ = self.gate.aggregate_support_metrics([])

        decision = self.gate.select_session_repair_target([], metrics)

        self.assertIsNone(decision["targeted_defect"])
        self.assertEqual(decision["targeted_defect_case_count"], 0)
        self.assertEqual(decision["session_support_omitted_case_count"], 0)
        self.assertEqual(decision["decision_reason"], "no_dominant_session_loss")

    def test_calibration_requires_three_recoveries_before_freezing(self):
        baseline = self.gate.safe_metric_fixture(
            session_support_omitted_count=15,
            pre_retrieval_induction_loss_count=15,
            preserved_support_event_count=19,
            expected_support_event_count=56,
        )
        passing = self.gate.safe_metric_fixture(
            session_support_omitted_count=12,
            pre_retrieval_induction_loss_count=12,
            preserved_support_event_count=22,
            expected_support_event_count=56,
        )
        failing = {**passing, "session_support_omitted_count": 13}

        self.assertEqual(
            self.gate.evaluate_calibration_candidate(baseline, passing)["readiness_status"],
            "candidate_frozen",
        )
        self.assertEqual(
            self.gate.evaluate_calibration_candidate(baseline, failing)["decision_reason"],
            "calibration_gain_insufficient",
        )

    def test_calibration_rejects_nominal_gain_that_moves_loss_to_archive_audit(self):
        baseline = self.gate.safe_metric_fixture(
            archive_audit_failed_count=6,
            session_support_omitted_count=19,
            pre_retrieval_induction_loss_count=19,
            preserved_support_event_count=4,
            expected_support_event_count=56,
        )
        candidate = self.gate.safe_metric_fixture(
            archive_audit_failed_count=28,
            session_support_omitted_count=0,
            pre_retrieval_induction_loss_count=0,
            preserved_support_event_count=10,
            expected_support_event_count=56,
        )

        decision = self.gate.evaluate_calibration_candidate(baseline, candidate)

        self.assertEqual(decision["gain_passed"], 1)
        self.assertEqual(decision["safety_passed"], 0)
        self.assertEqual(decision["readiness_status"], "session_support_no_go")
        self.assertEqual(decision["decision_reason"], "safety_regression")

    def test_holdout_requires_four_recoveries_quarter_reduction_and_event_gain(self):
        baseline = self.gate.safe_metric_fixture(
            session_support_omitted_count=15,
            pre_retrieval_induction_loss_count=15,
            preserved_support_event_count=19,
            expected_support_event_count=46,
        )
        candidate = self.gate.safe_metric_fixture(
            session_support_omitted_count=11,
            pre_retrieval_induction_loss_count=11,
            preserved_support_event_count=23,
            expected_support_event_count=46,
        )
        decision = self.gate.evaluate_holdout_candidate(baseline, candidate)
        self.assertEqual(decision["readiness_status"], "session_support_repair_go")
        self.assertEqual(decision["decision_reason"], "holdout_gain_and_safety_passed")
        self.assertEqual(decision["recovered_session_support_case_count"], 4)
        self.assertGreaterEqual(decision["session_support_omission_reduction_rate"], 0.25)
        self.assertEqual(decision["support_event_preservation_gain_count"], 4)

        shifted = {**candidate, "memory_induction_omitted_or_overcompressed_count": 4}
        shifted_decision = self.gate.evaluate_holdout_candidate(baseline, shifted)
        self.assertEqual(shifted_decision["readiness_status"], "session_support_no_go")
        self.assertEqual(shifted_decision["decision_reason"], "insufficient_holdout_gain")

    def test_report_is_aggregate_only_and_does_not_render_event_traces(self):
        observations = [
            {
                "is_abstention": 0,
                "first_loss": "session_support_omitted",
                "support_event_traces": [
                    {
                        "category": "no_summary_channel_candidate",
                        "forbidden_source_content": "do-not-render",
                    }
                ],
                "expected_support_event_count": 1,
                "preserved_support_event_count": 0,
            }
        ]
        report = self.gate.build_report(
            cohort="offline",
            mode="offline_fixture",
            observations=observations,
            dataset={"source": "synthetic", "sha256": "0" * 64},
            selection={"cohort": "offline", "cohort_overlap_count": 0},
            runtime_bundle={"fingerprint_sha256": "1" * 64},
        )
        rendered = json.dumps(report, sort_keys=True)
        self.assertNotIn("do-not-render", rendered)
        self.assertNotIn("support_event_traces", report)
        self.assertFalse(report["privacy"]["support_event_traces_rendered"])
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)

    def test_offline_gate_passes_with_public_data_free_fixture(self):
        completed = subprocess.run(
            [sys.executable, str(GATE), "--offline-fixture"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["report_kind"], "session_support_preservation_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["metrics"]["support_event_attribution_coverage_rate"], 1.0)
        self.assertEqual(
            report["metrics"]["support_event_partition_invariant_violation_count"],
            0,
        )
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])


if __name__ == "__main__":
    unittest.main()
