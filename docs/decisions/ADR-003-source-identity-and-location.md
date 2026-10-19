# ADR-003: Separate source identity from its current location

Status: Accepted

A source path is a location, not a session identity. A pending retry that only
matches its former path cannot recover after a move. A timestamp high-water also
cannot prove that all older source identities were processed.

Deployments may explicitly register a source collection in
`config/source_locations.jsonl`:

```json
{"source_dir":"/path/to/active-records","relocation_dirs":["/path/to/archived-records"],"identity_adapter":"codex-session","enabled":true}
```

Each declared root is inventoried once per batch. Project filtering, disabled
projects, archive scopes and source partitions continue to apply. Roots must be
absolute and disjoint. The optional Codex adapter reads only authoritative
`session_meta.payload.id`; the reusable updater does not infer identities from
conversation text. Other runtimes retain the existing single-root behavior.

The metadata-only inventory uses version 3 for collections, with a physical
`source_root`, a relative path, and a namespaced `source_identity`. Legacy
single-root inventory version 2 and private manifest version 1 remain readable.
Collection manifests use version 2. The target independently validates root
containment, bytes, size, mtime, project membership, timestamp and embedded
identity before preparing output. Duplicate identities across physical locations
are ambiguous and block the collection before target updates.

Session metadata, source maps and future deferred rows persist identity. Pending
identity, changed content, a changed physical location, and an unseen identity
bypass timestamp high-water filtering. Path-only legacy Codex retries can use a
strict rollout filename UUID as a lookup hint; the selected file must verify it
in its embedded metadata. Arbitrary legacy filenames without saved identity
cannot safely establish lineage by name alone.

A stable replacement removes earlier entries for the same identity only within
the current archive scope and source partition. Source maps and raw references
point to the actual validated location. Changed or unavailable candidates retain
the original pending row and identity; successful processing clears all matching
pending aliases. No source is copied, restored or modified by this mechanism.
Existing redaction and durable-content selection still govern what is archived.
A permanently missing source stays pending; identity does not prove source
availability or archived freshness.

The scheduled relocation gate exercises real adapter publication, a committed
legacy queue, movement between inventory and materialization, fresh staging
replay, repeated renames, complete content hashes and one lineage per identity.

Codex may also compress archived sources as `.jsonl.zst`. Shared source I/O
identifies the logical format and decodes in memory; inventories and source maps
keep SHA-256, size and mtime tied to the physical compressed file. Event anchors
continue to address decoded JSONL lines. Original-event resolution verifies both
the physical digest and the logical event digest. Decoding requires Python 3.14's
`compression.zstd` or the optional `zstandard` package; unavailable codecs,
or malformed frames block rather than omit data.

Forked Codex logs can include ancestor headers. The first authoritative session
header identifies the owner; additional IDs must be reachable through explicit
`forked_from_id` links from that owner. Conflicting parent declarations, cycles
and unrelated headers fail closed. A parent header never changes ownership of
the child source record. Filename-based ownership inference remains confined to
legacy lookup hints.

An existing deployment may set `discover_after` to its activation time. Older
relocated/compressed records are selected by durable pending identity or an
identity already persisted by this updater; only their owner headers are probed
for this lookup. All records modified after activation remain discoverable,
including sessions first seen after a move. Ordinary uncompressed primary-root
discovery is unchanged. The activation boundary never advances as an archive
high-water mark. Omitting it inventories all declared history. This supports a
scoped legacy backfill without enrolling every historical compressed copy.

`index/source_identities.jsonl` enrolls all verified collection identities only
after collection preflight, including unchanged primary records. Enrollment is
selection metadata, never evidence of archival freshness. This lets an unchanged
legacy source move later without losing lookup eligibility. The scheduled
transaction publishes enrollment together with retry state and archive updates;
an interrupted unpublished staging clone cannot advance it independently.

With an activation boundary, private inventory manifest version 3 also carries
owner headers for older unmaterialized locations. Before enrollment or target
filtering, every selected identity is checked against all these physical
locations, including identities first seen in the current primary inventory.
Unselected historical identities do not establish freshness or enter enrollment.
Starting from a secondary root validates its entire owning collection first and
then dispatches only that root's requested inventory. No root is rescanned.
Legacy entries already moved before activation, with neither pending state nor
persisted identity, require explicit historical enrollment or a full-history run;
the activation boundary is not a blanket historical source-map repair.
