import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from benchmarks import real_use_semantic_support_gate as semantic_gate


GATE_SCRIPT = Path("benchmarks/real_use_semantic_support_gate.py").resolve()
CASE_FILE = Path(
    "benchmarks/cases/real_use_semantic_support_synthetic.jsonl"
).resolve()
CASE_FILE_SHA256 = (
    "7893a6646c36982be2213f43bac75c8c045e72612d5f4177deb27b26e56172d0"
)


def load_cases():
    return [
        json.loads(line)
        for line in CASE_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class RealUseSemanticSupportGateTests(unittest.TestCase):
    def test_no_go_candidate_is_historical_and_absent_from_release_runtime(self):
        runtime = semantic_gate.historical_candidate_runtime()
        current = Path(
            "templates/agent-memory-repo/tools/search_memory.py"
        ).read_bytes()

        self.assertEqual(
            hashlib.sha256(runtime.search_script).hexdigest(),
            semantic_gate.CANDIDATE_SEARCH_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(runtime.provider_script).hexdigest(),
            semantic_gate.CANDIDATE_PROVIDER_SHA256,
        )
        self.assertIn(
            semantic_gate.SEMANTIC_POLICY.encode("utf-8"),
            runtime.search_script,
        )
        self.assertNotIn(
            semantic_gate.SEMANTIC_POLICY.encode("utf-8"),
            current,
        )
        self.assertNotIn(
            semantic_gate.SEMANTIC_MODEL_FINGERPRINT.encode("utf-8"),
            current,
        )

    def test_case_literal_audit_checks_the_historical_candidate_runtime(self):
        case = semantic_gate.load_cases()[0]
        runtime = semantic_gate.CandidateRuntime(
            search_script=b"# generic candidate\n",
            provider_script=f"# {case.case_id}\n".encode("utf-8"),
        )

        self.assertEqual(
            semantic_gate.case_specific_runtime_literal_count([case], runtime),
            1,
        )

    def test_frozen_cohorts_are_disjoint_public_and_cover_required_shapes(self):
        cases = load_cases()
        calibration = [case for case in cases if case["cohort"] == "calibration"]
        holdout = [case for case in cases if case["cohort"] == "holdout"]

        self.assertEqual(
            hashlib.sha256(CASE_FILE.read_bytes()).hexdigest(),
            CASE_FILE_SHA256,
        )
        self.assertEqual(
            {case["case_id"] for case in calibration}
            & {case["case_id"] for case in holdout},
            set(),
        )
        self.assertEqual(
            Counter(case["expected_action"] for case in calibration),
            {"answer": 9, "abstain": 9},
        )
        self.assertEqual(
            Counter(case["expected_action"] for case in holdout),
            {"answer": 9, "abstain": 13},
        )
        support_gap_cases = [
            case
            for case in cases
            if case.get("expected_first_loss")
            == "retrieved_but_query_support_weak"
        ]
        self.assertEqual(len(support_gap_cases), 12)
        self.assertEqual(
            {case["language"] for case in support_gap_cases},
            {"en", "zh", "mixed"},
        )
        self.assertGreaterEqual(
            sum(case["shape"] == "goal_delivery_paraphrase" for case in support_gap_cases),
            6,
        )
        self.assertGreaterEqual(
            sum(case["shape"] == "non_goal_preference_paraphrase" for case in support_gap_cases),
            4,
        )
        required_negative_shapes = {
            "same_subject_wrong_attribute",
            "temporary",
            "hypothetical",
            "quoted",
            "wrong_scope",
            "inactive_only",
            "missing_source_binding",
            "bare_subject",
            "multi_facet",
            "current_turn_override",
            "negation",
            "unrelated_copyable_content",
            "malformed_provider",
        }
        self.assertTrue(
            required_negative_shapes.issubset(
                {
                    case["shape"]
                    for case in holdout
                    if case["expected_action"] == "abstain"
                }
            )
        )
        rendered = CASE_FILE.read_text(encoding="utf-8")
        self.assertNotRegex(rendered, r"/Users/")
        self.assertNotRegex(
            rendered,
            re.compile(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                r"[0-9a-f]{4}-[0-9a-f]{12}",
                re.IGNORECASE,
            ),
        )
        self.assertNotRegex(rendered, r"\bmem_[A-Za-z0-9_.:-]+")

    def test_baseline_gate_reproduces_the_frozen_first_loss_taxonomy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--cohort",
                    "calibration",
                    "--baseline-only",
                    "--work-dir",
                    tmpdir,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["report_kind"], "real_use_semantic_support_gate")
        self.assertEqual(report["status"], "baseline_reproduced")
        self.assertEqual(report["cohort_fingerprint"], CASE_FILE_SHA256)
        self.assertEqual(
            report["metrics"]["baseline_support_gap_reproduction_rate"],
            1.0,
        )
        self.assertEqual(
            report["baseline_first_loss_counts"],
            {
                "memory_not_materialized": 1,
                "not_retrieved_at_5": 1,
                "retrieved_but_query_support_weak": 6,
                "supported": 1,
            },
        )
        self.assertEqual(report["metrics"]["free_form_answerability_use_count"], 0)
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)
        self.assertTrue(report["privacy"]["aggregate_only"])

    def test_holdout_baseline_reproduces_the_same_frozen_first_loss_taxonomy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--cohort",
                    "holdout",
                    "--baseline-only",
                    "--work-dir",
                    tmpdir,
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "baseline_reproduced")
        self.assertEqual(report["case_counts"]["negative"], 13)
        self.assertEqual(
            report["baseline_first_loss_counts"],
            {
                "memory_not_materialized": 1,
                "not_retrieved_at_5": 1,
                "retrieved_but_query_support_weak": 6,
                "supported": 1,
            },
        )
        self.assertEqual(
            report["metrics"]["baseline_support_gap_reproduction_rate"],
            1.0,
        )
        self.assertEqual(report["metrics"]["privacy_leak_count"], 0)


if __name__ == "__main__":
    unittest.main()
