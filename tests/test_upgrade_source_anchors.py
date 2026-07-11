import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SETUP_SCRIPT = Path("skills/setup-my-precious/scripts/setup_memory_archive.py").resolve()
UPGRADE_SCRIPT = Path("templates/agent-memory-repo/tools/upgrade_source_anchors.py").resolve()
BACKFILL_SCRIPT = Path("templates/agent-memory-repo/tools/backfill_memory_archive.py").resolve()


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def set_mtime(path: Path, stamp: str) -> None:
    value = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    os.utime(path, (value.timestamp(), value.timestamp()))


def jsonl_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def load_upgrade_module():
    module_name = "upgrade_source_anchors_under_test"
    spec = importlib.util.spec_from_file_location(module_name, UPGRADE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("upgrade module could not be loaded")
    sys.path.insert(0, str(UPGRADE_SCRIPT.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def load_backfill_module():
    module_name = "backfill_memory_archive_for_upgrade_evidence"
    spec = importlib.util.spec_from_file_location(module_name, BACKFILL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("backfill module could not be loaded")
    sys.path.insert(0, str(BACKFILL_SCRIPT.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class UpgradeSourceAnchorsTests(unittest.TestCase):
    def test_existing_backfill_can_delete_entry_before_failed_rewrite_without_rollback(self):
        module = load_backfill_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo = root / "agent-memory"
            entry = memory_repo / "sessions/2026/07/12/legacy-entry"
            entry.mkdir(parents=True)
            (entry / "summary.md").write_text("legacy bytes\n", encoding="utf-8")
            source = root / "legacy.jsonl"
            source.write_text(json.dumps({"role": "assistant", "content": "Reusable fact: durable."}) + "\n")
            group = module.BackfillGroup(
                project_path=root / "project",
                archive_scope="project",
                source_partition="partition",
                project_name="project",
                source_agent="synthetic-agent",
                source_record=source,
                entries=[entry],
            )
            args = Namespace(
                prune_only=False,
                prune_missing_source_noise=False,
                memory_repo=str(memory_repo),
                project_path=None,
                source_record=None,
                max_records=-1,
                dry_run=False,
                allow_redacted_secrets=False,
                project=None,
                source_agent=None,
            )
            with (
                mock.patch.object(module, "parse_args", return_value=args),
                mock.patch.object(module, "resolve_memory_repo", return_value=memory_repo),
                mock.patch.object(module, "collect_groups", return_value=[group]),
                mock.patch.object(module, "write_record", return_value=None),
                mock.patch.object(module, "rebuild_indexes"),
            ):
                with redirect_stdout(io.StringIO()):
                    return_code = module.main([])

            self.assertEqual(return_code, 0)
            self.assertFalse(entry.exists())

    def build_legacy_archive(self, root: Path, *, secret_token: str = "") -> tuple[Path, Path, str]:
        memory_repo = root / "agent-memory"
        source_root = root / "external-sources"
        project_path = root / "project"
        source_root.mkdir()
        project_path.mkdir()
        setup = run(
            [sys.executable, str(SETUP_SCRIPT), "--path", str(memory_repo), "--mode", "local", "--skip-config"]
        )
        self.assertEqual(setup.returncode, 0, setup.stdout + setup.stderr)

        fact = "Legacy source upgrade must preserve exact event provenance."
        source = source_root / "legacy.jsonl"
        source.write_text(
            "\n".join(
                [
                    json.dumps({"role": "user", "content": "Review legacy source upgrade behavior."}),
                    json.dumps({"role": "assistant", "content": "Decision: Keep the first quote unrelated."}),
                    json.dumps(
                        {
                            "role": "assistant",
                            "content": f"Reusable fact: {fact}{(' ' + secret_token) if secret_token else ''}",
                        }
                    ),
                    json.dumps({"role": "assistant", "content": "Acknowledged."}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        set_mtime(source, "2026-07-12T10:00:00Z")
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

        entry = next(path.parent for path in (memory_repo / "sessions").glob("**/source-map.json"))
        source_map_path = entry / "source-map.json"
        source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
        source_map.pop("source_anchor_version")
        source_map.pop("evidence_source_anchors")
        source_map_path.write_text(json.dumps(source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        meta_path = entry / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("source_anchor_version")
        for field in ("reusable_fact_sources", "memory_candidate_sources", "explicit_memory_sources"):
            for row in meta.get(field) or []:
                if isinstance(row, dict):
                    row.pop("source_anchor_id", None)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        source_map_rel = source_map["source_map_path"]
        for path in [
            memory_repo / "index/memories.jsonl",
            memory_repo / "memories/global.jsonl",
            memory_repo / "memories/domains.jsonl",
            memory_repo / "memories/projects.jsonl",
            memory_repo / "memories/explicit.jsonl",
        ]:
            rows = jsonl_rows(path)
            changed = False
            for row in rows:
                raw_refs = row.get("raw_refs")
                if not isinstance(raw_refs, list):
                    continue
                for raw_ref in raw_refs:
                    if isinstance(raw_ref, dict) and raw_ref.get("path") == source_map_rel:
                        raw_ref["anchor"] = "source_record"
                        changed = True
            if changed:
                write_jsonl(path, rows)
        return memory_repo, source_root, fact

    def upgrade_report(
        self,
        memory_repo: Path,
        source: Path,
        allow_root: Path,
        *extra: str,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = run(
            [
                sys.executable,
                str(UPGRADE_SCRIPT),
                "--memory-repo",
                str(memory_repo),
                "--source-record",
                str(source),
                "--allow-source-root",
                str(allow_root),
                "--dry-run",
                "--report-json",
                *extra,
            ],
            cwd=memory_repo,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result, json.loads(result.stdout)

    def replace_archived_source_hash(self, memory_repo: Path, source: Path) -> None:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        entry = next(path.parent for path in (memory_repo / "sessions").glob("**/source-map.json"))
        for name in ("source-map.json", "meta.json"):
            path = entry / name
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source_record_sha256"] = digest
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def repo_fingerprint(self, repo: Path) -> dict[str, str]:
        return {
            path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(repo.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }

    def semantic_snapshot(self, memory_repo: Path) -> dict:
        entry = next(path.parent for path in (memory_repo / "sessions").glob("**/source-map.json"))
        source_map = json.loads((entry / "source-map.json").read_text(encoding="utf-8"))
        source_map.pop("source_anchor_version", None)
        source_map.pop("evidence_source_anchors", None)
        meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
        meta.pop("source_anchor_version", None)
        for field in ("reusable_fact_sources", "memory_candidate_sources", "explicit_memory_sources"):
            for row in meta.get(field) or []:
                if isinstance(row, dict):
                    row.pop("source_anchor_id", None)
        memory_rows = []
        for relative in [
            "index/memories.jsonl",
            "memories/global.jsonl",
            "memories/domains.jsonl",
            "memories/projects.jsonl",
            "memories/explicit.jsonl",
        ]:
            for row in jsonl_rows(memory_repo / relative):
                value = dict(row)
                value.pop("raw_refs", None)
                memory_rows.append((relative, value))
        return {
            "source_map": source_map,
            "meta": meta,
            "memory_rows": memory_rows,
            "summary": (entry / "summary.md").read_bytes(),
            "evidence": (entry / "evidence.md").read_bytes(),
        }

    def legacy_source_ref(self, memory_repo: Path, query: str) -> str:
        search = run(
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
        self.assertEqual(search.returncode, 0, search.stdout + search.stderr)
        package = json.loads(search.stdout)
        hit = next(hit for hit in package["hits"] if hit["answerability"]["status"] == "supported")
        return hit["source_refs"][0]["source_ref_id"]

    def test_legacy_upgrade_dry_run_is_aggregate_and_non_mutating(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, fact = self.build_legacy_archive(root)
            source = source_root / "legacy.jsonl"
            legacy_ref = self.legacy_source_ref(memory_repo, fact)

            resolver = run(
                [
                    sys.executable,
                    str(memory_repo / "tools/resolve_memory_source.py"),
                    fact,
                    "--repo",
                    str(memory_repo),
                    "--source-ref-id",
                    legacy_ref,
                    "--allow-source-root",
                    str(source_root),
                    "--authorize-source-preview",
                    "--preview-json",
                ],
                cwd=memory_repo,
            )
            self.assertEqual(json.loads(resolver.stdout)["reason"], "legacy_source_anchor_unavailable")
            before = self.repo_fingerprint(memory_repo)

            result = run(
                [
                    sys.executable,
                    str(UPGRADE_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-record",
                    str(source),
                    "--allow-source-root",
                    str(source_root),
                    "--dry-run",
                    "--report-json",
                ],
                cwd=memory_repo,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["report_kind"], "memory_source_anchor_upgrade_package")
            self.assertEqual(report["status"], "eligible", report)
            self.assertEqual(report["reason"], "legacy_upgrade_ready")
            self.assertGreater(report["metrics"]["changed_file_count"], 0)
            self.assertEqual(self.repo_fingerprint(memory_repo), before)
            combined = result.stdout + result.stderr
            self.assertNotIn(str(root), combined)
            self.assertNotIn(fact, combined)
            self.assertNotIn("source-map.json", combined)

    def test_apply_resolves_exact_event_preserves_semantics_and_replays_as_noop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, fact = self.build_legacy_archive(root)
            source = source_root / "legacy.jsonl"
            before = self.semantic_snapshot(memory_repo)

            apply_result = run(
                [
                    sys.executable,
                    str(UPGRADE_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-record",
                    str(source),
                    "--allow-source-root",
                    str(source_root),
                    "--apply",
                    "--report-json",
                ],
                cwd=memory_repo,
            )

            self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
            report = json.loads(apply_result.stdout)
            self.assertEqual(report["status"], "applied", report)
            self.assertTrue(report["validation"]["post_apply_audit_passed"])
            self.assertTrue(report["validation"]["post_apply_search_health_passed"])
            self.assertEqual(self.semantic_snapshot(memory_repo), before)
            source_ref = self.legacy_source_ref(memory_repo, fact)
            resolver = run(
                [
                    sys.executable,
                    str(memory_repo / "tools/resolve_memory_source.py"),
                    fact,
                    "--repo",
                    str(memory_repo),
                    "--source-ref-id",
                    source_ref,
                    "--allow-source-root",
                    str(source_root),
                    "--authorize-source-preview",
                    "--preview-json",
                ],
                cwd=memory_repo,
            )
            preview = json.loads(resolver.stdout)
            self.assertEqual(preview["status"], "resolved", preview)
            self.assertIn(fact, preview["preview"])

            replay = run(
                [
                    sys.executable,
                    str(UPGRADE_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--source-record",
                    str(source),
                    "--allow-source-root",
                    str(source_root),
                    "--apply",
                    "--report-json",
                ],
                cwd=memory_repo,
            )
            replay_report = json.loads(replay.stdout)
            self.assertEqual(replay_report["status"], "noop", replay_report)
            self.assertEqual(replay_report["metrics"]["changed_file_count"], 0)

    def test_apply_rejects_stale_target_fingerprint_without_writing(self):
        module = load_upgrade_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, _ = self.build_legacy_archive(root)
            plan = module.build_plan(
                memory_repo.resolve(),
                str(source_root / "legacy.jsonl"),
                str(source_root),
                allow_redacted_secrets=False,
            )
            self.assertIsNotNone(plan)
            target = plan.replacements[0].path
            target.write_bytes(target.read_bytes() + b"\n")
            changed = self.repo_fingerprint(memory_repo)

            with self.assertRaises(module.UpgradeBlocked) as raised:
                module.apply_upgrade_plan(plan)

            self.assertEqual(raised.exception.reason, "target_fingerprint_changed")
            self.assertEqual(self.repo_fingerprint(memory_repo), changed)

    def test_apply_rejects_changed_source_and_evidence_dependencies_without_writing(self):
        module = load_upgrade_module()
        for dependency, expected_reason in (
            ("source", "source_hash_mismatch"),
            ("evidence", "archive_dependency_changed"),
        ):
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                memory_repo, source_root, _ = self.build_legacy_archive(root)
                plan = module.build_plan(
                    memory_repo.resolve(),
                    str(source_root / "legacy.jsonl"),
                    str(source_root),
                    allow_redacted_secrets=False,
                )
                self.assertIsNotNone(plan)
                path = source_root / "legacy.jsonl"
                if dependency == "evidence":
                    path = next((memory_repo / "sessions").glob("**/evidence.md"))
                path.write_bytes(path.read_bytes() + b"\n")
                changed = self.repo_fingerprint(memory_repo)

                with self.assertRaises(module.UpgradeBlocked) as raised:
                    module.apply_upgrade_plan(plan)

                self.assertEqual(raised.exception.reason, expected_reason)
                self.assertEqual(self.repo_fingerprint(memory_repo), changed)

    def test_write_and_post_audit_failures_restore_exact_bytes(self):
        module = load_upgrade_module()
        for failure_kind in ("write", "audit", "search"):
            with self.subTest(failure_kind=failure_kind), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                memory_repo, source_root, _ = self.build_legacy_archive(root)
                plan = module.build_plan(
                    memory_repo.resolve(),
                    str(source_root / "legacy.jsonl"),
                    str(source_root),
                    allow_redacted_secrets=False,
                )
                self.assertIsNotNone(plan)
                before = self.repo_fingerprint(memory_repo)
                modes = {item.path: item.path.stat().st_mode & 0o777 for item in plan.replacements}
                kwargs = {}
                expected_reason = "post_apply_audit_failed"
                if failure_kind == "write":
                    calls = 0

                    def fail_second_replace(source, destination):
                        nonlocal calls
                        calls += 1
                        if calls == 2:
                            raise OSError("injected replacement failure")
                        os.replace(source, destination)

                    kwargs["replace_func"] = fail_second_replace
                    expected_reason = "transaction_write_failed"
                else:
                    if failure_kind == "audit":
                        kwargs["post_validator"] = lambda _repo: (False, True)
                    else:
                        kwargs["post_validator"] = lambda _repo: (True, False)
                        expected_reason = "post_apply_search_health_failed"

                with self.assertRaises(module.UpgradeBlocked) as raised:
                    module.apply_upgrade_plan(plan, **kwargs)

                self.assertEqual(raised.exception.reason, expected_reason)
                self.assertEqual(self.repo_fingerprint(memory_repo), before)
                self.assertEqual(
                    {item.path: item.path.stat().st_mode & 0o777 for item in plan.replacements},
                    modes,
                )

    def test_post_validation_refuses_symlinked_archive_tools_and_rolls_back(self):
        module = load_upgrade_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, _ = self.build_legacy_archive(root)
            plan = module.build_plan(
                memory_repo.resolve(),
                str(source_root / "legacy.jsonl"),
                str(source_root),
                allow_redacted_secrets=False,
            )
            self.assertIsNotNone(plan)
            target_bytes = {item.path: item.path.read_bytes() for item in plan.replacements}
            marker = root / "unsafe-tool-ran"
            outside = root / "outside-audit.py"
            outside.write_text(
                "from pathlib import Path\nPath(%r).write_text('unsafe')\n" % str(marker),
                encoding="utf-8",
            )
            audit = memory_repo / "tools/audit_memory_archive.py"
            audit.unlink()
            audit.symlink_to(outside)

            with self.assertRaises(module.UpgradeBlocked) as raised:
                module.apply_upgrade_plan(plan)

            self.assertEqual(raised.exception.reason, "post_apply_audit_failed")
            self.assertFalse(marker.exists())
            self.assertEqual(
                {item.path: item.path.read_bytes() for item in plan.replacements},
                target_bytes,
            )

    def test_missing_drift_escape_symlink_and_malformed_inputs_fail_closed(self):
        cases = (
            ("missing", "source_record_unavailable"),
            ("drift", "source_hash_mismatch"),
            ("root_escape", "source_root_escape"),
            ("symlink", "symlink_escape"),
            ("archive_symlink", "unsafe_archive_path"),
            ("memory_dir_symlink", "unsafe_archive_path"),
            ("memory_binding_mismatch", "memory_evidence_binding_missing"),
            ("malformed_source_map", "source_map_malformed"),
            ("malformed_jsonl", "source_jsonl_malformed"),
        )
        for case, expected_reason in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                memory_repo, source_root, _ = self.build_legacy_archive(root)
                source = source_root / "legacy.jsonl"
                allow_root = source_root
                if case == "missing":
                    source.unlink()
                elif case == "drift":
                    source.write_text(source.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
                elif case == "root_escape":
                    allow_root = root / "other"
                    allow_root.mkdir()
                elif case == "symlink":
                    linked = source_root / "linked.jsonl"
                    linked.symlink_to(source)
                    source = linked
                elif case == "archive_symlink":
                    source_map_path = next((memory_repo / "sessions").glob("**/source-map.json"))
                    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
                    linked_entry = memory_repo / "linked-entry"
                    linked_entry.symlink_to(source_map_path.parent, target_is_directory=True)
                    source_map["evidence_path"] = "linked-entry/evidence.md"
                    source_map_path.write_text(
                        json.dumps(source_map, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                elif case == "memory_dir_symlink":
                    memories = memory_repo / "memories"
                    real_memories = memory_repo / "real-memories"
                    memories.rename(real_memories)
                    memories.symlink_to(real_memories, target_is_directory=True)
                elif case == "memory_binding_mismatch":
                    index_path = memory_repo / "index/memories.jsonl"
                    rows = jsonl_rows(index_path)
                    selected = next(row for row in rows if row.get("raw_refs"))
                    selected["evidence_refs"] = []
                    write_jsonl(index_path, rows)
                elif case == "malformed_source_map":
                    source_map = next((memory_repo / "sessions").glob("**/source-map.json"))
                    source_map.write_text("{not-json\n", encoding="utf-8")
                elif case == "malformed_jsonl":
                    source.write_text(source.read_text(encoding="utf-8") + "{not-json\n", encoding="utf-8")
                    self.replace_archived_source_hash(memory_repo, source)

                _, report = self.upgrade_report(memory_repo, source, allow_root)

                self.assertEqual(report["status"], "blocked", report)
                self.assertEqual(report["reason"], expected_reason, report)

    def test_absent_and_ambiguous_quote_bindings_fail_closed(self):
        for case, expected_reason in (
            ("absent", "evidence_event_binding_missing"),
            ("ambiguous", "ambiguous_evidence_event_binding"),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                memory_repo, source_root, fact = self.build_legacy_archive(root)
                source = source_root / "legacy.jsonl"
                if case == "absent":
                    evidence = next((memory_repo / "sessions").glob("**/evidence.md"))
                    evidence.write_text(
                        evidence.read_text(encoding="utf-8").replace(fact, "Quote absent from every source event."),
                        encoding="utf-8",
                    )
                else:
                    source.write_text(
                        source.read_text(encoding="utf-8")
                        + json.dumps({"role": "assistant", "content": f"Reusable fact: {fact}"})
                        + "\n",
                        encoding="utf-8",
                    )
                    self.replace_archived_source_hash(memory_repo, source)

                _, report = self.upgrade_report(memory_repo, source, source_root)

                self.assertEqual(report["status"], "blocked", report)
                self.assertEqual(report["reason"], expected_reason, report)

    def test_secret_policy_requires_explicit_redacted_allowance_without_leak(self):
        secret = "ghp_" + "NEVERRENDER" * 3
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, _ = self.build_legacy_archive(root, secret_token=secret)
            source = source_root / "legacy.jsonl"

            blocked_result, blocked = self.upgrade_report(memory_repo, source, source_root)
            allowed_result, allowed = self.upgrade_report(
                memory_repo,
                source,
                source_root,
                "--allow-redacted-secrets",
            )

            self.assertEqual(blocked["reason"], "secret_policy_authorization_required", blocked)
            self.assertEqual(allowed["status"], "eligible", allowed)
            self.assertGreater(allowed["metrics"]["redaction_category_count"], 0)
            self.assertNotIn(secret, blocked_result.stdout + blocked_result.stderr)
            self.assertNotIn(secret, allowed_result.stdout + allowed_result.stderr)

    def test_aggregate_scan_is_bounded_read_only_and_path_free(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            memory_repo, source_root, fact = self.build_legacy_archive(root)
            before = self.repo_fingerprint(memory_repo)

            result = run(
                [
                    sys.executable,
                    str(UPGRADE_SCRIPT),
                    "--memory-repo",
                    str(memory_repo),
                    "--allow-source-root",
                    str(source_root),
                    "--dry-run",
                    "--scan-limit",
                    "1",
                    "--report-json",
                ],
                cwd=memory_repo,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "scanned", report)
            self.assertEqual(report["reason"], "aggregate_readiness_scan_complete")
            self.assertEqual(report["metrics"]["source_records_scanned"], 1)
            self.assertEqual(report["metrics"]["eligible_source_record_count"], 1, report)
            self.assertTrue(report["validation"]["aggregate_scan_bounded"])
            self.assertTrue(report["validation"]["read_only"])
            self.assertEqual(self.repo_fingerprint(memory_repo), before)
            combined = result.stdout + result.stderr
            self.assertNotIn(str(root), combined)
            self.assertNotIn(fact, combined)
            self.assertNotIn("source-map.json", combined)


if __name__ == "__main__":
    unittest.main()
