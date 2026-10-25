"""A collection snapshot must prove the original physical bytes and page graph."""
from dataclasses import replace
import hashlib
import json

import test_codex_append_snapshots as _append


class CodexAppendSnapshotSafetyTests(_append.AppendSnapshotFixture):
    def archive_files(self):
        return {path.relative_to(self.repo): path.read_bytes()
                for path in self.repo.rglob('*') if path.is_file()}

    def assert_collection_rejected(self, inventories, diagnostic=None):
        before = self.archive_files()
        with self.assertRaises(self.runner.SourceInventoryError) as raised:
            self.runner.combine_source_collection(inventories)
        if diagnostic is not None:
            self.assertEqual(str(raised.exception), diagnostic)
        self.assertEqual(self.archive_files(), before)

    def test_changed_old_prefix_rejects_append_snapshot(self):
        for added in (False, True):
            with self.subTest(added=added):
                _, child = self.chain(cross_root=True)
                inventories = self.inventories()
                original = child.read_bytes()
                self.assertIn(b'amber', original)
                child.write_bytes(original.replace(b'amber', b'umber'))
                if added:
                    self.append(child, 4)
                self.assert_collection_rejected(inventories, 'source_inventory_changed')
                child.unlink()
                for path in self.active.glob('*.jsonl'):
                    path.unlink()

    def test_truncated_snapshot_rejects_collection(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        child.write_bytes(child.read_bytes()[:-10])
        self.assert_collection_rejected(inventories, 'source_inventory_changed')
        self.assertFalse(self.metas())

    def test_forged_raw_hash_does_not_admit_changed_prefix(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        old = child.read_bytes()
        child.write_bytes(old.replace(b'amber', b'umber'))
        self.append(child, 4)
        forged_hash = hashlib.sha256(child.read_bytes()[:len(old)]).hexdigest()
        forged = []
        for inventory in inventories:
            forged.append(self.runner.SourceInventory([
                replace(row, sha256=forged_hash)
                if row.source_root / row.relative_path == child else row for row in inventory
            ], inventory.source_headers))
        self.assert_collection_rejected(forged, 'source_inventory_changed')

    def test_false_raw_hash_rejects_even_an_unchanged_appended_prefix(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        self.append(child, 4)
        forged = [self.runner.SourceInventory([
            replace(row, sha256='0' * 64) if row.source_root / row.relative_path == child else row
            for row in inventory], inventory.source_headers) for inventory in inventories]
        self.assert_collection_rejected(forged, 'source_inventory_changed')

    def test_forged_physical_descriptor_in_manifest_is_rejected(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        manifest = self.root / 'inventory-manifest.json'
        payload = self.runner.source_inventory_manifest_payload(
            self.runner.SourceInventory([row for rows in inventories for row in rows]))
        row = next(row for row in payload['records'] if row['relative_path'] == child.name)
        row['source_fragment']['physical_end_byte_offset'] += 1
        manifest.write_text(json.dumps(payload))
        manifest.chmod(0o600)
        loaded = self.runner.load_source_inventory_manifest(manifest)
        self.assert_collection_rejected([loaded])

    def test_forged_physical_descriptor_in_collection_is_rejected(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        forged = []
        for inventory in inventories:
            forged.append(self.runner.SourceInventory([
                replace(row, source_fragment={**row.source_fragment,
                    'physical_end_ordinal_exclusive': row.source_fragment['physical_end_ordinal_exclusive'] + 1})
                if row.source_root / row.relative_path == child else row for row in inventory
            ], inventory.source_headers))
        self.assert_collection_rejected(forged)

    def test_compressed_page_needs_exact_physical_fingerprint(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd unavailable')
        base, _ = self.chain(cross_root=True)
        compressed = base.with_suffix('.jsonl.zst')
        compressed.write_bytes(zstd.compress(base.read_bytes()))
        base.unlink()
        inventories = self.inventories()
        records = self.runner.combine_source_collection(inventories)
        page = next(row for row in records if row.source_root / row.relative_path == compressed)
        self.assertEqual(page.sha256, hashlib.sha256(compressed.read_bytes()).hexdigest())
        with compressed.open('ab') as handle:
            handle.write(zstd.compress(b'\n'))
        self.assert_collection_rejected(inventories, 'source_inventory_changed')

    def test_symlink_to_outside_source_root_cannot_supply_old_snapshot(self):
        _, child = self.chain(cross_root=True)
        inventories = self.inventories()
        outside = self.root / 'outside-source.jsonl'
        outside.write_bytes(child.read_bytes())
        self.append(outside, 4)
        child.unlink()
        child.symlink_to(outside)
        self.assert_collection_rejected(inventories, 'source_inventory_unsafe')

    def test_stale_and_forged_stdin_cannot_write_existing_archive(self):
        _, child = self.chain(cross_root=True)
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        before = {path.relative_to(self.repo): path.read_bytes()
                  for path in (self.repo / 'sessions').rglob('*') if path.is_file()}
        stale = json.loads(self.payload())
        self.append(child, 4)
        report = self.update(json.dumps(stale))
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertEqual({path.relative_to(self.repo): path.read_bytes()
                          for path in (self.repo / 'sessions').rglob('*') if path.is_file()}, before)
        forged = json.loads(json.dumps(stale))
        row = next(row for row in forged['records'] if row['relative_path'] == child.name)
        row['source_fragment']['physical_end_byte_offset'] -= 1
        report = self.update(json.dumps(forged), expected=2)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual({path.relative_to(self.repo): path.read_bytes()
                          for path in (self.repo / 'sessions').rglob('*') if path.is_file()}, before)


if __name__ == '__main__':
    import unittest
    unittest.main()
