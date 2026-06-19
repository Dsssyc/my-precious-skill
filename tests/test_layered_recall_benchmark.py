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

        for row in rows:
            self.assertIsInstance(row.get("query"), str)
            self.assertTrue(row["query"].strip())
            if row.get("expected_abstain") is True:
                self.assertNotIn("expected_memory_id", row)
                continue
            for key in ("expected_memory_id", "expected_summary_path", "expected_source_anchor"):
                self.assertIsInstance(row.get(key), str)
                self.assertTrue(row[key].strip())

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
            self.assertGreaterEqual(payload["latency_ms"], 0)
            self.assertGreaterEqual(payload["latency_mean_ms"], 0)
            self.assertGreaterEqual(payload["latency_max_ms"], payload["latency_mean_ms"])
            self.assertLessEqual(payload["latency_max_ms"], payload["latency_ms"])
            self.assertEqual(payload["categories"]["abstention"]["cases"], 3)
            self.assertEqual(payload["categories"]["knowledge_update"]["update_consistency"], 1.0)
            self.assertEqual(payload["categories"]["privacy_boundary"]["privacy_boundary_pass_rate"], 1.0)

    def test_packaged_synthetic_cases_pass_packaged_quality_gates(self):
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

            result = self.run_benchmark(
                repo,
                SYNTHETIC_CASES,
                SEARCH_SCRIPT,
                extra_args=["--fail-under-file", str(SYNTHETIC_QUALITY_GATES)],
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["cases"], 30)
            self.assertEqual(payload["answer_cases"], 9)
            self.assertEqual(payload["answer_reachability"], 1.0)
            self.assertEqual(payload["answer_normalized_reachability"], 1.0)
            self.assertEqual(payload["answer_token_f1"], 1.0)
            self.assertEqual(payload["stale_memory_suppression"], 1.0)

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
            self.assertEqual(payload["session_drilldown_at_5"], 1.0)
            self.assertEqual(payload["source_reachability"], 1.0)
            self.assertEqual(payload["latency_mean_ms"], payload["latency_ms"])
            self.assertEqual(payload["latency_max_ms"], payload["latency_ms"])
            self.assertEqual(payload["categories"]["uncategorized"]["latency_mean_ms"], payload["latency_ms"])
            calls = calls_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(calls, ["memory|permission prompts", "session|permission prompts", "source|permission prompts"])

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

    def test_layered_recall_benchmark_writes_structured_threshold_failures_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self.create_repo(root)
            cases = self.write_cases(root, self.valid_case())
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
            self.assertEqual(failure_payload["failure_count"], 1)
            self.assertEqual(
                failure_payload["failures"],
                [
                    {
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
            self.assertEqual(failure_payload, {"failure_count": 0, "failures": []})

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
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print()
                        print("2. [global] Different memory")
                        print("   source: memory")
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
                    else:
                        print(f"Top memory hits for: {{query}}")
                        print()
                        print("1. [global] " + MEMORY_TEXT)
                        print("   source: memory")
                        print("   drill:")
                        print("     - " + SUMMARY_PATH)
                        print("   source anchors:")
                        print("     - " + SOURCE_ANCHOR)
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
