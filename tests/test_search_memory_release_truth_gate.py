import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmarks import search_memory_release_truth_gate as release_truth_gate


GATE_SCRIPT = Path("benchmarks/search_memory_release_truth_gate.py").resolve()


class SearchMemoryReleaseTruthGateTests(unittest.TestCase):
    def test_gate_requires_the_approved_search_runtime_in_every_release_surface(self):
        result = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "search_memory_release_truth_gate")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["approved_runtime"]["sha256"],
            "e73b7b6600db8a147d667f91f08eef0562b5029e487950a7fa228c4903f8d248",
        )
        self.assertEqual(
            report["approved_runtime"]["source_commit"],
            "b076f5585ee3bfe0a8b2db07718ec9b32a3e03dd",
        )
        self.assertEqual(report["metrics"]["release_surface_parity_rate"], 1.0)
        self.assertEqual(report["metrics"]["approved_runtime_match_rate"], 1.0)
        self.assertEqual(report["metrics"]["rejected_runtime_absence_rate"], 1.0)
        self.assertEqual(report["metrics"]["packaged_runtime_match_rate"], 1.0)
        self.assertEqual(report["metrics"]["packaged_health_check_rate"], 1.0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertNotIn("normalized_subject_candidate_v1", result.stdout)
        self.assertNotIn("source_bound_subject_preference_support_v1", result.stdout)

    def test_gate_rejects_every_documented_no_go_runtime(self):
        self.assertIn(
            "3e0715d25cf0d59703774c5e9d41a19155e92ce85fa8f11549516449d3c15875",
            release_truth_gate.REJECTED_SEARCH_SHA256,
        )
        self.assertIn(
            "29e20ef5f63570d37d09eb878916d66de57ff44e9f8e794bd5f1ec33e25eefed",
            release_truth_gate.REJECTED_SEARCH_SHA256,
        )
        self.assertIn(
            "scoped_global_preference_applicability",
            release_truth_gate.REJECTED_RUNTIME_SYMBOLS,
        )
        self.assertIn(
            "normalized_subject_candidate_v1",
            release_truth_gate.REJECTED_RUNTIME_SYMBOLS,
        )
        self.assertIn(
            "source_bound_subject_preference_support_v1",
            release_truth_gate.REJECTED_RUNTIME_SYMBOLS,
        )

    def test_historical_no_go_runtimes_are_rejected_as_release_surfaces(self):
        historical_commits = (
            "971fce201bd88ffb54464c58b6efffe556d80204",
            "1f153c535505685ead0d1566539eeede03ada0ee",
        )
        source_path = "templates/agent-memory-repo/tools/search_memory.py"
        for commit in historical_commits:
            with self.subTest(commit=commit), tempfile.TemporaryDirectory() as tmpdir:
                historical = subprocess.run(
                    ["git", "show", f"{commit}:{source_path}"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ).stdout
                root = Path(tmpdir)
                surfaces = tuple(root / f"surface-{index}.py" for index in range(3))
                for surface in surfaces:
                    surface.write_bytes(historical)
                with mock.patch.object(
                    release_truth_gate,
                    "RELEASE_SURFACES",
                    surfaces,
                ):
                    report = release_truth_gate.build_report(root / "probe")

                self.assertEqual(report["status"], "failed")
                self.assertEqual(
                    report["metrics"]["rejected_runtime_absence_rate"],
                    0.0,
                )

    def test_missing_release_surface_fails_closed_without_path_disclosure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = release_truth_gate.RELEASE_SURFACES[0].read_bytes()
            first = root / "first.py"
            second = root / "second.py"
            missing = root / "missing.py"
            first.write_bytes(approved)
            second.write_bytes(approved)

            with mock.patch.object(
                release_truth_gate,
                "RELEASE_SURFACES",
                (first, second, missing),
            ):
                report = release_truth_gate.build_report(root / "probe")

            rendered = json.dumps(report, sort_keys=True)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failure_counts"]["missing_surface_count"], 1)
            self.assertEqual(report["metrics"]["release_surface_read_rate"], 2 / 3)
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertNotIn(str(root), rendered)

    def test_non_utf8_release_surface_fails_closed_without_traceback_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = release_truth_gate.RELEASE_SURFACES[0].read_bytes()
            first = root / "first.py"
            second = root / "second.py"
            invalid = root / "invalid.py"
            first.write_bytes(approved)
            second.write_bytes(approved)
            invalid.write_bytes(b"\xff\xfe\x00")

            with mock.patch.object(
                release_truth_gate,
                "RELEASE_SURFACES",
                (first, second, invalid),
            ):
                report = release_truth_gate.build_report(root / "probe")

            rendered = json.dumps(report, sort_keys=True)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failure_counts"]["invalid_utf8_surface_count"], 1)
            self.assertEqual(report["metrics"]["release_surface_utf8_rate"], 2 / 3)
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("UnicodeDecodeError", rendered)

    def test_unreadable_release_surface_fails_closed_without_path_disclosure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = release_truth_gate.RELEASE_SURFACES[0].read_bytes()
            first = root / "first.py"
            second = root / "second.py"
            unreadable = root / "directory.py"
            first.write_bytes(approved)
            second.write_bytes(approved)
            unreadable.mkdir()

            with mock.patch.object(
                release_truth_gate,
                "RELEASE_SURFACES",
                (first, second, unreadable),
            ):
                report = release_truth_gate.build_report(root / "probe")

            rendered = json.dumps(report, sort_keys=True)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["failure_counts"]["unreadable_surface_count"], 1)
            self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
            self.assertNotIn(str(root), rendered)


if __name__ == "__main__":
    unittest.main()
