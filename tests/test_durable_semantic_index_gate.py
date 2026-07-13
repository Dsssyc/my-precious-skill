import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/durable_semantic_index_gate.py").resolve()


def load_gate_module():
    spec = importlib.util.spec_from_file_location("durable_semantic_index_gate_under_test", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("durable semantic index gate is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DurableSemanticIndexGateTests(unittest.TestCase):
    def test_architecture_decision_enforces_every_threshold(self):
        module = load_gate_module()
        parity = (1.0, 1.0, 1.0, 1.0, 1.0)

        self.assertEqual(module.architecture_decision(0.95, 0.60, parity), "implement")
        self.assertEqual(module.architecture_decision(0.949999, 0.60, parity), "architecture_no_go")
        self.assertEqual(module.architecture_decision(0.95, 0.599999, parity), "architecture_no_go")
        self.assertEqual(module.architecture_decision(0.95, 0.60, ()), "architecture_no_go")
        self.assertEqual(module.architecture_decision(0.95, 0.60, parity[:4]), "architecture_no_go")
        self.assertEqual(
            module.architecture_decision(0.95, 0.60, (1.0, 1.0, 0.999999, 1.0, 1.0)),
            "architecture_no_go",
        )

    def test_exclusive_profiler_does_not_double_count_nested_work(self):
        module = load_gate_module()
        clock = iter((0.0, 2.0, 5.0, 10.0)).__next__
        profiler = module.ExclusivePhaseProfiler(clock=clock)

        with profiler.measure("outer"):
            with profiler.measure("inner"):
                pass

        self.assertEqual(profiler.phase_seconds["inner"], 3.0)
        self.assertEqual(profiler.phase_seconds["outer"], 7.0)
        self.assertEqual(sum(profiler.phase_seconds.values()), 10.0)

    def test_gate_proves_exclusive_attribution_and_counterfactual_contract(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "durable_semantic_index_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertGreaterEqual(metrics["exclusive_phase_attribution_coverage_rate"], 0.95)
        self.assertEqual(metrics["exclusive_phase_overlap_seconds"], 0.0)
        self.assertEqual(metrics["architecture_decision_accuracy"], 1.0)
        self.assertGreater(metrics["baseline_raw_event_traversal_count"], 1)
        self.assertGreater(metrics["baseline_source_event_lookup_full_scan_count"], 0)
        self.assertGreater(metrics["baseline_source_event_for_text_scan_count"], 0)
        self.assertGreater(metrics["baseline_source_text_normalization_count"], 0)
        self.assertGreater(metrics["baseline_repeated_semantic_normalization_count"], 0)
        self.assertGreater(metrics["baseline_nondurable_text_materialization_count"], 0)
        self.assertGreater(metrics["synthetic_fused_avoidable_processing_share"], 0.0)
        self.assertGreater(metrics["synthetic_fused_projected_max_speedup"], 1.0)
        for name in (
            "counterfactual_archive_output_parity_rate",
            "counterfactual_summary_field_parity_rate",
            "counterfactual_source_anchor_parity_rate",
            "counterfactual_event_order_parity_rate",
            "counterfactual_event_hash_parity_rate",
        ):
            self.assertEqual(metrics[name], 1.0)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["source_content_rendered"])


if __name__ == "__main__":
    unittest.main()
