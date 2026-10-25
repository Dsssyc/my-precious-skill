"""Synthetic safety and protocol checks for Codex physical pages."""

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
import unittest

import test_codex_paginated_sources as _pagination
from source_record_io import resolve_source_fragments

BASE, CHILD, OWNER = _pagination.BASE, _pagination.CHILD, _pagination.OWNER

try:
    from compression import zstd
except ImportError:
    zstd = None


class CodexPaginationSafetyTests(_pagination.PaginationFixture):

    def assert_inventory_error(self, reason):
        with self.assertRaisesRegex(self.runner.SourceInventoryError, '^' + reason + '$'):
            self.collection()

    def rewrite(self, path, change):
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        change(rows)
        path.write_bytes(b''.join(json.dumps(row).encode() + b'\n' for row in rows))

    def test_extra_same_owner_copy_and_changed_copy_are_ambiguous(self):
        base, child = self.chain(cross_root=True)
        copied = self.relocated / 'unlisted-copy.jsonl'
        copied.write_bytes(base.read_bytes())
        self.assert_inventory_error('source_pagination_ambiguous')
        copied.unlink()
        copied.write_bytes(child.read_bytes())
        self.rewrite(copied, lambda rows: rows[1].update(content='Different facts under the same physical header.'))
        self.assert_inventory_error('source_pagination_ambiguous')

    def test_same_locator_with_different_header_is_ambiguous(self):
        self.chain()
        competing = self.relocated / f'rollout-2026-07-14T11-00-00-{OWNER}_{CHILD}.jsonl'
        self.write_page(competing, 2, ['Competing child branch.'],
                        {'thread_id': BASE, 'end_ordinal_exclusive': 2, 'end_byte_offset': 1})
        self.assert_inventory_error('source_pagination_ambiguous')

    def test_physical_locator_cannot_be_reused_by_another_logical_owner(self):
        self.chain()
        competing = self.relocated / f'rollout-2026-07-14T11-00-00-{CHILD}_{BASE}.jsonl'
        self.write_page(competing, 0, ['Decision: use a competing physical source.'])
        self.rewrite(competing, lambda rows: rows[0]['payload'].update(id=CHILD, session_id=CHILD))
        self.assert_inventory_error('source_pagination_ambiguous')

    def test_missing_base_and_wrong_owner_are_rejected(self):
        base, child = self.chain(cross_root=True)
        base.unlink()
        self.assert_inventory_error('source_pagination_reference_missing')
        base, child = self.chain(cross_root=True)
        self.rewrite(base, lambda rows: rows[0]['payload'].update(id=BASE, session_id=BASE))
        self.assert_inventory_error('source_pagination_invalid')

    def test_wrong_session_root_is_rejected(self):
        _, child = self.chain()
        self.rewrite(child, lambda rows: rows[0]['payload'].update(session_id=CHILD))
        self.assert_inventory_error('source_pagination_boundary_invalid')

    def test_start_gap_and_noninteger_ordinals_are_rejected(self):
        for mutation in (
            lambda rows: rows[0]['payload']['history_base'].update(end_ordinal_exclusive=3),
            lambda rows: rows[1].update(ordinal=4),
            lambda rows: rows[1].update(ordinal=2.0),
            lambda rows: rows[1].update(ordinal=True),
        ):
            with self.subTest(mutation=mutation):
                base, child = self.chain()
                self.rewrite(child, mutation)
                with self.assertRaisesRegex(self.runner.SourceInventoryError, '^source_pagination_invalid$'):
                    self.runner.build_source_inventory(self.active, ('*.jsonl',), 'codex-session')
                base.unlink()
                child.unlink()

    def test_byte_boundary_must_be_end_of_matching_ordinal(self):
        for boundary in (1, None):
            with self.subTest(boundary=boundary):
                base, child = self.chain()
                value = boundary if boundary is not None else len(base.read_bytes().splitlines(keepends=True)[0])
                self.rewrite(child, lambda rows: rows[0]['payload']['history_base'].update(end_byte_offset=value))
                self.assert_inventory_error('source_pagination_boundary_invalid')
                base.unlink()
                child.unlink()

    def test_physical_cycle_and_competing_children_are_rejected(self):
        base, child = self.chain()
        by_path = {row.source_root / row.relative_path: row.source_fragment for row in self.collection()}
        a, b = dict(by_path[base]), dict(by_path[child])
        a.update(history_base={'thread_id': b['rollout_id'], 'end_ordinal_exclusive': 1,
                               'end_byte_offset': 1}, start_ordinal=1)
        b.update(history_base={'thread_id': a['rollout_id'], 'end_ordinal_exclusive': 2,
                               'end_byte_offset': 1}, start_ordinal=2)
        with self.assertRaisesRegex(ValueError, '^source_pagination_cycle$'):
            resolve_source_fragments([('codex-session:' + OWNER, a), ('codex-session:' + OWNER, b)])

        another = self.relocated / f'rollout-2026-07-14T12-00-00-{OWNER}_44444444-4444-4444-8444-444444444444.jsonl'
        self.write_page(another, 2, ['Second branch.'],
                        {'thread_id': BASE, 'end_ordinal_exclusive': 2,
                         'end_byte_offset': sum(len(line) for line in base.read_bytes().splitlines(keepends=True)[:2])})
        self.assert_inventory_error('source_pagination_ambiguous')

    @unittest.skipIf(zstd is None, 'compression.zstd unavailable')
    def test_zstd_inventory_hash_tracks_compressed_bytes(self):
        base, _ = self.chain()
        compressed = self.relocated / (base.name + '.zst')
        compressed.write_bytes(zstd.compress(base.read_bytes()))
        base.unlink()
        records = self.collection()
        row = next(row for row in records if row.source_root / row.relative_path == compressed)
        self.assertEqual(row.sha256, hashlib.sha256(compressed.read_bytes()).hexdigest())
        self.assertNotEqual(row.sha256, row.source_fragment['content_sha256'])

    def test_v4_manifest_and_ipc_preserve_cross_root_dependency(self):
        base, child = self.chain(cross_root=True)
        records = self.collection()
        payload = self.runner.source_inventory_manifest_payload(records)
        self.assertEqual(payload['report_version'], 4)
        self.assertEqual({row['source_root'] for row in payload['records']},
                         {str(self.active), str(self.relocated)})
        manifest = self.root / 'inventory.json'
        manifest.write_text(json.dumps(payload))
        manifest.chmod(0o600)
        loaded = self.runner.load_source_inventory_manifest(manifest)
        self.assertEqual(loaded, records)
        self.assertEqual(self.runner.combine_source_collection([loaded]), records)
        ipc = json.loads(self.runner.source_inventory_payload(loaded))
        self.assertEqual(ipc['report_version'], 4)
        self.assertEqual({row['source_fragment']['rollout_id'] for row in ipc['records']}, {BASE, CHILD})
        self.assertEqual({row['source_root'] for row in ipc['records']}, {str(base.parent), str(child.parent)})

    def test_manifest_versions_one_to_three_still_load(self):
        plain = self.runner.SourceInventoryRecord('plain.jsonl', 'a' * 64, 1, 1,
            '2026-07-13T10:00:00Z', ())
        extended = replace(plain, source_root=self.active, source_identity='codex-session:' + OWNER)
        cases = (
            ([plain], 1),
            ([extended], 2),
            (self.runner.SourceInventory([extended],
                (self.runner.SourceIdentityHeader(self.active, 'old.jsonl', 'codex-session:' + OWNER),)), 3),
        )
        for records, version in cases:
            with self.subTest(version=version):
                payload = self.runner.source_inventory_manifest_payload(records)
                self.assertEqual(payload['report_version'], version)
                manifest = self.root / f'inventory-{version}.json'
                manifest.write_text(json.dumps(payload))
                manifest.chmod(0o600)
                self.assertEqual(list(self.runner.load_source_inventory_manifest(manifest)), list(records))

    def test_discover_after_keeps_old_paginated_base_across_roots(self):
        base, child = self.chain(cross_root=True)
        base = base.rename(self.relocated / base.name)
        child = child.rename(self.active / child.name)
        old = datetime(2026, 7, 13, tzinfo=timezone.utc).timestamp()
        os.utime(base, (old, old))
        cutoff = datetime(2026, 7, 14, tzinfo=timezone.utc)
        records = self.runner.combine_source_collection([
            self.runner.build_source_inventory(root, ('*.jsonl',), 'codex-session',
                discover_after=cutoff, include_existing=root == self.active)
            for root in (self.active, self.relocated)
        ])
        self.assertEqual({row.source_root / row.relative_path for row in records}, {base, child})

    def test_worker_diagnostic_does_not_echo_private_path_or_id(self):
        _, child = self.chain()
        child.unlink()
        private = self.active / 'private-token-owner-source.jsonl'
        self.write_page(private, 2, ['Sensitive synthetic content.'],
                        {'thread_id': BASE, 'end_ordinal_exclusive': 2, 'end_byte_offset': 1})
        self.rewrite(private, lambda rows: rows[1].update(ordinal=4))
        result = subprocess.run([sys.executable, self.runner.__file__, '--source-dir', str(self.active),
            '--source-identity-adapter', 'codex-session', '--inventory-worker-manifest',
            str(self.root / 'worker-manifest.json')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        diagnostic = result.stdout + result.stderr
        self.assertLess(len(diagnostic), 256)
        for secret in (str(self.root), private.name, OWNER, BASE, 'Sensitive synthetic content.'):
            self.assertNotIn(secret, diagnostic)


if __name__ == '__main__':
    unittest.main()
