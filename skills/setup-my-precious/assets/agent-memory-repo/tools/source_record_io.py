"""Read logical JSONL bytes while keeping hashes tied to the physical source."""
from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Iterable


class SourceRecordDecodeError(ValueError):
    pass


def source_format(path: Path) -> str:
    return '.jsonl' if path.name.lower().endswith('.jsonl.zst') else path.suffix


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


def source_header_identity(path: Path) -> str:
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
        return codex_session_identity([json.loads(line)])
    except SourceRecordDecodeError:
        raise
    except Exception as exc:
        raise SourceRecordDecodeError('source_header_unavailable') from exc


def legacy_codex_source_identity(path: str) -> str:
    match = re.fullmatch(r"rollout-\d{4}-\d{2}-\d{2}t\d{2}-\d{2}-\d{2}-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl", Path(path).name.lower())
    return 'codex-session:' + match[1] if match else ''
