"""Synthetic Codex physical-page lineage and archive regressions."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path('templates/agent-memory-repo/tools').resolve()
sys.path.insert(0, str(TOOLS))
from source_record_io import SourceRecordDecodeError


def load_runner():
    spec = importlib.util.spec_from_file_location('paginated_runner', TOOLS / 'run_memory_updates.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OWNER = '11111111-1111-4111-8111-111111111111'
BASE = '22222222-2222-4222-8222-222222222222'
CHILD = '33333333-3333-4333-8333-333333333333'


class PaginationFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.active = self.root / 'active'
        self.relocated = self.root / 'relocated'
        self.repo = self.root / 'memory'
        self.project = self.root / 'project'
        for path in (self.active, self.relocated, self.repo / 'index', self.repo / 'sessions', self.project):
            path.mkdir(parents=True)
        self.runner = load_runner()

    def write_page(self, path, start, facts, history_base=None):
        payload = {'id': OWNER, 'session_id': OWNER, 'history_mode': 'paginated',
                   'cwd': str(self.project), 'timestamp': '2026-07-13T10:00:00Z'}
        if history_base is not None:
            payload['history_base'] = history_base
        values = [{'type': 'session_meta', 'ordinal': start, 'payload': payload}]
        values.extend({'ordinal': start + i, 'timestamp': '2026-07-13T10:00:00Z',
                       'role': 'assistant', 'content': fact} for i, fact in enumerate(facts, 1))
        path.write_bytes(b''.join(json.dumps(value).encode() + b'\n' for value in values))
        return path

    def chain(self, cross_root=False):
        base = self.write_page(self.active / f'rollout-2026-07-13T10-00-00-{OWNER}_{BASE}.jsonl', 0,
                               ['Decision: retain cobalt storage for archived projects.',
                                'Decision: obsolete vermilion storage tail must disappear.'])
        boundary = sum(len(line) for line in base.read_bytes().splitlines(keepends=True)[:2])
        child = self.write_page((self.relocated if cross_root else self.active) /
                                f'rollout-2026-07-13T11-00-00-{OWNER}_{CHILD}.jsonl', 2,
                                ['Decision: use amber transport for new requests.'],
                                {'thread_id': BASE, 'end_ordinal_exclusive': 2, 'end_byte_offset': boundary})
        return base, child

    def collection(self):
        from source_record_io import archived_fragment_mappings
        mappings = archived_fragment_mappings(self.repo, lambda repo, path: path.resolve().is_relative_to(repo))
        return self.runner.combine_source_collection([
            self.runner.build_source_inventory(root, ('*.jsonl',), 'codex-session', fragment_mappings=mappings)
            for root in (self.active, self.relocated)], fragment_mappings=mappings)

    def update(self, payload=None, *, expected=0, extra=()):
        command = [sys.executable, str(TOOLS / 'update_memory_archive.py'), '--memory-repo', str(self.repo),
                   '--source-dir', str(self.active), '--source-relocation-dir', str(self.relocated),
                   '--source-identity-adapter', 'codex-session', '--project-path', str(self.project),
                   '--require-project-metadata', '--report-json', *extra]
        if payload is not None:
            command.append('--source-inventory-stdin')
        result = subprocess.run(command, input=payload, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        for private in (str(self.root), OWNER, BASE, CHILD):
            self.assertNotIn(private, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def metas(self):
        return [json.loads(path.read_text()) for path in self.repo.glob('sessions/**/meta.json')]

    def payload(self):
        return self.runner.source_inventory_payload(self.collection())


class CodexPaginatedSourcesTests(PaginationFixture):

    def test_valid_chain_has_separate_physical_pages_and_excludes_old_tail(self):
        base, child = self.chain()
        records = self.collection()
        self.assertEqual(len(records), 2)
        by_path = {row.source_root / row.relative_path: row for row in records}
        self.assertEqual(by_path[base].source_identity, 'codex-session:' + OWNER)
        self.assertEqual(by_path[child].source_identity, 'codex-session:' + OWNER)
        self.assertNotEqual(by_path[base].source_fragment['fragment_id'], by_path[child].source_fragment['fragment_id'])
        self.assertEqual(by_path[base].source_fragment['end_ordinal_exclusive'], 2)
        self.assertEqual(by_path[child].source_fragment['start_ordinal'], 2)

    def test_direct_and_stdin_archive_both_pages_with_local_evidence_and_no_old_tail(self):
        self.chain(cross_root=True)
        report = self.update(self.payload())
        self.assertEqual(report['metrics']['records_processed_count'], 2)
        self.assertEqual(len(self.metas()), 2)
        combined = '\n'.join(path.read_text() for path in self.repo.glob('sessions/**/*.md'))
        self.assertIn('cobalt storage', combined)
        self.assertIn('amber transport', combined)
        self.assertNotIn('vermilion', combined)
        self.assertEqual(self.update()['metrics']['records_processed_count'], 0)
        shutil.copytree(TOOLS, self.repo / 'tools')
        for query, fact in (('cobalt storage archived projects', 'cobalt storage'),
                            ('amber transport new requests', 'amber transport')):
            result = subprocess.run([sys.executable, str(TOOLS / 'search_memory.py'), query, '--repo', str(self.repo),
                                     '--depth', 'source', '--context-json'], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            package = json.loads(result.stdout)
            self.assertEqual(package['answerability']['status'], 'supported')
            hit = next(hit for hit in package['hits'] if hit['active_current'] and hit['source_refs']
                       and hit['answerability']['status'] == 'supported')
            result = subprocess.run([sys.executable, str(TOOLS / 'resolve_memory_source.py'), query,
                '--repo', str(self.repo), '--source-ref-id', hit['source_refs'][0]['source_ref_id'],
                '--allow-source-root', str(self.root), '--authorize-source-preview', '--preview-json'],
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            preview = json.loads(result.stdout)
            self.assertEqual(preview['status'], 'resolved', preview)
            self.assertIn(fact, preview['preview'])
        spec = importlib.util.spec_from_file_location('page_resolver', TOOLS / 'resolve_memory_source.py')
        resolver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resolver)
        for path in self.repo.glob('sessions/**/source-map.json'):
            mapping = json.loads(path.read_text())
            physical = Path(mapping['source_record'])
            self.assertEqual(mapping['source_record_sha256'], hashlib.sha256(physical.read_bytes()).hexdigest())
            anchors = mapping['evidence_source_anchors']
            self.assertTrue(anchors)
            for anchor in anchors:
                self.assertEqual(anchor['line_number'], 2)
                self.assertEqual(anchor['event_ordinal'], 1)
                value, reason, actual = resolver.read_jsonl_value_and_hash(physical, anchor['line_number'])
                self.assertEqual(reason, '')
                self.assertEqual(actual, mapping['source_record_sha256'])
                self.assertIn(value['ordinal'], (1, 3))

    def test_range_change_with_unchanged_raw_hash_replaces_only_the_base(self):
        base, child = self.chain()
        saved_child = child.read_bytes()
        child.unlink()
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 1)
        old_hash = self.metas()[0]['source_record_sha256']
        self.assertIn('vermilion', json.dumps(self.metas()))
        child.write_bytes(saved_child)
        report = self.update(self.payload())
        self.assertEqual(report['metrics']['records_processed_count'], 2)
        self.assertEqual(report['metrics']['entries_removed_count'], 1)
        self.assertEqual(len(self.metas()), 2)
        self.assertNotIn('vermilion', json.dumps(self.metas()))
        self.assertEqual(next(row for row in self.metas() if row['source_record'] == str(base))['source_record_sha256'], old_hash)

    def test_appending_one_page_does_not_remove_sibling_archive(self):
        _, child = self.chain()
        self.update(self.payload())
        base_meta = next(row for row in self.metas() if row['source_fragment']['start_ordinal'] == 0)
        with child.open('ab') as handle:
            handle.write(json.dumps({'ordinal': 4, 'timestamp': '2026-07-13T11:00:00Z', 'role': 'user',
                                     'content': 'Decision: retain saffron request retries.'}).encode() + b'\n')
        report = self.update(self.payload())
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertEqual(report['metrics']['entries_removed_count'], 1)
        self.assertEqual(len(self.metas()), 2)
        self.assertIn(base_meta, self.metas())

    def test_changed_dependency_defers_both_pages_and_stable_retry_completes(self):
        base, _ = self.chain(cross_root=True)
        stale = self.payload()
        with base.open('ab') as handle:
            handle.write(json.dumps({'ordinal': 3, 'role': 'user', 'content': 'Old tail addition.'}).encode() + b'\n')
        report = self.update(stale)
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        self.assertFalse(self.metas())
        queue = self.repo / 'index/deferred_sources.jsonl'
        self.assertEqual(len(queue.read_text().splitlines()), 2)
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        self.assertFalse(queue.exists())

    def test_limit_preserves_sibling_pending_and_retry_does_not_delete_completed_page(self):
        self.chain()
        first = self.update(self.payload(), extra=('--max-records', '1'))
        self.assertEqual(first['metrics']['records_processed_count'], 1)
        self.assertEqual(first['metrics']['records_deferred_count'], 1)
        first_meta = self.metas()[0]
        queue = self.repo / 'index/deferred_sources.jsonl'
        self.assertEqual(len(queue.read_text().splitlines()), 1)
        second = self.update(self.payload())
        self.assertEqual(second['metrics']['records_processed_count'], 1)
        self.assertEqual(len(self.metas()), 2)
        self.assertIn(first_meta, self.metas())
        self.assertFalse(queue.exists())

    def test_unknown_same_owner_copy_blocks_before_any_archive_or_pending_mutation(self):
        _, child = self.chain()
        payload = json.loads(self.payload())
        self.update(json.dumps(payload))
        queue = self.repo / 'index/deferred_sources.jsonl'
        row = next(row for row in self.metas() if row['source_record'] == str(child))
        queue.write_text(json.dumps({key: row[key] for key in (
            'archive_scope', 'source_partition', 'source_record', 'source_identity', 'source_fragment')}) + '\n')
        before = {path.relative_to(self.repo): path.read_bytes() for path in self.repo.rglob('*') if path.is_file()}
        unknown = self.relocated / 'unknown.jsonl'
        unknown.write_bytes(child.read_bytes())
        copied = dict(next(row for row in payload['records'] if row['relative_path'] == child.name))
        copied.update(source_root=str(self.relocated), relative_path=unknown.name, mtime_ns=unknown.stat().st_mtime_ns)
        payload['records'].append(copied)
        self.assertEqual(self.update(json.dumps(payload), expected=2)['status'], 'blocked')
        self.assertEqual({path.relative_to(self.repo): path.read_bytes() for path in self.repo.rglob('*') if path.is_file()}, before)

    def test_renamed_pages_use_verified_mappings_and_preserve_both_archives(self):
        base, child = self.chain(cross_root=True)
        self.update(self.payload())
        moved_base = base.rename(self.relocated / 'renamed-base.jsonl')
        moved_child = child.rename(self.active / 'renamed-continuation.jsonl')
        report = self.update(self.payload())
        self.assertEqual(report['metrics']['records_processed_count'], 2)
        self.assertEqual(report['metrics']['entries_removed_count'], 2)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(moved_base), str(moved_child)})
        self.assertEqual({row['source_fragment']['rollout_id'] for row in self.metas()}, {BASE, CHILD})
        self.assertEqual(self.update()['metrics']['records_processed_count'], 0)

    def test_deferred_unarchived_pages_can_move_and_rename_before_retry(self):
        base, child = self.chain(cross_root=True)
        report = self.update(self.payload(), extra=('--max-records', '0'))
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        base.rename(self.relocated / 'renamed-base.jsonl')
        child.rename(self.active / 'renamed-child.jsonl')
        self.assertEqual(self.update()['metrics']['records_processed_count'], 2)
        self.assertEqual(len(self.metas()), 2)
        self.assertFalse((self.repo / 'index/deferred_sources.jsonl').exists())

    def test_legacy_path_only_archive_and_pending_upgrade_are_page_limited(self):
        base, child = self.chain(cross_root=True)
        child_bytes = child.read_bytes()
        child.unlink()
        # Simulate the pre-pagination archive: full base, original v1 anchors,
        # no physical-page or logical-owner metadata.
        self.update()
        for path in self.repo.glob('sessions/**/meta.json'):
            row = json.loads(path.read_text())
            row.pop('source_identity')
            row.pop('source_fragment')
            path.write_text(json.dumps(row))
        queue = self.repo / 'index/deferred_sources.jsonl'
        queue.write_text(json.dumps({'archive_scope': str(self.project), 'source_partition': str(self.project),
                                    'source_record': str(base)}) + '\n')
        moved = base.rename(self.relocated / 'legacy-renamed-base.jsonl')
        child.write_bytes(child_bytes)
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        self.assertEqual(len(self.metas()), 2)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(moved), str(child)})
        self.assertFalse(queue.exists())
        self.assertNotIn('vermilion', json.dumps(self.metas()))

    def test_missing_dependency_in_stale_inventory_defers_and_returns_to_closure(self):
        base, _ = self.chain()
        stale = self.payload()
        raw = base.read_bytes()
        base.unlink()
        report = self.update(stale)
        self.assertEqual(report['metrics']['records_deferred_count'], 2)
        self.assertFalse(self.metas())
        base.write_bytes(raw)
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        self.assertFalse((self.repo / 'index/deferred_sources.jsonl').exists())

    def test_unmapped_legacy_pending_is_retained_after_a_sibling_succeeds(self):
        _, child = self.chain()
        self.update(self.payload())
        queue = self.repo / 'index/deferred_sources.jsonl'
        row = {'archive_scope': str(self.project), 'source_partition': str(self.project),
               'source_record': str(self.active / 'unknown-former-page.jsonl'),
               'source_identity': 'codex-session:' + OWNER}
        queue.write_text(json.dumps(row) + '\n')
        with child.open('ab') as handle:
            handle.write(json.dumps({'ordinal': 4, 'role': 'assistant',
                                     'content': 'Decision: use copper request envelopes.'}).encode() + b'\n')
        report = self.update(self.payload())
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertEqual(report['metrics']['records_deferred_count'], 1)
        self.assertEqual(json.loads(queue.read_text()), row)
        self.assertEqual(len(self.metas()), 2)

    def test_unknown_legacy_arbitrary_path_with_changed_bytes_retains_prior_archive(self):
        base = self.write_page(self.active / 'arbitrary-base.jsonl', 0,
                               ['Decision: use indigo storage volumes.'])
        self.update()
        for path in self.repo.glob('sessions/**/meta.json'):
            row = json.loads(path.read_text())
            row.pop('source_fragment')
            path.write_text(json.dumps(row))
        prior = self.metas()
        with base.open('ab') as handle:
            handle.write(json.dumps({'ordinal': 2, 'role': 'assistant',
                                     'content': 'Decision: use teal storage volumes.'}).encode() + b'\n')
        report = self.update(self.payload())
        self.assertEqual(report['status'], 'deferred')
        self.assertEqual(report['metrics']['records_processed_count'], 0)
        self.assertEqual(self.metas(), prior)
        # The newly written retry descriptor cannot retroactively prove which
        # page an older descriptor-less archive contained.
        retry = self.update(self.payload())
        self.assertEqual(retry['status'], 'deferred')
        self.assertEqual(retry['metrics']['records_processed_count'], 0)
        self.assertEqual(self.metas(), prior)

    def test_legacy_filename_hint_cannot_replace_archive_with_another_owner(self):
        base, child = self.chain()
        child.unlink()
        self.update()
        for path in self.repo.glob('sessions/**/meta.json'):
            row = json.loads(path.read_text())
            row.pop('source_fragment')
            row.pop('source_identity')
            path.write_text(json.dumps(row))
        prior = self.metas()
        values = [json.loads(line) for line in base.read_text().splitlines()]
        values[0]['payload'].update(id=CHILD, session_id=CHILD)
        base.write_text(''.join(json.dumps(value) + '\n' for value in values))
        self.assertEqual(self.update(expected=2)['status'], 'blocked')
        self.assertEqual(self.metas(), prior)

    def test_losing_an_archived_child_cannot_resurrect_its_excluded_parent_tail(self):
        _, child = self.chain()
        self.update(self.payload())
        prior = self.metas()
        child.unlink()
        self.assertEqual(self.update(expected=2)['status'], 'blocked')
        self.assertEqual(self.metas(), prior)
        with self.assertRaisesRegex(self.runner.SourceInventoryError, 'source_pagination_reference_missing'):
            self.collection()

    def test_cross_project_pages_provide_closure_without_archiving_foreign_page(self):
        base, child = self.chain(cross_root=True)
        other = self.root / 'other-project'
        other.mkdir()
        values = [json.loads(line) for line in child.read_text().splitlines()]
        values[0]['payload']['cwd'] = str(other)
        child.write_text(''.join(json.dumps(value) + '\n' for value in values))
        records = self.runner.inventory_records_for_target(self.collection(), self.project, require_project_metadata=True)
        self.assertEqual(len(records), 2)
        report = self.update(self.runner.source_inventory_payload(records))
        self.assertEqual(report['metrics']['records_processed_count'], 1)
        self.assertEqual([row['source_record'] for row in self.metas()], [str(base)])
        self.project = other
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 1)
        self.assertEqual({row['source_record'] for row in self.metas()}, {str(base), str(child)})

    def test_new_old_chain_is_selected_below_existing_high_water(self):
        newer = self.active / 'newer.jsonl'
        newer.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': CHILD, 'cwd': str(self.project)}}) + '\n'
                         + json.dumps({'timestamp': '2026-07-15T12:00:00Z', 'role': 'assistant',
                                       'content': 'Decision: use silver archive metadata.'}) + '\n')
        self.update(self.payload())
        self.chain(cross_root=True)
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 2)
        self.assertEqual(len(self.metas()), 3)

    def test_compressed_renamed_page_retains_raw_hash_and_local_anchor(self):
        try:
            from compression import zstd
        except ImportError:
            self.skipTest('compression.zstd unavailable')
        base, _ = self.chain()
        self.update(self.payload())
        compressed = self.relocated / 'renamed-base.jsonl.zst'
        compressed.write_bytes(zstd.compress(base.read_bytes()))
        base.unlink()
        self.assertEqual(self.update(self.payload())['metrics']['records_processed_count'], 1)
        self.assertEqual(len(self.metas()), 2)
        meta = next(row for row in self.metas() if row['source_record'] == str(compressed))
        self.assertEqual(meta['source_record_sha256'], hashlib.sha256(compressed.read_bytes()).hexdigest())
        self.assertNotEqual(meta['source_record_sha256'], meta['source_fragment']['content_sha256'])
        source_map = json.loads((self.repo / meta['source_map_path']).read_text())
        anchor = source_map['evidence_source_anchors'][0]
        spec = importlib.util.spec_from_file_location('compressed_page_resolver', TOOLS / 'resolve_memory_source.py')
        resolver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resolver)
        value, reason, raw_hash = resolver.read_jsonl_value_and_hash(compressed, anchor['line_number'])
        self.assertEqual(reason, '')
        self.assertEqual(raw_hash, meta['source_record_sha256'])
        self.assertEqual(anchor['event_ordinal'], 1)
        self.assertIn('cobalt', value['content'])

    def test_excluded_tail_cannot_discover_or_select_another_project(self):
        base, _ = self.chain()
        other = self.root / 'tail-only-project'
        other.mkdir()
        values = [json.loads(line) for line in base.read_text().splitlines()]
        values[-1]['cwd'] = str(other)
        base.write_text(''.join(json.dumps(value) + '\n' for value in values))
        records = self.collection()
        self.assertNotIn(other, self.runner.discover_projects_from_inventory(records))
        self.assertEqual(self.runner.inventory_records_for_target(records, other, require_project_metadata=True), [])
        self.project = other
        self.assertEqual(self.update(self.runner.source_inventory_payload(records))['metrics']['records_processed_count'], 0)
        self.assertEqual(self.update()['metrics']['records_processed_count'], 0)
        self.assertFalse(self.metas())


if __name__ == '__main__':
    unittest.main()
