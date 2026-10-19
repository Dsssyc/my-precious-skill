"""Read logical JSONL bytes while keeping hashes tied to the physical source."""
from __future__ import annotations

import io
from pathlib import Path

MAX_DECOMPRESSED_SOURCE_BYTES = 512 * 1024 * 1024


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
            decoded = reader.read(MAX_DECOMPRESSED_SOURCE_BYTES + 1)
        if len(decoded) > MAX_DECOMPRESSED_SOURCE_BYTES:
            raise SourceRecordDecodeError('source_compression_limit_exceeded')
        return decoded
    except SourceRecordDecodeError:
        raise
    except Exception as exc:
        raise SourceRecordDecodeError('source_compression_invalid') from exc
