"""Collection snapshots tolerate proven raw-prefix appends; target writes still defer."""
import hashlib
import json
import unittest
from unittest.mock import patch

import test_codex_reference_forks as _forks


class AppendSnapshotFixture(_forks.ReferenceForkFixture):
    def inventories(self):
        return [self.runner.build_source_inventory(root, ('*.jsonl',), 'codex-session')
                for root in (self.active, self.relocated)]

    def append(self, path, ordinal, fact='Decision: retain silver appended progress.'):
        with path.open('a') as handle:
            handle.write(json.dumps({'ordinal': ordinal, 'role': 'assistant', 'content': fact}) + '\n')


class CodexAppendSnapshotTests(AppendSnapshotFixture):
    def test_append_between_inventory_and_collection_keeps_snapshot_then_defers_owner(self):
        base, child = self.chain(cross_root=True)
        inventories = self.inventories()
        original = next(row for rows in inventories for row in rows if row.source_root / row.relative_path == child)
        self.append(child, 4)
        records = self.runner.combine_source_collection(inventories)
        snapshot = next(row for row in records if row.source_root / row.relative_path == child)
        self.assertEqual(snapshot, original)
        self.assertEqual(snapshot.source_fragment['physical_end_ordinal_exclusive'], 4)
        self.assertNotEqual(snapshot.sha256, hashlib.sha256(child.read_bytes()).hexdigest())
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        self.assertFalse(self.metas())
        pending = self.repo / 'index/deferred_sources.jsonl'
        self.assertIn(str(base), pending.read_text())
        self.assertIn(str(child), pending.read_text())
        fresh = self.runner.combine_source_collection(self.inventories())
        self.assertEqual(self.update(self.runner.source_inventory_payload(fresh))['metrics']['records_processed_count'], 2)
        self.assertFalse(pending.exists())
        summaries = '\n'.join(path.read_text() for path in self.repo.glob('sessions/**/*.md'))
        self.assertIn('silver appended progress', summaries)
        self.assertNotIn('vermilion', summaries)

    def test_append_before_second_collection_read_still_uses_same_snapshot(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        expected = next(row for rows in inventories for row in rows if row.source_root / row.relative_path == child)
        original = self.runner.read_source_snapshot_bytes
        child_reads = 0
        def read(path, size, sha256):
            nonlocal child_reads
            if path == child:
                child_reads += 1
                if child_reads == 2:
                    self.append(child, 4)
            return original(path, size, sha256)
        with patch.object(self.runner, 'read_source_snapshot_bytes', read):
            records = self.runner.combine_source_collection(inventories)
        self.assertEqual(child_reads, 2)
        self.assertEqual(next(row for row in records if row.relative_path == child.name), expected)
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertFalse(self.metas())

    def test_appended_owner_defers_both_own_pages_and_foreign_children(self):
        parent, child, continuation = self.fork(parent_continuation=True, two_children=True)
        inventories = self.inventories()
        self.append(continuation, 5)
        records = self.runner.combine_source_collection(inventories)
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_deferred_count'], 4)
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertFalse(self.metas())
        pending = self.repo / 'index/deferred_sources.jsonl'
        rows = [json.loads(line) for line in pending.read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        for path in (parent, child, continuation):
            self.assertIn(str(path), pending.read_text())
        fresh = self.runner.combine_source_collection(self.inventories())
        self.assertEqual(self.update(self.runner.source_inventory_payload(fresh))['metrics']['records_processed_count'], 4)
        self.assertFalse(pending.exists())

    def test_appended_other_project_parent_preserves_only_child_scope_pending(self):
        parent, child, continuation = self.fork(parent_continuation=True, different_project=True, two_children=True)
        inventories = self.inventories()
        self.append(continuation, 5)
        records = self.target_records(self.runner.combine_source_collection(inventories))
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        pending = self.repo / 'index/deferred_sources.jsonl'
        self.assertIn(str(child), pending.read_text())
        self.assertNotIn(str(parent), pending.read_text())
        self.assertNotIn(str(continuation), pending.read_text())
        self.assertFalse(self.metas())
        fresh = self.target_records(self.runner.combine_source_collection(self.inventories()))
        self.assertEqual(self.update(self.runner.source_inventory_payload(fresh))['metrics']['records_processed_count'], 2)
        self.assertFalse(pending.exists())
        self.assertNotIn(str(parent), {row['source_record'] for row in self.metas()})

    def test_unfinished_append_cannot_become_archive_content(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        with child.open('a') as handle:
            handle.write('{"ordinal":4,')
        records = self.runner.combine_source_collection(inventories)
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['status'], 'deferred')
        self.assertFalse(self.metas())
        with self.assertRaises(self.runner.SourceInventoryError):
            self.inventories()
        with child.open('a') as handle:
            handle.write('"role":"assistant","content":"Decision: completed silver append."}\n')
        fresh = self.runner.combine_source_collection(self.inventories())
        self.assertEqual(self.update(self.runner.source_inventory_payload(fresh))['metrics']['records_processed_count'], 2)


if __name__ == '__main__':
    unittest.main()
