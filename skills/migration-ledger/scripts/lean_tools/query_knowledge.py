#!/usr/bin/env python3
"""Query only the KMP migration knowledge needed for an active Lean slice."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent / "knowledge"
ANDROID_TO_KMP_ROOT = SKILL_ROOT.resolve()
INDEX_PATH = SKILL_ROOT / "references/knowledge-index.json"


class KnowledgeError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgeError(f"JSON root must be an object: {path}")
    return value


def _resolve_catalog_path(index: dict[str, Any], key: str) -> Path:
    raw = index.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise KnowledgeError(f"knowledge index is missing {key}")
    path = (SKILL_ROOT / raw).resolve()
    try:
        path.relative_to(ANDROID_TO_KMP_ROOT)
    except ValueError as exc:
        raise KnowledgeError(f"knowledge path escapes Android-to-KMP Skills root: {raw}") from exc
    if not path.exists():
        raise KnowledgeError(f"knowledge path does not exist: {path}")
    return path


def _entries(index: dict[str, Any]) -> list[dict[str, Any]]:
    entries = index.get("entries")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise KnowledgeError("knowledge index entries must be an array of objects")
    return entries


def _topic(index: dict[str, Any], topic_id: str) -> dict[str, Any]:
    matches = [item for item in _entries(index) if item.get("id") == topic_id]
    if len(matches) != 1:
        raise KnowledgeError(f"unknown or duplicate topic id: {topic_id}")
    return matches[0]


def _show_topic(index: dict[str, Any], topic_id: str) -> None:
    topic = _topic(index, topic_id)
    raw = topic.get("path")
    if not isinstance(raw, str):
        raise KnowledgeError(f"topic {topic_id} has no path")
    path = _resolve_relative(raw)
    print(f"TOPIC: {topic_id}")
    print(f"SOURCE: {path}")
    print(path.read_text(encoding="utf-8"))


def _resolve_relative(raw: str) -> Path:
    path = (SKILL_ROOT / raw).resolve()
    try:
        path.relative_to(ANDROID_TO_KMP_ROOT)
    except ValueError as exc:
        raise KnowledgeError(f"knowledge path escapes Android-to-KMP Skills root: {raw}") from exc
    if not path.is_file():
        raise KnowledgeError(f"knowledge file does not exist: {path}")
    return path


def _search_blob(value: Any, needle: str) -> bool:
    return needle in json.dumps(value, ensure_ascii=False).casefold()


def _compact_foundation_entry(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    return {
        key: entry.get(key)
        for key in (
            "capability",
            "coordinate",
            "version",
            "gav",
            "target_support",
            "cookbook",
            "evidence_file",
            "evidence_level",
            "status",
        )
    }


def _foundation(index: dict[str, Any], query: str, *, full: bool) -> None:
    catalog_path = _resolve_catalog_path(index, "foundation_catalog")
    catalog = _load_json(catalog_path)
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise KnowledgeError("foundation catalog entries must be an array")
    needle = query.casefold().strip()
    full_matches = [entry for entry in entries if _search_blob(entry, needle)]
    matches = full_matches if full else [_compact_foundation_entry(entry) for entry in full_matches]
    result: dict[str, Any] = {
        "query": query,
        "catalog": str(catalog_path),
        "matches": matches,
    }
    cookbook_root = _resolve_catalog_path(index, "foundation_cookbook_root")
    cookbooks: list[str] = []
    for entry in full_matches:
        cookbook = entry.get("cookbook") if isinstance(entry, dict) else None
        if isinstance(cookbook, str) and cookbook.strip():
            path = (cookbook_root / cookbook).resolve()
            if not path.is_relative_to(cookbook_root):
                raise KnowledgeError("foundation cookbook escapes root")
            if not path.is_file():
                raise KnowledgeError(f"foundation cookbook missing: {path}")
            if str(path) not in cookbooks:
                cookbooks.append(str(path))
    result["matching_cookbooks"] = cookbooks
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _diagnose(index: dict[str, Any], error_text: str) -> None:
    diagnostics_path = _resolve_catalog_path(index, "foundation_runtime_diagnostics")
    diagnostics = _load_json(diagnostics_path)
    entries = diagnostics.get("entries")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise KnowledgeError("runtime diagnostics entries must be an array of objects")

    needle = error_text.casefold().strip()
    if not needle:
        raise KnowledgeError("diagnostic error text must not be empty")
    cookbook_root = _resolve_catalog_path(index, "foundation_cookbook_root")
    matches: list[dict[str, Any]] = []
    for entry in entries:
        patterns = entry.get("patterns")
        if not isinstance(patterns, list) or any(not isinstance(item, str) for item in patterns):
            raise KnowledgeError("runtime diagnostic patterns must be an array of strings")
        matched_patterns = [pattern for pattern in patterns if pattern.casefold() in needle]
        if not matched_patterns:
            continue

        item = dict(entry)
        item["matched_patterns"] = matched_patterns
        cookbook_paths: list[str] = []
        for raw in item.get("cookbooks") or []:
            if not isinstance(raw, str):
                raise KnowledgeError("runtime diagnostic cookbooks must be strings")
            path = (cookbook_root / raw).resolve()
            try:
                path.relative_to(cookbook_root)
            except ValueError as exc:
                raise KnowledgeError(f"runtime diagnostic cookbook escapes root: {raw}") from exc
            if not path.is_file():
                raise KnowledgeError(f"runtime diagnostic cookbook does not exist: {path}")
            cookbook_paths.append(str(path))
        item["cookbook_paths"] = cookbook_paths

        topic_paths: list[str] = []
        for topic_id in item.get("topics") or []:
            if not isinstance(topic_id, str):
                raise KnowledgeError("runtime diagnostic topics must be strings")
            topic = _topic(index, topic_id)
            raw = topic.get("path")
            if not isinstance(raw, str):
                raise KnowledgeError(f"topic {topic_id} has no path")
            topic_paths.append(str(_resolve_relative(raw)))
        item["topic_paths"] = topic_paths
        matches.append(item)

    print(
        json.dumps(
            {
                "query": error_text,
                "catalog": str(diagnostics_path),
                "matches": matches,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _external(index: dict[str, Any], query: str) -> None:
    """Discover bundled host/native candidates without executing probes or installers."""
    catalog_path = _resolve_catalog_path(index, "external_capability_catalog")
    root = _resolve_catalog_path(index, "external_capability_root")
    entries = _load_json(catalog_path).get("entries")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise KnowledgeError("external capability catalog entries must be an array of objects")
    needle = query.casefold().strip()
    if not needle:
        raise KnowledgeError("external capability query must not be empty")
    matches = []
    for entry in entries:
        if not _search_blob(entry, needle):
            continue
        item = dict(entry)
        for key in ("record", "cookbook"):
            raw = item.get(key)
            if not isinstance(raw, str) or not raw.strip():
                raise KnowledgeError("external capability requires " + key)
            path = (root / raw).resolve()
            if not path.is_relative_to(root):
                raise KnowledgeError("external capability " + key + " escapes root")
            if not path.is_file():
                raise KnowledgeError("external capability " + key + " missing: " + str(path))
            item[key + "_path"] = str(path)
        record = _load_json(Path(item["record_path"]))
        if record.get("id") != item.get("id"):
            raise KnowledgeError("external capability record id mismatch")
        if record.get("cookbook") != item.get("cookbook"):
            raise KnowledgeError("external capability record cookbook mismatch")
        for descriptor in (item, record):
            support = descriptor.get("probe_support")
            if (descriptor.get("probe") is not None or not isinstance(support, dict)
                    or support.get("status") != "not-supported" or not support.get("reason")):
                raise KnowledgeError("external capability probes are not supported by this read-only adapter")
        item["execution"] = "not-executed; target build/package/runtime checks remain required"
        matches.append(item)
    print(json.dumps({"query": query, "catalog": str(catalog_path), "matches": matches},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit("Use lean_worker.py; standalone output is disabled.")
