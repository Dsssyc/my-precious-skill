"""Fail-closed regressions for physical, cross-owner Codex reference forks."""
import copy
from dataclasses import replace
import hashlib
import json

import test_codex_reference_forks as _forks
from source_record_io import SourceRecordDecodeError, resolve_source_fragments


class CodexReferenceForkSafetyTests(_forks.ReferenceForkFixture):
    def rewrite_header(self, path, change):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        change(rows)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def archive_files(self):
        return {path.relative_to(self.repo): path.read_bytes()
                for path in self.repo.rglob('*') if path.is_file()}

    def assert_rejected_without_archive(self):
        with self.assertRaises(self.runner.SourceInventoryError):
            self.collection()
        self.assertEqual(self.update(expected=2)['status'], 'blocked')
        self.assertFalse(self.metas())

    def test_foreign_reference_requires_matching_canonical_fork_owner(self):
        for parent_id in (None, _forks.OTHER_CHILD):
            with self.subTest(parent_id=parent_id):
                _, child, _ = self.fork()
                def change(rows):
                    if parent_id is None:
                        rows[0]['payload'].pop('forked_from_id')
                    else:
                        rows[0]['payload']['forked_from_id'] = parent_id
                self.rewrite_header(child, change)
                self.assert_rejected_without_archive()
                child.unlink()
                for path in self.relocated.glob('*.jsonl'):
                    path.unlink()

    def test_foreign_prefix_must_be_inside_parent_current_own_view(self):
        parent, child, _ = self.fork(parent_continuation=True)
        # The parent still contains ordinal 3 physically, but its own linear
        # continuation has frozen its current view at ordinal 3.
        def change(rows):
            rows[0]['payload']['history_base'] = self.reference(parent, 4)
            for row in rows:
                row['ordinal'] += 2
        self.rewrite_header(child, change)
        self.assert_rejected_without_archive()

    def test_parent_owner_is_verified_from_its_own_metadata(self):
        parent, _, _ = self.fork()
        self.rewrite_header(parent, lambda rows: rows[0]['payload'].update(
            id=_forks.OTHER_CHILD, session_id=_forks.OTHER_CHILD))
        self.assert_rejected_without_archive()

    def test_foreign_reference_rejects_inexact_byte_boundary(self):
        parent, child, _ = self.fork()
        self.rewrite_header(child, lambda rows: rows[0]['payload']['history_base'].update(
            end_byte_offset=self.reference(parent)['end_byte_offset'] + 1))
        self.assert_rejected_without_archive()

    def test_foreign_reference_rejects_inexact_ordinal_boundary(self):
        _, child, _ = self.fork()
        def change(rows):
            rows[0]['payload']['history_base']['end_ordinal_exclusive'] = 3
            for row in rows:
                row['ordinal'] += 1
        self.rewrite_header(child, change)
        self.assert_rejected_without_archive()

    def test_physically_missing_parent_defers_stale_inventory_and_blocks_discovery(self):
        parent, _, _ = self.fork()
        payload = self.payload()
        parent.unlink()
        with self.assertRaises(self.runner.SourceInventoryError):
            self.collection()
        report = self.update(payload)
        self.assertEqual(report['status'], 'deferred')
        self.assertFalse(self.metas())

    def test_cross_root_duplicate_parent_locator_is_ambiguous(self):
        parent, _, _ = self.fork()
        (self.active / parent.name).write_bytes(parent.read_bytes())
        self.assert_rejected_without_archive()

    def test_foreign_physical_cycle_is_rejected_by_resolver(self):
        parent, child, _ = self.fork()
        by_path = {row.source_root / row.relative_path: row for row in self.collection()}
        parent_fragment = copy.deepcopy(by_path[parent].source_fragment)
        child_fragment = copy.deepcopy(by_path[child].source_fragment)
        parent_fragment.update(
            history_base={'thread_id': _forks.CHILD, 'end_ordinal_exclusive': 2,
                          'end_byte_offset': 1},
            start_ordinal=2,
            forked_from_id=_forks.CHILD_OWNER,
        )
        with self.assertRaisesRegex(SourceRecordDecodeError, '^source_pagination_cycle$'):
            resolve_source_fragments([
                ('codex-session:' + _forks.PARENT, parent_fragment),
                ('codex-session:' + _forks.CHILD_OWNER, child_fragment),
            ])

    def test_forged_stdin_descriptors_do_not_archive(self):
        parent, child, _ = self.fork()
        original = json.loads(self.payload())
        for name, change in (
            ('parent_descriptor', lambda rows: rows[parent.name]['source_fragment'].update(
                forked_from_id=_forks.CHILD_OWNER)),
            ('child_fork', lambda rows: rows[child.name]['source_fragment'].update(
                forked_from_id=_forks.OTHER_CHILD)),
        ):
            with self.subTest(name=name):
                payload = copy.deepcopy(original)
                change({row['relative_path']: row for row in payload['records']})
                self.assertEqual(self.update(json.dumps(payload), expected=2)['status'], 'blocked')
                self.assertFalse(self.metas())
        payload = copy.deepcopy(original)
        next(row for row in payload['records'] if row['relative_path'] == parent.name)['sha256'] = '0' * 64
        self.assertEqual(self.update(json.dumps(payload))['status'], 'deferred')
        self.assertFalse(self.metas())

    def test_rejected_fork_does_not_change_existing_archive(self):
        _, child, _ = self.fork()
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        before = self.archive_files()
        self.rewrite_header(child, lambda rows: rows[0]['payload'].update(
            forked_from_id=_forks.OTHER_CHILD))
        with self.assertRaises(self.runner.SourceInventoryError):
            self.collection()
        self.assertEqual(self.update(expected=2)['status'], 'blocked')
        self.assertEqual(self.archive_files(), before)

    def test_invalid_dependency_bytes_have_bounded_inventory_diagnostic(self):
        parent, _, _ = self.fork()
        records = self.collection()
        parent.write_bytes(parent.read_bytes().replace(b'cobalt', b'\xffcobalt'))
        forged = [replace(row, sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
                          size=parent.stat().st_size, mtime_ns=parent.stat().st_mtime_ns)
                  if row.source_root / row.relative_path == parent else row for row in records]
        with self.assertRaisesRegex(self.runner.SourceInventoryError, '^source_pagination_invalid$'):
            self.runner.combine_source_collection([self.runner.SourceInventory(forged)])
        self.assertFalse(self.metas())


if __name__ == '__main__':
    import unittest
    unittest.main()
