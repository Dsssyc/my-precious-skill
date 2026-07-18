import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path("benchmarks/real_use_recall_utility_gate.py").resolve()


def load_gate():
    spec = importlib.util.spec_from_file_location("real_use_recall_utility_gate_test", GATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RealUseRecallUtilityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load_gate()

    def test_bounded_facet_decision_is_package_only_and_fail_closed(self):
        gate = self.gate
        supported = gate.package_fixture()
        self.assertEqual(gate.bounded_contract(), (1.0, 1, 0))

        live = gate.decide(gate.Facet("live", (supported,), free_form="answer from memory"))
        self.assertEqual(live.action, "route_repository")
        self.assertFalse(live.free_form_used)

        over_limit = gate.decide(gate.Facet("history", (supported, supported, supported)))
        self.assertEqual(over_limit.action, "abstain")
        self.assertEqual(over_limit.variants_examined, gate.MAX_VARIANTS)

        inactive = gate.decide(gate.Facet("history", (gate.package_fixture(active=False),)))
        weak = gate.decide(
            gate.Facet("history", (gate.package_fixture(support_status="weak"),))
        )
        self.assertEqual(inactive.action, "abstain")
        self.assertEqual(weak.action, "abstain")

    def test_v250_source_adapter_metric_contract_is_declared(self):
        self.assertTrue(
            {
                "canonical_skill_prefixed_preference_recall",
                "multi_skill_prefix_recall",
                "prefixed_preference_source_binding_rate",
                "invocation_only_rejection_rate",
                "arbitrary_markdown_path_rejection_rate",
                "malformed_prefix_rejection_rate",
                "prefixed_non_durable_rejection_rate",
                "standalone_preference_regression_rate",
                "invocation_artifact_leak_count",
            }.issubset(self.gate.REQUIRED_METRICS)
        )

    def test_gate_passes_twice_with_identical_aggregate_report(self):
        gate = self.gate
        with tempfile.TemporaryDirectory() as tmpdir:
            results = [
                subprocess.run(
                    [sys.executable, str(GATE_SCRIPT), "--work-dir", tmpdir],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=360,
                )
                for _ in range(2)
            ]

        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(result.stderr, "")
        self.assertEqual(results[0].stdout, results[1].stdout)

        report = json.loads(results[0].stdout)
        self.assertEqual(report["report_kind"], gate.REPORT_KIND)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["failure_codes"], [])
        self.assertEqual(set(report["metrics"]), gate.REQUIRED_METRICS)
        self.assertTrue(all(report["closure_observations"].values()))
        self.assertEqual(
            report["determinism"],
            {"aggregate_reports_match": True, "runs": 2},
        )
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["free_form_search_used"])
        self.assertEqual(report["execution_contract"]["packaged_runtime_tool_count"], 2)
        self.assertEqual(report["execution_contract"]["packaged_runtime_hash_match_rate"], 1.0)
        self.assertEqual(report["execution_contract"]["direct_final_memory_write_count"], 0)
        self.assertEqual(report["execution_contract"]["free_form_search_use_count"], 0)
        self.assertGreaterEqual(
            report["execution_contract"]["raw_wrong_project_related_supported_hit_count"],
            1,
        )
        self.assertEqual(report["execution_contract"]["synthetic_case_pass_rate"], 1.0)

        metrics = report["metrics"]
        self.assertGreaterEqual(metrics["synthetic_case_count"], 8)
        self.assertEqual(metrics["synthetic_case_count"], len(gate.SYNTHETIC_CASES))
        for key in (
            "canonical_skill_prefixed_preference_recall",
            "multi_skill_prefix_recall",
            "prefixed_preference_source_binding_rate",
            "invocation_only_rejection_rate",
            "arbitrary_markdown_path_rejection_rate",
            "malformed_prefix_rejection_rate",
            "prefixed_non_durable_rejection_rate",
            "standalone_preference_regression_rate",
            "durable_chinese_preference_extraction_recall",
            "durable_english_preference_regression_rate",
            "long_session_middle_preference_recall",
            "noise_insertion_stability_rate",
            "temporary_constraint_rejection_rate",
            "hypothetical_statement_rejection_rate",
            "quoted_prompt_rejection_rate",
            "global_preference_scope_accuracy",
            "bounded_facet_plan_accuracy",
            "natural_goal_preference_supported_recall",
            "project_history_supported_recall",
        ):
            self.assertEqual(metrics[key], 1.0, key)
        for key in (
            "invocation_artifact_leak_count",
            "assistant_acknowledgement_promotion_count",
            "live_state_memory_answer_count",
            "wrong_project_supported_hit_count",
            "broad_query_false_answer_count",
            "unsupported_claim_count",
            "privacy_leak_count",
        ):
            self.assertEqual(metrics[key], 0, key)
        self.assertLessEqual(metrics["max_query_variants_per_facet"], 2)

        combined = results[0].stdout + results[0].stderr
        for forbidden in (*gate.PRIVACY_MARKERS, str(Path(tmpdir))):
            self.assertNotIn(forbidden, combined)

    def test_gate_never_writes_final_memory_index(self):
        source = GATE_SCRIPT.read_text(encoding="utf-8")
        for call in (node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "write_text":
                self.assertNotIn("memories.jsonl", ast.get_source_segment(source, call) or "")
        self.assertIn('repo / "tools/update_memory_archive.py"', source)
        self.assertIn('repo / "tools/search_memory.py"', source)


if __name__ == "__main__":
    unittest.main()
