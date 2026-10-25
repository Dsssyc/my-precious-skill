"""Read logical JSONL bytes while keeping hashes tied to the physical source."""
from __future__ import annotations

import io
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable


UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
FRAGMENT_FIELDS = frozenset({
    'version', 'fragment_id', 'rollout_id', 'session_id', 'history_base',
    'start_ordinal', 'end_ordinal_exclusive', 'end_byte_offset',
    'physical_end_ordinal_exclusive', 'physical_end_byte_offset', 'content_sha256',
})
PAGINATION_HEADER_FIELDS = frozenset({'version', 'fragment_id', 'rollout_id', 'session_id',
                                     'history_base', 'start_ordinal'})
INVENTORY_DIAGNOSTICS = frozenset({
    'source_inventory_identity_conflict', 'source_pagination_invalid',
    'source_pagination_boundary_invalid', 'source_pagination_reference_missing',
    'source_pagination_ambiguous', 'source_pagination_cycle',
})


class SourceRecordDecodeError(ValueError):
    pass


def source_format(path: Path) -> str:
    return '.jsonl' if path.name.lower().endswith('.jsonl.zst') else path.suffix


def read_source_snapshot_bytes(path: Path, expected_size: int, expected_sha256: str) -> bytes:
    """Verify a physical inventory snapshot without admitting a later appended tail.

    The caller supplies a canonical path from its existing trusted collection.
    This is collection validation only; target materialization must still verify
    the current whole-file fingerprint. Compressed append is not supported.
    """
    if (type(expected_size) is not int or expected_size < 0
        or not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256)):
        raise SourceRecordDecodeError('source_inventory_changed')
    if path.resolve(strict=True) != path:
        raise SourceRecordDecodeError('source_inventory_unsafe')
    compressed = path.name.lower().endswith('.jsonl.zst')
    with path.open('rb') as physical:
        initial_size = os.fstat(physical.fileno()).st_size
        if initial_size < expected_size or (compressed and initial_size != expected_size):
            raise SourceRecordDecodeError('source_inventory_changed')
        raw = physical.read(expected_size)
        final_size = os.fstat(physical.fileno()).st_size
        if (len(raw) != expected_size or final_size < expected_size
            or (compressed and final_size != expected_size)
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
            raise SourceRecordDecodeError('source_inventory_changed')
    if path.resolve(strict=True) != path:
        raise SourceRecordDecodeError('source_inventory_unsafe')
    return raw


def decompress_source_bytes(path: Path, raw: bytes) -> bytes:
    if not path.name.lower().endswith('.jsonl.zst'):
        return raw
    try:
        from compression import zstd
        reader = zstd.ZstdFile(io.BytesIO(raw), 'rb')
    except ImportError:
        try:
            import zstandard
        except ImportError as exc:
            raise SourceRecordDecodeError('source_compression_unavailable') from exc
        try:
            reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
        except Exception as exc:
            raise SourceRecordDecodeError('source_compression_invalid') from exc
    except Exception as exc:
        raise SourceRecordDecodeError('source_compression_invalid') from exc
    try:
        with reader:
            decoded = reader.read()
        return decoded
    except SourceRecordDecodeError:
        raise
    except Exception as exc:
        raise SourceRecordDecodeError('source_compression_invalid') from exc


def codex_session_identity(values: Iterable[object]) -> str:
    """A fork owns its first header; later headers must be declared ancestors."""
    identities: list[str] = []
    parents: dict[str, str] = {}
    uuid_pattern = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    for value in values:
        if not isinstance(value, dict) or value.get("type") != "session_meta":
            continue
        payload = value.get("payload")
        identity = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(identity, str) or not re.fullmatch(uuid_pattern, identity.lower()):
            raise SourceRecordDecodeError("source_identity_invalid")
        identity = identity.lower()
        identities.append(identity)
        parent = payload.get("forked_from_id")
        if parent is not None:
            if not isinstance(parent, str) or not re.fullmatch(uuid_pattern, parent.lower()):
                raise SourceRecordDecodeError("source_identity_invalid")
            parent = parent.lower()
            if identity == parent or parents.get(identity, parent) != parent:
                raise SourceRecordDecodeError("source_identity_conflict")
            parents[identity] = parent
    if not identities:
        return ""
    owner = identities[0]
    ancestors = {owner}
    cursor = owner
    while cursor in parents:
        cursor = parents[cursor]
        if cursor in ancestors:
            raise SourceRecordDecodeError("source_identity_conflict")
        ancestors.add(cursor)
    if not set(identities).issubset(ancestors):
        raise SourceRecordDecodeError("source_identity_conflict")
    return "codex-session:" + owner


def source_header_value(path: Path) -> object:
    """Probe only the owner header when selecting an enrolled relocated source."""
    try:
        with path.open('rb') as physical:
            reader = physical
            if path.name.lower().endswith('.jsonl.zst'):
                try:
                    from compression import zstd
                    reader = zstd.ZstdFile(physical, 'rb')
                except ImportError:
                    try:
                        import zstandard
                    except ImportError as exc:
                        raise SourceRecordDecodeError('source_compression_unavailable') from exc
                    reader = io.BufferedReader(zstandard.ZstdDecompressor().stream_reader(physical))
            try:
                line = reader.readline(16 * 1024 * 1024 + 1)
            finally:
                if reader is not physical:
                    reader.close()
        if len(line) > 16 * 1024 * 1024:
            raise SourceRecordDecodeError('source_header_limit_exceeded')
        return json.loads(line)
    except SourceRecordDecodeError:
        raise
    except Exception as exc:
        raise SourceRecordDecodeError('source_header_unavailable') from exc


def source_header_identity(path: Path) -> str:
    return codex_session_identity([source_header_value(path)])


def archived_fragment_mappings(memory_repo: Path, safe_path) -> list[dict]:
    """Read only archive-owned mapping metadata, using the caller's existing path policy."""
    rows = []
    paths = sorted((memory_repo / 'sessions').glob('**/meta.json'))
    pending = memory_repo / 'index/deferred_sources.jsonl'
    if pending.exists():
        paths.append(pending)
    for path in paths:
        if path.is_symlink() or not safe_path(memory_repo, path):
            raise SourceRecordDecodeError('source_pagination_invalid')
        try:
            values = ([json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                      if path == pending else [json.loads(path.read_text())])
        except (OSError, ValueError) as exc:
            raise SourceRecordDecodeError('source_pagination_invalid') from exc
        for value in values:
            if not isinstance(value, dict):
                raise SourceRecordDecodeError('source_pagination_invalid')
            source = value.get('source_record', '')
            identity = value.get('source_identity') or legacy_codex_source_identity(source)
            fragment = validate_source_fragment(value.get('source_fragment'))
            if identity and (fragment or codex_rollout_locator(source)):
                rows.append({'source_identity': identity, 'source_record': source,
                             'source_record_sha256': value.get('source_record_sha256', ''),
                             'source_fragment': fragment, 'identity_verified': bool(value.get('source_identity'))})
    return rows


def legacy_codex_source_identity(path: str) -> str:
    match = rollout_filename_match(path)
    return 'codex-session:' + match[1] if match else ''


def rollout_filename_match(path: str):
    # Codex rollout_file_name.rs: stable thread UUID, optional _rollout UUID.
    return re.fullmatch(r'rollout-\d{4}-\d{2}-\d{2}t\d{2}-\d{2}-\d{2}-('
                        + UUID_PATTERN + r')(?:_(' + UUID_PATTERN + r'))?\.jsonl(?:\.zst)?',
                        Path(path).name.lower())


def codex_rollout_locator(path: str) -> str:
    match = rollout_filename_match(path)
    return (match[2] or match[1]) if match else ''


def validate_rollout_locators(entries: Iterable[tuple[Path, dict | None]]) -> None:
    """A physical reference must have one candidate across the entire collection."""
    entries = list(entries)
    if not any(fragment for _, fragment in entries):
        return
    seen = set()
    for path, fragment in entries:
        locator = fragment['rollout_id'] if fragment and fragment['rollout_id'] else codex_rollout_locator(str(path))
        if locator and locator in seen:
            raise SourceRecordDecodeError('source_pagination_ambiguous')
        if locator:
            seen.add(locator)


def _uuid(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(UUID_PATTERN, value))


def _uint(value: object) -> bool:
    return type(value) is int and 0 <= value < 2**64


def _history_base(value: object) -> bool:
    return value is None or (
        isinstance(value, dict)
        and set(value) == {'thread_id', 'end_ordinal_exclusive', 'end_byte_offset'}
        and _uuid(value['thread_id']) and _uint(value['end_ordinal_exclusive'])
        and _uint(value['end_byte_offset'])
    )


def validate_source_fragment(value: object) -> dict | None:
    """Validate the small, versioned page descriptor used by IPC and archive metadata."""
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('version')) is not int
        or value['version'] not in (1, 2)
        or set(value) != (FRAGMENT_FIELDS | ({'forked_from_id'} if value['version'] == 2 else set()))
        or (value['version'] == 2 and value['forked_from_id'] is not None and not _uuid(value['forked_from_id']))
        or not isinstance(value['fragment_id'], str)
        or not re.fullmatch(r'codex-page:[0-9a-f]{64}', value['fragment_id'])
        or (value['rollout_id'] != '' and not _uuid(value['rollout_id']))
        or not _uuid(value['session_id']) or not _history_base(value['history_base'])
        or any(not _uint(value[key]) for key in (
            'start_ordinal', 'end_ordinal_exclusive', 'end_byte_offset',
            'physical_end_ordinal_exclusive', 'physical_end_byte_offset'))
        or not isinstance(value['content_sha256'], str)
        or not re.fullmatch(r'[0-9a-f]{64}', value['content_sha256'])
        or not value['start_ordinal'] < value['end_ordinal_exclusive'] <= value['physical_end_ordinal_exclusive']
        or not 0 < value['end_byte_offset'] <= value['physical_end_byte_offset']
        or value['start_ordinal'] != (value['history_base']['end_ordinal_exclusive'] if value['history_base'] else 0)):
        raise SourceRecordDecodeError('source_pagination_invalid')
    return dict(value)


def validate_pagination_header(value: object) -> dict | None:
    """Small dependency hints for inactive pages; these never authorize archive writes."""
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('version')) is not int
        or value['version'] not in (1, 2)
        or set(value) != (PAGINATION_HEADER_FIELDS | ({'forked_from_id'} if value['version'] == 2 else set()))
        or (value['version'] == 2 and value['forked_from_id'] is not None and not _uuid(value['forked_from_id']))
        or not isinstance(value['fragment_id'], str)
        or not re.fullmatch(r'codex-page:[0-9a-f]{64}', value['fragment_id'])
        or (value['rollout_id'] != '' and not _uuid(value['rollout_id']))
        or not _uuid(value['session_id']) or not _history_base(value['history_base'])
        or not _uint(value['start_ordinal'])
        or value['start_ordinal'] != (value['history_base']['end_ordinal_exclusive'] if value['history_base'] else 0)):
        raise SourceRecordDecodeError('source_pagination_invalid')
    return dict(value)


def fragment_descriptor_matches(actual: dict | None, expected: dict | None) -> bool:
    """Read v1 descriptors after physical verification adds the v2 fork declaration.

    This comparison is also used for bounded header hints. Missing v2 metadata
    never proves a foreign edge; the actual canonical header must supply it.
    """
    if actual is None or expected is None:
        return actual == expected
    if expected.get('version') == 1 and actual.get('version') == 2:
        actual = {key: value for key, value in actual.items() if key != 'forked_from_id'}
        actual['version'] = 1
    return actual == expected


def _history_metadata(payload: object) -> tuple[str, str, dict | None]:
    if not isinstance(payload, dict):
        raise SourceRecordDecodeError('source_identity_invalid')
    mode = payload.get('history_mode', 'legacy')
    base = payload.get('history_base')
    if mode not in ('legacy', 'paginated') or not _history_base(base) or (base is not None and mode != 'paginated'):
        raise SourceRecordDecodeError('source_pagination_invalid')
    boundary = payload.get('subagent_history_start_ordinal')
    if boundary is not None and not _uint(boundary):
        raise SourceRecordDecodeError('source_pagination_invalid')
    session_id = payload.get('session_id', payload.get('id'))
    if mode == 'paginated' and not _uuid(session_id):
        raise SourceRecordDecodeError('source_pagination_invalid')
    return mode, session_id, base


def codex_pagination_header(path: Path, value: object) -> dict | None:
    if not isinstance(value, dict) or value.get('type') != 'session_meta':
        return None
    mode, session_id, base = _history_metadata(value.get('payload'))
    if mode != 'paginated':
        return None
    codex_session_identity([value])
    start = base['end_ordinal_exclusive'] if base else 0
    if not _uint(value.get('ordinal')) or value['ordinal'] != start:
        raise SourceRecordDecodeError('source_pagination_invalid')
    header_hash = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=True).encode()).hexdigest()
    return validate_pagination_header({
        'version': 2, 'fragment_id': 'codex-page:' + header_hash,
        'rollout_id': codex_rollout_locator(str(path)), 'session_id': session_id,
        'history_base': base, 'start_ordinal': start,
        'forked_from_id': value['payload'].get('forked_from_id'),
    })


def pagination_header_is_known(identity: str, header: dict, mappings: Iterable[dict]) -> bool | None:
    """Refine an enrolled logical owner to known physical pages when proofs exist.

    None means legacy enrollment has no physical mapping, so normal identity
    enrollment still applies. Matches are hints; full content is verified later.
    """
    known = []
    for row in mappings:
        if row.get('source_identity') != identity:
            continue
        previous = validate_source_fragment(row.get('source_fragment'))
        locator = previous['rollout_id'] if previous else codex_rollout_locator(row.get('source_record', ''))
        if previous or locator:
            known.append((previous, locator))
    if not known:
        return None
    return any((header['rollout_id'] and header['rollout_id'] == locator)
               or (previous and previous['fragment_id'] == header['fragment_id']
                   and (not header['rollout_id'] or not locator)) for previous, locator in known)


def codex_source_fragment(path: Path, logical: bytes) -> dict | None:
    """Describe one physical page; never derive its logical owner from a filename.

    Same-owner continuations and declared foreign forks are resolved separately.
    Unproven branches and competing copies are rejected by collection closure.
    """
    if source_format(path) != '.jsonl':
        return None
    header = None
    count = 0
    headers = []
    page_header = None
    paginated = False
    start = 0
    for line in io.BytesIO(logical):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise SourceRecordDecodeError('source_pagination_invalid') from exc
        if isinstance(value, dict) and value.get('type') == 'session_meta':
            payload = value.get('payload')
            mode, _, _ = _history_metadata(payload)
            if count == 0:
                header = value
                page_header = codex_pagination_header(path, value)
                paginated = page_header is not None
                start = page_header['start_ordinal'] if page_header else 0
            elif header is None and mode == 'paginated':
                raise SourceRecordDecodeError('source_pagination_invalid')
            headers.append(value)
        if paginated and (not isinstance(value, dict) or not _uint(value.get('ordinal')) or value['ordinal'] != start + count):
            raise SourceRecordDecodeError('source_pagination_invalid')
        count += 1
    if not paginated:
        return None
    if not logical.endswith(b'\n'):
        raise SourceRecordDecodeError('source_pagination_invalid')
    payload = header['payload']
    # The canonical child owns this physical page. Embedded ancestor metadata
    # describes copied context, not another physical history-base dependency.
    codex_session_identity(headers)
    boundary = payload.get('subagent_history_start_ordinal')
    if boundary is not None and boundary > start + count:
        raise SourceRecordDecodeError('source_pagination_invalid')
    if page_header['history_base'] is None and boundary is not None and boundary > 1:
        if not payload.get('forked_from_id') or len(headers) < 2 or headers[1]['ordinal'] != 1:
            raise SourceRecordDecodeError('source_pagination_invalid')
    if len(headers) > 1:
        identities = [value['payload']['id'].lower() for value in headers]
        if (page_header['history_base'] is not None or start != 0
            or not payload.get('forked_from_id') or boundary is None
            or identities[0] in identities[1:]
            or identities[1] != payload['forked_from_id'].lower()
            or any(not 0 < value['ordinal'] < boundary for value in headers[1:])):
            raise SourceRecordDecodeError('source_pagination_invalid')
    return validate_source_fragment({
        **page_header,
        'end_ordinal_exclusive': start + count, 'end_byte_offset': len(logical),
        'physical_end_ordinal_exclusive': start + count,
        'physical_end_byte_offset': len(logical), 'content_sha256': hashlib.sha256(logical).hexdigest(),
    })


def fragment_content_matches(logical: bytes, previous: dict) -> bool:
    """An archived decoded prefix proves a renamed/appended/recompressed page mapping."""
    previous = validate_source_fragment(previous)
    return bool(previous and len(logical) >= previous['physical_end_byte_offset']
                and hashlib.sha256(memoryview(logical)[:previous['physical_end_byte_offset']]).hexdigest() == previous['content_sha256'])


def restore_fragment_locator(fragment: dict, logical: bytes, identity: str, raw_sha256: str,
                             mappings: Iterable[dict]) -> dict:
    fragment = dict(fragment)
    candidates = set()
    unmapped_previous = False
    for row in mappings:
        if row.get('source_identity') != identity and row.get('identity_verified', True):
            continue
        previous = validate_source_fragment(row.get('source_fragment'))
        if previous:
            if previous['fragment_id'] == fragment['fragment_id'] and previous['rollout_id']:
                unmapped_previous = True
            if (previous['fragment_id'] == fragment['fragment_id'] and previous['rollout_id']
                and fragment_content_matches(logical, previous)):
                candidates.add(previous['rollout_id'])
        elif row.get('source_record_sha256') == raw_sha256:
            locator = codex_rollout_locator(row.get('source_record', ''))
            if locator:
                candidates.add(locator)
    if fragment['rollout_id']:
        candidates.add(fragment['rollout_id'])
    if len(candidates) > 1:
        raise SourceRecordDecodeError('source_pagination_ambiguous')
    if not candidates and unmapped_previous:
        raise SourceRecordDecodeError('source_pagination_reference_missing')
    if candidates:
        fragment['rollout_id'] = candidates.pop()
    return fragment


def fragment_prefix(logical: bytes, fragment: dict) -> bytes:
    fragment = validate_source_fragment(fragment)
    end = fragment['end_byte_offset']
    if end > len(logical) or logical[end - 1:end] != b'\n':
        raise SourceRecordDecodeError('source_pagination_boundary_invalid')
    expected = fragment['start_ordinal']
    reader = io.BytesIO(logical)
    while reader.tell() < end:
        line = reader.readline()
        if reader.tell() > end:
            raise SourceRecordDecodeError('source_pagination_boundary_invalid')
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise SourceRecordDecodeError('source_pagination_boundary_invalid') from exc
        if not isinstance(value, dict) or value.get('ordinal') != expected:
            raise SourceRecordDecodeError('source_pagination_boundary_invalid')
        expected += 1
    if expected != fragment['end_ordinal_exclusive']:
        raise SourceRecordDecodeError('source_pagination_boundary_invalid')
    return logical[:end]


def resolve_source_fragments(entries: Iterable[tuple[str, dict | None]], *, require_closure: bool = True,
                             fragment_mappings: Iterable[dict] = ()) -> list[dict | None]:
    """Resolve a trusted collection's physical graph. No path or owner allowlist lives here.

    Input order is retained. Range byte/ordinal boundaries are subsequently checked
    against each page's decoded bytes with fragment_prefix().
    """
    entries = list(entries)
    result = [validate_source_fragment(fragment) for _, fragment in entries]
    groups: dict[str, list[int]] = {}
    for i, (identity, _) in enumerate(entries):
        if identity:
            groups.setdefault(identity, []).append(i)
    if require_closure:
        for row in fragment_mappings:
            indexes = groups.get(row.get('source_identity'), [])
            previous = validate_source_fragment(row.get('source_fragment'))
            if indexes and previous and not any(result[i] and result[i]['fragment_id'] == previous['fragment_id'] for i in indexes):
                # Absence is not permission to expand a previously frozen prefix.
                raise SourceRecordDecodeError('source_pagination_reference_missing')
    by_locator = {}
    by_fragment = {}
    for i, page in enumerate(result):
        if page is None:
            continue
        if page['fragment_id'] in by_fragment or (page['rollout_id'] and page['rollout_id'] in by_locator):
            raise SourceRecordDecodeError('source_pagination_ambiguous')
        by_fragment[page['fragment_id']] = i
        if page['rollout_id']:
            by_locator[page['rollout_id']] = i
    parents = {}
    own_parents = {}
    own_children = {}
    for i, page in enumerate(result):
        if page is None or not page['history_base']:
            continue
        parent = by_locator.get(page['history_base']['thread_id'])
        if parent is None:
            if require_closure:
                raise SourceRecordDecodeError('source_pagination_reference_missing')
            continue
        parents[i] = parent
        if entries[i][0] == entries[parent][0]:
            if parent in own_children:
                raise SourceRecordDecodeError('source_pagination_ambiguous')
            own_parents[i] = parent
            own_children[parent] = i
        elif (not entries[parent][0] or
              page.get('forked_from_id') != entries[parent][0].removeprefix('codex-session:')):
            # A legacy descriptor is only a discovery hint until physical
            # verification supplies the canonical v2 fork declaration.
            if require_closure or page['version'] != 1:
                raise SourceRecordDecodeError('source_pagination_invalid')
    # All physical edges participate, including edges across logical owners.
    finished = set()
    for i in range(len(result)):
        visiting = set()
        cursor = i
        while cursor not in finished:
            if cursor in visiting:
                raise SourceRecordDecodeError('source_pagination_cycle')
            visiting.add(cursor)
            if cursor not in parents:
                break
            cursor = parents[cursor]
        finished.update(visiting)
    for indexes in groups.values():
        if len(indexes) == 1 and result[indexes[0]] is None:
            continue
        if any(result[i] is None for i in indexes):
            raise SourceRecordDecodeError('source_inventory_identity_conflict')
        if require_closure and sum(i not in own_parents for i in indexes) != 1:
            raise SourceRecordDecodeError('source_pagination_ambiguous')
    # Only a same-owner continuation determines its parent's own effective view.
    for child, parent in own_parents.items():
        base = result[child]['history_base']
        page = result[parent]
        if (page['session_id'] != result[child]['session_id']
            or not page['start_ordinal'] < base['end_ordinal_exclusive'] <= page['physical_end_ordinal_exclusive']
            or not 0 < base['end_byte_offset'] <= page['physical_end_byte_offset']):
            raise SourceRecordDecodeError('source_pagination_boundary_invalid')
        page['end_ordinal_exclusive'] = base['end_ordinal_exclusive']
        page['end_byte_offset'] = base['end_byte_offset']
    for child, parent in parents.items():
        base = result[child]['history_base']
        page = result[parent]
        if (not page['start_ordinal'] < base['end_ordinal_exclusive'] <= page['end_ordinal_exclusive']
            or not 0 < base['end_byte_offset'] <= page['end_byte_offset']):
            raise SourceRecordDecodeError('source_pagination_boundary_invalid')
    return result


def fragment_reference_prefixes(entries: Iterable[tuple[str, dict | None]]) -> dict[int, list[dict]]:
    """Group physical reference bounds after graph validation, for byte verification."""
    entries = list(entries)
    locators = {page['rollout_id']: i for i, (_, page) in enumerate(entries) if page and page['rollout_id']}
    references: dict[int, list[dict]] = {}
    for _, page in entries:
        if page and page['history_base'] and page['history_base']['thread_id'] in locators:
            references.setdefault(locators[page['history_base']['thread_id']], []).append(page['history_base'])
    return references


def validated_fragment_prefix(logical: bytes, fragment: dict, references: Iterable[dict] = ()) -> bytes:
    """Verify the own range and each inherited prefix against the original page bytes."""
    effective = fragment_prefix(logical, fragment)
    checked = {(fragment['end_ordinal_exclusive'], fragment['end_byte_offset'])}
    for base in references:
        boundary = (base['end_ordinal_exclusive'], base['end_byte_offset'])
        if boundary in checked:
            continue
        fragment_prefix(logical, {**fragment, 'end_ordinal_exclusive': base['end_ordinal_exclusive'],
                                  'end_byte_offset': base['end_byte_offset']})
        checked.add(boundary)
    return effective


def source_fragment_dependencies(entries: Iterable[tuple[str, dict | None]]) -> list[frozenset[int]]:
    """Return each page's transitive parents and complete owner views, including itself.

    This is a lookup operation, not graph authorization. Callers verify physical
    metadata and resolve the graph before using a closure to permit any writes.
    It can also conservatively propagate deferral from unverified snapshots.
    """
    entries = list(entries)
    owners: dict[str, set[int]] = {}
    locators = {}
    for i, (owner, page) in enumerate(entries):
        if page:
            owners.setdefault(owner, set()).add(i)
            if page['rollout_id']:
                if page['rollout_id'] in locators:
                    raise SourceRecordDecodeError('source_pagination_ambiguous')
                locators[page['rollout_id']] = i
    closures = {}
    for owner, indexes in owners.items():
        needed = set(indexes)
        remaining = list(indexes)
        while remaining:
            i = remaining.pop()
            page = entries[i][1]
            base = page['history_base'] if page else None
            parent = locators.get(base['thread_id']) if base else None
            if parent is None:
                continue
            for dependency in owners.get(entries[parent][0], {parent}) - needed:
                needed.add(dependency)
                remaining.append(dependency)
        closures[owner] = frozenset(needed)
    return [closures[owner] if page else frozenset({i}) for i, (owner, page) in enumerate(entries)]
