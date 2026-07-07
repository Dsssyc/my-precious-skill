import re
import unittest
from pathlib import Path


EVALUATION_DOC = Path("docs/evaluations/layered-memory-readiness.md")
DESIGN_DOC = Path("docs/design.md")
UPDATE_SKILL = Path("skills/update-my-precious/SKILL.md")
USING_SKILL = Path("skills/using-my-precious/SKILL.md")
SETUP_SKILL = Path("skills/setup-my-precious/SKILL.md")
TEMPLATE_AGENTS = Path("templates/agent-memory-repo/AGENTS.md")


class DocumentationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluation = EVALUATION_DOC.read_text(encoding="utf-8")
        cls.design = DESIGN_DOC.read_text(encoding="utf-8")
        cls.combined = cls.evaluation + "\n" + cls.design
        cls.skill_contracts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (UPDATE_SKILL, USING_SKILL, SETUP_SKILL, TEMPLATE_AGENTS)
        )

    def assert_contains(self, haystack: str, needle: str):
        if needle not in haystack:
            self.fail(f"missing documentation contract phrase: {needle!r}")

    def evaluation_section(self, heading: str) -> str:
        self.assert_contains(self.evaluation, heading)
        start = self.evaluation.index(heading)
        next_heading = self.evaluation.find("\n## ", start + len(heading))
        return self.evaluation[start:] if next_heading == -1 else self.evaluation[start:next_heading]

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

    def test_private_shadow_refresh_section_is_aggregate_only_and_decisive(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "memory_recall_at_5",
            "memory_precision_at_5",
            "top_k_noise_at_5",
            "expected_record_missing",
            "privacy_boundary_pass_rate",
            "lifecycle_integrity.score",
            "ranking/noise reduction",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_private_shadow_refresh_section_records_cross_scope_safety_fixture(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "Same-Topic Cross-Scope Safety Fixture",
            "same-topic/cross-scope support",
            "same-topic/cross-scope noise",
            "not sufficient to justify a production ranking change",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_private_shadow_refresh_section_records_runtime_signal_audit(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "Same-Topic Cross-Scope Runtime-Signal Audit",
            "runtime_signal_diagnostics_at_5",
            "support_count=1",
            "medium confidence",
            "not yet sufficient for a ranking patch",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_private_shadow_refresh_section_records_v12_conservative_ranking_gate(self):
        section = self.evaluation_section("## V1.1 Private Shadow Coverage Refresh")
        for phrase in (
            "V1.2 Conservative Same-Topic Cross-Scope Ranking Gate",
            "weak same-topic/cross-scope tail",
            "`memory_recall_at_5` stayed 1.0",
            "`top_k_noise_at_5` dropped to 0.0",
            "accepted as a narrow ranking/noise reduction patch",
            "aggregate-only",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v13_self_maintenance_lifecycle_gate(self):
        section = self.evaluation_section("## V1.3 Self-Maintenance Lifecycle Gate")
        for phrase in (
            "not a new retrieval capability",
            "public synthetic self-maintenance fixture",
            "`thread_source=automation`",
            "`search_memory.py --health-check`",
            "generic `search_memory.py memory`",
            "`sync_memory_archive.py`",
            "aggregate-only private dogfood",
            "automation_source_records=2",
            "automation_session_entries=0",
            "automation_memory_nodes=0",
            "automation_daily_noise_hits=0",
            "automation_index_noise_hits=0",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_evaluation_doc_records_v14_explicit_capture_contract(self):
        section = self.evaluation_section("## V1.4 Explicit Memory Capture Contract")
        for phrase in (
            "explicit memory capture contract",
            "not a new ranking capability",
            "not generated-answer quality",
            "not long-horizon ontology or governance",
            "`capture_explicit_memory.py`",
            "agent-neutral JSONL input",
            "short fact",
            "raw transcript fields are refused",
            "explicit_capture",
            "adapter_input_records=1",
            "captured_memory_nodes=1",
            "rejected_raw_transcript_records=1",
            "search_hit_count=1",
            "privacy_leak_count=0",
        ):
            self.assert_contains(section, phrase)
        self.assertIsNone(re.search(r"/Users/[^\s)`]+", section))

    def test_skill_docs_record_explicit_capture_adapter_contract(self):
        for phrase in (
            "capture_explicit_memory.py",
            "agent-neutral JSONL",
            "automatic induction is the default",
            "explicit capture path",
            "Do not paste raw chat transcripts",
            "short fact",
        ):
            self.assert_contains(self.skill_contracts, phrase)


if __name__ == "__main__":
    unittest.main()
