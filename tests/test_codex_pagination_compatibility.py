"""Copied-fork and activation-policy regressions; all source records are synthetic."""
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess
import sys
import unittest

import test_codex_paginated_sources as _pagination


OWNER, BASE, CHILD = _pagination.OWNER, _pagination.BASE, _pagination.CHILD
OTHER = '44444444-4444-4444-8444-444444444444'
CUTOFF = datetime(2026, 7, 14, tzinfo=timezone.utc)


class CodexPaginationCompatibilityTests(_pagination.PaginationFixture):
    def copied_fork(self):
        path = self.active / f'rollout-2026-07-13T10-00-00-{OWNER}.jsonl'
        owner = {'id': OWNER, 'session_id': BASE, 'cwd': str(self.project), 'history_mode': 'paginated',
                 'forked_from_id': BASE, 'subagent_history_start_ordinal': 3}
        parent = {'id': BASE, 'session_id': BASE, 'cwd': str(self.project), 'history_mode': 'paginated'}
        rows = [
            {'type': 'session_meta', 'ordinal': 0, 'payload': owner},
            {'type': 'session_meta', 'ordinal': 1, 'payload': parent},
            {'ordinal': 2, 'role': 'assistant', 'content': 'Decision: retain copied cobalt context.'},
            {'ordinal': 3, 'role': 'assistant', 'content': 'Decision: retain child amber result.'},
        ]
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def old(self, path):
        stamp = datetime(2026, 7, 13, tzinfo=timezone.utc).timestamp()
        os.utime(path, (stamp, stamp))

    def cutoff_inventories(self, required=frozenset(), mappings=()):
        return [self.runner.build_source_inventory(root, ('*.jsonl',), 'codex-session',
                    discover_after=CUTOFF, required_identities=required, include_existing=root == self.active,
                    fragment_mappings=mappings)
                for root in (self.active, self.relocated)]

    def cutoff_collection(self, required=frozenset(), mappings=()):
        return self.runner.combine_source_collection(self.cutoff_inventories(required, mappings), fragment_mappings=mappings)

    def cutoff_chain(self):
        base, child = self.chain(cross_root=True)
        base = base.rename(self.relocated / base.name)
        child = child.rename(self.active / child.name)
        self.old(base)
        fresh = CUTOFF.timestamp() + 3600
        os.utime(child, (fresh, fresh))
        return base, child

    def test_copied_paginated_fork_keeps_first_owner_and_inherited_prefix(self):
        path = self.copied_fork()
        records = self.collection()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_identity, 'codex-session:' + OWNER)
        self.assertEqual(records[0].source_fragment['start_ordinal'], 0)
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 1)
        self.assertEqual(self.metas()[0]['source_record'], str(path))
        self.assertEqual(self.metas()[0]['source_identity'], 'codex-session:' + OWNER)

    def test_old_unreferenced_same_owner_branch_stays_header_only(self):
        base, child = self.cutoff_chain()
        branch = self.write_page(self.relocated / f'rollout-2026-07-13T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                 ['Decision: unrelated obsolete branch.'])
        self.old(branch)
        records = self.cutoff_collection()
        self.assertEqual({row.source_root / row.relative_path for row in records}, {base, child})

    def test_inactive_compressed_branch_body_is_not_materialized(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd unavailable')
        base, child = self.cutoff_chain()
        branch = self.write_page(self.relocated / f'rollout-2026-07-13T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                 ['Decision: unrelated obsolete branch.'])
        compressed = branch.with_suffix('.jsonl.zst')
        compressed.write_bytes(zstd.compress(branch.read_bytes() + b'not a JSONL record\n'))
        branch.unlink()
        self.old(compressed)
        records = self.cutoff_collection()
        self.assertEqual({row.source_root / row.relative_path for row in records}, {base, child})

    def test_enrolled_identity_without_physical_mapping_still_rejects_ambiguity(self):
        self.cutoff_chain()
        branch = self.write_page(self.relocated / f'rollout-2026-07-13T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                 ['Decision: competing enrolled history.'])
        self.old(branch)
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_pagination_ambiguous'):
            self.cutoff_collection(frozenset({'codex-session:' + OWNER}))
        self.assertFalse(self.metas())

    def test_selected_new_branch_and_referenced_duplicate_both_fail_closed(self):
        base, _ = self.cutoff_chain()
        competing = self.write_page(self.relocated / f'rollout-2026-07-15T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                    ['Decision: competing newly selected branch.'])
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_pagination_ambiguous'):
            self.cutoff_collection()
        competing.unlink()
        duplicate = self.relocated / f'rollout-2026-07-12T10-00-00-{OWNER}_{BASE}.jsonl'
        duplicate.write_bytes(base.read_bytes())
        self.old(duplicate)
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_pagination_ambiguous'):
            self.cutoff_collection()
        self.assertFalse(self.metas())

    def test_transitive_old_bases_are_selected_across_roots(self):
        base, middle = self.cutoff_chain()
        middle = middle.rename(self.relocated / middle.name)
        prefix_end = len(middle.read_bytes())
        with middle.open('ab') as handle:
            handle.write(json.dumps({'ordinal': 4, 'role': 'assistant',
                                     'content': 'Decision: obsolete crimson middle tail.'}).encode() + b'\n')
        self.old(middle)
        leaf = self.write_page(self.active / f'rollout-2026-07-15T10-00-00-{OWNER}_{OTHER}.jsonl', 4,
                               ['Decision: keep golden current leaf.'],
                               {'thread_id': CHILD, 'end_ordinal_exclusive': 4, 'end_byte_offset': prefix_end})
        records = self.cutoff_collection()
        by_path = {row.source_root / row.relative_path: row for row in records}
        self.assertEqual(set(by_path), {base, middle, leaf})
        self.assertEqual(by_path[base].source_fragment['end_ordinal_exclusive'], 2)
        self.assertEqual(by_path[middle].source_fragment['end_ordinal_exclusive'], 4)
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 3)
        self.assertNotIn('crimson', json.dumps(self.metas()))
        self.assertNotIn('vermilion', json.dumps(self.metas()))

    def test_v5_header_manifest_roundtrip_preserves_only_needed_activation(self):
        base, child = self.cutoff_chain()
        branch = self.write_page(self.relocated / f'rollout-2026-07-13T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                 ['Decision: unrelated old branch.'])
        self.old(branch)
        inventories = self.cutoff_inventories()
        loaded = []
        for number, inventory in enumerate(inventories):
            manifest = self.root / f'root-{number}.json'
            self.runner.write_source_inventory_manifest(manifest, inventory)
            value = self.runner.load_source_inventory_manifest(manifest)
            self.assertEqual(value.source_headers, inventory.source_headers)
            loaded.append(value)
        self.assertEqual(json.loads((self.root / 'root-1.json').read_text())['report_version'], 5)
        records = self.runner.combine_source_collection(loaded)
        self.assertEqual({row.source_root / row.relative_path for row in records}, {base, child})
        self.assertEqual(json.loads(self.runner.source_inventory_payload(records))['report_version'], 4)

    def test_known_physical_pages_refine_enrollment_and_keep_missing_successor_guard(self):
        from source_record_io import archived_fragment_mappings
        base, child = self.chain(cross_root=True)
        self.update(self.payload())
        self.old(child)
        mappings = archived_fragment_mappings(self.repo, lambda repo, path: path.resolve().is_relative_to(repo))
        branch = self.write_page(self.relocated / f'rollout-2026-07-13T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                 ['Decision: unrelated old same-owner branch.'])
        self.old(branch)
        required = frozenset({'codex-session:' + OWNER})
        records = self.cutoff_collection(required, mappings)
        self.assertEqual({row.source_root / row.relative_path for row in records}, {base, child})
        self.assertEqual(next(row for row in records if row.relative_path == base.name).source_fragment['end_ordinal_exclusive'], 2)
        # Known successors are also dependencies without relying on owner-wide enrollment.
        self.assertEqual(len(self.cutoff_collection(mappings=mappings)), 2)
        prior = self.metas()
        child.unlink()
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_pagination_reference_missing'):
            self.cutoff_collection(required, mappings)
        self.assertEqual(self.metas(), prior)

    def test_changed_dependency_header_is_revalidated_before_activation(self):
        base, _ = self.cutoff_chain()
        inventories = self.cutoff_inventories()
        rows = [json.loads(line) for line in base.read_text().splitlines()]
        rows[0]['payload'].update(id=OTHER, session_id=OTHER)
        base.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_inventory_changed'):
            self.runner.combine_source_collection(inventories)
        self.assertFalse(self.metas())

    def test_renamed_compressed_old_dependency_needs_verified_mapping(self):
        from source_record_io import archived_fragment_mappings
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd unavailable')
        base, child = self.cutoff_chain()
        self.update(self.runner.source_inventory_payload(self.cutoff_collection()))
        mappings = archived_fragment_mappings(self.repo, lambda repo, path: path.resolve().is_relative_to(repo))
        renamed = self.relocated / 'renamed-old-base.jsonl.zst'
        renamed.write_bytes(zstd.compress(base.read_bytes()))
        base.unlink()
        self.old(renamed)
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_pagination_reference_missing'):
            self.cutoff_collection()
        records = self.cutoff_collection(mappings=mappings)
        self.assertEqual({row.source_root / row.relative_path for row in records}, {renamed, child})
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(renamed), str(child)})

    def test_legacy_exact_raw_mapping_can_activate_renamed_old_base(self):
        from source_record_io import archived_fragment_mappings
        base, child = self.cutoff_chain()
        # A legacy filename's UUID can locate a physical rollout without naming
        # its logical metadata owner. Only exact content proves the upgrade.
        base = base.rename(self.relocated / f'rollout-2026-07-13T10-00-00-{BASE}.jsonl')
        self.update(self.runner.source_inventory_payload(self.cutoff_collection()))
        for path in self.repo.glob('sessions/**/meta.json'):
            value = json.loads(path.read_text())
            value.pop('source_fragment')
            value.pop('source_identity')
            path.write_text(json.dumps(value))
        mappings = archived_fragment_mappings(self.repo, lambda repo, path: path.resolve().is_relative_to(repo))
        renamed = base.rename(self.relocated / 'legacy-renamed-base.jsonl')
        unrelated = self.write_page(self.relocated / 'unknown-old-branch.jsonl', 0,
                                     ['Decision: unrelated legacy candidate.'])
        with unrelated.open('ab') as handle:
            handle.write(b'unrelated invalid body must not be parsed\n')
        self.old(unrelated)
        records = self.cutoff_collection(frozenset({'codex-session:' + OWNER}), mappings)
        self.assertEqual({row.source_root / row.relative_path for row in records}, {renamed, child})
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 2)
        self.assertEqual({row['source_identity'] for row in self.metas()}, {'codex-session:' + OWNER})
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(renamed), str(child)})

    def test_isolated_runner_preserves_header_dependencies_and_ignores_inactive_branch(self):
        base, child = self.cutoff_chain()
        branch = self.write_page(self.relocated / f'rollout-2026-07-13T10-00-00-{OWNER}_{OTHER}.jsonl', 0,
                                 ['Decision: unrelated obsolete history.'])
        self.old(branch)
        shutil.copytree(_pagination.TOOLS, self.repo / 'tools')
        config = self.repo / 'config'
        config.mkdir()
        (config / 'projects.jsonl').write_text(json.dumps({'project_path': str(self.project),
            'source_dir': str(self.active), 'enabled': True}) + '\n')
        (config / 'source_locations.jsonl').write_text(json.dumps({'source_dir': str(self.active),
            'relocation_dirs': [str(self.relocated)], 'identity_adapter': 'codex-session',
            'discover_after': CUTOFF.isoformat(), 'enabled': True}) + '\n')
        result = subprocess.run([sys.executable, str(_pagination.TOOLS / 'run_memory_updates.py'),
            '--memory-repo', str(self.repo), '--source-dir', str(self.active), '--report-json'],
            text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report['metrics']['inventory_worker_count'], 2)
        self.assertEqual(report['metrics']['projects_updated_count'], 1)
        self.assertEqual(report['metrics']['records_deferred_count'], 0)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(base), str(child)})


if __name__ == '__main__':
    unittest.main()
