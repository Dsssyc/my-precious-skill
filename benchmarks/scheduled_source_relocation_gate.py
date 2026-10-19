#!/usr/bin/env python3
"""Prove scheduled publication and retry after source moves and renames."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'skills/update-my-precious/scripts/run_scheduled_memory_transaction.py'
try:
    from compression import zstd
except ImportError:
    zstd = None

IDS = ('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222',
       '33333333-3333-4333-8333-333333333333')


def command(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('synthetic_command_failed')
    return result


def git(repo: Path, *args: str) -> str:
    return command(['git', *args], repo).stdout.strip()


def write_source(path: Path, project: Path, identity: str, stamp: str) -> None:
    header = {'type': 'session_meta', 'payload': {'id': identity, 'cwd': str(project)}}
    if identity == IDS[0]:
        header['payload']['forked_from_id'] = IDS[1]
    rows = [header, {'timestamp': stamp, 'role': 'user', 'cwd': str(project),
        'content': 'Please remember: Ledger synchronization retains unresolved invoice keys until the server acknowledges delivery.'}]
    if identity == IDS[0]:
        rows.append({'type': 'session_meta', 'payload': {'id': IDS[1]}})
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))



def metadata(repo: Path) -> list[dict]:
    return [json.loads(path.read_text()) for path in repo.glob('sessions/**/meta.json')]


def run_case(root: Path) -> dict[str, int]:
    repo, active, archived, project = (root / name for name in ('memory', 'active', 'archived', 'project'))
    for path in (active, archived, project):
        path.mkdir()
    shutil.copytree(ROOT / 'templates/agent-memory-repo', repo, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (repo / 'config/projects.jsonl').write_text(json.dumps({'project_path': str(project),
        'source_dir': str(active), 'enabled': True}) + '\n')
    old_b = active / f'rollout-2026-07-13T10-00-00-{IDS[1]}.jsonl'
    write_source(old_b, project, IDS[1], '2026-07-13T10:00:00Z')
    git(repo, 'init', '--initial-branch=main')
    git(repo, 'config', 'user.name', 'Synthetic Migration Gate')
    git(repo, 'config', 'user.email', 'synthetic@example.invalid')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'Initialize synthetic migration fixture')
    remote = root / 'remote.git'
    command(['git', 'init', '--bare', '--initial-branch=main', str(remote)], root)
    git(repo, 'remote', 'add', 'origin', str(remote))
    git(repo, 'push', '-u', 'origin', 'main')
    outputs: list[str] = []

    def transaction() -> dict:
        result = command([sys.executable, str(ADAPTER), '--memory-repo', str(repo), '--source-dir', str(active),
            '--state-dir', str(root / 'state'), '--push', '--include-reviewed-memory-nodes'], repo)
        outputs.append(result.stdout + result.stderr)
        report = json.loads(result.stdout)
        assert report['status'] == 'published'
        assert report['metrics']['privacy_leak_count'] == 0
        assert git(repo, 'rev-parse', 'HEAD') == git(repo, 'rev-parse', 'origin/main')
        assert not git(repo, 'status', '--porcelain')
        return report

    transaction()
    old_a = active / f'rollout-2026-07-13T10-00-00-{IDS[0]}.jsonl'
    write_source(old_a, project, IDS[0], '2026-07-13T10:00:00Z')
    with old_b.open('a') as handle:
        handle.write(json.dumps({'timestamp': '2026-07-13T10:30:00Z', 'role': 'assistant',
                                 'content': 'Fixed: include the complete durable migrated session.'}) + '\n')
    for old in (old_a, old_b):
        os.utime(old, (1783944000, 1783944000))
    newer = active / 'newer.jsonl'
    write_source(newer, project, IDS[2], '2026-07-14T12:00:00Z')
    (repo / 'config/source_locations.jsonl').write_text(json.dumps({'source_dir': str(active),
        'relocation_dirs': [str(archived)], 'identity_adapter': 'codex-session', 'enabled': True, 'discover_after': '2026-07-14T00:00:00Z'}) + '\n')
    # Legacy path-only state is already committed before migration. The wrapper
    # moves sources after the shared inventory, reproducing a real selection race.
    queue = repo / 'index/deferred_sources.jsonl'
    queue.write_text(''.join(json.dumps({'archive_scope': str(project), 'source_partition': str(project),
                                      'source_record': str(path)}) + '\n' for path in (old_a, old_b)))
    updater = repo / 'tools/update_memory_archive.py'
    implementation = updater.with_name('migration_gate_impl.py')
    shutil.copyfile(updater, implementation)
    marker = root / 'moved'
    moved_a, moved_b = archived / 'renamed-session.jsonl', archived / old_b.name
    updater.write_text('import os,sys\nfrom pathlib import Path\n'
        + f'marker=Path({str(marker)!r})\n'
        + "if '--finalize-archive' not in sys.argv and not marker.exists():\n"
        + f'    Path({str(old_a)!r}).rename({str(moved_a)!r})\n'
        + f'    Path({str(old_b)!r}).rename({str(moved_b)!r})\n'
        + '    marker.touch()\n'
        + "os.execv(sys.executable,[sys.executable,str(Path(__file__).with_name('migration_gate_impl.py')),*sys.argv[1:]])\n")
    git(repo, 'add', 'config/source_locations.jsonl', 'index/deferred_sources.jsonl', 'tools')
    git(repo, 'commit', '-m', 'Configure synthetic migration and durable pending records')
    git(repo, 'push', 'origin', 'main')
    deferred = transaction()
    assert deferred['source_batch_complete'] is False
    # The published queue, rather than an abandoned staging checkout, must drive
    # the next adapter invocation's selection below the newer session high-water.
    remote_queue = git(repo, 'show', 'origin/main:index/deferred_sources.jsonl')
    assert len(remote_queue.splitlines()) == 2
    assert len(metadata(repo)) == 2
    moved_a = moved_a.rename(archived / 'renamed-again.jsonl')
    if zstd is not None:
        compressed = moved_a.with_suffix('.jsonl.zst')
        compressed.write_bytes(zstd.compress(moved_a.read_bytes()))
        moved_a.unlink()
        moved_a = compressed
    expected = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (moved_a, moved_b, newer)}
    recovered = transaction()
    assert recovered['source_batch_complete'] is True
    assert not queue.exists()
    rows = metadata(repo)
    assert len(rows) == 3
    assert {row['source_identity'] for row in rows} == {'codex-session:' + value for value in IDS}
    assert {row['source_record']: row['source_record_sha256'] for row in rows} == expected
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in expected.items())
    moved_b = moved_b.rename(archived / 'stable-renamed.jsonl')
    refreshed = transaction()
    assert refreshed['source_batch_complete'] is True
    assert len(metadata(repo)) == 3
    assert any(row['source_record'] == str(moved_b) for row in metadata(repo))
    assert all(row['source_record'] != str(archived / old_b.name) for row in metadata(repo))
    rendered = ''.join(outputs)
    assert str(root) not in rendered and IDS[0] not in rendered
    return {'published_transaction_count': 4, 'compressed_source_case_count': int(zstd is not None), 'forked_source_case_count': 1, 'legacy_records_recovered_count': 2,
            'duplicate_lineage_count': 0, 'pending_records_remaining_count': 0,
            'source_content_mutation_count': 0, 'privacy_leak_count': 0}


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as directory:
            metrics = run_case(Path(directory).resolve())
        report = {'report_kind': 'scheduled_source_relocation_gate', 'report_version': 1,
                  'status': 'passed', 'metrics': metrics}
    except Exception:
        report = {'report_kind': 'scheduled_source_relocation_gate', 'report_version': 1,
                  'status': 'failed', 'reason': 'synthetic_relocation_closure_failed'}
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
