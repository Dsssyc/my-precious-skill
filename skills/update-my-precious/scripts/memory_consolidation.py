"""Semantic consolidation and lifecycle helpers for layered memory nodes."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable


MEMORY_REFRESH_PATTERN = re.compile(
    r"(?i)^\s*(?:updated|refresh(?:ed)?|replacement|replace(?:d)?|superseding)\s+fact\s*[:\uFF1A]\s*"
    r"(?P<old>.+?)\s*(?:=>|->|\u2192)\s*(?P<new>.+)$"
)
MEMORY_DEPRECATION_PATTERN = re.compile(
    r"(?i)^\s*(?:deprecat(?:e|ed|ing)|delete(?:d)?|remove(?:d)?|retire(?:d)?)\s+fact\s*[:\uFF1A]\s*"
    r"(?P<old>.+)$"
)

TOKEN_SYNONYMS = {
    "anchors": "anchor",
    "evidences": "evidence",
    "keeps": "preserve",
    "kept": "preserve",
    "keeping": "preserve",
    "memories": "memory",
    "preserved": "preserve",
    "preserves": "preserve",
    "references": "ref",
    "reference": "ref",
    "refs": "ref",
    "retain": "preserve",
    "retained": "preserve",
    "retains": "preserve",
    "retaining": "preserve",
    "retrieving": "retrieval",
    "retrieve": "retrieval",
    "retrieved": "retrieval",
    "sources": "source",
}
SEMANTIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "can",
    "during",
    "for",
    "from",
    "in",
    "is",
    "it",
    "its",
    "may",
    "must",
    "of",
    "on",
    "or",
    "should",
    "that",
    "the",
    "their",
    "to",
    "when",
    "with",
}
NEGATIVE_CUES = {
    "avoid",
    "exclude",
    "excludes",
    "excluded",
    "excluding",
    "never",
    "no",
    "not",
    "omit",
    "omits",
    "omitted",
    "omitting",
    "skip",
    "skips",
    "skipped",
    "without",
}
POSITIVE_CUES = {
    "include",
    "includes",
    "included",
    "keep",
    "keeps",
    "preserve",
    "preserves",
    "retain",
    "retains",
}
PARTIAL_SUPERSESSION_DETAIL_TOKENS = {
    "anchor",
    "raw",
    "source",
}
MISSING = object()


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_memory_text(text: str) -> str:
    return compact_whitespace(text).strip(" -")


def memory_text_key(text: object) -> str:
    return normalize_memory_text(str(text)).lower()


def parse_memory_refresh_text(
    text: str,
    reject_text: Callable[[str], bool] | None = None,
) -> tuple[str, tuple[str, ...]]:
    match = MEMORY_REFRESH_PATTERN.match(text)
    if not match:
        return text, ()
    old_text = normalize_memory_text(match.group("old"))
    new_text = normalize_memory_text(match.group("new"))
    if not old_text or not new_text or old_text.lower() == new_text.lower():
        return text, ()
    if reject_text and (reject_text(old_text) or reject_text(new_text)):
        return text, ()
    return new_text, (old_text,)


def parse_memory_deprecation_text(
    text: str,
    reject_text: Callable[[str], bool] | None = None,
) -> tuple[str, tuple[str, ...]]:
    match = MEMORY_DEPRECATION_PATTERN.match(text)
    if not match:
        return text, ()
    old_text = normalize_memory_text(match.group("old"))
    if not old_text:
        return text, ()
    if reject_text and reject_text(old_text):
        return text, ()
    return f"Deprecated fact: {old_text}", (old_text,)


def semantic_tokens(text: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        canonical = TOKEN_SYNONYMS.get(token, token)
        if canonical in NEGATIVE_CUES or canonical in SEMANTIC_STOPWORDS:
            continue
        if canonical.endswith("ies") and len(canonical) > 4:
            canonical = f"{canonical[:-3]}y"
        elif canonical.endswith("s") and len(canonical) > 4:
            canonical = canonical[:-1]
        if len(canonical) < 3 or canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return tuple(out)


def semantic_polarity(text: str) -> int:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    token_set = set(tokens)
    if token_set.intersection(NEGATIVE_CUES):
        return -1
    if any(TOKEN_SYNONYMS.get(token, token) in POSITIVE_CUES for token in tokens):
        return 1
    return 0


def memory_consolidation_key(text: str) -> str:
    tokens = semantic_tokens(text)
    if len(tokens) < 4:
        return f"literal:{memory_text_key(text)}"
    return "semantic:{}:{}".format(semantic_polarity(text), " ".join(sorted(tokens)))


def semantic_relation(current_text: str, old_text: str) -> str:
    return str(semantic_relation_detail(current_text, old_text).get("relation") or "")


def semantic_relation_detail(current_text: str, old_text: str) -> dict:
    current_tokens = set(semantic_tokens(current_text))
    old_tokens = set(semantic_tokens(old_text))
    if len(current_tokens) < 4 or len(old_tokens) < 4:
        return {
            "relation": "",
            "review_reason": "",
            "overlap_token_count": 0,
            "overlap_ratio": 0.0,
        }
    overlap = current_tokens & old_tokens
    if len(overlap) < 4:
        return {
            "relation": "",
            "review_reason": "",
            "overlap_token_count": len(overlap),
            "overlap_ratio": len(overlap) / max(1, len(current_tokens | old_tokens)),
        }
    union = current_tokens | old_tokens
    overlap_ratio = len(overlap) / max(1, len(union))
    current_polarity = semantic_polarity(current_text)
    old_polarity = semantic_polarity(old_text)
    if current_polarity and old_polarity and current_polarity != old_polarity and overlap_ratio >= 0.6:
        return {
            "relation": "contradiction",
            "review_reason": "",
            "overlap_token_count": len(overlap),
            "overlap_ratio": overlap_ratio,
        }
    if current_polarity and old_polarity and current_polarity != old_polarity and overlap_ratio >= 0.45:
        return {
            "relation": "",
            "review_reason": "low_confidence_contradiction_requires_review",
            "overlap_token_count": len(overlap),
            "overlap_ratio": overlap_ratio,
        }
    removed_tokens = old_tokens - current_tokens
    if current_tokens < old_tokens and removed_tokens.issubset(PARTIAL_SUPERSESSION_DETAIL_TOKENS):
        return {
            "relation": "partial_supersession",
            "review_reason": "",
            "overlap_token_count": len(overlap),
            "overlap_ratio": overlap_ratio,
        }
    if current_tokens < old_tokens:
        return {
            "relation": "",
            "review_reason": "ambiguous_scope_narrowing_requires_review",
            "overlap_token_count": len(overlap),
            "overlap_ratio": overlap_ratio,
        }
    if overlap_ratio >= 0.45:
        return {
            "relation": "",
            "review_reason": "low_confidence_semantic_overlap_requires_review",
            "overlap_token_count": len(overlap),
            "overlap_ratio": overlap_ratio,
        }
    return {
        "relation": "",
        "review_reason": "",
        "overlap_token_count": len(overlap),
        "overlap_ratio": overlap_ratio,
    }


def unique_strings(*values: object) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out


def unique_dicts(key_fields: tuple[str, ...], *values: object) -> list[dict]:
    seen: set[tuple[str, ...]] = set()
    out: list[dict] = []
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            key = tuple(str(item.get(field, "")).strip() for field in key_fields)
            if not all(key) or key in seen:
                continue
            seen.add(key)
            out.append({field: key[idx] for idx, field in enumerate(key_fields)})
    return out


def sorted_memory_times(*values: object) -> list[str]:
    times = [str(value).strip() for value in values if isinstance(value, str) and value.strip()]
    return sorted(set(times))


def positive_int_value(value: object) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def set_optional_string_list(node: dict, field: str, values: list[str]) -> None:
    if values:
        node[field] = values
    else:
        node.pop(field, None)


def merge_memory_node_provenance(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    merged.update(incoming)
    derived_from = unique_strings(existing.get("derived_from"), incoming.get("derived_from"))
    evidence_refs = unique_dicts(("path", "quote_id"), existing.get("evidence_refs"), incoming.get("evidence_refs"))
    raw_refs = unique_dicts(("path", "anchor"), existing.get("raw_refs"), incoming.get("raw_refs"))
    supersedes = unique_strings(existing.get("supersedes"), incoming.get("supersedes"))
    contradicts = unique_strings(existing.get("contradicts"), incoming.get("contradicts"))
    contradicted_by = unique_strings(existing.get("contradicted_by"), incoming.get("contradicted_by"))
    deprecates = unique_strings(existing.get("deprecates"), incoming.get("deprecates"))
    tags = sorted(set(unique_strings(existing.get("tags"), incoming.get("tags"))))
    seen_times = sorted_memory_times(
        existing.get("first_seen"),
        incoming.get("first_seen"),
        existing.get("last_seen"),
        incoming.get("last_seen"),
    )
    merged["derived_from"] = derived_from
    merged["evidence_refs"] = evidence_refs
    merged["raw_refs"] = raw_refs
    merged["supersedes"] = supersedes
    set_optional_string_list(merged, "contradicts", contradicts)
    set_optional_string_list(merged, "contradicted_by", contradicted_by)
    set_optional_string_list(merged, "deprecates", deprecates)
    merged["tags"] = tags
    if seen_times:
        merged["first_seen"] = seen_times[0]
        merged["last_seen"] = seen_times[-1]
    merged["support_count"] = max(
        1,
        len(derived_from),
        len(evidence_refs),
        positive_int_value(existing.get("support_count")),
        positive_int_value(incoming.get("support_count")),
    )
    if merged.get("source") == "automatic" and merged["support_count"] >= 2:
        merged["confidence"] = "high"
    if incoming.get("superseded_by") is None and existing.get("superseded_by") is not None:
        merged["superseded_by"] = existing.get("superseded_by")
    if incoming.get("deprecated_by") is None and existing.get("deprecated_by") is not None:
        merged["deprecated_by"] = existing.get("deprecated_by")
    return merged


def merge_support_into_memory_node(node: dict, support: dict) -> None:
    original_superseded_by = node.get("superseded_by")
    original_contradicted_by = node.get("contradicted_by", MISSING)
    original_deprecated_by = node.get("deprecated_by", MISSING)
    merged = merge_memory_node_provenance(support, node)
    node.update(merged)
    node["superseded_by"] = original_superseded_by
    if original_contradicted_by is MISSING:
        node.pop("contradicted_by", None)
    else:
        node["contradicted_by"] = original_contradicted_by
    if original_deprecated_by is MISSING:
        node.pop("deprecated_by", None)
    else:
        node["deprecated_by"] = original_deprecated_by


def add_supersession_link(current: dict, old: dict) -> None:
    current_id = current.get("memory_id")
    old_id = old.get("memory_id")
    if not isinstance(current_id, str) or not isinstance(old_id, str) or current_id == old_id:
        return
    current["supersedes"] = unique_strings(current.get("supersedes"), [old_id])
    old["superseded_by"] = current_id
    old["confidence"] = "low"
    merge_support_into_memory_node(current, old)


def add_contradiction_link(current: dict, old: dict) -> None:
    current_id = current.get("memory_id")
    old_id = old.get("memory_id")
    if not isinstance(current_id, str) or not isinstance(old_id, str) or current_id == old_id:
        return
    current["contradicts"] = unique_strings(current.get("contradicts"), [old_id])
    old["contradicted_by"] = unique_strings(old.get("contradicted_by"), [current_id])
    old["confidence"] = "low"
    merge_support_into_memory_node(current, old)


def add_deprecation_link(current: dict, old: dict) -> None:
    current_id = current.get("memory_id")
    old_id = old.get("memory_id")
    if not isinstance(current_id, str) or not isinstance(old_id, str) or current_id == old_id:
        return
    current["deprecates"] = unique_strings(current.get("deprecates"), [old_id])
    old["deprecated_by"] = current_id
    old["confidence"] = "low"
    merge_support_into_memory_node(current, old)


def apply_memory_id_supersession_links(nodes: list[dict]) -> None:
    by_id = {
        memory_id: node
        for node in nodes
        if isinstance((memory_id := node.get("memory_id")), str) and memory_id
    }
    for node in nodes:
        supersedes = node.get("supersedes", [])
        if not isinstance(supersedes, list):
            continue
        for target_id in list(supersedes):
            if not isinstance(target_id, str):
                continue
            target = by_id.get(target_id)
            if target is not None:
                add_supersession_link(node, target)


def apply_memory_id_contradiction_links(nodes: list[dict]) -> None:
    by_id = {
        memory_id: node
        for node in nodes
        if isinstance((memory_id := node.get("memory_id")), str) and memory_id
    }
    for node in nodes:
        contradicts = node.get("contradicts", [])
        if not isinstance(contradicts, list):
            continue
        for target_id in list(contradicts):
            if not isinstance(target_id, str):
                continue
            target = by_id.get(target_id)
            if target is not None:
                add_contradiction_link(node, target)


def apply_memory_id_deprecation_links(nodes: list[dict]) -> None:
    by_id = {
        memory_id: node
        for node in nodes
        if isinstance((memory_id := node.get("memory_id")), str) and memory_id
    }
    for node in nodes:
        deprecates = node.get("deprecates", [])
        if not isinstance(deprecates, list):
            continue
        for target_id in list(deprecates):
            if not isinstance(target_id, str):
                continue
            target = by_id.get(target_id)
            if target is not None:
                add_deprecation_link(node, target)


def apply_text_supersession_links(nodes: list[dict], refresh_targets_by_text: dict[str, set[str]]) -> None:
    nodes_by_text: dict[str, list[dict]] = {}
    for node in nodes:
        key = memory_text_key(node.get("text", ""))
        if key:
            nodes_by_text.setdefault(key, []).append(node)
    for current_text_key, target_texts in refresh_targets_by_text.items():
        current_nodes = nodes_by_text.get(current_text_key, [])
        if not current_nodes:
            continue
        for target_text in sorted(target_texts):
            target_text_key = memory_text_key(target_text)
            if target_text_key == current_text_key:
                continue
            for current in current_nodes:
                for old in nodes_by_text.get(target_text_key, []):
                    add_supersession_link(current, old)


def apply_text_deprecation_links(nodes: list[dict], deprecation_targets_by_text: dict[str, set[str]]) -> None:
    nodes_by_text: dict[str, list[dict]] = {}
    for node in nodes:
        key = memory_text_key(node.get("text", ""))
        if key:
            nodes_by_text.setdefault(key, []).append(node)
    for current_text_key, target_texts in deprecation_targets_by_text.items():
        current_nodes = nodes_by_text.get(current_text_key, [])
        if not current_nodes:
            continue
        for target_text in sorted(target_texts):
            target_text_key = memory_text_key(target_text)
            if target_text_key == current_text_key:
                continue
            for current in current_nodes:
                for old in nodes_by_text.get(target_text_key, []):
                    add_deprecation_link(current, old)


def node_last_seen_key(node: dict) -> tuple[str, str]:
    return str(node.get("last_seen") or ""), str(node.get("memory_id") or "")


def apply_semantic_lifecycle_links(nodes: list[dict]) -> None:
    automatic_nodes = [node for node in nodes if node.get("source") == "automatic"]
    for current in sorted(automatic_nodes, key=node_last_seen_key):
        for old in automatic_nodes:
            if current is old:
                continue
            if node_last_seen_key(current) <= node_last_seen_key(old):
                continue
            relation = semantic_relation(str(current.get("text", "")), str(old.get("text", "")))
            if relation == "contradiction":
                add_contradiction_link(current, old)
            elif relation == "partial_supersession":
                add_supersession_link(current, old)
