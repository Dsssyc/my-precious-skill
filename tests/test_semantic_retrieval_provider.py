import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


class SemanticRetrievalProviderTests(unittest.TestCase):
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
