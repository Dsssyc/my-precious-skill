import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


GATE_SCRIPT = Path(
    "benchmarks/private_real_use_semantic_support_gate.py"
).resolve()


def load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "private_real_use_semantic_support_gate_under_test",
        GATE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PrivateRealUseSemanticSupportGateTests(unittest.TestCase):
    def test_documented_decision_requires_semantic_support_and_both_drill_paths(self):
        gate = load_gate_module()
        package = {
            "report_kind": "memory_recall_context_package",
            "answerability": {"status": "supported"},
            "hits": [
                {
                    "active_current": True,
                    "query_support": {
                        "status": "supported",
                        "policy": gate.SEMANTIC_POLICY,
                    },
                    "summary_drill_paths": ["sessions/synthetic/summary.md"],
                    "evidence_drill_paths": ["sessions/synthetic/evidence.md"],
                    "answerability": {"status": "supported"},
                }
            ],
        }

        decision = gate.documented_decision(package)

        self.assertEqual(decision["action"], "answer")
        self.assertTrue(decision["semantic_supported"])
        self.assertTrue(decision["summary_evidence_resolved"])

        for mutation in ("package", "query_support", "summary", "evidence"):
            candidate = json.loads(json.dumps(package))
            if mutation == "package":
                candidate["answerability"]["status"] = "unsupported"
            elif mutation == "query_support":
                candidate["hits"][0]["query_support"]["status"] = "weak"
            elif mutation == "summary":
                candidate["hits"][0]["summary_drill_paths"] = []
            else:
                candidate["hits"][0]["evidence_drill_paths"] = []
            with self.subTest(mutation=mutation):
                self.assertEqual(
                    gate.documented_decision(candidate)["action"],
                    "abstain",
                )

    def test_once_ledger_reservation_refuses_every_second_attempt(self):
        gate = load_gate_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "private-once.json"
            gate.reserve_once(ledger, "a" * 64)

            with self.assertRaises(gate.PrivateGateFailure) as raised:
                gate.reserve_once(ledger, "a" * 64)

            payload = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertEqual(str(raised.exception), "private_holdout_already_reserved")
        self.assertEqual(payload["status"], "reserved")
        self.assertEqual(payload["manifest_sha256"], "a" * 64)
        self.assertNotIn("query", payload)
        self.assertNotIn("archive_repo", payload)

    def test_manifest_validation_requires_disjoint_positive_and_negative_cases(self):
        gate = load_gate_module()
        valid = {
            "report_kind": "private_real_use_semantic_support_manifest",
            "report_version": 1,
            "archive_repo": "/private/archive",
            "cases": [
                {
                    "case_key": "positive_one",
                    "category": "goal_preference",
                    "expected_action": "answer",
                    "query": "private positive",
                },
                {
                    "case_key": "negative_one",
                    "category": "same_topic_negative",
                    "expected_action": "abstain",
                    "query": "private negative",
                },
            ],
        }

        manifest = gate.validate_manifest(valid)

        self.assertEqual(len(manifest.cases), 2)
        invalid = json.loads(json.dumps(valid))
        invalid["cases"][1]["case_key"] = "positive_one"
        with self.assertRaises(gate.PrivateGateFailure):
            gate.validate_manifest(invalid)


if __name__ == "__main__":
    unittest.main()
