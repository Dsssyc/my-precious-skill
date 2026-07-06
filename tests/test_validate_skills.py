import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


VALIDATOR = Path("tools/validate_skills.py").resolve()


def write_skill(root: Path, name: str, body: str | None = None) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    text = body
    if text is None:
        text = (
            "---\n"
            f"name: {name}\n"
            f"description: Validate {name} fixtures.\n"
            "---\n"
            f"\n# {name}\n"
        )
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")


def write_required_repo(root: Path) -> None:
    write_skill(root, "setup-my-precious")
    write_skill(root, "update-my-precious")
    write_skill(root, "using-my-precious")

    (root / "skills/setup-my-precious/scripts").mkdir(parents=True)
    (root / "skills/setup-my-precious/scripts/setup_memory_archive.py").write_text("", encoding="utf-8")
    (root / "skills/setup-my-precious/assets/agent-memory-repo").mkdir(parents=True)
    (root / "skills/setup-my-precious/assets/agent-memory-repo/AGENTS.md").write_text("", encoding="utf-8")
    (root / "skills/setup-my-precious/agents").mkdir(parents=True)
    (root / "skills/setup-my-precious/agents/openai.yaml").write_text("", encoding="utf-8")

    (root / "skills/update-my-precious/scripts").mkdir(parents=True)
    (root / "skills/update-my-precious/scripts/update_memory_archive.py").write_text("", encoding="utf-8")
    (root / "skills/update-my-precious/scripts/memory_consolidation.py").write_text("", encoding="utf-8")
    (root / "skills/update-my-precious/agents").mkdir(parents=True)
    (root / "skills/update-my-precious/agents/openai.yaml").write_text("", encoding="utf-8")

    (root / "skills/using-my-precious/scripts").mkdir(parents=True)
    (root / "skills/using-my-precious/scripts/search_memory.py").write_text("", encoding="utf-8")
    (root / "skills/using-my-precious/references").mkdir(parents=True)
    (root / "skills/using-my-precious/references/archive-format.md").write_text("", encoding="utf-8")
    (root / "skills/using-my-precious/agents").mkdir(parents=True)
    (root / "skills/using-my-precious/agents/openai.yaml").write_text("", encoding="utf-8")

    (root / "AGENTS.md").write_text("Run python3 tools/validate_skills.py\n", encoding="utf-8")
    (root / "README.md").write_text("Run python3 tools/validate_skills.py\n", encoding="utf-8")
    (root / "README.zh-CN.md").write_text("Run python3 tools/validate_skills.py\n", encoding="utf-8")


def run_validator(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--repo", str(root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class ValidateSkillsTests(unittest.TestCase):
    def test_accepts_valid_required_skill_folders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_required_repo(root)

            result = run_validator(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("validated 3 skill folders", result.stdout)

    def test_rejects_missing_skill_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_required_repo(root)
            (root / "skills/using-my-precious/SKILL.md").unlink()

            result = run_validator(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("skills/using-my-precious/SKILL.md is missing", result.stderr)

    def test_rejects_malformed_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_required_repo(root)
            (root / "skills/update-my-precious/SKILL.md").write_text(
                "name: update-my-precious\n"
                "description: missing delimiters\n",
                encoding="utf-8",
            )

            result = run_validator(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must start with YAML frontmatter", result.stderr)

    def test_rejects_missing_required_contract_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_required_repo(root)
            (root / "skills/update-my-precious/scripts/memory_consolidation.py").unlink()

            result = run_validator(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "skills/update-my-precious/scripts/memory_consolidation.py is missing",
                result.stderr,
            )

    def test_rejects_concrete_quick_validate_doc_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_required_repo(root)
            (root / "AGENTS.md").write_text(
                "python /path/to/skill-creator/scripts/quick_validate.py skills/setup-my-precious\n",
                encoding="utf-8",
            )

            result = run_validator(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("references a concrete quick_validate.py path", result.stderr)

    def test_rejects_name_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_required_repo(root)
            write_skill(root, "setup-my-precious", body=(
                "---\n"
                "name: wrong-name\n"
                "description: wrong skill name.\n"
                "---\n"
            ))

            result = run_validator(root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "skills/setup-my-precious/SKILL.md name must be setup-my-precious",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
