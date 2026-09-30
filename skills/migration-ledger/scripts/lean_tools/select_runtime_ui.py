#!/usr/bin/env python3
"""Select and normalize COMPLETE Android runtime UI captures for Lean."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


class RuntimeUiError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeUiError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeUiError(f"{label} must be a JSON object: {path}")
    return value


def require_file(value: object, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file():
        raise RuntimeUiError(f"{label} does not exist: {path}")
    return path


def node_facts(path: Path) -> list[dict]:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ET.ParseError) as exc:
        raise RuntimeUiError(f"cannot parse runtime view XML: {path}: {exc}") from exc
    facts: list[dict] = []
    for node in root.iter():
        attrs = node.attrib
        if node is root and not attrs:
            continue
        record = {
            key: attrs.get(key, "")
            for key in (
                "class",
                "resource-id",
                "text",
                "content-desc",
                "bounds",
                "package",
                "clickable",
                "enabled",
                "selected",
                "checked",
                "scrollable",
            )
        }
        if any(record.values()):
            facts.append(record)
    return facts


def parse_identity(raw: str) -> tuple[str, str, str]:
    parts = raw.split(":")
    if len(parts) not in {2, 3} or not all(part.strip() for part in parts):
        raise RuntimeUiError(
            f"--capture must use page-id:state-id[:viewport|scroll], got {raw!r}"
        )
    coverage = parts[2].strip() if len(parts) == 3 else "viewport"
    if coverage not in {"viewport", "scroll"}:
        raise RuntimeUiError(f"unsupported capture coverage {coverage!r} in {raw!r}")
    return parts[0].strip(), parts[1].strip(), coverage


def coverage_satisfies(coverage: dict, requested: str) -> bool:
    achieved = coverage.get("achieved")
    if requested == "viewport":
        return achieved in {"viewport", "scroll-partial", "scroll-complete"}
    return achieved == "scroll-complete"


def capture_coverage(match: dict, snapshot: dict, meta: dict) -> dict:
    raw = match.get("coverage")
    if not isinstance(raw, dict):
        raw = snapshot.get("coverage")
    if not isinstance(raw, dict):
        raw = meta.get("coverage")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "requested": str(raw.get("requested") or "viewport"),
        "achieved": str(raw.get("achieved") or "viewport"),
        "scrollable": bool(raw.get("scrollable", False)),
        "captureCount": raw.get("capture_count"),
        "termination": raw.get("termination") or "legacy-viewport",
    }


def viewport_files(
    raw_identity: str,
    snapshot: dict,
    meta: dict,
    screenshot: Path,
    view: Path,
    meta_path: Path,
) -> list[dict]:
    declared = snapshot.get("captures")
    viewports: list[dict] = []
    if isinstance(declared, list) and declared:
        for fallback_index, item in enumerate(declared):
            if not isinstance(item, dict):
                raise RuntimeUiError(f"{raw_identity} snapshot captures must contain objects")
            index = item.get("index", fallback_index)
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise RuntimeUiError(f"{raw_identity} viewport index is invalid: {index!r}")
            viewports.append(
                {
                    "index": index,
                    "screenshotPath": require_file(
                        item.get("screenshot"), f"{raw_identity} viewport {index} screenshot"
                    ),
                    "viewPath": require_file(
                        item.get("view_tree"), f"{raw_identity} viewport {index} view tree"
                    ),
                    "viewSignature": item.get("view_signature"),
                }
            )
    else:
        viewports.append(
            {
                "index": 0,
                "screenshotPath": screenshot,
                "viewPath": view,
                "viewSignature": meta.get("view_signature"),
            }
        )
        supplements = meta.get("scroll_captures") or []
        if not isinstance(supplements, list):
            raise RuntimeUiError(f"{raw_identity} metadata scroll_captures must be an array")
        for fallback_index, item in enumerate(supplements, start=1):
            if not isinstance(item, dict):
                raise RuntimeUiError(
                    f"{raw_identity} metadata scroll_captures must contain objects"
                )
            index = item.get("index", fallback_index)
            viewports.append(
                {
                    "index": index,
                    "screenshotPath": require_file(
                        meta_path.parent / str(item.get("screenshot") or ""),
                        f"{raw_identity} viewport {index} screenshot",
                    ),
                    "viewPath": require_file(
                        meta_path.parent / str(item.get("view") or ""),
                        f"{raw_identity} viewport {index} view tree",
                    ),
                    "viewSignature": item.get("view_signature"),
                }
            )
    viewports.sort(key=lambda item: item["index"])
    indices = [item["index"] for item in viewports]
    if indices != list(range(len(viewports))):
        raise RuntimeUiError(f"{raw_identity} viewport indices must be consecutive from zero")
    if viewports[0]["screenshotPath"] != screenshot or viewports[0]["viewPath"] != view:
        raise RuntimeUiError(f"{raw_identity} viewport zero does not match manifest base triple")
    return viewports


def merge_nodes(viewports: list[dict]) -> list[dict]:
    merged: dict[tuple[str, ...], dict] = {}
    identity_keys = (
        "class",
        "resource-id",
        "text",
        "content-desc",
        "package",
        "clickable",
        "enabled",
        "selected",
        "checked",
        "scrollable",
    )
    for viewport in viewports:
        viewport_index = viewport["index"]
        for fact in viewport["nodes"]:
            identity = tuple(str(fact.get(key, "")) for key in identity_keys)
            record = merged.get(identity)
            if record is None:
                record = {key: fact.get(key, "") for key in identity_keys}
                record["viewportIndices"] = []
                record["boundsByViewport"] = {}
                merged[identity] = record
            record["viewportIndices"].append(viewport_index)
            record["boundsByViewport"][str(viewport_index)] = fact.get("bounds", "")
    return list(merged.values())


def select(manifest_path: Path, identities: list[str]) -> dict:
    manifest = load_object(manifest_path, "capture manifest")
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise RuntimeUiError("capture manifest targets must be an array")
    captures: list[dict] = []
    for raw in identities:
        page_id, state_id, requested_coverage = parse_identity(raw)
        match = next(
            (
                item
                for item in targets
                if isinstance(item, dict)
                and item.get("mode") == "targeted"
                and item.get("phase") == "android-reference"
                and item.get("platform") == "android"
                and item.get("page_id") == page_id
                and item.get("state_id") == state_id
                and item.get("status") == "COMPLETE"
            ),
            None,
        )
        if match is None:
            raise RuntimeUiError(
                f"no COMPLETE Android reference for page={page_id} state={state_id}"
            )
        snapshot = match.get("snapshot")
        if not isinstance(snapshot, dict):
            raise RuntimeUiError(f"capture {raw} has no snapshot object")
        screenshot = require_file(snapshot.get("screenshot"), f"{raw} screenshot")
        view = require_file(snapshot.get("view_tree"), f"{raw} view tree")
        meta_path = require_file(snapshot.get("meta"), f"{raw} metadata")
        meta = load_object(meta_path, f"{raw} metadata")
        meta_screenshot = meta_path.parent / str(meta.get("screenshot") or "")
        if meta_screenshot.resolve() != screenshot:
            raise RuntimeUiError(f"{raw} metadata screenshot does not match manifest")
        coverage = capture_coverage(match, snapshot, meta)
        if not coverage_satisfies(coverage, requested_coverage):
            raise RuntimeUiError(
                f"{raw} coverage is incomplete: requested={requested_coverage} "
                f"achieved={coverage.get('achieved')} termination={coverage.get('termination')}"
            )
        viewport_paths = viewport_files(raw, snapshot, meta, screenshot, view, meta_path)
        if coverage["captureCount"] is not None and coverage["captureCount"] != len(viewport_paths):
            raise RuntimeUiError(
                f"{raw} coverage capture_count does not match retained viewport evidence"
            )
        viewports: list[dict] = []
        for viewport in viewport_paths:
            viewport_view = viewport.pop("viewPath")
            viewport_screenshot = viewport.pop("screenshotPath")
            viewports.append(
                {
                    **viewport,
                    "screenshot": {
                        "path": str(viewport_screenshot),
                        "sha256": sha256(viewport_screenshot),
                    },
                    "viewTree": {
                        "path": str(viewport_view),
                        "sha256": sha256(viewport_view),
                    },
                    "nodes": node_facts(viewport_view),
                }
            )
        captures.append(
            {
                "pageId": page_id,
                "stateId": state_id,
                "requestedCoverage": requested_coverage,
                "coverage": coverage,
                "screenshot": {"path": str(screenshot), "sha256": sha256(screenshot)},
                "viewTree": {"path": str(view), "sha256": sha256(view)},
                "meta": {"path": str(meta_path), "sha256": sha256(meta_path)},
                "pageName": meta.get("page_name"),
                "foreground": meta.get("foreground"),
                "viewSignature": meta.get("view_signature"),
                "viewports": viewports,
                "nodes": merge_nodes(viewports),
            }
        )
    return {
        "schemaVersion": 2,
        "manifest": str(manifest_path),
        "manifestSha256": sha256(manifest_path),
        "captureId": manifest.get("capture_id"),
        "captures": captures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--capture", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest = Path(args.manifest).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    try:
        payload = select(manifest, args.capture)
    except RuntimeUiError as exc:
        print(f"RUNTIME_UI_INVALID: {exc}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RUNTIME_UI_VALID {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
