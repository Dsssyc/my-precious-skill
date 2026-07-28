import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


PROVIDER_SCRIPT = Path(
    "templates/agent-memory-repo/tools/semantic_support_provider.py"
).resolve()
REQUIREMENTS_FILE = Path(
    "templates/agent-memory-repo/tools/semantic_support_provider_requirements.txt"
).resolve()


def load_provider_module():
    spec = importlib.util.spec_from_file_location(
        "semantic_support_provider_under_test",
        PROVIDER_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeModel:
    def encode(self, values, **kwargs):
        if kwargs != {
            "normalize_embeddings": True,
            "convert_to_numpy": True,
        }:
            raise AssertionError(f"unexpected encode options: {kwargs}")
        if values != [
            "query: How should the artifact be handed off?",
            "passage: Use one reusable plain-text block.",
            "passage: Use a chronological numbered list.",
        ]:
            raise AssertionError(f"unexpected provider input: {values}")
        return [
            [1.0, 0.0],
            [0.9, math.sqrt(1.0 - 0.9**2)],
            [0.7, math.sqrt(1.0 - 0.7**2)],
        ]


class SemanticSupportProviderTests(unittest.TestCase):
    def test_pinned_identity_matches_the_search_runtime_contract(self):
        provider = load_provider_module()

        self.assertEqual(
            provider.MODEL_ID,
            "intfloat/multilingual-e5-small",
        )
        self.assertEqual(
            provider.MODEL_REVISION,
            "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        )
        self.assertEqual(
            provider.MODEL_MANIFEST_SHA256,
            "8a945b5d9dde256c5bb6f0274845ac4d7a42e9a02b1e0ac76da66972d32299bb",
        )
        self.assertEqual(
            provider.MODEL_FINGERPRINT,
            "89c7223e22f226e5142b3ebc9360f0127b436dc88ba8684922b55dbdabcd6437",
        )
        self.assertEqual(
            REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines(),
            [
                "huggingface-hub==1.25.1",
                "numpy==2.5.1",
                "sentence-transformers==5.6.0",
                "torch==2.13.0",
                "transformers==5.14.1",
            ],
        )

    def test_provider_scores_bounded_prefixed_pairs_without_echoing_content(self):
        provider = load_provider_module()
        request = {
            "report_kind": "semantic_support_request",
            "report_version": 1,
            "model_fingerprint": provider.MODEL_FINGERPRINT,
            "query": "How should the artifact be handed off?",
            "candidates": [
                {
                    "candidate_id": "candidate_1",
                    "text": "Use one reusable plain-text block.",
                },
                {
                    "candidate_id": "candidate_2",
                    "text": "Use a chronological numbered list.",
                },
            ],
        }

        response = provider.score_request(FakeModel(), request)

        self.assertEqual(response["report_kind"], "semantic_support_response")
        self.assertEqual(response["model_fingerprint"], provider.MODEL_FINGERPRINT)
        self.assertEqual(
            response["scores"],
            [
                {"candidate_id": "candidate_1", "score": 0.9},
                {"candidate_id": "candidate_2", "score": 0.7},
            ],
        )
        rendered = json.dumps(response, sort_keys=True)
        self.assertNotIn(request["query"], rendered)
        self.assertNotIn(request["candidates"][0]["text"], rendered)

    def test_provider_rejects_unbounded_duplicate_and_wrong_fingerprint_requests(self):
        provider = load_provider_module()
        base = {
            "report_kind": "semantic_support_request",
            "report_version": 1,
            "model_fingerprint": provider.MODEL_FINGERPRINT,
            "query": "How should output be arranged?",
            "candidates": [
                {"candidate_id": "candidate_1", "text": "Use plain text."},
            ],
        }
        invalid_requests = [
            {**base, "model_fingerprint": "wrong"},
            {
                **base,
                "candidates": base["candidates"] * 6,
            },
            {
                **base,
                "candidates": [
                    {"candidate_id": "candidate_1", "text": "First."},
                    {"candidate_id": "candidate_1", "text": "Second."},
                ],
            },
        ]

        for request in invalid_requests:
            with self.subTest(request=request):
                with self.assertRaises(provider.ProviderRequestError):
                    provider.validate_request(request)

    def test_model_artifact_verification_fails_closed_without_rendering_a_path(self):
        provider = load_provider_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(provider.ProviderStartupError) as raised:
                provider.verify_model_artifacts(Path(tmpdir))

        self.assertEqual(str(raised.exception), "model_artifact_manifest_mismatch")
        self.assertNotIn(tmpdir, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
