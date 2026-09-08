#!/usr/bin/env python3
"""Serve local dense retrieval and reranking over a private memory index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np


REQUEST_KIND = "memory_semantic_retrieval_request"
RESPONSE_KIND = "memory_semantic_retrieval_response"
HEALTH_REQUEST_KIND = "memory_semantic_retrieval_health_request"
HEALTH_RESPONSE_KIND = "memory_semantic_retrieval_health_response"
REPORT_VERSION = 1
MAX_REQUEST_BYTES = 512 * 1024
MAX_QUERY_LENGTH = 1000
MAX_RESULTS = 64
MAX_ELIGIBLE_MEMORY_IDS = 100_000
PROVIDER_IMPLEMENTATION_ID = "wide-hybrid-retrieval-v1"
MAX_PREFIX_LENGTH = 100


class ProviderStartupError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class CorpusEntry:
    memory_id: str
    text: str


@dataclass(frozen=True)
class ProviderIdentity:
    fingerprint: str
    index_sha256: str


@dataclass
class ProviderState:
    identity: ProviderIdentity
    corpus: list[CorpusEntry]
    corpus_embeddings: np.ndarray
    embedding_model: Any
    reranker_model: Any | None
    query_prefix: str
    batch_size: int


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def directory_manifest_sha256(path: Path) -> str:
    if not path.is_dir() or path.is_symlink():
        raise ProviderStartupError("model_directory_unavailable")
    rows: list[dict[str, object]] = []
    try:
        for child in sorted(path.rglob("*")):
            if not child.is_file() or child.is_symlink():
                continue
            relative = child.relative_to(path)
            if ".cache" in relative.parts:
                continue
            rows.append(
                {
                    "path": relative.as_posix(),
                    "size": child.stat().st_size,
                    "sha256": file_sha256(child),
                }
            )
    except OSError as exc:
        raise ProviderStartupError("model_directory_unavailable") from exc
    if not rows:
        raise ProviderStartupError("model_directory_empty")
    return hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def provider_fingerprint(
    *,
    embedding_manifest_sha256: str,
    reranker_manifest_sha256: str,
    query_prefix: str,
    document_prefix: str,
) -> str:
    payload = {
        "document_prefix": document_prefix,
        "embedding_manifest_sha256": embedding_manifest_sha256,
        "implementation_id": PROVIDER_IMPLEMENTATION_ID,
        "protocol_version": REPORT_VERSION,
        "query_prefix": query_prefix,
        "reranker_manifest_sha256": reranker_manifest_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderStartupError("memory_index_malformed") from exc
            if not isinstance(value, dict):
                raise ProviderStartupError("memory_index_malformed")
            yield value


def field_text(record: dict, key: str) -> str:
    value = record.get(key)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return ""


def contextual_memory_text(record: dict) -> str:
    parts = [
        f"scope: {field_text(record, 'scope')}",
        f"topic: {field_text(record, 'topic')}",
        f"memory: {field_text(record, 'text')}",
        f"rationale: {field_text(record, 'rationale')}",
        f"tags: {field_text(record, 'tags')}",
    ]
    return "\n".join(part for part in parts if part.split(":", 1)[1].strip())


def load_corpus(index_path: Path) -> list[CorpusEntry]:
    if not index_path.is_file() or index_path.is_symlink():
        raise ProviderStartupError("memory_index_unavailable")
    entries: list[CorpusEntry] = []
    seen: set[str] = set()
    for record in iter_jsonl(index_path):
        memory_id = str(record.get("memory_id") or "")
        text = contextual_memory_text(record)
        if not memory_id or not text:
            continue
        if memory_id in seen:
            raise ProviderStartupError("memory_index_duplicate_id")
        seen.add(memory_id)
        entries.append(CorpusEntry(memory_id=memory_id, text=text))
    if not entries:
        raise ProviderStartupError("memory_index_empty")
    return entries


def normalized_embeddings(model: Any, texts: list[str], *, batch_size: int) -> np.ndarray:
    values = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    array = np.asarray(values, dtype=np.float32)
    if array.ndim != 2 or len(array) != len(texts) or not np.isfinite(array).all():
        raise ProviderStartupError("invalid_embedding_output")
    return array


def build_corpus_embeddings(
    model: Any,
    corpus: list[CorpusEntry],
    *,
    document_prefix: str,
    batch_size: int,
) -> np.ndarray:
    return normalized_embeddings(
        model,
        [f"{document_prefix}{entry.text}" for entry in corpus],
        batch_size=batch_size,
    )


def validate_request(
    request: object,
    state: ProviderState,
) -> tuple[str, int, set[str]]:
    if not isinstance(request, dict):
        raise ProviderRequestError("invalid_request")
    if (
        request.get("report_kind") != REQUEST_KIND
        or request.get("report_version") != REPORT_VERSION
        or request.get("provider_fingerprint") != state.identity.fingerprint
        or request.get("index_sha256") != state.identity.index_sha256
    ):
        raise ProviderRequestError("invalid_request")
    query = request.get("query")
    max_results = request.get("max_results")
    raw_eligible_ids = request.get("eligible_memory_ids")
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > MAX_QUERY_LENGTH
        or isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= MAX_RESULTS
        or not isinstance(raw_eligible_ids, list)
        or not 1 <= len(raw_eligible_ids) <= MAX_ELIGIBLE_MEMORY_IDS
    ):
        raise ProviderRequestError("invalid_request")
    eligible_ids: set[str] = set()
    for memory_id in raw_eligible_ids:
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or memory_id in eligible_ids
        ):
            raise ProviderRequestError("invalid_request")
        eligible_ids.add(memory_id)
    corpus_ids = {entry.memory_id for entry in state.corpus}
    if not eligible_ids.issubset(corpus_ids):
        raise ProviderRequestError("index_identity_mismatch")
    return query, max_results, eligible_ids


def query_embedding(state: ProviderState, query: str) -> np.ndarray:
    values = normalized_embeddings(
        state.embedding_model,
        [f"{state.query_prefix}{query}"],
        batch_size=1,
    )
    if values.shape[1] != state.corpus_embeddings.shape[1]:
        raise ProviderRequestError("invalid_model_output")
    return values[0]


def reranker_scores(state: ProviderState, query: str, indices: list[int]) -> list[float] | None:
    if state.reranker_model is None:
        return None
    raw = state.reranker_model.predict(
        [(query, state.corpus[index].text) for index in indices],
        batch_size=state.batch_size,
        show_progress_bar=False,
    )
    values = np.asarray(raw, dtype=np.float32).reshape(-1)
    if len(values) != len(indices) or not np.isfinite(values).all():
        raise ProviderRequestError("invalid_reranker_output")
    scores = [float(value) for value in values]
    if any(not 0.0 <= value <= 1.0 for value in scores):
        raise ProviderRequestError("invalid_reranker_output")
    return scores


def score_request(state: ProviderState, request: object) -> dict[str, object]:
    query, max_results, eligible_ids = validate_request(request, state)
    embedding = query_embedding(state, query)
    dense_scores = np.asarray(state.corpus_embeddings @ embedding, dtype=np.float32)
    if dense_scores.ndim != 1 or not np.isfinite(dense_scores).all():
        raise ProviderRequestError("invalid_model_output")
    eligible_indices = [
        index
        for index, entry in enumerate(state.corpus)
        if entry.memory_id in eligible_ids
    ]
    prefetch_limit = min(len(eligible_indices), max_results * 4)
    dense_order = sorted(
        eligible_indices,
        key=lambda index: (float(dense_scores[index]), state.corpus[index].memory_id),
        reverse=True,
    )[:prefetch_limit]
    support_scores = reranker_scores(state, query, dense_order)
    if support_scores is None:
        ranked = [(index, None) for index in dense_order[:max_results]]
    else:
        ranked = sorted(
            zip(dense_order, support_scores, strict=True),
            key=lambda item: (
                float(item[1]),
                float(dense_scores[item[0]]),
                state.corpus[item[0]].memory_id,
            ),
            reverse=True,
        )[:max_results]
    results = []
    for index, support_score in ranked:
        row: dict[str, object] = {
            "memory_id": state.corpus[index].memory_id,
            "retrieval_score": round(float(dense_scores[index]), 6),
        }
        if support_score is not None:
            row["support_score"] = round(float(support_score), 6)
        results.append(row)
    return {
        "report_kind": RESPONSE_KIND,
        "report_version": REPORT_VERSION,
        "provider_fingerprint": state.identity.fingerprint,
        "index_sha256": state.identity.index_sha256,
        "results": results,
    }


def health_response(state: ProviderState) -> dict[str, object]:
    return {
        "report_kind": HEALTH_RESPONSE_KIND,
        "report_version": REPORT_VERSION,
        "status": "ready",
        "provider_fingerprint": state.identity.fingerprint,
        "index_sha256": state.identity.index_sha256,
        "memory_count": len(state.corpus),
        "reranker_enabled": state.reranker_model is not None,
    }


def failure_response(state: ProviderState) -> dict[str, object]:
    return {
        "report_kind": RESPONSE_KIND,
        "report_version": REPORT_VERSION,
        "status": "failed",
        "provider_fingerprint": state.identity.fingerprint,
        "index_sha256": state.identity.index_sha256,
        "results": [],
    }


def receive_request(connection: socket.socket) -> object:
    payload = bytearray()
    while not payload.endswith(b"\n"):
        chunk = connection.recv(65536)
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > MAX_REQUEST_BYTES:
            raise ProviderRequestError("request_too_large")
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderRequestError("invalid_request") from exc


def serve(socket_path: Path, state: ProviderState) -> None:
    if not socket_path.is_absolute():
        raise ProviderStartupError("provider_socket_must_be_absolute")
    if socket_path.exists() or socket_path.is_symlink():
        raise ProviderStartupError("provider_socket_already_exists")
    if not socket_path.parent.is_dir() or socket_path.parent.is_symlink():
        raise ProviderStartupError("provider_socket_parent_unavailable")
    parent_stat = socket_path.parent.stat()
    if parent_stat.st_uid != os.getuid() or parent_stat.st_mode & 0o077:
        raise ProviderStartupError("provider_socket_parent_not_private")

    should_stop = False

    def stop(_signum, _frame) -> None:
        nonlocal should_stop
        should_stop = True

    previous_term = signal.signal(signal.SIGTERM, stop)
    previous_int = signal.signal(signal.SIGINT, stop)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            socket_path.chmod(0o600)
            server.listen(8)
            server.settimeout(0.25)
            while not should_stop:
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    try:
                        request = receive_request(connection)
                        if (
                            isinstance(request, dict)
                            and request.get("report_kind") == HEALTH_REQUEST_KIND
                            and request.get("provider_fingerprint")
                            == state.identity.fingerprint
                        ):
                            response = health_response(state)
                        else:
                            response = score_request(state, request)
                    except Exception:
                        response = failure_response(state)
                    try:
                        connection.sendall(
                            json.dumps(
                                response,
                                separators=(",", ":"),
                                sort_keys=True,
                            ).encode("utf-8")
                            + b"\n"
                        )
                    except OSError:
                        pass
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        try:
            if socket_path.is_socket() and socket_path.lstat().st_uid == os.getuid():
                socket_path.unlink()
        except OSError:
            pass


def load_models(
    embedding_model_dir: Path,
    reranker_model_dir: Path | None,
    *,
    device: str,
) -> tuple[Any, Any | None]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"
    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer
        import torch
    except ImportError as exc:
        raise ProviderStartupError("provider_runtime_unavailable") from exc
    embedding_model = SentenceTransformer(
        str(embedding_model_dir),
        device=device,
        local_files_only=True,
        trust_remote_code=False,
    )
    reranker_model = (
        CrossEncoder(
            str(reranker_model_dir),
            device=device,
            local_files_only=True,
            trust_remote_code=False,
            activation_fn=torch.nn.Sigmoid(),
        )
        if reranker_model_dir is not None
        else None
    )
    return embedding_model, reranker_model


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--embedding-model-dir", required=True)
    parser.add_argument("--reranker-model-dir")
    parser.add_argument("--socket")
    parser.add_argument("--query-prefix", default="query: ")
    parser.add_argument("--document-prefix", default="passage: ")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--print-fingerprint", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.batch_size <= 0:
            raise ProviderStartupError("invalid_batch_size")
        if (
            len(args.query_prefix) > MAX_PREFIX_LENGTH
            or len(args.document_prefix) > MAX_PREFIX_LENGTH
            or any(ord(char) < 32 for char in args.query_prefix + args.document_prefix)
        ):
            raise ProviderStartupError("invalid_prefix_policy")
        repo = Path(args.repo).expanduser().resolve()
        index_path = repo / "index" / "memories.jsonl"
        embedding_model_dir = Path(args.embedding_model_dir).expanduser().resolve()
        reranker_model_dir = (
            Path(args.reranker_model_dir).expanduser().resolve()
            if args.reranker_model_dir
            else None
        )
        embedding_manifest = directory_manifest_sha256(embedding_model_dir)
        reranker_manifest = (
            directory_manifest_sha256(reranker_model_dir)
            if reranker_model_dir is not None
            else ""
        )
        fingerprint = provider_fingerprint(
            embedding_manifest_sha256=embedding_manifest,
            reranker_manifest_sha256=reranker_manifest,
            query_prefix=args.query_prefix,
            document_prefix=args.document_prefix,
        )
        if args.print_fingerprint:
            print(
                json.dumps(
                    {
                        "report_kind": "memory_semantic_retrieval_provider_identity",
                        "report_version": REPORT_VERSION,
                        "provider_fingerprint": fingerprint,
                        "reranker_enabled": reranker_model_dir is not None,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if not args.socket:
            raise ProviderStartupError("provider_socket_required")
        corpus = load_corpus(index_path)
        embedding_model, reranker_model = load_models(
            embedding_model_dir,
            reranker_model_dir,
            device=args.device,
        )
        state = ProviderState(
            identity=ProviderIdentity(
                fingerprint=fingerprint,
                index_sha256=file_sha256(index_path),
            ),
            corpus=corpus,
            corpus_embeddings=build_corpus_embeddings(
                embedding_model,
                corpus,
                document_prefix=args.document_prefix,
                batch_size=args.batch_size,
            ),
            embedding_model=embedding_model,
            reranker_model=reranker_model,
            query_prefix=args.query_prefix,
            batch_size=args.batch_size,
        )
        print(
            json.dumps(
                {
                    "report_kind": "memory_semantic_retrieval_provider_startup",
                    "report_version": REPORT_VERSION,
                    "status": "ready",
                    "provider_fingerprint": fingerprint,
                    "memory_count": len(corpus),
                    "reranker_enabled": reranker_model is not None,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        serve(Path(args.socket).expanduser(), state)
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "report_kind": "memory_semantic_retrieval_provider_startup",
                    "status": "failed",
                    "reason": (
                        str(exc)
                        if isinstance(exc, ProviderStartupError)
                        else "provider_startup_error"
                    ),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
