import hashlib
import json
import math
import runpy
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path("benchmarks/layered_recall_benchmark.py").resolve()
SYNTHETIC_ARCHIVE_BUILDER = Path("benchmarks/build_synthetic_recall_archive.py").resolve()
SYNTHETIC_CASES = Path("benchmarks/cases/layered_recall_synthetic.jsonl").resolve()
SYNTHETIC_QUALITY_GATES = Path("benchmarks/quality-gates/layered_recall_synthetic.json").resolve()
SYNTHETIC_MAX_QUALITY_GATES = Path("benchmarks/quality-gates/layered_recall_synthetic_max.json").resolve()
SEARCH_SCRIPT = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()
AUDIT_SCRIPT = Path("templates/agent-memory-repo/tools/audit_memory_archive.py").resolve()
SUMMARY_PATH = "sessions/2026/06/04/source/summary.md"
SOURCE_ANCHOR = "records/private.jsonl#message:42"
MEMORY_TEXT = "Avoid repeated permission prompts after permission is granted."


class LayeredRecallBenchmarkTests(unittest.TestCase):
    def test_packaged_synthetic_cases_cover_public_benchmark_categories(self):
        cases_path = Path("benchmarks/cases/layered_recall_synthetic.jsonl")
        rows = [
            json.loads(line)
            for line in cases_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        self.assertGreaterEqual(len(rows), 34)
        self.assertLessEqual(len(rows), 50)
        categories = {row.get("category") for row in rows}
        self.assertTrue(
            {
                "automatic_induction",
                "explicit_memory",
                "information_extraction",
                "multi_session_reasoning",
                "temporal_reasoning",
                "knowledge_update",
                "abstention",
                "stale_memory_suppression",
                "privacy_boundary",
                "cross_project_recall",
                "source_reachability",
                "scope_calibration",
            }.issubset(categories)
        )
        self.assertTrue(any(row.get("expected_abstain") is True for row in rows))
        self.assertTrue(any(row.get("stale_memory_id") for row in rows))
        self.assertTrue(any(row.get("expected_not_memory_id") for row in rows))
        self.assertTrue(any(row.get("forbidden_output_patterns") for row in rows))
        self.assertTrue(any(row.get("reference_evidence") for row in rows))

        case_ids = []
        for row in rows:
            self.assertIsInstance(row.get("case_id"), str)
            self.assertRegex(row["case_id"], r"^synthetic:[a-z0-9_.-]+$")
            case_ids.append(row["case_id"])
            self.assertIsInstance(row.get("query"), str)
            self.assertTrue(row["query"].strip())
            if row.get("expected_abstain") is True:
                self.assertNotIn("expected_memory_id", row)
                continue
            for key in ("expected_memory_id", "expected_summary_path", "expected_source_anchor"):
                self.assertIsInstance(row.get(key), str)
                self.assertTrue(row[key].strip())
        self.assertEqual(len(set(case_ids)), len(case_ids))
        self.assertEqual(case_ids[0], "synthetic:info_permission_prompt")
        self.assertEqual(case_ids[-1], "synthetic:scope_domain_benchmark")
        expected_layers = {
            row["case_id"]: row.get("expected_layer")
            for row in rows
            if row.get("category") == "scope_calibration"
        }
        self.assertEqual(
            expected_layers,
            {
                "synthetic:scope_global_permission": "global",
                "synthetic:scope_project_my_precious": "project",
                "synthetic:scope_domain_benchmark": "domain",
            },
        )

    def test_packaged_synthetic_cases_produce_quantitative_scores(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            result = self.run_benchmark(repo, SYNTHETIC_CASES, SEARCH_SCRIPT)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 34)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["memory_recall_at_5"], 1.0)
            self.assertGreaterEqual(payload["memory_precision_at_5"], 0.25)
            self.assertGreater(payload["memory_result_count_at_5"], payload["memory_relevant_count_at_5"])
            self.assertEqual(payload["memory_relevant_count_at_5"], payload["positive_cases"])
            self.assertEqual(
                payload["memory_micro_precision_at_5"],
                payload["memory_relevant_count_at_5"] / payload["memory_result_count_at_5"],
            )
            self.assertEqual(payload["memory_mrr"], 1.0)
            self.assertEqual(payload["memory_ndcg_at_5"], 1.0)
            self.assertEqual(payload["memory_explainability_cases"], payload["positive_cases"])
            self.assertEqual(payload["memory_explainability"], 1.0)
            self.assertEqual(payload["layer_calibration_cases"], 5)
            self.assertEqual(payload["layer_calibration"], 1.0)
            self.assertEqual(payload["scope_filter_cases"], 5)
            self.assertEqual(payload["scope_filter_recall"], 1.0)
            self.assertEqual(payload["wrong_scope_suppression_cases"], 5)
            self.assertEqual(payload["wrong_scope_suppression"], 1.0)
            self.assertEqual(payload["memory_ranked_cases"], payload["positive_cases"])
            self.assertEqual(payload["memory_rank_missing_cases"], 0)
            self.assertEqual(payload["memory_rank_mean"], 1.0)
            self.assertEqual(payload["memory_rank_median"], 1.0)
            self.assertEqual(payload["memory_rank_histogram"]["1"], payload["positive_cases"])
            self.assertEqual(payload["memory_rank_histogram"]["missing"], 0)
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertGreaterEqual(payload["source_precision_at_5"], 0.28)
            self.assertGreaterEqual(payload["source_micro_precision_at_5"], 0.24)
            self.assertGreater(payload["source_result_count_at_5"], payload["source_relevant_count_at_5"])
            self.assertEqual(payload["source_relevant_count_at_5"], payload["source_cases"])
            self.assertEqual(
                payload["source_micro_precision_at_5"],
                payload["source_relevant_count_at_5"] / payload["source_result_count_at_5"],
            )
            self.assertEqual(payload["evidence_reachability"], 1.0)
            self.assertEqual(payload["memory_evidence_ref_cases"], payload["positive_cases"])
            self.assertEqual(payload["memory_evidence_ref_reachability"], 1.0)
            self.assertEqual(payload["evidence_text_cases"], 3)
            self.assertEqual(payload["evidence_text_reachability"], 1.0)
            self.assertEqual(payload["answer_cases"], 11)
            self.assertEqual(payload["answer_reachability"], 1.0)
            self.assertEqual(payload["answer_normalized_reachability"], 1.0)
            self.assertEqual(payload["answer_token_f1"], 1.0)
            self.assertEqual(payload["abstention_accuracy"], 1.0)
            self.assertEqual(payload["negative_memory_suppression"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)
            self.assertEqual(payload["update_consistency"], 1.0)
            self.assertEqual(payload["privacy_boundary_pass_rate"], 1.0)
            self.assertEqual(payload["failed_case_count"], 0)
            self.assertEqual(payload["case_pass_rate"], 1.0)
            self.assertGreaterEqual(payload["latency_ms"], 0)
            self.assertGreaterEqual(payload["latency_mean_ms"], 0)
            self.assertGreaterEqual(payload["latency_max_ms"], payload["latency_mean_ms"])
            self.assertLessEqual(payload["latency_max_ms"], payload["latency_ms"])
            self.assertEqual(payload["categories"]["abstention"]["cases"], 5)
            self.assertEqual(payload["categories"]["abstention"]["failed_case_count"], 0)
            self.assertEqual(payload["categories"]["abstention"]["case_pass_rate"], 1.0)
            self.assertEqual(payload["categories"]["automatic_induction"]["case_pass_rate"], 1.0)
            self.assertEqual(payload["categories"]["automatic_induction"]["layer_calibration"], 1.0)
            self.assertEqual(
                payload["categories"]["automatic_induction"]["memory_evidence_ref_reachability"],
                1.0,
            )
            self.assertEqual(payload["categories"]["explicit_memory"]["case_pass_rate"], 1.0)
            self.assertEqual(payload["categories"]["explicit_memory"]["layer_calibration"], 1.0)
            self.assertEqual(
                payload["categories"]["explicit_memory"]["memory_evidence_ref_reachability"],
                1.0,
            )
            self.assertEqual(payload["categories"]["knowledge_update"]["update_consistency"], 1.0)
            self.assertEqual(payload["categories"]["privacy_boundary"]["privacy_boundary_pass_rate"], 1.0)

    def test_packaged_synthetic_archive_passes_archive_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            result = subprocess.run(
                [sys.executable, str(AUDIT_SCRIPT), "--memory-repo", str(repo)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_packaged_synthetic_cases_pass_packaged_quality_gates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            details = Path(tmpdir) / "details.jsonl"
            lower_gates = json.loads(SYNTHETIC_QUALITY_GATES.read_text(encoding="utf-8"))
            upper_gates = json.loads(SYNTHETIC_MAX_QUALITY_GATES.read_text(encoding="utf-8"))
            self.assertEqual(lower_gates["case_pass_rate"], 1.0)
            self.assertEqual(lower_gates["memory_precision_at_5"], 0.25)
            self.assertEqual(lower_gates["memory_micro_precision_at_5"], 0.24)
            self.assertEqual(lower_gates["memory_ndcg_at_5"], 1.0)
            self.assertEqual(lower_gates["memory_explainability"], 1.0)
            self.assertEqual(lower_gates["memory_explainability_cases"], 29)
            self.assertEqual(lower_gates["memory_evidence_ref_cases"], 29)
            self.assertEqual(lower_gates["memory_evidence_ref_reachability"], 1.0)
            self.assertEqual(lower_gates["layer_calibration"], 1.0)
            self.assertEqual(lower_gates["layer_calibration_cases"], 5)
            self.assertEqual(lower_gates["scope_filter_recall"], 1.0)
            self.assertEqual(lower_gates["scope_filter_cases"], 5)
            self.assertEqual(lower_gates["wrong_scope_suppression"], 1.0)
            self.assertEqual(lower_gates["wrong_scope_suppression_cases"], 5)
            self.assertEqual(lower_gates["evidence_text_cases"], 3)
            self.assertEqual(lower_gates["evidence_text_reachability"], 1.0)
            self.assertEqual(lower_gates["source_precision_at_5"], 0.28)
            self.assertEqual(lower_gates["source_micro_precision_at_5"], 0.24)
            self.assertEqual(lower_gates["source_relevant_count_at_5"], 29)
            self.assertEqual(lower_gates["memory_ranked_cases"], 29)
            self.assertEqual(upper_gates["memory_rank_missing_cases"], 0)
            self.assertEqual(upper_gates["memory_rank_mean"], 1.0)
            self.assertEqual(upper_gates["memory_rank_median"], 1.0)
            self.assertEqual(upper_gates["source_result_count_at_5"], 117)
            self.assertEqual(upper_gates["unsafe_source_anchor_count_at_5"], 0)
            self.assertEqual(upper_gates["unsafe_source_anchor_rate_at_5"], 0.0)
            self.assertEqual(lower_gates["categories.abstention.case_pass_rate"], 1.0)
            self.assertEqual(lower_gates["categories.automatic_induction.case_pass_rate"], 1.0)
            self.assertEqual(lower_gates["categories.automatic_induction.layer_calibration"], 1.0)
            self.assertEqual(
                lower_gates["categories.automatic_induction.memory_evidence_ref_reachability"],
                1.0,
            )
            self.assertEqual(lower_gates["categories.explicit_memory.case_pass_rate"], 1.0)
            self.assertEqual(lower_gates["categories.explicit_memory.layer_calibration"], 1.0)
            self.assertEqual(
                lower_gates["categories.explicit_memory.memory_evidence_ref_reachability"],
                1.0,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                    "--include-superseded-distractors",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            result = self.run_benchmark(
                repo,
                SYNTHETIC_CASES,
                SEARCH_SCRIPT,
                extra_args=[
                    "--details-jsonl",
                    str(details),
                    "--fail-under-file",
                    str(SYNTHETIC_QUALITY_GATES),
                    "--fail-over-file",
                    str(SYNTHETIC_MAX_QUALITY_GATES),
                ],
            )

            payload = json.loads(result.stdout)
            detail_rows = [
                json.loads(line)
                for line in details.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(payload["cases"], 34)
            self.assertEqual(payload["answer_cases"], 11)
            self.assertGreaterEqual(payload["memory_precision_at_5"], lower_gates["memory_precision_at_5"])
            self.assertGreaterEqual(payload["memory_ndcg_at_5"], lower_gates["memory_ndcg_at_5"])
            self.assertGreaterEqual(payload["memory_explainability"], lower_gates["memory_explainability"])
            self.assertGreaterEqual(payload["memory_explainability_cases"], lower_gates["memory_explainability_cases"])
            self.assertGreaterEqual(payload["memory_evidence_ref_cases"], lower_gates["memory_evidence_ref_cases"])
            self.assertGreaterEqual(
                payload["memory_evidence_ref_reachability"],
                lower_gates["memory_evidence_ref_reachability"],
            )
            self.assertGreaterEqual(payload["layer_calibration"], lower_gates["layer_calibration"])
            self.assertGreaterEqual(payload["layer_calibration_cases"], lower_gates["layer_calibration_cases"])
            self.assertGreaterEqual(payload["scope_filter_recall"], lower_gates["scope_filter_recall"])
            self.assertGreaterEqual(payload["scope_filter_cases"], lower_gates["scope_filter_cases"])
            self.assertGreaterEqual(payload["wrong_scope_suppression"], lower_gates["wrong_scope_suppression"])
            self.assertGreaterEqual(
                payload["wrong_scope_suppression_cases"],
                lower_gates["wrong_scope_suppression_cases"],
            )
            self.assertGreaterEqual(payload["memory_ranked_cases"], lower_gates["memory_ranked_cases"])
            self.assertLessEqual(payload["memory_rank_missing_cases"], upper_gates["memory_rank_missing_cases"])
            self.assertLessEqual(payload["memory_rank_mean"], upper_gates["memory_rank_mean"])
            self.assertLessEqual(payload["memory_rank_median"], upper_gates["memory_rank_median"])
            self.assertGreaterEqual(payload["source_precision_at_5"], lower_gates["source_precision_at_5"])
            self.assertGreaterEqual(payload["source_micro_precision_at_5"], lower_gates["source_micro_precision_at_5"])
            self.assertGreaterEqual(payload["source_relevant_count_at_5"], lower_gates["source_relevant_count_at_5"])
            self.assertLessEqual(payload["source_result_count_at_5"], upper_gates["source_result_count_at_5"])
            self.assertLessEqual(
                payload["unsafe_source_anchor_count_at_5"],
                upper_gates["unsafe_source_anchor_count_at_5"],
            )
            self.assertLessEqual(
                payload["unsafe_source_anchor_rate_at_5"],
                upper_gates["unsafe_source_anchor_rate_at_5"],
            )
            self.assertEqual(payload["answer_reachability"], 1.0)
            self.assertGreaterEqual(payload["evidence_text_cases"], lower_gates["evidence_text_cases"])
            self.assertGreaterEqual(payload["evidence_text_reachability"], lower_gates["evidence_text_reachability"])
            self.assertEqual(payload["answer_normalized_reachability"], 1.0)
            self.assertEqual(payload["answer_token_f1"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)
            self.assertEqual(payload["failed_case_count"], 0)
            self.assertEqual(payload["case_pass_rate"], 1.0)
            self.assertEqual(len(detail_rows), 34)
            self.assertEqual(detail_rows[0]["case_id"], "synthetic:info_permission_prompt")
            self.assertEqual(detail_rows[-1]["case_id"], "synthetic:scope_domain_benchmark")

    def test_synthetic_builder_can_add_superseded_stale_distractors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                    "--include-superseded-distractors",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            records = [
                json.loads(line)
                for line in (repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            stale_ids = {
                row["stale_memory_id"]
                for row in (
                    json.loads(line)
                    for line in SYNTHETIC_CASES.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
                if row.get("stale_memory_id")
            }
            stale_records = [record for record in records if record.get("memory_id") in stale_ids]
            self.assertGreaterEqual(len(stale_records), 1)
            self.assertTrue(all(record.get("superseded_by") for record in stale_records))
            self.assertTrue(any("superseded distractor" in record.get("text", "") for record in stale_records))

            result = self.run_benchmark(repo, SYNTHETIC_CASES, SEARCH_SCRIPT)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 34)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)
            self.assertEqual(payload["update_consistency"], 1.0)

    def test_synthetic_builder_omits_supersedes_when_stale_records_are_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            rows_by_case_id = {
                row["case_id"]: row
                for row in (
                    json.loads(line)
                    for line in SYNTHETIC_CASES.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            }
            records = [
                json.loads(line)
                for line in (repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            stale_case_memory_ids = {
                row["expected_memory_id"]
                for row in rows_by_case_id.values()
                if row.get("stale_memory_id")
            }
            current_records = [record for record in records if record.get("memory_id") in stale_case_memory_ids]

            self.assertGreaterEqual(len(current_records), 1)
            self.assertTrue(all(record.get("supersedes") == [] for record in current_records))

    def test_synthetic_builder_uses_expected_layers_for_scope_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            records = {
                record["memory_id"]: record
                for record in (
                    json.loads(line)
                    for line in (repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()
                )
            }
            self.assertEqual(records["syn_scope_global_permission"]["layer"], "global")
            self.assertEqual(records["syn_scope_project_my_precious"]["layer"], "project")
            self.assertEqual(records["syn_scope_domain_benchmark"]["layer"], "domain")

    def test_synthetic_builder_missing_cases_file_reports_controlled_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            sensitive_cases_root = root / "cases-cookie=SHOULD_NOT_RENDER"
            missing_cases = sensitive_cases_root / "missing.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(missing_cases),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to read cases JSONL", result.stderr)
            self.assertIn("[unsafe-path]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_synthetic_builder_missing_cases_file_sanitizes_sensitive_slug_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            sensitive_cases_root = root / "cases-cookie_should_not_render"
            missing_cases = sensitive_cases_root / "missing.jsonl"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(missing_cases),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to read cases JSONL", result.stderr)
            self.assertIn("[unsafe-path]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("cookie_should_not_render", combined)
            self.assertNotIn("cookie", combined.lower())

    def test_synthetic_builder_success_payload_sanitizes_sensitive_repo_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sensitive_repo_root = root / "archive-cookie=SHOULD_NOT_RENDER"
            repo = sensitive_repo_root / "agent-memory"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["repo"], "[unsafe-path]")
            self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
            self.assertNotIn("cookie=", result.stdout)
            self.assertTrue((repo / "index" / "memories.jsonl").exists())
            for file_name in ("global.jsonl", "domains.jsonl", "projects.jsonl", "explicit.jsonl"):
                self.assertTrue((repo / "memories" / file_name).exists())
            def read_rows(path):
                return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

            indexed = {
                row["memory_id"]: row
                for row in read_rows(repo / "index" / "memories.jsonl")
            }
            durable = {}
            for file_name in ("global.jsonl", "domains.jsonl", "projects.jsonl", "explicit.jsonl"):
                for row in read_rows(repo / "memories" / file_name):
                    durable.setdefault(row["memory_id"], row)
            self.assertEqual(indexed, durable)

    def test_synthetic_builder_repo_write_error_reports_controlled_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "archive-cookie=SHOULD_NOT_RENDER"
            repo.write_text("not a directory", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(SYNTHETIC_CASES),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to write synthetic archive", result.stderr)
            self.assertIn("[unsafe-path]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_synthetic_builder_rejects_case_paths_outside_archive(self):
        scenarios = [
            (
                "expected_summary_path",
                {"expected_summary_path": "../outside/summary.md"},
                "outside/summary.md",
            ),
            (
                "required_evidence_paths",
                {"required_evidence_paths": ["../outside/evidence.md"]},
                "outside/evidence.md",
            ),
            (
                "expected_source_anchor",
                {"expected_source_anchor": "../outside/raw.jsonl#message:1"},
                "outside/raw.jsonl",
            ),
        ]
        for field, override, outside_path in scenarios:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                repo = root / "agent-memory"
                cases = self.write_cases(root, {**self.valid_case(), **override})
                outside = root / outside_path

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SYNTHETIC_ARCHIVE_BUILDER),
                        "--repo",
                        str(repo),
                        "--cases",
                        str(cases),
                    ],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsafe archive path in benchmark case field", result.stderr)
                self.assertIn(field, result.stderr)
                self.assertNotIn("Traceback", combined)
                self.assertFalse(outside.exists())

    def test_synthetic_builder_rejects_unsafe_memory_identifiers_without_leaking_values(self):
        scenarios = [
            ("expected_memory_id", {"expected_memory_id": "mem_control\nidentifier"}),
            ("stale_memory_id", {"stale_memory_id": "mem_cookie_SHOULD_NOT_RENDER"}),
            ("stale_memory_id", {"stale_memory_id": "../outside-memory"}),
        ]
        for field, override in scenarios:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                repo = root / "agent-memory"
                cases = self.write_cases(root, {**self.valid_case(), **override})

                result = subprocess.run(
                    [
                        sys.executable,
                        str(SYNTHETIC_ARCHIVE_BUILDER),
                        "--repo",
                        str(repo),
                        "--cases",
                        str(cases),
                        "--include-superseded-distractors",
                    ],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsafe benchmark memory identifier", result.stderr)
                self.assertIn(field, result.stderr)
                self.assertNotIn("Traceback", combined)
                self.assertNotIn("SHOULD_NOT_RENDER", combined)
                self.assertNotIn("cookie", combined)

    def test_layered_recall_benchmark_reports_parsed_block_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, calls_path = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 1)
            self.assertEqual(payload["memory_recall_at_5"], 1.0)
            self.assertEqual(payload["memory_precision_at_5"], 1.0)
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["latency_mean_ms"], payload["latency_ms"])
            self.assertEqual(payload["latency_max_ms"], payload["latency_ms"])
            self.assertEqual(payload["categories"]["uncategorized"]["latency_mean_ms"], payload["latency_ms"])
            calls = calls_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                calls,
                [
                    "memory|all|permission prompts",
                    "session|all|permission prompts",
                    "source|all|permission prompts",
                ],
            )

    def test_layered_recall_benchmark_does_not_count_session_path_prefix_collision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="session_path_prefix_collision")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["session_drilldown_at_5"], 0.0)
            self.assertFalse(detail["session_drilldown_hit"])
            self.assertIn("session_drilldown_at_5", detail["failed_checks"])

    def test_layered_recall_benchmark_does_not_count_evidence_path_prefix_collision(self):
        evidence_path = SUMMARY_PATH.replace("/summary.md", "/evidence.md")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "required_evidence_paths": [evidence_path]})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="evidence_path_prefix_collision")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["evidence_reachability"], 0.0)
            self.assertFalse(detail["evidence_reachability_hit"])
            self.assertIn("evidence_reachability", detail["failed_checks"])

    def test_evidence_reachability_requires_expected_memory_identity(self):
        evidence_path = SUMMARY_PATH.replace("/summary.md", "/evidence.md")
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "required_evidence_paths": [evidence_path]})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="evidence_wrong_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["evidence_reachability"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["evidence_reachability_hit"])
            self.assertIn("evidence_reachability", detail["failed_checks"])

    def test_layered_recall_benchmark_reports_memory_precision_at_5(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="extra_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["memory_recall_at_5"], 1.0)
            self.assertEqual(payload["memory_precision_at_5"], 0.5)
            self.assertEqual(payload["memory_micro_precision_at_5"], 0.5)
            self.assertEqual(payload["memory_result_count_at_5"], 2)
            self.assertEqual(payload["memory_relevant_count_at_5"], 1)
            self.assertEqual(payload["case_pass_rate"], 1.0)
            self.assertEqual(detail["memory_precision_at_5"], 0.5)
            self.assertEqual(detail["memory_result_count_at_5"], 2)
            self.assertEqual(detail["memory_relevant_count_at_5"], 1)
            self.assertTrue(detail["case_pass"])
            self.assertNotIn("memory_precision_at_5", detail["failed_checks"])

    def test_layered_recall_benchmark_does_not_count_memory_id_prefix_collision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="prefix_collision")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 0.0)
            self.assertEqual(payload["memory_recall_at_5"], 0.0)
            self.assertEqual(payload["memory_precision_at_5"], 0.0)
            self.assertEqual(payload["memory_relevant_count_at_5"], 0)
            self.assertEqual(detail["memory_result_ids"], ["mem_permission_extra"])
            self.assertIn("memory_recall_at_5", detail["failed_checks"])

    def test_layered_recall_benchmark_does_not_count_memory_title_prefix_collision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="title_prefix_collision")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 0.0)
            self.assertEqual(payload["memory_recall_at_5"], 0.0)
            self.assertEqual(payload["memory_precision_at_5"], 0.0)
            self.assertEqual(payload["memory_relevant_count_at_5"], 0)
            self.assertEqual(detail["memory_result_ids"], [])
            self.assertIn("memory_recall_at_5", detail["failed_checks"])

    def test_layered_recall_benchmark_reports_memory_ndcg_at_5(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="rank_second")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            expected_ndcg = 1 / math.log2(3)
            self.assertEqual(payload["memory_recall_at_1"], 0.0)
            self.assertEqual(payload["memory_recall_at_5"], 1.0)
            self.assertAlmostEqual(payload["memory_ndcg_at_5"], expected_ndcg)
            self.assertAlmostEqual(payload["categories"]["uncategorized"]["memory_ndcg_at_5"], expected_ndcg)
            self.assertAlmostEqual(detail["memory_ndcg_at_5"], round(expected_ndcg, 6))

    def test_layered_recall_benchmark_reports_memory_rank_distribution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                self.valid_case(),
                {**self.valid_case(), "query": "permission prompts rank second"},
                {**self.valid_case(), "query": "permission prompts missing"},
            )
            search_script, _ = self.write_stub_search(root, mode="rank_distribution")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["positive_cases"], 3)
            self.assertEqual(payload["memory_ranked_cases"], 2)
            self.assertEqual(payload["memory_rank_missing_cases"], 1)
            self.assertEqual(payload["memory_rank_mean"], 1.5)
            self.assertEqual(payload["memory_rank_median"], 1.5)
            self.assertEqual(
                payload["memory_rank_histogram"],
                {"1": 1, "2": 1, "3": 0, "4": 0, "5": 0, ">5": 0, "missing": 1},
            )
            self.assertEqual(payload["memory_recall_at_1"], 1 / 3)
            self.assertEqual(payload["memory_recall_at_5"], 2 / 3)
            self.assertEqual(payload["categories"]["uncategorized"]["memory_ranked_cases"], 2)
            self.assertEqual(payload["categories"]["uncategorized"]["memory_rank_missing_cases"], 1)

    def test_layered_recall_benchmark_reports_input_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases_path"], str(cases.resolve()))
            self.assertEqual(payload["cases_sha256"], hashlib.sha256(cases.read_bytes()).hexdigest())
            self.assertEqual(payload["search_script_path"], str(search_script.resolve()))
            self.assertEqual(
                payload["search_script_sha256"],
                hashlib.sha256(search_script.read_bytes()).hexdigest(),
            )

    def test_layered_recall_benchmark_reports_reference_answer_reachability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "reference_answer": MEMORY_TEXT})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["answer_reachability"], 1.0)
            self.assertEqual(payload["categories"]["uncategorized"]["answer_reachability"], 1.0)
            rows = [
                json.loads(line)
                for line in details.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(rows[0]["answer_expected"])
            self.assertTrue(rows[0]["answer_reachability_hit"])

    def test_layered_recall_benchmark_scores_normalized_answer_overlap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "reference_answer": "Answer-reachability scoring was added.",
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="normalized_answer")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["answer_reachability"], 0.0)
            self.assertEqual(payload["answer_normalized_reachability"], 1.0)
            self.assertEqual(payload["answer_token_f1"], 1.0)
            rows = [
                json.loads(line)
                for line in details.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertFalse(rows[0]["answer_reachability_hit"])
            self.assertTrue(rows[0]["answer_normalized_reachability_hit"])
            self.assertEqual(rows[0]["answer_token_f1"], 1.0)

    def test_answer_reachability_requires_expected_memory_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "reference_answer": "Zebra isotope lantern."})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="answer_wrong_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["answer_reachability"], 0.0)
            self.assertEqual(payload["answer_normalized_reachability"], 0.0)
            self.assertEqual(payload["answer_token_f1"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["answer_reachability_hit"])
            self.assertFalse(detail["answer_normalized_reachability_hit"])
            self.assertEqual(detail["answer_token_f1"], 0.0)
            self.assertIn("answer_reachability", detail["failed_checks"])
            self.assertIn("answer_normalized_reachability", detail["failed_checks"])
            self.assertIn("answer_token_f1", detail["failed_checks"])

    def test_synthetic_builder_includes_reference_answer_for_reachability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "reference_answer": "Layered recall adopted answer reachability scoring.",
                    "required_evidence_paths": [SUMMARY_PATH.replace("/summary.md", "/evidence.md")],
                },
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            memory_index = (repo / "index/memories.jsonl").read_text(encoding="utf-8")
            evidence = (repo / SUMMARY_PATH.replace("/summary.md", "/evidence.md")).read_text(encoding="utf-8")
            self.assertIn("Layered recall adopted answer reachability scoring.", memory_index)
            self.assertIn("Layered recall adopted answer reachability scoring.", evidence)

            result = self.run_benchmark(repo, cases, SEARCH_SCRIPT)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["answer_reachability"], 1.0)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)

    def test_synthetic_builder_writes_default_evidence_file_for_positive_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            cases = self.write_cases(root, self.valid_case())

            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            record = json.loads((repo / "index/memories.jsonl").read_text(encoding="utf-8").splitlines()[0])
            evidence_path = SUMMARY_PATH.replace("/summary.md", "/evidence.md")
            self.assertEqual(record["evidence_refs"], [{"path": evidence_path, "quote_id": "syn_ev_001"}])
            evidence = repo / evidence_path
            self.assertTrue(evidence.is_file())
            self.assertIn("Evidence supporting mem_permission", evidence.read_text(encoding="utf-8"))

    def test_layered_recall_benchmark_checks_reference_evidence_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "required_evidence_paths": [SUMMARY_PATH],
                    "reference_evidence": "Dedicated supporting evidence token.",
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["evidence_reachability"], 1.0)
            self.assertEqual(payload["evidence_text_cases"], 1)
            self.assertEqual(payload["evidence_text_reachability"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            detail = self.read_rows(details)[0]
            self.assertEqual(detail["reference_evidence_count"], 1)
            self.assertFalse(detail["evidence_text_reachability_hit"])
            self.assertIn("evidence_text_reachability", detail["failed_checks"])

    def test_layered_recall_benchmark_refuses_reference_evidence_outside_repo(self):
        scenarios = {
            "absolute": lambda outside: str(outside),
            "parent_escape": lambda outside: "../outside-evidence.md",
        }
        for name, path_text in scenarios.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                repo = self.create_repo(root)
                outside = root / "outside-evidence.md"
                outside.write_text("Dedicated supporting evidence token.", encoding="utf-8")
                cases = self.write_cases(
                    root,
                    {
                        **self.valid_case(),
                        "required_evidence_paths": [path_text(outside)],
                        "reference_evidence": "Dedicated supporting evidence token.",
                    },
                )
                details = root / "details.jsonl"
                search_script, _ = self.write_stub_search(root)

                result = self.run_benchmark(
                    repo,
                    cases,
                    search_script,
                    check=False,
                    extra_args=["--details-jsonl", str(details)],
                )

                combined = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{cases}:1", result.stderr)
                self.assertIn("unsafe archive path in benchmark case field", result.stderr)
                self.assertIn("required_evidence_paths", result.stderr)
                self.assertNotIn("Dedicated supporting evidence token", combined)
                self.assertFalse(details.exists())

    def test_synthetic_builder_includes_reference_evidence_for_reachability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            evidence_path = SUMMARY_PATH.replace("/summary.md", "/evidence.md")
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "required_evidence_paths": [evidence_path],
                    "reference_evidence": "Dedicated supporting evidence token.",
                },
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SYNTHETIC_ARCHIVE_BUILDER),
                    "--repo",
                    str(repo),
                    "--cases",
                    str(cases),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            evidence = (repo / evidence_path).read_text(encoding="utf-8")
            self.assertIn("Dedicated supporting evidence token.", evidence)

            result = self.run_benchmark(repo, cases, SEARCH_SCRIPT)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["evidence_text_cases"], 1)
            self.assertEqual(payload["evidence_text_reachability"], 1.0)

    def test_layered_recall_benchmark_writes_case_details_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 1)
            rows = [
                json.loads(line)
                for line in details.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(rows), 1)
            detail = rows[0]
            self.assertEqual(detail["case_path"], str(cases.resolve()))
            self.assertEqual(detail["case_line"], 1)
            self.assertEqual(detail["query"], "permission prompts")
            self.assertEqual(detail["category"], "uncategorized")
            self.assertEqual(detail["expected_memory_id"], "mem_permission")
            self.assertEqual(detail["memory_rank"], 1)
            self.assertTrue(detail["memory_recall_at_1"])
            self.assertTrue(detail["memory_recall_at_5"])
            self.assertTrue(detail["session_drilldown_hit"])
            self.assertTrue(detail["source_reachability_hit"])
            self.assertTrue(detail["privacy_boundary_pass"])
            self.assertTrue(detail["case_pass"])
            self.assertEqual(detail["failed_checks"], [])
            self.assertGreaterEqual(detail["latency_ms"], 0)

    def test_layered_recall_benchmark_details_list_failed_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "reference_answer": MEMORY_TEXT,
                    "required_evidence_paths": [SUMMARY_PATH],
                    "expected_not_memory_id": "mem_permission_v1",
                    "stale_memory_id": "mem_permission_v1",
                    "category": "knowledge_update",
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 1)
            detail = self.read_rows(details)[0]
            self.assertFalse(detail["case_pass"])
            self.assertEqual(
                detail["failed_checks"],
                [
                    "memory_recall_at_1",
                    "memory_recall_at_5",
                    "session_drilldown_at_5",
                    "source_reachability",
                    "evidence_reachability",
                    "memory_evidence_ref_reachability",
                    "answer_reachability",
                    "answer_normalized_reachability",
                    "answer_token_f1",
                    "update_consistency",
                ],
            )

    def test_layered_recall_benchmark_flags_unexplainable_memory_hit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="low_signal_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["memory_explainability_cases"], 1)
            self.assertEqual(payload["memory_explainability"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            detail = self.read_rows(details)[0]
            self.assertFalse(detail["memory_explainability_hit"])
            self.assertIn("memory_explainability", detail["failed_checks"])

    def test_layered_recall_benchmark_flags_wrong_memory_layer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "expected_layer": "project"})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["layer_calibration_cases"], 1)
            self.assertEqual(payload["layer_calibration"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            detail = self.read_rows(details)[0]
            self.assertEqual(detail["expected_layer"], "project")
            self.assertFalse(detail["layer_calibration_hit"])
            self.assertIn("layer_calibration", detail["failed_checks"])

    def test_layered_recall_benchmark_checks_scope_filtered_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "expected_layer": "global"})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="scope_filter_missing")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["layer_calibration"], 1.0)
            self.assertEqual(payload["scope_filter_cases"], 1)
            self.assertEqual(payload["scope_filter_recall"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            detail = self.read_rows(details)[0]
            self.assertFalse(detail["scope_filter_hit"])
            self.assertIn("scope_filter_recall", detail["failed_checks"])

    def test_scope_filtered_recall_requires_requested_layer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "expected_layer": "global"})
            details = root / "details.jsonl"
            search_script, calls_path = self.write_stub_search(root, mode="scope_wrong_layer")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            calls = calls_path.read_text(encoding="utf-8")
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["layer_calibration"], 1.0)
            self.assertEqual(payload["scope_filter_cases"], 1)
            self.assertEqual(payload["scope_filter_recall"], 0.0)
            self.assertEqual(payload["wrong_scope_suppression"], 1.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["scope_filter_hit"])
            self.assertIn("scope_filter_recall", detail["failed_checks"])
            self.assertIn("memory|global|permission prompts", calls)

    def test_layered_recall_benchmark_flags_wrong_scope_memory_leak(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "expected_layer": "global"})
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="wrong_scope_leak")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["scope_filter_recall"], 1.0)
            self.assertEqual(payload["wrong_scope_suppression_cases"], 1)
            self.assertEqual(payload["wrong_scope_suppression"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            detail = self.read_rows(details)[0]
            self.assertFalse(detail["wrong_scope_suppression_hit"])
            self.assertIn("wrong_scope_suppression", detail["failed_checks"])

    def test_layered_recall_benchmark_details_include_safe_case_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "case_id": "memora:permission_case",
                    "source_benchmark": "Memora",
                    "reference_answer": MEMORY_TEXT,
                    "required_evidence_paths": [SUMMARY_PATH],
                    "expected_not_memory_id": "mem_permission_v1",
                    "stale_memory_id": "mem_permission_v1",
                    "temporal_scope": "latest",
                    "forbidden_output_patterns": ["SYNTHETIC-SECRET"],
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            detail = self.read_rows(details)[0]
            self.assertEqual(detail["case_id"], "memora:permission_case")
            self.assertEqual(detail["source_benchmark"], "Memora")
            self.assertEqual(detail["temporal_scope"], "latest")
            self.assertEqual(detail["expected_not_memory_ids"], ["mem_permission_v1"])
            self.assertEqual(detail["stale_memory_ids"], ["mem_permission_v1"])
            self.assertEqual(detail["required_evidence_paths"], [SUMMARY_PATH])
            self.assertEqual(detail["forbidden_output_patterns_count"], 1)
            self.assertNotIn("reference_answer", detail)
            self.assertNotIn("forbidden_output_patterns", detail)
            self.assertNotIn(MEMORY_TEXT, json.dumps(detail))
            self.assertNotIn("SYNTHETIC-SECRET", json.dumps(detail))

    def test_layered_recall_benchmark_details_sanitize_sensitive_case_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "query": "permission prompts cookie=SHOULD_NOT_RENDER",
                    "case_id": "case cookie=SHOULD_NOT_RENDER",
                    "category": "privacy cookie=SHOULD_NOT_RENDER",
                    "source_benchmark": "Memora cookie=SHOULD_NOT_RENDER",
                    "temporal_scope": "latest cookie=SHOULD_NOT_RENDER",
                    "expected_memory_id": "mem_permission cookie=SHOULD_NOT_RENDER",
                    "expected_not_memory_id": "mem_old cookie=SHOULD_NOT_RENDER",
                    "stale_memory_id": "mem_stale cookie=SHOULD_NOT_RENDER",
                    "expected_summary_path": f"{SUMMARY_PATH} cookie=SHOULD_NOT_RENDER",
                    "expected_source_anchor": f"{SOURCE_ANCHOR} cookie=SHOULD_NOT_RENDER",
                    "required_evidence_paths": [f"{SUMMARY_PATH} cookie=SHOULD_NOT_RENDER"],
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(detail["query"], "[unsafe-result-identifier]")
            self.assertEqual(detail["case_id"], "[unsafe-result-identifier]")
            self.assertEqual(detail["category"], "[unsafe-result-identifier]")
            self.assertEqual(detail["source_benchmark"], "[unsafe-result-identifier]")
            self.assertEqual(detail["temporal_scope"], "[unsafe-result-identifier]")
            self.assertEqual(detail["expected_memory_id"], "[unsafe-result-identifier]")
            self.assertEqual(detail["expected_not_memory_ids"], ["[unsafe-result-identifier]"])
            self.assertEqual(detail["stale_memory_ids"], ["[unsafe-result-identifier]"])
            self.assertEqual(detail["expected_summary_path"], "[unsafe-result-identifier]")
            self.assertEqual(detail["expected_source_anchor"], "[unsafe-result-identifier]")
            self.assertEqual(detail["required_evidence_paths"], ["[unsafe-result-identifier]"])
            self.assertIn("[unsafe-result-identifier]", payload["categories"])
            self.assertNotIn("SHOULD_NOT_RENDER", json.dumps(detail))
            self.assertNotIn("cookie=", json.dumps(detail))
            self.assertNotIn("SHOULD_NOT_RENDER", json.dumps(payload))
            self.assertNotIn("cookie=", json.dumps(payload))

    def test_layered_recall_benchmark_details_sanitize_bare_secret_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            fake_openai_key = "sk-" + "barevalue" + ("0" * 20)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "query": f"permission prompts {fake_openai_key}",
                    "case_id": f"case-{fake_openai_key}",
                    "category": f"privacy-{fake_openai_key}",
                    "source_benchmark": f"Memora-{fake_openai_key}",
                    "expected_memory_id": f"mem_permission-{fake_openai_key}",
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(detail["query"], "[unsafe-result-identifier]")
            self.assertEqual(detail["case_id"], "[unsafe-result-identifier]")
            self.assertEqual(detail["category"], "[unsafe-result-identifier]")
            self.assertEqual(detail["source_benchmark"], "[unsafe-result-identifier]")
            self.assertEqual(detail["expected_memory_id"], "[unsafe-result-identifier]")
            self.assertIn("[unsafe-result-identifier]", payload["categories"])
            self.assertNotIn(fake_openai_key, json.dumps(detail))
            self.assertNotIn(fake_openai_key, json.dumps(payload))

    def test_layered_recall_benchmark_details_include_safe_returned_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            detail = self.read_rows(details)[0]
            self.assertEqual(detail["memory_result_ids"], ["mem_permission"])
            self.assertEqual(
                detail["memory_results_at_5"],
                [
                    {
                        "rank": 1,
                        "memory_id": "mem_permission",
                        "layer": "global",
                        "reasons": [
                            "field:text",
                            "important-token-coverage",
                            "matched:permission, prompts",
                        ],
                        "drill_paths": [SUMMARY_PATH],
                    }
                ],
            )
            self.assertEqual(detail["session_result_paths"], [SUMMARY_PATH])
            self.assertEqual(detail["source_result_ids"], ["mem_permission"])
            self.assertEqual(detail["source_result_anchors"], [SOURCE_ANCHOR])
            self.assertNotIn(MEMORY_TEXT, json.dumps(detail))

    def test_layered_recall_benchmark_details_sanitize_sensitive_returned_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="leaky_anchor")

            self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            detail = self.read_rows(details)[0]
            self.assertEqual(
                detail["source_result_anchors"],
                [SOURCE_ANCHOR, "[unsafe-result-identifier]"],
            )
            self.assertNotIn("SHOULD_NOT_RENDER", json.dumps(detail))
            self.assertNotIn("cookie=", json.dumps(detail))

    def test_source_result_ids_ignore_non_memory_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="source_non_memory_anchor")

            self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            detail = self.read_rows(details)[0]
            self.assertEqual(detail["source_result_ids"], [])
            self.assertEqual(detail["source_result_anchors"], [SOURCE_ANCHOR])

    def test_layered_recall_benchmark_reports_source_anchor_precision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="leaky_anchor")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertIn("source_precision_at_5", payload)
            self.assertEqual(payload["source_precision_at_5"], 0.5)
            self.assertEqual(payload["source_micro_precision_at_5"], 0.5)
            self.assertEqual(payload["source_result_count_at_5"], 2)
            self.assertEqual(payload["source_relevant_count_at_5"], 1)
            self.assertEqual(payload["unsafe_source_anchor_count_at_5"], 1)
            self.assertEqual(payload["unsafe_source_anchor_rate_at_5"], 0.5)
            self.assertIn("source_precision_at_5", detail)
            self.assertEqual(detail["source_precision_at_5"], 0.5)
            self.assertEqual(detail["source_result_count_at_5"], 2)
            self.assertEqual(detail["source_relevant_count_at_5"], 1)
            self.assertEqual(detail["unsafe_source_anchor_count_at_5"], 1)
            self.assertEqual(detail["unsafe_source_anchor_rate_at_5"], 0.5)

    def test_source_reachability_requires_expected_memory_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="source_wrong_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["source_reachability_hit"])
            self.assertEqual(detail["source_result_ids"], ["mem_other"])
            self.assertEqual(detail["source_result_anchors"], [SOURCE_ANCHOR])
            self.assertIn("source_reachability", detail["failed_checks"])

    def test_source_anchor_precision_requires_expected_memory_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="source_wrong_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["source_reachability"], 0.0)
            self.assertEqual(payload["source_precision_at_5"], 0.0)
            self.assertEqual(payload["source_micro_precision_at_5"], 0.0)
            self.assertEqual(payload["source_result_count_at_5"], 1)
            self.assertEqual(payload["source_relevant_count_at_5"], 0)
            self.assertEqual(detail["source_precision_at_5"], 0.0)
            self.assertEqual(detail["source_result_count_at_5"], 1)
            self.assertEqual(detail["source_relevant_count_at_5"], 0)

    def test_source_metrics_require_memory_source_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="source_non_memory_anchor")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["source_reachability"], 0.0)
            self.assertEqual(payload["source_precision_at_5"], 0.0)
            self.assertEqual(payload["source_micro_precision_at_5"], 0.0)
            self.assertEqual(payload["source_result_count_at_5"], 1)
            self.assertEqual(payload["source_relevant_count_at_5"], 0)
            self.assertFalse(detail["source_reachability_hit"])
            self.assertIn("source_reachability", detail["failed_checks"])

    def test_layered_recall_benchmark_details_sanitize_sensitive_returned_reasons(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="sensitive_reason")

            self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            detail = self.read_rows(details)[0]
            reasons = detail["memory_results_at_5"][0]["reasons"]
            self.assertEqual(
                reasons,
                [
                    "[unsafe-result-identifier]",
                    "important-token-coverage",
                    "matched:permission, prompts",
                ],
            )
            self.assertNotIn("field:session_id", json.dumps(detail))

    def test_layered_recall_benchmark_details_sanitize_unsafe_returned_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="leaky_path")

            self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            detail = self.read_rows(details)[0]
            self.assertEqual(detail["session_result_paths"], ["[unsafe-result-identifier]"])
            self.assertEqual(
                detail["source_result_anchors"],
                [SOURCE_ANCHOR, "[unsafe-result-identifier]"],
            )
            self.assertNotIn("/Users/private", json.dumps(detail))
            self.assertNotIn("../outside", json.dumps(detail))

    def test_layered_recall_benchmark_fails_under_metric_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under", "memory_recall_at_5=0.5"],
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["memory_recall_at_5"], 0.0)
            self.assertIn("memory_recall_at_5=0.0 below threshold 0.5", result.stderr)

    def test_layered_recall_benchmark_rejects_non_finite_metric_values(self):
        benchmark = runpy.run_path(str(SCRIPT))
        threshold_failure_details = benchmark["threshold_failure_details"]

        for metric_value in (math.nan, math.inf, -math.inf):
            with self.subTest(metric_value=metric_value):
                with self.assertRaises(SystemExit) as error:
                    threshold_failure_details(
                        {"source_precision_at_5": metric_value},
                        [("source_precision_at_5", 0.25)],
                    )

                self.assertIn(
                    "--fail-under metric is not finite in benchmark output: source_precision_at_5",
                    str(error.exception),
                )

    def test_layered_recall_benchmark_rejects_non_finite_direct_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under", "memory_recall_at_5=nan"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--fail-under threshold must be finite for memory_recall_at_5", result.stderr)

    def test_layered_recall_benchmark_sanitizes_sensitive_direct_threshold_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under", "memory_recall_at_5=cookie=SHOULD_NOT_RENDER"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "--fail-under threshold must be numeric for memory_recall_at_5: [unsafe-result-identifier]",
                result.stderr,
            )
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_layered_recall_benchmark_sanitizes_sensitive_threshold_metric_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under", "api_key:SHOULD_NOT_RENDER=0.5"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "--fail-under metric is not numeric in benchmark output: [unsafe-result-identifier]",
                result.stderr,
            )
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("api_key:", result.stderr)

    def test_layered_recall_benchmark_writes_structured_threshold_failures_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "case_id": "synthetic:permission_prompt",
                    "category": "information_extraction",
                    "source_benchmark": "LongMemEval",
                },
            )
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-under",
                    "memory_recall_at_5=0.5",
                    "--failures-json",
                    str(failures),
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            self.assertEqual(failure_payload["failure_count"], 1)
            self.assertEqual(failure_payload["cases"], 1)
            self.assertEqual(failure_payload["failed_case_count"], payload["failed_case_count"])
            self.assertEqual(failure_payload["case_pass_rate"], payload["case_pass_rate"])
            self.assertEqual(failure_payload["cases_path"], payload["cases_path"])
            self.assertEqual(failure_payload["cases_sha256"], payload["cases_sha256"])
            self.assertEqual(failure_payload["search_script_path"], payload["search_script_path"])
            self.assertEqual(failure_payload["search_script_sha256"], payload["search_script_sha256"])
            self.assertEqual(
                failure_payload["failed_cases"],
                [
                    {
                        "case_id": "synthetic:permission_prompt",
                        "case_line": 1,
                        "category": "information_extraction",
                        "failed_checks": [
                            "memory_recall_at_1",
                            "memory_recall_at_5",
                            "session_drilldown_at_5",
                            "source_reachability",
                        ],
                        "memory_ndcg_at_5": 0.0,
                        "memory_precision_at_5": 0.0,
                        "memory_explainability_hit": False,
                        "layer_calibration_hit": False,
                        "scope_filter_hit": False,
                        "wrong_scope_suppression_hit": False,
                        "memory_rank": None,
                        "memory_recall_at_1": False,
                        "memory_recall_at_5": False,
                        "memory_relevant_count_at_5": 0,
                        "memory_result_count_at_5": 0,
                        "memory_result_ids": [],
                        "memory_results_at_5": [],
                        "session_drilldown_hit": False,
                        "session_result_paths": [],
                        "evidence_reachability_hit": False,
                        "evidence_text_reachability_hit": False,
                        "answer_expected": False,
                        "answer_reachability_hit": False,
                        "answer_normalized_reachability_hit": False,
                        "answer_token_f1": 0.0,
                        "source_benchmark": "LongMemEval",
                        "source_result_anchors": [],
                        "source_result_ids": [],
                        "source_reachability_hit": False,
                        "source_precision_at_5": 0.0,
                        "source_relevant_count_at_5": 0,
                        "source_result_count_at_5": 0,
                        "unsafe_source_anchor_count_at_5": 0,
                        "unsafe_source_anchor_rate_at_5": 0.0,
                        "negative_memory_suppression_hit": True,
                        "stale_memory_suppression_hit": True,
                        "update_consistency_hit": False,
                        "privacy_boundary_pass": True,
                    }
                ],
            )
            self.assertNotIn("query", failure_payload["failed_cases"][0])
            self.assertNotIn("expected_memory_id", failure_payload["failed_cases"][0])
            self.assertEqual(
                failure_payload["failures"],
                [
                    {
                        "comparison": "below",
                        "metric": "memory_recall_at_5",
                        "threshold": 0.5,
                        "value": 0.0,
                    }
                ],
            )

    def test_layered_recall_benchmark_failures_json_sanitizes_sensitive_category(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "case_id": "synthetic:permission_prompt",
                    "category": "privacy cookie=SHOULD_NOT_RENDER",
                    "source_benchmark": "LongMemEval",
                },
            )
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-under",
                    "memory_recall_at_5=0.5",
                    "--failures-json",
                    str(failures),
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            self.assertEqual(failure_payload["failed_cases"][0]["category"], "[unsafe-result-identifier]")
            self.assertNotIn("SHOULD_NOT_RENDER", json.dumps(failure_payload))
            self.assertNotIn("cookie=", json.dumps(failure_payload))

    def test_layered_recall_benchmark_failures_json_sanitizes_returned_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(root, mode="leaky_path")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-over",
                    "failed_case_count=0",
                    "--failures-json",
                    str(failures),
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            failed_case = failure_payload["failed_cases"][0]
            self.assertEqual(failed_case["session_result_paths"], ["[unsafe-result-identifier]"])
            self.assertEqual(
                failed_case["source_result_anchors"],
                [SOURCE_ANCHOR, "[unsafe-result-identifier]"],
            )
            self.assertNotIn("/Users/private", json.dumps(failure_payload))
            self.assertNotIn("../outside", json.dumps(failure_payload))

    def test_layered_recall_benchmark_failures_json_includes_memory_result_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(root, mode="low_signal_memory")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-over",
                    "failed_case_count=0",
                    "--failures-json",
                    str(failures),
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            failed_case = failure_payload["failed_cases"][0]
            self.assertEqual(
                failed_case["memory_results_at_5"],
                [
                    {
                        "rank": 1,
                        "memory_id": "mem_permission",
                        "layer": "global",
                        "reasons": [
                            "low-signal-only",
                            "broad-field-only",
                            "matched:memory, session",
                        ],
                        "drill_paths": [SUMMARY_PATH],
                    }
                ],
            )

    def test_layered_recall_benchmark_failures_json_includes_answer_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "case_id": "synthetic:answer_gap",
                    "reference_answer": "The archive should surface the dedicated answer diagnostic.",
                },
            )
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-over",
                    "failed_case_count=0",
                    "--failures-json",
                    str(failures),
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            failed_case = failure_payload["failed_cases"][0]
            self.assertEqual(failed_case["case_id"], "synthetic:answer_gap")
            self.assertTrue(failed_case["answer_expected"])
            self.assertFalse(failed_case["answer_reachability_hit"])
            self.assertFalse(failed_case["answer_normalized_reachability_hit"])
            self.assertEqual(failed_case["answer_token_f1"], 0.0)
            self.assertNotIn("reference_answer", failed_case)
            self.assertNotIn("dedicated answer diagnostic", json.dumps(failure_payload))

    def test_layered_recall_benchmark_sanitizes_sensitive_payload_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            sensitive_input_root = root / "inputs-cookie=SHOULD_NOT_RENDER"
            sensitive_input_root.mkdir()
            cases = self.write_cases(sensitive_input_root, self.valid_case())
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(sensitive_input_root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-under",
                    "memory_recall_at_5=0.5",
                    "--failures-json",
                    str(failures),
                ],
            )

            payload = json.loads(result.stdout)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            combined = result.stdout + result.stderr + failures.read_text(encoding="utf-8")
            self.assertEqual(payload["cases_path"], "[unsafe-result-identifier]")
            self.assertEqual(payload["search_script_path"], "[unsafe-result-identifier]")
            self.assertEqual(failure_payload["cases_path"], "[unsafe-result-identifier]")
            self.assertEqual(failure_payload["search_script_path"], "[unsafe-result-identifier]")
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_layered_recall_benchmark_details_jsonl_sanitizes_sensitive_case_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            sensitive_cases_root = root / "cases-cookie=SHOULD_NOT_RENDER"
            sensitive_cases_root.mkdir()
            cases = self.write_cases(sensitive_cases_root, self.valid_case())
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = json.loads(details.read_text(encoding="utf-8").strip())
            combined = result.stdout + result.stderr + details.read_text(encoding="utf-8")
            self.assertEqual(payload["cases_path"], "[unsafe-result-identifier]")
            self.assertEqual(detail["case_path"], "[unsafe-result-identifier]")
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_layered_recall_benchmark_details_jsonl_write_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            sensitive_details_path = root / "details-cookie=SHOULD_NOT_RENDER"
            sensitive_details_path.mkdir()
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(sensitive_details_path)],
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to write --details-jsonl", result.stderr)
            self.assertIn("[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_layered_recall_benchmark_writes_empty_threshold_failures_json_when_gates_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            failures = root / "failures.json"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=[
                    "--fail-under",
                    "memory_recall_at_5=1.0",
                    "--failures-json",
                    str(failures),
                ],
            )

            payload = json.loads(result.stdout)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            self.assertEqual(payload["memory_recall_at_5"], 1.0)
            self.assertEqual(failure_payload["failure_count"], 0)
            self.assertEqual(failure_payload["cases"], 1)
            self.assertEqual(failure_payload["failed_case_count"], payload["failed_case_count"])
            self.assertEqual(failure_payload["case_pass_rate"], payload["case_pass_rate"])
            self.assertEqual(failure_payload["cases_path"], payload["cases_path"])
            self.assertEqual(failure_payload["cases_sha256"], payload["cases_sha256"])
            self.assertEqual(failure_payload["search_script_path"], payload["search_script_path"])
            self.assertEqual(failure_payload["search_script_sha256"], payload["search_script_sha256"])
            self.assertEqual(failure_payload["failed_cases"], [])
            self.assertEqual(failure_payload["failures"], [])

    def test_layered_recall_benchmark_failures_json_write_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            sensitive_failures_path = root / "failures-cookie=SHOULD_NOT_RENDER"
            sensitive_failures_path.mkdir()
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--failures-json", str(sensitive_failures_path)],
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to write --failures-json", result.stderr)
            self.assertIn("[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_layered_recall_benchmark_accepts_nested_category_fail_under_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "category": "knowledge_update"})
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--fail-under", "categories.knowledge_update.memory_recall_at_5=1.0"],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["categories"]["knowledge_update"]["memory_recall_at_5"], 1.0)

    def test_layered_recall_benchmark_fails_under_nested_category_metric_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "category": "knowledge_update"})
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under", "categories.knowledge_update.memory_recall_at_5=0.5"],
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["categories"]["knowledge_update"]["memory_recall_at_5"], 0.0)
            self.assertIn(
                "categories.knowledge_update.memory_recall_at_5=0.0 below threshold 0.5",
                result.stderr,
            )

    def test_layered_recall_benchmark_fails_over_metric_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-over", "latency_max_ms=-1"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stdout, result.stderr)
            payload = json.loads(result.stdout)
            self.assertGreaterEqual(payload["latency_max_ms"], 0)
            self.assertIn("latency_max_ms=", result.stderr)
            self.assertIn("above threshold -1.0", result.stderr)

    def test_layered_recall_benchmark_accepts_fail_under_threshold_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "category": "knowledge_update"})
            threshold_file = root / "thresholds.json"
            threshold_file.write_text(
                json.dumps(
                    {
                        "memory_recall_at_5": 1.0,
                        "categories.knowledge_update.memory_recall_at_5": 1.0,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=["--fail-under-file", str(threshold_file)],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["memory_recall_at_5"], 1.0)

    def test_layered_recall_benchmark_fails_over_threshold_file_metric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            threshold_file = root / "max-thresholds.json"
            failures = root / "failures.json"
            threshold_file.write_text(json.dumps({"latency_max_ms": -1}, sort_keys=True), encoding="utf-8")
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=[
                    "--fail-over-file",
                    str(threshold_file),
                    "--failures-json",
                    str(failures),
                ],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(result.stdout, result.stderr)
            payload = json.loads(result.stdout)
            failure_payload = json.loads(failures.read_text(encoding="utf-8"))
            self.assertGreaterEqual(payload["latency_max_ms"], 0)
            self.assertEqual(failure_payload["failure_count"], 1)
            self.assertEqual(
                failure_payload["failures"],
                [
                    {
                        "comparison": "above",
                        "metric": "latency_max_ms",
                        "threshold": -1.0,
                        "value": payload["latency_max_ms"],
                    }
                ],
            )

    def test_layered_recall_benchmark_direct_fail_over_overrides_threshold_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            threshold_file = root / "max-thresholds.json"
            threshold_file.write_text(json.dumps({"latency_max_ms": -1}, sort_keys=True), encoding="utf-8")
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                extra_args=[
                    "--fail-over-file",
                    str(threshold_file),
                    "--fail-over",
                    "latency_max_ms=999999",
                ],
            )

            payload = json.loads(result.stdout)
            self.assertLessEqual(payload["latency_max_ms"], 999999)

    def test_layered_recall_benchmark_fails_under_threshold_file_metric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "category": "knowledge_update"})
            threshold_file = root / "thresholds.json"
            threshold_file.write_text(
                json.dumps({"categories.knowledge_update.memory_recall_at_5": 0.5}, sort_keys=True),
                encoding="utf-8",
            )
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under-file", str(threshold_file)],
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["categories"]["knowledge_update"]["memory_recall_at_5"], 0.0)
            self.assertIn(
                "categories.knowledge_update.memory_recall_at_5=0.0 below threshold 0.5",
                result.stderr,
            )

    def test_layered_recall_benchmark_rejects_non_numeric_threshold_file_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            threshold_file = root / "thresholds.json"
            threshold_file.write_text(json.dumps({"memory_recall_at_5": "strict"}), encoding="utf-8")
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under-file", str(threshold_file)],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--fail-under-file threshold must be numeric for memory_recall_at_5", result.stderr)

    def test_layered_recall_benchmark_rejects_non_finite_threshold_file_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            threshold_file = root / "thresholds.json"
            threshold_file.write_text('{"memory_recall_at_5": Infinity}', encoding="utf-8")
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under-file", str(threshold_file)],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--fail-under-file threshold must be finite for memory_recall_at_5", result.stderr)

    def test_layered_recall_benchmark_reports_missing_threshold_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            missing_threshold_file = root / "missing-thresholds.json"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under-file", str(missing_threshold_file)],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to read --fail-under-file", result.stderr)
            self.assertIn(str(missing_threshold_file), result.stderr)

    def test_layered_recall_benchmark_sanitizes_sensitive_threshold_file_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            sensitive_threshold_root = root / "thresholds-cookie=SHOULD_NOT_RENDER"
            sensitive_threshold_root.mkdir()
            missing_threshold_file = sensitive_threshold_root / "missing-thresholds.json"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-under-file", str(missing_threshold_file)],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to read --fail-under-file", result.stderr)
            self.assertIn("[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_broken_search_script_fails_with_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            missing_search_script = root / "missing_search.py"

            result = self.run_benchmark(repo, cases, missing_search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("search failed", result.stderr)
            self.assertIn("depth=memory", result.stderr)
            self.assertIn("query='permission prompts'", result.stderr)
            self.assertIn("returncode=", result.stderr)
            self.assertIn(str(missing_search_script), result.stderr)

    def test_broken_search_script_sanitizes_sensitive_query_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {**self.valid_case(), "query": "permission prompts cookie=SHOULD_NOT_RENDER"},
            )
            missing_search_script = root / "missing_search.py"

            result = self.run_benchmark(repo, cases, missing_search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("search failed", result.stderr)
            self.assertIn("depth=memory", result.stderr)
            self.assertIn("query='[unsafe-result-identifier]'", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_broken_search_script_sanitizes_sensitive_script_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            sensitive_script_root = root / "scripts-cookie=SHOULD_NOT_RENDER"
            sensitive_script_root.mkdir()
            missing_search_script = sensitive_script_root / "missing_search.py"

            result = self.run_benchmark(repo, cases, missing_search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("search failed", result.stderr)
            self.assertIn("script=[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_broken_search_script_sanitizes_sensitive_child_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script = root / "leaky_search.py"
            search_script.write_text(
                "import sys\n"
                "print('cookie=SHOULD_NOT_RENDER', file=sys.stderr)\n"
                "raise SystemExit(2)\n",
                encoding="utf-8",
            )

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("search failed", result.stderr)
            self.assertIn("stderr:\n[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_search_timeout_fails_with_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root, mode="slow")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--search-timeout-s", "0.01"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("search timed out", result.stderr)
            self.assertIn("depth=memory", result.stderr)
            self.assertIn("query='permission prompts'", result.stderr)
            self.assertIn("timeout_s=0.01", result.stderr)
            self.assertIn(str(search_script), result.stderr)

    def test_search_timeout_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--search-timeout-s", "0"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--search-timeout-s must be greater than 0", result.stderr)

    def test_search_timeout_must_be_finite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--search-timeout-s", "nan"],
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--search-timeout-s must be finite", result.stderr)

    def test_missing_required_field_reports_cases_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {"query": "permission prompts", "expected_memory_id": "mem_permission"})
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"{cases}:1", result.stderr)
            self.assertIn("expected_summary_path", result.stderr)

    def test_missing_required_field_sanitizes_sensitive_cases_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            sensitive_cases_root = root / "cases-cookie=SHOULD_NOT_RENDER"
            sensitive_cases_root.mkdir()
            cases = self.write_cases(
                sensitive_cases_root,
                {"query": "permission prompts", "expected_memory_id": "mem_permission"},
            )
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("[unsafe-result-identifier]:1", result.stderr)
            self.assertIn("expected_summary_path", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_benchmark_case_archive_paths_must_not_escape_repo(self):
        scenarios = (
            ("expected_summary_path", {"expected_summary_path": "../outside/summary.md"}),
            ("expected_source_anchor", {"expected_source_anchor": "../outside/raw.jsonl#message:1"}),
            ("required_evidence_paths", {"required_evidence_paths": ["../outside/evidence.md"]}),
        )
        for field, override in scenarios:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    repo = self.create_repo(root)
                    cases = self.write_cases(root, {**self.valid_case(), **override})
                    search_script, _ = self.write_stub_search(root)

                    result = self.run_benchmark(repo, cases, search_script, check=False)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"{cases}:1", result.stderr)
                    self.assertIn("unsafe archive path in benchmark case field", result.stderr)
                    self.assertIn(field, result.stderr)

    def test_invalid_source_benchmark_type_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "source_benchmark": ["Memora"]})
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"{cases}:1", result.stderr)
            self.assertIn("source_benchmark", result.stderr)
            self.assertIn("must be string", result.stderr)

    def test_invalid_expected_layer_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, {**self.valid_case(), "expected_layer": "workspace"})
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"{cases}:1", result.stderr)
            self.assertIn("expected_layer must be global, domain, or project", result.stderr)

    def test_duplicate_case_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {**self.valid_case(), "case_id": "longmemeval:lme_q1"},
                {
                    **self.valid_case(),
                    "query": "permission prompts second",
                    "case_id": "longmemeval:lme_q1",
                },
            )
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            resolved_cases = cases.resolve()
            self.assertIn(f"{resolved_cases}:2", result.stderr)
            self.assertIn("duplicate case_id", result.stderr)
            self.assertIn("longmemeval:lme_q1", result.stderr)
            self.assertIn(f"first seen at {resolved_cases}:1", result.stderr)

    def test_duplicate_case_id_error_sanitizes_sensitive_identifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {**self.valid_case(), "case_id": "case cookie=SHOULD_NOT_RENDER"},
                {
                    **self.valid_case(),
                    "query": "permission prompts second",
                    "case_id": "case cookie=SHOULD_NOT_RENDER",
                },
            )
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            resolved_cases = cases.resolve()
            self.assertIn(f"{resolved_cases}:2", result.stderr)
            self.assertIn("duplicate case_id", result.stderr)
            self.assertIn("[unsafe-result-identifier]", result.stderr)
            self.assertIn(f"first seen at {resolved_cases}:1", result.stderr)
            self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
            self.assertNotIn("cookie=", result.stderr)

    def test_duplicate_case_id_error_sanitizes_sensitive_slug_identifier(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {**self.valid_case(), "case_id": "longmemeval:cookie_should_not_render"},
                {
                    **self.valid_case(),
                    "query": "permission prompts second",
                    "case_id": "longmemeval:cookie_should_not_render",
                },
            )
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate case_id", result.stderr)
            self.assertIn("[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("cookie_should_not_render", result.stderr)
            self.assertNotIn("cookie", result.stderr)

    def test_non_object_jsonl_row_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = root / "cases.jsonl"
            cases.write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"{cases}:1", result.stderr)
            self.assertIn("expected object", result.stderr)

    def test_empty_cases_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = root / "cases.jsonl"
            cases.write_text("", encoding="utf-8")
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no benchmark cases", result.stderr)
            self.assertIn(str(cases), result.stderr)

    def test_missing_cases_file_reports_controlled_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            sensitive_cases_root = root / "cases-cookie=SHOULD_NOT_RENDER"
            missing_cases = sensitive_cases_root / "missing.jsonl"
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, missing_cases, search_script, check=False)

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to read JSONL", result.stderr)
            self.assertIn("[unsafe-result-identifier]", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie=", combined)

    def test_distractor_blocks_do_not_count_split_expected_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root, mode="distractor")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 1)
            self.assertEqual(payload["memory_recall_at_5"], 0.0)
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 0.0)

    def test_no_hit_search_exit_code_scores_as_zero_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 1)
            self.assertEqual(payload["memory_recall_at_5"], 0.0)
            self.assertEqual(payload["session_drilldown_at_5"], 0.0)
            self.assertEqual(payload["source_reachability"], 0.0)

    def test_missing_memory_repo_file_reports_controlled_sanitized_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_secret = "sk-" + "missingrepo" + ("0" * 20)
            missing_repo = root / f"archive-{fake_secret}"
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(missing_repo, cases, search_script, check=False)

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memory archive is missing required file", result.stderr)
            self.assertNotIn("Traceback", combined)
            self.assertNotIn(fake_secret, combined)

    def test_benchmark_reports_public_benchmark_inspired_quality_metrics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            self.append_memory_records(
                repo,
                {
                    "memory_id": "mem_permission_v1",
                    "topic": "permission-prompts",
                    "text": "Ask for permission again after every command.",
                    "derived_from": ["sessions/2026/05/01/source/summary.md"],
                    "superseded_by": "mem_permission",
                    "raw_refs": [{"path": "records/private.jsonl", "anchor": "message:1"}],
                },
                {
                    "memory_id": "mem_other",
                    "topic": "unrelated",
                    "text": "Unrelated memory distractor.",
                    "derived_from": ["sessions/2026/04/01/source/summary.md"],
                    "raw_refs": [],
                },
            )
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "category": "knowledge_update",
                    "expected_not_memory_id": "mem_permission_v1",
                    "stale_memory_id": "mem_permission_v1",
                    "required_evidence_paths": [SUMMARY_PATH],
                    "forbidden_output_patterns": ["FAKE RAW PRIVATE CONTENT"],
                    "temporal_scope": "latest",
                },
                {
                    "query": "nonexistent migration ritual",
                    "category": "abstention",
                    "expected_abstain": True,
                    "forbidden_output_patterns": ["fabricated migration answer"],
                },
            )
            search_script, _ = self.write_stub_search(root, mode="quality")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 2)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["memory_recall_at_5"], 1.0)
            self.assertEqual(payload["memory_mrr"], 1.0)
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["evidence_reachability"], 1.0)
            self.assertEqual(payload["abstention_accuracy"], 1.0)
            self.assertEqual(payload["negative_memory_suppression"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)
            self.assertEqual(payload["update_consistency"], 1.0)
            self.assertEqual(payload["privacy_boundary_pass_rate"], 1.0)
            self.assertGreaterEqual(payload["latency_ms"], 0)
            self.assertEqual(payload["categories"]["knowledge_update"]["cases"], 1)
            self.assertEqual(payload["categories"]["knowledge_update"]["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["categories"]["knowledge_update"]["update_consistency"], 1.0)
            self.assertEqual(payload["categories"]["abstention"]["cases"], 1)
            self.assertEqual(payload["categories"]["abstention"]["abstention_accuracy"], 1.0)

    def test_forbidden_output_patterns_are_regular_expressions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "forbidden_output_patterns": [r"FAKE\s+RAW\s+PRIVATE\s+CONTENT"],
                },
            )
            search_script, _ = self.write_stub_search(root, mode="leaky")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["privacy_boundary_pass_rate"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)

    def test_privacy_boundary_checks_successful_search_stderr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "forbidden_output_patterns": ["STDERR-ONLY-LEAK"],
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="stderr_leaky")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["privacy_boundary_pass_rate"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["privacy_boundary_pass"])
            self.assertIn("privacy_boundary_pass_rate", detail["failed_checks"])

    def test_privacy_boundary_checks_scope_search_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "expected_layer": "global",
                    "forbidden_output_patterns": ["SCOPE-ONLY-LEAK"],
                },
            )
            details = root / "details.jsonl"
            search_script, _ = self.write_stub_search(root, mode="scope_leaky")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            self.assertEqual(payload["scope_filter_recall"], 1.0)
            self.assertEqual(payload["wrong_scope_suppression"], 1.0)
            self.assertEqual(payload["privacy_boundary_pass_rate"], 0.0)
            self.assertFalse(detail["privacy_boundary_pass"])
            self.assertIn("privacy_boundary_pass_rate", detail["failed_checks"])

    def test_abstention_checks_scope_search_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    "query": "unsupported scoped recall",
                    "category": "abstention",
                    "expected_abstain": True,
                    "forbidden_output_patterns": ["SCOPED-ABSTAIN-LEAK"],
                },
            )
            details = root / "details.jsonl"
            search_script, calls_path = self.write_stub_search(root, mode="abstain_scope_leaky")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            calls = calls_path.read_text(encoding="utf-8")
            self.assertEqual(payload["abstention_accuracy"], 0.0)
            self.assertEqual(payload["privacy_boundary_pass_rate"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["abstention_hit"])
            self.assertFalse(detail["privacy_boundary_pass"])
            self.assertIn("abstention_accuracy", detail["failed_checks"])
            self.assertIn("privacy_boundary_pass_rate", detail["failed_checks"])
            self.assertIn("memory|global|unsupported scoped recall", calls)
            self.assertIn("memory|domain|unsupported scoped recall", calls)
            self.assertIn("memory|project|unsupported scoped recall", calls)

    def test_abstention_rejects_unstructured_non_nohit_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    "query": "unsupported unstructured recall",
                    "category": "abstention",
                    "expected_abstain": True,
                },
            )
            details = root / "details.jsonl"
            search_script, calls_path = self.write_stub_search(root, mode="abstain_unstructured")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            calls = calls_path.read_text(encoding="utf-8")
            self.assertEqual(payload["abstention_accuracy"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["abstention_hit"])
            self.assertIn("abstention_accuracy", detail["failed_checks"])
            self.assertIn("memory|all|unsupported unstructured recall", calls)
            self.assertIn("memory|global|unsupported unstructured recall", calls)

    def test_suppression_checks_scope_search_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            self.append_memory_records(
                repo,
                {
                    "memory_id": "mem_scoped_forbidden",
                    "topic": "superseded-permission-prompts",
                    "text": "Forbidden scoped permission behavior",
                    "derived_from": [SUMMARY_PATH],
                    "raw_refs": [],
                },
            )
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "category": "knowledge_update",
                    "expected_layer": "global",
                    "expected_not_memory_id": "mem_scoped_forbidden",
                    "stale_memory_id": "mem_scoped_forbidden",
                },
            )
            details = root / "details.jsonl"
            search_script, calls_path = self.write_stub_search(root, mode="scope_suppression_leak")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--details-jsonl", str(details)],
            )

            payload = json.loads(result.stdout)
            detail = self.read_rows(details)[0]
            calls = calls_path.read_text(encoding="utf-8")
            self.assertEqual(payload["scope_filter_recall"], 1.0)
            self.assertEqual(payload["wrong_scope_suppression"], 1.0)
            self.assertEqual(payload["negative_memory_suppression"], 0.0)
            self.assertEqual(payload["stale_memory_suppression"], 0.0)
            self.assertEqual(payload["update_consistency"], 0.0)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertFalse(detail["negative_memory_suppression_hit"])
            self.assertFalse(detail["stale_memory_suppression_hit"])
            self.assertIn("negative_memory_suppression", detail["failed_checks"])
            self.assertIn("stale_memory_suppression", detail["failed_checks"])
            self.assertIn("memory|global|permission prompts", calls)

    def test_invalid_forbidden_output_pattern_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "forbidden_output_patterns": ["["],
                },
            )
            search_script, _ = self.write_stub_search(root)

            result = self.run_benchmark(repo, cases, search_script, check=False)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"{cases}:1", result.stderr)
            self.assertIn("invalid forbidden_output_patterns[0]", result.stderr)

    def test_expected_memory_id_must_not_be_also_forbidden_or_stale(self):
        for conflicting_key in ("expected_not_memory_id", "stale_memory_id"):
            with self.subTest(conflicting_key=conflicting_key):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    repo = self.create_repo(root)
                    cases = self.write_cases(
                        root,
                        {
                            **self.valid_case(),
                            conflicting_key: "mem_permission",
                        },
                    )
                    search_script, _ = self.write_stub_search(root)

                    result = self.run_benchmark(repo, cases, search_script, check=False)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"{cases}:1", result.stderr)
                    self.assertIn(f"expected_memory_id must not also appear in {conflicting_key}", result.stderr)

    def test_layered_recall_benchmark_reports_metric_denominators(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            self.append_memory_records(
                repo,
                {
                    "memory_id": "mem_permission_v1",
                    "topic": "permission-prompts",
                    "text": "Ask for permission again after every command.",
                    "derived_from": ["sessions/2026/05/01/source/summary.md"],
                    "superseded_by": "mem_permission",
                    "raw_refs": [{"path": "records/private.jsonl", "anchor": "message:1"}],
                },
            )
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "category": "knowledge_update",
                    "reference_answer": MEMORY_TEXT,
                    "expected_not_memory_id": "mem_permission_v1",
                    "stale_memory_id": "mem_permission_v1",
                    "required_evidence_paths": [SUMMARY_PATH],
                },
                {
                    "query": "nonexistent migration ritual",
                    "category": "abstention",
                    "expected_abstain": True,
                },
            )
            search_script, _ = self.write_stub_search(root, mode="quality")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 2)
            self.assertEqual(payload["positive_cases"], 1)
            self.assertEqual(payload["session_cases"], 1)
            self.assertEqual(payload["source_cases"], 1)
            self.assertEqual(payload["evidence_cases"], 1)
            self.assertEqual(payload["answer_cases"], 1)
            self.assertEqual(payload["abstain_cases"], 1)
            self.assertEqual(payload["negative_cases"], 1)
            self.assertEqual(payload["stale_cases"], 1)
            self.assertEqual(payload["update_cases"], 1)
            self.assertEqual(payload["privacy_cases"], 2)
            self.assertEqual(payload["categories"]["knowledge_update"]["positive_cases"], 1)
            self.assertEqual(payload["categories"]["knowledge_update"]["answer_cases"], 1)
            self.assertEqual(payload["categories"]["abstention"]["abstain_cases"], 1)
            self.assertEqual(payload["categories"]["abstention"]["positive_cases"], 0)

    def test_layered_recall_benchmark_reports_failed_case_count_and_pass_rate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertEqual(payload["case_pass_rate"], 0.0)
            self.assertEqual(payload["categories"]["uncategorized"]["failed_case_count"], 1)
            self.assertEqual(payload["categories"]["uncategorized"]["case_pass_rate"], 0.0)

    def test_layered_recall_benchmark_can_gate_failed_case_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(
                repo,
                cases,
                search_script,
                check=False,
                extra_args=["--fail-over", "failed_case_count=0"],
            )

            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["failed_case_count"], 1)
            self.assertIn("failed_case_count=1.0 above threshold 0.0", result.stderr)

    def test_abstention_case_must_not_require_positive_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    "query": "missing context should abstain",
                    "category": "abstention",
                    "expected_abstain": True,
                },
            )
            search_script, _ = self.write_stub_search(root, mode="nohit")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 1)
            self.assertEqual(payload["abstention_accuracy"], 1.0)

    def test_expected_not_memory_id_fails_when_distractor_block_contains_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(
                root,
                {
                    **self.valid_case(),
                    "expected_not_memory_id": "mem_forbidden",
                    "stale_memory_id": "mem_forbidden",
                    "category": "knowledge_update",
                },
            )
            search_script, _ = self.write_stub_search(root, mode="forbidden")

            result = self.run_benchmark(repo, cases, search_script)

            payload = json.loads(result.stdout)
            self.assertEqual(payload["negative_memory_suppression"], 0.0)
            self.assertEqual(payload["stale_memory_suppression"], 0.0)
            self.assertEqual(payload["update_consistency"], 0.0)

    def create_repo(self, root):
        repo = root / "agent-memory"
        (repo / "index").mkdir(parents=True)
        (repo / "index/memories.jsonl").write_text(
            json.dumps(
                {
                    "memory_id": "mem_permission",
                    "topic": "permission-prompts",
                    "text": MEMORY_TEXT,
                    "derived_from": [SUMMARY_PATH],
                    "raw_refs": [{"path": "records/private.jsonl", "anchor": "message:42"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return repo

    def valid_case(self):
        return {
            "query": "permission prompts",
            "expected_memory_id": "mem_permission",
            "expected_summary_path": SUMMARY_PATH,
            "expected_source_anchor": SOURCE_ANCHOR,
        }

    def append_memory_records(self, repo, *rows):
        with (repo / "index/memories.jsonl").open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def write_cases(self, root, *rows):
        cases = root / "cases.jsonl"
        cases.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return cases

    def write_stub_search(self, root, mode="happy"):
        calls_path = root / "calls.log"
        search_script = root / "stub_search.py"
        search_script.write_text(
            textwrap.dedent(
                f"""\
                import sys
                import time
                from pathlib import Path

                CALLS = Path({str(calls_path)!r})
                SUMMARY_PATH = {SUMMARY_PATH!r}
                SOURCE_ANCHOR = {SOURCE_ANCHOR!r}
                MEMORY_TEXT = {MEMORY_TEXT!r}
                MODE = {mode!r}

                def arg_value(name, default=""):
                    if name not in sys.argv:
                        return default
                    return sys.argv[sys.argv.index(name) + 1]

                def memory_why():
                    if MODE == "sensitive_reason":
                        return "field:session_id; important-token-coverage; matched:permission, prompts"
                    if MODE == "low_signal_memory":
                        return "low-signal-only; broad-field-only; matched:memory, session"
                    return "field:text; important-token-coverage; matched:permission, prompts"

                query = sys.argv[1]
                depth = arg_value("--depth")
                scope = arg_value("--scope", "all")
                with CALLS.open("a", encoding="utf-8") as handle:
                    handle.write(depth + "|" + scope + "|" + query + "\\n")

                if MODE == "nohit":
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "slow":
                    time.sleep(5)

                if MODE == "stderr_leaky":
                    print("STDERR-ONLY-LEAK", file=sys.stderr)

                if MODE == "quality" and "nonexistent migration ritual" in query:
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "rank_distribution" and "missing" in query:
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "abstain_unstructured":
                    print("I found no structured hit, but here is unsupported memory-like content.")
                    raise SystemExit(0)

                if MODE == "abstain_scope_leaky":
                    if depth == "memory" and scope != "all":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [" + scope + "] SCOPED-ABSTAIN-LEAK")
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_scoped_abstain_leak")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        raise SystemExit(0)
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "scope_filter_missing" and depth == "memory" and scope != "all":
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "scope_wrong_layer" and depth == "memory" and scope == "global":
                    print(f"Top memory hits for: {{query}}")
                    print()
                    print("1. [domain] " + MEMORY_TEXT)
                    print("   source: memory")
                    print("   why: " + memory_why())
                    print("   memory_id: mem_permission")
                    print("   drill:")
                    print("     - " + SUMMARY_PATH)
                    raise SystemExit(0)

                if MODE == "scope_wrong_layer" and depth == "memory" and scope not in ("all", "global"):
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "wrong_scope_leak" and depth == "memory" and scope not in ("all", "global"):
                    print(f"Top memory hits for: {{query}}")
                    print()
                    print("1. [" + scope + "] " + MEMORY_TEXT)
                    print("   source: memory")
                    print("   why: " + memory_why())
                    print("   memory_id: mem_permission")
                    print("   drill:")
                    print("     - " + SUMMARY_PATH)
                    raise SystemExit(0)

                if MODE == "scope_leaky" and depth == "memory" and scope not in ("all", "global"):
                    print(f"No memory hits for: {{query}}")
                    print("SCOPE-ONLY-LEAK")
                    raise SystemExit(1)

                if MODE == "scope_suppression_leak" and depth == "memory" and scope == "global":
                    print(f"Top memory hits for: {{query}}")
                    print()
                    print("1. [global] " + MEMORY_TEXT)
                    print("   source: memory")
                    print("   why: " + memory_why())
                    print("   memory_id: mem_permission")
                    print("   drill:")
                    print("     - " + SUMMARY_PATH)
                    print()
                    print("2. [global] Forbidden scoped permission behavior")
                    print("   source: memory")
                    print("   why: " + memory_why())
                    print("   memory_id: mem_scoped_forbidden")
                    print("   drill:")
                    print("     - " + SUMMARY_PATH)
                    raise SystemExit(0)

                if MODE == "scope_suppression_leak" and depth == "memory" and scope not in ("all", "global"):
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if depth == "memory":
                    if MODE == "forbidden":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] Forbidden old permission behavior")
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_forbidden")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "distractor":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   drill:")
                        print("     - sessions/other/summary.md")
                        print()
                        print("2. [global] Different memory")
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "normalized_answer":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] answer reachability scoring was added")
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "extra_memory":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] Unrelated archived preference")
                        print("   source: memory")
                        print("   why: field:text; matched:unrelated")
                        print("   memory_id: mem_unrelated")
                        print("   drill:")
                        print("     - sessions/other/summary.md")
                    elif MODE == "prefix_collision":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] Prefix collision memory")
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission_extra")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "title_prefix_collision":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT + " Extra distractor text")
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "rank_second" or (MODE == "rank_distribution" and "rank second" in query):
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] Unrelated archived preference")
                        print("   source: memory")
                        print("   why: field:text; matched:unrelated")
                        print("   memory_id: mem_unrelated")
                        print("   drill:")
                        print("     - sessions/other/summary.md")
                        print()
                        print("2. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    else:
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                elif depth == "session":
                    print(f"Top memory hits for: {{query}}")
                    print()
                    if MODE == "leaky_path":
                        print("1. /Users/private/summary.md")
                    elif MODE == "session_path_prefix_collision":
                        print("1. " + SUMMARY_PATH + ".bak")
                    else:
                        print("1. " + SUMMARY_PATH)
                    print("   source: index")
                elif depth == "source":
                    if MODE == "distractor":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] Different memory")
                        print("   source: memory")
                        print("   why: field:text; matched:different")
                        print("   memory_id: mem_other")
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                    elif MODE == "source_wrong_memory":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] Different memory")
                        print("   source: memory")
                        print("   why: field:text; matched:different")
                        print("   memory_id: mem_other")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                    elif MODE == "source_non_memory_anchor":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. " + SUMMARY_PATH)
                        print("   source: index")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                    elif MODE == "evidence_wrong_memory":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                        print()
                        print("2. [global] Different memory")
                        print("   source: memory")
                        print("   why: field:text; matched:different")
                        print("   memory_id: mem_other")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH.replace("/summary.md", "/evidence.md"))
                    elif MODE == "answer_wrong_memory":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                        print()
                        print("2. [global] Zebra isotope lantern.")
                        print("   source: memory")
                        print("   why: field:text; matched:zebra")
                        print("   memory_id: mem_other")
                        print("   drill:")
                        print("     - sessions/other/summary.md")
                    else:
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   why: " + memory_why())
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        if MODE == "evidence_path_prefix_collision":
                            print("     - " + SUMMARY_PATH.replace("/summary.md", "/evidence.md") + ".bak")
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                        if MODE == "leaky_anchor":
                            print("     - records/private.jsonl#message:44 cookie=SHOULD_NOT_RENDER")
                        if MODE == "leaky_path":
                            print("     - /Users/private/source.jsonl#message:44")
                            print("     - ../outside/source.jsonl#message:45")
                        if MODE == "leaky":
                            print("   evidence:")
                            print("     - FAKE RAW PRIVATE CONTENT")
                else:
                    raise SystemExit(2)
                """
            ),
            encoding="utf-8",
        )
        return search_script, calls_path

    def run_benchmark(self, repo, cases, search_script, check=True, extra_args=None):
        extra_args = extra_args or []
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo",
                str(repo),
                "--cases",
                str(cases),
                "--search-script",
                str(search_script),
                *extra_args,
            ],
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def read_rows(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
