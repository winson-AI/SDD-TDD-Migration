#!/usr/bin/env python3
"""Validate the compact three-round Harmony UI alignment result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


class AlignmentError(RuntimeError):
    pass


STATUSES = {"ALIGNED", "NEEDS_UI_FIX", "NEEDS_IMPLEMENTATION_FIX", "BLOCKED", "FAILED"}
ROUND_VERDICTS = {"ALIGNED", "NEEDS_UI_FIX", "INCOMPARABLE", "BLOCKED"}
TARGET_STATUSES = {
    "ALIGNED",
    "ALIGNED_CARRIED",
    "NEEDS_UI_FIX",
    "CAPTURE_BLOCKED",
    "NEEDS_IMPLEMENTATION_FIX",
}
ALIGNED_TARGET_STATUSES = {"ALIGNED", "ALIGNED_CARRIED"}
INTERACTION_STATUSES = {"PASSED", "FAILED", "BLOCKED"}


def load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlignmentError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AlignmentError(f"{label} must be a JSON object")
    return value


def resolve_file(root: Path, value: object, label: str) -> Path:
    raw = Path(str(value or "")).expanduser()
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    if not path.is_file():
        raise AlignmentError(f"{label} does not exist: {path}")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry_coverage(entry: dict) -> dict:
    raw = entry.get("coverage")
    if not isinstance(raw, dict):
        raise AlignmentError("manifest entry coverage must be an object")
    return {
        "requested": str(raw.get("requested") or ""),
        "achieved": str(raw.get("achieved") or ""),
        "termination": raw.get("termination"),
    }


def coverage_satisfies(coverage: dict, requested: str) -> bool:
    if requested == "viewport":
        return coverage.get("achieved") in {"viewport", "scroll-partial", "scroll-complete"}
    return coverage.get("achieved") == "scroll-complete"


def capture_indices(entry: dict) -> set[int]:
    snapshot = entry.get("snapshot") if isinstance(entry.get("snapshot"), dict) else {}
    captures = snapshot.get("captures")
    if not isinstance(captures, list) or not captures:
        raise AlignmentError("manifest snapshot captures must be a non-empty array")
    indices: set[int] = set()
    for item in captures:
        index = item.get("index") if isinstance(item, dict) else None
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise AlignmentError("manifest snapshot capture index is invalid")
        indices.add(index)
    if indices != set(range(len(indices))):
        raise AlignmentError("manifest snapshot capture indices must be consecutive from zero")
    return indices


def resolve_manifest_file(manifest_path: Path, value: object, label: str) -> Path:
    raw = Path(str(value or "")).expanduser()
    path = raw.resolve() if raw.is_absolute() else (manifest_path.parent / raw).resolve()
    if not path.is_file():
        raise AlignmentError(f"{label} does not exist: {path}")
    return path


def validate_snapshot_files(manifest_path: Path, entry: dict, label: str) -> None:
    snapshot = entry.get("snapshot")
    if not isinstance(snapshot, dict):
        raise AlignmentError(f"{label}.snapshot must be an object")
    for key in ("screenshot", "view_tree", "meta"):
        resolve_manifest_file(manifest_path, snapshot.get(key), f"{label}.snapshot.{key}")
    if not isinstance(snapshot.get("view_signature"), str) or not snapshot["view_signature"].strip():
        raise AlignmentError(f"{label}.snapshot.view_signature must be non-empty")
    backend = snapshot.get("device_backend")
    if not isinstance(backend, dict) or any(
        not str(backend.get(key) or "").strip() for key in ("name", "version", "device")
    ):
        raise AlignmentError(
            f"{label}.snapshot.device_backend requires name, version, and device"
        )
    if snapshot.get("coverage") != entry.get("coverage"):
        raise AlignmentError(f"{label}.snapshot.coverage must match entry coverage")
    captures = snapshot.get("captures")
    if not isinstance(captures, list) or not captures:
        raise AlignmentError(f"{label}.snapshot.captures must not be empty")
    for index, capture in enumerate(captures):
        capture_label = f"{label}.snapshot.captures[{index}]"
        if not isinstance(capture, dict):
            raise AlignmentError(f"{capture_label} must be an object")
        for key in ("screenshot", "view_tree"):
            resolve_manifest_file(manifest_path, capture.get(key), f"{capture_label}.{key}")
        if not isinstance(capture.get("view_signature"), str) or not capture["view_signature"].strip():
            raise AlignmentError(f"{capture_label}.view_signature must be non-empty")


def required_targets(result: dict) -> dict[tuple[str, str], str]:
    raw_targets = result.get("required_targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise AlignmentError("required_targets must be a non-empty list")
    targets: dict[tuple[str, str], str] = {}
    for index, item in enumerate(raw_targets):
        label = f"required_targets[{index}]"
        if not isinstance(item, dict):
            raise AlignmentError(f"{label} must be an object")
        page_id = str(item.get("page_id") or "").strip()
        state_id = str(item.get("state_id") or "").strip()
        coverage = str(item.get("coverage") or "").strip()
        if not page_id or not state_id:
            raise AlignmentError(f"{label} requires page_id and state_id")
        if coverage not in {"viewport", "scroll"}:
            raise AlignmentError(f"{label}.coverage must be viewport or scroll")
        key = (page_id, state_id)
        if key in targets:
            raise AlignmentError(f"duplicate required target: {page_id}:{state_id}")
        targets[key] = coverage
    return targets


def required_interactions(result: dict) -> dict[str, dict]:
    raw_interactions = result.get("required_interactions", [])
    if not isinstance(raw_interactions, list):
        raise AlignmentError("required_interactions must be an array")
    interactions: dict[str, dict] = {}
    for index, item in enumerate(raw_interactions):
        label = f"required_interactions[{index}]"
        if not isinstance(item, dict):
            raise AlignmentError(f"{label} must be an object")
        interaction_id = str(item.get("id") or "").strip()
        action = str(item.get("action") or "").strip()
        spec_ref = str(item.get("spec_ref") or "").strip()
        if not interaction_id or not action or not spec_ref:
            raise AlignmentError(f"{label} requires id, action, and spec_ref")
        if interaction_id in interactions:
            raise AlignmentError(f"duplicate required interaction: {interaction_id}")
        source = item.get("from")
        if not isinstance(source, dict) or any(
            not str(source.get(key) or "").strip() for key in ("page_id", "state_id")
        ):
            raise AlignmentError(f"{label}.from requires page_id and state_id")
        expected = item.get("expected")
        if not isinstance(expected, dict) or not isinstance(
            expected.get("app_foreground"), bool
        ):
            raise AlignmentError(f"{label}.expected requires boolean app_foreground")
        if expected["app_foreground"] and any(
            not str(expected.get(key) or "").strip() for key in ("page_id", "state_id")
        ):
            raise AlignmentError(
                f"{label}.expected requires page_id and state_id while app remains foreground"
            )
        interactions[interaction_id] = item
    return interactions


def validate_interaction_checks(
    root: Path,
    result: dict,
    interactions: dict[str, dict],
    current: int,
    latest_visual_verdict: object,
    latest_hap_sha256: str | None,
    status: object,
) -> None:
    raw_checks = result.get("interaction_checks", [])
    if not isinstance(raw_checks, list):
        raise AlignmentError("interaction_checks must be an array")
    if not interactions:
        if raw_checks:
            raise AlignmentError(
                "interaction_checks must be empty when required_interactions is empty"
            )
        return
    if not raw_checks:
        if status == "ALIGNED" or latest_visual_verdict == "ALIGNED":
            raise AlignmentError(
                "visually aligned output requires one check per required interaction"
            )
        return
    if current == 0 or latest_visual_verdict != "ALIGNED" or not latest_hap_sha256:
        raise AlignmentError(
            "interaction checks may run only after the latest candidate is visually aligned"
        )
    checks: dict[str, dict] = {}
    for index, item in enumerate(raw_checks):
        label = f"interaction_checks[{index}]"
        if not isinstance(item, dict):
            raise AlignmentError(f"{label} must be an object")
        interaction_id = str(item.get("id") or "").strip()
        if interaction_id not in interactions:
            raise AlignmentError(f"{label}.id is not declared in required_interactions")
        if interaction_id in checks:
            raise AlignmentError(f"duplicate interaction check: {interaction_id}")
        requirement = interactions[interaction_id]
        if item.get("action") != requirement.get("action"):
            raise AlignmentError(f"{label}.action does not match its requirement")
        if item.get("round") != current:
            raise AlignmentError(f"{label}.round must equal current_round")
        if item.get("hap_sha256") != latest_hap_sha256:
            raise AlignmentError(f"{label}.hap_sha256 does not match the latest HAP")
        check_status = item.get("status")
        if check_status not in INTERACTION_STATUSES:
            raise AlignmentError(f"{label}.status is invalid")
        observed = item.get("observed")
        if not isinstance(observed, dict) or not isinstance(
            observed.get("app_foreground"), bool
        ):
            raise AlignmentError(f"{label}.observed requires boolean app_foreground")
        resolve_file(root, item.get("evidence"), f"{label}.evidence")
        if check_status == "PASSED":
            expected = requirement["expected"]
            if observed.get("app_foreground") != expected.get("app_foreground"):
                raise AlignmentError(f"{label}.observed foreground does not match expected")
            if expected.get("app_foreground") and any(
                observed.get(key) != expected.get(key) for key in ("page_id", "state_id")
            ):
                raise AlignmentError(f"{label}.observed page/state does not match expected")
        checks[interaction_id] = item
    if set(checks) != set(interactions):
        missing = ", ".join(sorted(set(interactions) - set(checks)))
        raise AlignmentError(f"interaction_checks omitted required interactions: {missing}")
    check_statuses = {item["status"] for item in checks.values()}
    if "FAILED" in check_statuses and status != "NEEDS_IMPLEMENTATION_FIX":
        raise AlignmentError(
            "failed interaction check requires top-level NEEDS_IMPLEMENTATION_FIX status"
        )
    elif "BLOCKED" in check_statuses and status != "BLOCKED":
        raise AlignmentError("blocked interaction check requires top-level BLOCKED status")
    elif check_statuses == {"PASSED"} and status != "ALIGNED":
        raise AlignmentError("all passed interaction checks require top-level ALIGNED status")


def validate(root: Path, result: dict) -> dict:
    if result.get("schemaVersion") != 2:
        raise AlignmentError("schemaVersion must equal 2")
    status = result.get("status")
    if status not in STATUSES:
        raise AlignmentError(f"invalid status: {status!r}")
    current = result.get("current_round")
    if not isinstance(current, int) or isinstance(current, bool) or not 0 <= current <= 3:
        raise AlignmentError("current_round must be an integer from 0 through 3")
    if current == 0 and status not in {"NEEDS_IMPLEMENTATION_FIX", "BLOCKED", "FAILED"}:
        raise AlignmentError(f"{status} requires at least one completed comparison round")
    if result.get("max_rounds") != 3:
        raise AlignmentError("max_rounds must equal 3")
    required = required_targets(result)
    interactions = required_interactions(result)
    rounds = result.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != current:
        raise AlignmentError("rounds must contain exactly current_round entries")
    expected = list(range(1, current + 1))
    actual = [item.get("round") if isinstance(item, dict) else None for item in rounds]
    if actual != expected:
        raise AlignmentError("round numbers must be consecutive from 1")
    aligned_history: dict[tuple[str, str], int] = {}
    latest_target_statuses: dict[tuple[str, str], str] = {}
    latest_hap_sha256: str | None = None
    for index, item in enumerate(rounds):
        label = f"rounds[{index}]"
        verdict = item.get("verdict")
        if verdict not in ROUND_VERDICTS:
            raise AlignmentError(f"{label}.verdict is invalid")
        hap = item.get("hap")
        if not isinstance(hap, dict):
            raise AlignmentError(f"{label}.hap must be an object")
        hap_path = resolve_file(root, hap.get("path"), f"{label}.hap.path")
        if hap_path.suffix.lower() not in {".hap", ".hsp"}:
            raise AlignmentError(f"{label}.hap must point to HAP/HSP")
        if hap.get("sha256") != sha256(hap_path):
            raise AlignmentError(f"{label}.hap.sha256 does not match")
        latest_hap_sha256 = str(hap["sha256"])
        capture_round = item.get("capture_round", item.get("round"))
        if not isinstance(capture_round, int) or isinstance(capture_round, bool) or capture_round < item["round"]:
            raise AlignmentError(f"{label}.capture_round must be an integer >= round")
        manifest_path = resolve_file(root, item.get("capture_manifest"), f"{label}.capture_manifest")
        manifest = load_object(manifest_path, f"{label} capture manifest")
        if manifest.get("schema_version") != 2:
            raise AlignmentError(f"{label} capture manifest schema_version must equal 2")
        target_results_raw = item.get("target_results")
        if not isinstance(target_results_raw, list) or len(target_results_raw) != len(required):
            raise AlignmentError(
                f"{label}.target_results must contain exactly one result per required target"
            )
        target_results: dict[tuple[str, str], dict] = {}
        for target_index, target_result in enumerate(target_results_raw):
            target_label = f"{label}.target_results[{target_index}]"
            if not isinstance(target_result, dict):
                raise AlignmentError(f"{target_label} must be an object")
            target_key = (
                str(target_result.get("page_id") or ""),
                str(target_result.get("state_id") or ""),
            )
            if target_key not in required:
                raise AlignmentError(
                    f"{target_label} is not declared in required_targets: "
                    f"{target_key[0]}:{target_key[1]}"
                )
            if target_key in target_results:
                raise AlignmentError(
                    f"{target_label} duplicates {target_key[0]}:{target_key[1]}"
                )
            target_status = target_result.get("status")
            if target_status not in TARGET_STATUSES:
                raise AlignmentError(f"{target_label}.status is invalid")
            if target_status == "ALIGNED_CARRIED":
                carried_from = target_result.get("carried_from_round")
                if (
                    not isinstance(carried_from, int)
                    or isinstance(carried_from, bool)
                    or carried_from != aligned_history.get(target_key)
                    or carried_from >= item["round"]
                ):
                    raise AlignmentError(
                        f"{target_label} must carry the latest prior ALIGNED round"
                    )
                resolve_file(root, target_result.get("regression_score"), f"{target_label}.regression_score")
            target_results[target_key] = target_result
        if set(target_results) != set(required):
            missing = set(required) - set(target_results)
            names = ", ".join(f"{page}:{state}" for page, state in sorted(missing))
            raise AlignmentError(f"{label}.target_results omitted required targets: {names}")
        comparisons = item.get("comparisons")
        if not isinstance(comparisons, list):
            raise AlignmentError(f"{label}.comparisons must be an array")
        targets = manifest.get("targets") if isinstance(manifest.get("targets"), list) else []
        obligations: dict[tuple[str, str], dict[str, set[int] | str]] = {}
        comparison_counts: dict[tuple[str, str], int] = {}
        semantic_regions: dict[tuple[str, str], set[str]] = {}
        representative_regions: dict[tuple[str, str], set[str]] = {}
        representative_counts: dict[tuple[str, str], int] = {}
        for comparison_index, comparison in enumerate(comparisons):
            comparison_label = f"{label}.comparisons[{comparison_index}]"
            if not isinstance(comparison, dict):
                raise AlignmentError(f"{comparison_label} must be an object")
            page_id = comparison.get("page_id")
            state_id = comparison.get("state_id")
            target_key = (str(page_id or ""), str(state_id or ""))
            if target_key not in required:
                raise AlignmentError(
                    f"{comparison_label} is not declared in required_targets: "
                    f"{target_key[0]}:{target_key[1]}"
                )
            target_status = target_results[target_key]["status"]
            if target_status not in {"ALIGNED", "NEEDS_UI_FIX"}:
                raise AlignmentError(
                    f"{comparison_label} cannot attach comparison evidence to {target_status}"
                )
            comparison_counts[target_key] = comparison_counts.get(target_key, 0) + 1
            candidate = next(
                (
                    entry
                    for entry in targets
                    if isinstance(entry, dict)
                    and entry.get("phase") == "harmony-candidate"
                    and entry.get("platform") == "harmony"
                    and entry.get("page_id") == page_id
                    and entry.get("state_id") == state_id
                    and entry.get("round") == capture_round
                    and entry.get("status") == "COMPLETE"
                ),
                None,
            )
            if candidate is None:
                raise AlignmentError(
                    f"{comparison_label} has no matching COMPLETE Harmony manifest entry"
                )
            if candidate.get("observed_variant") != state_id:
                raise AlignmentError(
                    f"{comparison_label} Harmony observed_variant does not match state_id"
                )
            validate_snapshot_files(manifest_path, candidate, f"{comparison_label} Harmony")
            reference = next(
                (
                    entry
                    for entry in targets
                    if isinstance(entry, dict)
                    and entry.get("phase") == "android-reference"
                    and entry.get("platform") == "android"
                    and entry.get("page_id") == page_id
                    and entry.get("state_id") == state_id
                    and entry.get("status") == "COMPLETE"
                ),
                None,
            )
            if reference is None:
                raise AlignmentError(
                    f"{comparison_label} has no matching COMPLETE Android manifest entry"
                )
            if reference.get("observed_variant") != state_id:
                raise AlignmentError(
                    f"{comparison_label} Android observed_variant does not match state_id"
                )
            validate_snapshot_files(manifest_path, reference, f"{comparison_label} Android")
            reference_coverage = entry_coverage(reference)
            candidate_coverage = entry_coverage(candidate)
            requested_coverage = str(
                comparison.get("coverage") or reference_coverage.get("requested") or "viewport"
            )
            if requested_coverage not in {"viewport", "scroll"}:
                raise AlignmentError(f"{comparison_label}.coverage is invalid")
            if requested_coverage != required[target_key]:
                raise AlignmentError(
                    f"{comparison_label}.coverage does not match required target coverage"
                )
            if not coverage_satisfies(reference_coverage, requested_coverage):
                raise AlignmentError(
                    f"{comparison_label} Android {requested_coverage} coverage is incomplete"
                )
            if not coverage_satisfies(candidate_coverage, requested_coverage):
                raise AlignmentError(
                    f"{comparison_label} Harmony {requested_coverage} coverage is incomplete"
                )
            reference_indices = capture_indices(reference)
            candidate_indices = capture_indices(candidate)
            reference_index = comparison.get(
                "reference_capture_index", comparison.get("capture_index", 0)
            )
            candidate_index = comparison.get(
                "candidate_capture_index", comparison.get("capture_index", 0)
            )
            if reference_index not in reference_indices:
                raise AlignmentError(
                    f"{comparison_label}.reference_capture_index is absent from Android evidence"
                )
            if candidate_index not in candidate_indices:
                raise AlignmentError(
                    f"{comparison_label}.candidate_capture_index is absent from Harmony evidence"
                )
            if requested_coverage == "viewport" and (reference_index != 0 or candidate_index != 0):
                raise AlignmentError(
                    f"{comparison_label} viewport comparison must use capture index zero"
                )
            obligation = obligations.setdefault(
                (str(page_id), str(state_id)),
                {
                    "coverage": requested_coverage,
                    "reference_expected": reference_indices,
                    "candidate_expected": candidate_indices,
                    "reference_compared": set(),
                    "candidate_compared": set(),
                },
            )
            if obligation["coverage"] != requested_coverage:
                raise AlignmentError(f"{comparison_label} mixes coverage modes for one state")
            obligation["reference_compared"].add(reference_index)  # type: ignore[union-attr]
            obligation["candidate_compared"].add(candidate_index)  # type: ignore[union-attr]
            resolve_file(root, comparison.get("score"), f"{comparison_label}.score")
            semantic_region = str(comparison.get("semantic_region") or "").strip()
            if not semantic_region:
                raise AlignmentError(f"{comparison_label}.semantic_region must be non-empty")
            semantic_regions.setdefault(target_key, set()).add(semantic_region)
            semantic_value = comparison.get("semantic")
            if semantic_value:
                semantic = resolve_file(root, semantic_value, f"{comparison_label}.semantic")
                semantic_result = load_object(semantic, f"{comparison_label} semantic result")
                if semantic_result.get("status") != "COMPLETE":
                    raise AlignmentError(f"{comparison_label} semantic inspection is not COMPLETE")
                representative_regions.setdefault(target_key, set()).add(semantic_region)
                representative_counts[target_key] = representative_counts.get(target_key, 0) + 1
        for (page_id, state_id), target_result in target_results.items():
            target_key = (page_id, state_id)
            target_status = target_result["status"]
            if target_status in {"ALIGNED", "NEEDS_UI_FIX"} and not comparison_counts.get(target_key):
                raise AlignmentError(
                    f"{label} {page_id}:{state_id} {target_status} requires comparison evidence"
                )
            if target_status not in {"ALIGNED", "NEEDS_UI_FIX"}:
                continue
            obligation = obligations.get(target_key)
            if not obligation:
                raise AlignmentError(f"{label} {page_id}:{state_id} lacks viewport obligations")
            representative_count = representative_counts.get(target_key, 0)
            if obligation["coverage"] == "scroll":
                if obligation["reference_compared"] != obligation["reference_expected"]:
                    raise AlignmentError(
                        f"round {item['round']} {page_id}:{state_id} did not compare every "
                        "Android scroll viewport"
                    )
                if obligation["candidate_compared"] != obligation["candidate_expected"]:
                    raise AlignmentError(
                        f"round {item['round']} {page_id}:{state_id} did not compare every "
                        "Harmony scroll viewport"
                    )
                if not 1 <= representative_count <= 3:
                    raise AlignmentError(
                        f"{label} {page_id}:{state_id} scroll requires 1..3 semantic representatives"
                    )
                uncovered = semantic_regions.get(target_key, set()) - representative_regions.get(
                    target_key, set()
                )
                if uncovered:
                    raise AlignmentError(
                        f"{label} {page_id}:{state_id} semantic regions lack a representative: "
                        + ", ".join(sorted(uncovered))
                    )
            elif representative_count != 1:
                raise AlignmentError(
                    f"{label} {page_id}:{state_id} viewport requires one semantic inspection"
                )
        target_status_values = {entry["status"] for entry in target_results.values()}
        if "CAPTURE_BLOCKED" in target_status_values:
            expected_verdict = "BLOCKED"
        elif "NEEDS_IMPLEMENTATION_FIX" in target_status_values:
            expected_verdict = "INCOMPARABLE"
        elif "NEEDS_UI_FIX" in target_status_values:
            expected_verdict = "NEEDS_UI_FIX"
        else:
            expected_verdict = "ALIGNED"
        if verdict != expected_verdict:
            raise AlignmentError(
                f"{label}.verdict must be {expected_verdict} for its target_results"
            )
        round_issues = item.get("issues", [])
        if not isinstance(round_issues, list) or len(round_issues) > 2:
            raise AlignmentError(f"{label}.issues must contain at most two root-cause issues")
        for target_key, target_result in target_results.items():
            latest_target_statuses[target_key] = target_result["status"]
            if target_result["status"] == "ALIGNED":
                aligned_history[target_key] = item["round"]
    latest = rounds[-1]["verdict"] if rounds else None
    if status == "ALIGNED" and latest != "ALIGNED":
        raise AlignmentError("ALIGNED requires latest round verdict ALIGNED")
    if status == "ALIGNED" and set(latest_target_statuses.values()) - ALIGNED_TARGET_STATUSES:
        raise AlignmentError("ALIGNED requires every latest target result aligned")
    if status == "NEEDS_UI_FIX" and (current != 3 or latest != "NEEDS_UI_FIX"):
        raise AlignmentError("NEEDS_UI_FIX requires round 3 latest verdict NEEDS_UI_FIX")
    validate_interaction_checks(
        root,
        result,
        interactions,
        current,
        latest,
        latest_hap_sha256,
        status,
    )
    if status in {"NEEDS_IMPLEMENTATION_FIX", "BLOCKED", "FAILED"}:
        issues = result.get("issues")
        if not isinstance(issues, list) or not issues:
            raise AlignmentError(f"{status} requires non-empty issues")
        if status == "NEEDS_IMPLEMENTATION_FIX":
            for index, issue in enumerate(issues):
                if not isinstance(issue, dict) or issue.get("owner") not in {
                    "lean",
                    "resource",
                }:
                    raise AlignmentError(
                        f"issues[{index}].owner must be lean or resource for implementation fixes"
                    )
    return {
        "status": status,
        "current_round": current,
        "max_rounds": 3,
        "required_target_count": len(required),
        "required_interaction_count": len(interactions),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    root = Path(args.target_root).expanduser().resolve()
    result_path = Path(args.result).expanduser().resolve()
    try:
        result = load_object(result_path, "alignment result")
        summary = validate(root, result)
    except AlignmentError as exc:
        print(f"ALIGNMENT_RESULT_INVALID: {exc}", file=sys.stderr)
        return 1
    print("ALIGNMENT_RESULT_VALID " + json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit("Use the managed lean_worker.py entry point; this is a private library.")
