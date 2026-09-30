#!/usr/bin/env python3
"""Validate mobile UI capture manifests and requested page/state coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


class ManifestError(RuntimeError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read capture manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError("capture manifest must be a JSON object")
    return value


def require_file(value: object, label: str) -> Path:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file():
        raise ManifestError(f"{label} does not exist: {path}")
    return path


def parse_target(value: str) -> dict[str, str]:
    parts = value.split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ManifestError(f"target must be page_id:state_id:coverage: {value!r}")
    page_id, state_id, coverage = (part.strip() for part in parts)
    if coverage not in {"viewport", "scroll"}:
        raise ManifestError(f"unsupported target coverage {coverage!r}: {value!r}")
    return {"page_id": page_id, "state_id": state_id, "coverage": coverage}


def coverage_satisfies(coverage: dict[str, Any], requested: str) -> bool:
    achieved = coverage.get("achieved")
    if requested == "viewport":
        return achieved in {"viewport", "scroll-partial", "scroll-complete"}
    return achieved == "scroll-complete"


def validate_snapshot(snapshot: object, requested: str, label: str) -> None:
    if not isinstance(snapshot, dict):
        raise ManifestError(f"{label}.snapshot must be an object for COMPLETE evidence")
    for key in ("screenshot", "view_tree", "meta"):
        require_file(snapshot.get(key), f"{label}.snapshot.{key}")
    signature = snapshot.get("view_signature")
    if not isinstance(signature, str) or not signature.strip():
        raise ManifestError(f"{label}.snapshot.view_signature must be non-empty")
    backend = snapshot.get("device_backend")
    if not isinstance(backend, dict) or any(
        not str(backend.get(key) or "").strip() for key in ("name", "version", "device")
    ):
        raise ManifestError(
            f"{label}.snapshot.device_backend requires name, version, and device"
        )
    coverage = snapshot.get("coverage")
    if not isinstance(coverage, dict):
        raise ManifestError(f"{label}.snapshot.coverage must be an object")
    if coverage.get("requested") != requested:
        raise ManifestError(
            f"{label}.snapshot.coverage.requested must equal {requested!r}"
        )
    if not coverage_satisfies(coverage, requested):
        raise ManifestError(
            f"{label} coverage is incomplete: requested={requested} "
            f"achieved={coverage.get('achieved')} termination={coverage.get('termination')}"
        )
    captures = snapshot.get("captures")
    if not isinstance(captures, list) or not captures:
        raise ManifestError(f"{label}.snapshot.captures must be a non-empty array")
    if coverage.get("capture_count") != len(captures):
        raise ManifestError(
            f"{label}.snapshot.coverage.capture_count must equal captures length"
        )
    for index, capture in enumerate(captures):
        if not isinstance(capture, dict):
            raise ManifestError(f"{label}.snapshot.captures[{index}] must be an object")
        require_file(capture.get("screenshot"), f"{label}.snapshot.captures[{index}].screenshot")
        require_file(capture.get("view_tree"), f"{label}.snapshot.captures[{index}].view_tree")
        capture_signature = capture.get("view_signature")
        if not isinstance(capture_signature, str) or not capture_signature.strip():
            raise ManifestError(
                f"{label}.snapshot.captures[{index}].view_signature must be non-empty"
            )


def find_record(records: list[Any], requested: dict[str, str]) -> dict[str, Any] | None:
    return next(
        (
            record
            for record in records
            if isinstance(record, dict)
            and record.get("phase") == "android-reference"
            and record.get("platform") == "android"
            and record.get("page_id") == requested["page_id"]
            and record.get("state_id") == requested["state_id"]
        ),
        None,
    )


def validate_manifest(
    manifest: dict[str, Any], requested_targets: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    if manifest.get("schema_version") != 2:
        raise ManifestError(
            "capture manifest schema_version must equal 2; recapture legacy evidence"
        )
    records = manifest.get("targets")
    if not isinstance(records, list):
        raise ManifestError("capture manifest targets must be an array")
    requested_targets = requested_targets or [
        {
            "page_id": str(record.get("page_id") or ""),
            "state_id": str(record.get("state_id") or ""),
            "coverage": str(
                (record.get("coverage") or {}).get("requested")
                if isinstance(record.get("coverage"), dict)
                else ""
            ),
        }
        for record in records
        if isinstance(record, dict)
        and record.get("phase") == "android-reference"
        and record.get("platform") == "android"
        and record.get("status") in {"COMPLETE", "SOURCE_ONLY"}
    ]
    if not requested_targets:
        raise ManifestError("capture manifest has no requested Android reference targets")
    modes: set[str] = set()
    validated: list[str] = []
    for requested in requested_targets:
        label = f"{requested['page_id']}:{requested['state_id']}"
        record = find_record(records, requested)
        if record is None:
            raise ManifestError(f"capture manifest lacks Android reference for {label}")
        status = record.get("status")
        if status == "SOURCE_ONLY":
            if record.get("snapshot") is not None:
                raise ManifestError(f"{label} SOURCE_ONLY must not contain a snapshot")
            modes.add("source-only")
        elif status == "COMPLETE":
            requested_coverage = requested["coverage"]
            observed_variant = record.get("observed_variant")
            if not isinstance(observed_variant, str) or not observed_variant.strip():
                raise ManifestError(f"{label}.observed_variant must be non-empty")
            if observed_variant != requested["state_id"]:
                raise ManifestError(
                    f"{label}.observed_variant {observed_variant!r} must equal state_id; "
                    "record the visible tab/dialog/expanded state under a distinct state id"
                )
            coverage = record.get("coverage")
            if not isinstance(coverage, dict):
                raise ManifestError(f"{label}.coverage must be an object")
            if coverage.get("requested") != requested_coverage:
                raise ManifestError(
                    f"{label}.coverage.requested must equal {requested_coverage!r}"
                )
            validate_snapshot(record.get("snapshot"), requested_coverage, label)
            if coverage != record["snapshot"].get("coverage"):
                raise ManifestError(f"{label}.coverage must match snapshot.coverage")
            modes.add("runtime")
        else:
            raise ManifestError(f"Android reference {label} is {status}")
        validated.append(label)
    if len(modes) != 1:
        raise ManifestError("requested targets cannot mix runtime and source-only evidence")
    return {"mode": next(iter(modes)), "targets": validated}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--target", action="append", default=[])
    args = parser.parse_args()
    try:
        requested = [parse_target(value) for value in args.target]
        result = validate_manifest(
            load_object(Path(args.manifest).expanduser().resolve()), requested or None
        )
    except ManifestError as exc:
        print(f"CAPTURE_MANIFEST_INVALID: {exc}", file=sys.stderr)
        return 1
    print("CAPTURE_MANIFEST_VALID " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
