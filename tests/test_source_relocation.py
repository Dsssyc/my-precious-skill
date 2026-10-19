"""Synthetic migration regressions: durable retries, lineage and trusted locations."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path('templates/agent-memory-repo/tools/update_memory_archive.py').resolve()
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
            values = [json.loads(line) for line in raw.splitlines()]
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


if __name__ == '__main__':
    unittest.main()
