# Codex paginated source adapter

The opt-in `codex-session` adapter keeps `source_identity` equal to
`codex-session:<SessionMeta.id>`. A paginated thread can have several physical
JSONL pages with that same logical owner. Each page is archived separately;
its `source_record_sha256` always hashes its complete physical file, including
compressed bytes for `.jsonl.zst`.

Pagination semantics follow the pinned Codex commit
`970111f6cb62cc02fe36a82ea7d71b37a2889c97`:

- [HistoryPosition and SessionMeta](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/protocol/src/protocol.rs)
  distinguish the stable thread owner from `history_base.thread_id`, a physical
  rollout locator.
- [Ordinal assignment](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/rollout/src/ordinal.rs)
  starts a root page at zero and a continuation at the inherited exclusive end.
- [Rollout filenames](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/rollout/src/rollout_file_name.rs)
  carry a thread UUID and, after an underscore, an optional distinct rollout UUID.
  Filenames supply locators; metadata independently verifies logical ownership.
- [Reference indexing](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/rollout/src/rollout_reference_index.rs)
  and the [seekable reader](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/rollout/src/seekable_reader.rs)
  resolve physical pages and address decoded JSONL bytes even for compressed files.

`source_record_io.py` owns structural validation and graph resolution. The
supported collection has one closed linear continuation chain per logical owner
and session root. It checks integer ordinals, consecutive ranges, globally unique
physical locators, physical cycles, and exact newline/ordinal prefix bounds.
A same-owner successor determines its parent's own effective prefix; the later
physical tail contributes no facts or evidence. A cross-owner reference fork
requires the canonical child header's `forked_from_id` to match the parent's
independently verified logical owner. Session roots may differ. Each foreign
reference prefix must fit inside the parent's current own view, including the
range determined by its own continuations. Foreign children do not truncate that
view, and several declared children may reference it. Reconstructing superseded
historical branches, competing heads/copies, and undeclared foreign edges remain
unsupported and fail closed.
No modification-time or filename-based owner selection is used.

Self-contained copied forks retain the first child header as canonical owner.
The pinned [copy writer](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/thread-store/src/live_thread.rs)
sets `subagent_history_start_ordinal` after the copied items, and the
[persistence policy](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/rollout/src/policy.rs)
retains ancestor session headers. Such headers must lie inside the copied prefix,
follow declared `forked_from_id` ancestry, and never replace the first header's
owner, session root, or active history base. Embedded ancestors' own session roots
or history-base fields describe their original context and do not add external
dependencies to this self-contained file. A positive copied prefix requires its
immediate parent header at ordinal 1; an incomplete copy fails closed. Embedded
ancestors' own copy boundaries keep their original coordinates when their items
are persisted in a new child, so they are not compared as child page ordinals.

Inventory IPC remains version 4 for pages. Internal manifests use version 5 when
inactive headers carry bounded pagination hints; manifest versions 1–4 and
inventory versions 2–3 remain readable. Existing cutoff, `include_existing`, and
enrollment rules choose seeds. Old moved/compressed files contribute only header
hints until a selected page references them or a stored physical mapping needs
them. Known page mappings refine an enrolled owner to its physical pages;
owner-only legacy enrollment without a mapping still fails closed on ambiguity.
Dependencies are resolved transitively across all configured roots. Unreferenced,
unregistered historical branches stay inactive, including branches sharing an
owner or first-header fingerprint. Selected or referenced duplicates still fail
closed. Header hints are rechecked against full source content before use. A
renamed legacy page without a header descriptor can still be found by exact
archived raw SHA equality; nonmatching inactive candidates are not parsed or
activated. Unknown mappings continue to fail closed.
The full transitive dependency closure reaches each target, including other
owners and those parents' own continuation chains across roots and project
boundaries. Only matching project pages are archived in that target. Physical
bytes, raw fingerprints, canonical headers, and each reference boundary are
verified for dependencies as well as archive candidates. Version 4 IPC carries
project paths as target-selection hints while source metadata is verified again.
An older/manual input omitting those hints remains readable when physical
metadata can be verified; if its snapshot becomes unavailable first, processing
blocks before enrolling an unknown dependency in the target's pending queue.
Ordinary single-file and generic adapters retain their previous
contracts. Scheduled terminal reports remain version 1.

Collection revalidation may use an uncompressed page's exact inventory-length
raw prefix when the current file has grown. That prefix must hash exactly to
the original inventory raw SHA; owner, physical descriptor, decoded bounds, and
all graph references are verified on those snapshot bytes. The row's original
size, mtime, hash, and range are retained, and appended bytes are never included.
This does not authorize target writes: the updater still checks the current
whole-file fingerprint and defers the owner and its dependent owners until a
fresh stable inventory can complete them. Changed old bytes, truncation, and
forged fingerprints fail closed. Compressed append is unsupported; `.jsonl.zst`
requires the original complete physical size and raw hash.

The additive `source_fragment` version 2 metadata records a canonical first-header
fingerprint, physical rollout locator, session root, history-base reference,
canonical `forked_from_id`, effective ordinal/byte bounds, physical bounds, and a
decoded-content digest. Version 1 descriptors and header hints remain readable;
actual physical headers supply the fork declaration before graph authorization.
The decoded digest proves page mappings after rename, append, or recompression;
it never replaces the raw source fingerprint. Archived and deferred descriptors
also prevent a missing known continuation from expanding a frozen parent prefix.
A fresh collection missing a known page blocks; a changing or unavailable page
in a supplied snapshot defers its owner group and transitive dependent owners
until a stable retry. Dependencies are rechecked after record preparation and
before archive writes; a successful parent never clears a child's pending work.

Replacement, deferred clearing, and limits operate per physical page. Legacy
archives can upgrade through verified owner/rollout agreement or exact archived
raw-content equality. A filename hint whose owner disagrees requires exact raw
proof. An arbitrary legacy path with changed bytes remains pending when no page
mapping can be proved, including on repeated retries: a new pending snapshot
cannot supply provenance for an older descriptor-less archive. Renamed referenced
pages require a stored mapping and an
unchanged previously observed decoded prefix; unknown mappings fail closed.

Source anchor version 1 stays unchanged: anchors identify the physical raw hash,
the original local JSONL line, and an event ordinal within that line. Top-level
pagination ordinals never become event ordinals. Source maps add the page
descriptor while retaining their original resolver contract. Diagnostics expose
only a fixed allowlist of inventory error codes, never source paths, IDs,
content, or arbitrary exception text.
