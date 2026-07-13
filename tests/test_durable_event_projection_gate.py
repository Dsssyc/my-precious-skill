import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


GATE = Path("benchmarks/durable_event_projection_gate.py").resolve()


def load_gate_module():
    spec = importlib.util.spec_from_file_location("durable_event_projection_gate_under_test", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("durable event projection gate is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DurableEventProjectionGateTests(unittest.TestCase):
    def test_profile_decision_enforces_attribution_and_dependency_thresholds(self):
        module = load_gate_module()

        self.assertEqual(module.profile_decision(0.55, 0.0), "implement")
        self.assertEqual(module.profile_decision(0.549999, 0.0), "profile_no_go")
        self.assertEqual(module.profile_decision(0.75, 0.01), "profile_no_go")

    def test_gate_proves_bounded_phase_attribution_contract(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "durable_event_projection_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertGreaterEqual(metrics["phase_attribution_coverage_rate"], 0.95)
        self.assertEqual(metrics["implementation_decision_accuracy"], 1.0)
        self.assertEqual(metrics["nondurable_output_dependency_rate"], 0.0)
        self.assertGreater(metrics["nondurable_event_text_materialization_count"], 0)
        self.assertGreater(metrics["nondurable_event_normalization_count"], 0)
        self.assertEqual(metrics["durable_event_projection_parity_rate"], 1.0)
        self.assertEqual(metrics["durable_event_order_parity_rate"], 1.0)
        self.assertEqual(metrics["durable_event_hash_parity_rate"], 1.0)
        self.assertEqual(metrics["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["source_paths_rendered"])
        self.assertFalse(report["privacy"]["source_content_rendered"])


if __name__ == "__main__":
    unittest.main()
