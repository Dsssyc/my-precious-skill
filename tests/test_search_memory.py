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

    def test_search_memory_depth_source_shows_source_anchors_without_raw_content(self):
        script = Path("templates/agent-memory-repo/tools/search_memory.py").resolve()

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "index").mkdir()
            session_dir = repo / "sessions/2026/06/17/source"
            session_dir.mkdir(parents=True)
            (session_dir / "summary.md").write_text("# Session: Source Anchors\n", encoding="utf-8")
            raw_path = repo / "records/private.jsonl"
            raw_path.parent.mkdir(parents=True)
            raw_path.write_text("FAKE RAW PRIVATE CONTENT THAT MUST NOT BE PRINTED\n", encoding="utf-8")
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

        self.assertIn("source anchors:", result.stdout)
        self.assertIn("records/private.jsonl#message:42", result.stdout)
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

        self.assertIn("source anchors:", result.stdout)
        self.assertIn("[unsafe-source-ref]", result.stdout)
        self.assertNotIn("../outside", result.stdout)
        self.assertNotIn("/Users/private", result.stdout)
        self.assertNotIn("injected: yes", result.stdout)

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

        self.assertIn("source anchors:", result.stdout)
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

        self.assertIn("source anchors:", result.stdout)
        self.assertIn("[unsafe-source-ref]", result.stdout)
        self.assertNotIn("SHOULD_NOT_RENDER", result.stdout)
        self.assertNotIn("cookie=", result.stdout)

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


if __name__ == "__main__":
    unittest.main()
