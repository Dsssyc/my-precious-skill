import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


GATE_SCRIPT = Path("benchmarks/general_durable_preference_recall_gate.py").resolve()
CASE_FILE = Path(
    "benchmarks/cases/general_durable_preference_recall_synthetic.jsonl"
).resolve()


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "general_durable_preference_recall_gate_test",
        GATE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GeneralDurablePreferenceRecallGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load_gate()
        cls.cases = cls.gate.load_cases(CASE_FILE)

    def test_frozen_cohorts_are_disjoint_and_cover_required_shapes(self):
        gate = self.gate
        calibration = gate.cohort_cases(self.cases, "calibration")
        holdout = gate.cohort_cases(self.cases, "holdout")

        self.assertGreaterEqual(
            sum(case.expected_action == "answer" for case in holdout),
            8,
        )
        self.assertGreaterEqual(
            sum(case.expected_action == "abstain" for case in holdout),
            8,
        )
        self.assertEqual(
            {case.case_id for case in calibration}
            & {case.case_id for case in holdout},
            set(),
        )
        self.assertNotEqual(
            gate.cohort_fingerprint(calibration),
            gate.cohort_fingerprint(holdout),
        )
        required_shapes = {
            "direct",
            "repeated_correction",
            "skill_prefixed",
            "long_session_middle",
            "cross_project",
            "replacement",
            "temporary",
            "hypothetical",
            "quoted",
            "assistant_only",
            "wrong_scope",
            "inactive_only",
            "broad_lexical",
            "malformed_package",
            "missing_package",
        }
        self.assertTrue(
            required_shapes.issubset({case.shape for case in holdout})
        )
        self.assertEqual(
            {case.language for case in holdout if case.expected_action == "answer"},
            {"en", "zh"},
        )
        calibration_sources = {
            json.dumps(
                {
                    "project": source.project,
                    "updated_at": source.updated_at,
                    "events": list(source.events),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for case in calibration
            for source in case.sources
        }
        holdout_sources = {
            json.dumps(
                {
                    "project": source.project,
                    "updated_at": source.updated_at,
                    "events": list(source.events),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for case in holdout
            for source in case.sources
        }
        self.assertEqual(calibration_sources & holdout_sources, set())

    def test_case_file_contains_no_private_paths_or_session_ids(self):
        raw = CASE_FILE.read_text(encoding="utf-8")

        self.assertNotIn("/Users/", raw)
        self.assertNotRegex(
            raw,
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        )

    def test_first_loss_reports_the_first_failed_stage_only(self):
        stages = self.gate.FIRST_LOSS_STAGES
        checks = {stage: True for stage in stages}
        checks["memory_materialized"] = False
        checks["correct_scope"] = False

        self.assertEqual(
            self.gate.first_loss(checks),
            "memory_materialized",
        )

    def test_package_decision_fails_closed(self):
        supported = json.dumps(
            {
                "report_kind": self.gate.CONTEXT_REPORT_KIND,
                "answerability": {"status": "supported"},
                "hits": [
                    {
                        "memory_id": "mem_target",
                        "active_current": True,
                        "answerability": {"status": "supported"},
                        "query_support": {"status": "supported"},
                        "summary_drill_paths": ["sessions/a/summary.md"],
                        "evidence_drill_paths": ["sessions/a/evidence.md"],
                    }
                ],
            }
        )
        inactive = json.dumps(
            {
                "report_kind": self.gate.CONTEXT_REPORT_KIND,
                "answerability": {
                    "status": "unsupported",
                    "reason": "no_active_current_support",
                },
                "hits": [],
            }
        )

        self.assertEqual(
            self.gate.package_decision(supported, {"mem_target"}),
            "answer",
        )
        self.assertEqual(
            self.gate.package_decision(supported, {"mem_other"}),
            "abstain",
        )
        self.assertEqual(
            self.gate.package_decision(inactive, {"mem_target"}),
            "abstain",
        )
        self.assertEqual(
            self.gate.package_decision("{not-json", {"mem_target"}),
            "abstain",
        )
        self.assertEqual(
            self.gate.package_decision("", {"mem_target"}),
            "abstain",
        )
        self.assertEqual(
            self.gate.package_supported_decision(supported),
            "answer",
        )
        self.assertEqual(
            self.gate.package_supported_decision(inactive),
            "abstain",
        )
        self.assertEqual(
            self.gate.package_supported_decision("{not-json"),
            "abstain",
        )

    def test_static_overlap_checker_detects_forbidden_runtime_literals(self):
        holdout = self.gate.cohort_cases(self.cases, "holdout")
        diff = '+HOLDOUT-QUERY: "' + holdout[0].query + '"\n'

        metrics = self.gate.case_specific_runtime_metrics(diff, holdout)

        self.assertEqual(metrics["holdout_query_literal_overlap_count"], 1)
        self.assertGreaterEqual(
            metrics["new_case_specific_runtime_literal_count"],
            1,
        )

    def test_current_turn_precedence_metric_is_derived_from_frozen_cases(self):
        gate = self.gate
        checks = {stage: True for stage in gate.FIRST_LOSS_STAGES}
        cases = [
            gate.PreferenceCase(
                case_id="temporary",
                cohort="holdout",
                expected_action="abstain",
                language="en",
                shape="temporary",
                query="temporary synthetic query",
                expected_fact="",
                expected_scope="global",
                sources=(),
            ),
            gate.PreferenceCase(
                case_id="replacement",
                cohort="holdout",
                expected_action="answer",
                language="en",
                shape="replacement",
                query="replacement synthetic query",
                expected_fact="The user prefers the current synthetic choice.",
                expected_scope="global",
                sources=(),
            ),
        ]
        observations = [
            gate.CaseObservation(
                expected_action="abstain",
                shape="temporary",
                checks=checks,
                decision="answer",
                package_parsed=True,
                target_rank=0,
                wrong_scope_supported=False,
            ),
            gate.CaseObservation(
                expected_action="answer",
                shape="replacement",
                checks=checks,
                decision="answer",
                package_parsed=True,
                target_rank=1,
                wrong_scope_supported=False,
            ),
        ]

        metrics = gate.metrics_from_observations(
            cases,
            observations,
            ablation_rate=1.0,
            legacy_regression_rate=1.0,
            static_metrics={
                "new_case_specific_runtime_literal_count": 0,
                "holdout_query_literal_overlap_count": 0,
                "preference_specific_candidate_branch_count": 0,
            },
            performance={
                "performance_runtime_ratio": 1.0,
                "performance_peak_memory_ratio": 1.0,
                "deterministic_result_ordering_rate": 1.0,
            },
        )

        self.assertEqual(metrics["current_turn_precedence_accuracy"], 0.5)

    def test_private_report_is_aggregate_only_and_rechecks_archive_identity(self):
        gate = self.gate
        supported = json.dumps(
            {
                "report_kind": gate.CONTEXT_REPORT_KIND,
                "answerability": {"status": "supported"},
                "hits": [
                    {
                        "memory_id": "mem_private_target",
                        "layer": "global",
                        "active_current": True,
                        "answerability": {"status": "supported"},
                        "query_support": {"status": "supported"},
                        "summary_drill_paths": ["sessions/private/summary.md"],
                        "evidence_drill_paths": ["sessions/private/evidence.md"],
                    }
                ],
            }
        )
        unsupported = json.dumps(
            {
                "report_kind": gate.CONTEXT_REPORT_KIND,
                "answerability": {"status": "unsupported"},
                "hits": [],
            }
        )
        rows = [
            {
                "case_id": f"private-positive-{index}",
                "expected_action": "answer",
                "expected_scope": "global",
                "query": f"private secret positive query {index}",
                "scope": "global",
                "shape": "unseen_preference",
                "target_memory_ids": ["mem_private_target"],
            }
            for index in range(6)
        ]
        rows.extend(
            {
                "case_id": f"private-negative-{index}",
                "expected_action": "abstain",
                "query": f"private secret negative query {index}",
                "scope": "global",
                "shape": "hard_negative",
                "target_memory_ids": [],
            }
            for index in range(6)
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "private-manifest.jsonl"
            manifest.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            package_outputs = []
            for row in rows:
                candidate_output = (
                    supported if row["expected_action"] == "answer" else unsupported
                )
                package_outputs.extend((unsupported, candidate_output))
            with (
                patch.object(
                    gate,
                    "archive_identity",
                    side_effect=("immutable", "immutable"),
                ) as identity,
                patch.object(
                    gate,
                    "private_tool",
                    side_effect=(root / "baseline.py", root / "candidate.py"),
                ),
                patch.object(
                    gate,
                    "run_context_package",
                    side_effect=package_outputs,
                ),
            ):
                report = gate.run_private(root, root / "archive", manifest)

        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertEqual(identity.call_count, 2)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["candidate"]["metrics"]["canonical_archive_mutation_count"],
            0,
        )
        for row in rows:
            self.assertNotIn(row["query"], rendered)
            self.assertNotIn(row["case_id"], rendered)
            for memory_id in row["target_memory_ids"]:
                self.assertNotIn(memory_id, rendered)


if __name__ == "__main__":
    unittest.main()
