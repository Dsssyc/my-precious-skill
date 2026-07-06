import re
import unittest
from pathlib import Path


EVALUATION_DOC = Path("docs/evaluations/layered-memory-readiness.md")
DESIGN_DOC = Path("docs/design.md")


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluation = EVALUATION_DOC.read_text(encoding="utf-8")
        cls.design = DESIGN_DOC.read_text(encoding="utf-8")
        cls.combined = cls.evaluation + "\n" + cls.design

    def assert_contains(self, haystack: str, needle: str):
        self.assertIn(needle, haystack, msg=f"missing documentation contract phrase: {needle!r}")

    def test_evaluation_doc_lists_packaged_lifecycle_as_core_readiness_dimension(self):
        self.assert_contains(self.evaluation, "clean-room packaged lifecycle setup/update/search/audit")
        self.assert_contains(self.evaluation, "packaged_lifecycle")

    def test_evaluation_doc_no_longer_claims_four_required_packaged_dimensions(self):
        forbidden_patterns = (
            r"requires\s+four\s+packaged\s+synthetic\s+dimensions",
            r"four\s+required\s+packaged\s+dimensions",
            r"四个\s*packaged",
            r"四个\s*核心维度",
        )
        for pattern in forbidden_patterns:
            self.assertIsNone(
                re.search(pattern, self.evaluation, flags=re.IGNORECASE),
                msg=f"stale readiness wording still present: {pattern!r}",
            )

    def test_docs_distinguish_memory_readiness_gate_from_release_gate(self):
        self.assert_contains(self.combined, "benchmarks/v1_readiness_gate.py")
        self.assert_contains(self.combined, "tools/run_quality_gates.py")
        self.assert_contains(self.combined, "repo-local release gate")

    def test_docs_record_current_required_scorecards(self):
        self.assert_contains(self.evaluation, "required 5/5")
        self.assert_contains(self.evaluation, "required 6/6")

    def test_evaluation_doc_preserves_bounded_claim_language(self):
        for phrase in (
            "private archive",
            "public leaderboard parity",
            "live model answer quality",
            "automatic ontology discovery",
            "long-horizon governance",
        ):
            self.assert_contains(self.evaluation, phrase)


if __name__ == "__main__":
    unittest.main()
