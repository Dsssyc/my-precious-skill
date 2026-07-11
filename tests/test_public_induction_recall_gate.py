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


GATE = Path("benchmarks/public_induction_recall_gate.py").resolve()
FIXTURE = Path("benchmarks/cases/public_induction_recall_fixture.json").resolve()


def load_gate():
    spec = importlib.util.spec_from_file_location("public_induction_recall_gate", GATE)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load public induction recall gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicInductionRecallGateTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GATE.is_file(), "public induction recall gate is missing")
        self.gate = load_gate()
        self.rows = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_selects_deterministic_stratified_cases(self):
        first = self.gate.select_longmemeval_cases(
            self.rows,
            seed="v236-fixture",
            positive_per_type=1,
            abstention_count=2,
        )
        second = self.gate.select_longmemeval_cases(
            list(reversed(self.rows)),
            seed="v236-fixture",
            positive_per_type=1,
            abstention_count=2,
        )

        self.assertEqual(
            [row["question_id"] for row in first],
            [row["question_id"] for row in second],
        )
        self.assertEqual(len(first), 8)
        self.assertEqual(sum(row["question_id"].endswith("_abs") for row in first), 2)
        self.assertEqual(
            {row["question_type"] for row in first if not row["question_id"].endswith("_abs")},
            set(self.gate.POSITIVE_QUESTION_TYPES),
        )

    def test_writes_label_isolated_session_records(self):
        converted = self.gate.convert_longmemeval_case(self.rows[5], case_ordinal=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.gate.write_case_source_records(Path(tmpdir), converted)

            self.assertEqual(result["source_record_count"], 2)
            self.assertEqual(result["session_boundary_hits"], 2)
            self.assertEqual(result["role_preservation_hits"], 2)
            self.assertEqual(result["timestamp_preservation_hits"], 2)
            self.assertEqual(result["public_gold_label_ingestion_count"], 0)
            self.assertEqual(result["public_answer_ingestion_count"], 0)
            self.assertEqual(result["synthetic_memory_marker_injection_count"], 0)
            self.assertEqual(result["direct_synthetic_archive_injection_count"], 0)

            written = sorted(Path(tmpdir).glob("session-*/*.jsonl"))
            self.assertEqual(len(written), 2)
            payloads = [json.loads(line) for path in written for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(payloads, [
                {"content": "We can walk to the harbor.", "role": "user"},
                {"content": "Then take the ferry across.", "role": "assistant"},
            ])
            serialized = "\n".join(path.read_text(encoding="utf-8") for path in written)
            for forbidden in (
                "fixture_multi",
                "What combined plan was chosen?",
                "Walk and take the ferry",
                "question_type",
                "has_answer",
                "answer_session_ids",
                "gold-multi-a",
                "gold-multi-b",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_context_package_decision_fails_closed(self):
        supported = {
            "report_kind": "memory_recall_context_package",
            "answerability": {"status": "supported"},
            "hits": [
                {
                    "active_current": True,
                    "answerability": {"status": "supported"},
                    "query_support": {"status": "supported"},
                    "summary_drill_paths": ["sessions/example/summary.md"],
                    "evidence_drill_paths": ["sessions/example/evidence.md"],
                    "evidence_refs": [{"path": "sessions/example/evidence.md", "quote_id": "ev_001"}],
                }
            ],
        }
        inactive = {
            "report_kind": "memory_recall_context_package",
            "answerability": {"status": "supported"},
            "hits": [{"active_current": False, "answerability": {"status": "supported"}}],
        }
        malformed = {"report_kind": "wrong", "answerability": {"status": "supported"}}

        self.assertEqual(self.gate.context_package_decision(supported), "answer")
        self.assertEqual(self.gate.context_package_decision(inactive), "abstain")
        self.assertEqual(self.gate.context_package_decision(malformed), "abstain")
        self.assertEqual(self.gate.context_package_decision(None), "abstain")

    def test_context_package_parser_rejects_wrong_or_malformed_reports(self):
        valid = {"report_kind": "memory_recall_context_package", "answerability": {}, "hits": []}

        self.assertEqual(self.gate.parse_context_package(json.dumps(valid)), valid)
        self.assertIsNone(self.gate.parse_context_package('{not-json'))
        self.assertIsNone(self.gate.parse_context_package(json.dumps({"report_kind": "wrong"})))

    def test_gold_provenance_uses_supported_active_hits_only(self):
        package = {
            "report_kind": "memory_recall_context_package",
            "answerability": {"status": "supported"},
            "hits": [
                {
                    "active_current": True,
                    "answerability": {"status": "supported"},
                    "query_support": {"status": "supported"},
                    "summary_drill_paths": ["sessions/gold/summary.md"],
                    "evidence_drill_paths": ["sessions/gold/drill-evidence.md"],
                    "evidence_refs": ["sessions/gold/evidence.md#ev_001"],
                },
                {
                    "active_current": False,
                    "answerability": {"status": "supported"},
                    "evidence_refs": [{"path": "sessions/ignored/evidence.md", "quote_id": "ev_001"}],
                },
            ],
        }
        mapping = {
            "sessions/gold/evidence.md": "gold-session",
            "sessions/ignored/evidence.md": "ignored-session",
        }

        ranks = self.gate.supported_gold_provenance_ranks(package, mapping, {"gold-session"})

        self.assertEqual(ranks, [1])

    def test_supported_reachability_requires_available_source_package_ref(self):
        evidence_package = {
            "report_kind": "memory_recall_context_package",
            "answerability": {"status": "supported"},
            "hits": [
                {
                    "memory_id": "mem_supported",
                    "active_current": True,
                    "answerability": {"status": "supported"},
                    "query_support": {"status": "supported"},
                    "summary_drill_paths": ["sessions/example/summary.md"],
                    "evidence_drill_paths": ["sessions/example/evidence.md"],
                    "evidence_refs": ["sessions/example/evidence.md#ev_001"],
                }
            ],
        }
        source_package = {
            **evidence_package,
            "hits": [
                {
                    **evidence_package["hits"][0],
                    "source_refs": [
                        {
                            "source_ref_id": "src_fixture",
                            "status": "available",
                            "reason": "source_map_reachable",
                            "unsafe_ref": False,
                        }
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            evidence = repo / "sessions/example/evidence.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("ev_001: fixture evidence\n", encoding="utf-8")

            counts = self.gate.supported_package_reachability(
                evidence_package,
                source_package,
                repo,
            )

        self.assertEqual(counts, (1, 1, 1, 1))

    def test_aggregate_privacy_scan_detects_labels_content_and_local_paths(self):
        safe_report = {
            "report_kind": "public_induction_recall_gate",
            "question_type_counts": {"single-session-user": 1},
            "metrics": {"privacy_leak_count": 0},
        }
        local_path = Path("/tmp/private-public-input.json")

        self.assertEqual(
            self.gate.aggregate_privacy_leak_count(safe_report, [self.rows[0]], [local_path]),
            0,
        )
        self.assertGreater(
            self.gate.aggregate_privacy_leak_count(
                {**safe_report, "question": self.rows[0]["question"]},
                [self.rows[0]],
                [local_path],
            ),
            0,
        )
        self.assertGreater(
            self.gate.aggregate_privacy_leak_count(
                {**safe_report, "detail": self.rows[0]["haystack_sessions"][0][0]["content"]},
                [self.rows[0]],
                [local_path],
            ),
            0,
        )
        self.assertGreater(
            self.gate.aggregate_privacy_leak_count(
                {**safe_report, "detail": str(local_path)},
                [self.rows[0]],
                [local_path],
            ),
            0,
        )

    def test_offline_fixture_gate_reports_aggregate_contract_metrics(self):
        result = subprocess.run(
            [sys.executable, str(GATE), "--offline-fixture"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "public_induction_recall_gate")
        self.assertEqual(report["mode"], "offline_fixture")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["selected_case_count"], 8)
        for metric in (
            "public_case_selection_determinism_rate",
            "public_source_record_conversion_rate",
            "public_session_boundary_preservation_rate",
            "public_role_preservation_rate",
            "public_timestamp_preservation_rate",
            "runtime_malformed_fail_closed_rate",
            "runtime_missing_package_fail_closed_rate",
            "runtime_inactive_only_rejection_rate",
            "runtime_superseded_only_rejection_rate",
        ):
            self.assertEqual(report["metrics"][metric], 1.0, metric)
        for metric in (
            "public_gold_label_ingestion_count",
            "public_answer_ingestion_count",
            "synthetic_memory_marker_injection_count",
            "direct_synthetic_archive_injection_count",
            "free_form_answerability_use_count",
            "privacy_leak_count",
        ):
            self.assertEqual(report["metrics"][metric], 0, metric)
        self.assertTrue(report["privacy"]["aggregate_only"])
        self.assertFalse(report["privacy"]["questions_rendered"])
        self.assertFalse(report["privacy"]["answers_rendered"])
        self.assertNotIn("Which instrument", result.stdout)
        self.assertNotIn("gold-user", result.stdout)

    def test_packaged_case_uses_real_updater_audit_and_context_packages(self):
        case = self.gate.convert_longmemeval_case(self.rows[2], case_ordinal=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.gate.run_packaged_case(case, Path(tmpdir))

        self.assertEqual(result["packaged_setup_success"], 1)
        self.assertEqual(result["updater_success"], 1)
        self.assertEqual(result["archive_audit_success"], 1)
        self.assertEqual(result["source_record_count"], 1)
        self.assertEqual(result["context_package_search_count"], 3)
        self.assertEqual(result["context_package_parse_count"], 3)
        self.assertEqual(result["baseline_retrievable"], 1)
        self.assertGreaterEqual(result["automatic_memory_count"], 1)
        self.assertGreaterEqual(result["active_memory_count"], 1)
        self.assertIn(result["evidence_decision"], {"answer", "abstain"})
        self.assertEqual(result["public_gold_label_ingestion_count"], 0)
        self.assertEqual(result["public_answer_ingestion_count"], 0)
        self.assertEqual(result["privacy_leak_count"], 0)

    def test_packaged_case_stops_before_updater_when_question_leaks_into_source(self):
        row = dict(self.rows[0])
        row["question"] = row["haystack_sessions"][0][0]["content"]
        case = self.gate.convert_longmemeval_case(row, case_ordinal=1)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.gate.run_packaged_case(case, Path(tmpdir))

        self.assertEqual(result["packaged_setup_success"], 1)
        self.assertEqual(result["public_gold_label_ingestion_count"], 1)
        self.assertEqual(result["updater_success"], 0)
        self.assertEqual(result["archive_audit_success"], 0)
        self.assertEqual(result["context_package_search_count"], 0)

    def test_public_fixture_command_emits_structurally_valid_inconclusive_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "longmemeval_s_cleaned.json"
            report_path = root / "aggregate-report.json"
            shutil.copyfile(FIXTURE, public_input)
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "--public-input",
                    str(public_input),
                    "--dataset-source-url",
                    "https://example.invalid/longmemeval_s_cleaned.json",
                    "--seed",
                    "v236-fixture-public",
                    "--positive-per-type",
                    "1",
                    "--abstention-count",
                    "2",
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
            self.assertEqual(report["report_kind"], "public_induction_recall_gate")
            self.assertEqual(report["mode"], "public_longmemeval")
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["readiness_status"], "inconclusive")
            self.assertEqual(report["selected_case_count"], 8)
            self.assertEqual(report["metrics"]["public_positive_case_count"], 6)
            self.assertEqual(report["metrics"]["public_abstention_case_count"], 2)
            for metric in (
                "public_case_selection_determinism_rate",
                "public_source_record_conversion_rate",
                "public_session_boundary_preservation_rate",
                "public_role_preservation_rate",
                "public_timestamp_preservation_rate",
                "public_packaged_setup_success_rate",
                "public_updater_success_rate",
                "public_archive_audit_success_rate",
                "public_context_package_parse_success_rate",
            ):
                self.assertEqual(report["metrics"][metric], 1.0, metric)
                self.assertGreater(report["metric_counts"][metric]["denominator"], 0)
            for metric in (
                "public_gold_label_ingestion_count",
                "public_answer_ingestion_count",
                "synthetic_memory_marker_injection_count",
                "direct_synthetic_archive_injection_count",
                "inactive_support_acceptance_count",
                "free_form_answerability_use_count",
                "privacy_leak_count",
            ):
                self.assertEqual(report["metrics"][metric], 0, metric)
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertFalse(report["privacy"]["questions_rendered"])
            self.assertIn("single-session-preference", report["question_type_counts"])
            self.assertNotIn(str(root), result.stdout)
            self.assertNotIn("How does the user prefer", result.stdout)
            self.assertNotIn("gold-preference", result.stdout)

    def test_incompatible_public_schema_reports_inconclusive_without_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "incompatible.json"
            report_path = root / "aggregate-report.json"
            public_input.write_text('[{"unexpected": true}]\n', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "--public-input",
                    str(public_input),
                    "--dataset-source-url",
                    "https://example.invalid/incompatible.json",
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
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["readiness_status"], "inconclusive")
            self.assertEqual(report["inconclusive_reason"], "dataset_schema_incompatible")
            self.assertEqual(report["selected_case_count"], 0)
            self.assertTrue(report["privacy"]["aggregate_only"])
            self.assertNotIn(str(root), result.stdout)
            self.assertNotIn("unexpected", result.stdout)

    def test_public_runtime_failure_is_not_misclassified_as_schema_incompatible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            public_input = root / "longmemeval.json"
            shutil.copyfile(FIXTURE, public_input)
            args = SimpleNamespace(
                public_input=str(public_input),
                dataset_source_url="https://example.invalid/longmemeval.json",
                seed="v236-runtime-failure",
                positive_per_type=1,
                abstention_count=2,
                work_dir=str(root / "work"),
            )

            with mock.patch.object(
                self.gate,
                "run_packaged_case",
                side_effect=SystemExit("packaged runtime failed"),
            ):
                with self.assertRaisesRegex(SystemExit, "packaged runtime failed"):
                    self.gate.run_public_dataset(args)

    def test_external_artifact_guard_rejects_repository_paths(self):
        with self.assertRaisesRegex(SystemExit, "must stay outside"):
            self.gate.require_external_artifact_path(
                Path("benchmarks/cases/public_induction_recall_fixture.json").resolve(),
                "public input",
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            external = Path(tmpdir) / "artifact.json"
            self.assertEqual(
                self.gate.require_external_artifact_path(external, "public input"),
                external.resolve(),
            )


if __name__ == "__main__":
    unittest.main()
