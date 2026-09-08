# ADR-002: Deploy the Semantic Read Runtime from the Setup Skill

## Status

Accepted.

## Date

2026-09-08

## Context

ADR-001 introduced an optional local semantic retrieval provider, but source
code and a provider protocol are not enough for useful recall. A working
deployment also needs a Python environment, pinned model artifacts, private
runtime directories, provider identity in the My Precious config, persistent
process management, health verification, index refresh, and rollback.

Those responsibilities do not belong to scheduled archive transactions. The
scheduled writer must remain a single governed archive mutation path and must
not install packages, download models, rewrite runtime configuration, or manage
services. They also do not belong to `using-my-precious`, whose responsibility
is bounded read-path consumption.

## Decision

Make semantic runtime provisioning an explicit optional phase of
`setup-my-precious`, implemented by
`skills/setup-my-precious/scripts/setup_semantic_retrieval.py`.

The deployer exposes four actions:

- `--plan`: read-only aggregate inventory of intended external writes;
- `--install`: provision pinned dependencies/models, validate provider
  identity, install and health-check the selected service, then atomically
  enable private config;
- `--check`: read-only end-to-end runtime readiness verification;
- `--disable`: unload the service and set provider `enabled: false` without
  deleting environments, models, logs, archive data, or configuration history.

The default persistent layout is outside both repositories:

- runtime and model data under `~/.local/share/my-precious/`;
- socket and logs under `~/.local/state/my-precious/`;
- discovery configuration under `~/.config/my-precious/`;
- a user LaunchAgent plist under `~/Library/LaunchAgents/` on macOS.

The installer uses `uv` with an exact requirements file and downloads only an
allowlisted file set from pinned Hugging Face revisions. Model installation may
use the network; the running provider forces offline mode. Runtime and state
directories are mode `0700`; config, backup, plist, and socket are mode `0600`.
The provider fingerprint binds model manifests and prefix policy. Search also
binds each response to the current memory-index SHA-256.

The provider watches the memory index while idle. When the index changes, it
rebuilds the in-memory corpus embeddings and advances its index identity. A
query arriving before refresh completes safely falls back to lexical/FTS
retrieval.

On macOS, launchd is the supported persistent backend. The plist uses absolute
`ProgramArguments`, `KeepAlive`, explicit offline environment variables, and
logs outside the repositories. Other platforms may use `--service-backend
none` and manage the printed provider command externally; no system-wide or
privileged service is installed.

## Alternatives Considered

### Install from scheduled memory updates

Rejected. It would mix package/network/service mutations with the governed
single-writer archive transaction and make scheduled behavior non-deterministic.

### Put the virtual environment and models in the deployment archive

Rejected. Large generated artifacts would pollute Git, expand the private
publication surface, and violate the archive/source boundary.

### Let every agent start an ad-hoc provider

Rejected. Startup is expensive, concurrent processes waste memory, and model
or index identity would be difficult to audit.

### Delete everything during rollback

Rejected. Disabling config and unloading the service is faster, reversible,
and leaves model artifacts available for diagnosis or re-enable.

## Consequences

- A single setup workflow can bring storage, tools, and semantic recall to an
  operational state.
- Production configuration is enabled only after health verification.
- Login persistence and crash restart are delegated to launchd on macOS.
- Provider model/runtime storage consumes local disk and must be managed
  separately from archive retention.
- Updating pinned dependencies, model revisions, provider protocol, or service
  layout requires a new reviewed setup release and renewed fingerprint.
- Deployment remains explicit: setup must show a plan and obtain approval
  before enabling the service.

## Sources

- Apple `launchd.plist(5)` and the installed `launchctl` help for
  `bootstrap`, `bootout`, `kickstart`, and `print`.
- uv virtual environment and pip interfaces: https://docs.astral.sh/uv/reference/cli/
- Hugging Face snapshot download API: https://huggingface.co/docs/huggingface_hub/package_reference/file_download
