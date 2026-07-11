#!/usr/bin/env python3
"""Validate the repo-local My Precious skill package structure."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REQUIRED_SKILLS = {
    "setup-my-precious": (
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/setup_memory_archive.py",
        "assets/agent-memory-repo/AGENTS.md",
    ),
    "update-my-precious": (
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/update_memory_archive.py",
        "scripts/memory_consolidation.py",
    ),
    "using-my-precious": (
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/search_memory.py",
        "references/archive-format.md",
    ),
}

DOC_PATHS = (
    "AGENTS.md",
    "README.md",
    "README.zh-CN.md",
    "docs/design.md",
    "templates/agent-memory-repo/AGENTS.md",
    "templates/agent-memory-repo/README.md",
    "skills/setup-my-precious/assets/agent-memory-repo/AGENTS.md",
    "skills/setup-my-precious/assets/agent-memory-repo/README.md",
    "skills/setup-my-precious/SKILL.md",
    "skills/update-my-precious/SKILL.md",
    "skills/using-my-precious/SKILL.md",
    "skills/using-my-precious/references/archive-format.md",
)

BROKEN_QUICK_VALIDATE_RE = re.compile(
    r"(?:/path/to/|/Users/|\~/|[A-Za-z0-9_.-]*/skill-creator/)"
    r"[^\s`]*quick_validate\.py"
)


def relative(path: Path, repo: Path) -> str:
    return path.relative_to(repo).as_posix()


def parse_frontmatter(skill_md: Path, repo: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    rel = relative(skill_md, repo)
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()

    if not lines or lines[0].strip() != "---":
        return {}, [f"{rel} must start with YAML frontmatter delimited by ---"]

    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break

    if end is None:
        return {}, [f"{rel} must close YAML frontmatter with ---"]

    fields: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:end], start=2):
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            errors.append(f"{rel}:{line_number} has unsupported frontmatter line: {stripped}")
            continue
        key, value = stripped.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")

    for required in ("name", "description"):
        if not fields.get(required):
            errors.append(f"{rel} frontmatter must contain non-empty {required}")

    return fields, errors


def validate_required_skills(repo: Path) -> list[str]:
    errors: list[str] = []
    for skill_name, required_paths in REQUIRED_SKILLS.items():
        skill_dir = repo / "skills" / skill_name
        if not skill_dir.is_dir():
            errors.append(f"skills/{skill_name} is missing")
            continue

        for required_path in required_paths:
            path = skill_dir / required_path
            if not path.exists():
                errors.append(f"{relative(path, repo)} is missing")

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        fields, frontmatter_errors = parse_frontmatter(skill_md, repo)
        errors.extend(frontmatter_errors)
        actual_name = fields.get("name")
        if actual_name and actual_name != skill_name:
            errors.append(f"{relative(skill_md, repo)} name must be {skill_name}, got {actual_name}")

    return errors


def validate_docs(repo: Path) -> list[str]:
    errors: list[str] = []
    for rel_path in DOC_PATHS:
        path = repo / rel_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if BROKEN_QUICK_VALIDATE_RE.search(line):
                errors.append(
                    f"{rel_path}:{line_number} references a concrete quick_validate.py path; "
                    "use python3 tools/validate_skills.py for repo-local validation"
                )
    return errors


def validate_repo(repo: Path) -> list[str]:
    repo = repo.resolve()
    errors = []
    errors.extend(validate_required_skills(repo))
    errors.extend(validate_docs(repo))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository root to validate")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    errors = validate_repo(repo)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"validated {len(REQUIRED_SKILLS)} skill folders in {repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
