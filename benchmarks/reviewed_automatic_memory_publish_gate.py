#!/usr/bin/env python3
"""Gate reviewed automatic-memory publication through a packaged Git lifecycle."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "reviewed_automatic_memory_publish_gate"
DEFAULT_ALLOWED_ROOTS = (
    "INDEX.md",
    "config/projects.jsonl",
    "index",
    "daily",
    "memories/explicit.jsonl",
    "sessions",
)
REVIEWED_MEMORY_FILES = (
    "memories/global.jsonl",
    "memories/domains.jsonl",
    "memories/projects.jsonl",
)
FAKE_KEY = "sk-" + ("reviewedsynthetic" * 2)
NOISE_SENTINEL = "SYNTHETIC_REVIEWED_MEMORY_NOISE"
READINESS_SENTINEL = "SYNTHETIC_REVIEWED_READINESS_NOISE"


class GateFailure(RuntimeError):
    def __init__(self, stage: str, reason: str, returncode: int | None = None):
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def to_report(self) -> dict[str, object]:
        report: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            report["returncode"] = self.returncode
        return report


@dataclass(frozen=True)
class ArchiveFixture:
    repo: Path
    remote: Path
    initial_head: str


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def require(command: list[str], stage: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = run(command, cwd=cwd)
    if result.returncode:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result


def setup_git_archive(case_root: Path) -> ArchiveFixture:
    repo = case_root / "agent-memory"
    remote = case_root / "remote.git"
    require(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(repo),
            "--mode",
            "local",
            "--skip-config",
        ],
        "setup_archive",
    )
    require(["git", "init", "--bare", "--initial-branch=main", str(remote)], "init_remote")
    require(["git", "init", "--initial-branch=main"], "init_archive_git", cwd=repo)
    require(["git", "config", "user.email", "synthetic@example.invalid"], "git_email", cwd=repo)
    require(["git", "config", "user.name", "Synthetic Gate"], "git_name", cwd=repo)
    require(["git", "add", "."], "initial_stage", cwd=repo)
    require(["git", "commit", "-m", "Initialize synthetic archive"], "initial_commit", cwd=repo)
    require(["git", "remote", "add", "origin", str(remote)], "add_remote", cwd=repo)
    require(["git", "push", "-u", "origin", "main"], "initial_push", cwd=repo)
    initial_head = require(["git", "rev-parse", "HEAD"], "initial_head", cwd=repo).stdout.strip()
    return ArchiveFixture(repo, remote, initial_head)


def make_node(
    repo: Path,
    memory_id: str,
    *,
    layer: str = "global",
    text: str = "Reviewed automatic memory publication preserves durable support evidence.",
) -> dict[str, object]:
    entry_dir = repo / f"sessions/2026/07/10/{memory_id}"
    entry_dir.mkdir(parents=True, exist_ok=True)
    summary_path = entry_dir / "summary.md"
    evidence_path = entry_dir / "evidence.md"
    summary_path.write_text(f"# Summary\n\n{text}\n", encoding="utf-8")
    evidence_path.write_text(f"ev_{memory_id}: Synthetic evidence for durable support.\n", encoding="utf-8")
    return {
        "memory_id": memory_id,
        "layer": layer,
        "scope": "*" if layer == "global" else f"synthetic-{layer}",
        "topic": "durable-publication",
        "text": text,
        "rationale": "Synthetic deterministic publication fixture.",
        "source": "automatic",
        "confidence": "high",
        "persistence": "normal",
        "support_count": 1,
        "first_seen": "2026-07-10T00:00:00Z",
        "last_seen": "2026-07-10T00:00:00Z",
        "derived_from": [summary_path.relative_to(repo).as_posix()],
        "evidence_refs": [
            {
                "path": evidence_path.relative_to(repo).as_posix(),
                "quote_id": f"ev_{memory_id}",
            }
        ],
        "raw_refs": [],
        "supersedes": [],
        "superseded_by": None,
        "tags": ["durable-publication"],
    }


def write_nodes(repo: Path, nodes: list[dict[str, object]]) -> None:
    layer_files = {
        "global": "global.jsonl",
        "domain": "domains.jsonl",
        "project": "projects.jsonl",
    }
    for layer, filename in layer_files.items():
        layer_nodes = [node for node in nodes if node.get("layer") == layer]
        if layer_nodes:
            payload = "".join(json.dumps(node, sort_keys=True) + "\n" for node in layer_nodes)
            (repo / "memories" / filename).write_text(payload, encoding="utf-8")
    index_payload = "".join(json.dumps(node, sort_keys=True) + "\n" for node in nodes)
    (repo / "index/memories.jsonl").write_text(index_payload, encoding="utf-8")


def write_safe_nodes(repo: Path, *, all_layers: bool) -> list[dict[str, object]]:
    layers = ("global", "domain", "project") if all_layers else ("global",)
    nodes = [make_node(repo, f"mem_reviewed_{layer}", layer=layer) for layer in layers]
    write_nodes(repo, nodes)
    return nodes


def run_sync(
    repo: Path,
    *,
    reviewed: bool,
    dry_run: bool = True,
    push: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(repo / "tools/sync_memory_archive.py"), "--memory-repo", str(repo)]
    if reviewed:
        command.append("--include-reviewed-memory-nodes")
    if dry_run:
        command.append("--dry-run")
    if push:
        command.append("--push")
    return run(command, cwd=repo, env=env)


def command_text(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def allowed_committed_path(path: str) -> bool:
    if path in REVIEWED_MEMORY_FILES:
        return True
    return any(path == root or path.startswith(f"{root}/") for root in DEFAULT_ALLOWED_ROOTS)


def git_trace_environment(root: Path) -> tuple[dict[str, str], Path]:
    real_git = shutil.which("git")
    if real_git is None:
        raise GateFailure("git_trace", "git_not_found")
    wrapper_dir = root / "git-wrapper"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    trace_path = root / "git-invocations.jsonl"
    wrapper = wrapper_dir / "git"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        f"REAL_GIT = {real_git!r}\n"
        "with open(os.environ['MY_PRECIOUS_GIT_TRACE'], 'a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "raise SystemExit(subprocess.run([REAL_GIT, *sys.argv[1:]], check=False).returncode)\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = os.environ.copy()
    env["MY_PRECIOUS_GIT_TRACE"] = str(trace_path)
    env["PATH"] = f"{wrapper_dir}{os.pathsep}{env.get('PATH', '')}"
    return env, trace_path


def traced_add_invocations(trace_path: Path) -> list[list[str]]:
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise GateFailure("git_trace", "trace_unreadable") from exc
    invocations: list[list[str]] = []
    for line in lines:
        try:
            args = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GateFailure("git_trace", "trace_invalid_json") from exc
        if isinstance(args, list) and all(isinstance(arg, str) for arg in args) and args[:1] == ["add"]:
            invocations.append(args)
    return invocations


def run_default_rejection(root: Path) -> dict[str, object]:
    fixture = setup_git_archive(root / "default-rejection")
    write_safe_nodes(fixture.repo, all_layers=True)
    result = run_sync(fixture.repo, reviewed=False, push=True)
    output = command_text(result)
    passed = result.returncode != 0 and all(path in output for path in REVIEWED_MEMORY_FILES)
    return {"case": "default_rejects_automatic_memory", "passed": passed, "expected": "reject"}


def run_safe_dry_run(root: Path) -> tuple[dict[str, object], bool]:
    fixture = setup_git_archive(root / "reviewed-safe-dry-run")
    write_safe_nodes(fixture.repo, all_layers=True)
    index_path = fixture.repo / "INDEX.md"
    index_path.write_text("# Agent Memory\n\nPreserved staged state.\n", encoding="utf-8")
    require(["git", "add", "--", "INDEX.md"], "dry_run_seed_index", cwd=fixture.repo)
    staged_blob_before = require(
        ["git", "rev-parse", ":INDEX.md"],
        "dry_run_staged_blob_before",
        cwd=fixture.repo,
    ).stdout.strip()
    index_path.write_text("# Agent Memory\n\nCandidate working-tree state.\n", encoding="utf-8")
    result = run_sync(fixture.repo, reviewed=True, push=True)
    output = command_text(result)
    real_index = require(["git", "diff", "--cached", "--name-only"], "dry_run_real_index", cwd=fixture.repo)
    staged_blob_after = require(
        ["git", "rev-parse", ":INDEX.md"],
        "dry_run_staged_blob_after",
        cwd=fixture.repo,
    ).stdout.strip()
    remote_head = require(
        ["git", "--git-dir", str(fixture.remote), "rev-parse", "refs/heads/main"],
        "dry_run_remote_head",
    ).stdout.strip()
    index_preserved = (
        staged_blob_after == staged_blob_before
        and real_index.stdout.splitlines() == ["INDEX.md"]
    )
    passed = (
        result.returncode == 0
        and all(path in output for path in REVIEWED_MEMORY_FILES)
        and "Would push after commit." in output
        and index_preserved
        and remote_head == fixture.initial_head
    )
    return {
        "case": "reviewed_safe_dry_run",
        "passed": passed,
        "expected": "pass",
        "index_preserved": index_preserved,
    }, index_preserved


def run_safe_live_push(root: Path) -> tuple[dict[str, object], bool, bool]:
    fixture = setup_git_archive(root / "reviewed-safe-live-push")
    write_safe_nodes(fixture.repo, all_layers=True)
    (fixture.repo / "INDEX.md").write_text("# Agent Memory\n\nSynthetic reviewed publication.\n", encoding="utf-8")
    trace_env, trace_path = git_trace_environment(fixture.repo.parent)
    result = run_sync(fixture.repo, reviewed=True, dry_run=False, push=True, env=trace_env)
    head = require(["git", "rev-parse", "HEAD"], "live_head", cwd=fixture.repo).stdout.strip()
    remote_head = require(
        ["git", "--git-dir", str(fixture.remote), "rev-parse", "refs/heads/main"],
        "live_remote_head",
    ).stdout.strip()
    status = require(["git", "status", "--porcelain"], "live_status", cwd=fixture.repo).stdout
    changed = set(
        path
        for path in require(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD"],
            "live_commit_paths",
            cwd=fixture.repo,
        ).stdout.split("\0")
        if path
    )
    exact_scope = all(allowed_committed_path(path) for path in changed) and set(REVIEWED_MEMORY_FILES).issubset(changed)
    add_invocations = traced_add_invocations(trace_path)
    expected_add_paths = {*DEFAULT_ALLOWED_ROOTS, *REVIEWED_MEMORY_FILES}
    exact_add_pathspec = (
        len(add_invocations) == 1
        and add_invocations[0][:2] == ["add", "--"]
        and len(add_invocations[0][2:]) == len(expected_add_paths)
        and set(add_invocations[0][2:]) == expected_add_paths
    )
    passed = (
        result.returncode == 0
        and head != fixture.initial_head
        and remote_head == head
        and not status
        and exact_scope
        and exact_add_pathspec
    )
    return {
        "case": "reviewed_safe_live_push",
        "passed": passed,
        "expected": "pass",
        "exact_add_pathspec": exact_add_pathspec,
    }, exact_scope, exact_add_pathspec


Mutation = Callable[[Path, list[dict[str, object]]], tuple[tuple[str, ...], tuple[str, ...]]]


def run_unsafe_case(root: Path, name: str, mutation: Mutation) -> dict[str, object]:
    fixture = setup_git_archive(root / name)
    nodes = [make_node(fixture.repo, f"mem_{name.replace('-', '_')}")]
    write_nodes(fixture.repo, nodes)
    expected_tokens, private_markers = mutation(fixture.repo, nodes)
    result = run_sync(fixture.repo, reviewed=True)
    output = command_text(result)
    rejected = result.returncode != 0 and all(token in output for token in expected_tokens)
    privacy_preserved = all(marker not in output for marker in private_markers)
    return {
        "case": name,
        "passed": rejected and privacy_preserved,
        "expected": "reject",
        "rejected": rejected,
        "privacy_preserved": privacy_preserved,
    }


def mutate_parity(repo: Path, nodes: list[dict[str, object]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    indexed = dict(nodes[0])
    indexed["text"] = "A different indexed value creates deterministic parity failure."
    (repo / "index/memories.jsonl").write_text(json.dumps(indexed, sort_keys=True) + "\n", encoding="utf-8")
    return (("memory_index_mismatch",), ())


def mutate_lifecycle(repo: Path, nodes: list[dict[str, object]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    nodes[0]["supersedes"] = ["mem_missing_predecessor"]
    evidence_refs = nodes[0]["evidence_refs"]
    assert isinstance(evidence_refs, list) and isinstance(evidence_refs[0], dict)
    evidence_refs[0]["quote_id"] = "ev_missing"
    write_nodes(repo, nodes)
    return (("broken_memory_ref", "broken_supersession_ref"), ())


def mutate_noise(repo: Path, nodes: list[dict[str, object]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    nodes[0]["text"] = f"session_meta {NOISE_SENTINEL} must be rejected."
    write_nodes(repo, nodes)
    return (("category=noise",), (NOISE_SENTINEL,))


def mutate_publish_readiness(
    repo: Path,
    nodes: list[dict[str, object]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    del nodes
    daily = repo / "daily/2026/2026-07-10.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# Daily Memory Index\n\n"
        f"Command Status: would push after commit. {READINESS_SENTINEL}\n",
        encoding="utf-8",
    )
    return (("publish readiness", "command_progress"), (READINESS_SENTINEL,))


def mutate_secret(repo: Path, nodes: list[dict[str, object]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    nodes[0]["text"] = f"Synthetic secret-like value {FAKE_KEY} must be rejected."
    write_nodes(repo, nodes)
    return (("openai_key",), (FAKE_KEY,))


def unexpected_path_mutation(relative: str) -> Mutation:
    def mutate(repo: Path, nodes: list[dict[str, object]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
        del nodes
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.startswith("tools/") and path.exists():
            path.write_text(path.read_text(encoding="utf-8") + "\n# synthetic unexpected edit\n", encoding="utf-8")
        else:
            path.write_text('{"synthetic":true}\n', encoding="utf-8")
        return (("unexpected files", relative), ())

    return mutate


def run_health_failure(root: Path) -> dict[str, object]:
    fixture = setup_git_archive(root / "search-health-failure")
    old_node = make_node(fixture.repo, "mem_health_old")
    marker_node = make_node(fixture.repo, "mem_health_marker")
    old_node["deprecated_by"] = marker_node["memory_id"]
    marker_node["deprecates"] = [old_node["memory_id"]]
    write_nodes(fixture.repo, [old_node, marker_node])
    result = run_sync(fixture.repo, reviewed=True)
    output = command_text(result)
    rejected = result.returncode != 0 and "search health" in output and "no active memory records" in output
    return {
        "case": "search_health_failure",
        "passed": rejected,
        "expected": "reject",
        "rejected": rejected,
        "privacy_preserved": True,
    }


def ratio(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def run_gate(root: Path) -> dict[str, object]:
    default_cases = [run_default_rejection(root)]
    dry_run_case, dry_run_index_preserved = run_safe_dry_run(root)
    dry_run_cases = [dry_run_case]
    live_case, exact_scope, exact_add_pathspec = run_safe_live_push(root)
    unsafe_cases = [
        run_unsafe_case(root, "index-parity-mismatch", mutate_parity),
        run_unsafe_case(root, "broken-lifecycle-evidence", mutate_lifecycle),
        run_unsafe_case(root, "automatic-memory-noise", mutate_noise),
        run_unsafe_case(root, "publish-readiness-noise", mutate_publish_readiness),
        run_unsafe_case(root, "automatic-memory-secret", mutate_secret),
        run_unsafe_case(
            root,
            "unexpected-reviews-path",
            unexpected_path_mutation("reviews/memory_lifecycle_decisions.jsonl"),
        ),
        run_unsafe_case(
            root,
            "unexpected-tools-path",
            unexpected_path_mutation("tools/run_memory_updates.py"),
        ),
        run_unsafe_case(
            root,
            "unexpected-source-stream-path",
            unexpected_path_mutation("config/source_streams.jsonl"),
        ),
        run_unsafe_case(
            root,
            "unexpected-memory-sibling",
            unexpected_path_mutation("memories/unreviewed.jsonl"),
        ),
        run_unsafe_case(root, "unexpected-other-path", unexpected_path_mutation("scheduler-state.json")),
        run_health_failure(root),
    ]
    all_cases = [*default_cases, *dry_run_cases, live_case, *unsafe_cases]
    unexpected_names = {
        "unexpected-reviews-path",
        "unexpected-tools-path",
        "unexpected-source-stream-path",
        "unexpected-memory-sibling",
        "unexpected-other-path",
    }
    privacy_leak_count = sum(
        1 for case in unsafe_cases if case.get("privacy_preserved") is False
    )
    metrics = {
        "default_mode_automatic_memory_rejection_rate": ratio(
            sum(int(case["passed"]) for case in default_cases), len(default_cases)
        ),
        "reviewed_mode_safe_dry_run_pass_rate": ratio(
            sum(int(case["passed"]) for case in dry_run_cases), len(dry_run_cases)
        ),
        "reviewed_mode_live_push_success_rate": 1.0 if live_case["passed"] else 0.0,
        "reviewed_mode_exact_stage_scope_rate": 1.0 if exact_scope else 0.0,
        "reviewed_mode_exact_add_pathspec_rate": 1.0 if exact_add_pathspec else 0.0,
        "reviewed_mode_dry_run_index_preservation_rate": 1.0 if dry_run_index_preserved else 0.0,
        "reviewed_mode_unsafe_rejection_accuracy": ratio(
            sum(int(case["passed"]) for case in unsafe_cases), len(unsafe_cases)
        ),
        "reviewed_mode_index_parity_rejection_count": sum(
            int(case["passed"]) for case in unsafe_cases if case["case"] == "index-parity-mismatch"
        ),
        "reviewed_mode_lifecycle_rejection_count": sum(
            int(case["passed"]) for case in unsafe_cases if case["case"] == "broken-lifecycle-evidence"
        ),
        "reviewed_mode_content_noise_rejection_count": sum(
            int(case["passed"]) for case in unsafe_cases if case["case"] == "automatic-memory-noise"
        ),
        "reviewed_mode_publish_readiness_rejection_count": sum(
            int(case["passed"]) for case in unsafe_cases if case["case"] == "publish-readiness-noise"
        ),
        "reviewed_mode_secret_rejection_count": sum(
            int(case["passed"]) for case in unsafe_cases if case["case"] == "automatic-memory-secret"
        ),
        "reviewed_mode_unexpected_path_rejection_count": sum(
            int(case["passed"]) for case in unsafe_cases if case["case"] in unexpected_names
        ),
        "privacy_leak_count": privacy_leak_count,
    }
    passed = (
        all(case["passed"] for case in all_cases)
        and metrics["default_mode_automatic_memory_rejection_rate"] == 1.0
        and metrics["reviewed_mode_safe_dry_run_pass_rate"] == 1.0
        and metrics["reviewed_mode_live_push_success_rate"] == 1.0
        and metrics["reviewed_mode_exact_stage_scope_rate"] == 1.0
        and metrics["reviewed_mode_exact_add_pathspec_rate"] == 1.0
        and metrics["reviewed_mode_dry_run_index_preservation_rate"] == 1.0
        and metrics["reviewed_mode_unsafe_rejection_accuracy"] == 1.0
        and metrics["reviewed_mode_index_parity_rejection_count"] == 1
        and metrics["reviewed_mode_lifecycle_rejection_count"] == 1
        and metrics["reviewed_mode_content_noise_rejection_count"] == 1
        and metrics["reviewed_mode_publish_readiness_rejection_count"] == 1
        and metrics["reviewed_mode_secret_rejection_count"] == 1
        and metrics["reviewed_mode_unexpected_path_rejection_count"] == 5
        and metrics["privacy_leak_count"] == 0
    )
    return {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "passed" if passed else "failed",
        "claim_boundary": (
            "packaged deterministic reviewed staging, audit, commit, and local bare-remote push closure only; "
            "not LLM answer quality, ranking quality, vector search, ontology discovery, or public leaderboard parity"
        ),
        "metrics": metrics,
        "cases": all_cases,
        "privacy": {
            "synthetic_only": True,
            "aggregate_only": True,
            "command_output_rendered": False,
            "memory_text_rendered": False,
            "secret_value_rendered": False,
        },
    }


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="reviewed-memory-publish-gate-") as tmpdir:
            report = run_gate(Path(tmpdir))
    except GateFailure as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": 1,
            "status": "failed",
            "failure": exc.to_report(),
            "privacy": {
                "synthetic_only": True,
                "aggregate_only": True,
                "command_output_rendered": False,
                "memory_text_rendered": False,
                "secret_value_rendered": False,
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
