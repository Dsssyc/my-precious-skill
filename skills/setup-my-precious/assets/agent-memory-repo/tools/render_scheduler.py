#!/usr/bin/env python3
"""Render reviewable scheduler configuration for an agent memory archive.

The script renders local scheduler configuration or agent-native automation
prompts and prepares the local log directory. It does not install, load, or
enable scheduled jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import sys
from pathlib import Path


CONFIG_CANDIDATES = (
    "MY_PRECIOUS_CONFIG",
    "AGENT_SESSION_MEMORY_CONFIG",
)
DEFAULT_CONFIG_PATH = Path("~/.config/my-precious/config.json")


def configured_memory_repos() -> list[str]:
    config_paths: list[str] = []
    for name in CONFIG_CANDIDATES:
        value = os.environ.get(name)
        if value:
            config_paths.append(value)
    config_paths.append(str(DEFAULT_CONFIG_PATH))

    repos: list[str] = []
    for candidate in config_paths:
        path = Path(candidate).expanduser()
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        value = payload.get("memory_repo")
        if isinstance(value, str) and value.strip():
            repos.append(value)
    return repos


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates = []
    if repo_arg:
        candidates.append(repo_arg)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.extend(configured_memory_repos())
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise SystemExit(
        "No memory repository found. Run setup-my-precious, pass --memory-repo, "
        "or set AGENT_SESSION_MEMORY_REPO."
    )


def interval_seconds(schedule: str) -> int:
    if schedule == "hourly":
        return 60 * 60
    if schedule == "daily":
        return 24 * 60 * 60
    raise SystemExit(f"unsupported schedule: {schedule}")


def archive_program_arguments(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path | None,
    allow_redacted_secrets: bool,
) -> list[str]:
    if project_path is None:
        args = [
            "/usr/bin/env",
            "python3",
            str(memory_repo / "tools" / "run_memory_updates.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
        ]
    else:
        args = [
            "/usr/bin/env",
            "python3",
            str(memory_repo / "tools" / "update_memory_archive.py"),
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
            "--project-path",
            str(project_path),
        ]
    if allow_redacted_secrets:
        args.append("--allow-redacted-secrets")
    return args


def shell_archive_command(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path | None,
    allow_redacted_secrets: bool,
) -> list[str]:
    if project_path is None:
        args = [
            f"AGENT_SESSION_MEMORY_REPO={shlex.quote(str(memory_repo))}",
            shlex.quote(sys.executable),
            shlex.quote(str(memory_repo / "tools" / "run_memory_updates.py")),
            "--memory-repo",
            shlex.quote(str(memory_repo)),
            "--source-dir",
            shlex.quote(str(source_dir)),
        ]
    else:
        args = [
            f"AGENT_SESSION_MEMORY_REPO={shlex.quote(str(memory_repo))}",
            shlex.quote(sys.executable),
            shlex.quote(str(memory_repo / "tools" / "update_memory_archive.py")),
            "--memory-repo",
            shlex.quote(str(memory_repo)),
            "--source-dir",
            shlex.quote(str(source_dir)),
            "--project-path",
            shlex.quote(str(project_path)),
        ]
    if allow_redacted_secrets:
        args.append("--allow-redacted-secrets")
    return args


def agent_native_prompt(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path | None,
    allow_redacted_secrets: bool,
    push: bool,
) -> str:
    if project_path is None:
        update_command = [
            "python",
            "tools/run_memory_updates.py",
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
        ]
    else:
        update_command = [
            "python",
            "tools/update_memory_archive.py",
            "--memory-repo",
            str(memory_repo),
            "--source-dir",
            str(source_dir),
            "--project-path",
            str(project_path),
        ]
    if allow_redacted_secrets:
        update_command.append("--allow-redacted-secrets")

    sync_command = ["python", "tools/sync_memory_archive.py"]
    if push:
        sync_command.append("--push")

    return "\n".join(
        [
            "Run the My Precious memory update from this memory repository workspace.",
            "",
            "Use exactly one working directory:",
            str(memory_repo),
            "",
            "Run:",
            shlex.join(update_command),
            "python tools/search_memory.py memory",
            shlex.join(sync_command),
            "",
            "Do not upload raw transcripts.",
            "Do not report or reproduce original secret values.",
            "If any command refuses to continue, stop and report the failing command and summarized error only.",
            "",
        ]
    )


def launchd_plist(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path | None,
    schedule: str,
    label: str,
    allow_redacted_secrets: bool,
) -> bytes:
    log_dir = memory_repo / ".tmp" / "logs"
    payload = {
        "Label": label,
        "ProgramArguments": archive_program_arguments(memory_repo, source_dir, project_path, allow_redacted_secrets),
        "StartInterval": interval_seconds(schedule),
        "WorkingDirectory": str(memory_repo),
        "EnvironmentVariables": {
            "AGENT_SESSION_MEMORY_REPO": str(memory_repo),
        },
        "StandardOutPath": str(log_dir / "update.out.log"),
        "StandardErrorPath": str(log_dir / "update.err.log"),
    }
    return plistlib.dumps(payload, sort_keys=True)


def cron_line(
    memory_repo: Path,
    source_dir: Path,
    project_path: Path | None,
    schedule: str,
    allow_redacted_secrets: bool,
) -> str:
    when = "0 * * * *" if schedule == "hourly" else "0 9 * * *"
    log_dir = memory_repo / ".tmp" / "logs"
    command = " ".join(
        [
            "cd",
            shlex.quote(str(memory_repo)),
            "&&",
            *shell_archive_command(memory_repo, source_dir, project_path, allow_redacted_secrets),
            ">>",
            shlex.quote(str(log_dir / "update.out.log")),
            "2>>",
            shlex.quote(str(log_dir / "update.err.log")),
        ]
    )
    return f"{when} {command}\n"


def validate_archive_command(memory_repo: Path, project_path: Path | None) -> None:
    if project_path is None:
        runner = memory_repo / "tools" / "run_memory_updates.py"
        if not runner.exists():
            raise SystemExit(f"global scheduler requires {runner}")
        return
    updater = memory_repo / "tools" / "update_memory_archive.py"
    if not updater.exists():
        raise SystemExit(f"single-project scheduler requires {updater}")


def validate_sync_command(memory_repo: Path) -> None:
    syncer = memory_repo / "tools" / "sync_memory_archive.py"
    if not syncer.exists():
        raise SystemExit(f"agent-native scheduler requires {syncer}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--source-dir", required=True, help="Directory containing source records to scan")
    parser.add_argument("--project-path", help="Optional single project path; omit to run the global project runner")
    parser.add_argument(
        "--backend",
        choices=("launchd", "cron", "agent-native"),
        default="launchd",
        help="Scheduler format or agent-native automation prompt to render",
    )
    parser.add_argument("--schedule", choices=("hourly", "daily"), default="daily", help="Run frequency")
    parser.add_argument("--label", default="com.agent-memory.update", help="launchd label")
    parser.add_argument(
        "--allow-redacted-secrets",
        action="store_true",
        help="Include --allow-redacted-secrets in rendered archive commands",
    )
    parser.add_argument(
        "--push-after-update",
        action="store_true",
        help="For agent-native prompts, ask the agent to push after safe archive sync",
    )
    parser.add_argument("--output", help="Write rendered scheduler config to this path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_repo = resolve_memory_repo(args.memory_repo)
    source_dir = Path(args.source_dir).expanduser().resolve()
    project_path = Path(args.project_path).expanduser().resolve() if args.project_path else None
    validate_archive_command(memory_repo, project_path)
    if args.backend == "agent-native":
        validate_sync_command(memory_repo)
    (memory_repo / ".tmp" / "logs").mkdir(parents=True, exist_ok=True)

    if args.backend == "launchd":
        content = launchd_plist(
            memory_repo,
            source_dir,
            project_path,
            args.schedule,
            args.label,
            args.allow_redacted_secrets,
        )
        mode = "wb"
    elif args.backend == "agent-native":
        content = agent_native_prompt(
            memory_repo,
            source_dir,
            project_path,
            args.allow_redacted_secrets,
            args.push_after_update,
        ).encode("utf-8")
        mode = "wb"
    else:
        content = cron_line(
            memory_repo,
            source_dir,
            project_path,
            args.schedule,
            args.allow_redacted_secrets,
        ).encode("utf-8")
        mode = "wb"

    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open(mode) as handle:
            handle.write(content)
        print(f"Rendered scheduler config: {output}")
    else:
        sys.stdout.buffer.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
