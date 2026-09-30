#!/usr/bin/env python3
"""Collect deterministic Android UI source facts for a scoped Lean migration.

This script does not infer product behavior. It inventories the XML/resource facts and
code anchors that an agent uses to build a source-backed ``ui-tree.json``.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


ANDROID_NS = "http://schemas.android.com/apk/res/android"
APP_NS = "http://schemas.android.com/apk/res-auto"
TOOLS_NS = "http://schemas.android.com/tools"
NAMESPACE_PREFIXES = {
    ANDROID_NS: "android",
    APP_NS: "app",
    TOOLS_NS: "tools",
}

SOURCE_SUFFIXES = {".kt", ".kts", ".java"}
RESOURCE_REF_RE = re.compile(r"[@?](?:android:)?[A-Za-z_][\w.-]*/[A-Za-z_][\w.-]*")
CODE_RESOURCE_REF_RE = re.compile(
    r"(?<![\w.])(?P<platform>android\.)?R\."
    r"(?P<kind>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
PRESENTATION_MUTATION_RE = re.compile(
    r"\b(?P<target>[A-Za-z_][A-Za-z0-9_.]*)\."
    r"(?P<method>setBackgroundColor|setBackgroundResource|setTextColor|setTextSize|"
    r"setPadding|setPaddingRelative|setImageResource|setImageDrawable|setColorFilter|"
    r"setCompoundDrawables|setCompoundDrawablesWithIntrinsicBounds|setTypeface)\s*\("
)
PRESENTATION_PROPERTIES = {
    "setBackgroundColor": "background",
    "setBackgroundResource": "background",
    "setTextColor": "textColor",
    "setTextSize": "textSize",
    "setPadding": "padding",
    "setPaddingRelative": "padding",
    "setImageResource": "image",
    "setImageDrawable": "image",
    "setColorFilter": "colorFilter",
    "setCompoundDrawables": "compoundDrawables",
    "setCompoundDrawablesWithIntrinsicBounds": "compoundDrawables",
    "setTypeface": "typeface",
}
LAYOUT_REF_RE = re.compile(r"\bR\.layout\.([A-Za-z_][A-Za-z0-9_]*)")
BINDING_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)Binding\s*\.\s*(?:inflate|bind)\b")
COMPOSABLE_RE = re.compile(r"@Composable\b")
FUN_RE = re.compile(r"\bfun\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

UI_ANCHOR_PATTERNS = {
    "set_content_view": re.compile(r"\bsetContentView\s*\("),
    "set_compose_content": re.compile(r"\bsetContent\s*\{"),
    "inflate": re.compile(r"\b(?:inflate|View\.inflate)\s*\("),
    "add_view": re.compile(r"\baddView\s*\("),
    "visibility_mutation": re.compile(r"\.(?:visibility|isVisible)\s*="),
    "layout_mutation": re.compile(r"\.(?:layoutParams|translation[XY]|alpha)\s*="),
    "dialog": re.compile(r"\b(?:AlertDialog|DialogFragment|BottomSheetDialog|Dialog)\b"),
    "list": re.compile(r"\b(?:RecyclerView|ListView|ViewHolder|ListAdapter|RecyclerView\.Adapter)\b"),
    "navigation": re.compile(r"\b(?:navigate|NavController|startActivity|FragmentTransaction)\b"),
    "compose_container": re.compile(
        r"\b(?:Scaffold|Column|Row|Box|LazyColumn|LazyRow|LazyVerticalGrid|Pager|Dialog|Popup)\s*\("
    ),
}


class CollectionError(RuntimeError):
    pass


def relative_to_root(path: Path, root: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise CollectionError(f"path is outside Android root: {path}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def camel_to_snake(value: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def qualified_name(name: str) -> str:
    if not name.startswith("{"):
        return name
    namespace, local = name[1:].split("}", 1)
    prefix = NAMESPACE_PREFIXES.get(namespace, namespace)
    return f"{prefix}:{local}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def resource_refs(value: str) -> list[str]:
    return sorted(
        ref
        for ref in set(RESOURCE_REF_RE.findall(value))
        if not ref.startswith("@id/")
    )


def code_resource_refs(value: str) -> list[str]:
    refs = set()
    for match in CODE_RESOURCE_REF_RE.finditer(value):
        prefix = "@android:" if match.group("platform") else "@"
        refs.add(f"{prefix}{match.group('kind')}/{match.group('name')}")
    return sorted(refs)


def call_end(text: str, open_paren: int, limit: int = 2400) -> int | None:
    depth = 0
    end = min(len(text), open_paren + limit)
    for index in range(open_paren, end):
        character = text[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def presentation_mutations(text: str, source_path: str) -> list[dict]:
    mutations = []
    for match in PRESENTATION_MUTATION_RE.finditer(text):
        end = call_end(text, match.end() - 1)
        if end is None:
            continue
        expression = text[match.start() : end]
        mutations.append(
            {
                "target": match.group("target"),
                "method": match.group("method"),
                "property": PRESENTATION_PROPERTIES[match.group("method")],
                "sourcePath": source_path,
                "line": line_number(text, match.start()),
                "expression": " ".join(expression.split()),
                "resourceRefs": code_resource_refs(expression),
            }
        )
    return mutations


def element_selector(parent_selector: str, tag: str, index: int, android_id: str | None) -> str:
    segment = local_name(tag)
    if android_id:
        segment += f"[@android:id='{android_id}']"
    else:
        segment += f"[{index}]"
    return f"{parent_selector}/{segment}" if parent_selector else f"/{segment}"


def parse_layout_node(element: ET.Element, selector: str) -> dict:
    raw_attrs: dict[str, str] = {}
    direct_refs: set[str] = set()
    android_id = element.attrib.get(f"{{{ANDROID_NS}}}id")
    for raw_name, value in element.attrib.items():
        name = qualified_name(raw_name)
        if name.startswith("tools:") or name == "android:id":
            continue
        raw_attrs[name] = value
        direct_refs.update(resource_refs(value))

    refs = set(direct_refs)

    child_counts: dict[str, int] = {}
    children = []
    for child in list(element):
        tag = local_name(child.tag)
        child_counts[tag] = child_counts.get(tag, 0) + 1
        child_id = child.attrib.get(f"{{{ANDROID_NS}}}id")
        child_selector = element_selector(selector, child.tag, child_counts[tag], child_id)
        parsed = parse_layout_node(child, child_selector)
        children.append(parsed)
        refs.update(parsed["resourceRefs"])

    return {
        "tag": local_name(element.tag),
        "androidId": android_id,
        "selector": selector,
        "rawAttrs": raw_attrs,
        "directResourceRefs": sorted(
            ref for ref in direct_refs if not ref.startswith("@layout/")
        ),
        "resourceRefs": sorted(refs),
        "children": children,
    }


def discover_layout_files(root: Path) -> dict[str, list[Path]]:
    layouts: dict[str, list[Path]] = {}
    for path in root.rglob("*.xml"):
        if not path.is_file() or not path.parent.name.startswith("layout"):
            continue
        if "res" not in path.parts:
            continue
        layouts.setdefault(path.stem, []).append(path.resolve())
    for paths in layouts.values():
        paths.sort()
    return layouts


def resolve_source_argument(value: str, root: Path) -> tuple[Path | None, str | None]:
    path_text, separator, symbol = value.partition("#")
    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_file():
        return candidate.resolve(), symbol or None

    requested = Path(path_text).stem
    matches = [
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES and path.stem == requested
    ]
    if len(matches) == 1:
        return matches[0], symbol or requested
    return None, symbol or requested or value


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def role_hint(text: str, offset: int) -> str:
    window = text[max(0, offset - 800) : min(len(text), offset + 800)]
    if re.search(r"\b(?:Adapter|ViewHolder|ListAdapter|RecyclerView\.Adapter)\b", window):
        return "list_item"
    if re.search(r"\b(?:Dialog|DialogFragment|AlertDialog|BottomSheet)\b", window):
        return "dialog"
    if re.search(r"\b(?:setContentView|onCreateView|Fragment|Activity)\b", window):
        return "screen"
    return "unknown"


def inspect_source(path: Path, root: Path) -> tuple[dict, list[dict], list[dict]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    relative = relative_to_root(path, root)
    layout_refs: list[dict] = []
    seen_refs: set[tuple[int, str, str]] = set()

    for match in LAYOUT_REF_RE.finditer(text):
        key = (line_number(text, match.start()), match.group(1), "r_layout")
        if key in seen_refs:
            continue
        seen_refs.add(key)
        layout_refs.append(
            {
                "sourcePath": relative,
                "line": key[0],
                "layoutName": key[1],
                "relation": key[2],
                "roleHint": role_hint(text, match.start()),
            }
        )

    for match in BINDING_RE.finditer(text):
        layout_name = camel_to_snake(match.group(1))
        key = (line_number(text, match.start()), layout_name, "view_binding")
        if key in seen_refs:
            continue
        seen_refs.add(key)
        layout_refs.append(
            {
                "sourcePath": relative,
                "line": key[0],
                "layoutName": key[1],
                "relation": key[2],
                "roleHint": role_hint(text, match.start()),
            }
        )

    composables: list[dict] = []
    for annotation in COMPOSABLE_RE.finditer(text):
        tail = text[annotation.end() : annotation.end() + 800]
        function = FUN_RE.search(tail)
        if function:
            absolute_offset = annotation.end() + function.start()
            composables.append(
                {
                    "sourcePath": relative,
                    "line": line_number(text, absolute_offset),
                    "name": function.group(1),
                }
            )

    anchors: list[dict] = []
    for kind, pattern in UI_ANCHOR_PATTERNS.items():
        for match in pattern.finditer(text):
            anchors.append(
                {
                    "kind": kind,
                    "sourcePath": relative,
                    "line": line_number(text, match.start()),
                    "snippet": text[match.start() : match.start() + 160].splitlines()[0].strip(),
                }
            )
    anchors.sort(key=lambda item: (item["line"], item["kind"]))

    source_fact = {
        "path": relative,
        "language": path.suffix.lstrip("."),
        "sha256": sha256_file(path),
        "composables": composables,
        "uiAnchors": anchors,
        "resourceRefs": code_resource_refs(text),
        "presentationMutations": presentation_mutations(text, relative),
    }
    return source_fact, layout_refs, composables


def layout_reference_from_xml(value: str) -> str | None:
    match = re.fullmatch(r"@layout/([A-Za-z_][A-Za-z0-9_]*)", value.strip())
    return match.group(1) if match else None


def parse_layout(path: Path, root: Path) -> tuple[dict, list[tuple[str, str]]]:
    try:
        document = ET.parse(path)
    except ET.ParseError as exc:
        raise CollectionError(f"invalid layout XML {path}: {exc}") from exc
    xml_root = document.getroot()
    root_id = xml_root.attrib.get(f"{{{ANDROID_NS}}}id")
    selector = element_selector("", xml_root.tag, 1, root_id)
    parsed_root = parse_layout_node(xml_root, selector)
    relationships: list[tuple[str, str]] = []
    for element in xml_root.iter():
        tag = local_name(element.tag)
        for raw_name, value in element.attrib.items():
            target = layout_reference_from_xml(value)
            if not target:
                continue
            name = qualified_name(raw_name)
            if tag == "include" or name == "layout":
                role = "include"
            elif tag == "ViewStub" or tag.endswith(".ViewStub"):
                role = "view_stub"
            elif name == "app:headerLayout":
                role = "header"
            elif name == "tools:listitem":
                role = "list_item_hint"
            else:
                role = "layout_reference"
            relationships.append((target, role))

    relative = relative_to_root(path, root)
    qualifier = path.parent.name[len("layout") :].lstrip("-") or "default"
    return (
        {
            "name": path.stem,
            "path": relative,
            "qualifier": qualifier,
            "sha256": sha256_file(path),
            "root": parsed_root,
            "resourceRefs": parsed_root["resourceRefs"],
        },
        relationships,
    )


def discover_resource(root: Path, ref: str) -> list[dict]:
    clean = ref.lstrip("@?")
    if clean.startswith("android:"):
        return [{"ref": ref, "kind": "platform", "status": "platform"}]
    if "/" not in clean:
        return []
    kind, name = clean.split("/", 1)
    found: list[dict] = []

    if kind in {"string", "color", "dimen", "integer", "bool", "style", "array", "plurals"}:
        for path in root.rglob("*.xml"):
            if not path.is_file() or not path.parent.name.startswith("values") or "res" not in path.parts:
                continue
            try:
                document = ET.parse(path)
            except ET.ParseError:
                continue
            for element in document.getroot():
                element_kind = local_name(element.tag)
                declared_kind = element.attrib.get("type", element_kind)
                if declared_kind in {"string-array", "integer-array"}:
                    declared_kind = "array"
                if element.attrib.get("name") != name or declared_kind != kind:
                    continue
                value: object
                if kind == "style":
                    value = {
                        "parent": element.attrib.get("parent"),
                        "items": {item.attrib.get("name", ""): "".join(item.itertext()).strip() for item in element},
                    }
                else:
                    value = "".join(element.itertext()).strip()
                found.append(
                    {
                        "ref": ref,
                        "kind": kind,
                        "qualifier": path.parent.name[len("values") :].lstrip("-") or "default",
                        "path": relative_to_root(path, root),
                        "sha256": sha256_file(path),
                        "value": value,
                    }
                )
    if kind not in {"string", "dimen", "integer", "bool", "style", "array", "plurals"}:
        for path in root.rglob(f"{name}.*"):
            if not path.is_file() or "res" not in path.parts:
                continue
            parent = path.parent.name
            if parent == kind or parent.startswith(f"{kind}-"):
                found.append(
                    {
                        "ref": ref,
                        "kind": kind,
                        "qualifier": parent[len(kind) :].lstrip("-") or "default",
                        "path": relative_to_root(path, root),
                        "sha256": sha256_file(path),
                    }
                )
    return found


def collect(args: argparse.Namespace) -> dict:
    root = Path(args.android_root).expanduser().resolve()
    if not root.is_dir():
        raise CollectionError(f"Android root does not exist: {root}")

    source_paths: dict[Path, dict] = {}
    entries: list[dict] = []
    unresolved: list[dict] = []
    for requested in args.entry:
        path, symbol = resolve_source_argument(requested, root)
        if path is None:
            unresolved.append(
                {
                    "kind": "entry",
                    "requested": requested,
                    "reason": "source entry could not be resolved uniquely",
                }
            )
            entries.append({"requested": requested, "sourcePath": None, "symbol": symbol})
            continue
        source_paths[path] = {}
        entries.append(
            {
                "requested": requested,
                "sourcePath": relative_to_root(path, root),
                "symbol": symbol,
            }
        )

    for requested in args.source_file:
        path, _ = resolve_source_argument(requested, root)
        if path is None:
            unresolved.append(
                {
                    "kind": "source_file",
                    "requested": requested,
                    "reason": "source file could not be resolved uniquely",
                }
            )
            continue
        source_paths[path] = {}

    source_facts: list[dict] = []
    layout_references: list[dict] = []
    compose_functions: list[dict] = []
    source_resource_refs: set[str] = set()
    for path in sorted(source_paths):
        fact, references, composables = inspect_source(path, root)
        source_facts.append(fact)
        source_resource_refs.update(fact["resourceRefs"])
        layout_references.extend(references)
        compose_functions.extend(composables)

    layout_index = discover_layout_files(root)
    requested_layouts = list(args.layout)
    requested_layouts.extend(item["layoutName"] for item in layout_references)
    queue = deque(dict.fromkeys(requested_layouts))
    visited_names: set[str] = set()
    layout_documents: list[dict] = []
    layout_edges: list[dict] = []
    all_refs: set[str] = set(source_resource_refs)

    while queue:
        name = queue.popleft()
        if name in visited_names:
            continue
        visited_names.add(name)
        variants = layout_index.get(name, [])
        if not variants:
            unresolved.append(
                {
                    "kind": "layout",
                    "requested": name,
                    "reason": "referenced layout resource was not found",
                }
            )
            continue
        for path in variants:
            document, relationships = parse_layout(path, root)
            layout_documents.append(document)
            all_refs.update(document["resourceRefs"])
            for target, relation in relationships:
                layout_edges.append(
                    {
                        "fromPath": document["path"],
                        "toLayoutName": target,
                        "relation": relation,
                    }
                )
                queue.append(target)

    resource_documents: list[dict] = []
    for ref in sorted(all_refs):
        # Code references retain ids in sourceFiles.resourceRefs for node/binding
        # analysis, but an id identifies a node rather than a migratable file.
        if ref.startswith(("@id/", "@android:id/")):
            continue
        matches = discover_resource(root, ref)
        if matches:
            resource_documents.extend(matches)
        elif not ref.startswith("?attr/"):
            unresolved.append(
                {
                    "kind": "resource",
                    "requested": ref,
                    "reason": "referenced resource was not found in the scoped source root",
                }
            )

    layout_documents.sort(key=lambda item: (item["name"], item["qualifier"], item["path"]))
    layout_references.sort(key=lambda item: (item["sourcePath"], item["line"], item["layoutName"]))
    layout_edges.sort(key=lambda item: (item["fromPath"], item["toLayoutName"], item["relation"]))
    resource_documents.sort(key=lambda item: (item["ref"], item.get("qualifier", ""), item.get("path", "")))

    return {
        "schemaVersion": 1,
        "scope": args.scope,
        "androidRoot": str(root),
        "entries": entries,
        "sourceFiles": source_facts,
        "layoutReferences": layout_references,
        "composeFunctions": compose_functions,
        "layouts": layout_documents,
        "layoutEdges": layout_edges,
        "resources": resource_documents,
        "unresolved": unresolved,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-root", required=True)
    parser.add_argument("--scope", default="source-ui")
    parser.add_argument("--entry", action="append", default=[])
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--layout", action="append", default=[])
    parser.add_argument("--out", required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.entry and not args.source_file and not args.layout:
        parser.error("at least one --entry, --source-file, or --layout is required")
    try:
        document = collect(args)
        output = Path(args.out).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (CollectionError, OSError) as exc:
        print(f"UI_SOURCE_COLLECTION_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"UI_SOURCE_INDEX_WRITTEN {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
