# ADR-001: Use Wide Hybrid Recall Before Evidence Authorization

## Status

Accepted for opt-in evaluation; `lexical_v1` remains the CLI compatibility
default until a frozen public and private holdout admits promotion.

## Date

2026-09-08

## Context

The production search path optimizes fail-closed answerability but loses useful
memories before evidence validation. Schema-compliant project memories store
project identity in `scope`, while project ranking previously inspected only
session-oriented project fields. Coarse topic deduplication and a 99-percent
relative-score cutoff could also collapse hundreds of project memories into a
very small candidate set. Unsegmented CJK clauses made exact lexical overlap
especially brittle.

Earlier experiments did not close the problem. Relaxing token support admitted
hard negatives. The V2.58 semantic candidate inspected only weak memories that
had already survived the lexical top five, so it could not repair no-hit or
pre-top-five losses.

## Decision

Introduce two additive retrieval modes while preserving `lexical_v1`:

- `hybrid_fts_v1` builds request-local SQLite FTS5 word and trigram indexes,
  fuses weighted lexical, BM25, and CJK-trigram rankings with reciprocal-rank
  fusion, and never changes answer authorization.
- `hybrid_v1` adds an optional local semantic provider. The provider embeds the
  full current memory index, retrieves a dense prefetch, and may rerank that
  prefetch with a cross-encoder. It returns bounded memory IDs and numeric
  scores only over a private Unix socket.

Candidate generation and authorization are separate contracts. Dense
similarity alone cannot support an answer. Semantic authorization requires a
separate reranker `support_score`, a configured threshold, active/current
lifecycle, automatic or explicit provenance, matching scope, and both summary
and evidence drill paths. Broad queries still require bounded decomposition.

Provider identity includes the model artifact manifests and prefix policy.
Search also verifies the current memory-index SHA-256, socket ownership and
permissions, response shape and size, result IDs, and score ranges. Any provider
failure falls back to lexical/FTS retrieval. Model dependencies and model files
remain outside the reusable core runtime and private archive.

The `using-my-precious` skill requests `hybrid_v1`; without a configured
provider this safely degrades to the local lexical/FTS channels. The direct CLI
keeps `lexical_v1` as its compatibility default during evaluation.

## Alternatives Considered

### Lower the lexical support threshold

Rejected because the V2.37 calibration recovered positives while losing the
required hard-negative rejection boundary.

### Apply one embedding threshold to lexical top five

Rejected as the target architecture because it cannot recover candidates that
the lexical stage never returned. This was the bounded V2.58 design.

### Make a cloud embedding API mandatory

Rejected because the archive is private, query-time network access is not
required, and the reusable skills must remain agent-neutral.

### Adopt GraphRAG immediately

Deferred. Graph traversal may later help relationship-heavy or corpus-global
questions, but it does not repair the current scope, CJK, candidate-pruning, or
atomic-evidence losses.

## Consequences

- Current-project memories survive early diversity and relative-score pruning.
- CJK and exact-identifier retrieval improve without a model dependency.
- Full semantic recall and reranking are available through an isolated,
  fingerprinted adapter.
- A running provider must be restarted after `index/memories.jsonl` changes;
  stale providers fail closed by index identity.
- The semantic operating threshold is model- and corpus-specific and must be
  admitted by calibration and a frozen holdout before default promotion.
- SQLite FTS5 work adds request latency while indexes remain ephemeral; a
  persistent, rebuildable cache may be considered only after profiling proves
  this is a material bottleneck.

## Sources

- SQLite FTS5 tokenizers and BM25: https://www.sqlite.org/fts5.html
- Sentence Transformers retrieve-and-rerank: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html
- SentenceTransformer encode API: https://www.sbert.net/docs/package_reference/sentence_transformer/model.html
- CrossEncoder usage: https://www.sbert.net/docs/cross_encoder/usage/usage.html
- Azure reciprocal-rank fusion: https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking
