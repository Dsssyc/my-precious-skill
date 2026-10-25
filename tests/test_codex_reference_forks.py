"""Declared reference forks use verified physical dependencies, not owner aliases."""
from datetime import datetime, timezone
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_codex_paginated_sources as _pagination


PARENT = _pagination.OWNER
BASE = _pagination.BASE
CHILD = _pagination.CHILD
CHILD_OWNER = '44444444-4444-4444-8444-444444444444'
OTHER_CHILD = '55555555-5555-4555-8555-555555555555'
OTHER_PAGE = '66666666-6666-4666-8666-666666666666'
PARENT_NEXT = '77777777-7777-4777-8777-777777777777'


class ReferenceForkFixture(_pagination.PaginationFixture):
    def updater(self):
        spec = importlib.util.spec_from_file_location('reference_fork_updater', _pagination.TOOLS / 'update_memory_archive.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def target_records(self, records):
        return self.runner.inventory_records_for_target(records, self.project, require_project_metadata=True)

    def page(self, owner, locator, facts, *, start=0, base=None, parent=None, root=None, project=None):
        path = (root or self.active) / f'rollout-2026-07-13T10-00-00-{owner}_{locator}.jsonl'
        payload = {'id': owner, 'session_id': owner, 'history_mode': 'paginated',
                   'cwd': str(project or self.project), 'timestamp': '2026-07-13T10:00:00Z'}
        if base is not None:
            payload['history_base'] = base
        if parent is not None:
            payload['forked_from_id'] = parent
        values = [{'type': 'session_meta', 'ordinal': start, 'payload': payload}]
        values.extend({'ordinal': start + i, 'timestamp': '2026-07-13T10:00:00Z',
                       'role': 'assistant', 'content': fact} for i, fact in enumerate(facts, 1))
        path.write_text(''.join(json.dumps(value) + '\n' for value in values))
        return path

    def reference(self, path, count=2):
        return {'thread_id': BASE, 'end_ordinal_exclusive': count,
                'end_byte_offset': sum(len(line) for line in path.read_bytes().splitlines(keepends=True)[:count])}

    def fork(self, *, parent_continuation=False, different_project=False, two_children=False):
        parent_project = self.root / 'parent-project' if different_project else self.project
        parent_project.mkdir(exist_ok=True)
        parent = self.page(PARENT, BASE, ['Decision: preserve cobalt parent context.',
                                        'Decision: retain emerald parent-only progress.',
                                        'Decision: obsolete vermilion parent tail.'],
                           root=self.relocated, project=parent_project)
        child = self.page(CHILD_OWNER, CHILD, ['Decision: retain amber child result.'],
                          start=2, base=self.reference(parent), parent=PARENT)
        continuation = None
        if parent_continuation:
            continuation = self.page(PARENT, PARENT_NEXT, ['Decision: retain golden parent continuation.'],
                                     start=3, base=self.reference(parent, 3), root=self.relocated,
                                     project=parent_project)
        if two_children:
            self.page(OTHER_CHILD, OTHER_PAGE, ['Decision: retain silver sibling fork.'],
                      start=2, base=self.reference(parent), parent=PARENT)
        return parent, child, continuation


class CodexReferenceForkTests(ReferenceForkFixture):
    def test_declared_cross_owner_fork_keeps_parent_own_view(self):
        parent, child, continuation = self.fork(parent_continuation=True, two_children=True)
        records = self.collection()
        by_path = {row.source_root / row.relative_path: row for row in records}
        self.assertEqual(len(records), 4)
        self.assertEqual(by_path[parent].source_fragment['end_ordinal_exclusive'], 3)
        self.assertEqual(by_path[continuation].source_fragment['start_ordinal'], 3)
        self.assertEqual(by_path[child].source_identity, 'codex-session:' + CHILD_OWNER)
        self.assertEqual(by_path[child].source_fragment['forked_from_id'], PARENT)
        self.assertEqual(by_path[parent].sha256, hashlib.sha256(parent.read_bytes()).hexdigest())
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_processed_count'], 4)
        summaries = '\n'.join(path.read_text() for path in self.repo.glob('sessions/**/*.md'))
        for fact in ('cobalt parent', 'emerald parent', 'golden parent', 'amber child', 'silver sibling'):
            self.assertIn(fact, summaries)
        self.assertNotIn('vermilion', summaries)

    def test_old_cross_project_parent_and_own_continuation_reach_target_only_as_dependencies(self):
        parent, child, continuation = self.fork(parent_continuation=True, different_project=True)
        cutoff = datetime(2026, 7, 14, tzinfo=timezone.utc)
        for path in (parent, continuation):
            os.utime(path, (cutoff.timestamp() - 3600, cutoff.timestamp() - 3600))
        inventories = [self.runner.build_source_inventory(root, ('*.jsonl',), 'codex-session',
                       discover_after=cutoff, include_existing=root == self.active)
                       for root in (self.active, self.relocated)]
        self.assertEqual(sum(map(len, inventories)), 1)
        records = self.runner.combine_source_collection(inventories)
        selected = self.target_records(records)
        self.assertEqual({row.source_root / row.relative_path for row in selected}, {parent, child, continuation})
        report = self.update(self.runner.source_inventory_payload(selected))
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(child)})
        summaries = '\n'.join(path.read_text() for path in self.repo.glob('sessions/**/*.md'))
        self.assertIn('amber child', summaries)
        self.assertNotIn('cobalt parent', summaries)
        self.assertNotIn('golden parent', summaries)
        self.assertEqual(self.update()['metrics']['records_processed_count'], 0)

    def test_parent_child_replacement_and_pending_are_independent(self):
        parent, child, continuation = self.fork(parent_continuation=True, different_project=True)
        payload = self.runner.source_inventory_payload(self.target_records(self.collection()))
        limited = self.update(payload, extra=('--max-records', '0'))
        self.assertEqual(limited['metrics']['records_deferred_count'], 1)
        pending = self.repo / 'index/deferred_sources.jsonl'
        self.assertIn(str(child), pending.read_text())
        report = self.update(extra=('--project-path', str(self.root / 'parent-project')))
        self.assertEqual(report['metrics']['records_processed_count'], 2)
        self.assertIn(str(child), pending.read_text())
        self.assertEqual(self.update(payload)['metrics']['records_processed_count'], 1)
        before = {row['source_record']: row['source_record_sha256'] for row in self.metas()}
        with child.open('a') as handle:
            handle.write(json.dumps({'ordinal': 4, 'role': 'assistant',
                                     'content': 'Decision: retain updated violet child result.'}) + '\n')
        self.assertEqual(self.update()['metrics']['records_processed_count'], 1)
        after = {row['source_record']: row['source_record_sha256'] for row in self.metas()}
        self.assertEqual(set(after), set(before))
        self.assertEqual(after[str(parent)], before[str(parent)])
        self.assertEqual(after[str(continuation)], before[str(continuation)])
        self.assertNotEqual(after[str(child)], before[str(child)])

    def test_changed_foreign_dependency_preserves_child_pending_and_retries(self):
        parent, child, _ = self.fork(different_project=True)
        payload = self.runner.source_inventory_payload(self.target_records(self.collection()))
        self.update(payload, extra=('--max-records', '0'))
        with parent.open('a') as handle:
            handle.write(json.dumps({'ordinal': 4, 'role': 'assistant',
                                     'content': 'Decision: additional parent-only progress.'}) + '\n')
        report = self.update(payload)
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertFalse(self.metas())
        pending = self.repo / 'index/deferred_sources.jsonl'
        self.assertIn(str(child), pending.read_text())
        self.assertNotIn(str(parent), pending.read_text())
        self.assertEqual(self.update()['metrics']['records_processed_count'], 1)
        self.assertNotIn(str(child), pending.read_text() if pending.exists() else '')

    def test_dependency_changed_during_preparation_defers_all_child_pages_before_writes(self):
        parent, child, _ = self.fork(different_project=True)
        grandchild = self.page(CHILD_OWNER, OTHER_PAGE, ['Decision: retain second child page.'],
                              start=4, base={'thread_id': CHILD, 'end_ordinal_exclusive': 4,
                                            'end_byte_offset': len(child.read_bytes())}, parent=PARENT)
        payload = self.runner.source_inventory_payload(self.target_records(self.collection()))
        module = self.updater()
        original = module.prepare_inventory_record
        changed = False
        def prepare(*args, **kwargs):
            nonlocal changed
            prepared = original(*args, **kwargs)
            if not changed:
                changed = True
                with parent.open('a') as handle:
                    handle.write(json.dumps({'ordinal': 4, 'role': 'assistant',
                                             'content': 'Decision: changed dependency during preparation.'}) + '\n')
            return prepared
        arguments = ['update_memory_archive.py', '--memory-repo', str(self.repo),
                     '--source-dir', str(self.active), '--source-relocation-dir', str(self.relocated),
                     '--source-identity-adapter', 'codex-session', '--project-path', str(self.project),
                     '--require-project-metadata', '--source-inventory-stdin', '--report-json']
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', arguments), patch.object(sys, 'stdin', io.StringIO(payload)), \
             patch.object(module, 'prepare_inventory_record', prepare), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(module.main(), 0, stderr.getvalue())
        report = json.loads(stdout.getvalue())
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        self.assertFalse(self.metas())
        pending = (self.repo / 'index/deferred_sources.jsonl').read_text()
        self.assertIn(str(child), pending)
        self.assertIn(str(grandchild), pending)
        self.assertEqual(self.update()['metrics']['records_processed_count'], 2)

    def test_old_v1_page_descriptors_upgrade_after_actual_verification(self):
        self.chain(cross_root=True)
        payload = json.loads(self.payload())
        for row in payload['records']:
            row['source_fragment']['version'] = 1
            row['source_fragment'].pop('forked_from_id')
        self.assertEqual(self.update(json.dumps(payload))['metrics']['records_processed_count'], 2)
        self.assertEqual({row['source_fragment']['version'] for row in self.metas()}, {2})

    def test_v1_foreign_fork_manifest_and_stdin_upgrade_from_physical_headers(self):
        self.fork(parent_continuation=True, different_project=True)
        legacy = []
        for record in self.collection():
            fragment = {key: value for key, value in record.source_fragment.items() if key != 'forked_from_id'}
            fragment['version'] = 1
            legacy.append(replace(record, source_fragment=fragment))
        manifest = self.root / 'legacy-manifest.json'
        manifest.write_text(json.dumps(self.runner.source_inventory_manifest_payload(legacy)))
        manifest.chmod(0o600)
        loaded = self.runner.load_source_inventory_manifest(manifest)
        records = self.runner.combine_source_collection([loaded])
        self.assertEqual({record.source_fragment['version'] for record in records}, {2})
        self.assertEqual(self.update(self.runner.source_inventory_payload(self.target_records(loaded)))
                         ['metrics']['records_processed_count'], 1)

    def test_stdin_without_project_hints_is_verified_before_enrolling_pending(self):
        parent, child, _ = self.fork(different_project=True)
        payload = json.loads(self.runner.source_inventory_payload(self.target_records(self.collection())))
        for row in payload['records']:
            row.pop('project_paths')
        payload = json.dumps(payload)
        self.assertEqual(self.update(payload, extra=('--max-records', '0'))['status'], 'deferred')
        pending = self.repo / 'index/deferred_sources.jsonl'
        before = pending.read_bytes()
        with parent.open('a') as handle:
            handle.write(json.dumps({'ordinal': 4, 'role': 'assistant', 'content': 'Decision: changed parent.'}) + '\n')
        self.assertEqual(self.update(payload, expected=2)['status'], 'blocked')
        self.assertFalse(self.metas())
        self.assertEqual(pending.read_bytes(), before)
        self.assertEqual(self.update()['status'], 'updated')
        self.assertFalse(pending.exists())

    def test_no_hint_dependency_race_during_boundary_validation_does_not_enroll_parent(self):
        parent, _, _ = self.fork(different_project=True)
        payload = json.loads(self.payload())
        for row in payload['records']:
            row.pop('project_paths')
        module = self.updater()
        original = module.read_validated_inventory_record
        reads = 0
        def read(record):
            nonlocal reads
            if record.path == parent:
                reads += 1
                if reads == 2:
                    raise module.SourceInventoryError('source inventory record changed')
            return original(record)
        with patch.object(module, 'read_validated_inventory_record', read):
            with self.assertRaisesRegex(module.SourceInventoryError, '^source inventory target metadata is unavailable$'):
                module.discover_records_from_inventory(json.dumps(payload), self.active, None, self.project,
                    require_project_metadata=True, source_roots=(self.relocated,), source_identity_adapter='codex-session')
        self.assertFalse(self.metas())
        self.assertFalse((self.repo / 'index/deferred_sources.jsonl').exists())

    def test_manifest_cannot_shorten_root_view_without_own_continuation(self):
        parent, _, _ = self.fork(different_project=True)
        records = self.collection()
        forged = []
        for row in records:
            if row.source_root / row.relative_path == parent:
                row = replace(row, source_fragment={**row.source_fragment,
                    'end_ordinal_exclusive': 2, 'end_byte_offset': self.reference(parent)['end_byte_offset']})
            forged.append(row)
        with self.assertRaisesRegex(self.runner.SourceInventoryError, '^source_pagination_boundary_invalid$'):
            self.runner.combine_source_collection([self.runner.SourceInventory(forged)])
        self.assertFalse(self.metas())

    def test_renamed_foreign_parent_keeps_its_physical_mapping(self):
        parent, child, _ = self.fork()
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        renamed = parent.rename(self.active / 'renamed-parent.jsonl')
        records = self.collection()
        self.assertEqual(next(row for row in records if row.relative_path == renamed.name).source_fragment['rollout_id'], BASE)
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 1)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(renamed), str(child)})

    def test_compressed_foreign_parent_keeps_physical_raw_fingerprint(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd unavailable')
        parent, child, _ = self.fork(different_project=True)
        compressed = parent.with_suffix('.jsonl.zst')
        compressed.write_bytes(zstd.compress(parent.read_bytes()))
        parent.unlink()
        records = self.target_records(self.collection())
        dependency = next(row for row in records if row.relative_path == compressed.name)
        self.assertEqual(dependency.sha256, hashlib.sha256(compressed.read_bytes()).hexdigest())
        self.assertNotEqual(dependency.sha256, dependency.source_fragment['content_sha256'])
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 1)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(child)})

    def test_reference_fork_evidence_resolves_to_child_physical_page(self):
        parent, child, _ = self.fork(different_project=True)
        self.update(self.runner.source_inventory_payload(self.target_records(self.collection())))
        shutil.copytree(_pagination.TOOLS, self.repo / 'tools')
        result = subprocess.run([sys.executable, str(_pagination.TOOLS / 'search_memory.py'),
                                 'amber child result', '--repo', str(self.repo), '--depth', 'source', '--context-json'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        package = json.loads(result.stdout)
        hit = next(row for row in package['hits'] if row['active_current'] and row['source_refs'])
        result = subprocess.run([sys.executable, str(_pagination.TOOLS / 'resolve_memory_source.py'),
                                 'amber child result', '--repo', str(self.repo), '--source-ref-id',
                                 hit['source_refs'][0]['source_ref_id'], '--allow-source-root', str(self.root),
                                 '--authorize-source-preview', '--preview-json'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview['status'], 'resolved')
        self.assertIn('amber child', preview['preview'])
        mapping = json.loads(next(self.repo.glob('sessions/**/source-map.json')).read_text())
        self.assertEqual(mapping['source_record'], str(child))
        self.assertEqual(mapping['source_record_sha256'], hashlib.sha256(child.read_bytes()).hexdigest())
        self.assertEqual(mapping['evidence_source_anchors'][0]['line_number'], 2)
        self.assertEqual(mapping['evidence_source_anchors'][0]['event_ordinal'], 1)


if __name__ == '__main__':
    unittest.main()
