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
