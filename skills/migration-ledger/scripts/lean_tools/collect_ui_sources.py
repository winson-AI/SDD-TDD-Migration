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

import resource_facts
import resource_signals


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
    r"(?P<method>setBackgroundColor|setBackgroundResource|setBackgroundDrawable|setBackground|setForeground|"
    r"setTextColor|setTextSize|setPadding|setPaddingRelative|setImageResource|setImageDrawable|setImageBitmap|"
    r"setImageURI|setImageTintList|setScaleType|setAnimation|setColorFilter|setCompoundDrawables|"
    r"setCompoundDrawablesWithIntrinsicBounds|setCompoundDrawablesRelative|"
    r"setCompoundDrawablesRelativeWithIntrinsicBounds|setTypeface)\s*\("
)
PRESENTATION_ASSIGNMENT_RE = re.compile(
    r"\b(?P<target>[A-Za-z_][A-Za-z0-9_.]*)\.(?P<method>scaleType|imageTintList|background|foreground)\s*=(?!=)"
)
PRESENTATION_PROPERTIES = {
    "setBackgroundColor": "background",
    "setBackgroundResource": "background",
    "setBackgroundDrawable": "background",
    "setBackground": "background",
    "setForeground": "foreground",
    "scaleType": "scaleType",
    "imageTintList": "tint",
    "background": "background",
    "foreground": "foreground",
    "setImageBitmap": "image",
    "setImageURI": "image",
    "setImageTintList": "tint",
    "setScaleType": "scaleType",
    "setAnimation": "animation",
    "setCompoundDrawablesRelative": "compoundDrawables",
    "setCompoundDrawablesRelativeWithIntrinsicBounds": "compoundDrawables",
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
    for match in PRESENTATION_ASSIGNMENT_RE.finditer(text):
        end = text.find("\n", match.end())
        expression = text[match.start() : end if end >= 0 else len(text)][:240]
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
    mutations.sort(key=lambda item: item["line"])
    return mutations


def element_selector(parent_selector: str, tag: str, index: int, android_id: str | None) -> str:
    segment = local_name(tag)
    if android_id:
        segment += f"[@android:id='{android_id}']"
    else:
        segment += f"[{index}]"
    return f"{parent_selector}/{segment}" if parent_selector else f"/{segment}"


def parse_layout_node(element: ET.Element, selector: str, hints: list | None = None) -> dict:
    raw_attrs: dict[str, str] = {}
    direct_refs: set[str] = set()
    android_id = element.attrib.get(f"{{{ANDROID_NS}}}id")
    names = {qualified_name(raw_name) for raw_name in element.attrib}
    for raw_name, value in element.attrib.items():
        name = qualified_name(raw_name)
        if hints is not None:
            resource_signals.layout_hint(hints, selector, name, value, names)
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
        parsed = parse_layout_node(child, child_selector, hints)
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

    # A class may be named by its file name or by its qualified name (package.Class).
    requested = Path(path_text).stem if Path(path_text).suffix in SOURCE_SUFFIXES else path_text.rsplit(".", 1)[-1]
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


def block_end(text: str, open_brace: int) -> int | None:
    """Offset just past the brace closing the block opened at `open_brace`; comments, strings and chars are skipped."""
    depth, index, size = 0, open_brace, len(text)
    while index < size:
        char = text[index]
        if text.startswith("//", index):
            index = text.find("\n", index)
            index = size if index < 0 else index
        elif text.startswith("/*", index):
            index = text.find("*/", index + 2)
            index = size if index < 0 else index + 2
        elif text.startswith('"""', index):
            index = text.find('"""', index + 3)
            index = size if index < 0 else index + 3
        elif char in "\"'":
            index += 1
            while index < size and text[index] != char and text[index] != "\n":
                index += 2 if text[index] == "\\" else 1
            index += 1
        else:
            depth += char == "{"
            if char == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
    return None


def declaration_spans(text: str, symbol: str) -> list[tuple[int, int]]:
    """(start, end) offsets of every class, interface, enum or object named `symbol` declared in the text."""
    spans = []
    for match in re.finditer(r"\b(?:class|interface|enum|object|record)\s+" + re.escape(symbol) + r"\b", text):
        start = text.rfind("\n", 0, match.start()) + 1
        if text[start:match.start()].lstrip().startswith(("//", "*", "/*")):
            continue  # a mention in a comment, not a declaration
        opening = text.find("{", match.end())
        end = block_end(text, opening) if opening >= 0 else None
        if end:
            spans.append((start, end))
    return spans


def scoped_text(text: str, symbols) -> tuple[str, list[dict]]:
    """The text with everything outside the named declarations blanked, so offsets and line numbers stay those of the
    file, and the line ranges kept. An entry `path#Class` collects that class alone: a screen that is one class of a
    large file is indexed without the other screens the file holds."""
    spans = sorted({span for symbol in sorted(symbols) for span in declaration_spans(text, symbol)})
    kept, cursor, pieces = [], 0, []
    for start, end in spans:
        if start < cursor:
            continue  # nested in a span already kept
        pieces.append(re.sub(r"[^\n]", " ", text[cursor:start]))
        pieces.append(text[start:end])
        kept.append({"lines": [line_number(text, start), line_number(text, end - 1)]})
        cursor = end
    pieces.append(re.sub(r"[^\n]", " ", text[cursor:]))
    return "".join(pieces), kept


def role_hint(text: str, offset: int) -> str:
    window = text[max(0, offset - 800) : min(len(text), offset + 800)]
    if re.search(r"\b(?:Adapter|ViewHolder|ListAdapter|RecyclerView\.Adapter)\b", window):
        return "list_item"
    if re.search(r"\b(?:Dialog|DialogFragment|AlertDialog|BottomSheet)\b", window):
        return "dialog"
    if re.search(r"\b(?:setContentView|onCreateView|Fragment|Activity)\b", window):
        return "screen"
    return "unknown"


def inspect_source(path: Path, root: Path, text: str | None = None) -> tuple[dict, list[dict], list[dict]]:
    text = path.read_text(encoding="utf-8", errors="replace") if text is None else text
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


def parse_layout(path: Path, root: Path) -> tuple[dict, list[tuple[str, str]], list[dict]]:
    try:
        document = ET.parse(path)
    except ET.ParseError as exc:
        raise CollectionError(f"invalid layout XML {path}: {exc}") from exc
    xml_root = document.getroot()
    root_id = xml_root.attrib.get(f"{{{ANDROID_NS}}}id")
    selector = element_selector("", xml_root.tag, 1, root_id)
    hints: list[dict] = []
    parsed_root = parse_layout_node(xml_root, selector, hints)
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
        [{**hint, "sourcePath": relative} for hint in hints],
    )


def parse_xml_document(path: Path, root: Path, kind: str, name: str, qualifier: str) -> dict:
    """A menu, preference or navigation document: its nodes keep their attributes, its icons are references."""
    try:
        xml_root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise CollectionError(f"invalid {kind} XML {path}: {exc}") from exc
    parsed = parse_layout_node(
        xml_root, element_selector("", xml_root.tag, 1, xml_root.attrib.get(f"{{{ANDROID_NS}}}id")))
    return {"ref": f"@{kind}/{name}", "kind": kind, "name": name, "qualifier": qualifier,
            "path": relative_to_root(path, root), "sha256": sha256_file(path), "root": parsed,
            "resourceRefs": parsed["resourceRefs"]}


def parse_manifest(path: Path, root: Path) -> dict:
    """Only the icon-bearing attributes of a manifest; the rest of it is not display."""
    try:
        xml_root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise CollectionError(f"invalid manifest XML {path}: {exc}") from exc
    icons = []
    for element in xml_root.iter():
        for attr in ("icon", "roundIcon", "logo", "banner"):
            for ref in resource_facts.references(element.attrib.get(f"{{{ANDROID_NS}}}{attr}")):
                icons.append({"element": local_name(element.tag), "name": element.attrib.get(f"{{{ANDROID_NS}}}name"),
                              "attr": "android:" + attr, "ref": ref})
    relative = relative_to_root(path, root)
    return {"ref": "manifest:" + relative, "kind": "manifest", "name": relative, "qualifier": "default",
            "path": relative, "sha256": sha256_file(path), "icons": icons,
            "resourceRefs": sorted({icon["ref"] for icon in icons})}


def discover_resource(root: Path, ref: str, catalog: resource_signals.Catalog | None = None) -> list[dict]:
    """Every declaration of a reference (values entries and res/ files), one row per qualifier."""
    return (catalog or resource_signals.Catalog(root)).rows(ref)


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
        # `path#Class` asks for that class alone; a path or a class name asks for the whole file.
        named = symbol if "#" in requested else None
        if named and not declaration_spans(path.read_text(encoding="utf-8", errors="replace"), named):
            unresolved.append({"kind": "entry", "requested": requested, "reason": "symbol is not declared in the source file"})
            entries.append({"requested": requested, "sourcePath": relative_to_root(path, root), "symbol": symbol})
            continue
        scope = source_paths.setdefault(path, {"symbols": set(), "whole": False})
        scope["symbols" if named else "whole"] = scope["symbols"] | {named} if named else True
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
        source_paths.setdefault(path, {"symbols": set(), "whole": False})["whole"] = True

    source_facts: list[dict] = []
    layout_references: list[dict] = []
    compose_functions: list[dict] = []
    source_resource_refs: set[str] = set()
    catalog = resource_signals.Catalog(root)
    image_rows: list[dict] = []
    sink_candidates: list[dict] = []
    asset_names: set[str] = set()
    for path in sorted(source_paths):
        scope = source_paths[path]
        text = path.read_text(encoding="utf-8", errors="replace")
        kept = None
        if scope["symbols"] and not scope["whole"]:
            text, kept = scoped_text(text, scope["symbols"])
        fact, references, composables = inspect_source(path, root, text)
        if kept is not None:
            fact["scope"] = {"symbols": sorted(scope["symbols"]), "ranges": kept}
        source_facts.append(fact)
        source_resource_refs.update(fact["resourceRefs"])
        layout_references.extend(references)
        compose_functions.extend(composables)
        found = resource_signals.code_sources(
            catalog, text, fact["path"],
            getattr(args, "image_sinks", None) or (), getattr(args, "layout_helpers", None) or ())
        image_rows.extend(found["imageSources"])
        asset_names.update(found["assets"])
        fact["resourceUsages"] = found["usages"]
        fact["parameters"] = found["parameters"]
        sink_candidates.extend(found["sinkCandidates"])

    layout_index = discover_layout_files(root)
    requested_layouts = list(args.layout)
    requested_layouts.extend(item["layoutName"] for item in layout_references)
    layout_queue = deque(dict.fromkeys(requested_layouts))
    xml_queue: deque = deque()
    ref_queue: deque = deque()
    visited_names: set[str] = set()
    visited_xml: set[tuple[str, str]] = set()
    seen_refs: set[str] = set()
    parents: dict[str, set[str]] = {}
    layout_documents: list[dict] = []
    layout_edges: list[dict] = []
    xml_documents: list[dict] = []
    resource_documents: list[dict] = []
    theme_attrs: list[dict] = []
    missing: list[dict] = []
    hints: list[dict] = []

    def note(ref: str, parent: str | None = None) -> None:
        if parent:
            parents.setdefault(ref, set()).add(parent)
        ref_queue.append(ref)
        kind, _, name = ref.lstrip("@?").partition("/")
        if kind in resource_signals.XML_KINDS:
            xml_queue.append((kind, name))

    for ref in sorted(source_resource_refs):
        note(ref)
    for row in image_rows:
        for ref in resource_signals.source_refs(row):
            note(ref)
    for relative in sorted(asset_names):
        asset = catalog.asset_row(relative)
        if asset:
            resource_documents.append(asset)
        else:
            missing.append({"kind": "asset", "requested": relative,
                            "reason": "referenced asset was not found under assets/"})
    for requested in getattr(args, "manifest", None) or []:
        manifest = Path(requested).expanduser()
        manifest = (manifest if manifest.is_absolute() else root / manifest).resolve()
        if not manifest.is_file():
            unresolved.append({"kind": "manifest", "requested": requested, "reason": "manifest was not found"})
            continue
        document = parse_manifest(manifest, root)
        xml_documents.append(document)
        for ref in document["resourceRefs"]:
            note(ref)

    while layout_queue or xml_queue or ref_queue:
        while layout_queue:
            name = layout_queue.popleft()
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
                document, relationships, found = parse_layout(path, root)
                layout_documents.append(document)
                hints.extend(found)
                for ref in document["resourceRefs"]:
                    note(ref)
                for target, relation in relationships:
                    layout_edges.append(
                        {
                            "fromPath": document["path"],
                            "toLayoutName": target,
                            "relation": relation,
                        }
                    )
                    layout_queue.append(target)
        while xml_queue:
            kind, name = xml_queue.popleft()
            if (kind, name) in visited_xml:
                continue
            visited_xml.add((kind, name))
            for qualifier, path in catalog.xml_files(kind, name):
                document = parse_xml_document(path, root, kind, name, qualifier)
                xml_documents.append(document)
                for ref in document["resourceRefs"]:
                    note(ref)
                    if ref.startswith("@layout/"):
                        layout_edges.append({"fromPath": document["path"], "toLayoutName": ref[len("@layout/") :],
                                             "relation": "xml_reference"})
                        layout_queue.append(ref[len("@layout/") :])
        while ref_queue:
            ref = ref_queue.popleft()
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            # Code references retain ids in sourceFiles.resourceRefs for node/binding
            # analysis, but an id identifies a node rather than a migratable file.
            if ref.startswith(("@id/", "@android:id/")):
                continue
            matches = catalog.rows(ref)
            if matches:
                for row in matches:
                    catalog.describe(row)
                    for nested in row.get("references", []):
                        note(nested["ref"], ref)
                resource_documents.extend(matches)
            elif ref.startswith("?attr/"):
                # A theme attribute is defined by the project's styles or by a library; it is never silently dropped.
                definitions = catalog.theme_definitions(ref.split("/", 1)[1])
                theme_attrs.append({"ref": ref, "status": "project" if definitions else "library",
                                    "definitions": definitions})
                for definition in definitions:
                    for nested in resource_facts.references(definition["value"]):
                        note(nested, ref)
            else:
                missing.append(
                    {
                        "kind": "resource",
                        "requested": ref,
                        "reason": "referenced resource was not found in the scoped source root",
                    }
                )

    unresolved.extend(sorted(missing, key=lambda item: (item["kind"], item["requested"])))
    for row in resource_documents:
        if row["ref"] in parents:
            row["via"] = sorted(parents[row["ref"]])
    for hint in hints:
        image_rows.append(hint)
    layout_documents.sort(key=lambda item: (item["name"], item["qualifier"], item["path"]))
    layout_references.sort(key=lambda item: (item["sourcePath"], item["line"], item["layoutName"]))
    layout_edges.sort(key=lambda item: (item["fromPath"], item["toLayoutName"], item["relation"]))
    resource_documents.sort(key=lambda item: (item["ref"], item.get("qualifier", ""), item.get("path", "")))
    xml_documents.sort(key=lambda item: (item["kind"], item["name"], item["qualifier"], item["path"]))
    theme_attrs.sort(key=lambda item: item["ref"])

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
        "xmlResources": xml_documents,
        "resources": resource_documents,
        "themeAttrs": theme_attrs,
        "imageSources": resource_signals.identify(image_rows),
        "imageSinkCandidates": sink_candidates,
        "unresolved": unresolved,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-root", required=True)
    parser.add_argument("--scope", default="source-ui")
    parser.add_argument("--entry", action="append", default=[])
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--layout", action="append", default=[])
    parser.add_argument("--manifest", action="append", default=[], help="manifest whose icon attributes belong to the scope")
    parser.add_argument("--image-sink", dest="image_sinks", action="append", default=[],
                        help="project method that loads an image from its first argument")
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
