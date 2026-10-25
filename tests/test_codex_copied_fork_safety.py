"""Synthetic regressions for self-contained copied Codex fork pages."""
import hashlib
import importlib.util
import json

from test_codex_paginated_sources import BASE, CHILD, OWNER, PaginationFixture, TOOLS


GRANDPARENT = '55555555-5555-4555-8555-555555555555'
FOREIGN = '66666666-6666-4666-8666-666666666666'
EXTERNAL = '77777777-7777-4777-8777-777777777777'


class CodexCopiedForkSafetyTests(PaginationFixture):
    def copied_rows(self):
        """The child's entire inherited prefix is physically in this file."""
        owner = {'id': OWNER, 'session_id': CHILD, 'cwd': str(self.project),
                 'history_mode': 'paginated', 'forked_from_id': BASE,
                 'subagent_history_start_ordinal': 4}
        parent = {'id': BASE, 'session_id': BASE, 'cwd': str(self.project),
                  'history_mode': 'paginated', 'forked_from_id': GRANDPARENT,
                  'subagent_history_start_ordinal': 3,
                  'history_base': {'thread_id': EXTERNAL, 'end_ordinal_exclusive': 1,
                                   'end_byte_offset': 1}}
        grandparent = {'id': GRANDPARENT, 'session_id': GRANDPARENT,
                       'cwd': str(self.project), 'history_mode': 'paginated'}
        return [
            {'type': 'session_meta', 'ordinal': 0, 'payload': owner},
            {'type': 'session_meta', 'ordinal': 1, 'payload': parent},
            {'type': 'session_meta', 'ordinal': 2, 'payload': grandparent},
            {'ordinal': 3, 'role': 'assistant', 'content': 'Decision: keep inherited cobalt context.'},
            {'ordinal': 4, 'role': 'assistant', 'content': 'Decision: use amber child result.'},
        ]

    def write_rows(self, rows, *, filename=None):
        path = self.active / (filename or f'rollout-2026-07-13T10-00-00-{OWNER}.jsonl')
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def assert_rejected(self, rows, diagnostic):
        self.write_rows(rows)
        with self.assertRaisesRegex(self.runner.SourceInventoryError, '^' + diagnostic + '$'):
            self.collection()
        report = self.update(expected=2)
        self.assertEqual(report['status'], 'blocked')
        self.assertFalse(self.metas())

    def test_nested_copied_ancestors_preserve_canonical_owner_root_and_active_fragment(self):
        path = self.write_rows(self.copied_rows())
        records = self.collection()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source_identity, 'codex-session:' + OWNER)
        self.assertEqual(record.source_fragment['session_id'], CHILD)
        self.assertIsNone(record.source_fragment['history_base'])
        self.assertEqual((record.source_fragment['start_ordinal'],
                          record.source_fragment['end_ordinal_exclusive']), (0, 5))
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        meta = self.metas()[0]
        self.assertEqual(meta['source_record'], str(path))
        self.assertEqual(meta['source_identity'], 'codex-session:' + OWNER)
        self.assertEqual(meta['source_fragment']['session_id'], CHILD)
        self.assertIsNone(meta['source_fragment']['history_base'])
        self.assertEqual(self.update()['metrics']['records_processed_count'], 0)

    def test_direct_entry_archives_same_nested_copied_fork(self):
        path = self.write_rows(self.copied_rows())
        self.assertEqual(self.update()['metrics']['records_processed_count'], 1)
        meta = self.metas()[0]
        self.assertEqual(meta['source_record'], str(path))
        self.assertEqual(meta['source_identity'], 'codex-session:' + OWNER)
        self.assertEqual(meta['source_fragment']['session_id'], CHILD)
        self.assertIsNone(meta['source_fragment']['history_base'])

    def test_ancestor_copy_boundary_stays_in_its_original_coordinate_system(self):
        rows = self.copied_rows()
        # Parent ordinal 0 becomes child ordinal 1. Its original own-history
        # boundary 2 therefore corresponds to child ordinal 3, not ordinal 2.
        rows[1]['payload']['subagent_history_start_ordinal'] = 2
        self.write_rows(rows)
        self.assertEqual(len(self.collection()), 1)

    def test_positive_copied_prefix_requires_its_immediate_parent_header(self):
        rows = self.copied_rows()
        for value in rows[1:3]:
            value.clear()
        rows[1].update(ordinal=1, role='assistant', content='Copied-looking message without parent metadata.')
        rows[2].update(ordinal=2, role='assistant', content='Another copied-looking message.')
        self.assert_rejected(rows, 'source_pagination_invalid')

    def test_undeclared_foreign_header_cannot_replace_canonical_owner(self):
        rows = self.copied_rows()
        rows[2]['payload']['id'] = FOREIGN
        self.assert_rejected(rows, 'source_identity_conflict')

    def test_copied_headers_require_owner_fork_declaration_and_boundary(self):
        for missing in ('forked_from_id', 'subagent_history_start_ordinal'):
            with self.subTest(missing=missing):
                rows = self.copied_rows()
                rows[0]['payload'].pop(missing)
                self.assert_rejected(rows, 'source_identity_conflict' if missing == 'forked_from_id'
                                     else 'source_pagination_invalid')

    def test_header_at_or_beyond_own_child_boundary_is_rejected(self):
        for boundary in (1, 2):
            with self.subTest(boundary=boundary):
                rows = self.copied_rows()
                rows[0]['payload']['subagent_history_start_ordinal'] = boundary
                self.assert_rejected(rows, 'source_pagination_invalid')

    def test_incomplete_and_malformed_child_boundaries_are_rejected(self):
        for boundary in (None, '4', -1, True, 6):
            with self.subTest(boundary=boundary):
                rows = self.copied_rows()
                rows[0]['payload']['subagent_history_start_ordinal'] = boundary
                self.assert_rejected(rows, 'source_pagination_invalid')

    def test_ancestor_cycles_conflicts_and_repeated_owner_are_rejected(self):
        mutations = {
            'cycle': lambda rows: rows[2]['payload'].update(forked_from_id=OWNER),
            'conflict': lambda rows: rows[1]['payload'].update(forked_from_id=FOREIGN),
            'repeated_owner': lambda rows: rows[2]['payload'].update(id=OWNER),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                rows = self.copied_rows()
                mutate(rows)
                self.assert_rejected(rows, 'source_identity_conflict' if name in ('cycle', 'conflict')
                                     else 'source_pagination_invalid')

    def test_repeated_declared_ancestor_headers_keep_existing_identity_contract(self):
        rows = self.copied_rows()
        rows.insert(3, json.loads(json.dumps(rows[1])))
        rows[0]['payload']['subagent_history_start_ordinal'] = 5
        for ordinal, value in enumerate(rows):
            value['ordinal'] = ordinal
        self.write_rows(rows)
        records = self.collection()
        self.assertEqual(records[0].source_identity, 'codex-session:' + OWNER)
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 1)

    def test_ordinary_legacy_fork_header_remains_accepted(self):
        rows = [{'type': 'session_meta', 'payload': {'id': OWNER, 'session_id': BASE,
                 'forked_from_id': BASE, 'cwd': str(self.project)}},
                {'type': 'session_meta', 'payload': {'id': BASE, 'session_id': BASE,
                 'cwd': str(self.project)}},
                {'role': 'assistant', 'content': 'Decision: keep legacy cobalt context.'}]
        self.write_rows(rows)
        records = self.collection()
        self.assertEqual(records[0].source_identity, 'codex-session:' + OWNER)
        self.assertIsNone(records[0].source_fragment)
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 1)

    def test_legacy_owner_does_not_inherit_pagination_mode_from_copied_parent(self):
        rows = self.copied_rows()
        rows[0]['payload']['history_mode'] = 'legacy'
        for value in rows:
            value.pop('ordinal')
        self.write_rows(rows)
        records = self.collection()
        self.assertEqual(records[0].source_identity, 'codex-session:' + OWNER)
        self.assertIsNone(records[0].source_fragment)

    def test_compressed_copied_fork_uses_raw_hash_and_local_child_anchor(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd unavailable')
        path = self.write_rows(self.copied_rows())
        compressed = self.relocated / 'renamed-copied-fork.jsonl.zst'
        compressed.write_bytes(zstd.compress(path.read_bytes()))
        path.unlink()
        report = self.update()
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        meta = self.metas()[0]
        self.assertEqual(meta['source_record'], str(compressed))
        self.assertEqual(meta['source_record_sha256'], hashlib.sha256(compressed.read_bytes()).hexdigest())
        self.assertNotEqual(meta['source_record_sha256'], meta['source_fragment']['content_sha256'])
        mapping = json.loads((self.repo / meta['source_map_path']).read_text())
        anchors = mapping['evidence_source_anchors']
        self.assertTrue(anchors)
        spec = importlib.util.spec_from_file_location('copied_fork_resolver', TOOLS / 'resolve_memory_source.py')
        resolver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resolver)
        for anchor in anchors:
            value, reason, raw_hash = resolver.read_jsonl_value_and_hash(compressed, anchor['line_number'])
            self.assertEqual(reason, '')
            self.assertEqual(raw_hash, meta['source_record_sha256'])
            self.assertEqual(value['ordinal'] + 1, anchor['line_number'])
            self.assertIn(value['ordinal'], (3, 4))


if __name__ == '__main__':
    import unittest
    unittest.main()
