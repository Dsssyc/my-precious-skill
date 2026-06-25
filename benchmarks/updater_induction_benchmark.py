#!/usr/bin/env python3
"""Run an updater-driven synthetic induction benchmark.

The runner creates temporary synthetic source records, runs the real archive
setup and update scripts, then reports aggregate-only write-path metrics. It
does not render source content, memory text, source paths, raw anchors, or
case-level details.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETUP_SCRIPT = REPO_ROOT / "skills/setup-my-precious/scripts/setup_memory_archive.py"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
SAFE_REL_PATH_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,240}$")
SENSITIVE_OUTPUT_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:api[_-]?key|authorization|bearer|cookie|credential|password|"
    r"private[_ -]?key|secret|session[_-]?id|token)\b\s*[:=]|"
    r"\bbearer\s+\S+|"
    r"\bsk-[A-Za-z0-9_-]{20,}\b|"
    r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r")"
)
FALSE_PROMOTION_REASON_METRICS = {
    "ephemeral_status": "ephemeral_status",
    "hypothetical": "hypothetical",
    "acknowledgement_only": "acknowledgement_only",
    "temporary_local_decision": "temporary_local_decision",
    "generic_rule": "generic_rule",
}


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class CaseScore:
    passed: bool
    leaked: bool
    induction_cases: int = 0
    induction_hits: int = 0
    false_promotion_cases: int = 0
    false_promotions: int = 0
    ephemeral_status_cases: int = 0
    ephemeral_status_rejections: int = 0
    hypothetical_cases: int = 0
    hypothetical_rejections: int = 0
    acknowledgement_only_cases: int = 0
    acknowledgement_only_rejections: int = 0
    temporary_local_decision_cases: int = 0
    temporary_local_decision_rejections: int = 0
    generic_rule_cases: int = 0
    generic_rule_rejections: int = 0
    natural_cases: int = 0
    natural_hits: int = 0
    cross_project_generalization_cases: int = 0
    cross_project_generalization_hits: int = 0
    project_scope_precision_cases: int = 0
    project_scope_precision_hits: int = 0
    review_cases: int = 0
    review_hits: int = 0
    noise_cases: int = 0
    noise_hits: int = 0
    layer_cases: int = 0
    layer_hits: int = 0
    evidence_cases: int = 0
    evidence_hits: int = 0
    source_ref_cases: int = 0
    source_ref_hits: int = 0
    lifecycle_cases: int = 0
    lifecycle_hits: int = 0
    forced_cases: int = 0
    forced_hits: int = 0
    refusal_cases: int = 0
    refusal_hits: int = 0
    redaction_cases: int = 0
    redaction_hits: int = 0
    source_records: int = 0


def ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


def false_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def safe_id(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not SAFE_ID_RE.fullmatch(text):
        raise SystemExit(f"unsafe {field}")
    return text


def safe_category(value: object) -> str:
    return safe_id(value or "uncategorized", "category")


def safe_case_slug(case_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", case_id)[:120]


def is_safe_relative_path(value: object) -> bool:
    text = str(value or "").strip()
    if not text or not SAFE_REL_PATH_RE.fullmatch(text):
        return False
    if text.startswith(("/", "~", "\\")) or re.match(r"^[A-Za-z]:[\\/]", text):
        return False
    return not any(part == ".." for part in re.split(r"[\\/]+", text))


def cases_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSONL case at line {line_no}") from exc
            if not isinstance(value, dict):
                raise SystemExit(f"benchmark case at line {line_no} must be an object")
            yield value


def validate_cases(cases: list[dict[str, Any]]) -> None:
    if not cases:
        raise SystemExit("no benchmark cases found")
    seen: set[str] = set()
    for case in cases:
        case_id = safe_id(case.get("case_id"), "case_id")
        if case_id in seen:
            raise SystemExit("duplicate case_id")
        seen.add(case_id)
        safe_category(case.get("category"))
        records = case.get("records")
        if not isinstance(records, list) or not records:
            raise SystemExit("benchmark case records must be a non-empty list")
        for record in records:
            if not isinstance(record, dict):
                raise SystemExit("benchmark record must be an object")
            safe_id(record.get("record_id"), "record_id")
            safe_id(record.get("project_key"), "project_key")
            safe_id(record.get("project"), "project")
            if not isinstance(record.get("events"), list) or not record["events"]:
                raise SystemExit("benchmark record events must be a non-empty list")
            for event in record["events"]:
                if not isinstance(event, dict):
                    raise SystemExit("benchmark event must be an object")
                if str(event.get("role") or "") not in {"user", "assistant"}:
                    raise SystemExit("benchmark event role must be user or assistant")
                if not isinstance(event.get("content"), str) or not event["content"].strip():
                    raise SystemExit("benchmark event content must be non-empty text")


def timestamp_to_epoch(stamp: str) -> float:
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).timestamp()


def synthetic_openai_key() -> str:
    return "sk-" + "syntheticnotreal" + ("0" * 20)


def synthetic_bearer_token() -> str:
    return "syntheticbearervalue" + ("0" * 24)


def expand_synthetic_placeholders(text: str) -> str:
    bearer_prefix = "Be" + "arer "
    auth_header = "Author" + "ization: " + bearer_prefix + synthetic_bearer_token()
    return (
        text.replace("{{OPENAI_KEY}}", synthetic_openai_key())
        .replace("{{BEARER_TOKEN}}", bearer_prefix + synthetic_bearer_token())
        .replace("{{AUTHORIZATION_BEARER}}", auth_header)
    )


def run_command(command: list[str], *, cwd: Path | None = None) -> CommandResult:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def setup_archive(memory_repo: Path, setup_script: Path) -> None:
    result = run_command(
        [
            sys.executable,
            str(setup_script),
            "--path",
            str(memory_repo),
            "--mode",
            "local",
            "--skip-config",
        ]
    )
    if result.returncode != 0:
        raise SystemExit("archive setup failed")


def write_source_record(case_root: Path, record: dict[str, Any]) -> tuple[Path, Path, Path]:
    record_id = safe_id(record.get("record_id"), "record_id")
    project_key = safe_id(record.get("project_key"), "project_key")
    source_dir = case_root / "source-records" / record_id
    project_path = case_root / "projects" / project_key
    source_dir.mkdir(parents=True, exist_ok=True)
    project_path.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"{record_id}.jsonl"
    lines = []
    for event in record["events"]:
        payload = {
            "role": str(event["role"]),
            "content": expand_synthetic_placeholders(str(event["content"])),
        }
        lines.append(json.dumps(payload, sort_keys=True))
    source_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.utime(source_path, (timestamp_to_epoch(str(record["updated_at"])),) * 2)
    return source_dir, project_path, source_path


def run_update(memory_repo: Path, source_dir: Path, project_path: Path, record: dict[str, Any]) -> CommandResult:
    command = [
        sys.executable,
        str(memory_repo / "tools/update_memory_archive.py"),
        "--source-dir",
        str(source_dir),
        "--project-path",
        str(project_path),
        "--project",
        safe_id(record.get("project"), "project"),
        "--source-agent",
        "synthetic-agent",
        "--rewrite-existing",
    ]
    if record.get("allow_redacted_secrets") is True:
        command.append("--allow-redacted-secrets")
    return run_command(command)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def load_nodes(memory_repo: Path) -> list[dict[str, Any]]:
    return load_jsonl(memory_repo / "index/memories.jsonl")


def load_meta_rows(memory_repo: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((memory_repo / "sessions").glob("**/meta.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_review_candidates(memory_repo: Path) -> list[dict[str, Any]]:
    return load_jsonl(memory_repo / "index/memory_review_candidates.jsonl")


def node_by_text(nodes: list[dict[str, Any]], text: str, source: str) -> dict[str, Any] | None:
    for node in nodes:
        if node.get("text") == text and node.get("source") == source:
            return node
    return None


def node_int(node: dict[str, Any], key: str) -> int:
    try:
        return int(node.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def node_list_len(node: dict[str, Any], key: str) -> int:
    value = node.get(key)
    return len(value) if isinstance(value, list) else 0


def cross_project_generalization_hit(node: dict[str, Any] | None) -> bool:
    return bool(
        node is not None
        and node.get("layer") == "domain"
        and node_int(node, "support_count") >= 2
        and node_list_len(node, "derived_from") >= 2
    )


def project_scope_precision_hit(node: dict[str, Any] | None) -> bool:
    return bool(
        node is not None
        and node.get("layer") == "project"
        and isinstance(node.get("scope"), str)
        and str(node["scope"]).startswith("project:")
    )


def evidence_quote_id_exists(path: Path, quote_id: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return bool(re.search(rf"(?m)^\s*{re.escape(quote_id)}\s*:", text))


def evidence_retained(memory_repo: Path, node: dict[str, Any], expected: dict[str, Any]) -> bool:
    derived_from = node.get("derived_from")
    evidence_refs = node.get("evidence_refs")
    if not isinstance(derived_from, list) or not isinstance(evidence_refs, list):
        return False
    if len(derived_from) < int(expected.get("min_derived_from") or 0):
        return False
    if len(evidence_refs) < int(expected.get("min_evidence_refs") or 0):
        return False
    for path_text in derived_from:
        if not is_safe_relative_path(path_text) or not (memory_repo / str(path_text)).is_file():
            return False
    for ref in evidence_refs:
        if not isinstance(ref, dict):
            return False
        path_text = ref.get("path")
        quote_id = ref.get("quote_id")
        if not isinstance(path_text, str) or not isinstance(quote_id, str):
            return False
        if not is_safe_relative_path(path_text):
            return False
        evidence_path = memory_repo / path_text
        if not evidence_path.is_file() or not evidence_quote_id_exists(evidence_path, quote_id):
            return False
    return True


def raw_refs_policy_pass(memory_repo: Path, node: dict[str, Any]) -> bool:
    raw_refs = node.get("raw_refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        return False
    for ref in raw_refs:
        if not isinstance(ref, dict):
            return False
        path_text = ref.get("path")
        anchor = ref.get("anchor")
        if not isinstance(path_text, str) or not isinstance(anchor, str):
            return False
        if not is_safe_relative_path(path_text) or not SAFE_REL_PATH_RE.fullmatch(anchor):
            return False
        if not (memory_repo / path_text).is_file():
            return False
    return True


def lifecycle_link_hit(
    nodes: list[dict[str, Any]],
    relation: str,
    current_text: str,
    target_text: str,
) -> bool:
    current = next((node for node in nodes if node.get("text") == current_text), None)
    target = next((node for node in nodes if node.get("text") == target_text), None)
    if current is None or target is None:
        return False
    current_id = current.get("memory_id")
    target_id = target.get("memory_id")
    if not isinstance(current_id, str) or not isinstance(target_id, str):
        return False
    if relation == "supersedes":
        return target_id in list_texts(current.get("supersedes")) and target.get("superseded_by") == current_id
    if relation == "contradicts":
        return target_id in list_texts(current.get("contradicts")) and current_id in list_texts(
            target.get("contradicted_by")
        )
    if relation == "deprecates":
        return target_id in list_texts(current.get("deprecates")) and target.get("deprecated_by") == current_id
    return False


def review_candidate_hit(
    nodes: list[dict[str, Any]],
    review_candidates: list[dict[str, Any]],
    expected: dict[str, Any],
) -> bool:
    current = node_by_text(nodes, str(expected.get("current_text") or ""), "automatic")
    older = node_by_text(nodes, str(expected.get("older_text") or ""), "automatic")
    if current is None or older is None:
        return False
    current_id = current.get("memory_id")
    older_id = older.get("memory_id")
    reason = str(expected.get("reason") or "")
    if not isinstance(current_id, str) or not isinstance(older_id, str) or not reason:
        return False
    for candidate in review_candidates:
        if (
            candidate.get("current_memory_id") == current_id
            and candidate.get("older_memory_id") == older_id
            and candidate.get("reason") == reason
            and candidate.get("recommended_action") == "manual_review"
        ):
            return True
    return False


def noise_rejection_hit(nodes: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    text = str(expected.get("text") or "").strip()
    pattern = str(expected.get("pattern") or "").strip()
    for node in nodes:
        node_text = str(node.get("text") or "")
        if text and node_text == text:
            return False
        if pattern:
            try:
                if re.search(pattern, node_text, re.IGNORECASE):
                    return False
            except re.error as exc:
                raise SystemExit("invalid expected noise rejection pattern") from exc
    return True


def false_promotion_present(nodes: list[dict[str, Any]], expected: dict[str, Any]) -> bool:
    text = str(expected.get("text") or "").strip()
    pattern = str(expected.get("pattern") or "").strip()
    if not text and not pattern:
        raise SystemExit("expected_false_promotions entries must include text or pattern")
    for node in nodes:
        node_text = str(node.get("text") or "")
        if text and node_text == text:
            return True
        if pattern:
            try:
                if re.search(pattern, node_text, re.IGNORECASE):
                    return True
            except re.error as exc:
                raise SystemExit("invalid expected false promotion pattern") from exc
    return False


def score_natural_quality_expectations(
    case: dict[str, Any],
    memory_repo: Path,
    nodes: list[dict[str, Any]],
) -> Counter:
    score = Counter()
    for expected in case.get("expected_memories") or []:
        if not isinstance(expected, dict):
            raise SystemExit("expected_memories entries must be objects")
        node = node_by_text(nodes, str(expected.get("text") or ""), str(expected.get("source") or ""))
        if expected.get("natural_induction") is True:
            score["natural_cases"] += 1
            score["natural_hits"] += int(node is not None)
        if expected.get("cross_project_generalization") is True:
            score["cross_project_generalization_cases"] += 1
            score["cross_project_generalization_hits"] += int(cross_project_generalization_hit(node))
        if expected.get("project_scope_precision") is True:
            score["project_scope_precision_cases"] += 1
            score["project_scope_precision_hits"] += int(project_scope_precision_hit(node))

    review_candidates = load_review_candidates(memory_repo)
    for expected in case.get("expected_review_candidates") or []:
        if not isinstance(expected, dict):
            raise SystemExit("expected_review_candidates entries must be objects")
        score["review_cases"] += 1
        score["review_hits"] += int(review_candidate_hit(nodes, review_candidates, expected))

    for expected in case.get("expected_noise_rejections") or []:
        if not isinstance(expected, dict):
            raise SystemExit("expected_noise_rejections entries must be objects")
        score["noise_cases"] += 1
        score["noise_hits"] += int(noise_rejection_hit(nodes, expected))

    for expected in case.get("expected_false_promotions") or []:
        if not isinstance(expected, dict):
            raise SystemExit("expected_false_promotions entries must be objects")
        score["false_promotion_cases"] += 1
        promoted = false_promotion_present(nodes, expected)
        score["false_promotions"] += int(promoted)
        reason = str(expected.get("reason") or "")
        metric = FALSE_PROMOTION_REASON_METRICS.get(reason)
        if metric:
            score[f"{metric}_cases"] += 1
            score[f"{metric}_rejections"] += int(not promoted)
    return score


def natural_quality_expectations_pass(score: Counter) -> bool:
    pairs = (
        ("natural_hits", "natural_cases"),
        ("cross_project_generalization_hits", "cross_project_generalization_cases"),
        ("project_scope_precision_hits", "project_scope_precision_cases"),
        ("review_hits", "review_cases"),
        ("noise_hits", "noise_cases"),
    )
    rejection_pairs = tuple(
        (f"{metric}_rejections", f"{metric}_cases")
        for metric in FALSE_PROMOTION_REASON_METRICS.values()
    )
    return (
        score["false_promotions"] == 0
        and all(score[hits] == score[cases] for hits, cases in pairs)
        and all(score[hits] == score[cases] for hits, cases in rejection_pairs)
    )


def list_texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def generated_archive_text(memory_repo: Path) -> str:
    roots = [
        memory_repo / "sessions",
        memory_repo / "index",
        memory_repo / "memories",
        memory_repo / "daily",
        memory_repo / "INDEX.md",
    ]
    chunks: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(path for path in root.glob("**/*") if path.is_file())
        for path in paths:
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def forbidden_output_hit(text: str, patterns: object) -> bool:
    if not isinstance(patterns, list):
        return False
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            continue
        try:
            if re.search(pattern, text):
                return True
        except re.error:
            raise SystemExit("invalid forbidden output pattern")
    return False


def strip_redacted_secret_placeholders(text: str) -> str:
    text = re.sub(
        r"(?i)\bauthorization\s*:\s*bearer\s+\[REDACTED_[A-Z0-9_]+\]",
        "[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)\bbearer\s+\[REDACTED_[A-Z0-9_]+\]", "[REDACTED]", text)
    return re.sub(r"\[REDACTED_[A-Z0-9_]+\]", "[REDACTED]", text)


def privacy_leaked(case: dict[str, Any], command_outputs: list[CommandResult], memory_repo: Path) -> bool:
    public_like_output = "\n".join(result.stdout + "\n" + result.stderr for result in command_outputs)
    archive_output = generated_archive_text(memory_repo)
    combined = public_like_output + "\n" + archive_output
    sensitive_scan_text = strip_redacted_secret_placeholders(combined)
    return bool(
        SENSITIVE_OUTPUT_RE.search(sensitive_scan_text)
        or forbidden_output_hit(combined, case.get("forbidden_output_patterns"))
    )


def refusal_pass(memory_repo: Path, result: CommandResult) -> bool:
    return (
        result.returncode != 0
        and "Refusing to archive" in result.stderr
        and not any((memory_repo / "sessions").glob("**/summary.md"))
    )


def redaction_pass(meta_rows: list[dict[str, Any]]) -> bool:
    if not meta_rows:
        return False
    for row in meta_rows:
        if row.get("redaction_status") == "redacted" and isinstance(row.get("redaction_counts"), dict):
            if row["redaction_counts"]:
                return True
    return False


def score_case(case: dict[str, Any], run_root: Path, setup_script: Path) -> CaseScore:
    case_id = safe_id(case.get("case_id"), "case_id")
    case_root = run_root / safe_case_slug(case_id)
    case_root.mkdir(parents=True, exist_ok=True)
    memory_repo = case_root / "synthetic-memory-archive"
    setup_archive(memory_repo, setup_script)

    command_outputs: list[CommandResult] = []
    unexpected_update_failure = False
    refusal_cases = 0
    refusal_hits = 0
    source_records = 0
    for record in case["records"]:
        source_records += 1
        source_dir, project_path, _ = write_source_record(case_root, record)
        result = run_update(memory_repo, source_dir, project_path, record)
        command_outputs.append(result)
        if record.get("expect_refusal") is True:
            refusal_cases += 1
            refusal_hits += int(refusal_pass(memory_repo, result))
        elif result.returncode != 0:
            unexpected_update_failure = True

    nodes = load_nodes(memory_repo)
    meta_rows = load_meta_rows(memory_repo)
    leaked = privacy_leaked(case, command_outputs, memory_repo)
    natural_quality = score_natural_quality_expectations(case, memory_repo, nodes)

    score = CaseScore(
        passed=not unexpected_update_failure and not leaked,
        leaked=leaked,
        refusal_cases=refusal_cases,
        refusal_hits=refusal_hits,
        source_records=source_records,
        false_promotion_cases=natural_quality["false_promotion_cases"],
        false_promotions=natural_quality["false_promotions"],
        ephemeral_status_cases=natural_quality["ephemeral_status_cases"],
        ephemeral_status_rejections=natural_quality["ephemeral_status_rejections"],
        hypothetical_cases=natural_quality["hypothetical_cases"],
        hypothetical_rejections=natural_quality["hypothetical_rejections"],
        acknowledgement_only_cases=natural_quality["acknowledgement_only_cases"],
        acknowledgement_only_rejections=natural_quality["acknowledgement_only_rejections"],
        temporary_local_decision_cases=natural_quality["temporary_local_decision_cases"],
        temporary_local_decision_rejections=natural_quality["temporary_local_decision_rejections"],
        generic_rule_cases=natural_quality["generic_rule_cases"],
        generic_rule_rejections=natural_quality["generic_rule_rejections"],
        natural_cases=natural_quality["natural_cases"],
        natural_hits=natural_quality["natural_hits"],
        cross_project_generalization_cases=natural_quality["cross_project_generalization_cases"],
        cross_project_generalization_hits=natural_quality["cross_project_generalization_hits"],
        project_scope_precision_cases=natural_quality["project_scope_precision_cases"],
        project_scope_precision_hits=natural_quality["project_scope_precision_hits"],
        review_cases=natural_quality["review_cases"],
        review_hits=natural_quality["review_hits"],
        noise_cases=natural_quality["noise_cases"],
        noise_hits=natural_quality["noise_hits"],
    )
    if case.get("expected_redaction") is True:
        score.redaction_cases += 1
        score.redaction_hits += int(redaction_pass(meta_rows) and not leaked)

    for expected in case.get("expected_memories") or []:
        if not isinstance(expected, dict):
            raise SystemExit("expected_memories entries must be objects")
        text = str(expected.get("text") or "")
        source = str(expected.get("source") or "")
        node = node_by_text(nodes, text, source)
        found = node is not None
        if source == "automatic":
            score.induction_cases += 1
            score.induction_hits += int(found)
        elif source == "explicit":
            score.forced_cases += 1
            score.forced_hits += int(
                found and node is not None and node.get("persistence") == "sticky"
            )
        else:
            raise SystemExit("expected memory source must be automatic or explicit")

        if "layer" in expected:
            score.layer_cases += 1
            score.layer_hits += int(found and node is not None and node.get("layer") == expected["layer"])
        if expected.get("min_derived_from") or expected.get("min_evidence_refs"):
            score.evidence_cases += 1
            score.evidence_hits += int(found and node is not None and evidence_retained(memory_repo, node, expected))
        if expected.get("expect_source_ref") is True:
            score.source_ref_cases += 1
            score.source_ref_hits += int(found and node is not None and raw_refs_policy_pass(memory_repo, node))

    for expected in case.get("expected_lifecycle_links") or []:
        if not isinstance(expected, dict):
            raise SystemExit("expected_lifecycle_links entries must be objects")
        score.lifecycle_cases += 1
        score.lifecycle_hits += int(
            lifecycle_link_hit(
                nodes,
                str(expected.get("relation") or ""),
                str(expected.get("current_text") or ""),
                str(expected.get("target_text") or ""),
            )
        )

    score.passed = score.passed and all(
        (
            score.induction_hits == score.induction_cases,
            score.layer_hits == score.layer_cases,
            score.evidence_hits == score.evidence_cases,
            score.source_ref_hits == score.source_ref_cases,
            score.lifecycle_hits == score.lifecycle_cases,
            score.forced_hits == score.forced_cases,
            score.refusal_hits == score.refusal_cases,
            score.redaction_hits == score.redaction_cases,
            natural_quality_expectations_pass(natural_quality),
        )
    )
    return score


def prepare_work_dir(work_dir: str | None):
    if work_dir:
        path = Path(work_dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        if any(path.iterdir()):
            raise SystemExit("--work-dir must be empty")
        return path, None
    temp = tempfile.TemporaryDirectory(prefix="my-precious-updater-induction-")
    return Path(temp.name), temp


def parse_thresholds(values: list[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit("thresholds must use metric=value")
        metric, raw_threshold = value.split("=", 1)
        metric = metric.strip()
        if not SAFE_ID_RE.fullmatch(metric):
            raise SystemExit("unsafe threshold metric name")
        try:
            thresholds[metric] = float(raw_threshold)
        except ValueError as exc:
            raise SystemExit("threshold value must be numeric") from exc
    return thresholds


def load_threshold_file(path_text: str | None) -> dict[str, float]:
    if not path_text:
        return {}
    path = Path(path_text).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("unable to read threshold file") from exc
    if not isinstance(payload, dict):
        raise SystemExit("threshold file must contain an object")
    out: dict[str, float] = {}
    for key, value in payload.items():
        if not SAFE_ID_RE.fullmatch(str(key)):
            raise SystemExit("unsafe threshold metric name")
        if not isinstance(value, (int, float)):
            raise SystemExit("threshold values must be numeric")
        out[str(key)] = float(value)
    return out


def apply_quality_gates(report: dict[str, Any], fail_under: dict[str, float], fail_over: dict[str, float]) -> list[str]:
    failures: list[str] = []
    for metric, threshold in sorted(fail_under.items()):
        value = report.get(metric)
        if not isinstance(value, (int, float)) or float(value) < threshold:
            failures.append(f"{metric} below threshold")
    for metric, threshold in sorted(fail_over.items()):
        value = report.get(metric)
        if not isinstance(value, (int, float)) or float(value) > threshold:
            failures.append(f"{metric} above threshold")
    return failures


def build_report(cases: list[dict[str, Any]], scores: list[CaseScore], fingerprint: str) -> dict[str, Any]:
    totals = Counter()
    category_counts = Counter(safe_category(case.get("category")) for case in cases)
    for score in scores:
        totals["source_records"] += score.source_records
        totals["induction_cases"] += score.induction_cases
        totals["induction_hits"] += score.induction_hits
        totals["false_promotion_cases"] += score.false_promotion_cases
        totals["false_promotions"] += score.false_promotions
        totals["ephemeral_status_cases"] += score.ephemeral_status_cases
        totals["ephemeral_status_rejections"] += score.ephemeral_status_rejections
        totals["hypothetical_cases"] += score.hypothetical_cases
        totals["hypothetical_rejections"] += score.hypothetical_rejections
        totals["acknowledgement_only_cases"] += score.acknowledgement_only_cases
        totals["acknowledgement_only_rejections"] += score.acknowledgement_only_rejections
        totals["temporary_local_decision_cases"] += score.temporary_local_decision_cases
        totals["temporary_local_decision_rejections"] += score.temporary_local_decision_rejections
        totals["generic_rule_cases"] += score.generic_rule_cases
        totals["generic_rule_rejections"] += score.generic_rule_rejections
        totals["natural_cases"] += score.natural_cases
        totals["natural_hits"] += score.natural_hits
        totals["cross_project_generalization_cases"] += score.cross_project_generalization_cases
        totals["cross_project_generalization_hits"] += score.cross_project_generalization_hits
        totals["project_scope_precision_cases"] += score.project_scope_precision_cases
        totals["project_scope_precision_hits"] += score.project_scope_precision_hits
        totals["review_cases"] += score.review_cases
        totals["review_hits"] += score.review_hits
        totals["noise_cases"] += score.noise_cases
        totals["noise_hits"] += score.noise_hits
        totals["layer_cases"] += score.layer_cases
        totals["layer_hits"] += score.layer_hits
        totals["evidence_cases"] += score.evidence_cases
        totals["evidence_hits"] += score.evidence_hits
        totals["source_ref_cases"] += score.source_ref_cases
        totals["source_ref_hits"] += score.source_ref_hits
        totals["lifecycle_cases"] += score.lifecycle_cases
        totals["lifecycle_hits"] += score.lifecycle_hits
        totals["forced_cases"] += score.forced_cases
        totals["forced_hits"] += score.forced_hits
        totals["refusal_cases"] += score.refusal_cases
        totals["refusal_hits"] += score.refusal_hits
        totals["redaction_cases"] += score.redaction_cases
        totals["redaction_hits"] += score.redaction_hits
        totals["privacy_leak_count"] += int(score.leaked)
        totals["failed_case_count"] += int(not score.passed)
    return {
        "report_version": 1,
        "report_kind": "updater_induction_benchmark",
        "cases_sha256": fingerprint,
        "privacy": {
            "aggregate_only": True,
            "case_details_rendered": False,
            "memory_text_rendered": False,
            "source_content_rendered": False,
            "source_paths_rendered": False,
            "raw_refs_rendered": False,
        },
        "cases": len(cases),
        "source_records": int(totals["source_records"]),
        "category_counts": dict(sorted(category_counts.items())),
        "expected_automatic_memories": int(totals["induction_cases"]),
        "expected_forced_memories": int(totals["forced_cases"]),
        "expected_lifecycle_links": int(totals["lifecycle_cases"]),
        "expected_privacy_refusals": int(totals["refusal_cases"]),
        "expected_privacy_redactions": int(totals["redaction_cases"]),
        "induction_success_rate": ratio(totals["induction_hits"], totals["induction_cases"]),
        "natural_induction_success_rate": ratio(totals["natural_hits"], totals["natural_cases"]),
        "natural_false_promotion_rate": false_rate(totals["false_promotions"], totals["false_promotion_cases"]),
        "cross_project_generalization_rate": ratio(
            totals["cross_project_generalization_hits"],
            totals["cross_project_generalization_cases"],
        ),
        "project_scope_precision": ratio(
            totals["project_scope_precision_hits"],
            totals["project_scope_precision_cases"],
        ),
        "ambiguous_candidate_review_rate": ratio(totals["review_hits"], totals["review_cases"]),
        "review_routing_rate": ratio(totals["review_hits"], totals["review_cases"]),
        "ephemeral_status_rejection_rate": ratio(
            totals["ephemeral_status_rejections"],
            totals["ephemeral_status_cases"],
        ),
        "hypothetical_rejection_rate": ratio(
            totals["hypothetical_rejections"],
            totals["hypothetical_cases"],
        ),
        "acknowledgement_only_rejection_rate": ratio(
            totals["acknowledgement_only_rejections"],
            totals["acknowledgement_only_cases"],
        ),
        "temporary_local_decision_rejection_rate": ratio(
            totals["temporary_local_decision_rejections"],
            totals["temporary_local_decision_cases"],
        ),
        "generic_rule_rejection_rate": ratio(
            totals["generic_rule_rejections"],
            totals["generic_rule_cases"],
        ),
        "process_noise_rejection_rate": ratio(totals["noise_hits"], totals["noise_cases"]),
        "layer_assignment_accuracy": ratio(totals["layer_hits"], totals["layer_cases"]),
        "evidence_retention_rate": ratio(totals["evidence_hits"], totals["evidence_cases"]),
        "source_ref_policy_pass_rate": ratio(totals["source_ref_hits"], totals["source_ref_cases"]),
        "lifecycle_link_accuracy": ratio(totals["lifecycle_hits"], totals["lifecycle_cases"]),
        "forced_memory_capture_rate": ratio(totals["forced_hits"], totals["forced_cases"]),
        "privacy_refusal_pass_rate": ratio(totals["refusal_hits"], totals["refusal_cases"]),
        "privacy_redaction_pass_rate": ratio(totals["redaction_hits"], totals["redaction_cases"]),
        "privacy_leak_count": int(totals["privacy_leak_count"]),
        "failed_case_count": int(totals["failed_case_count"]),
        "case_pass_rate": ratio(len(cases) - totals["failed_case_count"], len(cases)),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Synthetic updater-induction benchmark JSONL")
    parser.add_argument("--work-dir", help="Empty directory for temporary synthetic archives")
    parser.add_argument("--setup-script", default=str(DEFAULT_SETUP_SCRIPT), help="Archive setup script to run")
    parser.add_argument("--fail-under", action="append", default=[], help="Require metric >= value")
    parser.add_argument("--fail-over", action="append", default=[], help="Require metric <= value")
    parser.add_argument("--fail-under-file", help="JSON object of lower-bound metric thresholds")
    parser.add_argument("--fail-over-file", help="JSON object of upper-bound metric thresholds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases_path = Path(args.cases).expanduser().resolve()
    setup_script = Path(args.setup_script).expanduser().resolve()
    if not setup_script.is_file():
        raise SystemExit("setup script not found")
    cases = list(iter_jsonl(cases_path))
    validate_cases(cases)
    run_root, temp_handle = prepare_work_dir(args.work_dir)
    try:
        scores = [score_case(case, run_root, setup_script) for case in cases]
        report = build_report(cases, scores, cases_fingerprint(cases_path))
        fail_under = {
            **load_threshold_file(args.fail_under_file),
            **parse_thresholds(args.fail_under),
        }
        fail_over = {
            **load_threshold_file(args.fail_over_file),
            **parse_thresholds(args.fail_over),
        }
        failures = apply_quality_gates(report, fail_under, fail_over)
        if failures:
            for failure in failures:
                print(failure, file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        if temp_handle is not None:
            temp_handle.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
