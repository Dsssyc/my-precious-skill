import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def valid_memory_node(**overrides):
    node = {
        "memory_id": "mem_valid_root",
        "layer": "global",
        "scope": "global",
        "topic": "agent-workflow",
        "text": "Valid root memory references should pass audit.",
        "rationale": "Audit should validate root memory node files.",
        "source": "automatic",
        "confidence": "high",
        "persistence": "normal",
        "support_count": 1,
        "first_seen": "2026-06-05T10:00:00Z",
        "last_seen": "2026-06-05T10:00:00Z",
        "derived_from": [],
        "evidence_refs": [],
        "raw_refs": [],
        "supersedes": [],
        "superseded_by": None,
        "tags": ["audit"],
    }
    node.update(overrides)
    return node


def write_memory_node_provenance(memory_repo, slug, quote_id="ev_001"):
    entry_rel = f"sessions/2026/06/05/{slug}"
    entry_dir = memory_repo / entry_rel
    entry_dir.mkdir(parents=True)
    (entry_dir / "summary.md").write_text(f"Summary for {slug} memory audit.\n", encoding="utf-8")
    (entry_dir / "evidence.md").write_text(f"{quote_id}: Evidence for {slug} memory audit.\n", encoding="utf-8")
    return {
        "derived_from": [f"{entry_rel}/summary.md"],
        "evidence_refs": [{"path": f"{entry_rel}/evidence.md", "quote_id": quote_id}],
    }


class AuditMemoryArchiveTests(unittest.TestCase):
    def test_audit_memory_archive_flags_noise_and_secrets_without_leaking_values(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            fake_key = "sk-" + ("notreal" * 4)
            entry_dir = memory_repo / "sessions/2026/05/14/noisy"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    f"session_meta: wrapper noise must not ship. Do not leak {fake_key}.\n"
                    "I confirmed the branch and commit range before checking files.\n"
                ),
                encoding="utf-8",
            )
            (entry_dir / "evidence.md").write_text(
                "Chunk ID: abc123\nWall time: 4.89 seconds\nOriginal token count: 436\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=noise", combined)
            self.assertIn("category=process_update", combined)
            self.assertIn("category=openai_key", combined)
            self.assertIn("sessions/2026/05/14/noisy/summary.md", combined)
            self.assertNotIn(fake_key, combined)

    def test_audit_memory_archive_sanitizes_slugged_finding_paths(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/cookie_should_not_render"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("session_meta: wrapper noise must not ship.\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("[unsafe-path]", combined)
            self.assertNotIn("cookie_should_not_render", combined)
            self.assertNotIn("cookie", combined.lower())

    def test_audit_memory_archive_allows_redaction_count_labels(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/redacted"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Clean summary.\n", encoding="utf-8")
            (entry_dir / "redactions.md").write_text("- cookie: 2\n- openai_key: 1\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_memory_archive_flags_embedded_process_updates(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/process"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "The dry run exited cleanly and selected three records. "
                    "I’m proceeding with the actual update now.\n"
                    "尾段正在处理多个 project_path 共享同一 source record 的情况。继续等待进程退出。\n"
                    "Using `using-superpowers` as requested, so I’ll also use `brainstorming` lightly.\n"
                    "根因已经比较明确。现在我检查 Cargo workspace 边界。\n"
                    "这里 process_update 不是旧 wrapper 污染，而是过程句进入了 reusable/problem/unresolved。\n"
                    "第二轮已经接近上一轮耗时，继续等最终输出。\n"
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=process_update", combined)
            self.assertIn("sessions/2026/05/14/process/summary.md", combined)

    def test_audit_memory_archive_allows_user_intent_with_wozhengzai(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/04/24/user-intent"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "## User Intent\n"
                    "我正在为这个仓库对应的论文写4.4节，你现在作为一个专业的水动力，计算机和GIS\n\n"
                    "## Reusable Facts\n"
                    "- `4.4` 应该是 case-specific：Gei Wai 情景如何构建，以及它带来了什么水动力响应。\n"
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_memory_archive_flags_skill_and_chinese_process_updates(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/skill-process"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "Using `using-superpowers` as requested, so I’ll also use `brainstorming` lightly.\n"
                    "根因已经比较明确。现在我检查 Cargo workspace 边界。\n"
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=process_update", combined)
            self.assertIn("sessions/2026/05/14/skill-process/summary.md", combined)

    def test_audit_memory_archive_flags_process_update_jargon_without_other_process_phrases(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/process-jargon"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "这里 process_update 不是旧 wrapper 污染，而是过程句进入了 reusable/problem/unresolved。\n"
                    "第二轮已经接近上一轮耗时，继续等最终输出。\n"
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=process_update", combined)
            self.assertIn("sessions/2026/05/14/process-jargon/summary.md", combined)

    def test_audit_memory_archive_flags_placeholder_titles_and_noisy_tags(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/weak-index"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "# Session: 这个skill总结的记忆摘要在/Users/soku/Desktop/agents/agent-memory这个目录下\n"
                    "## Decisions Made\n"
                    "- No decisions were detected automatically.\n"
                    "## Unresolved Tasks\n"
                    "- No unresolved tasks were detected automatically.\n"
                    "## Search Tags\n"
                    "my-precious-skill, secret-pattern, subagent, codespace, templates, agent-memory-repo, task, you, using-superpowers, codex_home\n"
                    "## Reusable Facts\n"
                    "- Actual update completed. **Command Status** - `update_memory_archive.py`: exit 0\n"
                    "- The implementation has meaningful improvements: unit tests pass, archive audit passes, skill validators pass, py_compile passed, template/script sync checks passed.\n"
                    "<oai-mem-citation>\n"
                    "<citation_entries>\n"
                    "MEMORY.md:30-51|note=[memory archive workflow gates and expected archive surfaces]\n"
                    "</citation_entries>\n"
                    "</oai-mem-citation>\n"
                ),
                encoding="utf-8",
            )
            (entry_dir / "evidence.md").write_text(
                "- No specific evidence snippets were selected automatically.\n",
                encoding="utf-8",
            )
            (memory_repo / "index/sessions.jsonl").write_text(
                '{"title":"# Files mentioned by the user: /Users/soku/.codex/attachments/pasted-text.txt",'
                '"summary_path":"sessions/2026/05/14/weak-index/summary.md"}\n',
                encoding="utf-8",
            )
            (memory_repo / "index/tags.jsonl").write_text(
                '{"tag":"codespace","summary_path":"sessions/2026/05/14/weak-index/summary.md"}\n'
                '{"tag":"agent-memory-repo","summary_path":"sessions/2026/05/14/weak-index/summary.md"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=placeholder", combined)
            self.assertIn("category=raw_title", combined)
            self.assertIn("category=noisy_tag", combined)
            self.assertIn("category=noise", combined)
            self.assertIn("category=process_update", combined)

    def test_audit_memory_archive_flags_archive_source_record_placeholders_and_redaction_categories(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/12/archive-source-record"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "# Session: Archive source record for my-precious-skill\n\n"
                    "## User Intent\n"
                    "Archive source record for my-precious-skill.\n\n"
                    "## Reusable Facts\n"
                    "- bearer_token, cookie, openai_key\n\n"
                    "## Final State\n"
                    "Archived source record for my-precious-skill.\n\n"
                    "## Search Tags\n"
                    "my-precious-skill, bearer_token, openai_key, latest, generic\n"
                ),
                encoding="utf-8",
            )
            (memory_repo / "index/sessions.jsonl").write_text(
                (
                    '{"title":"Archive source record for my-precious-skill",'
                    '"summary":"Archived source record for my-precious-skill.",'
                    '"user_intent":"Archive source record for my-precious-skill.",'
                    '"reusable_facts":["bearer_token, cookie, openai_key"],'
                    '"tags":["my-precious-skill","bearer_token","openai_key","latest","generic"],'
                    '"summary_path":"sessions/2026/06/12/archive-source-record/summary.md"}\n'
                ),
                encoding="utf-8",
            )
            (memory_repo / "index/tags.jsonl").write_text(
                '{"tag":"bearer_token","summary_path":"sessions/2026/06/12/archive-source-record/summary.md"}\n'
                '{"tag":"latest","summary_path":"sessions/2026/06/12/archive-source-record/summary.md"}\n',
                encoding="utf-8",
            )
            (entry_dir / "redactions.md").write_text("- openai_key: 1\n", encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=placeholder", combined)
            self.assertIn("category=redaction_category", combined)
            self.assertIn("category=noisy_tag", combined)
            self.assertNotIn("openai_key: 1", combined)

    def test_audit_memory_archive_flags_broken_memory_references(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "index").mkdir(exist_ok=True)
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_broken",
                        "layer": "global",
                        "scope": "global",
                        "topic": "agent-workflow",
                        "text": "Broken reference should be caught.",
                        "rationale": "Audit must validate drilldown paths.",
                        "source": "automatic",
                        "confidence": "medium",
                        "persistence": "normal",
                        "support_count": 1,
                        "first_seen": "2026-06-05T10:00:00Z",
                        "last_seen": "2026-06-05T10:00:00Z",
                        "derived_from": ["sessions/2026/06/05/missing/summary.md"],
                        "evidence_refs": [{"path": "sessions/2026/06/05/missing/evidence.md", "quote_id": "ev_001"}],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": None,
                        "tags": ["audit"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("category=broken_memory_ref", combined)
        self.assertIn("index/memories.jsonl", combined)

    def test_audit_memory_archive_allows_valid_memory_references_without_raw_ref_files(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/valid-memory"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for layered recall evidence.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for layered recall.\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_valid",
                        "layer": "global",
                        "scope": "global",
                        "topic": "agent-workflow",
                        "text": "Valid references should pass audit.",
                        "rationale": "Audit should allow existing archive drilldown paths.",
                        "source": "automatic",
                        "confidence": "high",
                        "persistence": "normal",
                        "support_count": 1,
                        "first_seen": "2026-06-05T10:00:00Z",
                        "last_seen": "2026-06-05T10:00:00Z",
                        "derived_from": ["sessions/2026/06/05/valid-memory/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/05/valid-memory/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [{"path": "source-records/safe-gated/source.jsonl", "anchor": "message:1"}],
                        "supersedes": [],
                        "superseded_by": None,
                        "tags": ["audit"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_memory_archive_flags_missing_internal_raw_ref_files(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/raw-ref-missing"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for missing raw ref validation.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for missing raw ref validation.\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_missing_internal_raw_ref",
                        derived_from=["sessions/2026/06/05/raw-ref-missing/summary.md"],
                        evidence_refs=[
                            {"path": "sessions/2026/06/05/raw-ref-missing/evidence.md", "quote_id": "ev_001"}
                        ],
                        raw_refs=[
                            {
                                "path": "sessions/2026/06/05/raw-ref-missing/source-map.json",
                                "anchor": "source_record",
                            }
                        ],
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=unsafe_raw_ref", combined)

    def test_audit_memory_archive_flags_internal_raw_ref_directories(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/raw-ref-directory"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for raw ref file validation.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for raw ref file validation.\n", encoding="utf-8")
            (entry_dir / "source-map.json").mkdir()
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_directory_internal_raw_ref",
                        derived_from=["sessions/2026/06/05/raw-ref-directory/summary.md"],
                        evidence_refs=[
                            {"path": "sessions/2026/06/05/raw-ref-directory/evidence.md", "quote_id": "ev_001"}
                        ],
                        raw_refs=[
                            {
                                "path": "sessions/2026/06/05/raw-ref-directory/source-map.json",
                                "anchor": "source_record",
                            }
                        ],
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=unsafe_raw_ref", combined)

    def test_audit_memory_archive_flags_missing_meta_source_map_paths(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/missing-source-map-meta"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for source map metadata validation.\n", encoding="utf-8")
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/missing-source-map-meta/summary.md",
                        "source_map_path": "sessions/2026/06/05/missing-source-map-meta/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sessions/2026/06/05/missing-source-map-meta/meta.json:1 category=broken_source_map_ref", combined)

    def test_audit_memory_archive_flags_cross_entry_meta_source_map_paths(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/cross-source-map-meta"
            other_dir = memory_repo / "sessions/2026/06/05/other-source-map"
            entry_dir.mkdir(parents=True)
            other_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for cross-entry source map validation.\n", encoding="utf-8")
            (other_dir / "source-map.json").write_text("{}\n", encoding="utf-8")
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/cross-source-map-meta/summary.md",
                        "source_map_path": "sessions/2026/06/05/other-source-map/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sessions/2026/06/05/cross-source-map-meta/meta.json:1 category=broken_source_map_ref", combined)

    def test_audit_memory_archive_allows_valid_meta_source_map_paths(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/valid-source-map-meta"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for valid source map metadata.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for valid source map metadata.\n", encoding="utf-8")
            (entry_dir / "source-map.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/valid-source-map-meta/summary.md",
                        "evidence_path": "sessions/2026/06/05/valid-source-map-meta/evidence.md",
                        "source_map_path": "sessions/2026/06/05/valid-source-map-meta/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/valid-source-map-meta/summary.md",
                        "source_map_path": "sessions/2026/06/05/valid-source-map-meta/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_memory_archive_flags_source_map_internal_path_mismatches(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/source-map-mismatch"
            other_dir = memory_repo / "sessions/2026/06/05/other-source-map-target"
            entry_dir.mkdir(parents=True)
            other_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for source map mismatch validation.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for source map mismatch.\n", encoding="utf-8")
            (other_dir / "summary.md").write_text("Other summary should not be referenced.\n", encoding="utf-8")
            (other_dir / "evidence.md").write_text("ev_001: Other evidence should not be referenced.\n", encoding="utf-8")
            (other_dir / "source-map.json").write_text("{}\n", encoding="utf-8")
            (entry_dir / "source-map.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/other-source-map-target/summary.md",
                        "evidence_path": "sessions/2026/06/05/other-source-map-target/evidence.md",
                        "source_map_path": "sessions/2026/06/05/other-source-map-target/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/source-map-mismatch/summary.md",
                        "source_map_path": "sessions/2026/06/05/source-map-mismatch/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sessions/2026/06/05/source-map-mismatch/source-map.json:1 category=broken_source_map_ref", combined)

    def test_audit_memory_archive_flags_invalid_session_meta_json(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/invalid-meta-json"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for invalid meta JSON validation.\n", encoding="utf-8")
            (entry_dir / "meta.json").write_text('{"source_map_path": ', encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sessions/2026/06/05/invalid-meta-json/meta.json:1 category=invalid_json", combined)

    def test_audit_memory_archive_flags_invalid_source_map_json(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/invalid-source-map-json"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for invalid source-map JSON validation.\n", encoding="utf-8")
            (entry_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "summary_path": "sessions/2026/06/05/invalid-source-map-json/summary.md",
                        "source_map_path": "sessions/2026/06/05/invalid-source-map-json/source-map.json",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (entry_dir / "source-map.json").write_text('{"source_record": ', encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sessions/2026/06/05/invalid-source-map-json/source-map.json:1 category=invalid_json", combined)

    def test_audit_memory_archive_flags_missing_evidence_quote_id(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/missing-quote"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for evidence quote validation.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_0010: Different evidence quote.\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_missing_quote",
                        "layer": "global",
                        "scope": "global",
                        "topic": "agent-workflow",
                        "text": "Evidence quote IDs should be reachable.",
                        "rationale": "Audit should validate evidence quote anchors, not only files.",
                        "source": "automatic",
                        "confidence": "high",
                        "persistence": "normal",
                        "support_count": 1,
                        "first_seen": "2026-06-05T10:00:00Z",
                        "last_seen": "2026-06-05T10:00:00Z",
                        "derived_from": ["sessions/2026/06/05/missing-quote/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/05/missing-quote/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": None,
                        "tags": ["audit"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=broken_memory_ref", combined)
            self.assertIn("index/memories.jsonl", combined)

    def test_audit_memory_archive_flags_missing_root_evidence_quote_id(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/root-missing-quote"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for root evidence quote validation.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_present: Existing root evidence quote.\n", encoding="utf-8")
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_root_missing_quote",
                        text="Root memory evidence quote IDs should be reachable.",
                        derived_from=["sessions/2026/06/05/root-missing-quote/summary.md"],
                        evidence_refs=[
                            {"path": "sessions/2026/06/05/root-missing-quote/evidence.md", "quote_id": "ev_missing"}
                        ],
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=broken_memory_ref", combined)

    def test_audit_memory_archive_flags_memory_nodes_without_required_provenance(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            missing_derived = valid_memory_node(
                memory_id="mem_missing_derived",
                derived_from=[],
                evidence_refs=[{"path": "sessions/2026/06/05/provenance/evidence.md", "quote_id": "ev_001"}],
            )
            summary_only_provenance = valid_memory_node(
                memory_id="mem_summary_only_provenance",
                derived_from=["sessions/2026/06/05/provenance/summary.md"],
                evidence_refs=[],
            )
            entry_dir = memory_repo / "sessions/2026/06/05/provenance"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for provenance audit.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for provenance audit.\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(missing_derived, sort_keys=True)
                + "\n"
                + json.dumps(summary_only_provenance, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=invalid_memory_node", combined)
            self.assertNotIn("index/memories.jsonl:2 category=invalid_memory_node", combined)

    def test_audit_memory_archive_scans_memory_jsonl_quality_fields_not_raw_json(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            node = valid_memory_node(
                memory_id="mem-dry-run-found-record-identifier",
                text="Layered migration keeps durable memory nodes searchable.",
                **write_memory_node_provenance(memory_repo, "raw-json-quality"),
            )
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(node, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(node, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)

    def test_audit_memory_archive_flags_invalid_memory_node_rows(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "index/memories.jsonl").write_text(
                "{invalid json}\n"
                + json.dumps(
                    {
                        "memory_id": "mem_missing",
                        "layer": "global",
                        "scope": "global",
                        "topic": "agent-workflow",
                        "text": "This row is missing required fields.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=invalid_json", combined)
            self.assertIn("category=invalid_memory_node", combined)
            self.assertIn("index/memories.jsonl", combined)

    def test_audit_memory_archive_flags_invalid_root_memory_node_rows(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/global.jsonl").write_text(
                "{invalid json}\n"
                + json.dumps({"text": "bad root-only memory row"})
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=invalid_json", combined)
            self.assertIn("memories/global.jsonl:2 category=invalid_memory_node", combined)

    def test_audit_memory_archive_flags_invalid_support_counts(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(valid_memory_node(memory_id="mem_string_support", support_count="1"))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_negative_support", support_count=-1))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_boolean_support", support_count=True))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_zero_support", support_count=0))
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=invalid_memory_node", combined)
            self.assertIn("memories/global.jsonl:2 category=invalid_memory_node", combined)
            self.assertIn("memories/global.jsonl:3 category=invalid_memory_node", combined)
            self.assertIn("memories/global.jsonl:4 category=invalid_memory_node", combined)

    def test_audit_memory_archive_flags_invalid_memory_lifecycle_timestamps(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(valid_memory_node(memory_id="mem_bad_first_seen", first_seen="not-a-date"))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_bad_last_seen", last_seen="2026-99-99T00:00:00Z"))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_inverted_seen_range",
                        first_seen="2026-06-06T00:00:00Z",
                        last_seen="2026-06-05T23:59:59Z",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=invalid_memory_node", combined)
            self.assertIn("memories/global.jsonl:2 category=invalid_memory_node", combined)
            self.assertIn("memories/global.jsonl:3 category=invalid_memory_node", combined)

    def test_audit_memory_archive_flags_schema_violating_root_memory_nodes(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            extra_field = valid_memory_node(memory_id="mem_extra_field")
            extra_field["embedding"] = [0.1, 0.2]
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(valid_memory_node(memory_id="mem_bad_layer", layer="team"))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_bad_source", source="manual"))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_bad_tags", tags=["audit", 123]))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_bad_superseded_by", superseded_by=42))
                + "\n"
                + json.dumps(valid_memory_node(memory_id=123))
                + "\n"
                + json.dumps(extra_field)
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            for line_number in range(1, 7):
                self.assertIn(f"memories/global.jsonl:{line_number} category=invalid_memory_node", combined)

    def test_audit_memory_archive_flags_unsafe_memory_identifiers_without_leaking_values(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(valid_memory_node(memory_id="mem_control\nidentifier"))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_cookie_SHOULD_NOT_RENDER"))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="../outside-memory"))
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            for line_number in range(1, 4):
                self.assertIn(f"memories/global.jsonl:{line_number} category=invalid_memory_node", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie", combined)

    def test_audit_memory_archive_flags_unsafe_supersession_identifiers_without_leaking_values(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(valid_memory_node(memory_id="mem_unsafe_supersedes", supersedes=["mem_control\nidentifier"]))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_unsafe_superseded_by",
                        superseded_by="mem_cookie_SHOULD_NOT_RENDER",
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_unsafe_supersedes_path", supersedes=["../outside-memory"]))
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            for line_number in range(1, 4):
                self.assertIn(f"memories/global.jsonl:{line_number} category=invalid_memory_node", combined)
            self.assertNotIn("SHOULD_NOT_RENDER", combined)
            self.assertNotIn("cookie", combined)

    def test_audit_memory_archive_flags_memory_root_file_layer_mismatches(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "file-layer-mismatch")
            domain_in_global = valid_memory_node(
                memory_id="mem_domain_in_global",
                layer="domain",
                scope="memory",
                **provenance,
            )
            project_in_domains = valid_memory_node(
                memory_id="mem_project_in_domains",
                layer="project",
                scope="/repo/project",
                **provenance,
            )
            automatic_in_explicit = valid_memory_node(
                memory_id="mem_auto_in_explicit",
                source="automatic",
                **provenance,
            )
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(domain_in_global, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "memories/domains.jsonl").write_text(
                json.dumps(project_in_domains, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "memories/explicit.jsonl").write_text(
                json.dumps(automatic_in_explicit, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                "".join(
                    json.dumps(node, sort_keys=True) + "\n"
                    for node in (domain_in_global, project_in_domains, automatic_in_explicit)
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=memory_file_mismatch", combined)
            self.assertIn("memories/domains.jsonl:1 category=memory_file_mismatch", combined)
            self.assertIn("memories/explicit.jsonl:1 category=memory_file_mismatch", combined)
            self.assertNotIn("category=memory_index_mismatch", combined)

    def test_audit_memory_archive_flags_explicit_nodes_outside_explicit_root(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            misplaced_explicit = valid_memory_node(
                memory_id="mem_explicit_in_global",
                layer="global",
                scope="global",
                source="explicit",
                persistence="sticky",
                **write_memory_node_provenance(memory_repo, "explicit-outside-root"),
            )
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(misplaced_explicit, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(misplaced_explicit, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=memory_file_mismatch", combined)
            self.assertNotIn("category=memory_index_mismatch", combined)

    def test_audit_memory_archive_flags_broken_root_memory_references(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/domains.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_broken_root",
                        text="Broken root memory references should be caught.",
                        derived_from=["sessions/2026/06/05/missing/summary.md"],
                        evidence_refs=[{"path": "sessions/2026/06/05/missing/evidence.md", "quote_id": "ev_001"}],
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/domains.jsonl:1 category=broken_memory_ref", combined)
            self.assertNotIn("index/memories.jsonl", combined)

    def test_audit_memory_archive_does_not_read_root_memory_symlink_outside_repo(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            outside = root / "outside-memory-row.jsonl"
            outside.write_text('{"text":"outside row must not be audited"}\n', encoding="utf-8")
            link = memory_repo / "memories/link.jsonl"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, combined)
            self.assertNotIn("memories/link.jsonl", combined)
            self.assertNotIn("category=invalid_memory_node", combined)

    def test_audit_memory_archive_allows_root_memory_rows_without_raw_ref_files(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/root-valid-memory"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for valid root memory evidence.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for valid root memory.\n", encoding="utf-8")
            (memory_repo / "memories/explicit.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_valid_root_raw_ref",
                        source="explicit",
                        derived_from=["sessions/2026/06/05/root-valid-memory/summary.md"],
                        evidence_refs=[
                            {"path": "sessions/2026/06/05/root-valid-memory/evidence.md", "quote_id": "ev_001"}
                        ],
                        raw_refs=[{"path": "source-records/safe-gated/source.jsonl", "anchor": "message:1"}],
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                (memory_repo / "memories/explicit.jsonl").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_memory_archive_flags_durable_memories_missing_search_index(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/index-missing"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for missing index evidence.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for missing index.\n", encoding="utf-8")
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_missing_index",
                        derived_from=["sessions/2026/06/05/index-missing/summary.md"],
                        evidence_refs=[{"path": "sessions/2026/06/05/index-missing/evidence.md", "quote_id": "ev_001"}],
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=memory_index_mismatch", combined)

    def test_audit_memory_archive_flags_memory_index_mismatches(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/index-mismatch"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for index mismatch evidence.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for index mismatch.\n", encoding="utf-8")
            durable_node = valid_memory_node(
                memory_id="mem_index_mismatch",
                derived_from=["sessions/2026/06/05/index-mismatch/summary.md"],
                evidence_refs=[{"path": "sessions/2026/06/05/index-mismatch/evidence.md", "quote_id": "ev_001"}],
            )
            stale_index_node = dict(durable_node)
            stale_index_node["text"] = "Stale index text should be caught by audit."
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(durable_node, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(stale_index_node, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:1 category=memory_index_mismatch", combined)

    def test_audit_memory_archive_flags_duplicate_memory_ids_within_logical_store(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/duplicate-id"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for duplicate memory ID evidence.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for duplicate memory ID.\n", encoding="utf-8")
            memory_node = valid_memory_node(
                memory_id="mem_duplicate_id",
                derived_from=["sessions/2026/06/05/duplicate-id/summary.md"],
                evidence_refs=[{"path": "sessions/2026/06/05/duplicate-id/evidence.md", "quote_id": "ev_001"}],
            )
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(memory_node, sort_keys=True)
                + "\n"
                + json.dumps(memory_node, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(memory_node, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:2 category=duplicate_memory_id", combined)
            self.assertNotIn("index/memories.jsonl:1 category=duplicate_memory_id", combined)

    def test_audit_memory_archive_flags_broken_supersession_references(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "broken-supersession")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(valid_memory_node(memory_id="mem_current", supersedes=["mem_missing_old"], **provenance))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_old", superseded_by="mem_missing_new", **provenance))
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_self", supersedes=["mem_self"], **provenance))
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=broken_supersession_ref", combined)
            self.assertIn("index/memories.jsonl:2 category=broken_supersession_ref", combined)
            self.assertIn("index/memories.jsonl:3 category=broken_supersession_ref", combined)

    def test_audit_memory_archive_flags_non_reciprocal_supersession_references(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "non-reciprocal-supersession")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_current_missing_backref",
                        supersedes=["mem_old_missing_backref"],
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_old_missing_backref", **provenance))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_old_missing_forwardref",
                        superseded_by="mem_current_missing_forwardref",
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_current_missing_forwardref", **provenance))
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=broken_supersession_ref", combined)
            self.assertIn("index/memories.jsonl:3 category=broken_supersession_ref", combined)
            self.assertNotIn("index/memories.jsonl:2 category=broken_supersession_ref", combined)
            self.assertNotIn("index/memories.jsonl:4 category=broken_supersession_ref", combined)

    def test_audit_memory_archive_flags_broken_contradiction_references(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "broken-contradiction")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_current_missing_backref",
                        contradicts=["mem_old_missing_backref"],
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_old_missing_backref", **provenance))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_old_missing_forwardref",
                        contradicted_by=["mem_current_missing_forwardref"],
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_current_missing_forwardref", **provenance))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_self_contradiction",
                        contradicts=["mem_self_contradiction"],
                        **provenance,
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=broken_contradiction_ref", combined)
            self.assertIn("index/memories.jsonl:3 category=broken_contradiction_ref", combined)
            self.assertIn("index/memories.jsonl:5 category=broken_contradiction_ref", combined)
            self.assertNotIn("index/memories.jsonl:2 category=broken_contradiction_ref", combined)
            self.assertNotIn("index/memories.jsonl:4 category=broken_contradiction_ref", combined)

    def test_audit_memory_archive_flags_broken_deprecation_references_and_illegal_states(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "broken-deprecation")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_marker_missing_backref",
                        deprecates=["mem_old_missing_backref"],
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_old_missing_backref", **provenance))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_old_missing_forwardref",
                        deprecated_by="mem_marker_missing_forwardref",
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(valid_memory_node(memory_id="mem_marker_missing_forwardref", **provenance))
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_self_deprecation",
                        deprecates=["mem_self_deprecation"],
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_illegal_dual_retired",
                        superseded_by="mem_replacement",
                        deprecated_by="mem_deprecation_marker",
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_illegal_marker_replaced",
                        supersedes=["mem_old_target"],
                        deprecates=["mem_old_target"],
                        **provenance,
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=broken_deprecation_ref", combined)
            self.assertIn("index/memories.jsonl:3 category=broken_deprecation_ref", combined)
            self.assertIn("index/memories.jsonl:5 category=broken_deprecation_ref", combined)
            self.assertIn("index/memories.jsonl:6 category=invalid_memory_lifecycle_state", combined)
            self.assertIn("index/memories.jsonl:7 category=invalid_memory_lifecycle_state", combined)
            self.assertNotIn("index/memories.jsonl:2 category=broken_deprecation_ref", combined)
            self.assertNotIn("index/memories.jsonl:4 category=broken_deprecation_ref", combined)

    def test_audit_memory_archive_flags_supersession_refs_masked_by_other_copies(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "masked-supersession")
            current = valid_memory_node(memory_id="mem_current_masked", **provenance)
            old = valid_memory_node(
                memory_id="mem_old_masked",
                superseded_by="mem_current_masked",
                **provenance,
            )
            indexed_current = valid_memory_node(
                memory_id="mem_current_masked",
                supersedes=["mem_old_masked"],
                **provenance,
            )
            (memory_repo / "memories/global.jsonl").write_text(
                json.dumps(current) + "\n" + json.dumps(old) + "\n",
                encoding="utf-8",
            )
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(indexed_current) + "\n" + json.dumps(old) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/global.jsonl:2 category=broken_supersession_ref", combined)

    def test_audit_memory_archive_flags_cyclic_supersession_references(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            provenance = write_memory_node_provenance(memory_repo, "cyclic-supersession")
            (memory_repo / "index/memories.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_cycle_a",
                        supersedes=["mem_cycle_b"],
                        superseded_by="mem_cycle_b",
                        **provenance,
                    )
                )
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_cycle_b",
                        supersedes=["mem_cycle_a"],
                        superseded_by="mem_cycle_a",
                        **provenance,
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("index/memories.jsonl:1 category=broken_supersession_ref", combined)
            self.assertIn("index/memories.jsonl:2 category=broken_supersession_ref", combined)

    def test_audit_memory_archive_flags_unsafe_root_memory_raw_refs(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/explicit.jsonl").write_text(
                json.dumps(
                    valid_memory_node(
                        memory_id="mem_legacy_raw_ref",
                        raw_refs=["records/private.jsonl#message:42"],
                    )
                )
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_control_raw_ref",
                        raw_refs=[{"path": "/external/safe-gated/source.jsonl", "anchor": "message:1\nleak"}],
                    )
                )
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_absolute_raw_ref",
                        raw_refs=[{"path": "/external/safe-gated/source.jsonl", "anchor": "message:1"}],
                    )
                )
                + "\n"
                + json.dumps(
                    valid_memory_node(
                        memory_id="mem_escaping_raw_ref",
                        raw_refs=[{"path": "../outside/source.jsonl", "anchor": "message:2"}],
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("memories/explicit.jsonl:1 category=unsafe_raw_ref", combined)
            self.assertIn("memories/explicit.jsonl:2 category=unsafe_raw_ref", combined)
            self.assertIn("memories/explicit.jsonl:3 category=unsafe_raw_ref", combined)
            self.assertIn("memories/explicit.jsonl:4 category=unsafe_raw_ref", combined)

    def test_audit_memory_archive_scans_memory_root_files(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            (memory_repo / "memories/global.jsonl").write_text(
                '{"text":"session_meta should be audited in memory root files."}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=noise", combined)
            self.assertIn("memories/global.jsonl", combined)

    def test_audit_memory_archive_applies_quality_patterns_to_memory_text_fields(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/05/quality-memory"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text("Summary for quality filtering memory.\n", encoding="utf-8")
            (entry_dir / "evidence.md").write_text("ev_001: Evidence for quality filtering memory.\n", encoding="utf-8")
            (memory_repo / "index/memories.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "memory_id": "mem_quality_process",
                                "layer": "global",
                                "scope": "global",
                                "topic": "agent-workflow",
                                "text": "I confirmed the branch and commit range before checking files.",
                                "rationale": "Audit should apply quality filtering to memory nodes.",
                                "source": "automatic",
                                "confidence": "medium",
                                "persistence": "normal",
                                "support_count": 1,
                                "first_seen": "2026-06-05T10:00:00Z",
                                "last_seen": "2026-06-05T10:00:00Z",
                                "derived_from": ["sessions/2026/06/05/quality-memory/summary.md"],
                                "evidence_refs": [
                                    {"path": "sessions/2026/06/05/quality-memory/evidence.md", "quote_id": "ev_001"}
                                ],
                                "raw_refs": [],
                                "supersedes": [],
                                "superseded_by": None,
                                "tags": ["audit"],
                            }
                        ),
                        json.dumps(
                            {
                                "memory_id": "mem_quality_low_signal",
                                "layer": "global",
                                "scope": "global",
                                "topic": "agent-workflow",
                                "text": "DONE",
                                "rationale": "Audit should apply quality filtering to memory nodes.",
                                "source": "automatic",
                                "confidence": "medium",
                                "persistence": "normal",
                                "support_count": 1,
                                "first_seen": "2026-06-05T10:00:00Z",
                                "last_seen": "2026-06-05T10:00:00Z",
                                "derived_from": ["sessions/2026/06/05/quality-memory/summary.md"],
                                "evidence_refs": [
                                    {"path": "sessions/2026/06/05/quality-memory/evidence.md", "quote_id": "ev_001"}
                                ],
                                "raw_refs": [],
                                "supersedes": [],
                                "superseded_by": None,
                                "tags": ["audit"],
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=low_signal", combined)
            self.assertIn("category=process_update", combined)
            self.assertIn("index/memories.jsonl", combined)

    def test_audit_memory_archive_flags_low_signal_fragments_and_run_status(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/low-signal"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "## Reusable Facts\n"
                    "- 验证结果：\n"
                    "- 但阻塞点很明确：\n"
                    "- 但这次 subagent 的 $update-my-precious 没有产生新写入：dry run 选中 1 条记录，"
                    "live update 被默认 secret gate 拒绝，原因是 source record 命中 cookie=33。\n"
                    "- 这个skill总结的记忆摘要在\n"
                    "- 结论：**只能算部分符合；按你的记忆索引目标，不能算最终验收通过。\n"
                    "## Search Tags\n"
                    "dry, live, update, secret, gate, cookie, meta, user, intent, facts\n"
                ),
                encoding="utf-8",
            )
            (memory_repo / "index/tags.jsonl").write_text(
                '{"tag":"dry","summary_path":"sessions/2026/05/14/low-signal/summary.md"}\n'
                '{"tag":"secret","summary_path":"sessions/2026/05/14/low-signal/summary.md"}\n'
                '{"tag":"facts","summary_path":"sessions/2026/05/14/low-signal/summary.md"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=low_signal", combined)
            self.assertIn("category=process_update", combined)
            self.assertIn("category=noisy_tag", combined)
            self.assertIn("sessions/2026/05/14/low-signal/summary.md", combined)

    def test_audit_memory_archive_flags_objective_wrappers_and_search_verification_status(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/06/12/wrapper-status"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "## User Intent\n"
                    "The objective below is user-provided data.\n\n"
                    "<objective>\n"
                    "## My request for Codex:\n\n"
                    "## Reusable Facts\n"
                    "- 验证已跑：unit tests pass, archive audit passed.\n"
                    "- `libx265 libheif _gdal osgeo` 第一命中是 Gridmen/GDAL 根因 summary。\n"
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=noise", combined)
            self.assertIn("category=low_signal", combined)
            self.assertIn("sessions/2026/06/12/wrapper-status/summary.md", combined)

    def test_audit_memory_archive_flags_incomplete_fragments_and_broken_markdown(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/incomplete"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                (
                    "## User Intent\n"
                    "这个skill总结的记忆摘要在\n\n"
                    "## Reusable Facts\n"
                    "- **阻塞原因**\n"
                    "- Future messages should adhere to the following personality:\n"
                    "- 结论：**只能算部分符合；按你的记忆索引目标，不能算最终验收通过。\n"
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            combined = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("category=low_signal", combined)
            self.assertIn("sessions/2026/05/14/incomplete/summary.md", combined)

    def test_audit_memory_archive_does_not_cross_match_jsonl_metadata_fields(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/durable-dry-run"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                "Decision: use `npx rule-porter --from copilot --to agents-md --dry-run` to preview migration.\n",
                encoding="utf-8",
            )
            (memory_repo / "index/sessions.jsonl").write_text(
                (
                    '{"title":"Rule porter dry-run migration preview",'
                    '"summary":"Decision: use `npx rule-porter --from copilot --to agents-md --dry-run` to preview migration.",'
                    '"reusable_facts":["Decision: use `npx rule-porter --from copilot --to agents-md --dry-run` to preview migration."],'
                    '"source_record":"/Users/soku/.codex/sessions/rollout.jsonl",'
                    '"summary_path":"sessions/2026/05/14/durable-dry-run/summary.md"}\n'
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_memory_archive_does_not_flag_chinese_now_user_requests(self):
        setup_script = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            subprocess.run(
                [sys.executable, str(setup_script), "--path", str(memory_repo), "--mode", "local", "--skip-config"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            entry_dir = memory_repo / "sessions/2026/05/14/chinese-request"
            entry_dir.mkdir(parents=True)
            (entry_dir / "summary.md").write_text(
                "现在我希望当前程序同样能去除白色背景。\n现在有个问题就是主界面返回后点位会偏移。\n下一步要验证持久化坐标是否被覆盖。\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(memory_repo / "tools/audit_memory_archive.py"), "--memory-repo", str(memory_repo)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
