import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SearchMemoryTests(unittest.TestCase):
    def test_search_memory_finds_index_and_summary_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/05/14/example").mkdir(parents=True)

            summary_path = repo / "sessions/2026/05/14/example/summary.md"
            summary_path.write_text(
                "# Session: Agent Memory Archive\n\n"
                "## User intent\n"
                "Design a private agent session memory archive.\n",
                encoding="utf-8",
            )

            (repo / "index/sessions.jsonl").write_text(
                '{"date":"2026-05-14","source_agent":"agent",'
                '"project":"agent-memory","title":"Design private agent memory",'
                '"tags":["agent","memory","archive"],'
                '"summary_path":"sessions/2026/05/14/example/summary.md",'
                '"evidence_path":"sessions/2026/05/14/example/evidence.md",'
                '"unresolved_count":0}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "private memory archive", "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("Top memory hits for: private memory archive", result.stdout)
        self.assertIn("sessions/2026/05/14/example/summary.md", result.stdout)
        self.assertIn("index:sessions.jsonl", result.stdout)

    def test_search_memory_ignores_internal_review_and_trace_indexes(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "index/memory_review_candidates.jsonl").write_text(
                '{"reason":"diagnostic-only-token","current_memory_id":"mem_current"}\n',
                encoding="utf-8",
            )
            (repo / "index/memory_consolidation_trace.jsonl").write_text(
                '{"decision":"skip","reason":"diagnostic-only-token"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "diagnostic-only-token", "--repo", str(repo)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("No memory hits for: diagnostic-only-token", result.stdout)
        self.assertNotIn("memory_review_candidates.jsonl", result.stdout)
        self.assertNotIn("memory_consolidation_trace.jsonl", result.stdout)

    def test_search_memory_filters_tag_only_low_signal_memory_noise(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/05/14/example").mkdir(parents=True)
            (repo / "sessions/2026/05/14/example/summary.md").write_text(
                "# Session: Search Signal\n\n"
                "Durable ranking marker appears in high-signal memory text.\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "memory_id": "mem_signal_target",
                    "layer": "global",
                    "scope": "global",
                    "topic": "search-signal",
                    "text": "Durable ranking marker belongs to the target memory.",
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 1,
                    "derived_from": ["sessions/2026/05/14/example/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                    "supersedes": [],
                    "superseded_by": None,
                    "tags": ["search-signal"],
                },
                {
                    "memory_id": "mem_tag_only_noise",
                    "layer": "global",
                    "scope": "global",
                    "topic": "unrelated",
                    "text": "Unrelated note without the query phrase.",
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 1,
                    "derived_from": ["sessions/2026/05/14/example/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                    "supersedes": [],
                    "superseded_by": None,
                    "tags": ["durable", "ranking", "marker"],
                },
            ]
            (repo / "index/memories.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "durable ranking marker",
                    "--repo",
                    str(repo),
                    "--limit",
                    "5",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("mem_signal_target", result.stdout)
        self.assertNotIn("mem_tag_only_noise", result.stdout)

    def test_search_memory_sanitizes_archive_path_display(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "cookie=SHOULD_NOT_RENDER"
            (repo / "index").mkdir(parents=True)
            (repo / "sessions/2026/05/14/example").mkdir(parents=True)

            (repo / "sessions/2026/05/14/example/summary.md").write_text(
                "# Session: Path Display\n\n"
                "Archive display privacy remains searchable.\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                '{"date":"2026-05-14","source_agent":"agent",'
                '"project":"agent-memory","title":"Archive display privacy",'
                '"summary_path":"sessions/2026/05/14/example/summary.md"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "archive display privacy", "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("Archive: [unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)
        self.assertNotIn(str(repo.parent), result.stdout)

    def test_search_memory_accepts_depth_session_for_summary_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/05/14/example").mkdir(parents=True)

            (repo / "sessions/2026/05/14/example/summary.md").write_text(
                "# Session: Layered Search\n\n"
                "Normal session summary remains searchable with depth session.\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                '{"date":"2026-05-14","source_agent":"agent",'
                '"project":"agent-memory","title":"Layered search compatibility",'
                '"summary":"Normal session summary remains searchable.",'
                '"summary_path":"sessions/2026/05/14/example/summary.md"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "normal session summary",
                    "--repo",
                    str(repo),
                    "--depth",
                    "session",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("sessions/2026/05/14/example/summary.md", result.stdout)

    def test_search_memory_depth_session_limits_legacy_hits_to_memory_drill_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            good_dir = repo / "sessions/2026/05/14/good"
            noisy_dir = repo / "sessions/2026/05/14/noisy"
            good_dir.mkdir(parents=True)
            noisy_dir.mkdir(parents=True)
            (good_dir / "summary.md").write_text(
                "# Session: Layered Drill\n\n"
                "The durable memory says layered drill token belongs here.\n",
                encoding="utf-8",
            )
            (noisy_dir / "summary.md").write_text(
                "# Session: Noisy Legacy\n\n"
                "layered drill token " * 20,
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_layered_drill",
                        "layer": "global",
                        "scope": "global",
                        "topic": "layered-drill",
                        "text": "Layered drill token should drill to the good session only.",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/05/14/good/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-05-14",
                        "project": "agent-memory",
                        "summary": "layered drill token belongs to good",
                        "summary_path": "sessions/2026/05/14/good/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-05-14",
                        "project": "agent-memory",
                        "summary": "layered drill token " * 20,
                        "summary_path": "sessions/2026/05/14/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "layered drill token",
                    "--repo",
                    str(repo),
                    "--depth",
                    "session",
                    "--limit",
                    "5",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("sessions/2026/05/14/good/summary.md", result.stdout)
        self.assertNotIn("sessions/2026/05/14/noisy/summary.md", result.stdout)

    def test_search_memory_include_evidence_limits_legacy_hits_to_memory_drill_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            good_dir = repo / "sessions/2026/05/14/good"
            noisy_dir = repo / "sessions/2026/05/14/noisy"
            good_dir.mkdir(parents=True)
            noisy_dir.mkdir(parents=True)
            (good_dir / "summary.md").write_text(
                "# Session: Evidence Drill\n\n"
                "The durable memory says evidence drill token belongs here.\n",
                encoding="utf-8",
            )
            (good_dir / "evidence.md").write_text(
                "# Evidence\n\n"
                "Evidence drill token supporting snippet.\n",
                encoding="utf-8",
            )
            (noisy_dir / "evidence.md").write_text(
                "# Evidence\n\n"
                "evidence drill token " * 20,
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_evidence_drill",
                        "layer": "global",
                        "scope": "global",
                        "topic": "evidence-drill",
                        "text": "Evidence drill token should drill only to declared support.",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/05/14/good/summary.md"],
                        "evidence_refs": ["sessions/2026/05/14/good/evidence.md"],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "evidence drill token",
                    "--repo",
                    str(repo),
                    "--include-evidence",
                    "--limit",
                    "5",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("sessions/2026/05/14/good/evidence.md", result.stdout)
        self.assertNotIn("sessions/2026/05/14/noisy/evidence.md", result.stdout)

    def test_search_memory_rejects_non_positive_limit(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/05/14/limit"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Limit Validation\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_limit_validation",
                        "layer": "global",
                        "scope": "global",
                        "topic": "limit-validation",
                        "text": "Limit validation token should have a visible search result.",
                        "source": "synthetic",
                        "derived_from": ["sessions/2026/05/14/limit/summary.md"],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "limit validation token",
                    "--repo",
                    str(repo),
                    "--limit",
                    "0",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--limit must be greater than 0", result.stderr)

    def test_search_memory_depth_evidence_searches_evidence_markdown(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/05/14/example"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Evidence Depth\n", encoding="utf-8")
            (session_dir / "evidence.md").write_text(
                "# Evidence\n\n"
                "Supporting snippet mentions layered-evidence-depth-token.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "layered-evidence-depth-token",
                    "--repo",
                    str(repo),
                    "--depth",
                    "evidence",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("sessions/2026/05/14/example/evidence.md", result.stdout)

    def test_search_memory_prefers_memory_nodes_by_default(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/permission"
            session_dir.mkdir(parents=True)
            summary_path = session_dir / "summary.md"
            evidence_path = session_dir / "evidence.md"
            summary_path.write_text(
                "# Session: Permission Prompt Preference\n\n"
                "The user said 授权后不要反复请求权限.\n",
                encoding="utf-8",
            )
            evidence_path.write_text(
                "# Evidence\n\n"
                "Supporting snippet for 授权后不要反复请求权限.\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_permission_prompt",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "授权后不要反复请求权限。",
                        "rationale": "Explicit memory requested by the user.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/permission/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-17",
                        "project": "agent-memory",
                        "summary": "授权后不要反复请求权限 should be respected by future agents.",
                        "summary_path": "sessions/2026/06/17/permission/summary.md",
                        "evidence_path": "sessions/2026/06/17/permission/evidence.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "授权后不要反复请求权限", "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("[global]", first_hit)
        self.assertIn("source: memory", first_hit)
        self.assertIn("memory_id: mem_global_permission_prompt", first_hit)
        self.assertIn("source:explicit", first_hit)
        self.assertIn("drill:", first_hit)
        self.assertIn("sessions/2026/06/17/permission/summary.md", first_hit)
        self.assertNotIn("sessions/2026/06/17/permission/evidence.md", first_hit)

    def test_search_memory_ranks_durable_memory_above_repeated_process_noise(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/21/layered"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Layered recall\n\n"
                "Layered memory recall should use durable high-level memory first.\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "memory_id": "mem_layered_recall_policy",
                    "layer": "global",
                    "scope": "global",
                    "topic": "layered-memory-recall",
                    "text": "Layered memory recall should return durable high-level memory nodes before process notes.",
                    "rationale": "Durable design preference extracted from user direction.",
                    "source": "explicit",
                    "confidence": "high",
                    "support_count": 3,
                    "derived_from": ["sessions/2026/06/21/layered/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                    "tags": ["durable-policy"],
                },
                {
                    "memory_id": "mem_layered_process_noise",
                    "layer": "project",
                    "scope": "project:agent-memory",
                    "topic": "implementation-progress",
                    "text": (
                        "Continue current goal. layered memory recall layered memory recall "
                        "layered memory recall layered memory recall while implementing Task 3."
                    ),
                    "task": (
                        "You are implementing the layered memory recall plan. "
                        "The task status repeats layered memory recall for progress tracking."
                    ),
                    "source": "automatic",
                    "confidence": "low",
                    "support_count": 1,
                    "derived_from": ["sessions/2026/06/21/layered/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                    "tags": ["progress"],
                },
            ]
            (repo / "index/memories.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "layered memory recall",
                    "--repo",
                    str(repo),
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("memory_id: mem_layered_recall_policy", first_hit)
        self.assertNotIn("memory_id: mem_layered_process_noise", first_hit)

    def test_search_memory_demotes_scope_mixed_broad_lexical_noise(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/21/scope"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Scope ranking\n\n"
                "Global permission prompts policy should not be hidden by project task noise.\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "memory_id": "mem_global_permission_policy",
                    "layer": "global",
                    "scope": "global",
                    "topic": "permission-prompts",
                    "text": "Permission prompts policy: after access is granted, avoid repeated approval requests.",
                    "rationale": "Global user preference.",
                    "source": "explicit",
                    "confidence": "high",
                    "support_count": 2,
                    "derived_from": ["sessions/2026/06/21/scope/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                },
                {
                    "memory_id": "mem_project_permission_progress",
                    "layer": "project",
                    "scope": "project:unrelated",
                    "topic": "implementation-progress",
                    "text": (
                        "permission prompts policy permission prompts policy "
                        "permission prompts policy appeared in a project-local progress note."
                    ),
                    "task": "Continue the permission prompts policy implementation task.",
                    "source": "automatic",
                    "confidence": "low",
                    "support_count": 1,
                    "derived_from": ["sessions/2026/06/21/scope/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                },
            ]
            (repo / "index/memories.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "permission prompts policy",
                    "--repo",
                    str(repo),
                    "--limit",
                    "1",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("memory_id: mem_global_permission_policy", result.stdout)
        self.assertNotIn("memory_id: mem_project_permission_progress", result.stdout)

    def test_search_memory_preferred_scope_ranks_requested_layer_first(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/21/preferred-scope"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Preferred scope\n\n"
                "Scope preference marker should rank the requested layer before wrong-layer neighbors.\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "memory_id": "mem_domain_scope_target",
                    "layer": "domain",
                    "scope": "domain:agent-workflow",
                    "topic": "scope-preference",
                    "text": "scope preference marker durable domain answer",
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 2,
                    "derived_from": ["sessions/2026/06/21/preferred-scope/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                },
                {
                    "memory_id": "mem_project_scope_neighbor",
                    "layer": "project",
                    "scope": "project:unrelated",
                    "topic": "scope-preference",
                    "text": (
                        "scope preference marker scope preference marker "
                        "scope preference marker wrong-layer project neighbor"
                    ),
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 2,
                    "derived_from": ["sessions/2026/06/21/preferred-scope/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                },
            ]
            (repo / "index/memories.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "scope preference marker",
                    "--repo",
                    str(repo),
                    "--preferred-scope",
                    "domain",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("memory_id: mem_domain_scope_target", first_hit)
        self.assertIn("scope-preference:domain", first_hit)

    def test_search_memory_preferred_scope_keeps_cross_layer_shared_memory_reachable(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/21/shared-scope"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Shared scope\n\n"
                "Shared layer marker remains reachable even when another layer is preferred.\n",
                encoding="utf-8",
            )
            row = {
                "memory_id": "mem_global_shared_scope",
                "layer": "global",
                "scope": "global",
                "topic": "scope-preference",
                "text": "shared layer marker durable global memory",
                "source": "explicit",
                "confidence": "high",
                "support_count": 2,
                "derived_from": ["sessions/2026/06/21/shared-scope/summary.md"],
                "evidence_refs": [],
                "raw_refs": [],
            }
            (repo / "index/memories.jsonl").write_text(
                json.dumps(row, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "shared layer marker",
                    "--repo",
                    str(repo),
                    "--preferred-scope",
                    "domain",
                    "--limit",
                    "1",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("memory_id: mem_global_shared_scope", result.stdout)
        self.assertIn("scope-preference-demoted:domain", result.stdout)

    def test_search_memory_prunes_loose_specific_token_matches_when_strict_hits_exist(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/21/specific"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Specific token coverage\n\n"
                "A complete c2-runtime memory should beat broad agent-workflow neighbors.\n",
                encoding="utf-8",
            )
            rows = [
                {
                    "memory_id": "mem_c2_runtime_target",
                    "layer": "domain",
                    "scope": "domain:agent-workflow",
                    "topic": "agent-workflow",
                    "text": "agent-workflow c-two c2-runtime has the durable runtime routing rule.",
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 2,
                    "derived_from": ["sessions/2026/06/21/specific/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                    "tags": ["agent-workflow", "c-two", "c2-runtime"],
                },
                {
                    "memory_id": "mem_agent_workflow_neighbor",
                    "layer": "domain",
                    "scope": "domain:agent-workflow",
                    "topic": "agent-workflow",
                    "text": "agent-workflow and c-two nearby implementation detail.",
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 2,
                    "derived_from": ["sessions/2026/06/21/specific/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                    "tags": ["agent-workflow", "c-two"],
                },
            ]
            (repo / "index/memories.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "agent-workflow c-two c2-runtime",
                    "--repo",
                    str(repo),
                    "--limit",
                    "5",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("memory_id: mem_c2_runtime_target", result.stdout)
        self.assertIn("strict-token-coverage", result.stdout)
        self.assertNotIn("memory_id: mem_agent_workflow_neighbor", result.stdout)

    def test_search_memory_skips_superseded_memory_nodes(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_v1",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy old superseded policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "superseded_by": "mem_permission_current",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_permission_current",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy latest active policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": ["mem_permission_v1"],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "permission prompts current policy",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("latest active policy", result.stdout)
        self.assertNotIn("old superseded policy", result.stdout)

    def test_search_memory_skips_memory_nodes_listed_in_current_supersedes(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_v1",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy stale forward-only policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_permission_current",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy latest active policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": ["mem_permission_v1"],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "permission prompts current policy",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("latest active policy", result.stdout)
        self.assertNotIn("stale forward-only policy", result.stdout)

    def test_search_memory_skips_confirmed_contradicted_memory_nodes(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            old_entry = repo / "sessions/2026/06/17/layered-old"
            current_entry = repo / "sessions/2026/06/18/layered-current"
            old_entry.mkdir(parents=True)
            current_entry.mkdir(parents=True)
            (old_entry / "evidence.md").write_text(
                "ev_001: Old evidence for the preserve evidence refs policy.\n",
                encoding="utf-8",
            )
            (current_entry / "evidence.md").write_text(
                "ev_001: Current evidence for the must not preserve evidence refs policy.\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_layered_v1",
                        "layer": "domain",
                        "scope": "domain:memory-retrieval",
                        "topic": "memory-retrieval",
                        "text": "layered retrieval must preserve evidence refs old contradicted policy",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/layered-old/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/layered-old/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                        "contradicted_by": ["mem_layered_current"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_layered_current",
                        "layer": "domain",
                        "scope": "domain:memory-retrieval",
                        "topic": "memory-retrieval",
                        "text": "layered retrieval must not preserve evidence refs current active policy",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 2,
                        "derived_from": [
                            "sessions/2026/06/17/layered-old/summary.md",
                            "sessions/2026/06/18/layered-current/summary.md",
                        ],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/layered-old/evidence.md", "quote_id": "ev_001"},
                            {"path": "sessions/2026/06/18/layered-current/evidence.md", "quote_id": "ev_001"},
                        ],
                        "raw_refs": [],
                        "contradicts": ["mem_layered_v1"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "layered retrieval preserve evidence refs policy",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("memory_id: mem_layered_current", result.stdout)
        self.assertNotIn("memory_id: mem_layered_v1", result.stdout)
        self.assertIn("sessions/2026/06/17/layered-old/evidence.md#ev_001", result.stdout)
        self.assertIn("sessions/2026/06/18/layered-current/evidence.md#ev_001", result.stdout)

    def test_search_memory_skips_confirmed_deprecated_memory_nodes_and_markers(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            deprecated_entry = repo / "sessions/2026/06/17/deprecated"
            active_entry = repo / "sessions/2026/06/18/active"
            deprecated_entry.mkdir(parents=True)
            active_entry.mkdir(parents=True)
            (deprecated_entry / "evidence.md").write_text(
                "ev_001: Raw transcript uploads disabled by default old policy.\n",
                encoding="utf-8",
            )
            (active_entry / "evidence.md").write_text(
                "ev_001: Active drilldown policy keeps raw transcript uploads gated.\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_raw_uploads_old",
                        "layer": "domain",
                        "scope": "domain:memory-retrieval",
                        "topic": "memory-retrieval",
                        "text": "raw transcript uploads disabled by default old deprecated policy",
                        "source": "automatic",
                        "confidence": "low",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/deprecated/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/deprecated/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                        "deprecated_by": "mem_raw_uploads_deprecation",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_raw_uploads_deprecation",
                        "layer": "domain",
                        "scope": "domain:memory-retrieval",
                        "topic": "memory-retrieval",
                        "text": "deprecated fact raw transcript uploads disabled by default tombstone marker",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 2,
                        "derived_from": [
                            "sessions/2026/06/17/deprecated/summary.md",
                            "sessions/2026/06/18/active/summary.md",
                        ],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/deprecated/evidence.md", "quote_id": "ev_001"},
                            {"path": "sessions/2026/06/18/active/evidence.md", "quote_id": "ev_001"},
                        ],
                        "raw_refs": [],
                        "deprecates": ["mem_raw_uploads_old"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_raw_uploads_active",
                        "layer": "domain",
                        "scope": "domain:memory-retrieval",
                        "topic": "memory-retrieval",
                        "text": "raw transcript uploads require gated source drilldown active policy",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/18/active/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/18/active/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "raw transcript uploads policy",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("memory_id: mem_raw_uploads_active", result.stdout)
        self.assertNotIn("memory_id: mem_raw_uploads_old", result.stdout)
        self.assertNotIn("memory_id: mem_raw_uploads_deprecation", result.stdout)

    def test_search_memory_ignores_unsafe_supersession_claims(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_safe",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy safe durable policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_current cookie=SHOULD_NOT_RENDER",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy unsafe supersession claim",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": ["mem_permission_safe"],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "safe durable policy",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("safe durable policy", result.stdout)
        self.assertIn("memory_id: mem_permission_safe", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_ignores_unsafe_superseded_by_metadata(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_safe",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy safe retained policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": "mem_current cookie=SHOULD_NOT_RENDER",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "safe retained policy",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("safe retained policy", result.stdout)
        self.assertIn("memory_id: mem_permission_safe", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_ignores_orphaned_superseded_by_metadata(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_safe",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy safe orphaned policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": "mem_missing_current",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "safe orphaned policy",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("safe orphaned policy", result.stdout)
        self.assertIn("memory_id: mem_permission_safe", result.stdout)

    def test_search_memory_ignores_unconfirmed_superseded_by_metadata(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_safe",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy safe unconfirmed policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": "mem_permission_candidate",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_permission_candidate",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts candidate record lacks reciprocal link",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "supersedes": [],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "safe unconfirmed policy",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("safe unconfirmed policy", result.stdout)
        self.assertIn("memory_id: mem_permission_safe", result.stdout)

    def test_search_memory_skips_invalid_memory_lifecycle_nodes(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/permission").mkdir(parents=True)
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_permission_bad_lifecycle",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy obsolete invalid lifecycle",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 3,
                        "first_seen": "2026-06-18T00:00:00Z",
                        "last_seen": "2026-06-17T00:00:00Z",
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "memory_id": "mem_permission_current",
                        "layer": "global",
                        "scope": "global",
                        "topic": "permission-prompts",
                        "text": "permission prompts current policy latest active policy",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 1,
                        "first_seen": "2026-06-17T00:00:00Z",
                        "last_seen": "2026-06-18T00:00:00Z",
                        "derived_from": ["sessions/2026/06/17/permission/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                        "superseded_by": None,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "permission prompts current policy",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("latest active policy", result.stdout)
        self.assertNotIn("obsolete invalid lifecycle", result.stdout)

    def test_search_memory_depth_source_reports_source_status_without_raw_content(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/source"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Source Anchors\n", encoding="utf-8")
            raw_path = repo / "records/private.jsonl"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text(
                "message:42: FAKE RAW PRIVATE CONTENT THAT MUST NOT BE PRINTED\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_source_anchor",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-depth",
                        "text": "Source depth can report anchors without copying raw content.",
                        "rationale": "Source-depth recall needs provenance without raw transcript exposure.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/source/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [{"path": str(raw_path), "anchor": "message:42"}],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "source-depth anchors",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("source_ref_id: src_", result.stdout)
        self.assertIn("status: available", result.stdout)
        self.assertIn("reason: archive_source_anchor_reachable", result.stdout)
        self.assertNotIn("records/private.jsonl#message:42", result.stdout)
        self.assertNotIn("FAKE RAW PRIVATE CONTENT", result.stdout)

    def test_search_memory_raw_source_preview_requires_explicit_opt_in_and_redacts(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/source-preview"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Source Preview\n", encoding="utf-8")
            raw_path = repo / "records/private.jsonl"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text(
                "message:42: Safe preview phrase for gated source drilldown cookie=SHOULD_NOT_RENDER\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_source_preview",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-preview",
                        "text": "Raw source preview should require explicit opt in and redaction.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/source-preview/summary.md"],
                        "raw_refs": [{"path": str(raw_path), "anchor": "message:42"}],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            default_result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "source preview redaction",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            preview_result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "source preview redaction",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                    "--raw-source-preview",
                    "all",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotIn("raw_preview:", default_result.stdout)
        self.assertIn("raw_preview:", preview_result.stdout)
        self.assertIn("Safe preview phrase for gated source drilldown", preview_result.stdout)
        self.assertIn("[REDACTED_COOKIE]", preview_result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", preview_result.stdout)
        self.assertNotIn("cookie=", preview_result.stdout)

    def test_search_memory_depth_source_reports_reachable_source_map_without_path_leak(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/source-map"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Source Map\n", encoding="utf-8")
            (session_dir / "evidence.md").write_text("ev_001: Evidence for source map.\n", encoding="utf-8")
            source_map_path = session_dir / "source-map.json"
            source_map_path.write_text(
                json.dumps(
                    {
                        "source_record": "/private/raw-transcript.jsonl",
                        "summary_path": "sessions/2026/06/17/source-map/summary.md",
                        "evidence_path": "sessions/2026/06/17/source-map/evidence.md",
                        "source_map_path": "sessions/2026/06/17/source-map/source-map.json",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_source_map",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-map",
                        "text": "Source maps can prove source reachability without exposing raw paths.",
                        "source": "automatic",
                        "derived_from": ["sessions/2026/06/17/source-map/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/source-map/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [
                            {
                                "path": "sessions/2026/06/17/source-map/source-map.json",
                                "anchor": "explicit_memory",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "source map reachability",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("status: available", result.stdout)
        self.assertIn("reason: source_map_reachable", result.stdout)
        self.assertNotIn("source-map.json#explicit_memory", result.stdout)
        self.assertNotIn("/private/raw-transcript.jsonl", result.stdout)

    def test_search_memory_depth_source_parses_string_source_refs_with_anchors(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/string-source"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: String Source Anchors\n", encoding="utf-8")
            raw_path = repo / "records/private.jsonl"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text(
                "message:42: FAKE RAW PRIVATE CONTENT THAT MUST NOT BE PRINTED\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_string_source_anchor",
                        "layer": "global",
                        "scope": "global",
                        "topic": "string-source-depth",
                        "text": "String source refs should preserve source-depth anchors.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/string-source/summary.md"],
                        "raw_refs": ["records/private.jsonl#message:42"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "string source-depth anchors",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("source_ref_id: src_", result.stdout)
        self.assertIn("status: available", result.stdout)
        self.assertNotIn("records/private.jsonl#message:42", result.stdout)
        self.assertNotIn("FAKE RAW PRIVATE CONTENT", result.stdout)

    def test_search_memory_depth_source_sanitizes_unsafe_source_refs(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/unsafe-source"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Unsafe Source Ref\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_unsafe_source_ref",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-depth",
                        "text": "Unsafe source-depth refs should not be printed verbatim.",
                        "rationale": "Source refs are untrusted display data.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/unsafe-source/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [
                            {"path": "../outside/private.jsonl", "anchor": "message:42\n   injected: yes"},
                            {"path": "/Users/private/source.jsonl", "anchor": "message:43"},
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "unsafe source-depth refs",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("status: blocked", result.stdout)
        self.assertIn("reason: unsafe_source_ref", result.stdout)
        self.assertIn("[unsafe-source-ref]", result.stdout)
        self.assertNotIn("../outside", result.stdout)
        self.assertNotIn("/Users/private", result.stdout)
        self.assertNotIn("injected: yes", result.stdout)

    def test_search_memory_depth_source_sanitizes_missing_internal_source_refs(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/missing-internal-source"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Missing Internal Source Ref\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_missing_internal_source_ref",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-depth",
                        "text": "Broken internal source anchors should be sanitized before display.",
                        "rationale": "Source-depth output should not present unreachable archive anchors as usable.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/missing-internal-source/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [
                            {
                                "path": "sessions/2026/06/17/missing-internal-source/source-map.json",
                                "anchor": "source_record",
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "broken internal source anchors",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("status: blocked", result.stdout)
        self.assertIn("reason: unsafe_source_ref", result.stdout)
        self.assertIn("[unsafe-source-ref]", result.stdout)
        self.assertNotIn("source-map.json", result.stdout)

    def test_search_memory_depth_source_sanitizes_sensitive_source_ref_anchors(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-source-anchor"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Source Anchor\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_sensitive_source_anchor",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-depth",
                        "text": "Sensitive source-depth anchor text should not be printed verbatim.",
                        "rationale": "Source anchors are untrusted display data.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/sensitive-source-anchor/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [
                            {"path": "records/private.jsonl", "anchor": "message:44 cookie=SHOULD_NOT_RENDER"}
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "sensitive source-depth anchor",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("status: blocked", result.stdout)
        self.assertIn("reason: unsafe_source_ref", result.stdout)
        self.assertIn("[unsafe-source-ref]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_depth_source_sanitizes_sensitive_source_ref_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-source-path"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Source Path\n", encoding="utf-8")
            raw_path = repo / "records/cookie=SHOULD_NOT_RENDER/source.jsonl"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text("FAKE RAW PRIVATE CONTENT THAT MUST NOT BE PRINTED\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_sensitive_source_path",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-depth",
                        "text": "Sensitive source-depth path text should not be printed verbatim.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/sensitive-source-path/summary.md"],
                        "raw_refs": [{"path": str(raw_path), "anchor": "message:45"}],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "sensitive source-depth path",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("status: blocked", result.stdout)
        self.assertIn("reason: unsafe_source_ref", result.stdout)
        self.assertIn("[unsafe-source-ref]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_depth_source_blocks_symlinked_raw_source_refs(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            repo.mkdir()
            outside = root / "outside-private.jsonl"
            outside.write_text("message:46: OUTSIDE RAW CONTENT MUST NOT RENDER\n", encoding="utf-8")
            (repo / "index").mkdir()
            (repo / "records").mkdir()
            symlink_path = repo / "records/outside-link.jsonl"
            symlink_path.symlink_to(outside)
            session_dir = repo / "sessions/2026/06/17/symlink-source"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Symlink Source\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_symlink_source",
                        "layer": "global",
                        "scope": "global",
                        "topic": "source-depth",
                        "text": "Symlinked source-depth refs should be refused before raw preview.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/symlink-source/summary.md"],
                        "raw_refs": [{"path": "records/outside-link.jsonl", "anchor": "message:46"}],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "symlinked source-depth refs",
                    "--repo",
                    str(repo),
                    "--depth",
                    "source",
                    "--raw-source-preview",
                    "all",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source refs:", result.stdout)
        self.assertIn("status: blocked", result.stdout)
        self.assertIn("reason: unsafe_source_ref", result.stdout)
        self.assertNotIn("OUTSIDE RAW CONTENT", result.stdout)
        self.assertNotIn("outside-link.jsonl", result.stdout)

    def test_search_memory_sanitizes_multiline_memory_metadata(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/display-safety"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Display Safety\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_display\n   injected: yes",
                        "layer": "global\n   injected: yes",
                        "scope": "global\n   injected: yes",
                        "topic": "display-safety",
                        "text": "Display safety token should sanitize metadata fields.",
                        "rationale": "Metadata fields are untrusted display data.",
                        "source": "explicit\n   injected: yes",
                        "confidence": "high\n   injected: yes",
                        "support_count": "1\n   injected: yes",
                        "derived_from": ["sessions/2026/06/17/display-safety/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "display safety token",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("[unsafe-field]", result.stdout)
        self.assertNotIn("injected: yes", result.stdout)
        self.assertNotIn("source:explicit\n", result.stdout)

    def test_search_memory_sanitizes_sensitive_memory_metadata(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-display"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Display\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_display cookie=SHOULD_NOT_RENDER",
                        "layer": "global cookie=SHOULD_NOT_RENDER",
                        "scope": "scope cookie=SHOULD_NOT_RENDER",
                        "topic": "sensitive-display",
                        "text": "Metadata display sentinel should sanitize memory fields.",
                        "rationale": "Metadata fields are untrusted display data.",
                        "source": "explicit cookie=SHOULD_NOT_RENDER",
                        "confidence": "high cookie=SHOULD_NOT_RENDER",
                        "support_count": "1 cookie=SHOULD_NOT_RENDER",
                        "derived_from": ["sessions/2026/06/17/sensitive-display/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "metadata display sentinel",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("[unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_sanitizes_sensitive_slug_memory_metadata(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-slug-display"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Slug Display\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_display cookie_should_not_render",
                        "layer": "global",
                        "scope": "scope cookie_should_not_render",
                        "topic": "sensitive-slug-display",
                        "text": "Slug metadata sentinel should sanitize memory fields.",
                        "rationale": "Metadata fields are untrusted display data.",
                        "source": "explicit cookie_should_not_render",
                        "confidence": "high cookie_should_not_render",
                        "support_count": "1 cookie_should_not_render",
                        "derived_from": ["sessions/2026/06/17/sensitive-slug-display/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "slug metadata sentinel",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("[unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie_should_not_render", result.stdout)
        self.assertNotIn("cookie", result.stdout.lower())

    def test_search_memory_keeps_safe_privacy_boundary_memory_ids(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/privacy-secret-gate"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Privacy Secret Gate\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_privacy_secret_gate",
                        "layer": "project",
                        "scope": "synthetic",
                        "topic": "privacy-boundary",
                        "text": "Likely secrets are refused unless redacted.",
                        "rationale": "Privacy boundary topics are safe to identify when no secret value is present.",
                        "source": "synthetic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/privacy-secret-gate/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "likely secrets refused redacted",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("memory_id: mem_privacy_secret_gate", result.stdout)
        self.assertNotIn("[unsafe-field]", result.stdout)

    def test_search_memory_sanitizes_sensitive_memory_text(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-text"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Text\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_sensitive_text",
                        "layer": "global",
                        "scope": "global",
                        "topic": "sensitive-text",
                        "text": "Memory display sentinel cookie=SHOULD_NOT_RENDER should not render.",
                        "rationale": "Memory text is untrusted display data.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/sensitive-text/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "memory display sentinel",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("[unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_sanitizes_sensitive_matched_tokens(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-match"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Match\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_sensitive_match",
                        "layer": "global",
                        "scope": "global",
                        "topic": "sensitive-match",
                        "text": "Matched reason sentinel cookie=SHOULD_NOT_RENDER should not render.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/sensitive-match/summary.md"],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "matched reason sentinel cookie=SHOULD_NOT_RENDER",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("matched:[unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)
        self.assertNotIn("cookie", result.stdout.lower())

    def test_search_memory_sanitizes_sensitive_drill_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/cookie=SHOULD_NOT_RENDER"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Path\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_sensitive_drill",
                        "layer": "global",
                        "scope": "global",
                        "topic": "sensitive-drill-path",
                        "text": "Sensitive drill path sentinel remains searchable.",
                        "source": "explicit",
                        "derived_from": [
                            "sessions/2026/06/17/cookie=SHOULD_NOT_RENDER/summary.md"
                        ],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "sensitive drill path sentinel",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("drill:", result.stdout)
        self.assertIn("     - [unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_skips_missing_memory_drill_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/reachable-drill"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Reachable Drill\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_reachable_drill",
                        "layer": "global",
                        "scope": "global",
                        "topic": "drill-reachability",
                        "text": "Reachable drill token should not advertise missing supporting files.",
                        "source": "explicit",
                        "derived_from": [
                            "sessions/2026/06/17/reachable-drill/summary.md",
                            "sessions/2026/06/17/missing-drill/summary.md",
                        ],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/missing-drill/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "reachable drill token",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("drill:", result.stdout)
        self.assertIn("sessions/2026/06/17/reachable-drill/summary.md", result.stdout)
        self.assertNotIn("sessions/2026/06/17/missing-drill/summary.md", result.stdout)
        self.assertNotIn("sessions/2026/06/17/missing-drill/evidence.md", result.stdout)

    def test_search_memory_skips_evidence_drill_paths_with_missing_quote_ids(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/quote-drill"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Quote Drill\n", encoding="utf-8")
            (session_dir / "evidence.md").write_text("ev_999: Different evidence snippet.\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_quote_drill",
                        "layer": "global",
                        "scope": "global",
                        "topic": "quote-drill",
                        "text": "Quote drill token should not advertise unsupported evidence snippets.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/quote-drill/summary.md"],
                        "evidence_refs": [
                            {"path": "sessions/2026/06/17/quote-drill/evidence.md", "quote_id": "ev_001"}
                        ],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "quote drill token",
                    "--repo",
                    str(repo),
                    "--depth",
                    "evidence",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("drill:", result.stdout)
        self.assertIn("sessions/2026/06/17/quote-drill/summary.md", result.stdout)
        self.assertNotIn("sessions/2026/06/17/quote-drill/evidence.md", result.stdout)

    def test_search_memory_default_memory_hit_shows_evidence_refs_without_raw_evidence_text(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/visible-evidence"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Visible Evidence\n", encoding="utf-8")
            (session_dir / "evidence.md").write_text(
                "ev_001: PRIVATE SUPPORTING EVIDENCE TEXT SHOULD NOT PRINT.\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_visible_evidence_ref",
                        "layer": "domain",
                        "scope": "memory-retrieval",
                        "topic": "visible-evidence",
                        "text": "Visible evidence refs let agents verify induced memories without reading raw evidence.",
                        "source": "automatic",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/visible-evidence/summary.md"],
                        "evidence_refs": [
                            {
                                "path": "sessions/2026/06/17/visible-evidence/evidence.md",
                                "quote_id": "ev_001",
                            }
                        ],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "visible evidence refs induced memories",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("source: memory", result.stdout)
        self.assertIn("memory_id: mem_visible_evidence_ref", result.stdout)
        self.assertIn("evidence:", result.stdout)
        self.assertIn("sessions/2026/06/17/visible-evidence/evidence.md#ev_001", result.stdout)
        self.assertNotIn("PRIVATE SUPPORTING EVIDENCE TEXT SHOULD NOT PRINT", result.stdout)

    def test_search_memory_sanitizes_sensitive_legacy_index_titles(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/sensitive-title"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Sensitive Title\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-17",
                        "project": "agent-memory",
                        "title": "Legacy title cookie=SHOULD_NOT_RENDER",
                        "summary": "Legacy title sentinel should sanitize display titles.",
                        "summary_path": "sessions/2026/06/17/sensitive-title/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "legacy title sentinel",
                    "--repo",
                    str(repo),
                    "--legacy-sessions",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("[unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_sanitizes_sensitive_query_echo_for_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/query-echo"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Query Echo\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_query_echo",
                        "layer": "global",
                        "scope": "global",
                        "topic": "query-echo",
                        "text": "Query echo sentinel should still find this memory.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/query-echo/summary.md"],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "query echo sentinel cookie=SHOULD_NOT_RENDER",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("Top memory hits for: [unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_sanitizes_bare_secret_query_echo_for_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/query-echo"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Query Echo\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_query_echo",
                        "layer": "global",
                        "scope": "global",
                        "topic": "query-echo",
                        "text": "Query echo sentinel should still find this memory.",
                        "source": "explicit",
                        "derived_from": ["sessions/2026/06/17/query-echo/summary.md"],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            fake_openai_key = "sk-" + "queryecho" + ("0" * 20)

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    f"query echo sentinel {fake_openai_key}",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("Top memory hits for: [unsafe-field]", result.stdout)
        self.assertNotIn(fake_openai_key, result.stdout)

    def test_search_memory_sanitizes_sensitive_query_echo_for_no_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions").mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "missing query cookie=SHOULD_NOT_RENDER",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("No memory hits for: [unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_scope_global_filters_memory_layers(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/17/global").mkdir(parents=True)
            (repo / "sessions/2026/06/17/project").mkdir(parents=True)
            (repo / "sessions/2026/06/17/global/summary.md").write_text("# Session: global\n", encoding="utf-8")
            (repo / "sessions/2026/06/17/project/summary.md").write_text("# Session: project\n", encoding="utf-8")
            rows = [
                {
                    "memory_id": "mem_global_recall_scope",
                    "layer": "global",
                    "scope": "global",
                    "topic": "recall-scope",
                    "text": "Recall scope token belongs to the global memory.",
                    "rationale": "Global node should remain visible with --scope global.",
                    "source": "automatic",
                    "confidence": "high",
                    "support_count": 2,
                    "derived_from": ["sessions/2026/06/17/global/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                },
                {
                    "memory_id": "mem_project_recall_scope",
                    "layer": "project",
                    "scope": "/tmp/project",
                    "topic": "recall-scope",
                    "text": "Recall scope token belongs to the project memory.",
                    "rationale": "Project node should be filtered by --scope global.",
                    "source": "automatic",
                    "confidence": "medium",
                    "support_count": 1,
                    "derived_from": ["sessions/2026/06/17/project/summary.md"],
                    "evidence_refs": [],
                    "raw_refs": [],
                },
            ]
            (repo / "index/memories.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "recall scope token",
                    "--repo",
                    str(repo),
                    "--scope",
                    "global",
                    "--limit",
                    "5",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("[global] Recall scope token belongs to the global memory.", result.stdout)
        self.assertNotIn("project memory", result.stdout)
        self.assertNotIn("sessions/2026/06/17/project/summary.md", result.stdout)

    def test_search_memory_legacy_sessions_uses_old_session_results(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/legacy"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Legacy Result\n\nlegacy fallback token appears here.\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_global_legacy_override",
                        "layer": "global",
                        "scope": "global",
                        "topic": "legacy",
                        "text": "legacy fallback token appears in a memory node too.",
                        "rationale": "Default search should prefer this unless legacy mode is requested.",
                        "source": "explicit",
                        "confidence": "high",
                        "support_count": 1,
                        "derived_from": ["sessions/2026/06/17/legacy/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-17",
                        "project": "agent-memory",
                        "title": "Legacy session result",
                        "summary": "legacy fallback token appears in the old session index.",
                        "summary_path": "sessions/2026/06/17/legacy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "legacy fallback token",
                    "--repo",
                    str(repo),
                    "--legacy-sessions",
                    "--scope",
                    "global",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("sessions/2026/06/17/legacy/summary.md", result.stdout)
        self.assertIn("index:sessions.jsonl", result.stdout)
        self.assertNotIn("source: memory", result.stdout)

    def test_search_memory_sanitizes_sensitive_legacy_result_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/cookie=SHOULD_NOT_RENDER"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Legacy Sensitive Path\n\nlegacy sensitive path token appears here.\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-17",
                        "project": "agent-memory",
                        "title": "Legacy sensitive path result",
                        "summary": "legacy sensitive path token appears in the old session index.",
                        "summary_path": "sessions/2026/06/17/cookie=SHOULD_NOT_RENDER/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "legacy sensitive path token",
                    "--repo",
                    str(repo),
                    "--legacy-sessions",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("1. [unsafe-field]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

    def test_search_memory_legacy_sessions_skips_invalid_memories_jsonl(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/legacy-invalid-memory"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Legacy Invalid Memory\n\nlegacy invalid memory token appears here.\n",
                encoding="utf-8",
            )
            (repo / "index/memories.jsonl").write_text(
                "{invalid memory json}\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-17",
                        "project": "agent-memory",
                        "title": "Legacy invalid memory result",
                        "summary": "legacy invalid memory token appears in the old session index.",
                        "summary_path": "sessions/2026/06/17/legacy-invalid-memory/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "legacy invalid memory token",
                    "--repo",
                    str(repo),
                    "--legacy-sessions",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(0, result.returncode)
        self.assertIn("sessions/2026/06/17/legacy-invalid-memory/summary.md", result.stdout)
        self.assertNotIn("skipped invalid JSON", result.stderr)
        self.assertNotIn("memories.jsonl", result.stderr)

    def test_search_memory_sanitizes_invalid_json_warning_paths(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/warning-path"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: Warning Path\n\nwarning path token appears here.\n",
                encoding="utf-8",
            )
            (repo / "index/cookie=SHOULD_NOT_RENDER.jsonl").write_text(
                "{invalid json}\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-17",
                        "project": "agent-memory",
                        "title": "Warning path result",
                        "summary": "warning path token appears in a valid session index.",
                        "summary_path": "sessions/2026/06/17/warning-path/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "warning path token",
                    "--repo",
                    str(repo),
                    "--legacy-sessions",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("warning: skipped invalid JSON at [unsafe-field]:1", result.stderr)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stderr)
        self.assertNotIn("cookie=", result.stderr)
        self.assertNotIn(str(repo.parent), result.stderr)

    def test_search_memory_does_not_return_index_paths_outside_archive(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions").mkdir()
            (repo / "index/sessions.jsonl").write_text(
                '{"date":"2026-05-14","source_agent":"agent",'
                '"project":"agent-memory","title":"Escape path memory",'
                '"summary_path":"../outside/secret.md",'
                '"summary":"archive path should stay inside repository"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "escape path", "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("index/sessions.jsonl", result.stdout)
        self.assertNotIn("../outside/secret.md", result.stdout)

    def test_search_memory_does_not_read_symlinked_markdown_outside_archive(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            outside = root / "outside-secret.md"
            outside.write_text("# Outside Secret\n\noutside-only-token should never be indexed.\n", encoding="utf-8")
            session_dir = repo / "sessions/2026/06/18/symlink"
            session_dir.mkdir(parents=True)
            (repo / "index").mkdir()
            (session_dir / "summary.md").symlink_to(outside)

            result = subprocess.run(
                [sys.executable, str(script), "outside-only-token", "--repo", str(repo)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No memory hits", result.stdout)
        self.assertNotIn("Outside Secret", result.stdout)
        self.assertNotIn("outside-only-token should never be indexed", result.stdout)
        self.assertNotIn(str(outside), result.stdout + result.stderr)

    def test_search_memory_does_not_read_symlinked_memory_index_outside_archive(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            outside = root / "outside-memory.jsonl"
            outside.write_text(
                json.dumps(
                    {
                        "memory_id": "outside_memory",
                        "layer": "global",
                        "scope": "global",
                        "topic": "outside",
                        "text": "outside-only-index-token should never be indexed.",
                        "source": "external",
                        "derived_from": [],
                        "raw_refs": [],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index").mkdir(parents=True)
            (repo / "sessions").mkdir()
            (repo / "index/memories.jsonl").symlink_to(outside)

            result = subprocess.run(
                [sys.executable, str(script), "outside-only-index-token", "--repo", str(repo)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No memory hits", result.stdout)
        self.assertNotIn("outside-only-index-token should never be indexed", result.stdout)
        self.assertNotIn("outside_memory", result.stdout)
        self.assertNotIn(str(outside), result.stdout + result.stderr)

    def test_search_memory_uses_summary_title_when_index_title_is_generic_source_file(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            summary_dir = repo / "sessions/2026/04/25/example"
            summary_dir.mkdir(parents=True)
            (summary_dir / "summary.md").write_text(
                "# Session: c-two: rollout-2026-04-25T13-42-27.jsonl\n",
                encoding="utf-8",
            )
            summary = (
                "README docs should read like standalone project documentation for 陌生开发者; "
                "Runnable Examples should be a concise index instead of repeating the walkthrough."
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-04-25",
                        "source_agent": "agent",
                        "project": "c-two",
                        "title": "c-two: rollout-2026-04-25T13-42-27.jsonl",
                        "summary": summary,
                        "summary_path": "sessions/2026/04/25/example/summary.md",
                        "tags": ["readme", "runnable", "examples"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "README 陌生开发者 runnable examples", "--repo", str(repo)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("title: README docs should read like standalone project documentation", result.stdout)
        self.assertNotIn("title: c-two: rollout-2026-04-25T13-42-27.jsonl", result.stdout)

    def test_search_memory_prioritizes_structured_decisions_over_tag_only_hits(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/05/01/good").mkdir(parents=True)
            (repo / "sessions/2026/05/01/tag-only").mkdir(parents=True)
            (repo / "sessions/2026/05/01/good/summary.md").write_text("# Session: good\n", encoding="utf-8")
            (repo / "sessions/2026/05/01/tag-only/summary.md").write_text("# Session: tag-only\n", encoding="utf-8")
            (repo / "index/decisions.jsonl").write_text(
                '{"date":"2026-05-01","project":"gridmen",'
                '"decision":"Root cause: Homebrew libheif references missing libx265.215.dylib during _gdal import.",'
                '"summary_path":"sessions/2026/05/01/good/summary.md"}\n',
                encoding="utf-8",
            )
            (repo / "index/tags.jsonl").write_text(
                '{"date":"2026-05-01","project":"misc","tag":"libx265",'
                '"summary_path":"sessions/2026/05/01/tag-only/summary.md"}\n'
                '{"date":"2026-05-01","project":"misc","tag":"libheif",'
                '"summary_path":"sessions/2026/05/01/tag-only/summary.md"}\n'
                '{"date":"2026-05-01","project":"misc","tag":"_gdal",'
                '"summary_path":"sessions/2026/05/01/tag-only/summary.md"}\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(script), "libx265 libheif _gdal", "--repo", str(repo), "--limit", "2"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/05/01/good/summary.md", first_hit)
        self.assertIn("Root cause: Homebrew libheif", result.stdout)

    def test_search_memory_prioritizes_specific_tokens_over_broad_project_noise(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/01/specific").mkdir(parents=True)
            (repo / "sessions/2026/06/01/noisy").mkdir(parents=True)
            (repo / "sessions/2026/06/01/specific/summary.md").write_text(
                "# Session: specific\n"
                "C-Two README should be written for 陌生开发者 as standalone documentation.\n",
                encoding="utf-8",
            )
            (repo / "sessions/2026/06/01/noisy/summary.md").write_text(
                "# Session: noisy\n"
                "C-Two README runnable examples workflow release examples runnable README.\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-01",
                        "project": "my-precious-skill",
                        "title": "my-precious-skill: rollout-2026-06-01T00-00-00.jsonl",
                        "summary": "C-Two README should be written for 陌生开发者 as standalone documentation.",
                        "summary_path": "sessions/2026/06/01/specific/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-01",
                        "project": "c-two",
                        "title": "c-two: rollout-2026-06-01T00-00-00.jsonl",
                        "summary": "C-Two README runnable examples workflow release examples runnable README.",
                        "summary_path": "sessions/2026/06/01/noisy/summary.md",
                        "tags": ["c-two", "readme", "examples", "runnable"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "README 陌生开发者 Runnable Examples c-two",
                    "--repo",
                    str(repo),
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/01/specific/summary.md", first_hit)
        self.assertIn("陌生开发者", first_hit)

    def test_search_memory_prioritizes_entity_match_over_shared_proxy_tokens(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/11/cc-switch").mkdir(parents=True)
            (repo / "sessions/2026/05/08/proxy-noise").mkdir(parents=True)
            (repo / "sessions/2026/06/11/cc-switch/summary.md").write_text("# Session: cc-switch\n", encoding="utf-8")
            (repo / "sessions/2026/05/08/proxy-noise/summary.md").write_text("# Session: proxy noise\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-11",
                        "project": "cc-switch",
                        "title": "CC Switch supports proxy settings",
                        "summary": "CC Switch can use 全局出站代理 such as http://127.0.0.1:7890, while Local Routing is separate.",
                        "summary_path": "sessions/2026/06/11/cc-switch/summary.md",
                        "tags": ["cc-switch", "proxy", "127.0.0.1", "7890"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-05-08",
                        "project": "flow-field-texture-builder",
                        "title": "Build container proxy failure",
                        "summary": "apt-get failed because a build container used 127.0.0.1:7897 as a proxy. proxy proxy proxy proxy proxy.",
                        "summary_path": "sessions/2026/05/08/proxy-noise/summary.md",
                        "tags": ["proxy", "127.0.0.1"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "cc-switch 127.0.0.1:7890 socks5 proxy",
                    "--repo",
                    str(repo),
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/11/cc-switch/summary.md", first_hit)

    def test_search_memory_prioritizes_important_phrase_coverage(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/04/27/exact").mkdir(parents=True)
            (repo / "sessions/2026/04/27/broad").mkdir(parents=True)
            (repo / "sessions/2026/04/27/exact/summary.md").write_text("# Session: exact\n", encoding="utf-8")
            (repo / "sessions/2026/04/27/broad/summary.md").write_text("# Session: broad\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-04-27",
                        "project": "c-two",
                        "title": "Concurrent reconnect losers return spurious 502",
                        "summary": "Residual gap: concurrent reconnect loser path must avoid a spurious 502.",
                        "summary_path": "sessions/2026/04/27/exact/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-04-27",
                        "project": "c-two",
                        "title": "Generic HTTP 502 review",
                        "summary": "HTTP 502 happened in a broad review. 502 502 502 502.",
                        "tags": ["502"],
                        "summary_path": "sessions/2026/04/27/broad/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "Concurrent reconnect losers spurious 502",
                    "--repo",
                    str(repo),
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/04/27/exact/summary.md", first_hit)

    def test_search_memory_prefers_compact_session_title_over_matching_long_summary(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/11/cc-switch").mkdir(parents=True)
            (repo / "sessions/2026/06/11/cc-switch/summary.md").write_text(
                "# Session: cc switch这个软件是否能设置代理？\n"
                "Use Settings > Proxy > Global Outbound Proxy with http://127.0.0.1:7890.\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-11",
                        "project": "cc-switch",
                        "title": "cc switch这个软件是否能设置代理？",
                        "summary": (
                            "cc switch这个软件是否能设置代理？ 可以。 在 CC Switch 里进："
                            "`设置 → 代理 → 全局出站代理`，然后填 http://127.0.0.1:7890 "
                            "或者 socks5://127.0.0.1:7890。"
                        ),
                        "user_intent": "cc switch这个软件是否能设置代理？",
                        "tags": ["cc-switch", "proxy", "127.0.0.1", "7890", "socks5"],
                        "summary_path": "sessions/2026/06/11/cc-switch/summary.md",
                        "unresolved_count": 0,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "cc-switch 127.0.0.1:7890 socks5 proxy",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("title: cc switch这个软件是否能设置代理？", result.stdout)
        self.assertNotIn("title: cc switch这个软件是否能设置代理？ 可以。", result.stdout)

    def test_search_memory_explains_structured_phrase_match(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/12/good").mkdir(parents=True)
            (repo / "sessions/2026/06/12/noisy").mkdir(parents=True)
            (repo / "sessions/2026/06/12/good/summary.md").write_text("# Session: good\n", encoding="utf-8")
            (repo / "sessions/2026/06/12/noisy/summary.md").write_text("# Session: noisy\n", encoding="utf-8")
            (repo / "index/decisions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-12",
                        "project": "c-two",
                        "decision": "C-Two work follows a review-fix-re-review loop before completion.",
                        "summary_path": "sessions/2026/06/12/good/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-12",
                        "project": "misc",
                        "title": "Broad review loop notes",
                        "summary": "review loop review loop review loop review loop review loop",
                        "tags": ["review", "loop"],
                        "summary_path": "sessions/2026/06/12/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "review-fix-re-review loop",
                    "--repo",
                    str(repo),
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/12/good/summary.md", first_hit)
        self.assertIn("field:decision", first_hit)
        self.assertIn("phrase:review-fix-re-review loop", first_hit)

    def test_search_memory_project_path_boost_breaks_tie(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/c-two").mkdir(parents=True)
            (repo / "sessions/2026/06/13/other").mkdir(parents=True)
            (repo / "sessions/2026/06/13/c-two/summary.md").write_text("# Session: c-two\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/other/summary.md").write_text("# Session: other\n", encoding="utf-8")
            shared_summary = "FastDB FdbViewOwner invalidate lifetime boundary review."
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "unrelated",
                        "project_path": "/tmp/other-project",
                        "summary": shared_summary,
                        "summary_path": "sessions/2026/06/13/other/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                        "summary": shared_summary,
                        "summary_path": "sessions/2026/06/13/c-two/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "FastDB FdbViewOwner invalidate lifetime",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/c-two/summary.md", first_hit)
        self.assertIn("project-context", first_hit)

    def test_search_memory_project_context_matches_separator_variants(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/current").mkdir(parents=True)
            (repo / "sessions/2026/06/13/other").mkdir(parents=True)
            (repo / "sessions/2026/06/13/current/summary.md").write_text("# Session: current\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/other/summary.md").write_text("# Session: other\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "other-project",
                        "summary": "Layered recall metric threshold threshold threshold threshold.",
                        "summary_path": "sessions/2026/06/13/other/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "my_precious_skill",
                        "summary": "Layered recall metric threshold.",
                        "summary_path": "sessions/2026/06/13/current/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "layered recall metric threshold",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/mememe/my-precious-skill",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/current/summary.md", first_hit)
        self.assertIn("project-context", first_hit)

    def test_search_memory_project_context_does_not_promote_context_only_noise(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/good").mkdir(parents=True)
            (repo / "sessions/2026/06/13/noisy").mkdir(parents=True)
            (repo / "sessions/2026/06/13/good/summary.md").write_text("# Session: good\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/noisy/summary.md").write_text("# Session: noisy\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "gridmen",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/gridmen",
                        "summary": "PatchEdit stale closure root cause affects selectTab and pickingTab mode restoration.",
                        "summary_path": "sessions/2026/06/13/good/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                        "summary": "Generic project update with no patch editor details.",
                        "summary_path": "sessions/2026/06/13/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/decisions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "decision": "A stale C-Two relay loop was reviewed.",
                        "summary_path": "sessions/2026/06/13/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "index/tags.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "tag": "c-two",
                        "summary_path": "sessions/2026/06/13/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "PatchEdit stale closure selectTab c-two",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/good/summary.md", first_hit)
        self.assertNotIn("project-context", first_hit)

    def test_search_memory_project_token_does_not_satisfy_specific_coverage(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/good").mkdir(parents=True)
            (repo / "sessions/2026/06/13/noisy").mkdir(parents=True)
            (repo / "sessions/2026/06/13/good/summary.md").write_text("# Session: good\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/noisy/summary.md").write_text("# Session: noisy\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "gridmen",
                        "summary": "PatchEdit stale closure selectTab mode restoration regression.",
                        "summary_path": "sessions/2026/06/13/good/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                        "summary": "A stale C-Two relay loop was reviewed.",
                        "summary_path": "sessions/2026/06/13/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "PatchEdit stale closure selectTab c-two",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/good/summary.md", first_hit)

    def test_search_memory_project_only_match_is_not_important_token_coverage(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/project-only").mkdir(parents=True)
            (repo / "sessions/2026/06/13/project-only/summary.md").write_text("# Session: project only\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                        "summary": "Generic project housekeeping.",
                        "summary_path": "sessions/2026/06/13/project-only/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "c-two",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("low-signal-only", result.stdout)
        self.assertNotIn("important-token-coverage", result.stdout)

    def test_search_memory_project_context_token_does_not_keep_markdown_only_hit(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/13/context-only-markdown"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text(
                "# Session: C-Two housekeeping\n\n"
                "C-Two project housekeeping happened, with no deployment decision recorded.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "c-two migration",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("No memory hits for: c-two migration", result.stdout)
        self.assertNotIn("context-only-markdown/summary.md", result.stdout)

    def test_search_memory_duplicate_low_signal_rows_do_not_outrank_content_hit(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/content").mkdir(parents=True)
            (repo / "sessions/2026/06/13/noisy").mkdir(parents=True)
            (repo / "sessions/2026/06/13/content/summary.md").write_text("# Session: content\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/noisy/summary.md").write_text("# Session: noisy\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "gridmen",
                        "summary": "PatchEdit stale closure selectTab mode restoration regression.",
                        "summary_path": "sessions/2026/06/13/content/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                        "summary": "A stale C-Two relay loop was reviewed.",
                        "summary_path": "sessions/2026/06/13/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            for index_name, key in (("decisions", "decision"), ("unresolved", "task"), ("tags", "tag"), ("files", "path")):
                (repo / f"index/{index_name}.jsonl").write_text(
                    "".join(
                        json.dumps(
                            {
                                "date": "2026-06-13",
                                "project": "c-two",
                                key: f"stale c-two loop {idx}",
                                "summary_path": "sessions/2026/06/13/noisy/summary.md",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                        for idx in range(8)
                    ),
                    encoding="utf-8",
                )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "PatchEdit stale closure selectTab c-two",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/c-two",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/content/summary.md", first_hit)

    def test_search_memory_penalizes_search_verification_memory_entries(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/real").mkdir(parents=True)
            (repo / "sessions/2026/06/13/verification").mkdir(parents=True)
            (repo / "sessions/2026/06/13/real/summary.md").write_text("# Session: real\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/verification/summary.md").write_text(
                "# Session: verification\n", encoding="utf-8"
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "my-precious-skill",
                        "title": "Good hit: captures libx265.215.dylib _gdal osgeo search verification.",
                        "summary": "Search verification example says top hit captured libx265.215.dylib _gdal osgeo.",
                        "summary_path": "sessions/2026/06/13/verification/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "gridmen",
                        "title": "GDAL import fails on missing libx265.215.dylib",
                        "summary": "Root cause: Homebrew libheif references missing libx265.215.dylib during _gdal import.",
                        "summary_path": "sessions/2026/06/13/real/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "libx265.215.dylib _gdal osgeo",
                    "--repo",
                    str(repo),
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/real/summary.md", first_hit)

    def test_search_memory_filters_search_verification_only_entries(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/verification").mkdir(parents=True)
            (repo / "sessions/2026/06/13/verification/summary.md").write_text(
                "# Session: verification\n", encoding="utf-8"
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "my-precious-skill",
                        "title": "Expected title to include PatchEdit stale closure selectTab",
                        "summary": "Search verification result stdout mentions PatchEdit stale closure selectTab.",
                        "summary_path": "sessions/2026/06/13/verification/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "PatchEdit stale closure selectTab",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("No memory hits for: PatchEdit stale closure selectTab", result.stdout)

    def test_search_memory_project_context_can_beat_external_archive_noise(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/gridmen").mkdir(parents=True)
            (repo / "sessions/2026/06/13/noise").mkdir(parents=True)
            (repo / "sessions/2026/06/13/gridmen/summary.md").write_text("# Session: gridmen\n", encoding="utf-8")
            (repo / "sessions/2026/06/13/noise/summary.md").write_text("# Session: noise\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "my-precious-skill",
                        "summary": "A memory-quality note mentions libx265.215.dylib _gdal osgeo as a search example.",
                        "summary_path": "sessions/2026/06/13/noise/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n"
                + json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "gridmen",
                        "project_path": "/Users/soku/Desktop/codespace/WorldInProgress/gridmen",
                        "summary": "Root cause: Homebrew libheif references missing libx265.215.dylib during _gdal import.",
                        "summary_path": "sessions/2026/06/13/gridmen/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "libx265.215.dylib _gdal osgeo",
                    "--repo",
                    str(repo),
                    "--project-path",
                    "/Users/soku/Desktop/codespace/WorldInProgress/gridmen",
                    "--limit",
                    "2",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        first_hit = result.stdout.split("\n\n", 2)[1]
        self.assertIn("sessions/2026/06/13/gridmen/summary.md", first_hit)

    def test_search_memory_filters_low_signal_hits_when_important_terms_are_missing(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/13/noisy").mkdir(parents=True)
            (repo / "sessions/2026/06/13/noisy/summary.md").write_text(
                "# Session: noisy\n"
                "A stale relay review happened in another project.\n",
                encoding="utf-8",
            )
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-13",
                        "project": "c-two",
                        "summary": "A stale relay review happened in another project.",
                        "summary_path": "sessions/2026/06/13/noisy/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "PatchEdit stale closure selectTab",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("No memory hits for: PatchEdit stale closure selectTab", result.stdout)

    def test_search_memory_explains_important_token_coverage(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            (repo / "sessions/2026/06/14/specific").mkdir(parents=True)
            (repo / "sessions/2026/06/14/specific/summary.md").write_text("# Session: specific\n", encoding="utf-8")
            (repo / "index/sessions.jsonl").write_text(
                json.dumps(
                    {
                        "date": "2026-06-14",
                        "project": "gridmen",
                        "title": "GDAL startup failure",
                        "summary": "GDAL import failed because libheif referenced missing libx265.215.dylib.",
                        "summary_path": "sessions/2026/06/14/specific/summary.md",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "GDAL libx265.215.dylib",
                    "--repo",
                    str(repo),
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertIn("important-token-coverage", result.stdout)

    def test_search_memory_does_not_match_ascii_query_token_inside_word(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/20/substring"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: substring\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_concatenate",
                        "layer": "global",
                        "scope": "global",
                        "topic": "string-joining",
                        "text": "Concatenate archive fragments without a standalone feline keyword.",
                        "source": "synthetic",
                        "derived_from": ["sessions/2026/06/20/substring/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "cat",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("No memory hits for: cat", result.stdout)
        self.assertNotIn("mem_concatenate", result.stdout)

    def test_search_memory_ignores_question_stopword_only_overlap(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/20/stopwords"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: stopwords\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_question_noise",
                        "layer": "global",
                        "scope": "global",
                        "topic": "question-noise",
                        "text": "Which project is it in?",
                        "source": "synthetic",
                        "derived_from": ["sessions/2026/06/20/stopwords/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "Which repo is it in?",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("No memory hits for: Which repo is it in?", result.stdout)
        self.assertNotIn("mem_question_noise", result.stdout)

    def test_search_memory_rejects_query_with_only_stopwords(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "What is it?",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("query must contain at least one searchable token", result.stderr)

    def test_search_memory_ignores_generic_memory_modal_overlap(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "agent-memory"
            repo.mkdir()
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/20/modal-overlap"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: modal overlap\n", encoding="utf-8")
            (repo / "index/memories.jsonl").write_text(
                json.dumps(
                    {
                        "memory_id": "mem_memory_should_noise",
                        "layer": "global",
                        "scope": "global",
                        "topic": "modal-overlap",
                        "text": "Which memory should keep the old scheduler mode?",
                        "source": "synthetic",
                        "derived_from": ["sessions/2026/06/20/modal-overlap/summary.md"],
                        "evidence_refs": [],
                        "raw_refs": [],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "Which memory should cache?",
                    "--repo",
                    str(repo),
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("No memory hits for: Which memory should cache?", result.stdout)
        self.assertNotIn("mem_memory_should_noise", result.stdout)


if __name__ == "__main__":
    unittest.main()
