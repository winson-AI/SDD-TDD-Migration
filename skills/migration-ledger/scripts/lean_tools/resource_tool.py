#!/usr/bin/env python3
"""Deterministic helpers for current-slice Android-to-CMP resource migration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import xml.etree.ElementTree as ET


ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID = f"{{{ANDROID_NS}}}"
ALLOWED_VECTOR_TAGS = {"vector", "path", "group", "clip-path"}
ALLOWED_STRATEGIES = {
    "exact_vector_xml",
    "byte_copy",
    "value_xml_exact",
    "design_token_exact",
    "compose_semantic_exact",
    "manual_exact",
    "blocked",
}
REFERENCE_RE = re.compile(r"^(?:@|\?).+")
VALUE_XML_KINDS = {"string", "plurals", "array"}
DESIGN_TOKEN_KINDS = {"color", "dimen", "attr"}


class ResourceError(RuntimeError):
    pass


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResourceError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResourceError(f"{label} must be a JSON object")
    return value


def require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResourceError(f"{label} must be non-empty text")
    return value.strip()


def inside_file(root: Path, raw: str, label: str, must_exist: bool = True) -> Path:
    candidate = Path(raw).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise ResourceError(f"{label} must resolve inside {root}: {path}")
    if must_exist and not path.is_file():
        raise ResourceError(f"{label} does not exist: {path}")
    return path


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def resource_kind(source_id: str) -> str | None:
    match = re.match(r"^@(?:android:)?([^/]+)/[^/]+$", source_id)
    if match:
        return match.group(1)
    if source_id.startswith("?attr/") or source_id.startswith("?android:attr/"):
        return "attr"
    return None


def validate_mapping_strategy(
    source_id: str, source_path: str, strategy: str, label: str
) -> None:
    kind = resource_kind(source_id)
    if kind in VALUE_XML_KINDS and strategy not in {
        "value_xml_exact",
        "manual_exact",
        "blocked",
    }:
        raise ResourceError(
            f"{label}.strategy for {source_id} must be value_xml_exact, manual_exact or blocked"
        )
    if strategy == "value_xml_exact" and kind not in VALUE_XML_KINDS:
        raise ResourceError(
            f"{label}.strategy value_xml_exact is valid only for string/plurals/array"
        )
    if kind in DESIGN_TOKEN_KINDS and strategy == "byte_copy":
        raise ResourceError(
            f"{label}.strategy for {source_id} must not be byte_copy; use design_token_exact or an exact semantic/manual strategy"
        )
    if strategy == "design_token_exact" and kind not in DESIGN_TOKEN_KINDS:
        raise ResourceError(
            f"{label}.strategy design_token_exact is valid only for color/dimen/attr"
        )
    if strategy == "byte_copy":
        normalized = source_path.lower()
        if normalized.endswith(".9.png"):
            raise ResourceError(
                f"{label}.strategy byte_copy cannot preserve Android nine-patch semantics"
            )
        if kind not in {"drawable", "mipmap", "font", "raw"}:
            raise ResourceError(
                f"{label}.strategy byte_copy is valid only for unchanged drawable/mipmap/font/raw files"
            )
        if kind in {"drawable", "mipmap"} and not normalized.endswith(
            (".png", ".webp", ".jpg", ".jpeg", ".gif", ".avif")
        ):
            raise ResourceError(
                f"{label}.strategy byte_copy requires an unchanged ordinary raster file"
            )


def parse_assignments(values: list[str]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ResourceError(f"reference assignment must use REF=VALUE: {value!r}")
        key, replacement = value.split("=", 1)
        if not key.strip() or not replacement.strip():
            raise ResourceError(f"reference assignment must use REF=VALUE: {value!r}")
        assignments[key.strip()] = replacement.strip()
    return assignments


def serialize_vector(root: ET.Element) -> bytes:
    ET.register_namespace("android", ANDROID_NS)
    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def prepare_vector(args: argparse.Namespace) -> dict[str, Any]:
    android_root = Path(args.android_root).expanduser().resolve()
    target_root = Path(args.target_root).expanduser().resolve()
    source = inside_file(android_root, args.source, "source vector")
    destination = inside_file(target_root, args.destination, "destination", must_exist=False)
    try:
        tree = ET.parse(source)
    except (OSError, ET.ParseError) as exc:
        raise ResourceError(f"cannot parse VectorDrawable {source}: {exc}") from exc
    vector = tree.getroot()
    if local_name(vector.tag) != "vector":
        raise ResourceError("source root must be <vector>")
    unsupported = sorted(
        {local_name(element.tag) for element in vector.iter()} - ALLOWED_VECTOR_TAGS
    )
    if unsupported:
        raise ResourceError(
            "manual exact adaptation required for unsupported vector tags: "
            + ", ".join(unsupported)
        )

    replacements = parse_assignments(args.resolve_ref)
    source_tint = vector.attrib.pop(ANDROID + "tint", None)
    source_tint_mode = vector.attrib.pop(ANDROID + "tintMode", None)
    consumer_tint = args.consumer_tint
    if source_tint:
        if consumer_tint:
            pass
        elif source_tint in replacements:
            consumer_tint = replacements[source_tint]
        elif REFERENCE_RE.match(source_tint):
            raise ResourceError(
                f"root tint {source_tint!r} requires --consumer-tint or --resolve-ref"
            )
        else:
            consumer_tint = source_tint

    unresolved: list[str] = []
    for element in vector.iter():
        for attribute, value in list(element.attrib.items()):
            if value in replacements:
                element.attrib[attribute] = replacements[value]
            elif REFERENCE_RE.match(value):
                unresolved.append(f"{local_name(element.tag)}@{local_name(attribute)}={value}")
    if unresolved:
        raise ResourceError(
            "manual exact adaptation required for unresolved Android references: "
            + ", ".join(sorted(unresolved))
        )

    payload = serialize_vector(vector)
    action = "created"
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ResourceError(
                f"target resource already exists with different semantics; refusing overwrite: {destination}"
            )
        action = "reused"

    mapping: dict[str, Any] = {
        "sourceId": require_text(args.source_id, "source-id"),
        "sourcePath": source.relative_to(android_root).as_posix(),
        "targetPath": destination.relative_to(target_root).as_posix(),
        "targetRef": require_text(args.target_ref, "target-ref"),
        "consumers": sorted(set(args.consumer)),
        "strategy": "exact_vector_xml",
    }
    if not mapping["consumers"]:
        raise ResourceError("at least one --consumer is required")
    if consumer_tint:
        mapping["consumerTint"] = consumer_tint
    if source_tint_mode:
        mapping["consumerTintMode"] = source_tint_mode
    return {"status": "VECTOR_READY", "action": action, "mapping": mapping, "content": payload.decode("utf-8")}


def collect_resource_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        presentation = value.get("presentation")
        if isinstance(presentation, dict):
            resource_refs = presentation.get("resourceRefs")
            if isinstance(resource_refs, list):
                refs.update(item for item in resource_refs if isinstance(item, str))
        for child in value.values():
            refs.update(collect_resource_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(collect_resource_refs(child))
    return refs


def collect_source_index_refs(value: object) -> set[str]:
    refs: set[str] = set()
    if not isinstance(value, dict):
        return refs
    resources = value.get("resources")
    if isinstance(resources, list):
        refs.update(
            item["ref"]
            for item in resources
            if isinstance(item, dict) and isinstance(item.get("ref"), str)
        )
    for source in value.get("sourceFiles", []):
        if not isinstance(source, dict):
            continue
        for mutation in source.get("presentationMutations", []):
            if not isinstance(mutation, dict):
                continue
            values = mutation.get("resourceRefs", [])
            if isinstance(values, list):
                refs.update(item for item in values if isinstance(item, str))
    return {
        ref
        for ref in refs
        if not ref.startswith(("@layout/", "@id/", "@+id/"))
    }


def source_candidates(android_root: Path, resource_id: str) -> list[str]:
    match = re.match(r"^@(?:android:)?([^/]+)/([^/]+)$", resource_id)
    if not match or resource_id.startswith("@android:"):
        return []
    kind, name = match.groups()
    candidates: list[Path] = []
    if kind in {"drawable", "mipmap", "font", "raw", "color"}:
        candidates.extend(p for p in android_root.glob(f"**/res/{kind}*/{name}.*")
                          if p.is_file() and p.name.split('.')[0] == name)
    if kind not in {"drawable", "mipmap", "font", "raw"}:
        for values_file in android_root.glob("**/res/values*/*.xml"):
            try:
                parsed = ET.parse(values_file).getroot()
            except (OSError, ET.ParseError):
                continue
            if any(
                child.attrib.get("name") == name
                and (local_name(child.tag) == kind or kind == 'array' and local_name(child.tag) in ('string-array', 'integer-array')
                     or local_name(child.tag) == "item" and child.attrib.get('type') == kind)
                for child in parsed
            ):
                candidates.append(values_file)
    return sorted(path.relative_to(android_root).as_posix() for path in set(candidates))


def scan(args: argparse.Namespace) -> dict[str, Any]:
    android_root = Path(args.android_root).expanduser().resolve()
    refs = set(args.extra_ref)
    if args.ui_tree:
        tree_path = Path(args.ui_tree).expanduser().resolve()
        refs.update(collect_resource_refs(load_object(tree_path, "UI tree")))
    if args.source_index:
        index_path = Path(args.source_index).expanduser().resolve()
        refs.update(collect_source_index_refs(load_object(index_path, "UI source index")))
    resources = [
        {"sourceId": ref, "candidates": source_candidates(android_root, ref)}
        for ref in sorted(refs)
    ]
    return {"status": "RESOURCE_SCAN_READY", "resources": resources}


def validate_result(args: argparse.Namespace) -> dict[str, Any]:
    android_root = Path(args.android_root).expanduser().resolve() if args.android_root else None
    target_root = Path(args.target_root).expanduser().resolve()
    result_path = Path(args.result).expanduser().resolve()
    result = load_object(result_path, "resource result")
    if result.get("schemaVersion") != 1:
        raise ResourceError("schemaVersion must equal 1")
    status = result.get("status")
    if status not in {"READY_FOR_LEAN", "BLOCKED"}:
        raise ResourceError("status must be READY_FOR_LEAN or BLOCKED")
    change_id = require_text(result.get("changeId"), "changeId")
    approved_hash = require_text(result.get("approvedSpecHash"), "approvedSpecHash")
    if not re.fullmatch(r"[0-9a-f]{64}", approved_hash):
        raise ResourceError("approvedSpecHash must be lowercase SHA-256")
    if args.approved_spec_hash and approved_hash != args.approved_spec_hash:
        raise ResourceError("resource result does not match the approved OpenSpec hash")

    mappings = result.get("resourceMappings")
    manual_items = result.get("manualItems")
    files_changed = result.get("filesChanged")
    if not isinstance(mappings, list):
        raise ResourceError("resourceMappings must be an array")
    if not isinstance(manual_items, list):
        raise ResourceError("manualItems must be an array")
    if not isinstance(files_changed, list):
        raise ResourceError("filesChanged must be an array")

    seen: set[str] = set()
    blocked = False
    for index, mapping in enumerate(mappings):
        label = f"resourceMappings[{index}]"
        if not isinstance(mapping, dict):
            raise ResourceError(f"{label} must be an object")
        source_id = require_text(mapping.get("sourceId"), f"{label}.sourceId")
        source_path = require_text(mapping.get("sourcePath"), f"{label}.sourcePath")
        inferred = Path(source_path).parent.name.partition('-')[2] or 'base'
        qualifier = mapping.get('qualifier', inferred)
        if qualifier != inferred:
            raise ResourceError(f"{label}.qualifier differs from source configuration")
        key = (source_id, qualifier)
        if key in seen:
            raise ResourceError(f"duplicate resource mapping: {source_id} / {qualifier}")
        seen.add(key)
        consumers = mapping.get("consumers")
        if not isinstance(consumers, list) or not consumers or not all(
            isinstance(item, str) and item.strip() for item in consumers
        ):
            raise ResourceError(f"{label}.consumers must contain non-empty consumer names")
        strategy = mapping.get("strategy")
        if strategy not in ALLOWED_STRATEGIES:
            raise ResourceError(f"{label}.strategy is unsupported: {strategy!r}")
        if "approx" in str(strategy).lower():
            raise ResourceError(f"{label} must not use approximation")
        validate_mapping_strategy(source_id, source_path, str(strategy), label)
        if android_root is not None:
            inside_file(android_root, source_path, f"{label}.sourcePath")
        if strategy == "blocked":
            blocked = True
            continue
        require_text(mapping.get("targetRef"), f"{label}.targetRef")
        target = inside_file(
            target_root,
            require_text(mapping.get("targetPath"), f"{label}.targetPath"),
            f"{label}.targetPath",
        )
        if strategy == 'byte_copy':
            if android_root is None:
                raise ResourceError('byte_copy verification requires android_root')
            source = inside_file(android_root, source_path, f'{label}.sourcePath')
            if source.read_bytes() != target.read_bytes():
                raise ResourceError(f'{label}.byte_copy source and target bytes differ')

    for index, item in enumerate(manual_items):
        if not isinstance(item, dict):
            raise ResourceError(f"manualItems[{index}] must be an object")
        require_text(item.get("sourceId"), f"manualItems[{index}].sourceId")
        require_text(item.get("reason"), f"manualItems[{index}].reason")
    for index, path in enumerate(files_changed):
        inside_file(
            target_root,
            require_text(path, f"filesChanged[{index}]"),
            f"filesChanged[{index}]",
        )

    if status == "READY_FOR_LEAN" and (manual_items or blocked):
        raise ResourceError("READY_FOR_LEAN requires no manualItems or blocked mappings")
    if status == "BLOCKED" and not (manual_items or blocked):
        raise ResourceError("BLOCKED requires a manual item or blocked mapping")
    return {
        "status": status,
        "changeId": change_id,
        "approvedSpecHash": approved_hash,
        "mappingCount": len(mappings),
        "result": str(result_path),
    }


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    scan_parser = commands.add_parser("scan")
    scan_parser.add_argument("--android-root", required=True)
    scan_parser.add_argument("--ui-tree")
    scan_parser.add_argument("--source-index")
    scan_parser.add_argument("--extra-ref", action="append", default=[])

    vector = commands.add_parser("prepare-vector")
    vector.add_argument("--android-root", required=True)
    vector.add_argument("--target-root", required=True)
    vector.add_argument("--source", required=True)
    vector.add_argument("--destination", required=True)
    vector.add_argument("--source-id", required=True)
    vector.add_argument("--target-ref", required=True)
    vector.add_argument("--consumer", action="append", default=[])
    vector.add_argument("--resolve-ref", action="append", default=[])
    vector.add_argument("--consumer-tint")

    validate = commands.add_parser("validate-result")
    validate.add_argument("--android-root")
    validate.add_argument("--target-root", required=True)
    validate.add_argument("--result", required=True)
    validate.add_argument("--approved-spec-hash")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        if args.command == "scan":
            result = scan(args)
        elif args.command == "prepare-vector":
            result = prepare_vector(args)
        else:
            result = validate_result(args)
    except (ResourceError, OSError, ValueError) as exc:
        print(f"RESOURCE_ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
