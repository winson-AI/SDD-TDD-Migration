"""Read-only primitives extracted from the user supplied Lean bundle.

No standalone CLI, default output directory, config lookup, retries, or workflow authority.
Managed lean_visual_worker owns configuration, execution bounds, paths and status.
"""
from __future__ import annotations
import hashlib
import re
from typing import Any
import xml.etree.ElementTree as ET

class CaptureError(RuntimeError):
    pass

def harmony_page_name(data: dict[str, Any]) -> str:
    stack = [data]
    while stack:
        item = stack.pop(0)
        attrs = item.get("attributes") if isinstance(item, dict) else None
        if isinstance(attrs, dict) and attrs.get("pagePath"):
            return str(attrs["pagePath"]).rstrip("/").split("/")[-1]
        children = item.get("children") if isinstance(item, dict) else None
        if isinstance(children, list):
            stack.extend(child for child in children if isinstance(child, dict))
    return "unknown"


def harmony_node(data: dict[str, Any]) -> ET.Element | None:
    attrs = data.get("attributes") if isinstance(data, dict) else {}
    attrs = attrs if isinstance(attrs, dict) else {}
    node_type = str(attrs.get("type") or "")
    bundle = str(attrs.get("bundleName") or "")
    if node_type in {"WindowScene", "__Common__", "EffectComponent", "metaballNode"} or bundle in {
        "com.huawei.systemui", "com.ohos.systemui", "com.huawei.android.launcher"
    }:
        children = data.get("children") if isinstance(data, dict) else []
        for child in children if isinstance(children, list) else []:
            converted = harmony_node(child)
            if converted is not None:
                return converted
        return None
    converted_attrs = {
        "class": node_type,
        "resource-id": str(attrs.get("key") or ""),
        "text": str(attrs.get("text") or ""),
        "content-desc": str(attrs.get("description") or ""),
        "clickable": str(attrs.get("clickable", False)).lower(),
        "long-clickable": str(attrs.get("longClickable", False)).lower(),
        "scrollable": str(attrs.get("scrollable", False)).lower(),
        "enabled": str(attrs.get("enabled", True)).lower(),
        "focused": str(attrs.get("focused", False)).lower(),
        "bounds": str(attrs.get("bounds") or ""),
        "package": bundle,
    }
    element = ET.Element("node", converted_attrs)
    children = data.get("children") if isinstance(data, dict) else []
    for child in children if isinstance(children, list) else []:
        converted = harmony_node(child)
        if converted is not None:
            element.append(converted)
    return element


def bounds_center(bounds: str) -> tuple[int, int] | None:
    values = [int(value) for value in re.findall(r"-?\d+", bounds)]
    if len(values) != 4:
        return None
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1 + x2) // 2, (y1 + y2) // 2


def bounds_box(bounds: str) -> tuple[int, int, int, int] | None:
    values = [int(value) for value in re.findall(r"-?\d+", bounds)]
    if len(values) != 4:
        return None
    x1, y1, x2, y2 = values
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def scrollable_regions(xml: str) -> list[tuple[int, int, int, int]]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CaptureError(f"invalid view XML: {exc}") from exc
    regions: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for node in root.iter("node"):
        if node.attrib.get("scrollable") != "true":
            continue
        box = bounds_box(node.attrib.get("bounds", ""))
        if box and box not in seen:
            seen.add(box)
            regions.append(box)
    return sorted(
        regions,
        key=lambda item: ((item[2] - item[0]) * (item[3] - item[1]), item[3] - item[1]),
        reverse=True,
    )


def view_signature(xml: str, foreground: str) -> str:
    try:
        root = ET.fromstring(xml)
        nodes = []
        for node in root.iter("node"):
            attrs = node.attrib
            nodes.append(
                "|".join(
                    str(attrs.get(key, ""))
                    for key in ("class", "resource-id", "text", "content-desc", "clickable", "bounds")
                )
            )
        normalized = "\n".join(nodes)
    except ET.ParseError:
        normalized = xml
    return hashlib.sha256(f"{foreground}\n{normalized}".encode("utf-8")).hexdigest()
