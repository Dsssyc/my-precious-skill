import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path("benchmarks/public_query_support_calibration_gate.py").resolve()
PUBLIC_FIXTURE = Path("benchmarks/cases/public_induction_recall_fixture.json").resolve()


def load_gate():
    spec = importlib.util.spec_from_file_location("public_query_support_calibration_gate", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load public query-support calibration gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PublicQuerySupportCalibrationGateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "public query-support calibration gate is missing")
        self.gate = load_gate()
        self.public_rows = json.loads(PUBLIC_FIXTURE.read_text(encoding="utf-8"))

    @staticmethod
    def importance(token):
        return {
            "alpha": 1,
            "durable": 2,
            "context": 2,
            "v23ledger": 4,
            "policy": 1,
            "exactanswer": 3,
            "weakonly": 2,
            "support": 2,
            "coverage": 2,
            "marker": 1,
        }[token]

    def test_predeclared_policy_matrix_is_frozen(self):
        complete = {
            "matched_tokens": ["alpha", "durable"],
            "missing_tokens": [],
            "strict_token_coverage": False,
            "meaningful_token_coverage": True,
        }
        partial_positive = {
            "matched_tokens": ["alpha", "durable"],
            "missing_tokens": ["context"],
            "strict_token_coverage": False,
            "meaningful_token_coverage": False,
        }
        broad_negative = {
            "matched_tokens": ["v23ledger", "policy"],
            "missing_tokens": ["exactanswer"],
            "strict_token_coverage": False,
            "meaningful_token_coverage": False,
        }
        weak_negative = {
            "matched_tokens": ["weakonly", "support"],
            "missing_tokens": ["coverage", "marker"],
            "strict_token_coverage": False,
            "meaningful_token_coverage": False,
        }

        self.assertEqual(
            self.gate.POLICY_NAMES,
            ("strict_v1", "weighted_partial_060_v1", "weighted_partial_050_specific_v1"),
        )
        self.assertTrue(self.gate.policy_supports(complete, self.importance, "strict_v1"))
        self.assertFalse(self.gate.policy_supports(partial_positive, self.importance, "strict_v1"))
        self.assertTrue(
            self.gate.policy_supports(partial_positive, self.importance, "weighted_partial_060_v1")
        )
        self.assertTrue(
            self.gate.policy_supports(partial_positive, self.importance, "weighted_partial_050_specific_v1")
        )
        self.assertTrue(
            self.gate.policy_supports(broad_negative, self.importance, "weighted_partial_060_v1")
        )
        self.assertFalse(
            self.gate.policy_supports(weak_negative, self.importance, "weighted_partial_060_v1")
        )
        self.assertTrue(
            self.gate.policy_supports(weak_negative, self.importance, "weighted_partial_050_specific_v1")
        )
        with self.assertRaisesRegex(ValueError, "unknown query-support policy"):
            self.gate.policy_supports(complete, self.importance, "unbounded-policy")

    def test_candidate_selection_rejects_unsafe_or_low_recall_policies(self):
        policy_metrics = {
            "strict_v1": {
                "gold_candidate_count": 5,
                "gold_candidate_support_rate": 0.2,
                "supported_decision_precision": 1.0,
                "abstention_accuracy": 1.0,
                "hard_negative_rejection_rate": 1.0,
            },
            "weighted_partial_060_v1": {
                "gold_candidate_count": 5,
                "gold_candidate_support_rate": 1.0,
                "supported_decision_precision": 1.0,
                "abstention_accuracy": 1.0,
                "hard_negative_rejection_rate": 2 / 3,
            },
            "weighted_partial_050_specific_v1": {
                "gold_candidate_count": 5,
                "gold_candidate_support_rate": 1.0,
                "supported_decision_precision": 0.75,
                "abstention_accuracy": 0.8,
                "hard_negative_rejection_rate": 1 / 3,
            },
        }

        decision = self.gate.select_candidate_policy(policy_metrics)

        self.assertIsNone(decision["selected_policy"])
        self.assertEqual(decision["decision_reason"], "no_safe_policy")
        self.assertEqual(decision["selected_policy_count"], 0)
        self.assertIn("gold_candidate_support_rate_below_threshold", decision["rejections"]["strict_v1"])
        self.assertIn(
            "hard_negative_rejection_rate_below_threshold",
            decision["rejections"]["weighted_partial_060_v1"],
        )

    def test_candidate_selection_requires_lifecycle_and_malformed_safety(self):
        safe_metrics = {
            "gold_candidate_count": 5,
            "gold_candidate_support_rate": 1.0,
            "supported_decision_precision": 1.0,
            "abstention_accuracy": 1.0,
            "hard_negative_rejection_rate": 1.0,
            "inactive_lifecycle_rejection_rate": 1.0,
            "malformed_missing_fail_closed_rate": 1.0,
        }
        policy_metrics = {
            "strict_v1": {**safe_metrics, "inactive_lifecycle_rejection_rate": 0.0},
            "weighted_partial_060_v1": {
                **safe_metrics,
                "malformed_missing_fail_closed_rate": 0.5,
            },
            "weighted_partial_050_specific_v1": {
                **safe_metrics,
                "inactive_lifecycle_rejection_rate": 0.5,
            },
        }

        decision = self.gate.select_candidate_policy(policy_metrics)

        self.assertIsNone(decision["selected_policy"])
        self.assertIn(
            "inactive_lifecycle_rejection_rate_below_threshold",
            decision["rejections"]["strict_v1"],
        )
        self.assertIn(
            "malformed_missing_fail_closed_rate_below_threshold",
            decision["rejections"]["weighted_partial_060_v1"],
        )

    def test_supported_abstention_is_always_false_support(self):
        outcome = self.gate.score_policy_outcome(
            supported_memory_ids={"mem_gold_like"},
            active_gold_memory_ids={"mem_gold_like"},
            is_abstention=True,
        )

        self.assertEqual(
            outcome,
            {
                "supported_decision": 1,
                "supported_gold_decision": 0,
                "false_support": 1,
                "abstention_correct": 0,
            },
        )

    def test_frozen_ranking_drift_ignores_abstention_baselines(self):
        observations = [
            {
                "is_abstention": 0,
                "baseline_retrievable": 1,
                "gold_candidate_at_1": 1,
                "gold_candidate_at_5": 1,
            }
            for _ in range(6)
        ]
        observations.extend(
            {
                "is_abstention": 0,
                "baseline_retrievable": 1,
                "gold_candidate_at_1": 0,
                "gold_candidate_at_5": 0,
            }
            for _ in range(7)
        )
        observations.extend(
            {
                "is_abstention": 1,
                "baseline_retrievable": 1,
                "gold_candidate_at_1": 0,
                "gold_candidate_at_5": 0,
            }
            for _ in range(5)
        )

        self.assertEqual(self.gate.frozen_holdout_ranking_drift(observations), 0)

    def test_disjoint_selection_excludes_frozen_holdout_ids(self):
        rows = []
        for question_type in self.gate.public_gate.POSITIVE_QUESTION_TYPES:
            for suffix in ("a", "b"):
                rows.append(
                    {
                        "question_id": f"{question_type}-{suffix}",
                        "question_type": question_type,
                    }
                )
        rows.extend(
            {"question_id": f"abs-{suffix}_abs", "question_type": "multi-session"}
            for suffix in ("a", "b")
        )

        holdout, calibration = self.gate.select_disjoint_cohorts(
            rows,
            holdout_seed="holdout",
            calibration_seed="calibration",
            positive_per_type=1,
            abstention_count=1,
        )

        holdout_ids = {row["question_id"] for row in holdout}
        calibration_ids = {row["question_id"] for row in calibration}
        self.assertEqual(len(holdout), 7)
        self.assertEqual(len(calibration), 7)
        self.assertFalse(holdout_ids.intersection(calibration_ids))

    def test_first_loss_classification_is_mutually_exclusive(self):
        cases = (
            ({"gold_memory_present": False}, "induction_loss"),
            ({"gold_memory_present": True, "active_gold_memory_present": False}, "induction_loss"),
            (
                {
                    "gold_memory_present": True,
                    "active_gold_memory_present": True,
                    "gold_candidate_at_5": False,
                },
                "retrieval_loss",
            ),
            (
                {
                    "gold_memory_present": True,
                    "active_gold_memory_present": True,
                    "gold_candidate_at_5": True,
                    "gold_candidate_query_supported": False,
                },
                "query_support_rejection",
            ),
            (
                {
                    "gold_memory_present": True,
                    "active_gold_memory_present": True,
                    "gold_candidate_at_5": True,
                    "gold_candidate_query_supported": True,
                    "gold_candidate_answerable": False,
                },
                "answerability_rejection",
            ),
            (
                {
                    "gold_memory_present": True,
                    "active_gold_memory_present": True,
                    "gold_candidate_at_5": True,
                    "gold_candidate_query_supported": True,
                    "gold_candidate_answerable": True,
                    "supported_gold_package": True,
                },
                "supported",
            ),
        )

        self.assertEqual(
            [self.gate.classify_first_loss(case) for case, _ in cases],
            [expected for _, expected in cases],
        )

    def test_existing_hard_negatives_eliminate_unsafe_partial_policies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = self.gate.evaluate_synthetic_policy_boundaries(Path(tmpdir))

        self.assertEqual(metrics["strict_v1"]["hard_negative_rejection_rate"], 1.0)
        self.assertLess(
            metrics["weighted_partial_060_v1"]["hard_negative_rejection_rate"],
            1.0,
        )
        self.assertLess(
            metrics["weighted_partial_050_specific_v1"]["hard_negative_rejection_rate"],
            1.0,
        )
        for policy in self.gate.POLICY_NAMES:
            self.assertEqual(metrics[policy]["inactive_lifecycle_rejection_rate"], 1.0)
            self.assertEqual(metrics[policy]["malformed_missing_fail_closed_rate"], 1.0)

    def test_offline_fixture_reports_safe_no_change_decision(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--offline-fixture"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "public_query_support_calibration_gate")
        self.assertEqual(report["mode"], "offline_fixture")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["readiness_status"], "no_go")
        self.assertEqual(report["decision_reason"], "no_safe_policy")
        self.assertEqual(report["metrics"]["selected_policy_count"], 0)
        self.assertEqual(report["metrics"]["baseline_runtime_policy_parity_rate"], 1.0)
        self.assertEqual(report["metrics"]["selected_runtime_policy_parity_rate"], 1.0)
        self.assertEqual(report["metrics"]["missing_support_drilldown_rejection_rate"], 1.0)
        self.assertEqual(report["metrics"]["no_hit_rejection_rate"], 1.0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["queries_rendered"])
        self.assertNotIn("v23weakonly", result.stdout)
        self.assertNotIn("v23ledger", result.stdout)
        self.assertNotIn("Synthetic raw source anchor", result.stdout)

    def test_observes_real_packaged_case_without_rendering_scorer_labels(self):
        row = self.public_rows[2]
        with tempfile.TemporaryDirectory() as tmpdir:
            observation = self.gate.observe_packaged_case(row, 1, Path(tmpdir))

        self.assertEqual(observation["packaged_setup_success"], 1)
        self.assertEqual(observation["updater_success"], 1)
        self.assertEqual(observation["context_package_parse_success"], 1)
        self.assertEqual(observation["baseline_retrievable"], 1)
        self.assertEqual(observation["gold_memory_present"], 1)
        self.assertEqual(observation["active_gold_memory_present"], 1)
        self.assertEqual(set(observation["policy_outcomes"]), set(self.gate.POLICY_NAMES))
        self.assertGreater(observation["baseline_runtime_policy_parity_denominator"], 0)
        self.assertEqual(
            observation["baseline_runtime_policy_parity_numerator"],
            observation["baseline_runtime_policy_parity_denominator"],
        )
        self.assertEqual(observation["non_baseline_runtime_policy_hit_count"], 1)
        rendered = json.dumps(observation, sort_keys=True)
        self.assertNotIn(row["question_id"], rendered)
        self.assertNotIn(row["question"], rendered)
        self.assertNotIn(row["answer"], rendered)
        for session_id in row["answer_session_ids"]:
            self.assertNotIn(session_id, rendered)

    def test_builds_aggregate_attribution_with_explicit_denominators(self):
        def observation(loss_stage, *, abstention=False):
            flags = {
                "gold_memory_present": 1,
                "active_gold_memory_present": 1,
                "gold_candidate_at_1": 1,
                "gold_candidate_at_5": 1,
                "gold_candidate_query_supported": 1,
                "gold_candidate_answerable": 1,
                "supported_gold_package": 1,
            }
            if loss_stage == "induction_loss":
                flags.update(
                    gold_memory_present=0,
                    active_gold_memory_present=0,
                    gold_candidate_at_1=0,
                    gold_candidate_at_5=0,
                    gold_candidate_query_supported=0,
                    gold_candidate_answerable=0,
                    supported_gold_package=0,
                )
            elif loss_stage == "retrieval_loss":
                flags.update(
                    gold_candidate_at_1=0,
                    gold_candidate_at_5=0,
                    gold_candidate_query_supported=0,
                    gold_candidate_answerable=0,
                    supported_gold_package=0,
                )
            elif loss_stage == "query_support_rejection":
                flags.update(
                    gold_candidate_query_supported=0,
                    gold_candidate_answerable=0,
                    supported_gold_package=0,
                )
            elif loss_stage == "answerability_rejection":
                flags.update(gold_candidate_answerable=0, supported_gold_package=0)
            outcomes = {
                policy: {
                    "supported_decision": int(loss_stage == "supported" and not abstention),
                    "supported_gold_decision": int(loss_stage == "supported" and not abstention),
                    "false_support": 0,
                    "abstention_correct": int(abstention),
                }
                for policy in self.gate.POLICY_NAMES
            }
            return {
                "question_type": "multi-session",
                "is_abstention": int(abstention),
                "packaged_setup_success": 1,
                "updater_success": 1,
                "archive_audit_success": 1,
                "context_package_parse_success": 1,
                "baseline_retrievable": int(not abstention),
                **flags,
                "baseline_runtime_policy_parity_numerator": 1,
                "baseline_runtime_policy_parity_denominator": 1,
                "runtime_policy_parity": {
                    policy: {"numerator": 1, "denominator": 1}
                    for policy in self.gate.POLICY_NAMES
                },
                "policy_outcomes": outcomes,
                "public_gold_label_ingestion_count": 0,
                "public_answer_ingestion_count": 0,
                "synthetic_memory_marker_injection_count": 0,
                "direct_synthetic_archive_injection_count": 0,
                "privacy_leak_count": 0,
            }

        observations = [
            observation("induction_loss"),
            observation("retrieval_loss"),
            observation("query_support_rejection"),
            observation("answerability_rejection"),
            observation("supported"),
            observation("supported", abstention=True),
        ]
        boundaries = {
            policy: {
                "hard_negative_rejection_rate": 1.0 if policy == "strict_v1" else 0.5,
                "inactive_lifecycle_rejection_rate": 1.0,
                "malformed_missing_fail_closed_rate": 1.0,
            }
            for policy in self.gate.POLICY_NAMES
        }

        report = self.gate.build_cohort_report(
            cohort="calibration",
            observations=observations,
            policy_boundaries=boundaries,
            dataset={"source": "fixture", "sha256": "fixture-sha"},
            selection={"fingerprint_sha256": "fixture-selection"},
        )

        metrics = report["metrics"]
        counts = report["metric_counts"]
        self.assertEqual(metrics["public_baseline_retrievable_case_count"], 5)
        self.assertEqual(metrics["public_gold_memory_presence_count"], 4)
        self.assertEqual(metrics["public_active_gold_memory_count"], 4)
        self.assertEqual(metrics["public_gold_memory_candidate_at_1_count"], 3)
        self.assertEqual(metrics["public_gold_memory_candidate_at_5_count"], 3)
        self.assertEqual(metrics["public_gold_candidate_query_supported_count"], 2)
        self.assertEqual(metrics["public_gold_candidate_answerable_count"], 1)
        self.assertEqual(metrics["public_supported_gold_package_count"], 1)
        self.assertEqual(metrics["public_induction_loss_count"], 1)
        self.assertEqual(metrics["public_retrieval_loss_count"], 1)
        self.assertEqual(metrics["public_query_support_rejection_count"], 1)
        self.assertEqual(metrics["public_answerability_rejection_count"], 1)
        self.assertEqual(metrics["public_attribution_invariant_violation_count"], 0)
        self.assertEqual(metrics["public_packaged_setup_success_rate"], 1.0)
        self.assertEqual(metrics["public_updater_success_rate"], 1.0)
        self.assertEqual(metrics["public_archive_audit_success_rate"], 1.0)
        self.assertEqual(metrics["public_context_package_parse_success_rate"], 1.0)
        self.assertEqual(counts["public_updater_success_rate"], {"numerator": 6, "denominator": 6})
        self.assertEqual(metrics["baseline_runtime_policy_parity_rate"], 1.0)
        self.assertEqual(counts["baseline_runtime_policy_parity_rate"], {"numerator": 6, "denominator": 6})
        self.assertEqual(
            sum(report["first_loss_buckets"].values()),
            metrics["public_baseline_retrievable_case_count"],
        )
        self.assertEqual(report["readiness_status"], "inconclusive")
        self.assertEqual(report["decision_reason"], "insufficient_gold_candidates")
        self.assertTrue(report["privacy"]["aggregate_only"])
        rendered = json.dumps(report, sort_keys=True)
        for forbidden in ("question", "answer_session_ids", "memory_text", "source_path"):
            self.assertNotIn(f'"{forbidden}"', rendered)

    def test_baseline_policy_parity_failure_is_inconclusive(self):
        outcomes = {
            policy: {
                "supported_decision": 1,
                "supported_gold_decision": 1,
                "false_support": 0,
                "abstention_correct": 0,
            }
            for policy in self.gate.POLICY_NAMES
        }
        observation = {
            "question_type": "multi-session",
            "is_abstention": 0,
            "packaged_setup_success": 1,
            "updater_success": 1,
            "archive_audit_success": 1,
            "context_package_parse_success": 1,
            "baseline_retrievable": 1,
            "gold_memory_present": 1,
            "active_gold_memory_present": 1,
            "gold_candidate_at_1": 1,
            "gold_candidate_at_5": 1,
            "gold_candidate_query_supported": 1,
            "gold_candidate_answerable": 1,
            "supported_gold_package": 1,
            "baseline_runtime_policy_parity_numerator": 0,
            "baseline_runtime_policy_parity_denominator": 1,
            "runtime_policy_parity": {
                policy: {"numerator": 1, "denominator": 1}
                for policy in self.gate.POLICY_NAMES
            },
            "policy_outcomes": outcomes,
            "public_gold_label_ingestion_count": 0,
            "public_answer_ingestion_count": 0,
            "synthetic_memory_marker_injection_count": 0,
            "direct_synthetic_archive_injection_count": 0,
            "privacy_leak_count": 0,
        }
        boundaries = {
            policy: {
                "hard_negative_rejection_rate": 1.0,
                "inactive_lifecycle_rejection_rate": 1.0,
                "malformed_missing_fail_closed_rate": 1.0,
            }
            for policy in self.gate.POLICY_NAMES
        }
        abstention = {
            **observation,
            "is_abstention": 1,
            "baseline_retrievable": 0,
            "gold_memory_present": 0,
            "active_gold_memory_present": 0,
            "gold_candidate_at_1": 0,
            "gold_candidate_at_5": 0,
            "gold_candidate_query_supported": 0,
            "gold_candidate_answerable": 0,
            "supported_gold_package": 0,
            "policy_outcomes": {
                policy: {
                    "supported_decision": 0,
                    "supported_gold_decision": 0,
                    "false_support": 0,
                    "abstention_correct": 1,
                }
                for policy in self.gate.POLICY_NAMES
            },
        }

        report = self.gate.build_cohort_report(
            cohort="calibration",
            observations=[observation.copy() for _ in range(5)]
            + [abstention.copy() for _ in range(10)],
            policy_boundaries=boundaries,
            dataset={"source": "fixture", "sha256": "fixture-sha"},
            selection={"fingerprint_sha256": "fixture-selection"},
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["readiness_status"], "inconclusive")
        self.assertEqual(report["decision_reason"], "baseline_runtime_policy_parity_mismatch")

    def test_calibration_selection_defers_selected_runtime_parity_to_holdout(self):
        policy_outcomes = {
            "strict_v1": {
                "supported_decision": 0,
                "supported_gold_decision": 0,
                "false_support": 0,
                "abstention_correct": 0,
            },
            "weighted_partial_060_v1": {
                "supported_decision": 1,
                "supported_gold_decision": 1,
                "false_support": 0,
                "abstention_correct": 0,
            },
            "weighted_partial_050_specific_v1": {
                "supported_decision": 1,
                "supported_gold_decision": 1,
                "false_support": 0,
                "abstention_correct": 0,
            },
        }
        observation = {
            "question_type": "multi-session",
            "is_abstention": 0,
            "packaged_setup_success": 1,
            "updater_success": 1,
            "archive_audit_success": 1,
            "context_package_parse_success": 1,
            "baseline_retrievable": 1,
            "gold_memory_present": 1,
            "active_gold_memory_present": 1,
            "gold_candidate_at_1": 1,
            "gold_candidate_at_5": 1,
            "gold_candidate_query_supported": 0,
            "gold_candidate_answerable": 0,
            "supported_gold_package": 0,
            "baseline_runtime_policy_parity_numerator": 1,
            "baseline_runtime_policy_parity_denominator": 1,
            "runtime_policy_parity": {
                "strict_v1": {"numerator": 1, "denominator": 1},
                "weighted_partial_060_v1": {"numerator": 0, "denominator": 1},
                "weighted_partial_050_specific_v1": {"numerator": 0, "denominator": 1},
            },
            "policy_outcomes": policy_outcomes,
            "public_gold_label_ingestion_count": 0,
            "public_answer_ingestion_count": 0,
            "synthetic_memory_marker_injection_count": 0,
            "direct_synthetic_archive_injection_count": 0,
            "privacy_leak_count": 0,
        }
        boundaries = {
            policy: {
                "hard_negative_rejection_rate": 1.0,
                "inactive_lifecycle_rejection_rate": 1.0,
                "malformed_missing_fail_closed_rate": 1.0,
            }
            for policy in self.gate.POLICY_NAMES
        }
        abstention = {
            **observation,
            "is_abstention": 1,
            "baseline_retrievable": 0,
            "gold_memory_present": 0,
            "active_gold_memory_present": 0,
            "gold_candidate_at_1": 0,
            "gold_candidate_at_5": 0,
            "gold_candidate_query_supported": 0,
            "gold_candidate_answerable": 0,
            "supported_gold_package": 0,
            "policy_outcomes": {
                policy: {
                    "supported_decision": 0,
                    "supported_gold_decision": 0,
                    "false_support": 0,
                    "abstention_correct": 1,
                }
                for policy in self.gate.POLICY_NAMES
            },
        }

        report = self.gate.build_cohort_report(
            cohort="calibration",
            observations=[observation.copy() for _ in range(5)]
            + [abstention.copy() for _ in range(10)],
            policy_boundaries=boundaries,
            dataset={"source": "fixture", "sha256": "fixture-sha"},
            selection={"fingerprint_sha256": "fixture-selection"},
        )

        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["readiness_status"], "calibration_passed")
        self.assertEqual(report["decision_reason"], "policy_selected")
        self.assertEqual(report["selected_policy"], "weighted_partial_060_v1")
        self.assertEqual(report["metrics"]["selected_runtime_policy_parity_rate"], 0.0)

        holdout_report = self.gate.build_cohort_report(
            cohort="holdout",
            observations=[observation.copy() for _ in range(5)]
            + [abstention.copy() for _ in range(10)],
            policy_boundaries=boundaries,
            dataset={"source": "fixture", "sha256": "fixture-sha"},
            selection={"fingerprint_sha256": "fixture-selection"},
            selected_policy="weighted_partial_060_v1",
        )
        self.assertEqual(holdout_report["status"], "completed")
        self.assertEqual(holdout_report["readiness_status"], "no_go")
        self.assertEqual(holdout_report["decision_reason"], "holdout_failed")

    def test_public_cli_fails_closed_on_unpinned_dataset_sha(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "longmemeval.json"
            report_path = root / "aggregate-report.json"
            shutil.copyfile(PUBLIC_FIXTURE, public_input)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--public-input",
                    str(public_input),
                    "--dataset-source-url",
                    "https://example.invalid/longmemeval.json",
                    "--cohort",
                    "calibration",
                    "--work-dir",
                    str(root / "work"),
                    "--report-file",
                    str(report_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report, json.loads(report_path.read_text(encoding="utf-8")))
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["readiness_status"], "inconclusive")
            self.assertEqual(report["decision_reason"], "dataset_sha_mismatch")
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertFalse((root / "work").exists())
            self.assertNotIn(str(root), result.stdout)
            self.assertNotIn("fixture_preference", result.stdout)

    def test_public_cli_fails_closed_when_dataset_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "missing-longmemeval.json"
            report_path = root / "aggregate-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--public-input",
                    str(public_input),
                    "--dataset-source-url",
                    "https://example.invalid/longmemeval.json",
                    "--cohort",
                    "calibration",
                    "--work-dir",
                    str(root / "work"),
                    "--report-file",
                    str(report_path),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report, json.loads(report_path.read_text(encoding="utf-8")))
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["readiness_status"], "inconclusive")
            self.assertEqual(report["decision_reason"], "dataset_unreadable")
            self.assertEqual(report["dataset"]["sha256"], "unavailable")
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertFalse((root / "work").exists())
            self.assertNotIn(str(root), result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    def test_public_cli_rejects_repository_artifact_paths(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--public-input",
                str(PUBLIC_FIXTURE),
                "--dataset-source-url",
                "https://example.invalid/fixture.json",
                "--cohort",
                "holdout",
                "--work-dir",
                "/tmp/v237-rejected-work",
                "--report-file",
                "/tmp/v237-rejected-report.json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must stay outside", result.stderr)

    def test_public_runner_executes_only_disjoint_calibration_cohort(self):
        rows = []
        for question_type in self.gate.public_gate.POSITIVE_QUESTION_TYPES:
            for suffix in ("a", "b"):
                rows.append(
                    {
                        "question_id": f"{question_type}-{suffix}",
                        "question_type": question_type,
                    }
                )
        rows.extend(
            {"question_id": f"abs-{suffix}_abs", "question_type": "multi-session"}
            for suffix in ("a", "b")
        )

        def fake_observation(row, case_ordinal, case_root):
            is_abstention = row["question_id"].endswith("_abs")
            policy_outcomes = {}
            for policy in self.gate.POLICY_NAMES:
                partial = policy != "strict_v1"
                policy_outcomes[policy] = {
                    "supported_decision": int(partial and not is_abstention),
                    "supported_gold_decision": int(partial and not is_abstention),
                    "false_support": 0,
                    "abstention_correct": int(is_abstention),
                }
            return {
                "question_type": row["question_type"],
                "is_abstention": int(is_abstention),
                "packaged_setup_success": 1,
                "updater_success": 1,
                "archive_audit_success": 1,
                "context_package_parse_success": 1,
                "baseline_retrievable": int(not is_abstention),
                "gold_memory_present": int(not is_abstention),
                "active_gold_memory_present": int(not is_abstention),
                "gold_candidate_at_1": int(not is_abstention),
                "gold_candidate_at_5": int(not is_abstention),
                "gold_candidate_query_supported": 0,
                "gold_candidate_answerable": 0,
                "supported_gold_package": 0,
                "baseline_runtime_policy_parity_numerator": 1,
                "baseline_runtime_policy_parity_denominator": 1,
                "runtime_policy_parity": {
                    policy: {"numerator": int(policy == "strict_v1"), "denominator": 1}
                    for policy in self.gate.POLICY_NAMES
                },
                "policy_outcomes": policy_outcomes,
                "public_gold_label_ingestion_count": 0,
                "public_answer_ingestion_count": 0,
                "synthetic_memory_marker_injection_count": 0,
                "direct_synthetic_archive_injection_count": 0,
                "privacy_leak_count": 0,
            }

        boundaries = {
            policy: {
                "hard_negative_rejection_rate": 1.0 if policy == "strict_v1" else 0.5,
                "inactive_lifecycle_rejection_rate": 1.0,
                "malformed_missing_fail_closed_rate": 1.0,
            }
            for policy in self.gate.POLICY_NAMES
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "longmemeval.json"
            public_input.write_text(json.dumps(rows), encoding="utf-8")
            args = SimpleNamespace(
                public_input=str(public_input),
                dataset_source_url="https://example.invalid/pinned.json",
                cohort="calibration",
                work_dir=str(root / "work"),
                report_file=str(root / "report.json"),
                selected_policy="none",
                positive_per_type=1,
                abstention_count=1,
            )
            with (
                mock.patch.object(
                    self.gate.public_gate,
                    "_file_sha256",
                    return_value=self.gate.OFFICIAL_DATASET_SHA256,
                ),
                mock.patch.object(
                    self.gate,
                    "observe_packaged_case",
                    side_effect=fake_observation,
                ) as observe,
                mock.patch.object(
                    self.gate,
                    "evaluate_synthetic_policy_boundaries",
                    return_value=boundaries,
                ),
            ):
                report = self.gate.run_public_dataset(args)

            self.assertEqual(observe.call_count, 7)
            self.assertTrue((root / "work").is_dir())

        self.assertEqual(report["mode"], "public_calibration")
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["readiness_status"], "no_go")
        self.assertEqual(report["decision_reason"], "no_safe_policy")
        self.assertEqual(report["metrics"]["cohort_overlap_count"], 0)
        self.assertEqual(report["metrics"]["calibration_gold_memory_candidate_count"], 6)
        self.assertEqual(report["metrics"]["selected_policy_count"], 0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertNotIn("work_dir", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
