#!/usr/bin/env python3
"""Render reviewable scheduler configuration for an agent memory archive.

The script renders configuration and prepares the local log directory. It does
not install, load, or enable scheduled jobs.
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import sys
from pathlib import Path


def resolve_memory_repo(repo_arg: str | None) -> Path:
    candidates = []
    if repo_arg:
        candidates.append(repo_arg)
    for env_name in ("AGENT_SESSION_MEMORY_REPO", "AGENT_MEMORY_REPO"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    candidates.append(str(Path(__file__).resolve().parents[1]))
    candidates.append(os.getcwd())
    candidates.append("~/repos/agent-memory")
    for candidate in candidates:
        repo = Path(candidate).expanduser()
        if repo.exists() and (repo / "tools" / "update_memory_archive.py").exists():
            return repo.resolve()
    raise SystemExit("No memory repository found. Pass --memory-repo or set AGENT_SESSION_MEMORY_REPO.")


def interval_seconds(schedule: str) -> int:
    if schedule == "hourly":
        return 60 * 60
    if schedule == "daily":
        return 24 * 60 * 60
    raise SystemExit(f"unsupported schedule: {schedule}")


def launchd_plist(memory_repo: Path, source_dir: Path, project_path: Path, schedule: str, label: str) -> bytes:
    log_dir = memory_repo / ".tmp" / "logs"
    program_arguments = [
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
    payload = {
        "Label": label,
        "ProgramArguments": program_arguments,
        "StartInterval": interval_seconds(schedule),
        "WorkingDirectory": str(memory_repo),
        "EnvironmentVariables": {
            "AGENT_SESSION_MEMORY_REPO": str(memory_repo),
        },
        "StandardOutPath": str(log_dir / "update.out.log"),
        "StandardErrorPath": str(log_dir / "update.err.log"),
    }
    return plistlib.dumps(payload, sort_keys=True)


def cron_line(memory_repo: Path, source_dir: Path, project_path: Path, schedule: str) -> str:
    when = "0 * * * *" if schedule == "hourly" else "0 9 * * *"
    log_dir = memory_repo / ".tmp" / "logs"
    command = " ".join(
        [
            "cd",
            shlex.quote(str(memory_repo)),
            "&&",
            f"AGENT_SESSION_MEMORY_REPO={shlex.quote(str(memory_repo))}",
            shlex.quote(sys.executable),
            shlex.quote(str(memory_repo / "tools" / "update_memory_archive.py")),
            "--memory-repo",
            shlex.quote(str(memory_repo)),
            "--source-dir",
            shlex.quote(str(source_dir)),
            "--project-path",
            shlex.quote(str(project_path)),
            ">>",
            shlex.quote(str(log_dir / "update.out.log")),
            "2>>",
            shlex.quote(str(log_dir / "update.err.log")),
        ]
    )
    return f"{when} {command}\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-repo", help="Path to the private memory repository")
    parser.add_argument("--source-dir", required=True, help="Directory containing source records to scan")
    parser.add_argument("--project-path", required=True, help="Project path used as the high-water-mark key")
    parser.add_argument("--backend", choices=("launchd", "cron"), default="launchd", help="Scheduler format to render")
    parser.add_argument("--schedule", choices=("hourly", "daily"), default="daily", help="Run frequency")
    parser.add_argument("--label", default="com.agent-memory.update", help="launchd label")
    parser.add_argument("--output", help="Write rendered scheduler config to this path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    memory_repo = resolve_memory_repo(args.memory_repo)
    source_dir = Path(args.source_dir).expanduser().resolve()
    project_path = Path(args.project_path).expanduser().resolve()
    (memory_repo / ".tmp" / "logs").mkdir(parents=True, exist_ok=True)

    if args.backend == "launchd":
        content = launchd_plist(memory_repo, source_dir, project_path, args.schedule, args.label)
        mode = "wb"
    else:
        content = cron_line(memory_repo, source_dir, project_path, args.schedule).encode("utf-8")
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
