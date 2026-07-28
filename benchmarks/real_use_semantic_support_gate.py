#!/usr/bin/env python3
"""Gate the frozen top-five weak-hit semantic-support slice."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = REPO_ROOT / "benchmarks/cases/real_use_semantic_support_synthetic.jsonl"
CASE_FILE_SHA256 = "7893a6646c36982be2213f43bac75c8c045e72612d5f4177deb27b26e56172d0"
SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
REPORT_KIND = "real_use_semantic_support_gate"
CONTEXT_REPORT_KIND = "memory_recall_context_package"
SEMANTIC_POLICY = "bounded_local_semantic_support_v1"
SEMANTIC_MODEL_FINGERPRINT = (
    "89c7223e22f226e5142b3ebc9360f0127b436dc88ba8684922b55dbdabcd6437"
)
SEMANTIC_THRESHOLD = 0.85
SEMANTIC_PROVIDER_SCRIPT = (
    "tools/semantic_support_provider.py"
)
CANDIDATE_COMMIT = "bfc5842bea845dddceb1721a4d47b9155aa21e70"
CANDIDATE_SEARCH_PATH = "templates/agent-memory-repo/tools/search_memory.py"
CANDIDATE_PROVIDER_PATH = (
    "templates/agent-memory-repo/tools/semantic_support_provider.py"
)
CANDIDATE_SEARCH_SHA256 = (
    "186e02ab36146113580d4a234c1e7a7050110ce319ace137c7cc69e5120c25d6"
)
CANDIDATE_PROVIDER_SHA256 = (
    "241ca4ac329d7ca551e07c4ee51d666db3e0ba4d8198d5701c51c7d43e2620e7"
)
COPYABLE_GOAL_GATE = REPO_ROOT / "benchmarks/copyable_goal_preference_recall_gate.py"
FIRST_LOSS_STAGES = (
    "memory_not_materialized",
    "not_retrieved_at_5",
    "retrieved_but_query_support_weak",
    "supported",
)
PRIVATE_MARKERS = (
    re.compile(r"/Users/"),
    re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    ),
    re.compile(r"\bmem_[A-Za-z0-9_.:-]+"),
)


class GateFailure(RuntimeError):
    def __init__(self, stage: str, reason: str, returncode: int | None = None) -> None:
        super().__init__(f"{stage}:{reason}")
        self.stage = stage
        self.reason = reason
        self.returncode = returncode

    def report(self) -> dict[str, object]:
        result: dict[str, object] = {"stage": self.stage, "reason": self.reason}
        if self.returncode is not None:
            result["returncode"] = self.returncode
        return result


@dataclass(frozen=True)
class SemanticCase:
    case_id: str
    cohort: str
    expected_action: str
    expected_first_loss: str
    language: str
    shape: str
    query: str
    memory_text: str
    materialized: bool
    layer: str
    scope: str
    source: str
    inactive: bool
    drill_paths: bool


@dataclass(frozen=True)
class BaselineObservation:
    expected_action: str
    expected_first_loss: str
    first_loss: str
    package_parsed: bool
    decision: str


@dataclass(frozen=True)
class CandidateObservation:
    expected_action: str
    expected_first_loss: str
    shape: str
    decision: str
    package_parsed: bool
    semantic_supported: bool
    semantic_status: str
    semantic_score: float | None
    candidate_evaluation_count: int
    summary_evidence_resolved: bool
    elapsed_seconds: float


@dataclass(frozen=True)
class CandidateRuntime:
    search_script: bytes
    provider_script: bytes


def safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def load_cases(path: Path = CASE_FILE) -> list[SemanticCase]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != CASE_FILE_SHA256:
        raise GateFailure("cases", "frozen_case_fingerprint_mismatch")
    cases: list[SemanticCase] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        value = json.loads(raw_line)
        case_id = str(value.get("case_id") or "")
        if not case_id or case_id in seen:
            raise GateFailure("cases", "invalid_or_duplicate_case_id")
        seen.add(case_id)
        expected_action = str(value.get("expected_action") or "")
        expected_first_loss = str(value.get("expected_first_loss") or "")
        if expected_action not in {"answer", "abstain"}:
            raise GateFailure("cases", "invalid_expected_action")
        if expected_action == "answer" and expected_first_loss not in FIRST_LOSS_STAGES:
            raise GateFailure("cases", "invalid_expected_first_loss")
        cases.append(
            SemanticCase(
                case_id=case_id,
                cohort=str(value.get("cohort") or ""),
                expected_action=expected_action,
                expected_first_loss=expected_first_loss,
                language=str(value.get("language") or ""),
                shape=str(value.get("shape") or ""),
                query=str(value.get("query") or ""),
                memory_text=str(value.get("memory_text") or ""),
                materialized=value.get("materialized") is not False,
                layer=str(value.get("layer") or "global"),
                scope=str(value.get("scope") or "global"),
                source=str(value.get("source") or "automatic"),
                inactive=value.get("inactive") is True,
                drill_paths=value.get("drill_paths") is not False,
            )
        )
    return cases


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require(
    command: list[str],
    stage: str,
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    result = run(command, cwd=cwd)
    if result.returncode:
        raise GateFailure(stage, "command_failed", result.returncode)
    return result


def historical_candidate_runtime() -> CandidateRuntime:
    scripts: dict[str, bytes] = {}
    for name, relative, expected_sha256 in (
        ("search_script", CANDIDATE_SEARCH_PATH, CANDIDATE_SEARCH_SHA256),
        ("provider_script", CANDIDATE_PROVIDER_PATH, CANDIDATE_PROVIDER_SHA256),
    ):
        result = subprocess.run(
            ["git", "show", f"{CANDIDATE_COMMIT}:{relative}"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise GateFailure("candidate_history", "candidate_artifact_missing")
        if hashlib.sha256(result.stdout).hexdigest() != expected_sha256:
            raise GateFailure("candidate_history", "candidate_artifact_hash_mismatch")
        scripts[name] = result.stdout
    return CandidateRuntime(
        search_script=scripts["search_script"],
        provider_script=scripts["provider_script"],
    )


def target_memory_id(case: SemanticCase) -> str:
    digest = hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:16]
    return f"semantic_support_{digest}"


def setup_case_archive(
    root: Path,
    case: SemanticCase,
    *,
    candidate_runtime: CandidateRuntime | None = None,
) -> tuple[Path, str]:
    memory_repo = root / case.case_id
    require(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(memory_repo),
            "--skip-config",
        ],
        "setup_archive",
    )
    if candidate_runtime is not None:
        search_script = memory_repo / "tools/search_memory.py"
        search_script.write_bytes(candidate_runtime.search_script)
        search_script.chmod(0o755)
    memory_id = target_memory_id(case)
    if not case.materialized:
        return memory_repo, memory_id

    summary_path = f"sessions/synthetic/{case.case_id}/summary.md"
    evidence_path = f"sessions/synthetic/{case.case_id}/evidence.md"
    derived_from: list[str] = []
    evidence_refs: list[dict[str, str]] = []
    if case.drill_paths:
        summary = memory_repo / summary_path
        evidence = memory_repo / evidence_path
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text("# Synthetic semantic-support summary\n", encoding="utf-8")
        evidence.write_text(
            "ev_semantic_support_001: synthetic public evidence\n",
            encoding="utf-8",
        )
        derived_from = [summary_path]
        evidence_refs = [
            {"path": evidence_path, "quote_id": "ev_semantic_support_001"}
        ]
    row: dict[str, Any] = {
        "memory_id": memory_id,
        "layer": case.layer,
        "scope": case.scope,
        "topic": f"synthetic-{case.case_id}",
        "text": case.memory_text,
        "source": case.source,
        "confidence": "high",
        "support_count": 2,
        "derived_from": derived_from,
        "evidence_refs": evidence_refs,
        "raw_refs": [],
        "supersedes": [],
        "superseded_by": (
            f"{memory_id}_replacement" if case.inactive else None
        ),
    }
    rows = [row]
    if case.inactive:
        replacement_summary = (
            f"sessions/synthetic/{case.case_id}-replacement/summary.md"
        )
        replacement_evidence = (
            f"sessions/synthetic/{case.case_id}-replacement/evidence.md"
        )
        for relative, text in (
            (replacement_summary, "# Synthetic current replacement\n"),
            (
                replacement_evidence,
                "ev_semantic_support_001: synthetic replacement evidence\n",
            ),
        ):
            path = memory_repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        rows.append(
            {
                "memory_id": f"{memory_id}_replacement",
                "layer": case.layer,
                "scope": case.scope,
                "topic": "synthetic-current-replacement",
                "text": "The current synthetic replacement uses unrelated terms.",
                "source": "automatic",
                "confidence": "high",
                "support_count": 1,
                "derived_from": [replacement_summary],
                "evidence_refs": [
                    {
                        "path": replacement_evidence,
                        "quote_id": "ev_semantic_support_001",
                    }
                ],
                "raw_refs": [],
                "supersedes": [memory_id],
                "superseded_by": None,
            }
        )
    index = memory_repo / "index/memories.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
            for value in rows
        ),
        encoding="utf-8",
    )
    return memory_repo, memory_id


def context_package(
    memory_repo: Path,
    query: str,
    *,
    semantic_socket: Path | None = None,
) -> tuple[str, float]:
    command = [
        sys.executable,
        str(memory_repo / "tools/search_memory.py"),
        query,
        "--repo",
        str(memory_repo),
        "--depth",
        "evidence",
        "--context-json",
        "--limit",
        "5",
    ]
    if semantic_socket is not None:
        command.extend(["--semantic-provider-socket", str(semantic_socket)])
    started = time.perf_counter()
    result = require(
        command,
        "context_package",
        cwd=memory_repo,
    )
    return result.stdout, time.perf_counter() - started


def parse_package(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("report_kind") != CONTEXT_REPORT_KIND:
        return None
    return value


def provider_health(socket_path: Path) -> bool:
    request = json.dumps(
        {
            "report_kind": "semantic_support_health_request",
            "report_version": 1,
            "model_fingerprint": SEMANTIC_MODEL_FINGERPRINT,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(str(socket_path))
            client.sendall(request)
            payload = bytearray()
            while not payload.endswith(b"\n"):
                chunk = client.recv(65536)
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > 65536:
                    return False
        response = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return (
        isinstance(response, dict)
        and response.get("report_kind") == "semantic_support_health_response"
        and response.get("status") == "ready"
        and response.get("model_fingerprint") == SEMANTIC_MODEL_FINGERPRINT
    )


@contextmanager
def packaged_provider(
    root: Path,
    provider_python: Path,
    model_dir: Path,
    candidate_runtime: CandidateRuntime | None = None,
) -> Iterator[Path]:
    runtime = candidate_runtime or historical_candidate_runtime()
    provider_repo = root / "provider-host"
    require(
        [
            sys.executable,
            str(SETUP_SCRIPT),
            "--path",
            str(provider_repo),
            "--skip-config",
        ],
        "provider_setup",
    )
    provider_script = provider_repo / SEMANTIC_PROVIDER_SCRIPT
    provider_script.write_bytes(runtime.provider_script)
    provider_script.chmod(0o755)
    socket_path = root / "semantic-provider.sock"
    process = subprocess.Popen(
        [
            str(provider_python),
            str(provider_script),
            "--socket",
            str(socket_path),
            "--model-dir",
            str(model_dir),
        ],
        cwd=provider_repo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise GateFailure(
                    "provider_startup",
                    "provider_exited",
                    process.returncode,
                )
            if socket_path.is_socket() and provider_health(socket_path):
                break
            time.sleep(0.1)
        else:
            raise GateFailure("provider_startup", "provider_not_ready")
        yield socket_path
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextmanager
def one_shot_provider(socket_path: Path, mode: str) -> Iterator[None]:
    ready = threading.Event()
    errors: list[str] = []

    def serve() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                socket_path.chmod(0o600)
                server.listen(1)
                ready.set()
                connection, _ = server.accept()
                with connection:
                    payload = bytearray()
                    while not payload.endswith(b"\n"):
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        payload.extend(chunk)
                    request = json.loads(payload)
                    if mode == "malformed":
                        response = b"{not-json\n"
                    elif mode == "fingerprint":
                        response = json.dumps(
                            {
                                "report_kind": "semantic_support_response",
                                "report_version": 1,
                                "model_fingerprint": "wrong",
                                "scores": [
                                    {
                                        "candidate_id": item["candidate_id"],
                                        "score": 0.99,
                                    }
                                    for item in request.get("candidates", [])
                                ],
                            },
                            sort_keys=True,
                        ).encode("utf-8") + b"\n"
                    elif mode == "timeout":
                        time.sleep(2.0)
                        response = json.dumps(
                            {
                                "report_kind": "semantic_support_response",
                                "report_version": 1,
                                "model_fingerprint": SEMANTIC_MODEL_FINGERPRINT,
                                "scores": [
                                    {
                                        "candidate_id": item["candidate_id"],
                                        "score": 0.99,
                                    }
                                    for item in request.get("candidates", [])
                                ],
                            },
                            sort_keys=True,
                        ).encode("utf-8") + b"\n"
                    else:
                        raise ValueError("unsupported stub mode")
                    try:
                        connection.sendall(response)
                    except BrokenPipeError:
                        pass
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append("stub_failure")
            ready.set()
        finally:
            try:
                if socket_path.is_socket():
                    socket_path.unlink()
            except OSError:
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    if not ready.wait(2) or errors:
        raise GateFailure("provider_stub", "stub_start_failed")
    try:
        yield
    finally:
        thread.join(timeout=3)
        if thread.is_alive() or errors:
            raise GateFailure("provider_stub", "stub_completion_failed")


def target_hit(package: dict[str, Any] | None, memory_id: str) -> tuple[int, dict[str, Any] | None]:
    if package is None:
        return 0, None
    hits = package.get("hits")
    if not isinstance(hits, list):
        return 0, None
    for rank, hit in enumerate(hits, 1):
        if isinstance(hit, dict) and hit.get("memory_id") == memory_id:
            return rank, hit
    return 0, None


def package_decision(package: dict[str, Any] | None, hit: dict[str, Any] | None) -> str:
    if package is None or hit is None:
        return "abstain"
    answerability = package.get("answerability")
    hit_answerability = hit.get("answerability")
    query_support = hit.get("query_support")
    if (
        isinstance(answerability, dict)
        and answerability.get("status") == "supported"
        and isinstance(hit_answerability, dict)
        and hit_answerability.get("status") == "supported"
        and isinstance(query_support, dict)
        and query_support.get("status") == "supported"
        and hit.get("summary_drill_paths")
        and hit.get("evidence_drill_paths")
    ):
        return "answer"
    return "abstain"


def observe_baseline(root: Path, case: SemanticCase) -> BaselineObservation:
    memory_repo, memory_id = setup_case_archive(root, case)
    raw_package, _elapsed = context_package(memory_repo, case.query)
    package = parse_package(raw_package)
    rank, hit = target_hit(package, memory_id)
    decision = package_decision(package, hit)
    if not case.materialized:
        first_loss = "memory_not_materialized"
    elif not 1 <= rank <= 5:
        first_loss = "not_retrieved_at_5"
    elif decision != "answer":
        first_loss = "retrieved_but_query_support_weak"
    else:
        first_loss = "supported"
    return BaselineObservation(
        expected_action=case.expected_action,
        expected_first_loss=case.expected_first_loss,
        first_loss=first_loss,
        package_parsed=package is not None,
        decision=decision,
    )


def observe_candidate(
    root: Path,
    case: SemanticCase,
    semantic_socket: Path,
    candidate_runtime: CandidateRuntime,
) -> CandidateObservation:
    memory_repo, memory_id = setup_case_archive(
        root,
        case,
        candidate_runtime=candidate_runtime,
    )
    if case.shape == "malformed_provider":
        malformed_socket = root.parent / "malformed.sock"
        with one_shot_provider(malformed_socket, "malformed"):
            raw_package, elapsed = context_package(
                memory_repo,
                case.query,
                semantic_socket=malformed_socket,
            )
    else:
        raw_package, elapsed = context_package(
            memory_repo,
            case.query,
            semantic_socket=semantic_socket,
        )
    package = parse_package(raw_package)
    _rank, hit = target_hit(package, memory_id)
    decision = package_decision(package, hit)
    query_support = hit.get("query_support") if isinstance(hit, dict) else None
    semantic_support = (
        query_support.get("semantic_support")
        if isinstance(query_support, dict)
        and isinstance(query_support.get("semantic_support"), dict)
        else {}
    )
    package_semantic = (
        package.get("semantic_support")
        if isinstance(package, dict)
        and isinstance(package.get("semantic_support"), dict)
        else {}
    )
    return CandidateObservation(
        expected_action=case.expected_action,
        expected_first_loss=case.expected_first_loss,
        shape=case.shape,
        decision=decision,
        package_parsed=package is not None,
        semantic_supported=(
            isinstance(query_support, dict)
            and query_support.get("status") == "supported"
            and query_support.get("policy") == SEMANTIC_POLICY
            and semantic_support.get("status") == "supported"
        ),
        semantic_status=str(semantic_support.get("status") or "not_evaluated"),
        semantic_score=(
            float(semantic_support["score"])
            if isinstance(semantic_support.get("score"), (int, float))
            and not isinstance(semantic_support.get("score"), bool)
            else None
        ),
        candidate_evaluation_count=int(
            package_semantic.get("candidate_evaluation_count") or 0
        ),
        summary_evidence_resolved=(
            isinstance(hit, dict)
            and bool(hit.get("summary_drill_paths"))
            and bool(hit.get("evidence_drill_paths"))
        ),
        elapsed_seconds=elapsed,
    )


def privacy_leak_count(report: dict[str, Any]) -> int:
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    return sum(bool(pattern.search(rendered)) for pattern in PRIVATE_MARKERS)


def run_baseline(cohort: str, root: Path) -> dict[str, Any]:
    cases = [case for case in load_cases() if case.cohort == cohort]
    if not cases:
        raise GateFailure("cases", "cohort_empty")
    observations = [observe_baseline(root, case) for case in cases]
    positives = [
        observation
        for observation in observations
        if observation.expected_action == "answer"
    ]
    support_gaps = [
        observation
        for observation in positives
        if observation.expected_first_loss == "retrieved_but_query_support_weak"
    ]
    first_loss_counts = Counter(observation.first_loss for observation in positives)
    metrics: dict[str, int | float] = {
        "baseline_support_gap_reproduction_rate": safe_rate(
            sum(
                observation.first_loss == observation.expected_first_loss
                for observation in support_gaps
            ),
            len(support_gaps),
        ),
        "baseline_first_loss_classification_accuracy": safe_rate(
            sum(
                observation.first_loss == observation.expected_first_loss
                for observation in positives
            ),
            len(positives),
        ),
        "baseline_context_package_parse_success_rate": safe_rate(
            sum(observation.package_parsed for observation in observations),
            len(observations),
        ),
        "baseline_negative_abstention_rate": safe_rate(
            sum(
                observation.decision == "abstain"
                for observation in observations
                if observation.expected_action == "abstain"
            ),
            sum(
                observation.expected_action == "abstain"
                for observation in observations
            ),
        ),
        "free_form_answerability_use_count": 0,
        "privacy_leak_count": 0,
    }
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 1,
        "status": "baseline_reproduced",
        "mode": "baseline_only",
        "cohort": cohort,
        "cohort_fingerprint": CASE_FILE_SHA256,
        "case_counts": {
            "positive": len(positives),
            "negative": len(observations) - len(positives),
            "support_gap": len(support_gaps),
        },
        "baseline_first_loss_counts": {
            stage: first_loss_counts.get(stage, 0)
            for stage in FIRST_LOSS_STAGES
            if first_loss_counts.get(stage, 0)
        },
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "case_text_rendered": False,
            "query_text_rendered": False,
            "memory_text_rendered": False,
            "paths_rendered": False,
            "ids_rendered": False,
            "context_packages_rendered": False,
        },
        "claim_boundary": (
            "frozen synthetic first-loss taxonomy only; not semantic candidate "
            "quality, private recall, vector search, or LLM answer quality"
        ),
    }
    metrics["privacy_leak_count"] = privacy_leak_count(report)
    if (
        metrics["baseline_support_gap_reproduction_rate"] != 1.0
        or metrics["baseline_first_loss_classification_accuracy"] != 1.0
        or metrics["baseline_context_package_parse_success_rate"] != 1.0
        or metrics["privacy_leak_count"] != 0
    ):
        report["status"] = "failed"
    return report


def required_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def provider_failure_probes(
    root: Path,
    case: SemanticCase,
    candidate_runtime: CandidateRuntime,
) -> list[bool]:
    results: list[bool] = []
    for index, mode in enumerate(
        ("missing", "malformed", "fingerprint", "timeout"),
        1,
    ):
        mode_root = root / "provider-failure-probes" / mode
        mode_root.mkdir(parents=True, exist_ok=True)
        memory_repo, memory_id = setup_case_archive(
            mode_root,
            case,
            candidate_runtime=candidate_runtime,
        )
        socket_path = root / f"f{index}.sock"
        if mode == "missing":
            raw_package, _elapsed = context_package(
                memory_repo,
                case.query,
                semantic_socket=socket_path,
            )
        else:
            with one_shot_provider(socket_path, mode):
                raw_package, _elapsed = context_package(
                    memory_repo,
                    case.query,
                    semantic_socket=socket_path,
                )
        package = parse_package(raw_package)
        _rank, hit = target_hit(package, memory_id)
        query_support = hit.get("query_support") if isinstance(hit, dict) else None
        semantic_support = (
            query_support.get("semantic_support")
            if isinstance(query_support, dict)
            and isinstance(query_support.get("semantic_support"), dict)
            else {}
        )
        results.append(
            package_decision(package, hit) == "abstain"
            and isinstance(query_support, dict)
            and query_support.get("status") == "weak"
            and semantic_support.get("status") == "provider_failure"
        )
    return results


def cohort_slice_fingerprint(cases: list[SemanticCase]) -> str:
    payload = [
        {
            field: getattr(case, field)
            for field in SemanticCase.__dataclass_fields__
        }
        for case in cases
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def case_specific_runtime_literal_count(
    cases: list[SemanticCase],
    candidate_runtime: CandidateRuntime,
) -> int:
    runtime = b"\n".join(
        (candidate_runtime.search_script, candidate_runtime.provider_script)
    ).decode("utf-8")
    case_ids = {case.case_id for case in cases}
    synthetic_subjects: set[str] = set()
    for case in cases:
        synthetic_subjects.update(
            re.findall(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b", case.query)
        )
        synthetic_subjects.update(
            re.findall(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b", case.memory_text)
        )
    return sum(value in runtime for value in case_ids | synthetic_subjects)


def legacy_goal_regression_rate() -> float:
    result = run([sys.executable, str(COPYABLE_GOAL_GATE)])
    return 1.0 if result.returncode == 0 else 0.0


def run_candidate(
    cohort: str,
    root: Path,
    *,
    provider_python: Path,
    model_dir: Path,
) -> dict[str, Any]:
    cases = [case for case in load_cases() if case.cohort == cohort]
    if not cases:
        raise GateFailure("cases", "cohort_empty")
    candidate_runtime = historical_candidate_runtime()
    with packaged_provider(
        root,
        provider_python,
        model_dir,
        candidate_runtime,
    ) as semantic_socket:
        observations = [
            observe_candidate(
                root / "cases",
                case,
                semantic_socket,
                candidate_runtime,
            )
            for case in cases
        ]
        support_gap_case = next(
            case
            for case in cases
            if case.expected_first_loss == "retrieved_but_query_support_weak"
        )
        failure_probe_results = provider_failure_probes(
            root,
            support_gap_case,
            candidate_runtime,
        )

    support_gaps = [
        observation
        for observation in observations
        if observation.expected_first_loss == "retrieved_but_query_support_weak"
    ]
    negatives = [
        observation
        for observation in observations
        if observation.expected_action == "abstain"
    ]
    answered = [
        observation
        for observation in observations
        if observation.decision == "answer"
    ]
    wrong_scope = [
        observation
        for observation in observations
        if observation.shape == "wrong_scope"
    ]
    inactive = [
        observation
        for observation in observations
        if observation.shape == "inactive_only"
    ]
    current_turn = [
        observation
        for observation in observations
        if observation.shape == "current_turn_override"
    ]
    semantic_positive_scores = [
        observation.semantic_score
        for observation in support_gaps
        if observation.semantic_score is not None
    ]
    semantic_negative_scores = [
        observation.semantic_score
        for observation in negatives
        if observation.semantic_score is not None
    ]
    recall_name = f"semantic_support_public_{cohort}_recall"
    metrics: dict[str, int | float] = {
        recall_name: safe_rate(
            sum(observation.semantic_supported for observation in support_gaps),
            len(support_gaps),
        ),
        "supported_decision_precision": safe_rate(
            sum(observation.expected_action == "answer" for observation in answered),
            len(answered),
        ),
        "hard_negative_rejection_rate": required_rate(
            sum(observation.decision == "abstain" for observation in negatives),
            len(negatives),
        ),
        "wrong_scope_rejection_rate": required_rate(
            sum(observation.decision == "abstain" for observation in wrong_scope),
            len(wrong_scope),
        ),
        "inactive_rejection_rate": required_rate(
            sum(observation.decision == "abstain" for observation in inactive),
            len(inactive),
        ),
        "current_turn_precedence_accuracy": required_rate(
            sum(observation.decision == "abstain" for observation in current_turn),
            len(current_turn),
        ),
        "summary_evidence_resolution_rate": safe_rate(
            sum(
                observation.semantic_supported
                and observation.summary_evidence_resolved
                for observation in support_gaps
            ),
            len(support_gaps),
        ),
        "legacy_v253_goal_preference_regression_rate": legacy_goal_regression_rate(),
        "provider_failure_fail_closed_rate": safe_rate(
            sum(failure_probe_results),
            len(failure_probe_results),
        ),
        "runtime_context_package_parse_success_rate": safe_rate(
            sum(observation.package_parsed for observation in observations),
            len(observations),
        ),
        "semantic_candidate_evaluation_count_per_query": max(
            (
                observation.candidate_evaluation_count
                for observation in observations
            ),
            default=0,
        ),
        "public_warm_query_p95_seconds": round(
            percentile_95(
                [observation.elapsed_seconds for observation in observations]
            ),
            6,
        ),
        "false_support_count": sum(
            observation.decision == "answer" for observation in negatives
        ),
        "free_form_answerability_use_count": 0,
        "case_specific_runtime_literal_count": case_specific_runtime_literal_count(
            cases,
            candidate_runtime,
        ),
        "privacy_leak_count": 0,
    }
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "report_version": 2,
        "status": (
            "calibration_passed" if cohort == "calibration" else "go"
        ),
        "decision": (
            "threshold_frozen" if cohort == "calibration" else "public_holdout_go"
        ),
        "mode": "semantic_candidate",
        "candidate_commit": CANDIDATE_COMMIT,
        "cohort": cohort,
        "case_file_fingerprint": CASE_FILE_SHA256,
        "cohort_fingerprint": cohort_slice_fingerprint(cases),
        "provider_identity": {
            "model_id": "intfloat/multilingual-e5-small",
            "model_revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
            "model_manifest_sha256": (
                "8a945b5d9dde256c5bb6f0274845ac4d7a42e9a02b1e0ac76da66972d32299bb"
            ),
            "model_fingerprint": SEMANTIC_MODEL_FINGERPRINT,
            "sentence_transformers_version": "5.6.0",
            "torch_version": "2.13.0",
            "transformers_version": "5.14.1",
            "query_prefix": "query:",
            "passage_prefix": "passage:",
            "network_at_query_time": False,
        },
        "policy": {
            "name": SEMANTIC_POLICY,
            "threshold": SEMANTIC_THRESHOLD,
            "candidate_limit": 5,
            "threshold_source": "frozen_calibration_only",
        },
        "case_counts": {
            "total": len(observations),
            "support_gap": len(support_gaps),
            "negative": len(negatives),
            "provider_failure_probe": len(failure_probe_results),
        },
        "score_summary": {
            "semantic_positive_min": (
                round(min(semantic_positive_scores), 6)
                if semantic_positive_scores
                else None
            ),
            "semantic_negative_max_evaluated": (
                round(max(semantic_negative_scores), 6)
                if semantic_negative_scores
                else None
            ),
        },
        "metrics": metrics,
        "privacy": {
            "aggregate_only": True,
            "case_text_rendered": False,
            "query_text_rendered": False,
            "memory_text_rendered": False,
            "paths_rendered": False,
            "ids_rendered": False,
            "context_packages_rendered": False,
            "provider_logging_enabled": False,
        },
        "claim_boundary": (
            "pinned local semantic support for existing top-five weak active/current "
            "hits only; not no-hit semantic retrieval, vector search, induction "
            "quality, ontology discovery, LLM answer quality, or leaderboard parity"
        ),
    }
    metrics["privacy_leak_count"] = privacy_leak_count(report)
    required_one = (
        recall_name,
        "supported_decision_precision",
        "hard_negative_rejection_rate",
        "wrong_scope_rejection_rate",
        "inactive_rejection_rate",
        "current_turn_precedence_accuracy",
        "summary_evidence_resolution_rate",
        "legacy_v253_goal_preference_regression_rate",
        "provider_failure_fail_closed_rate",
        "runtime_context_package_parse_success_rate",
    )
    if (
        any(metrics[name] != 1.0 for name in required_one)
        or metrics["semantic_candidate_evaluation_count_per_query"] > 5
        or metrics["public_warm_query_p95_seconds"] > 2.0
        or any(
            metrics[name] != 0
            for name in (
                "false_support_count",
                "free_form_answerability_use_count",
                "case_specific_runtime_literal_count",
                "privacy_leak_count",
            )
        )
    ):
        report["status"] = "failed"
        report["decision"] = (
            "calibration_failed" if cohort == "calibration" else "no_go"
        )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=("calibration", "holdout"), required=True)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--provider-python")
    parser.add_argument("--model-dir")
    parser.add_argument("--work-dir")
    parser.add_argument("--report-file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.baseline_only and (not args.provider_python or not args.model_dir):
        print(
            json.dumps(
                {
                    "report_kind": REPORT_KIND,
                    "status": "failed",
                    "failures": [
                        {
                            "stage": "arguments",
                            "reason": "candidate_requires_provider_python_and_model_dir",
                        }
                    ],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    parent = (
        Path(args.work_dir).expanduser().resolve()
        if args.work_dir
        else Path(tempfile.gettempdir())
    )
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="v258-semantic-support-", dir=parent))
    try:
        if args.baseline_only:
            report = run_baseline(args.cohort, root)
        else:
            provider_python = Path(args.provider_python).expanduser()
            model_dir = Path(args.model_dir).expanduser()
            if not provider_python.is_file() or not model_dir.is_dir():
                raise GateFailure("arguments", "provider_runtime_missing")
            report = run_candidate(
                args.cohort,
                root,
                provider_python=provider_python,
                model_dir=model_dir,
            )
        output = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if args.report_file:
            report_path = Path(args.report_file).expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output + "\n", encoding="utf-8")
        print(output)
        return (
            0
            if report["status"]
            in {"baseline_reproduced", "calibration_passed", "go"}
            else 1
        )
    except (GateFailure, OSError, json.JSONDecodeError) as failure:
        detail = (
            failure.report()
            if isinstance(failure, GateFailure)
            else {"stage": "gate", "reason": type(failure).__name__}
        )
        print(
            json.dumps(
                {
                    "report_kind": REPORT_KIND,
                    "status": "failed",
                    "failures": [detail],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
