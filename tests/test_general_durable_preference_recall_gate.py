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

    def test_v256_candidate_runtime_is_loaded_from_its_historical_commit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = self.gate.setup_archive(Path(tmpdir), "candidate")

            self.gate.install_candidate_runtime(repo)

            candidate = repo / "tools/search_memory.py"
            release = Path(
                "templates/agent-memory-repo/tools/search_memory.py"
            ).resolve()
            self.assertEqual(
                self.gate.CANDIDATE_COMMIT,
                "1f153c535505685ead0d1566539eeede03ada0ee",
            )
            self.assertNotEqual(candidate.read_bytes(), release.read_bytes())
            self.assertEqual(
                self.gate.file_sha256(candidate),
                "29e20ef5f63570d37d09eb878916d66de57ff44e9f8e794bd5f1ec33e25eefed",
            )

    def test_frozen_cohorts_are_disjoint_and_cover_required_shapes(self):
        gate = self.gate
        calibration = gate.cohort_cases(self.cases, "calibration")
        holdout = gate.cohort_cases(self.cases, "holdout")
        deployment_holdout = gate.cohort_cases(
            self.cases,
            "deployment-holdout",
        )

        self.assertGreaterEqual(
            sum(case.expected_action == "answer" for case in holdout),
            8,
        )
        self.assertGreaterEqual(
            sum(case.expected_action == "abstain" for case in holdout),
            8,
        )
        self.assertGreaterEqual(
            sum(
                case.expected_action == "answer"
                for case in deployment_holdout
            ),
            8,
        )
        self.assertGreaterEqual(
            sum(
                case.expected_action == "abstain"
                for case in deployment_holdout
            ),
            8,
        )
        self.assertEqual(
            {case.case_id for case in calibration}
            & {case.case_id for case in holdout},
            set(),
        )
        self.assertEqual(
            {
                case.case_id
                for case in (*calibration, *holdout)
            }
            & {case.case_id for case in deployment_holdout},
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
            "normalized_surface_variant",
            "open_ended_subject_preference",
            "candidate_only",
            "bare_subject",
            "negation",
            "current_turn_override",
            "unrelated_copyable_content",
            "project_goal_state",
            "general_markdown_rule",
        }
        self.assertTrue(
            required_shapes.issubset({case.shape for case in holdout})
        )
        self.assertEqual(
            {case.language for case in holdout if case.expected_action == "answer"},
            {"en", "zh"},
        )
        self.assertEqual(
            {
                case.language
                for case in deployment_holdout
                if case.expected_action == "answer"
            },
            {"en", "zh"},
        )
        self.assertEqual(
            {
                name: gate.cohort_fingerprint(
                    gate.cohort_cases(self.cases, name)
                )
                for name in gate.FROZEN_PUBLIC_FINGERPRINTS
            },
            gate.FROZEN_PUBLIC_FINGERPRINTS,
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

    def test_v256_thresholds_measure_candidate_support_separation(self):
        thresholds = self.gate.PUBLIC_THRESHOLDS

        self.assertEqual(
            thresholds["normalized_surface_variant_recall_at_5"],
            ("==", 1.0),
        )
        self.assertEqual(
            thresholds["normalized_surface_variant_supported_recall"],
            ("==", 1.0),
        )
        self.assertEqual(
            thresholds["open_ended_subject_preference_supported_recall"],
            (">=", 0.9),
        )
        self.assertEqual(thresholds["candidate_only_answer_count"], ("==", 0))
        self.assertEqual(
            thresholds["candidate_only_safety_eligible_rate"],
            ("==", 1.0),
        )
        self.assertEqual(
            thresholds["candidate_only_subject_support_count"],
            ("==", 0),
        )
        self.assertEqual(thresholds["negation_rejection_rate"], ("==", 1.0))
        self.assertEqual(thresholds["wrong_scope_rejection_rate"], ("==", 1.0))

    def test_cohort_results_are_non_authorizing_stage_decisions(self):
        gate = self.gate

        self.assertEqual(
            gate.cohort_stage_decision("calibration", []),
            "calibration_passed",
        )
        self.assertEqual(
            gate.cohort_stage_decision("holdout", []),
            "regression_passed",
        )
        self.assertEqual(
            gate.cohort_stage_decision("deployment-holdout", []),
            "public_deployment_holdout_passed",
        )
        self.assertEqual(
            gate.cohort_stage_decision("private-holdout", []),
            "private_deployment_holdout_passed",
        )
        self.assertEqual(
            gate.cohort_stage_decision("calibration", ["metric"]),
            "no_go",
        )

    def test_read_path_fixture_seeding_preserves_support_boundaries(self):
        gate = self.gate
        cases = [
            gate.PreferenceCase(
                case_id="supported",
                cohort="holdout",
                expected_action="answer",
                language="en",
                shape="normalized_surface_variant",
                query="synthetic report delivery preference",
                expected_fact="The user prefers synthetic reports to use plain text.",
                expected_scope="global",
                sources=(),
            ),
            gate.PreferenceCase(
                case_id="candidate-only",
                cohort="holdout",
                expected_action="abstain",
                language="en",
                shape="candidate_only",
                query="synthetic checklist delivery preference",
                expected_fact="The user prefers synthetic checklists to be copy ready.",
                expected_scope="global",
                sources=(),
            ),
            gate.PreferenceCase(
                case_id="inactive",
                cohort="holdout",
                expected_action="abstain",
                language="en",
                shape="inactive_only",
                query="target-memory-id",
                expected_fact="The user prefers synthetic summaries to use tables.",
                expected_scope="global",
                sources=(),
                query_mode="target_memory_id",
            ),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            gate.seed_read_path_archive(repo, cases)
            rows = gate.read_jsonl(repo / "index/memories.jsonl")

        supported = next(
            row for row in rows if row["text"] == cases[0].expected_fact
        )
        candidate_only = next(
            row for row in rows if row["text"] == cases[1].expected_fact
        )
        inactive = next(
            row for row in rows if row["text"] == cases[2].expected_fact
        )
        self.assertEqual(supported["source"], "automatic")
        self.assertEqual(supported["layer"], "global")
        self.assertTrue(supported["derived_from"])
        self.assertTrue(supported["evidence_refs"])
        self.assertEqual(candidate_only["source"], "automatic")
        self.assertTrue(inactive["superseded_by"])

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
        holdout = self.gate.cohort_cases(
            self.cases,
            "deployment-holdout",
        )
        diff = '+HOLDOUT-QUERY: "' + holdout[0].query + '"\n'

        metrics = self.gate.case_specific_runtime_metrics(diff, holdout)

        self.assertGreaterEqual(
            metrics["holdout_query_literal_overlap_count"],
            1,
        )
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
                        "query_support": {
                            "status": "supported",
                            "subject_preference_support": True,
                            "preference_memory": True,
                        },
                        "candidate_match": {
                            "polarity_match": True,
                            "focused_preference_intent": True,
                        },
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
        candidate_only = json.dumps(
            {
                "report_kind": gate.CONTEXT_REPORT_KIND,
                "answerability": {"status": "unsupported"},
                "hits": [
                    {
                        "memory_id": "mem_private_target",
                        "layer": "global",
                        "active_current": True,
                        "answerability": {"status": "unsupported"},
                        "query_support": {
                            "status": "weak",
                            "preference_memory": True,
                            "preference_safety_eligible": True,
                            "subject_preference_support": False,
                        },
                        "summary_drill_paths": ["sessions/private/summary.md"],
                        "evidence_drill_paths": ["sessions/private/evidence.md"],
                    }
                ],
            }
        )
        positive_shapes = (
            "normalized_surface_variant",
            "normalized_surface_variant",
            "open_ended_subject_preference",
            "open_ended_subject_preference",
            "unseen_preference",
            "unseen_preference",
        )
        rows = [
            {
                "case_id": f"private-positive-{index}",
                "expected_action": "answer",
                "expected_scope": "global",
                "query": f"private secret positive query {index}",
                "scope": "global",
                "shape": shape,
                "target_memory_ids": ["mem_private_target"],
            }
            for index, shape in enumerate(positive_shapes)
        ]
        negative_shapes = (
            "wrong_scope",
            "inactive_only",
            "negation",
            "current_turn_override",
            "candidate_only",
            "bare_subject",
            "quoted",
        )
        rows.extend(
            {
                "case_id": f"private-negative-{index}",
                "expected_action": "abstain",
                "query": f"private secret negative query {index}",
                "scope": "global",
                "shape": shape,
                "target_memory_ids": (
                    ["mem_private_target"]
                    if shape in {"candidate_only", "bare_subject"}
                    else []
                ),
            }
            for index, shape in enumerate(negative_shapes)
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
                if row["expected_action"] == "answer":
                    candidate_output = supported
                elif row["shape"] == "candidate_only":
                    candidate_output = candidate_only
                else:
                    candidate_output = unsupported
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
            report["decision"],
            "private_deployment_holdout_passed",
        )
        self.assertEqual(
            report["candidate"]["metrics"]["canonical_archive_mutation_count"],
            0,
        )
        self.assertEqual(
            report["candidate"]["metrics"][
                "private_required_shape_coverage_rate"
            ],
            1.0,
        )
        for row in rows:
            self.assertNotIn(row["query"], rendered)
            self.assertNotIn(row["case_id"], rendered)
            for memory_id in row["target_memory_ids"]:
                self.assertNotIn(memory_id, rendered)

    def test_private_manifest_rejects_missing_real_goal_shapes(self):
        rows = [
            {
                "case_id": f"case-{index}",
                "expected_action": "answer" if index < 6 else "abstain",
                "query": f"synthetic query {index}",
                "shape": "unseen_preference",
                "target_memory_ids": [],
            }
            for index in range(12)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                self.gate.GateFailure,
                "required_shape_coverage_missing",
            ):
                self.gate.load_private_manifest(path)


if __name__ == "__main__":
    unittest.main()
