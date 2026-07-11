import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SETUP_SCRIPT = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()


def set_mtime(path: Path, stamp: str) -> None:
    dt = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    os.utime(path, (dt.timestamp(), dt.timestamp()))


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class ResolveMemorySourceTests(unittest.TestCase):
    def build_archive(self, root: Path, *, secret_token: str = "") -> tuple[Path, Path, str, str]:
        memory_repo = root / "agent-memory"
        source_root = root / "source-records"
        project_path = root / "project"
        source_root.mkdir()
        project_path.mkdir()
        setup = run(
            [sys.executable, str(SETUP_SCRIPT), "--path", str(memory_repo), "--mode", "local", "--skip-config"]
        )
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)

        fact = "Resolver event preview should return the exact supporting event."
        query = "resolver event preview exact supporting event"
        source = source_root / "session.jsonl"
        secret_suffix = f" {secret_token}" if secret_token else ""
        source.write_text(
            "\n".join(
                [
                    json.dumps({"role": "user", "content": "Inspect the original event when explicitly authorized."}),
                    json.dumps({"role": "assistant", "content": "Decision: Keep an unrelated first quote as a distractor."}),
                    json.dumps({"role": "assistant", "content": f"Reusable fact: {fact}{secret_suffix}"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        set_mtime(source, "2026-07-11T12:00:00Z")
        update = run(
            [
                sys.executable,
                str(memory_repo / "tools/update_memory_archive.py"),
                "--memory-repo",
                str(memory_repo),
                "--source-dir",
                str(source_root),
                "--project-path",
                str(project_path),
                "--source-agent",
                "synthetic-agent",
                "--rewrite-existing",
                *(["--allow-redacted-secrets"] if secret_token else []),
            ],
            cwd=memory_repo,
        )
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        return memory_repo, source_root, query, fact

    def source_ref_id(self, memory_repo: Path, query: str) -> str:
        result = run(
            [
                sys.executable,
                str(memory_repo / "tools/search_memory.py"),
                query,
                "--repo",
                str(memory_repo),
                "--depth",
                "source",
                "--context-json",
            ],
            cwd=memory_repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        package = json.loads(result.stdout)
        self.assertEqual(package["report_kind"], "memory_recall_context_package")
        self.assertEqual(package["answerability"]["status"], "supported")
        supported_hit = next(
            hit
            for hit in package["hits"]
            if hit["active_current"] is True
            and hit["answerability"]["status"] == "supported"
            and hit["query_support"]["status"] == "supported"
            and hit["source_refs"]
        )
        return supported_hit["source_refs"][0]["source_ref_id"]

    def resolve(
        self,
        memory_repo: Path,
        source_root: Path,
        query: str,
        source_ref_id: str,
        *,
        authorize: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        command = [
            sys.executable,
            str(memory_repo / "tools/resolve_memory_source.py"),
            query,
            "--repo",
            str(memory_repo),
            "--source-ref-id",
            source_ref_id,
            "--allow-source-root",
            str(source_root),
        ]
        if authorize:
            command.append("--authorize-source-preview")
        command.append("--preview-json")
        result = run(command, cwd=memory_repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result, json.loads(result.stdout)

    def source_map(self, memory_repo: Path) -> tuple[Path, dict]:
        path = next((memory_repo / "sessions").glob("**/source-map.json"))
        return path, json.loads(path.read_text(encoding="utf-8"))

    def write_source_map(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_authorized_exact_ref_resolves_redacted_original_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, fact = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)

            result, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["report_kind"], "memory_source_preview_package")
        self.assertEqual(package["status"], "resolved")
        self.assertEqual(package["reason"], "original_event_resolved")
        self.assertEqual(package["source_ref_id"], source_ref_id)
        self.assertTrue(package["support_validation"]["active_current_query_supported"])
        self.assertTrue(package["integrity"]["source_root_allowed"])
        self.assertTrue(package["integrity"]["source_hash_verified"])
        self.assertTrue(package["integrity"]["source_anchor_verified"])
        self.assertIn(fact, package["preview"])
        self.assertNotIn(str(source_root), result.stdout + result.stderr)
        self.assertFalse(package["privacy"]["full_query_rendered"])
        self.assertFalse(package["privacy"]["source_path_rendered"])
        self.assertFalse(package["privacy"]["raw_ref_rendered"])
        self.assertFalse(package["privacy"]["unrestricted_source_content_rendered"])

    def test_missing_authorization_blocks_without_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            result, package = self.resolve(
                memory_repo,
                source_root,
                query,
                source_ref_id,
                authorize=False,
            )

        self.assertEqual(package["status"], "blocked")
        self.assertEqual(package["reason"], "authorization_required")
        self.assertEqual(package["preview"], "")
        self.assertNotIn(str(source_root), result.stdout + result.stderr)

    def test_no_hit_and_wrong_ref_are_unsupported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            _, no_hit = self.resolve(memory_repo, source_root, "absent lexical query marker", source_ref_id)
            _, wrong_ref = self.resolve(memory_repo, source_root, query, "src_000000000000")

        self.assertEqual(no_hit["status"], "unsupported")
        self.assertEqual(no_hit["reason"], "source_ref_not_supported")
        self.assertEqual(wrong_ref["status"], "unsupported")
        self.assertEqual(wrong_ref["reason"], "source_ref_not_supported")

    def test_inactive_source_only_is_rejected_distinctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, fact = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            index_path = memory_repo / "index/memories.jsonl"
            rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
            inactive = next(row for row in rows if row.get("text") == fact)
            inactive["superseded_by"] = "mem_current_unrelated"
            current = dict(inactive)
            current["memory_id"] = "mem_current_unrelated"
            current["text"] = "Current replacement has unrelated lexical support."
            current["supersedes"] = [inactive["memory_id"]]
            current["superseded_by"] = None
            current["raw_refs"] = []
            rows.append(current)
            index_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )

            _, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "unsupported")
        self.assertEqual(package["reason"], "inactive_source_only")
        self.assertEqual(package["preview"], "")

    def test_source_root_escape_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            other_root = root / "other-source-root"
            other_root.mkdir()
            _, package = self.resolve(memory_repo, other_root, query, source_ref_id)

        self.assertEqual(package["status"], "blocked")
        self.assertEqual(package["reason"], "source_root_escape")
        self.assertEqual(package["preview"], "")

    def test_symlink_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            outside_dir = root / "outside"
            outside_dir.mkdir()
            outside_source = outside_dir / "outside.jsonl"
            outside_source.write_text((source_root / "session.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
            link = source_root / "linked.jsonl"
            link.symlink_to(outside_source)
            source_map_path, source_map = self.source_map(memory_repo)
            source_map["source_record"] = str(source_root.resolve() / link.name)
            source_map["source_record_sha256"] = hashlib.sha256(outside_source.read_bytes()).hexdigest()
            self.write_source_map(source_map_path, source_map)
            _, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "blocked")
        self.assertEqual(package["reason"], "symlink_escape")
        self.assertEqual(package["preview"], "")

    def test_source_hash_and_event_hash_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            source = source_root / "session.jsonl"
            original = source.read_text(encoding="utf-8")
            source.write_text(original + json.dumps({"role": "assistant", "content": "Appended mutation."}) + "\n", encoding="utf-8")
            _, hash_package = self.resolve(memory_repo, source_root, query, source_ref_id)

            source.write_text(original, encoding="utf-8")
            source_map_path, source_map = self.source_map(memory_repo)
            source_map["evidence_source_anchors"][-1]["event_sha256"] = "0" * 64
            self.write_source_map(source_map_path, source_map)
            _, anchor_package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(hash_package["reason"], "source_hash_mismatch")
        self.assertEqual(hash_package["preview"], "")
        self.assertEqual(anchor_package["reason"], "source_anchor_mismatch")
        self.assertEqual(anchor_package["preview"], "")

    def test_coordinated_source_map_redirect_cannot_preserve_source_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            redirected_text = "Reusable fact: Redirected source map event must never resolve."
            redirected = source_root / "redirected.jsonl"
            redirected.write_text(
                "\n".join(
                    [
                        json.dumps({"role": "user", "content": "Redirected first event."}),
                        json.dumps({"role": "assistant", "content": "Decision: Redirected second event."}),
                        json.dumps({"role": "assistant", "content": redirected_text}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            source_map_path, source_map = self.source_map(memory_repo)
            source_map["source_record"] = str(redirected.resolve())
            source_map["source_record_sha256"] = hashlib.sha256(redirected.read_bytes()).hexdigest()
            target_anchor = next(
                row for row in source_map["evidence_source_anchors"] if row.get("line_number") == 3
            )
            target_anchor["event_sha256"] = hashlib.sha256(redirected_text.encode("utf-8")).hexdigest()
            self.write_source_map(source_map_path, source_map)
            _, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "blocked")
        self.assertEqual(package["reason"], "source_anchor_mismatch")
        self.assertEqual(package["preview"], "")

    def test_legacy_source_map_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            source_map_path, source_map = self.source_map(memory_repo)
            source_map.pop("source_anchor_version")
            self.write_source_map(source_map_path, source_map)
            _, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "unavailable")
        self.assertEqual(package["reason"], "legacy_source_anchor_unavailable")
        self.assertEqual(package["preview"], "")

    def test_malformed_context_package_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            (memory_repo / "tools/search_memory.py").write_text(
                "#!/usr/bin/env python3\nprint('{not-json')\n",
                encoding="utf-8",
            )
            _, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "unsupported")
        self.assertEqual(package["reason"], "malformed_context_package")
        self.assertEqual(package["preview"], "")

    def test_unsupported_source_format_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            source_ref_id = self.source_ref_id(memory_repo, query)
            source_map_path, source_map = self.source_map(memory_repo)
            unsupported = source_root / "session.txt"
            unsupported.write_bytes((source_root / "session.jsonl").read_bytes())
            source_map["source_record"] = str(unsupported.resolve())
            source_map["source_record_sha256"] = hashlib.sha256(unsupported.read_bytes()).hexdigest()
            self.write_source_map(source_map_path, source_map)
            _, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "unavailable")
        self.assertEqual(package["reason"], "unsupported_source_format")
        self.assertEqual(package["preview"], "")

    def test_source_ref_id_rejects_all_selector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, _ = self.build_archive(root)
            result = run(
                [
                    sys.executable,
                    str(memory_repo / "tools/resolve_memory_source.py"),
                    query,
                    "--repo",
                    str(memory_repo),
                    "--source-ref-id",
                    "all",
                    "--allow-source-root",
                    str(source_root),
                    "--authorize-source-preview",
                    "--preview-json",
                ],
                cwd=memory_repo,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--source-ref-id must be one exact source_ref_id", result.stderr)

    def test_authorized_preview_redacts_secret_token(self):
        secret = "ghp_" + "SHOULDNOTRENDER" * 2
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, query, fact = self.build_archive(root, secret_token=secret)
            source_ref_id = self.source_ref_id(memory_repo, query)
            result, package = self.resolve(memory_repo, source_root, query, source_ref_id)

        self.assertEqual(package["status"], "resolved", package)
        self.assertIn(fact, package["preview"])
        self.assertIn("[REDACTED_GITHUB_TOKEN]", package["preview"])
        self.assertTrue(package["redaction"]["applied"])
        self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
