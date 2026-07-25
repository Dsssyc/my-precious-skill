import re
import unittest
from pathlib import Path


USING_SKILL = Path("skills/using-my-precious/SKILL.md")
OPENAI_AGENT = Path("skills/using-my-precious/agents/openai.yaml")
README_EN = Path("README.md")
README_ZH = Path("README.zh-CN.md")
TEMPLATE_README = Path("templates/agent-memory-repo/README.md")
TEMPLATE_AGENTS = Path("templates/agent-memory-repo/AGENTS.md")


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    match = re.search(r"\n## ", text[start + len(heading) :])
    return text[start:] if match is None else text[start : start + len(heading) + match.start()]


def documented_action(package: dict) -> str:
    if package.get("report_kind") != "memory_recall_context_package":
        return "malformed or missing package -> abstain"
    answerability = package.get("answerability")
    if not isinstance(answerability, dict):
        return "malformed or missing package -> abstain"
    if answerability.get("reason") == "no_active_current_support":
        return "inactive/superseded-only package -> abstain"
    if answerability.get("status") != "supported":
        return "unsupported package -> abstain"
    hits = package.get("hits")
    if not isinstance(hits, list):
        return "malformed or missing package -> abstain"
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        hit_answerability = hit.get("answerability")
        if (
            hit.get("active_current") is True
            and isinstance(hit_answerability, dict)
            and hit_answerability.get("status") == "supported"
            and isinstance(hit.get("query_support"), dict)
            and hit["query_support"].get("status") == "supported"
            and hit.get("summary_drill_paths")
            and hit.get("evidence_drill_paths")
        ):
            return "supported package -> answer"
    return "unsupported package -> abstain"


class UsingMyPreciousRuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = USING_SKILL.read_text(encoding="utf-8")
        cls.search_workflow = section(cls.skill, "## Search Workflow")
        cls.agent_prompt = OPENAI_AGENT.read_text(encoding="utf-8")
        cls.readme_en = README_EN.read_text(encoding="utf-8")
        cls.readme_zh = README_ZH.read_text(encoding="utf-8")
        cls.template_readme = TEMPLATE_README.read_text(encoding="utf-8")
        cls.template_agents = TEMPLATE_AGENTS.read_text(encoding="utf-8")

    def assert_contains(self, haystack: str, needle: str):
        if needle not in haystack:
            self.fail(f"missing runtime contract phrase: {needle!r}")

    def test_using_skill_makes_context_package_the_default_answerability_step(self):
        first_command = re.search(r"```\s*bash\s*\n(?P<command>.*?)\n\s*```", self.search_workflow, flags=re.DOTALL)
        self.assertIsNotNone(first_command)
        command = first_command.group("command")
        self.assertIn("--context-json", command)
        self.assertIn("--depth evidence", command)
        self.assert_contains(
            self.search_workflow,
            "Do not use free-form search output as the answerability source.",
        )
        self.assert_contains(
            self.search_workflow,
            "Use free-form search output only for exploration or drilldown after the package decision.",
        )

    def test_using_skill_decision_recipe_covers_supported_abstain_inactive_and_malformed(self):
        for phrase in (
            "supported package -> answer",
            "unsupported package -> abstain",
            "inactive/superseded-only package -> abstain",
            "malformed or missing package -> abstain",
            "fail closed to abstain",
            "active/current memory hits",
            "summary_drill_paths",
            "evidence_drill_paths",
            "answerability.status",
        ):
            self.assert_contains(self.search_workflow, phrase)

    def test_synthetic_context_packages_map_to_documented_agent_actions(self):
        cases = [
            (
                {
                    "report_kind": "memory_recall_context_package",
                    "answerability": {"status": "supported", "reason": "active_current_memory_support"},
                    "hits": [
                        {
                            "active_current": True,
                            "answerability": {"status": "supported"},
                            "query_support": {"status": "supported"},
                            "summary_drill_paths": ["sessions/synthetic/summary.md"],
                            "evidence_drill_paths": ["sessions/synthetic/evidence.md"],
                        }
                    ],
                },
                "supported package -> answer",
            ),
            (
                {
                    "report_kind": "memory_recall_context_package",
                    "answerability": {"status": "unsupported", "reason": "no_recall_hits"},
                    "hits": [],
                },
                "unsupported package -> abstain",
            ),
            (
                {
                    "report_kind": "memory_recall_context_package",
                    "answerability": {"status": "unsupported", "reason": "no_active_current_support"},
                    "hits": [],
                },
                "inactive/superseded-only package -> abstain",
            ),
            ({"report_kind": "unexpected_report"}, "malformed or missing package -> abstain"),
            (
                {
                    "report_kind": "memory_recall_context_package",
                    "answerability": {"status": "supported", "reason": "active_current_memory_support"},
                    "hits": [
                        {
                            "active_current": True,
                            "answerability": {"status": "supported"},
                            "query_support": {"status": "weak"},
                            "summary_drill_paths": ["sessions/synthetic/summary.md"],
                            "evidence_drill_paths": ["sessions/synthetic/evidence.md"],
                        }
                    ],
                },
                "unsupported package -> abstain",
            ),
        ]
        for package, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(documented_action(package), expected)
                self.assert_contains(self.search_workflow, expected)

    def test_runtime_surfaces_default_to_context_package_before_free_form_search(self):
        surfaces = {
            "agent_prompt": self.agent_prompt,
            "readme_en": self.readme_en,
            "readme_zh": self.readme_zh,
            "template_readme": self.template_readme,
            "template_agents": self.template_agents,
        }
        for name, text in surfaces.items():
            with self.subTest(surface=name):
                self.assert_contains(text, "memory_recall_context_package")
                self.assert_contains(text, "--context-json")
                self.assert_contains(text, "--depth evidence")
                self.assert_contains(text, "answerability.status")

    def test_runtime_contract_preserves_privacy_boundary(self):
        for phrase in (
            "private query",
            "memory text",
            "raw refs",
            "source paths",
            "credentials",
            "scheduler state",
            "local private paths",
        ):
            self.assert_contains(self.search_workflow, phrase)

    def test_runtime_contract_applies_copyable_goal_preference_after_package_decision(self):
        for phrase in (
            "copyable goal artifact",
            "single `text` code fence",
            "no explanatory preamble or epilogue outside the fence",
            "outer fence longer than every backtick run inside the goal",
            "current-turn format instructions take precedence",
            "archive abstention does not erase a current-turn instruction",
        ):
            self.assert_contains(self.search_workflow, phrase)


if __name__ == "__main__":
    unittest.main()
