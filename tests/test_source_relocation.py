"""Synthetic migration regressions: durable retries, lineage and trusted locations."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import shutil
import os
import unittest
from pathlib import Path


SCRIPT = Path('templates/agent-memory-repo/tools/update_memory_archive.py').resolve()
try:
    from compression import zstd
except ImportError:
    zstd = None

IDENTITY_A = '11111111-1111-4111-8111-111111111111'
IDENTITY_B = '22222222-2222-4222-8222-222222222222'
IDENTITY_C = '33333333-3333-4333-8333-333333333333'


class SourceRelocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / 'memory'
        self.active = self.root / 'active'
        self.archived = self.root / 'archived'
        self.project = self.root / 'project'
        for path in (self.repo / 'index', self.repo / 'sessions', self.active, self.archived, self.project):
            path.mkdir(parents=True)
        self.queue = self.repo / 'index/deferred_sources.jsonl'

    def source(self, path, identity=IDENTITY_A, stamp='2026-07-13T10:00:00Z'):
        rows = [
            {'type': 'session_meta', 'payload': {'id': identity, 'cwd': str(self.project)}},
            {'timestamp': stamp, 'cwd': str(self.project), 'role': 'user',
             'content': 'Decision: retain durable migration support after source relocation.'},
        ]
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def inventory(self, paths, version=3):
        rows = []
        for path in paths:
            raw = path.read_bytes()
            logical = zstd.decompress(raw) if path.name.endswith(".jsonl.zst") else raw
            values = [json.loads(line) for line in logical.split(b"\n") if line.strip()]
            root = next(root for root in (self.active, self.archived) if path.is_relative_to(root))
            row = {'relative_path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(),
                   'size': len(raw), 'mtime_ns': path.stat().st_mtime_ns,
                   'source_updated_at': max(value['timestamp'] for value in values if 'timestamp' in value)}
            if version == 3:
                row.update(source_root=str(root), source_identity='codex-session:' + values[0]['payload']['id'])
            rows.append(row)
        return {'report_kind': 'memory_source_inventory', 'report_version': version, 'records': rows}

    def run_update(self, payload, adapter=True, expected=0):
        command = [sys.executable, str(SCRIPT), '--memory-repo', str(self.repo), '--source-dir', str(self.active),
                   '--project-path', str(self.project), '--require-project-metadata', '--source-inventory-stdin',
                   '--defer-global-rebuild', '--report-json']
        if adapter:
            command += ['--source-relocation-dir', str(self.archived), '--source-identity-adapter', 'codex-session']
        result = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)
        return json.loads(result.stdout)

    def metas(self):
        return [json.loads(path.read_text()) for path in self.repo.glob('sessions/**/meta.json')]

    def pending(self, paths, identities=None):
        self.queue.write_text(''.join(json.dumps(dict(archive_scope=str(self.project), source_partition=str(self.project),
            source_record=str(path), **({'source_identity': identities[str(path)]} if identities else {}))) + '\n' for path in paths))

    def test_legacy_missing_paths_reselected_after_move_and_rename_below_high_water(self):
        old_a = self.source(self.active / f'rollout-2026-07-13T10-00-00-{IDENTITY_A}.jsonl')
        old_b = self.source(self.active / f'rollout-2026-07-13T10-00-00-{IDENTITY_B}.jsonl', IDENTITY_B)
        self.run_update(self.inventory([old_b], version=2), adapter=False)
        with old_b.open('a') as handle:
            handle.write(json.dumps({'timestamp': '2026-07-13T10:30:00Z', 'role': 'assistant',
                                     'content': 'Fixed: preserve the newer source content during migration.'}) + '\n')
        self.pending([old_a, old_b])
        newer = self.source(self.active / 'newer.jsonl', IDENTITY_C, '2026-07-14T12:00:00Z')
        self.run_update(self.inventory([newer]))
        moved_a = old_a.rename(self.archived / 'renamed-session.jsonl')
        moved_b = old_b.rename(self.archived / old_b.name)
        report = self.run_update(self.inventory([moved_a, moved_b, newer]))
        self.assertEqual(report['metrics']['records_processed_count'], 2)
        self.assertFalse(self.queue.exists())
        metas = self.metas()
        self.assertEqual(len(metas), 3)
        for path, identity in ((moved_a, IDENTITY_A), (moved_b, IDENTITY_B)):
            rows = [row for row in metas if row['source_identity'] == 'codex-session:' + identity]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['source_record'], str(path))
            self.assertEqual(rows[0]['source_record_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report['metrics']['entries_removed_count'], 1)

    def test_future_deferred_arbitrary_filename_survives_repeated_rename(self):
        original = self.source(self.active / 'arbitrary.jsonl')
        stale = self.inventory([original])
        with original.open('a') as handle:
            handle.write('{}\n')
        report = self.run_update(stale)
        self.assertEqual(report['metrics']['records_deferred_count'], 1)
        self.assertEqual(json.loads(self.queue.read_text())['source_identity'], 'codex-session:' + IDENTITY_A)
        newer = self.source(self.active / 'newer.jsonl', IDENTITY_C, '2026-07-14T12:00:00Z')
        self.run_update(self.inventory([newer]))
        moved = original.rename(self.archived / 'renamed.jsonl')
        stale = self.inventory([moved, newer])
        moved = moved.rename(self.archived / 'renamed-again.jsonl')
        report = self.run_update(stale)
        self.assertEqual(report['metrics']['records_deferred_count'], 1)
        self.assertEqual(len(self.queue.read_text().splitlines()), 1)
        report = self.run_update(self.inventory([moved, newer]))
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertFalse(self.queue.exists())
        self.assertEqual(len(self.metas()), 2)

    def test_archived_identity_refreshes_location_even_with_unchanged_bytes(self):
        original = self.source(self.active / 'named.jsonl')
        self.run_update(self.inventory([original]))
        moved = original.rename(self.archived / 'renamed.jsonl')
        report = self.run_update(self.inventory([moved]))
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertEqual(report['metrics']['entries_removed_count'], 1)
        self.assertEqual([row['source_record'] for row in self.metas()], [str(moved)])
        source_map = next(self.repo.glob('sessions/**/source-map.json'))
        self.assertEqual(json.loads(source_map.read_text())['source_record'], str(moved))
        self.assertEqual(self.run_update(self.inventory([moved]))['metrics']['records_processed_count'], 0)

    def test_new_identity_older_than_high_water_is_not_omitted(self):
        newer = self.source(self.active / 'newer.jsonl', IDENTITY_C, '2026-07-14T12:00:00Z')
        self.run_update(self.inventory([newer]))
        older = self.source(self.archived / 'older.jsonl')
        self.assertEqual(self.run_update(self.inventory([older, newer]))['metrics']['records_processed_count'], 1)

    def test_duplicate_identity_fails_closed_without_clearing_pending(self):
        first = self.source(self.active / 'first.jsonl')
        second = self.source(self.archived / 'second.jsonl')
        self.pending([first])
        before = self.queue.read_bytes()
        report = self.run_update(self.inventory([first, second]), expected=2)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(self.queue.read_bytes(), before)
        self.assertFalse(self.metas())

    def test_untrusted_inventory_root_fails_closed(self):
        source = self.source(self.active / 'first.jsonl')
        payload = self.inventory([source])
        payload['records'][0]['source_root'] = str(self.root)
        report = self.run_update(payload, expected=2)
        self.assertEqual(report['status'], 'blocked')
        self.assertFalse(self.metas())

    def test_identity_is_validated_against_embedded_session_metadata(self):
        source = self.source(self.active / 'first.jsonl')
        payload = self.inventory([source])
        payload['records'][0]['source_identity'] = 'codex-session:' + IDENTITY_B
        self.assertEqual(self.run_update(payload, expected=2)['status'], 'blocked')
        self.assertFalse(self.metas())

    def test_reused_pending_path_cannot_clear_another_identity(self):
        source = self.source(self.active / 'reused.jsonl', IDENTITY_B)
        self.pending([source], {str(source): 'codex-session:' + IDENTITY_A})
        before = self.queue.read_bytes()
        self.assertEqual(self.run_update(self.inventory([source]), expected=2)['status'], 'blocked')
        self.assertEqual(self.queue.read_bytes(), before)
        self.assertFalse(self.metas())

    def test_changed_migrated_source_preserves_prior_entry_until_stable_retry(self):
        original = self.source(self.active / 'original.jsonl')
        self.run_update(self.inventory([original]))
        before = self.metas()
        moved = original.rename(self.archived / 'moved.jsonl')
        stale = self.inventory([moved])
        with moved.open('a') as handle:
            handle.write('{}\n')
        self.assertEqual(self.run_update(stale)['metrics']['records_deferred_count'], 1)
        self.assertEqual(self.metas(), before)
        self.assertEqual(self.run_update(self.inventory([moved]))['metrics']['records_processed_count'], 1)
        self.assertFalse(self.queue.exists())
        self.assertEqual([row['source_record'] for row in self.metas()], [str(moved)])

    def test_empty_inventory_identity_cannot_hide_embedded_session(self):
        source = self.source(self.active / 'first.jsonl')
        payload = self.inventory([source])
        payload['records'][0]['source_identity'] = ''
        self.assertEqual(self.run_update(payload, expected=2)['status'], 'blocked')
        self.assertFalse(self.metas())

    @unittest.skipIf(zstd is None, 'stdlib zstd compression fixture requires Python 3.14')
    def test_compressed_migration_uses_physical_hash_and_logical_event_anchors(self):
        original = self.source(self.active / f'rollout-2026-07-13T10-00-00-{IDENTITY_A}.jsonl')
        self.run_update(self.inventory([original], version=2), adapter=False)
        self.pending([original])
        raw = b"\r" + original.read_bytes()
        moved = self.archived / 'compressed-renamed.jsonl.zst'
        moved.write_bytes(zstd.compress(raw))
        original.unlink()
        self.assertEqual(self.run_update(self.inventory([moved]))['metrics']['records_processed_count'], 1)
        self.assertFalse(self.queue.exists())
        self.assertEqual(len(self.metas()), 1)
        physical_hash = hashlib.sha256(moved.read_bytes()).hexdigest()
        self.assertEqual(self.metas()[0]['source_record_sha256'], physical_hash)
        spec = importlib.util.spec_from_file_location('migration_resolver', SCRIPT.with_name('resolve_memory_source.py'))
        resolver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resolver)
        value, reason, actual_hash = resolver.read_jsonl_value_and_hash(moved, 2)
        self.assertEqual(reason, '')
        self.assertEqual(actual_hash, physical_hash)
        self.assertEqual(value, json.loads(raw.split(b"\n")[1]))

    def test_forked_source_uses_owner_identity_with_declared_parent_metadata(self):
        source = self.source(self.active / 'forked.jsonl')
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        rows[0]['payload']['forked_from_id'] = IDENTITY_B
        rows.append({'type': 'session_meta', 'payload': {'id': IDENTITY_B}})
        source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(self.run_update(self.inventory([source]))['metrics']['records_processed_count'], 1)
        self.assertEqual(self.metas()[0]['source_identity'], 'codex-session:' + IDENTITY_A)

    def test_unrelated_embedded_header_cannot_claim_fork_ancestry(self):
        source = self.source(self.active / 'conflicting.jsonl')
        with source.open('a') as handle:
            handle.write(json.dumps({'type': 'session_meta', 'payload': {'id': IDENTITY_B}}) + '\n')
        self.assertEqual(self.run_update(self.inventory([source]), expected=2)['status'], 'blocked')
        self.assertFalse(self.metas())

    def test_direct_entry_checks_cross_project_duplicate_before_any_mutation(self):
        first = self.source(self.active / 'first.jsonl')
        second = self.source(self.archived / 'other-project.jsonl')
        rows = [json.loads(line) for line in second.read_text().splitlines()]
        for row in rows:
            if 'cwd' in row:
                row['cwd'] = str(self.root / 'foreign-project')
            if 'payload' in row:
                row['payload']['cwd'] = str(self.root / 'foreign-project')
        second.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.pending([first])
        before = self.queue.read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), '--memory-repo', str(self.repo),
            '--source-dir', str(self.active), '--source-relocation-dir', str(self.archived),
            '--source-identity-adapter', 'codex-session', '--project-path', str(self.project),
            '--require-project-metadata', '--report-json'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['status'], 'blocked')
        self.assertEqual(self.queue.read_bytes(), before)
        self.assertFalse(self.metas())

    def test_json_metadata_uses_the_generic_format_without_a_jsonl_identity(self):
        path = self.active / 'metadata.json'
        value = {'type': 'session_meta', 'timestamp': '2026-07-13T10:00:00Z',
                 'payload': {'id': IDENTITY_A, 'cwd': str(self.project)}}
        path.write_text(json.dumps(value))
        raw = path.read_bytes()
        payload = {'report_kind': 'memory_source_inventory', 'report_version': 3, 'records': [{
            'relative_path': path.name, 'source_root': str(self.active), 'source_identity': '',
            'source_updated_at': value['timestamp'], 'sha256': hashlib.sha256(raw).hexdigest(),
            'size': len(raw), 'mtime_ns': path.stat().st_mtime_ns}]}
        self.assertEqual(self.run_update(payload)['status'], 'updated')

    def configure_runner(self, projects, *, discover_after=None):
        shutil.copytree(SCRIPT.parent.parent, self.repo, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (self.repo / 'config/projects.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in projects))
        location = dict(source_dir=str(self.active), relocation_dirs=[str(self.archived)],
                        identity_adapter='codex-session', enabled=True)
        if discover_after:
            location['discover_after'] = discover_after
        (self.repo / 'config/source_locations.jsonl').write_text(json.dumps(location) + '\n')

    def runner(self, *, source_dir=None, blocked=False):
        result = subprocess.run([sys.executable, str(self.repo / 'tools/run_memory_updates.py'),
            '--memory-repo', str(self.repo), '--source-dir', str(source_dir or self.active), '--report-json'],
            text=True, capture_output=True)
        if blocked:
            self.assertNotEqual(result.returncode, 0)
        else:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assert_identity_location_conflict(self, *, discover_after=None):
        spec = importlib.util.spec_from_file_location('collection_conflict_under_test', SCRIPT.with_name('run_memory_updates.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cutoff = module.parse_source_timestamp(discover_after) if discover_after else None
        inventories = [module.build_source_inventory(root, module.DEFAULT_PATTERNS, 'codex-session',
            discover_after=cutoff, include_existing=root == self.active) for root in (self.active, self.archived)]
        with self.assertRaisesRegex(module.SourceInventoryError, 'source_inventory_identity_conflict'):
            module.combine_source_collection(inventories)

    @unittest.skipIf(zstd is None, 'stdlib zstd fixture requires Python 3.14')
    def test_cold_start_checks_old_compressed_copies_before_enrollment(self):
        first = self.source(self.active / 'current.jsonl')
        copy = self.archived / 'historical-copy.jsonl.zst'
        copy.write_bytes(zstd.compress(first.read_bytes()))
        os.utime(copy, (1783944000, 1783944000))
        self.configure_runner([{'project_path': str(self.project), 'source_dir': str(self.active), 'enabled': True}],
                              discover_after='2026-07-14T00:00:00Z')
        self.pending([self.active / f'rollout-2026-07-13T10-00-00-{IDENTITY_C}.jsonl'])
        before = self.queue.read_bytes()
        registry = self.repo / 'config/projects.jsonl'
        before_registry = registry.read_bytes()
        self.assert_identity_location_conflict(discover_after='2026-07-14T00:00:00Z')
        report = self.runner(blocked=True)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['reason'], 'source_inventory_invalid')
        self.assertEqual(self.queue.read_bytes(), before)
        self.assertEqual(registry.read_bytes(), before_registry)
        self.assertFalse((self.repo / 'index/source_identities.jsonl').exists())
        self.assertFalse(self.metas())

    def test_secondary_only_start_validates_the_primary_collection(self):
        self.source(self.active / 'first.jsonl')
        self.source(self.archived / 'copy.jsonl')
        self.configure_runner([{'project_path': str(self.project), 'source_dir': str(self.archived), 'enabled': True}])
        registry = self.repo / 'config/projects.jsonl'
        before = registry.read_bytes()
        self.assert_identity_location_conflict()
        report = self.runner(source_dir=self.archived, blocked=True)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['reason'], 'source_inventory_invalid')
        self.assertEqual(registry.read_bytes(), before)
        self.assertFalse((self.repo / 'index/source_identities.jsonl').exists())
        self.assertFalse(self.metas())

    def test_secondary_root_registration_reuses_the_collection_inventory(self):
        self.source(self.active / 'first.jsonl')
        second = self.source(self.archived / 'second.jsonl', IDENTITY_B)
        other = self.root / 'other-project'
        other.mkdir()
        second.write_text(second.read_text().replace(str(self.project), str(other)))
        self.configure_runner([{'project_path': str(self.project), 'source_dir': str(self.active), 'enabled': True},
                               {'project_path': str(other), 'source_dir': str(self.archived), 'enabled': True}])
        report = self.runner()
        self.assertEqual(report['metrics']['inventory_worker_count'], 2)
        self.assertEqual(len(self.metas()), 2)

    def test_unchanged_legacy_source_is_enrolled_before_a_later_move(self):
        original = self.source(self.active / f'rollout-2026-07-13T10-00-00-{IDENTITY_A}.jsonl')
        os.utime(original, (1783944000, 1783944000))
        self.run_update(self.inventory([original], version=2), adapter=False)
        self.configure_runner([{'project_path': str(self.project), 'source_dir': str(self.active), 'enabled': True}],
                              discover_after='2026-07-14T00:00:00Z')
        self.runner()
        registry = self.repo / 'index/source_identities.jsonl'
        self.assertEqual(json.loads(registry.read_text())['source_identity'], 'codex-session:' + IDENTITY_A)
        moved = original.rename(self.archived / 'older-renamed.jsonl')
        self.runner()
        self.assertEqual([row['source_record'] for row in self.metas()], [str(moved)])
        self.assertEqual(self.metas()[0]['source_identity'], 'codex-session:' + IDENTITY_A)

    @unittest.skipIf(zstd is None, 'stdlib zstd fixture requires Python 3.14')
    def test_enrollment_selects_legacy_pending_and_future_unknown_moves(self):
        pending_path = self.active / f'rollout-2026-07-13T10-00-00-{IDENTITY_A}.jsonl'
        pending = self.source(self.archived / 'renamed.jsonl')
        unrelated = self.source(self.archived / 'historical.jsonl', IDENTITY_B)
        with unrelated.open('a') as handle:
            handle.write(json.dumps({'role': 'assistant', 'content': 'x' * 10000}) + '\n')
        future = self.source(self.archived / 'new-moved.jsonl', IDENTITY_C)
        compressed = []
        for path in (pending, unrelated, future):
            target = path.with_suffix('.jsonl.zst')
            target.write_bytes(zstd.compress(path.read_bytes()))
            path.unlink()
            compressed.append(target)
        for path in compressed[:2]:
            os.utime(path, (1783944000, 1783944000))
        self.configure_runner([{'project_path': str(self.project), 'source_dir': str(self.active), 'enabled': True}],
                              discover_after='2026-07-14T00:00:00Z')
        self.pending([pending_path])
        codec = self.repo / 'tools/source_record_io.py'
        codec.write_text(codec.read_text().replace('        return decoded', '        if len(decoded) > 4096:\n            raise SourceRecordDecodeError("unselected_history_materialized")\n        return decoded'))
        report = self.runner()
        self.assertEqual(report['metrics']['records_deferred_count'], 0)
        self.assertFalse(self.queue.exists())
        self.assertEqual({row['source_identity'] for row in self.metas()},
                         {'codex-session:' + IDENTITY_A, 'codex-session:' + IDENTITY_C})

    def test_source_symlink_cannot_escape_declared_roots(self):
        source = self.source(self.active / 'first.jsonl')
        payload = self.inventory([source])
        outside = source.rename(self.root / 'outside.jsonl')
        source.symlink_to(outside)
        self.assertEqual(self.run_update(payload, expected=2)['status'], 'blocked')
        self.assertFalse(self.metas())


if __name__ == '__main__':
    unittest.main()
