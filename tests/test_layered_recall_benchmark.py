import hashlib
import json
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

        self.assertGreaterEqual(len(rows), 30)
        self.assertLessEqual(len(rows), 50)
        categories = {row.get("category") for row in rows}
        self.assertTrue(
            {
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
            self.assertEqual(payload["cases"], 30)
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
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["evidence_reachability"], 1.0)
            self.assertEqual(payload["answer_cases"], 9)
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
            self.assertEqual(payload["categories"]["abstention"]["cases"], 3)
            self.assertEqual(payload["categories"]["abstention"]["failed_case_count"], 0)
            self.assertEqual(payload["categories"]["abstention"]["case_pass_rate"], 1.0)
            self.assertEqual(payload["categories"]["knowledge_update"]["update_consistency"], 1.0)
            self.assertEqual(payload["categories"]["privacy_boundary"]["privacy_boundary_pass_rate"], 1.0)

    def test_packaged_synthetic_cases_pass_packaged_quality_gates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            details = Path(tmpdir) / "details.jsonl"
            lower_gates = json.loads(SYNTHETIC_QUALITY_GATES.read_text(encoding="utf-8"))
            self.assertEqual(lower_gates["case_pass_rate"], 1.0)
            self.assertEqual(lower_gates["memory_precision_at_5"], 0.25)
            self.assertEqual(lower_gates["memory_micro_precision_at_5"], 0.24)
            self.assertEqual(lower_gates["categories.abstention.case_pass_rate"], 1.0)
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
            self.assertEqual(payload["cases"], 30)
            self.assertEqual(payload["answer_cases"], 9)
            self.assertGreaterEqual(payload["memory_precision_at_5"], lower_gates["memory_precision_at_5"])
            self.assertEqual(payload["answer_reachability"], 1.0)
            self.assertEqual(payload["answer_normalized_reachability"], 1.0)
            self.assertEqual(payload["answer_token_f1"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)
            self.assertEqual(payload["failed_case_count"], 0)
            self.assertEqual(payload["case_pass_rate"], 1.0)
            self.assertEqual(len(detail_rows), 30)
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
            self.assertEqual(payload["cases"], 30)
            self.assertEqual(payload["memory_recall_at_1"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)
            self.assertEqual(payload["update_consistency"], 1.0)

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
            self.assertEqual(calls, ["memory|permission prompts", "session|permission prompts", "source|permission prompts"])

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
                    "answer_reachability",
                    "answer_normalized_reachability",
                    "answer_token_f1",
                    "update_consistency",
                ],
            )

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
                        "source_benchmark": "LongMemEval",
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

                query = sys.argv[1]
                depth = arg_value("--depth")
                with CALLS.open("a", encoding="utf-8") as handle:
                    handle.write(depth + "|" + query + "\\n")

                if MODE == "nohit":
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if MODE == "slow":
                    time.sleep(5)

                if MODE == "quality" and "nonexistent migration ritual" in query:
                    print(f"No memory hits for: {{query}}")
                    raise SystemExit(1)

                if depth == "memory":
                    if MODE == "forbidden":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] Forbidden old permission behavior")
                        print("   source: memory")
                        print("   memory_id: mem_forbidden")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "distractor":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   drill:")
                        print("     - sessions/other/summary.md")
                        print()
                        print("2. [global] Different memory")
                        print("   source: memory")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "normalized_answer":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] answer reachability scoring was added")
                        print("   source: memory")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                    elif MODE == "extra_memory":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] Unrelated archived preference")
                        print("   source: memory")
                        print("   memory_id: mem_unrelated")
                        print("   drill:")
                        print("     - sessions/other/summary.md")
                    else:
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                elif depth == "session":
                    print(f"Top memory hits for: {{query}}")
                    print()
                    print("1. " + SUMMARY_PATH)
                    print("   source: index")
                elif depth == "source":
                    if MODE == "distractor":
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] Different memory")
                        print("   source: memory")
                        print("   memory_id: mem_other")
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                    else:
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   memory_id: mem_permission")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                        if MODE == "leaky_anchor":
                            print("     - records/private.jsonl#message:44 cookie=SHOULD_NOT_RENDER")
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
