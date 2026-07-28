import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


GATE = Path("benchmarks/scheduled_live_source_deferral_gate.py").resolve()
PRIVATE_AB_GATE = Path("benchmarks/private_live_source_inventory_ab_gate.py").resolve()


def load_private_ab_gate():
    spec = importlib.util.spec_from_file_location("private_live_source_inventory_ab_gate", PRIVATE_AB_GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("private A/B gate module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScheduledLiveSourceDeferralGateTests(unittest.TestCase):
    def test_private_ab_freezes_wall_clock_for_byte_parity(self):
        module = load_private_ab_gate()
        self.assertTrue(
            hasattr(module, "frozen_parity_environment"),
            "private A/B must expose one shared frozen-clock environment",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            environment = module.frozen_parity_environment(Path(tmpdir))
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import datetime; "
                        "print(datetime.datetime.now(datetime.UTC).isoformat())"
                    ),
                ],
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "2026-07-13T12:00:00+00:00")

    def test_private_ab_uses_production_redaction_policy(self):
        module = load_private_ab_gate()
        command = module.runner_command(Path("/tmp/archive"), Path("/tmp/source"))

        self.assertIn("--allow-redacted-secrets", command)

    def test_gate_reports_complete_live_source_closure(self):
        result = subprocess.run(
            [sys.executable, str(GATE)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "scheduled_live_source_deferral_gate")
        self.assertEqual(report["status"], "passed")
        metrics = report["metrics"]
        self.assertEqual(metrics["live_source_defer_accuracy"], 1.0)
        self.assertEqual(metrics["stable_sibling_publish_accuracy"], 1.0)
        self.assertEqual(metrics["deferred_retry_recall"], 1.0)
        self.assertEqual(metrics["changed_source_partial_mutation_count"], 0)
        self.assertEqual(metrics["changed_source_freshness_advance_count"], 0)
        self.assertEqual(metrics["unknown_failure_block_accuracy"], 1.0)
        self.assertEqual(metrics["aggregate_failure_reason_coverage"], 1.0)
        self.assertEqual(metrics["inventory_worker_isolation_accuracy"], 1.0)
        self.assertEqual(metrics["manifest_metadata_only_accuracy"], 1.0)
        self.assertEqual(metrics["privacy_leak_count"], 0)


if __name__ == "__main__":
    unittest.main()
