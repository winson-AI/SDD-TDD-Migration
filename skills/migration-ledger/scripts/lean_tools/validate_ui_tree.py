#!/usr/bin/env python3
"""Validate a Lean source-backed UI tree against its collected source index."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


ATTACHMENT_KINDS = {
    "drawer",
    "dialog",
    "menu",
    "overlay",
    "pager_page",
    "list_item",
    "header",
    "footer",
}
NODE_KINDS = {"container", "view", "virtual", "dynamic"}
ANALYSIS_STATUSES = {"expanded", "leaf", "dynamic", "blocked"}
VISIBILITIES = {"visible", "invisible", "gone", "runtime", "unknown"}
CLOSURE_STATUSES = {"mapped", "blocked", "out_of_scope"}
RUNTIME_INDEX_SCHEMA_VERSIONS = {1, 2}
RESOURCE_REF_RE = re.compile(r"[@?](?:android:)?[A-Za-z_][\w.-]*/[A-Za-z_][\w.-]*")


class ValidationError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"JSON root must be an object: {path}")
    return value


def require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValidationError(f"{label} must be an array")
    return value


def require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_node(
    value: object,
    label: str,
    known_paths: set[str],
    node_ids: set[str],
    source_nodes: dict[tuple[str, str], dict],
) -> None:
    node = require_object(value, label)
    required = {
        "id",
        "name",
        "nodeKind",
        "viewClass",
        "analysisStatus",
        "source",
        "initialVisibility",
        "layout",
        "presentation",
        "bindings",
        "events",
        "dynamicRules",
        "capabilities",
        "children",
    }
    missing = sorted(required - set(node))
    if missing:
        raise ValidationError(f"{label} is missing fields: {', '.join(missing)}")

    node_id = require_text(node["id"], f"{label}.id")
    if node_id in node_ids:
        raise ValidationError(f"duplicate UI node id: {node_id}")
    node_ids.add(node_id)
    require_text(node["name"], f"{label}.name")
    require_text(node["viewClass"], f"{label}.viewClass")
    if node["nodeKind"] not in NODE_KINDS:
        raise ValidationError(f"{label}.nodeKind is invalid: {node['nodeKind']}")
    if node["analysisStatus"] not in ANALYSIS_STATUSES:
        raise ValidationError(f"{label}.analysisStatus is invalid: {node['analysisStatus']}")
    if node["initialVisibility"] not in VISIBILITIES:
        raise ValidationError(f"{label}.initialVisibility is invalid: {node['initialVisibility']}")

    source = require_object(node["source"], f"{label}.source")
    source_path = require_text(source.get("path"), f"{label}.source.path")
    require_text(source.get("selector"), f"{label}.source.selector")
    if source.get("origin") not in {"xml", "code", "runtime_factory"}:
        raise ValidationError(f"{label}.source.origin is invalid")
    if source_path not in known_paths:
        raise ValidationError(f"{label}.source.path is absent from source index: {source_path}")
    selector = source["selector"]
    source_key = (source_path, selector)
    if source_key in source_nodes:
        raise ValidationError(f"duplicate UI source selector mapping: {source_path} {selector}")
    if "line" in source and source["line"] is not None:
        if not isinstance(source["line"], int) or source["line"] < 1:
            raise ValidationError(f"{label}.source.line must be a positive integer or null")

    layout = require_object(node["layout"], f"{label}.layout")
    require_object(layout.get("rawAttrs"), f"{label}.layout.rawAttrs")
    require_object(layout.get("resolvedAttrs"), f"{label}.layout.resolvedAttrs")
    require_text(layout.get("kind"), f"{label}.layout.kind")
    if not isinstance(layout.get("scrollable"), bool):
        raise ValidationError(f"{label}.layout.scrollable must be boolean")

    presentation = require_object(node["presentation"], f"{label}.presentation")
    refs = require_list(presentation.get("resourceRefs"), f"{label}.presentation.resourceRefs")
    for index, ref in enumerate(refs):
        require_text(ref, f"{label}.presentation.resourceRefs[{index}]")

    validate_semantic_records(node, label, known_paths)
    require_object(node["capabilities"], f"{label}.capabilities")
    source_nodes[source_key] = {
        "nodeId": node_id,
        "rawAttrs": layout["rawAttrs"],
        "presentationRefs": set(refs),
        "dynamicRules": node["dynamicRules"],
    }
    children = require_list(node["children"], f"{label}.children")
    for index, child in enumerate(children):
        validate_node(child, f"{label}.children[{index}]", known_paths, node_ids, source_nodes)


def flatten_source_layout(node: object, label: str) -> dict[str, dict]:
    value = require_object(node, label)
    selector = require_text(value.get("selector"), f"{label}.selector")
    raw_attrs = require_object(value.get("rawAttrs"), f"{label}.rawAttrs")
    direct_refs = value.get("directResourceRefs")
    if direct_refs is None:
        direct_refs = sorted(
            {
                ref
                for attr_value in raw_attrs.values()
                if isinstance(attr_value, str)
                for ref in RESOURCE_REF_RE.findall(attr_value)
                if not ref.startswith(("@id/", "@layout/"))
            }
        )
    else:
        direct_refs = require_list(direct_refs, f"{label}.directResourceRefs")
    flattened = {
        selector: {
            "rawAttrs": raw_attrs,
            "directResourceRefs": set(direct_refs),
        }
    }
    for index, child in enumerate(require_list(value.get("children"), f"{label}.children")):
        nested = flatten_source_layout(child, f"{label}.children[{index}]")
        overlap = set(flattened).intersection(nested)
        if overlap:
            raise ValidationError(f"source index contains duplicate XML selectors: {', '.join(sorted(overlap))}")
        flattened.update(nested)
    return flattened


def validate_source_anchor(record: dict, label: str, known_paths: set[str]) -> None:
    source_path = require_text(record.get("sourcePath"), f"{label}.sourcePath")
    if source_path not in known_paths:
        raise ValidationError(f"{label}.sourcePath is absent from source index: {source_path}")
    line = record.get("line")
    selector = record.get("selector")
    has_line = isinstance(line, int) and not isinstance(line, bool) and line > 0
    has_selector = isinstance(selector, str) and bool(selector.strip())
    if not has_line and not has_selector:
        raise ValidationError(f"{label} must contain a positive line or non-empty selector")


def validate_semantic_records(node: dict, label: str, known_paths: set[str]) -> None:
    bindings = require_list(node["bindings"], f"{label}.bindings")
    for index, raw_record in enumerate(bindings):
        record_label = f"{label}.bindings[{index}]"
        record = require_object(raw_record, record_label)
        require_text(record.get("target"), f"{record_label}.target")
        require_text(record.get("source"), f"{record_label}.source")
        validate_source_anchor(record, record_label, known_paths)

    events = require_list(node["events"], f"{label}.events")
    for index, raw_record in enumerate(events):
        record_label = f"{label}.events[{index}]"
        record = require_object(raw_record, record_label)
        require_text(record.get("trigger"), f"{record_label}.trigger")
        require_text(record.get("handler"), f"{record_label}.handler")
        validate_source_anchor(record, record_label, known_paths)

    dynamic_rules = require_list(node["dynamicRules"], f"{label}.dynamicRules")
    for index, raw_record in enumerate(dynamic_rules):
        record_label = f"{label}.dynamicRules[{index}]"
        record = require_object(raw_record, record_label)
        require_text(record.get("when"), f"{record_label}.when")
        require_text(record.get("property"), f"{record_label}.property")
        if "result" not in record:
            raise ValidationError(f"{record_label}.result is required")
        validate_source_anchor(record, record_label, known_paths)


def source_presentation_refs(source_index: dict) -> set[str]:
    refs: set[str] = set()
    for source in require_list(source_index.get("sourceFiles"), "source-index.sourceFiles"):
        if not isinstance(source, dict):
            continue
        mutations = source.get("presentationMutations", [])
        if not isinstance(mutations, list):
            continue
        for mutation in mutations:
            if not isinstance(mutation, dict):
                continue
            values = mutation.get("resourceRefs", [])
            if isinstance(values, list):
                refs.update(value for value in values if isinstance(value, str))
    return refs


def source_presentation_mutations(source_index: dict) -> set[tuple[str, int, str]]:
    mutations: set[tuple[str, int, str]] = set()
    for source in require_list(source_index.get("sourceFiles"), "source-index.sourceFiles"):
        if not isinstance(source, dict):
            continue
        for mutation in source.get("presentationMutations", []):
            if not isinstance(mutation, dict):
                continue
            path = mutation.get("sourcePath")
            line = mutation.get("line")
            property_name = mutation.get("property")
            if (
                isinstance(path, str)
                and path
                and isinstance(line, int)
                and line > 0
                and isinstance(property_name, str)
                and property_name
            ):
                mutations.add((path, line, property_name))
    return mutations


def validate(tree_path: Path, index_path: Path, runtime_index_path: Path | None = None) -> dict:
    tree = load_json(tree_path)
    source_index = load_json(index_path)
    if tree.get("schemaVersion") != 1:
        raise ValidationError("ui-tree.schemaVersion must equal 1")
    if source_index.get("schemaVersion") != 1:
        raise ValidationError("source index schemaVersion must equal 1")
    require_text(tree.get("scope"), "ui-tree.scope")

    generated = require_object(tree.get("generatedFrom"), "ui-tree.generatedFrom")
    expected_hash = sha256(index_path)
    if generated.get("sourceIndexSha256") != expected_hash:
        raise ValidationError("ui-tree.generatedFrom.sourceIndexSha256 does not match source index")
    if runtime_index_path is not None:
        runtime_index = load_json(runtime_index_path)
        if runtime_index.get("schemaVersion") not in RUNTIME_INDEX_SCHEMA_VERSIONS:
            supported = ", ".join(str(version) for version in sorted(RUNTIME_INDEX_SCHEMA_VERSIONS))
            raise ValidationError(
                f"runtime UI index schemaVersion must be one of: {supported}"
            )
        captures = require_list(runtime_index.get("captures"), "runtime-ui-index.captures")
        if not captures:
            raise ValidationError("runtime UI index captures must not be empty")
        if generated.get("runtimeIndexSha256") != sha256(runtime_index_path):
            raise ValidationError(
                "ui-tree.generatedFrom.runtimeIndexSha256 does not match runtime UI index"
            )

    known_paths = {
        item["path"]
        for item in require_list(source_index.get("sourceFiles"), "source-index.sourceFiles")
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    layout_items = require_list(source_index.get("layouts"), "source-index.layouts")
    layout_paths = {
        item["path"]
        for item in layout_items
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    layout_nodes_by_path = {
        item["path"]: flatten_source_layout(item.get("root"), f"source-index.layouts[{index}].root")
        for index, item in enumerate(layout_items)
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    known_paths.update(layout_paths)
    resource_paths = {
        item["path"]
        for item in require_list(source_index.get("resources"), "source-index.resources")
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    known_paths.update(resource_paths)

    screens = require_list(tree.get("screens"), "ui-tree.screens")
    if not screens:
        raise ValidationError("ui-tree.screens must not be empty")
    node_ids: set[str] = set()
    source_nodes: dict[tuple[str, str], dict] = {}
    attachment_anchors: list[tuple[str, str]] = []
    screen_ids: set[str] = set()
    for screen_index, raw_screen in enumerate(screens):
        label = f"ui-tree.screens[{screen_index}]"
        screen = require_object(raw_screen, label)
        screen_id = require_text(screen.get("id"), f"{label}.id")
        if screen_id in screen_ids:
            raise ValidationError(f"duplicate screen id: {screen_id}")
        screen_ids.add(screen_id)
        require_text(screen.get("name"), f"{label}.name")
        require_text(screen.get("kind"), f"{label}.kind")
        validate_node(screen.get("root"), f"{label}.root", known_paths, node_ids, source_nodes)
        attachments = require_list(screen.get("attachments"), f"{label}.attachments")
        for attachment_index, raw_attachment in enumerate(attachments):
            attachment_label = f"{label}.attachments[{attachment_index}]"
            attachment = require_object(raw_attachment, attachment_label)
            require_text(attachment.get("id"), f"{attachment_label}.id")
            if attachment.get("kind") not in ATTACHMENT_KINDS:
                raise ValidationError(f"{attachment_label}.kind is invalid")
            anchor = attachment.get("anchorNodeId")
            if anchor is not None:
                attachment_anchors.append((attachment_label, require_text(anchor, f"{attachment_label}.anchorNodeId")))
            validate_node(
                attachment.get("root"),
                f"{attachment_label}.root",
                known_paths,
                node_ids,
                source_nodes,
            )

    for label, anchor in attachment_anchors:
        if anchor not in node_ids:
            raise ValidationError(f"{label}.anchorNodeId references unknown node: {anchor}")

    closure = require_list(tree.get("layoutClosure"), "ui-tree.layoutClosure")
    closure_paths: set[str] = set()
    for index, raw_item in enumerate(closure):
        label = f"ui-tree.layoutClosure[{index}]"
        item = require_object(raw_item, label)
        path = require_text(item.get("path"), f"{label}.path")
        if path in closure_paths:
            raise ValidationError(f"duplicate layoutClosure path: {path}")
        closure_paths.add(path)
        if path not in layout_paths:
            raise ValidationError(f"{label}.path is absent from source index: {path}")
        status = item.get("status")
        if status not in CLOSURE_STATUSES:
            raise ValidationError(f"{label}.status is invalid")
        ids = require_list(item.get("nodeIds"), f"{label}.nodeIds")
        if status == "mapped" and not ids:
            raise ValidationError(f"{label}.nodeIds must not be empty when mapped")
        for node_id in ids:
            if node_id not in node_ids:
                raise ValidationError(f"{label}.nodeIds references unknown node: {node_id}")
        require_text(item.get("reason"), f"{label}.reason")
        if status == "mapped":
            expected = layout_nodes_by_path[path]
            actual = {
                selector: facts
                for (source_path, selector), facts in source_nodes.items()
                if source_path == path
            }
            missing_selectors = sorted(set(expected) - set(actual))
            extra_selectors = sorted(set(actual) - set(expected))
            if missing_selectors:
                raise ValidationError(
                    f"{label} omits XML selectors: {', '.join(missing_selectors)}"
                )
            if extra_selectors:
                raise ValidationError(
                    f"{label} contains selectors absent from source XML: {', '.join(extra_selectors)}"
                )
            for selector, expected_facts in expected.items():
                actual_attrs = actual[selector]["rawAttrs"]
                if actual_attrs != expected_facts["rawAttrs"]:
                    raise ValidationError(
                        f"{label} rawAttrs differ from source XML at {selector}"
                    )
                missing_refs = sorted(
                    expected_facts["directResourceRefs"]
                    - actual[selector]["presentationRefs"]
                )
                if missing_refs:
                    raise ValidationError(
                        f"{label} presentation.resourceRefs omits source XML references "
                        f"at {selector}: {', '.join(missing_refs)}"
                    )
            actual_ids = {facts["nodeId"] for facts in actual.values()}
            if set(ids) != actual_ids:
                raise ValidationError(
                    f"{label}.nodeIds must exactly cover nodes sourced from the mapped layout"
                )

    missing_layouts = sorted(layout_paths - closure_paths)
    if missing_layouts:
        raise ValidationError(f"layoutClosure is missing source layouts: {', '.join(missing_layouts)}")

    tree_presentation_refs = {
        ref
        for facts in source_nodes.values()
        for ref in facts["presentationRefs"]
    }
    missing_runtime_refs = sorted(
        source_presentation_refs(source_index) - tree_presentation_refs
    )
    if missing_runtime_refs:
        raise ValidationError(
            "ui-tree presentation.resourceRefs omits source runtime presentation references: "
            + ", ".join(missing_runtime_refs)
        )
    tree_mutations = {
        (rule.get("sourcePath"), rule.get("line"), rule.get("property"))
        for facts in source_nodes.values()
        for rule in facts["dynamicRules"]
        if isinstance(rule, dict)
    }
    missing_mutations = sorted(source_presentation_mutations(source_index) - tree_mutations)
    if missing_mutations:
        formatted = ", ".join(
            f"{path}:{line}:{property_name}"
            for path, line, property_name in missing_mutations
        )
        raise ValidationError(
            "ui-tree dynamicRules omits source runtime presentation mutations: " + formatted
        )

    critical = require_list(tree.get("criticalLayoutContracts"), "ui-tree.criticalLayoutContracts")
    for index, raw_item in enumerate(critical):
        label = f"ui-tree.criticalLayoutContracts[{index}]"
        item = require_object(raw_item, label)
        require_text(item.get("id"), f"{label}.id")
        screen_id = require_text(item.get("screenId"), f"{label}.screenId")
        if screen_id not in screen_ids:
            raise ValidationError(f"{label}.screenId references unknown screen: {screen_id}")
        subjects = require_list(item.get("subjects"), f"{label}.subjects")
        if not subjects:
            raise ValidationError(f"{label}.subjects must not be empty")
        for subject in subjects:
            if subject not in node_ids:
                raise ValidationError(f"{label}.subjects references unknown node: {subject}")
        require_text(item.get("kind"), f"{label}.kind")
        require_text(item.get("targetRequirement"), f"{label}.targetRequirement")

    require_list(tree.get("unresolved"), "ui-tree.unresolved")
    return {
        "screens": len(screens),
        "nodes": len(node_ids),
        "layouts": len(layout_paths),
        "criticalLayoutContracts": len(critical),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--source-index", required=True)
    parser.add_argument("--runtime-index")
    args = parser.parse_args()
    tree_path = Path(args.tree).expanduser().resolve()
    index_path = Path(args.source_index).expanduser().resolve()
    runtime_index_path = Path(args.runtime_index).expanduser().resolve() if args.runtime_index else None
    try:
        summary = validate(tree_path, index_path, runtime_index_path)
    except ValidationError as exc:
        print(f"UI_TREE_INVALID: {exc}", file=sys.stderr)
        return 1
    print("UI_TREE_VALID " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
