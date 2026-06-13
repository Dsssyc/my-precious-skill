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


if __name__ == "__main__":
    unittest.main()
