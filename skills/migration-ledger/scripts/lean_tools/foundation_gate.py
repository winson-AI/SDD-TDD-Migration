#!/usr/bin/env python3
"""Resolve and verify HarmonyOS KMP foundation dependencies before implementation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import os
try:
    import tomllib
except ImportError:
    tomllib = None
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent / "knowledge"
KMP_SKILLS_ROOT = SKILL_ROOT.resolve()
KNOWLEDGE_INDEX = SKILL_ROOT / "references/knowledge-index.json"
OHOS_MARKERS = (
    "ohosArm64(",
    "ohosX64(",
    "ohosMain",
    "harmonyApp",
    "BinariesToHarmonyApp",
)


class FoundationError(ValueError):
    pass


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FoundationError(f"JSON root must be an object: {path}")
    return value


def _foundation_catalog() -> tuple[Path, list[dict[str, Any]]]:
    index = _read_object(KNOWLEDGE_INDEX)
    raw = index.get("foundation_catalog")
    if not isinstance(raw, str) or not raw.strip():
        raise FoundationError("knowledge index has no foundation_catalog")
    path = (SKILL_ROOT / raw).resolve()
    try:
        path.relative_to(KMP_SKILLS_ROOT)
    except ValueError as exc:
        raise FoundationError("foundation catalog escapes Android-to-KMP Skills root") from exc
    catalog = _read_object(path)
    entries = catalog.get("entries")
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise FoundationError("foundation catalog entries must be an array of objects")
    return path, entries


def _target_has_ohos(target_root: Path) -> bool:
    ignored = {"build", ".gradle", ".git", ".sdd-migration", ".sdd-runs", "openspec"}
    for directory, dirs, files in os.walk(target_root, followlinks=False):
        base = Path(directory)
        dirs[:] = [d for d in dirs if d not in ignored and not (base / d).is_symlink()]
        if "harmonyApp" in dirs or "ohosMain" in dirs:
            return True
        for name in files:
            path = base / name
            if path.is_symlink() or not name.endswith((".gradle.kts", ".gradle")):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(marker in text for marker in OHOS_MARKERS):
                return True
    return False


def _inside(root: Path, raw: Path, label: str) -> Path:
    resolved = raw.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise FoundationError(f"{label} must stay inside target root: {raw}") from exc
    return resolved


def _exact_requirement(entries: list[dict[str, Any]], query: str) -> dict[str, Any]:
    needle = query.casefold().strip()
    exact = [
        item
        for item in entries
        if any(
            isinstance(item.get(key), str) and item[key].casefold() == needle
            for key in ("capability", "coordinate", "gav")
        )
    ]
    if len(exact) == 1:
        return exact[0]
    fuzzy = [
        item
        for item in entries
        if needle
        and needle
        in " ".join(
            str(item.get(key) or "").casefold()
            for key in ("capability", "coordinate", "gav")
        )
    ]
    if len(fuzzy) != 1:
        choices = sorted(
            str(item.get("capability") or item.get("coordinate")) for item in fuzzy[:10]
        )
        raise FoundationError(
            f"requirement {query!r} must resolve to exactly one foundation entry; "
            f"matches={choices}"
        )
    return fuzzy[0]


def _compact(entry: dict[str, Any], query: str) -> dict[str, Any]:
    support = entry.get("target_support")
    if entry.get("status") != "available":
        raise FoundationError(f"foundation requirement is not available: {query}")
    if not isinstance(support, dict) or support.get("ohosArm64") is not True:
        raise FoundationError(f"foundation requirement lacks ohosArm64 support: {query}")
    return {
        "query": query,
        "capability": entry.get("capability"),
        "coordinate": entry.get("coordinate"),
        "version": entry.get("version"),
        "gav": entry.get("gav"),
        "target_support": support,
        "status": entry.get("status"),
        "cookbook": entry.get("cookbook"),
        "evidence_file": entry.get("evidence_file"),
        "evidence_level": entry.get("evidence_level"),
    }


def resolve(target_root: Path, requirements: list[str], no_new_dependencies: bool) -> dict[str, Any]:
    if bool(requirements) == no_new_dependencies:
        raise FoundationError("use either --require or --no-new-dependencies")
    target_root = target_root.expanduser().resolve()
    if not target_root.is_dir():
        raise FoundationError(f"target root is not a directory: {target_root}")
    has_ohos = _target_has_ohos(target_root)
    catalog_path, entries = _foundation_catalog()
    resolved: list[dict[str, Any]] = []
    if has_ohos and not no_new_dependencies:
        resolved = [_compact(_exact_requirement(entries, query), query) for query in requirements]
    document = {
        "schema_version": 1,
        "target_root": str(target_root),
        "target_matrix": {
            "harmony": has_ohos,
            "required_target": "ohosArm64" if has_ohos else None,
        },
        "catalog": str(catalog_path),
        "status": (
            "passed"
            if has_ohos and resolved
            else "not_required_no_new_dependencies"
            if has_ohos
            else "not_required_non_harmony_target"
        ),
        "requirements": resolved,
    }
    return document


def _module_and_version(alias: str, item: Any, versions: dict[str, Any]) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    module = item.get("module")
    if not isinstance(module, str):
        group, name = item.get("group"), item.get("name")
        module = f"{group}:{name}" if isinstance(group, str) and isinstance(name, str) else None
    if not module:
        return None
    raw_version = item.get("version")
    if isinstance(raw_version, str):
        version = raw_version
    elif isinstance(raw_version, dict) and isinstance(raw_version.get("ref"), str):
        version = versions.get(raw_version["ref"])
    elif isinstance(item.get("version.ref"), str):
        version = versions.get(item["version.ref"])
    else:
        version = None
    if not isinstance(version, str):
        raise FoundationError(f"cannot resolve version for catalog alias {alias}")
    return module, version


def verify(target_root: Path, resolution: Path, catalog: Path) -> dict[str, Any]:
    target_root = target_root.expanduser().resolve()
    catalog = _inside(target_root, catalog, "version catalog")
    document = _read_object(resolution)
    if document.get("target_root") != str(target_root):
        raise FoundationError("resolution belongs to another target")
    if tomllib is None:
        raise FoundationError("foundation-verify requires Python 3.11+ for TOML parsing")
    requirements = document.get("requirements")
    if document.get("status") != "passed" or not isinstance(requirements, list) or not requirements:
        raise FoundationError("resolution has no selected foundation requirements to verify")
    try:
        parsed = tomllib.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise FoundationError(f"cannot parse version catalog {catalog}: {exc}") from exc
    versions = parsed.get("versions")
    libraries = parsed.get("libraries")
    if not isinstance(versions, dict) or not isinstance(libraries, dict):
        raise FoundationError("version catalog must contain [versions] and [libraries]")
    wanted = set()
    for item in requirements:
        if not isinstance(item, dict) or not isinstance(item.get("coordinate"), str) or not isinstance(item.get("version"), str):
            raise FoundationError("resolution requirement lacks coordinate/version")
        wanted.add(item["coordinate"])
    selected: dict[str, str] = {}
    for alias, item in libraries.items():
        if not isinstance(item, dict):
            continue
        coordinate = item.get("module") or f"{item.get('group')}:{item.get('name')}"
        if coordinate not in wanted:
            continue
        value = _module_and_version(alias, item, versions)
        if value:
            if value[0] in selected and selected[value[0]] != value[1]:
                raise FoundationError(f"conflicting versions for {value[0]}")
            selected[value[0]] = value[1]
    errors: list[str] = []
    for item in requirements:
        if not isinstance(item, dict):
            raise FoundationError("resolution requirements must be objects")
        coordinate, version = item.get("coordinate"), item.get("version")
        if not isinstance(coordinate, str) or not isinstance(version, str):
            raise FoundationError("resolution requirement lacks coordinate/version")
        actual = selected.get(coordinate)
        if actual != version:
            errors.append(f"{coordinate}: expected {version}, catalog has {actual!r}")
    if errors:
        raise FoundationError("foundation version verification failed: " + "; ".join(errors))
    return {"schema_version": 1, "status": "foundation-verified",
            "target_root": str(target_root), "requirements": requirements,
            "selected_versions": {item["coordinate"]: selected[item["coordinate"]] for item in requirements}}


if __name__ == "__main__":
    raise SystemExit("Use lean_worker.py; standalone output is disabled.")
