import importlib.util
import contextlib
import io
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


PROVIDER_SCRIPT = Path(
    "templates/agent-memory-repo/tools/semantic_retrieval_provider.py"
).resolve()


def load_provider_module():
    spec = importlib.util.spec_from_file_location(
        "semantic_retrieval_provider_under_test",
        PROVIDER_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeEmbeddingModel:
    def encode(self, texts, **_kwargs):
        rows = []
        for index, _text in enumerate(texts):
            row = np.zeros(3, dtype=np.float32)
            row[index % 3] = 1.0
            rows.append(row)
        return np.asarray(rows)


class FakeRerankerModel:
    def predict(self, pairs, **_kwargs):
        return np.asarray(
            [0.95 if "secondary" in document else 0.20 for _query, document in pairs],
            dtype=np.float32,
        )


def make_startup_fixture(root):
    repo = root / "repo"
    index = repo / "index"
    index.mkdir(parents=True)
    (index / "memories.jsonl").write_text(
        '{"memory_id":"mem_one","text":"a memory"}\n', encoding="utf-8"
    )
    model = root / "model"
    model.mkdir()
    (model / "config.json").write_text("{}\n", encoding="utf-8")
    return ["--repo", str(repo), "--embedding-model-dir", str(model)]


def run_main_without_models(provider, argv, *, load_models=None):
    output = io.StringIO()
    errors = io.StringIO()
    with (
        mock.patch.object(provider, "directory_manifest_sha256", return_value="a" * 64) as manifest,
        mock.patch.object(
            provider, "load_models", side_effect=load_models or AssertionError("models loaded")
        ) as models,
        mock.patch.object(
            provider, "build_corpus_embeddings", side_effect=AssertionError("embeddings built")
        ) as embeddings,
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        result = provider.main(argv)
    return result, output.getvalue(), errors.getvalue(), manifest, models, embeddings


FAKE_PROVIDER = """
import importlib.util
import os
import sys
import time
import numpy as np

spec = importlib.util.spec_from_file_location('semantic_provider_child', sys.argv[1])
provider = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = provider
spec.loader.exec_module(provider)
class FakeModel:
    def encode(self, texts, **kwargs):
        return np.ones((len(texts), 3), dtype=np.float32)
provider.directory_manifest_sha256 = lambda path: 'a' * 64
def fake_load_models(*args, **kwargs):
    marker = os.environ.get('MP_TEST_MODEL_MARKER')
    if marker:
        open(marker, 'w').close()
        deadline = time.monotonic() + 5
        while not os.path.exists(marker + '.release') and time.monotonic() < deadline:
            time.sleep(.01)
    return FakeModel(), None
provider.load_models = fake_load_models
sys.exit(provider.main(sys.argv[2:]))
"""


def start_fake_provider(argv, *, model_marker=None):
    environment = os.environ.copy()
    if model_marker is not None:
        environment["MP_TEST_MODEL_MARKER"] = str(model_marker)
    return subprocess.Popen(
        [sys.executable, "-u", "-c", FAKE_PROVIDER, str(PROVIDER_SCRIPT), *argv],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def startup_message(process):
    readable, _, _ = select.select([process.stdout], [], [], 5)
    if not readable:
        raise AssertionError("provider emitted no startup message")
    line = process.stdout.readline()
    if not line:
        raise AssertionError(f"provider exited without startup message: {process.stderr.read()}")
    return json.loads(line)


def wait_for_health(socket_path, fingerprint):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(socket_path))
                client.sendall(
                    json.dumps(
                        {
                            "report_kind": "memory_semantic_retrieval_health_request",
                            "provider_fingerprint": fingerprint,
                        }
                    ).encode() + b"\n"
                )
                response = client.recv(4096)
            payload = json.loads(response)
            if payload.get("status") == "ready":
                return payload
        except (OSError, ValueError):
            time.sleep(0.02)
    raise AssertionError("provider socket never became healthy")


class SemanticRetrievalProviderTests(unittest.TestCase):
    def test_socket_conflicts_fail_before_model_work_and_preserve_path(self):
        provider = load_provider_module()
        for kind in (
            "regular", "symlink", "active", "active_full", "public_parent", "symlink_parent"
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(
                prefix="mp-", dir="/tmp"
            ) as tmpdir:
                root = Path(tmpdir)
                argv = make_startup_fixture(root)
                parent = root / "public" if kind == "public_parent" else root
                if kind == "public_parent":
                    parent.mkdir(mode=0o755)
                    parent.chmod(0o755)
                elif kind == "symlink_parent":
                    target_parent = root / "actual"
                    target_parent.mkdir()
                    parent = root / "link"
                    parent.symlink_to(target_parent, target_is_directory=True)
                socket_path = parent / "provider.sock"
                listener = None
                queued = None
                if kind == "regular":
                    socket_path.write_text("keep me", encoding="utf-8")
                elif kind == "symlink":
                    target = root / "target"
                    target.write_text("keep me", encoding="utf-8")
                    socket_path.symlink_to(target)
                elif kind in ("active", "active_full"):
                    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    listener.bind(str(socket_path))
                    socket_path.chmod(0o600)
                    listener.listen(1)
                    if kind == "active_full":
                        queued = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        queued.connect(str(socket_path))
                try:
                    original = (
                        socket_path.lstat()
                        if kind not in ("public_parent", "symlink_parent")
                        else None
                    )
                    result, output, errors, manifest, models, embeddings = (
                        run_main_without_models(
                            provider, [*argv, "--socket", str(socket_path)]
                        )
                    )
                    self.assertEqual(result, 1)
                    self.assertEqual(output, "")
                    self.assertEqual(json.loads(errors)["status"], "failed")
                    manifest.assert_not_called()
                    models.assert_not_called()
                    embeddings.assert_not_called()
                    if original is not None:
                        self.assertEqual(socket_path.lstat().st_ino, original.st_ino)
                    else:
                        self.assertFalse(socket_path.exists())
                        if kind == "symlink_parent":
                            self.assertTrue(parent.is_symlink())
                    if kind == "regular":
                        self.assertEqual(socket_path.read_text(), "keep me")
                    elif kind == "symlink":
                        self.assertTrue(socket_path.is_symlink())
                        self.assertEqual(target.read_text(), "keep me")
                    elif kind in ("active", "active_full"):
                        listener.settimeout(1)
                        probe_connection, _ = listener.accept()
                        probe_connection.close()
                        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                            client.connect(str(socket_path))
                finally:
                    if queued is not None:
                        queued.close()
                    if listener is not None:
                        listener.close()

    def test_model_initialization_failure_releases_reserved_socket(self):
        provider = load_provider_module()
        with tempfile.TemporaryDirectory(prefix="mp-", dir="/tmp") as tmpdir:
            root = Path(tmpdir)
            argv = make_startup_fixture(root)
            socket_path = root / "provider.sock"
            observed_reservation = []

            def fail_during_model_load(*_args, **_kwargs):
                observed_reservation.append(socket_path.is_socket())
                raise provider.ProviderStartupError("model_load_failed")

            result, output, errors, _manifest, models, embeddings = (
                run_main_without_models(
                    provider,
                    [*argv, "--socket", str(socket_path)],
                    load_models=fail_during_model_load,
                )
            )
            self.assertEqual(result, 1)
            self.assertEqual(output, "")
            self.assertIn("model_load_failed", errors)
            models.assert_called_once()
            embeddings.assert_not_called()
            self.assertEqual(observed_reservation, [True])
            self.assertFalse(socket_path.exists())

    def test_killed_provider_socket_is_recovered_and_normal_stop_cleans_up(self):
        with tempfile.TemporaryDirectory(prefix="mp-", dir="/tmp") as tmpdir:
            root = Path(tmpdir)
            argv = make_startup_fixture(root)
            socket_path = root / "provider.sock"
            argv.extend(["--socket", str(socket_path)])
            first = start_fake_provider(argv)
            replacement = None
            try:
                first_ready = startup_message(first)
                self.assertEqual(first_ready["status"], "ready")
                wait_for_health(socket_path, first_ready["provider_fingerprint"])

                duplicate = start_fake_provider(argv)
                duplicate_output, duplicate_errors = duplicate.communicate(timeout=5)
                self.assertEqual(duplicate.returncode, 1)
                self.assertEqual(duplicate_output, "")
                self.assertEqual(json.loads(duplicate_errors)["status"], "failed")
                wait_for_health(socket_path, first_ready["provider_fingerprint"])

                first.kill()
                first.wait(timeout=5)
                self.assertTrue(socket_path.is_socket())
                replacement = start_fake_provider(argv)
                replacement_ready = startup_message(replacement)
                self.assertEqual(replacement_ready["status"], "ready")
                wait_for_health(socket_path, replacement_ready["provider_fingerprint"])

                replacement.send_signal(signal.SIGTERM)
                replacement.wait(timeout=5)
                self.assertEqual(replacement.returncode, 0)
                self.assertFalse(socket_path.exists())
            finally:
                for process in (first, replacement):
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                        process.stdout.close()
                        process.stderr.close()

    def test_concurrent_start_does_not_steal_or_remove_reserved_socket(self):
        with tempfile.TemporaryDirectory(prefix="mp-", dir="/tmp") as tmpdir:
            root = Path(tmpdir)
            argv = make_startup_fixture(root)
            socket_path = root / "provider.sock"
            argv.extend(["--socket", str(socket_path)])
            marker = root / "model-loading"
            first = start_fake_provider(argv, model_marker=marker)
            second = None
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    self.assertIsNone(first.poll(), "first provider exited before loading")
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), "first provider did not reach model loading")
                self.assertTrue(socket_path.is_socket(), "endpoint was not reserved before loading")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    client.connect(str(socket_path))
                self.assertFalse(
                    select.select([first.stdout], [], [], 0.05)[0],
                    "ready was emitted before model initialization completed",
                )

                second = start_fake_provider(argv)
                second_output, second_errors = second.communicate(timeout=5)
                self.assertEqual(second.returncode, 1)
                self.assertEqual(second_output, "")
                self.assertEqual(json.loads(second_errors)["status"], "failed")
                self.assertTrue(socket_path.is_socket())

                Path(str(marker) + ".release").touch()
                first_ready = startup_message(first)
                self.assertEqual(first_ready["status"], "ready")
                wait_for_health(socket_path, first_ready["provider_fingerprint"])
                first.send_signal(signal.SIGTERM)
                first.wait(timeout=5)
                self.assertEqual(first.returncode, 0)
                self.assertFalse(socket_path.exists())
            finally:
                for process in (first, second):
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                        process.stdout.close()
                        process.stderr.close()

    def test_inconclusive_holder_check_preserves_stale_socket_before_model_work(self):
        provider = load_provider_module()
        outcomes = (
            subprocess.CompletedProcess([], 0, b"p123\n", b""),
            subprocess.CompletedProcess([], 1, b"", b"inspection incomplete"),
            subprocess.TimeoutExpired([], 3),
        )
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__), tempfile.TemporaryDirectory(
                prefix="mp-", dir="/tmp"
            ) as tmpdir:
                root = Path(tmpdir)
                argv = make_startup_fixture(root)
                socket_path = root / "provider.sock"
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
                    stale.bind(str(socket_path))
                socket_path.chmod(0o600)
                inode = socket_path.lstat().st_ino
                query = (
                    mock.patch.object(provider.subprocess, "run", side_effect=outcome)
                    if isinstance(outcome, Exception)
                    else mock.patch.object(provider.subprocess, "run", return_value=outcome)
                )
                with mock.patch.object(provider.sys, "platform", "darwin"), query:
                    result, output, _errors, manifest, models, embeddings = (
                        run_main_without_models(provider, [*argv, "--socket", str(socket_path)])
                    )
                self.assertEqual(result, 1)
                self.assertEqual(output, "")
                self.assertEqual(socket_path.lstat().st_ino, inode)
                manifest.assert_not_called()
                models.assert_not_called()
                embeddings.assert_not_called()

    def test_sigterm_during_initialization_releases_reserved_socket(self):
        with tempfile.TemporaryDirectory(prefix="mp-", dir="/tmp") as tmpdir:
            root = Path(tmpdir)
            argv = make_startup_fixture(root)
            socket_path = root / "provider.sock"
            marker = root / "model-loading"
            child = start_fake_provider([*argv, "--socket", str(socket_path)], model_marker=marker)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    self.assertIsNone(child.poll())
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                self.assertTrue(socket_path.is_socket())
                child.send_signal(signal.SIGTERM)
                output, _errors = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(output, "")
                self.assertFalse(socket_path.exists())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stdout.close()
                child.stderr.close()

    def test_provider_fingerprint_is_deterministic_and_prefix_sensitive(self):
        provider = load_provider_module()

        first = provider.provider_fingerprint(
            embedding_manifest_sha256="a" * 64,
            reranker_manifest_sha256="b" * 64,
            query_prefix="query: ",
            document_prefix="passage: ",
        )
        second = provider.provider_fingerprint(
            embedding_manifest_sha256="a" * 64,
            reranker_manifest_sha256="b" * 64,
            query_prefix="query: ",
            document_prefix="passage: ",
        )
        changed = provider.provider_fingerprint(
            embedding_manifest_sha256="a" * 64,
            reranker_manifest_sha256="b" * 64,
            query_prefix="search: ",
            document_prefix="passage: ",
        )

        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_load_corpus_builds_contextual_units_without_raw_refs(self):
        provider = load_provider_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "memories.jsonl"
            index_path.write_text(
                json.dumps(
                    {
                        "memory_id": "mem_target",
                        "scope": "project:demo",
                        "topic": "retrieval",
                        "text": "Use evidence-bound memory nodes.",
                        "rationale": "Preserve provenance.",
                        "tags": ["memory", "retrieval"],
                        "raw_refs": [{"path": "private.jsonl", "anchor": "secret"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            corpus = provider.load_corpus(index_path)

        self.assertEqual(len(corpus), 1)
        self.assertEqual(corpus[0].memory_id, "mem_target")
        self.assertIn("scope: project:demo", corpus[0].text)
        self.assertIn("memory: Use evidence-bound memory nodes.", corpus[0].text)
        self.assertNotIn("private.jsonl", corpus[0].text)
        self.assertNotIn("secret", corpus[0].text)

    def test_load_corpus_rejects_duplicate_memory_ids(self):
        provider = load_provider_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "memories.jsonl"
            index_path.write_text(
                '{"memory_id":"mem_duplicate","text":"first"}\n'
                '{"memory_id":"mem_duplicate","text":"second"}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                provider.ProviderStartupError,
                "memory_index_duplicate_id",
            ):
                provider.load_corpus(index_path)

    def test_build_corpus_embeddings_uses_document_prefix(self):
        provider = load_provider_module()
        corpus = [provider.CorpusEntry(memory_id="mem_target", text="Durable memory")]
        model = FakeEmbeddingModel()

        embeddings = provider.build_corpus_embeddings(
            model,
            corpus,
            document_prefix="passage: ",
            batch_size=8,
        )

        self.assertEqual(embeddings.shape, (1, 3))

    def test_refresh_provider_state_rebuilds_changed_memory_index(self):
        provider = load_provider_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = Path(tmpdir) / "memories.jsonl"
            index_path.write_text(
                '{"memory_id":"mem_first","text":"first memory"}\n',
                encoding="utf-8",
            )
            model = FakeEmbeddingModel()
            corpus = provider.load_corpus(index_path)
            state = provider.ProviderState(
                identity=provider.ProviderIdentity(
                    fingerprint="f" * 64,
                    index_sha256=provider.file_sha256(index_path),
                ),
                corpus=corpus,
                corpus_embeddings=provider.build_corpus_embeddings(
                    model,
                    corpus,
                    document_prefix="passage: ",
                    batch_size=8,
                ),
                embedding_model=model,
                reranker_model=None,
                query_prefix="query: ",
                batch_size=8,
                index_path=index_path,
                document_prefix="passage: ",
                index_signature=provider.memory_index_signature(index_path),
            )
            old_sha256 = state.identity.index_sha256
            index_path.write_text(
                '{"memory_id":"mem_first","text":"first memory"}\n'
                '{"memory_id":"mem_second","text":"second memory"}\n',
                encoding="utf-8",
            )

            changed = provider.refresh_provider_state_if_changed(state)

        self.assertTrue(changed)
        self.assertEqual(len(state.corpus), 2)
        self.assertNotEqual(state.identity.index_sha256, old_sha256)
        self.assertEqual(state.corpus_embeddings.shape, (2, 3))

    def test_score_request_retrieves_then_reranks_eligible_memories(self):
        provider = load_provider_module()
        corpus = [
            provider.CorpusEntry(memory_id="mem_primary", text="primary memory"),
            provider.CorpusEntry(memory_id="mem_secondary", text="secondary memory"),
            provider.CorpusEntry(memory_id="mem_other", text="other memory"),
        ]
        embedding_model = FakeEmbeddingModel()
        state = provider.ProviderState(
            identity=provider.ProviderIdentity(
                fingerprint="f" * 64,
                index_sha256="a" * 64,
            ),
            corpus=corpus,
            corpus_embeddings=provider.build_corpus_embeddings(
                embedding_model,
                corpus,
                document_prefix="passage: ",
                batch_size=8,
            ),
            embedding_model=embedding_model,
            reranker_model=FakeRerankerModel(),
            query_prefix="query: ",
            batch_size=8,
        )
        request = {
            "report_kind": provider.REQUEST_KIND,
            "report_version": provider.REPORT_VERSION,
            "provider_fingerprint": state.identity.fingerprint,
            "index_sha256": state.identity.index_sha256,
            "query": "find the durable decision",
            "max_results": 2,
            "eligible_memory_ids": [entry.memory_id for entry in corpus],
        }

        response = provider.score_request(state, request)

        self.assertEqual(response["report_kind"], provider.RESPONSE_KIND)
        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["results"][0]["memory_id"], "mem_secondary")
        self.assertEqual(response["results"][0]["support_score"], 0.95)

    def test_validate_request_rejects_stale_index_identity(self):
        provider = load_provider_module()
        corpus = [provider.CorpusEntry(memory_id="mem_target", text="target")]
        model = FakeEmbeddingModel()
        state = provider.ProviderState(
            identity=provider.ProviderIdentity(
                fingerprint="f" * 64,
                index_sha256="a" * 64,
            ),
            corpus=corpus,
            corpus_embeddings=provider.build_corpus_embeddings(
                model,
                corpus,
                document_prefix="passage: ",
                batch_size=8,
            ),
            embedding_model=model,
            reranker_model=None,
            query_prefix="query: ",
            batch_size=8,
        )

        with self.assertRaises(provider.ProviderRequestError):
            provider.validate_request(
                {
                    "report_kind": provider.REQUEST_KIND,
                    "report_version": provider.REPORT_VERSION,
                    "provider_fingerprint": state.identity.fingerprint,
                    "index_sha256": "0" * 64,
                    "query": "target",
                    "max_results": 1,
                    "eligible_memory_ids": ["mem_target"],
                },
                state,
            )

    def test_print_fingerprint_does_not_load_models_or_render_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "agent-memory"
            model = root / "embedding-model"
            repo.mkdir()
            model.mkdir()
            (model / "config.json").write_text("{}\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROVIDER_SCRIPT),
                    "--repo",
                    str(repo),
                    "--embedding-model-dir",
                    str(model),
                    "--print-fingerprint",
                ],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["report_kind"],
            "memory_semantic_retrieval_provider_identity",
        )
        self.assertRegex(payload["provider_fingerprint"], r"^[0-9a-f]{64}$")
        self.assertNotIn(str(root), result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
