#!/usr/bin/env python3
"""Provision and manage the optional local semantic retrieval runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REPORT_KIND = "semantic_retrieval_setup"
REPORT_VERSION = 1
SERVICE_LABEL = "com.my-precious.semantic-retrieval"
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")
DEFAULT_RUNTIME_ROOT = Path("~/.local/share/my-precious/semantic-retrieval")
DEFAULT_STATE_ROOT = Path("~/.local/state/my-precious/semantic-retrieval")
DEFAULT_SUPPORT_THRESHOLD = 0.90
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_BATCH_SIZE = 32
DEFAULT_PYTHON_VERSION = "3.12"
EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"
EMBEDDING_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
RERANKER_MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
EMBEDDING_MODEL_FILES = (
    "1_Pooling/config.json",
    "config.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
RERANKER_MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
PROVIDER_SCRIPT_NAME = "semantic_retrieval_provider.py"
PROVIDER_REQUIREMENTS_NAME = "semantic_retrieval_provider_requirements.txt"
MAX_HEALTH_RESPONSE_BYTES = 64 * 1024


class SetupError(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class RuntimeLayout:
    memory_repo: Path
    config_path: Path
    runtime_root: Path
    state_root: Path
    venv_path: Path
    embedding_model_path: Path
    reranker_model_path: Path
    socket_path: Path
    stdout_log_path: Path
    stderr_log_path: Path
    plist_path: Path
    provider_script: Path
    requirements_path: Path


def expanded_absolute(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def build_layout(
    *,
    memory_repo: str | Path,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    runtime_root: str | Path = DEFAULT_RUNTIME_ROOT,
    state_root: str | Path = DEFAULT_STATE_ROOT,
    socket_path: str | Path | None = None,
    plist_path: str | Path | None = None,
) -> RuntimeLayout:
    repo = expanded_absolute(memory_repo)
    config = expanded_absolute(config_path)
    runtime = expanded_absolute(runtime_root)
    state = expanded_absolute(state_root)
    if runtime == repo or state == repo or is_within(runtime, repo) or is_within(state, repo):
        raise SetupError("semantic_runtime_must_be_outside_memory_repo")
    resolved_socket_path = (
        expanded_absolute(socket_path)
        if socket_path is not None
        else state / "run" / "semantic-retrieval.sock"
    )
    if is_within(resolved_socket_path, repo):
        raise SetupError("semantic_socket_must_be_outside_memory_repo")
    if len(os.fsencode(resolved_socket_path)) >= 100:
        raise SetupError("semantic_socket_path_too_long")
    resolved_plist_path = (
        expanded_absolute(plist_path)
        if plist_path is not None
        else expanded_absolute(
            Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
        )
    )
    return RuntimeLayout(
        memory_repo=repo,
        config_path=config,
        runtime_root=runtime,
        state_root=state,
        venv_path=runtime / "venv",
        embedding_model_path=runtime / "models" / "multilingual-e5-small",
        reranker_model_path=runtime / "models" / "mmarco-reranker",
        socket_path=resolved_socket_path,
        stdout_log_path=state / "logs" / "provider.stdout.log",
        stderr_log_path=state / "logs" / "provider.stderr.log",
        plist_path=resolved_plist_path,
        provider_script=repo / "tools" / PROVIDER_SCRIPT_NAME,
        requirements_path=repo / "tools" / PROVIDER_REQUIREMENTS_NAME,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise SetupError("private_config_symlink_refused")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError("private_config_unreadable") from exc
    if not isinstance(value, dict):
        raise SetupError("private_config_malformed")
    return value


def atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(mode)
        os.replace(temp_path, path)
        path.chmod(mode)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def configured_provider_block(
    layout: RuntimeLayout,
    *,
    provider_fingerprint: str,
    support_threshold: float,
    timeout_seconds: float,
) -> dict[str, object]:
    return {
        "enabled": True,
        "socket": str(layout.socket_path),
        "provider_fingerprint": provider_fingerprint,
        "support_threshold": support_threshold,
        "timeout_seconds": timeout_seconds,
    }


def write_private_config(
    layout: RuntimeLayout,
    provider_block: dict[str, object],
) -> tuple[bool, bool]:
    config = read_json_object(layout.config_path)
    expected_repo = str(layout.memory_repo)
    existing_repo = config.get("memory_repo")
    existing_repo_matches = (
        existing_repo is None
        or (
            isinstance(existing_repo, str)
            and expanded_absolute(existing_repo) == layout.memory_repo
        )
    )
    if not existing_repo_matches:
        raise SetupError("private_config_memory_repo_mismatch")
    changed = (
        existing_repo != expected_repo
        or config.get("semantic_retrieval_provider") != provider_block
    )
    if not changed:
        return False, False
    backup_created = False
    if layout.config_path.exists() and "semantic_retrieval_provider" not in config:
        backup_path = layout.config_path.with_name(
            f"{layout.config_path.name}.pre-semantic-retrieval"
        )
        if not backup_path.exists():
            atomic_write_bytes(backup_path, layout.config_path.read_bytes())
            backup_created = True
    config["memory_repo"] = expected_repo
    config["semantic_retrieval_provider"] = provider_block
    atomic_write_bytes(
        layout.config_path,
        (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return True, backup_created


def launchd_plist(
    layout: RuntimeLayout,
    *,
    batch_size: int,
    device: str,
) -> dict[str, object]:
    python_path = layout.venv_path / "bin" / "python"
    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            str(python_path),
            str(layout.provider_script),
            "--repo",
            str(layout.memory_repo),
            "--embedding-model-dir",
            str(layout.embedding_model_path),
            "--reranker-model-dir",
            str(layout.reranker_model_path),
            "--socket",
            str(layout.socket_path),
            "--batch-size",
            str(batch_size),
            "--device",
            device,
        ],
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "ThrottleInterval": 10,
        "StandardOutPath": str(layout.stdout_log_path),
        "StandardErrorPath": str(layout.stderr_log_path),
        "EnvironmentVariables": {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "PYTHONUNBUFFERED": "1",
        },
    }


def plan_report(layout: RuntimeLayout, *, service_backend: str) -> dict[str, object]:
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "action": "plan",
        "status": "planned",
        "service_backend": service_backend,
        "checks": {
            "memory_repo_exists": layout.memory_repo.is_dir(),
            "provider_tool_present": layout.provider_script.is_file(),
            "requirements_present": layout.requirements_path.is_file(),
            "runtime_exists": layout.runtime_root.is_dir(),
            "state_exists": layout.state_root.is_dir(),
            "config_exists": layout.config_path.is_file(),
            "service_definition_exists": layout.plist_path.is_file(),
        },
        "planned_mutations": {
            "repository_mutation_count": 0,
            "archive_content_mutation_count": 0,
            "external_runtime_write": True,
            "private_config_write": True,
            "service_definition_write": service_backend == "launchd",
            "service_enable": service_backend == "launchd",
        },
        "model_identity": {
            "embedding_revision_pinned": True,
            "reranker_revision_pinned": True,
            "query_time_network_disabled": True,
        },
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "config_content_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
        },
    }


def default_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, **kwargs)


def run_checked(
    command: list[str],
    *,
    stage: str,
    runner: Runner = default_runner,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SetupError(f"{stage}_unavailable") from exc
    if result.returncode:
        raise SetupError(f"{stage}_failed")
    return result


def ensure_private_directory(path: Path) -> None:
    existed = path.exists() or path.is_symlink()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if not existed:
            path.chmod(0o700)
        path_stat = path.lstat()
    except OSError as exc:
        raise SetupError("private_directory_permission_failed") from exc
    if (
        path.is_symlink()
        or not path.is_dir()
        or path_stat.st_uid != os.getuid()
        or stat.S_IMODE(path_stat.st_mode) != 0o700
    ):
        raise SetupError("private_directory_not_private")


def prepare_runtime_directories(layout: RuntimeLayout) -> None:
    for path in (
        layout.runtime_root,
        layout.runtime_root / "models",
        layout.state_root,
        layout.socket_path.parent,
        layout.stdout_log_path.parent,
    ):
        ensure_private_directory(path)


def provision_python_environment(
    layout: RuntimeLayout,
    *,
    uv_path: Path,
    python_version: str,
    runner: Runner = default_runner,
) -> bool:
    venv_python = layout.venv_path / "bin" / "python"
    if layout.venv_path.is_symlink() or (
        layout.venv_path.exists() and not layout.venv_path.is_dir()
    ):
        raise SetupError("semantic_venv_unsafe")
    if venv_python.is_file():
        return False
    if layout.venv_path.exists() and any(layout.venv_path.iterdir()):
        raise SetupError("semantic_venv_incomplete")
    run_checked(
        [
            str(uv_path),
            "venv",
            "--no-project",
            "--python",
            python_version,
            str(layout.venv_path),
        ],
        stage="semantic_venv_create",
        runner=runner,
    )
    if not venv_python.is_file():
        raise SetupError("semantic_venv_python_missing")
    return True


def install_provider_dependencies(
    layout: RuntimeLayout,
    *,
    uv_path: Path,
    runner: Runner = default_runner,
) -> None:
    if not layout.requirements_path.is_file() or layout.requirements_path.is_symlink():
        raise SetupError("semantic_requirements_missing")
    run_checked(
        [
            str(uv_path),
            "pip",
            "install",
            "--python",
            str(layout.venv_path / "bin" / "python"),
            "--requirements",
            str(layout.requirements_path),
        ],
        stage="semantic_dependencies_install",
        runner=runner,
    )


MODEL_DOWNLOAD_PROGRAM = """
import json
import sys
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id=sys.argv[1],
    revision=sys.argv[2],
    local_dir=sys.argv[3],
    allow_patterns=json.loads(sys.argv[4]),
)
""".strip()


def required_model_files_present(
    destination: Path,
    allow_patterns: tuple[str, ...],
) -> bool:
    return all(
        (destination / relative).is_file()
        and not (destination / relative).is_symlink()
        for relative in allow_patterns
    )


def download_model_snapshot(
    layout: RuntimeLayout,
    *,
    model_id: str,
    revision: str,
    destination: Path,
    allow_patterns: tuple[str, ...],
    runner: Runner = default_runner,
) -> bool:
    ensure_private_directory(destination)
    if required_model_files_present(destination, allow_patterns):
        return False
    run_checked(
        [
            str(layout.venv_path / "bin" / "python"),
            "-c",
            MODEL_DOWNLOAD_PROGRAM,
            model_id,
            revision,
            str(destination),
            json.dumps(allow_patterns),
        ],
        stage="semantic_model_download",
        runner=runner,
    )
    if not required_model_files_present(destination, allow_patterns):
        raise SetupError("semantic_model_artifacts_incomplete")
    return True


def provision_models(
    layout: RuntimeLayout,
    *,
    runner: Runner = default_runner,
) -> int:
    download_count = int(download_model_snapshot(
        layout,
        model_id=EMBEDDING_MODEL_ID,
        revision=EMBEDDING_MODEL_REVISION,
        destination=layout.embedding_model_path,
        allow_patterns=EMBEDDING_MODEL_FILES,
        runner=runner,
    ))
    download_count += int(download_model_snapshot(
        layout,
        model_id=RERANKER_MODEL_ID,
        revision=RERANKER_MODEL_REVISION,
        destination=layout.reranker_model_path,
        allow_patterns=RERANKER_MODEL_FILES,
        runner=runner,
    ))
    return download_count


def provider_identity(
    layout: RuntimeLayout,
    *,
    runner: Runner = default_runner,
) -> str:
    if not layout.provider_script.is_file() or layout.provider_script.is_symlink():
        raise SetupError("semantic_provider_tool_missing")
    result = run_checked(
        [
            str(layout.venv_path / "bin" / "python"),
            str(layout.provider_script),
            "--repo",
            str(layout.memory_repo),
            "--embedding-model-dir",
            str(layout.embedding_model_path),
            "--reranker-model-dir",
            str(layout.reranker_model_path),
            "--print-fingerprint",
        ],
        stage="semantic_provider_identity",
        runner=runner,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError("semantic_provider_identity_malformed") from exc
    fingerprint = payload.get("provider_fingerprint") if isinstance(payload, dict) else None
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in fingerprint)
        or payload.get("report_kind") != "memory_semantic_retrieval_provider_identity"
        or payload.get("reranker_enabled") is not True
    ):
        raise SetupError("semantic_provider_identity_malformed")
    return fingerprint


def write_launchd_plist(
    layout: RuntimeLayout,
    *,
    batch_size: int,
    device: str,
    runner: Runner = default_runner,
) -> bool:
    rendered = plistlib.dumps(
        launchd_plist(layout, batch_size=batch_size, device=device),
        fmt=plistlib.FMT_XML,
        sort_keys=True,
    )
    if layout.plist_path.is_symlink():
        raise SetupError("semantic_launchd_plist_symlink_refused")
    changed = not layout.plist_path.is_file() or layout.plist_path.read_bytes() != rendered
    if changed:
        if layout.plist_path.is_file():
            backup_path = layout.plist_path.with_name(
                f"{layout.plist_path.name}.pre-semantic-retrieval"
            )
            if not backup_path.exists():
                atomic_write_bytes(backup_path, layout.plist_path.read_bytes())
        atomic_write_bytes(layout.plist_path, rendered)
    run_checked(
        ["/usr/bin/plutil", "-lint", str(layout.plist_path)],
        stage="semantic_launchd_plist_validation",
        runner=runner,
    )
    return changed


def launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def launchd_service_target() -> str:
    return f"{launchd_domain()}/{SERVICE_LABEL}"


def command_result(
    command: list[str],
    *,
    runner: Runner = default_runner,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SetupError("service_command_unavailable") from exc


def launchd_service_loaded(*, runner: Runner = default_runner) -> bool:
    result = command_result(
        ["/bin/launchctl", "print", launchd_service_target()],
        runner=runner,
    )
    return result.returncode == 0


def enable_launchd_service(
    layout: RuntimeLayout,
    *,
    runner: Runner = default_runner,
) -> bool:
    if platform.system() != "Darwin":
        raise SetupError("launchd_backend_requires_macos")
    was_loaded = launchd_service_loaded(runner=runner)
    if was_loaded:
        run_checked(
            ["/bin/launchctl", "bootout", launchd_service_target()],
            stage="semantic_launchd_bootout",
            runner=runner,
        )
    run_checked(
        ["/bin/launchctl", "bootstrap", launchd_domain(), str(layout.plist_path)],
        stage="semantic_launchd_bootstrap",
        runner=runner,
    )
    run_checked(
        ["/bin/launchctl", "kickstart", "-k", launchd_service_target()],
        stage="semantic_launchd_kickstart",
        runner=runner,
    )
    return not was_loaded


def disable_launchd_service(*, runner: Runner = default_runner) -> bool:
    if platform.system() != "Darwin" or not launchd_service_loaded(runner=runner):
        return False
    run_checked(
        ["/bin/launchctl", "bootout", launchd_service_target()],
        stage="semantic_launchd_bootout",
        runner=runner,
    )
    return True


def semantic_health(
    layout: RuntimeLayout,
    *,
    provider_fingerprint: str,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    try:
        socket_stat = layout.socket_path.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISSOCK(socket_stat.st_mode)
        or socket_stat.st_uid != os.getuid()
        or socket_stat.st_mode & 0o077
    ):
        return None
    request = json.dumps(
        {
            "report_kind": "memory_semantic_retrieval_health_request",
            "report_version": 1,
            "provider_fingerprint": provider_fingerprint,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    response_bytes = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_seconds)
            client.connect(str(layout.socket_path))
            client.sendall(request)
            while not response_bytes.endswith(b"\n"):
                chunk = client.recv(65536)
                if not chunk:
                    break
                response_bytes.extend(chunk)
                if len(response_bytes) > MAX_HEALTH_RESPONSE_BYTES:
                    return None
    except (OSError, TimeoutError):
        return None
    try:
        response = json.loads(response_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    expected_index = layout.memory_repo / "index" / "memories.jsonl"
    if (
        not isinstance(response, dict)
        or response.get("report_kind") != "memory_semantic_retrieval_health_response"
        or response.get("status") != "ready"
        or response.get("provider_fingerprint") != provider_fingerprint
        or not expected_index.is_file()
        or response.get("index_sha256") != sha256_file(expected_index)
        or response.get("reranker_enabled") is not True
        or isinstance(response.get("memory_count"), bool)
        or not isinstance(response.get("memory_count"), int)
        or response["memory_count"] <= 0
    ):
        return None
    return response


def wait_for_semantic_health(
    layout: RuntimeLayout,
    *,
    provider_fingerprint: str,
    wait_seconds: float,
) -> tuple[dict[str, object] | None, float]:
    started = time.monotonic()
    deadline = started + wait_seconds
    while time.monotonic() < deadline:
        health = semantic_health(
            layout,
            provider_fingerprint=provider_fingerprint,
        )
        if health is not None:
            return health, time.monotonic() - started
        time.sleep(0.5)
    return None, time.monotonic() - started


def disable_private_config(layout: RuntimeLayout) -> bool:
    config = read_json_object(layout.config_path)
    block = config.get("semantic_retrieval_provider")
    if not isinstance(block, dict) or block.get("enabled") is False:
        return False
    updated = dict(block)
    updated["enabled"] = False
    config["semantic_retrieval_provider"] = updated
    atomic_write_bytes(
        layout.config_path,
        (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return True


def path_mode_is(path: Path, expected: int) -> bool:
    try:
        return not path.is_symlink() and stat.S_IMODE(path.stat().st_mode) == expected
    except OSError:
        return False


def launchd_definition_matches(
    layout: RuntimeLayout,
    *,
    batch_size: int,
    device: str,
) -> bool:
    if not layout.plist_path.is_file() or layout.plist_path.is_symlink():
        return False
    try:
        value = plistlib.loads(layout.plist_path.read_bytes())
    except (OSError, plistlib.InvalidFileException):
        return False
    return value == launchd_plist(layout, batch_size=batch_size, device=device)


def check_report(
    layout: RuntimeLayout,
    *,
    service_backend: str,
    batch_size: int,
    device: str,
    runner: Runner = default_runner,
) -> dict[str, object]:
    config = read_json_object(layout.config_path)
    block = config.get("semantic_retrieval_provider")
    configured = isinstance(block, dict) and block.get("enabled") is True
    fingerprint = block.get("provider_fingerprint") if isinstance(block, dict) else None
    config_aligned = (
        configured
        and block.get("socket") == str(layout.socket_path)
        and isinstance(fingerprint, str)
        and len(fingerprint) == 64
        and isinstance(block.get("support_threshold"), (int, float))
        and not isinstance(block.get("support_threshold"), bool)
        and 0.0 <= float(block["support_threshold"]) <= 1.0
        and isinstance(block.get("timeout_seconds"), (int, float))
        and not isinstance(block.get("timeout_seconds"), bool)
        and 0.0 < float(block["timeout_seconds"]) <= 10.0
    )
    provider_ready = False
    if isinstance(fingerprint, str) and len(fingerprint) == 64:
        provider_ready = semantic_health(
            layout,
            provider_fingerprint=fingerprint,
        ) is not None
    service_loaded = (
        launchd_service_loaded(runner=runner)
        if service_backend == "launchd" and platform.system() == "Darwin"
        else service_backend == "none"
    )
    checks = {
        "provider_tool_present": layout.provider_script.is_file(),
        "requirements_present": layout.requirements_path.is_file(),
        "venv_python_present": (layout.venv_path / "bin" / "python").is_file(),
        "embedding_model_present": all(
            (layout.embedding_model_path / relative).is_file()
            for relative in EMBEDDING_MODEL_FILES
        ),
        "reranker_model_present": all(
            (layout.reranker_model_path / relative).is_file()
            for relative in RERANKER_MODEL_FILES
        ),
        "config_enabled_and_aligned": config_aligned,
        "config_private_mode": path_mode_is(layout.config_path, 0o600),
        "runtime_private_mode": path_mode_is(layout.runtime_root, 0o700),
        "state_private_mode": path_mode_is(layout.state_root, 0o700),
        "service_definition_matches": (
            launchd_definition_matches(
                layout,
                batch_size=batch_size,
                device=device,
            )
            and path_mode_is(layout.plist_path, 0o600)
            if service_backend == "launchd"
            else True
        ),
        "service_loaded": service_loaded,
        "provider_health_ready": provider_ready,
    }
    status = "current" if all(checks.values()) else "drifted"
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "action": "check",
        "status": status,
        "service_backend": service_backend,
        "checks": checks,
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "config_content_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
        },
    }


def install_runtime(
    layout: RuntimeLayout,
    *,
    service_backend: str,
    python_version: str,
    support_threshold: float,
    timeout_seconds: float,
    batch_size: int,
    device: str,
    wait_seconds: float,
    uv_path: Path,
    runner: Runner = default_runner,
) -> dict[str, object]:
    if service_backend not in ("launchd", "none"):
        raise SetupError("unsupported_service_backend")
    if not 0.0 <= support_threshold <= 1.0 or not 0.0 < timeout_seconds <= 10.0:
        raise SetupError("invalid_semantic_threshold_or_timeout")
    if batch_size <= 0 or wait_seconds <= 0:
        raise SetupError("invalid_semantic_runtime_limit")
    if not layout.memory_repo.is_dir():
        raise SetupError("memory_repo_unavailable")
    if not layout.provider_script.is_file() or not layout.requirements_path.is_file():
        raise SetupError("semantic_runtime_tools_missing")
    prepare_runtime_directories(layout)
    venv_created = provision_python_environment(
        layout,
        uv_path=uv_path,
        python_version=python_version,
        runner=runner,
    )
    install_provider_dependencies(layout, uv_path=uv_path, runner=runner)
    model_download_count = provision_models(layout, runner=runner)
    fingerprint = provider_identity(layout, runner=runner)
    plist_changed = False
    service_newly_loaded = False
    health: dict[str, object] | None = None
    health_wait_seconds = 0.0
    if service_backend == "launchd":
        plist_changed = write_launchd_plist(
            layout,
            batch_size=batch_size,
            device=device,
            runner=runner,
        )
        service_newly_loaded = enable_launchd_service(layout, runner=runner)
        health, health_wait_seconds = wait_for_semantic_health(
            layout,
            provider_fingerprint=fingerprint,
            wait_seconds=wait_seconds,
        )
        if health is None:
            disable_launchd_service(runner=runner)
            disable_private_config(layout)
            raise SetupError("semantic_provider_health_timeout")
    else:
        health = semantic_health(
            layout,
            provider_fingerprint=fingerprint,
        )
        if health is None:
            raise SetupError("manual_semantic_provider_not_ready")
    provider_block = configured_provider_block(
        layout,
        provider_fingerprint=fingerprint,
        support_threshold=support_threshold,
        timeout_seconds=timeout_seconds,
    )
    try:
        config_changed, backup_created = write_private_config(layout, provider_block)
    except Exception:
        if service_backend == "launchd":
            disable_launchd_service(runner=runner)
        disable_private_config(layout)
        raise
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "action": "install",
        "status": "installed",
        "service_backend": service_backend,
        "provider_fingerprint": fingerprint,
        "metrics": {
            "venv_created": int(venv_created),
            "dependency_install_completed": 1,
            "pinned_model_download_count": model_download_count,
            "config_changed": int(config_changed),
            "config_backup_created": int(backup_created),
            "plist_changed": int(plist_changed),
            "service_newly_loaded": int(service_newly_loaded),
            "provider_health_ready": int(health is not None),
            "provider_memory_count": int(health.get("memory_count", 0)) if health else 0,
            "health_wait_seconds": round(health_wait_seconds, 3),
            "repository_mutation_count": 0,
            "archive_content_mutation_count": 0,
        },
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "config_content_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
        },
    }


def disable_runtime(
    layout: RuntimeLayout,
    *,
    service_backend: str,
    runner: Runner = default_runner,
) -> dict[str, object]:
    service_disabled = (
        disable_launchd_service(runner=runner)
        if service_backend == "launchd"
        else False
    )
    config_changed = disable_private_config(layout)
    return {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "action": "disable",
        "status": "disabled",
        "service_backend": service_backend,
        "metrics": {
            "service_disabled": int(service_disabled),
            "config_changed": int(config_changed),
            "runtime_files_removed": 0,
            "model_files_removed": 0,
            "archive_content_mutation_count": 0,
        },
        "privacy": {
            "aggregate_only": True,
            "absolute_paths_rendered": False,
            "config_content_rendered": False,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan", action="store_true")
    action.add_argument("--install", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--disable", action="store_true")
    parser.add_argument("--memory-repo", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--runtime-root", default=str(DEFAULT_RUNTIME_ROOT))
    parser.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    parser.add_argument("--socket")
    parser.add_argument("--plist")
    parser.add_argument("--service-backend", choices=("launchd", "none"), required=True)
    parser.add_argument("--python-version", default=DEFAULT_PYTHON_VERSION)
    parser.add_argument("--support-threshold", type=float, default=DEFAULT_SUPPORT_THRESHOLD)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--wait-seconds", type=float, default=180.0)
    parser.add_argument("--uv")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        layout = build_layout(
            memory_repo=args.memory_repo,
            config_path=args.config,
            runtime_root=args.runtime_root,
            state_root=args.state_root,
            socket_path=args.socket,
            plist_path=args.plist,
        )
        if args.plan:
            report = plan_report(layout, service_backend=args.service_backend)
        elif args.check:
            report = check_report(
                layout,
                service_backend=args.service_backend,
                batch_size=args.batch_size,
                device=args.device,
            )
        elif args.disable:
            report = disable_runtime(layout, service_backend=args.service_backend)
        else:
            uv_value = args.uv or shutil.which("uv")
            if not uv_value:
                raise SetupError("uv_unavailable")
            uv_path = expanded_absolute(uv_value)
            report = install_runtime(
                layout,
                service_backend=args.service_backend,
                python_version=args.python_version,
                support_threshold=args.support_threshold,
                timeout_seconds=args.timeout_seconds,
                batch_size=args.batch_size,
                device=args.device,
                wait_seconds=args.wait_seconds,
                uv_path=uv_path,
            )
    except Exception as exc:
        report = {
            "report_kind": REPORT_KIND,
            "report_version": REPORT_VERSION,
            "status": "blocked",
            "reason": str(exc) if isinstance(exc, SetupError) else "unexpected_setup_failure",
            "privacy": {
                "aggregate_only": True,
                "absolute_paths_rendered": False,
                "config_content_rendered": False,
                "memory_text_rendered": False,
                "source_content_rendered": False,
            },
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in ("planned", "installed", "current", "disabled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
