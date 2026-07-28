#!/usr/bin/env python3
"""Serve the pinned local semantic-support verifier over a private Unix socket."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Any


MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_MANIFEST_SHA256 = (
    "8a945b5d9dde256c5bb6f0274845ac4d7a42e9a02b1e0ac76da66972d32299bb"
)
MODEL_FINGERPRINT = (
    "89c7223e22f226e5142b3ebc9360f0127b436dc88ba8684922b55dbdabcd6437"
)
MAX_CANDIDATES = 5
MAX_TEXT_LENGTH = 180
MAX_REQUEST_BYTES = 65536
EXPECTED_RUNTIME_VERSIONS = {
    "sentence-transformers": "5.6.0",
    "torch": "2.13.0",
    "transformers": "5.14.1",
}
EXPECTED_MODEL_FILES = {
    "1_Pooling/config.json": (
        "987f7a67a38fa564c849bb5d277c52ab9088a84368fc0be31a354125aebb12a0",
        200,
    ),
    "config.json": (
        "69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959",
        655,
    ),
    "model.safetensors": (
        "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
        470641600,
    ),
    "modules.json": (
        "c6e29747481e8b5dd2b58401966aeac910de39092f90cda9a704b1545f902b04",
        387,
    ),
    "sentence_bert_config.json": (
        "948201d8329907aae938fa62f9ceeed53f5694dacc2b87b9f3b78b37ee986529",
        57,
    ),
    "sentencepiece.bpe.model": (
        "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        5069051,
    ),
    "special_tokens_map.json": (
        "d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7",
        167,
    ),
    "tokenizer.json": (
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
        17082730,
    ),
    "tokenizer_config.json": (
        "a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b",
        443,
    ),
}


class ProviderStartupError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_artifacts(model_dir: Path) -> None:
    try:
        actual_files = {
            path.relative_to(model_dir).as_posix()
            for path in model_dir.rglob("*")
            if path.is_file()
            and ".cache" not in path.relative_to(model_dir).parts
        }
        if actual_files != set(EXPECTED_MODEL_FILES):
            raise ProviderStartupError("model_artifact_manifest_mismatch")
        rows = []
        for relative in sorted(EXPECTED_MODEL_FILES):
            expected_sha256, expected_size = EXPECTED_MODEL_FILES[relative]
            path = model_dir / relative
            actual_size = path.stat().st_size
            actual_sha256 = file_sha256(path)
            if actual_size != expected_size or actual_sha256 != expected_sha256:
                raise ProviderStartupError("model_artifact_manifest_mismatch")
            rows.append(
                {
                    "path": relative,
                    "sha256": actual_sha256,
                    "size": actual_size,
                }
            )
        manifest = hashlib.sha256(
            json.dumps(
                rows,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    except OSError as exc:
        raise ProviderStartupError("model_artifact_manifest_mismatch") from exc
    if manifest != MODEL_MANIFEST_SHA256:
        raise ProviderStartupError("model_artifact_manifest_mismatch")


def verify_runtime_versions() -> None:
    for package, expected in EXPECTED_RUNTIME_VERSIONS.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ProviderStartupError("provider_runtime_version_mismatch") from exc
        if actual != expected:
            raise ProviderStartupError("provider_runtime_version_mismatch")


def validate_request(request: object) -> tuple[str, list[tuple[str, str]]]:
    if not isinstance(request, dict):
        raise ProviderRequestError("invalid_request")
    if (
        request.get("report_kind") != "semantic_support_request"
        or request.get("report_version") != 1
        or request.get("model_fingerprint") != MODEL_FINGERPRINT
    ):
        raise ProviderRequestError("invalid_request")
    query = request.get("query")
    raw_candidates = request.get("candidates")
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > MAX_TEXT_LENGTH
        or not isinstance(raw_candidates, list)
        or not 1 <= len(raw_candidates) <= MAX_CANDIDATES
    ):
        raise ProviderRequestError("invalid_request")
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw_candidates:
        if not isinstance(item, dict):
            raise ProviderRequestError("invalid_request")
        candidate_id = item.get("candidate_id")
        text = item.get("text")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id.startswith("candidate_")
            or candidate_id in seen
            or not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_TEXT_LENGTH
        ):
            raise ProviderRequestError("invalid_request")
        seen.add(candidate_id)
        candidates.append((candidate_id, text))
    return query, candidates


def score_request(model: Any, request: object) -> dict[str, object]:
    query, candidates = validate_request(request)
    embeddings = model.encode(
        [
            f"query: {query}",
            *(f"passage: {text}" for _candidate_id, text in candidates),
        ],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    if len(embeddings) != len(candidates) + 1:
        raise ProviderRequestError("invalid_model_output")
    query_embedding = embeddings[0]
    scores = []
    for (candidate_id, _text), embedding in zip(
        candidates,
        embeddings[1:],
        strict=True,
    ):
        score = float(sum(float(left) * float(right) for left, right in zip(
            query_embedding,
            embedding,
            strict=True,
        )))
        if not math.isfinite(score) or not -1.0 <= score <= 1.0:
            raise ProviderRequestError("invalid_model_output")
        scores.append(
            {
                "candidate_id": candidate_id,
                "score": round(score, 6),
            }
        )
    return {
        "report_kind": "semantic_support_response",
        "report_version": 1,
        "model_fingerprint": MODEL_FINGERPRINT,
        "scores": scores,
    }


def health_response() -> dict[str, object]:
    return {
        "report_kind": "semantic_support_health_response",
        "report_version": 1,
        "status": "ready",
        "model_fingerprint": MODEL_FINGERPRINT,
    }


def failure_response() -> dict[str, object]:
    return {
        "report_kind": "semantic_support_response",
        "report_version": 1,
        "status": "failed",
        "model_fingerprint": MODEL_FINGERPRINT,
        "scores": [],
    }


def receive_request(connection: socket.socket) -> object:
    payload = bytearray()
    while not payload.endswith(b"\n"):
        chunk = connection.recv(MAX_REQUEST_BYTES)
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > MAX_REQUEST_BYTES:
            raise ProviderRequestError("request_too_large")
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProviderRequestError("invalid_request") from exc


def load_model(model_dir: Path):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        str(model_dir),
        device="cpu",
        local_files_only=True,
        trust_remote_code=False,
    )


def serve(socket_path: Path, model: Any) -> None:
    if socket_path.exists() or socket_path.is_symlink():
        raise ProviderStartupError("provider_socket_already_exists")
    if not socket_path.parent.is_dir():
        raise ProviderStartupError("provider_socket_parent_missing")

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
                            and request.get("report_kind")
                            == "semantic_support_health_request"
                            and request.get("model_fingerprint") == MODEL_FINGERPRINT
                        ):
                            response = health_response()
                        else:
                            response = score_request(model, request)
                    except (ProviderRequestError, OSError, ValueError):
                        response = failure_response()
                    connection.sendall(
                        json.dumps(
                            response,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                        + b"\n"
                    )
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        try:
            if socket_path.is_socket() and socket_path.lstat().st_uid == os.getuid():
                socket_path.unlink()
        except OSError:
            pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--model-dir", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        model_dir = Path(args.model_dir).expanduser()
        socket_path = Path(args.socket).expanduser()
        verify_runtime_versions()
        verify_model_artifacts(model_dir)
        model = load_model(model_dir)
        serve(socket_path, model)
        return 0
    except (ProviderStartupError, OSError) as exc:
        print(
            json.dumps(
                {
                    "report_kind": "semantic_support_provider_startup",
                    "status": "failed",
                    "reason": str(exc)
                    if isinstance(exc, ProviderStartupError)
                    else "provider_os_error",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
