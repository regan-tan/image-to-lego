"""Run the private, offline M13C placement reconstruction and mask audit."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# ruff: noqa: E402
from app.conversion import core  # noqa: E402
from app.conversion.m13c_silhouette_equivalence_audit import (  # noqa: E402
    AUDIT_RESULT_JSON_SCHEMA,
    AuditError,
    candidate_coverage_ceiling,
    candidate_preflight_failures,
    compare_mask_triplets,
    m13b_fixed_frame_bounds,
    m13b_no_wedge_candidate_preflight,
    native_comparison_metadata,
    parity_record,
    placement_comparison,
    reconstruct_m13b_preprocessing,
    reconstruct_m13b_target_cells,
    reconstruct_placements,
    render_masks_in_bounds,
    shared_bounds_for_pair,
    stage_b_allowed,
    verify_source_sha256,
)
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)

EXPECTED_CASES = {"duck", "mansion", "realistic-man"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--candidate-ceiling",
        action="store_true",
        help="Opt in to the no-solver Stage B candidate-union coverage audit.",
    )
    args = parser.parse_args()
    if len(args.summary) != len(EXPECTED_CASES):
        parser.error("Pass exactly three --summary paths, one for each completed M13B case.")
    manifest = load_manifest(args.manifest)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != EXPECTED_CASES:
        raise AuditError("The manifest must contain exactly the three SHA-pinned M13B cases.")
    summaries = _load_summaries(args.summary)
    if set(summaries) != EXPECTED_CASES:
        raise AuditError("The summaries must contain exactly one record for each M13B case.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = [
        _audit_case(cases[case_id], summaries[case_id], args.candidate_ceiling)
        for case_id in sorted(EXPECTED_CASES)
    ]
    payload = {
        "schemaVersion": "m13c-silhouette-equivalence-audit-v1",
        "stageA": "PASS" if all(record["stageA"] == "PASS" for record in records) else "FAIL",
        "stageB": _stage_b_status(records, args.candidate_ceiling),
        "candidateCeiling": None,
        "records": records,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "schema.json").write_text(
        json.dumps(AUDIT_RESULT_JSON_SCHEMA, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["stageA"] == "PASS" and payload["stageB"] != "PRECHECK_FAILED" else 1


def _audit_case(
    case: BenchmarkCase, record: dict[str, object], candidate_ceiling_requested: bool
) -> dict[str, object]:
    source = verify_case_source(case)
    source_sha256 = verify_source_sha256(source, record.get("sourceSha256"))
    configuration = _mapping(record.get("configuration"), "configuration")
    if configuration.get("wedge41769aEnabled") is not False:
        raise AuditError(f"{case.case_id} is not a no-wedge M13B record.")
    grid_value = _mapping(configuration.get("grid"), "configuration.grid")
    grid = core.GridSize(
        _int(grid_value.get("width_studs"), "grid.width_studs"),
        _int(grid_value.get("depth_studs"), "grid.depth_studs"),
        _int(grid_value.get("height_plates"), "grid.height_plates"),
    )
    if configuration.get("sourceEvidenceResolution") != 1:
        raise AuditError("M13C only reconstructs M13B's pinned 1x source evidence frame.")
    if configuration.get("upAxis") != case.up_axis.value:
        raise AuditError(f"{case.case_id} summary up axis differs from the pinned manifest.")
    vertices, faces, target_cells = reconstruct_m13b_target_cells(source, grid, case.up_axis)
    control_saved = _mapping(record.get("control"), "control")
    experiment_saved = _mapping(record.get("iouProxy"), "iouProxy")
    control = reconstruct_placements(
        _strings(control_saved.get("placementIds"), "control.placementIds")
    )
    experiment = reconstruct_placements(
        _strings(experiment_saved.get("placementIds"), "iouProxy.placementIds")
    )
    saved_bounds = _shared_bounds(control_saved, experiment_saved)
    control_parity = parity_record(
        vertices, faces, control, target_cells, control_saved, saved_bounds
    )
    experiment_parity = parity_record(
        vertices, faces, experiment, target_cells, experiment_saved, saved_bounds
    )
    base = {
        "caseId": case.case_id,
        "source": {"sha256": source_sha256, "verified": True},
        "placementComparison": placement_comparison(control, experiment),
        "mechanical": {
            "control": _mechanical_summary(control_saved),
            "experiment": _mechanical_summary(experiment_saved),
        },
        "parity": {"control": control_parity, "experiment": experiment_parity},
        "candidateCeiling": None,
        "stageB": {
            "status": "NOT_REQUESTED" if not candidate_ceiling_requested else "BLOCKED_STAGE_A"
        },
    }
    if not stage_b_allowed(control_parity, experiment_parity):
        return {**base, "stageA": "FAIL", "comparison": None}
    computed_bounds = shared_bounds_for_pair(vertices, control, experiment)
    if computed_bounds != saved_bounds:
        raise AuditError(f"{case.case_id} reconstructed pair frame differs from saved M13B bounds.")
    control_masks = render_masks_in_bounds(vertices, faces, control, saved_bounds)
    experiment_masks = render_masks_in_bounds(vertices, faces, experiment, saved_bounds)
    stage_b = (
        _candidate_ceiling_record(
            case.case_id,
            source,
            grid,
            case.up_axis,
            control,
            experiment,
            control_saved,
            configuration,
        )
        if candidate_ceiling_requested
        else {"status": "NOT_REQUESTED", "candidateCeiling": None}
    )
    return {
        **base,
        "stageA": "PASS",
        "candidateCeiling": stage_b["candidateCeiling"],
        "stageB": stage_b,
        "comparison": {
            "sharedFrame": compare_mask_triplets(control_masks, experiment_masks, saved_bounds),
            "nativeFrames": native_comparison_metadata(vertices, faces, control, experiment),
        },
    }


def _candidate_ceiling_record(
    case_id: str,
    source: bytes,
    grid: core.GridSize,
    up_axis: core.Axis,
    control: tuple[core.BrickPlacement, ...],
    experiment: tuple[core.BrickPlacement, ...],
    control_saved: Mapping[str, object],
    configuration: Mapping[str, object],
) -> dict[str, object]:
    """Run Stage B's deterministic preflight and relaxed raster-union calculation."""
    control_locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
    experiment_locked = tuple(item for item in experiment if item.brick_type.shape != "rectangular")
    if [item for item in control_locked] != [item for item in experiment_locked]:
        return {
            "status": "PRECHECK_FAILED",
            "candidateCeiling": None,
            "diagnostics": ["Control and IoU-proxy locked nonrectangular placements differ."],
        }
    preprocessing = reconstruct_m13b_preprocessing(source, grid, up_axis)
    preflight = m13b_no_wedge_candidate_preflight(preprocessing, control_locked)
    preflight_evidence = {
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "grid": {
            "widthStuds": grid.width_studs,
            "depthStuds": grid.depth_studs,
            "heightPlates": grid.height_plates,
        },
        "targetCellCount": len(preprocessing.target_cells),
        "protectedEmptyCellCount": len(preprocessing.protected_empty_cells),
        "initialLockedSlopeCount": len(preprocessing.initial_locked_slope_placements),
        "finalLockedNonrectangularCount": len(control_locked),
        "rawRectangleCount": preflight.raw_rectangle_count,
        "collisionFilteredRectangleCount": preflight.collision_filtered_rectangle_count,
        "supportReachableRectangleCount": preflight.support_reachable_rectangle_count,
        "eligibleWedgeCount": preflight.eligible_wedge_count,
        "combinedCandidateCount": preflight.combined_candidate_count,
        "preflightStatus": preflight.status,
        "expectedHistoricalRectangleCount": configuration.get("candidateCount"),
    }
    if preflight.status != "READY":
        return {
            "status": "PRECHECK_FAILED",
            "candidateCeiling": None,
            "machineReason": "historical_combined_preflight_not_ready",
            "diagnostics": ["Historical combined wedge-plus-rectangle preflight was not READY."],
            "preflight": preflight_evidence,
        }
    preflight_failures = candidate_preflight_failures(
        configuration.get("candidateCount"), preflight.candidates, control
    )
    if preflight_failures:
        return {
            "status": "PRECHECK_FAILED",
            "candidateCeiling": None,
            "machineReason": "historical_rectangle_preflight_mismatch",
            "diagnostics": list(preflight_failures),
            "preflight": preflight_evidence,
        }
    assert preflight.candidate_rasters is not None
    assert preflight.locked_pixels is not None
    assert preflight.source_pixels is not None
    fixed_frame = _mapping(control_saved.get("fixedFrame"), "control.fixedFrame")
    observed_iou = {
        view: _float(_fixed_frame_view(fixed_frame, view).get("iou"), f"fixedFrame.{view}.iou")
        for view in ("front", "side", "top")
    }
    result = candidate_coverage_ceiling(
        preflight.source_pixels,
        preflight.locked_pixels,
        preflight.candidate_rasters,
        observed_iou,
        m13b_fixed_frame_bounds(preprocessing.source_vertices, preprocessing.target_cells),
    )
    result.update(
        {
            "candidateCount": len(preflight.candidates),
            "lockedPlacementCount": len(control_locked),
            "controlCandidateMembership": "verified",
        }
    )
    return {
        "status": "PASS",
        "candidateCeiling": result,
        "preflight": preflight_evidence,
    }


def _stage_b_status(records: list[dict[str, object]], requested: bool) -> str:
    if not requested:
        return "NOT_REQUESTED"
    statuses = {
        stage_b["status"]
        for record in records
        if isinstance((stage_b := record.get("stageB")), dict) and "status" in stage_b
    }
    if "PRECHECK_FAILED" in statuses:
        return "PRECHECK_FAILED"
    if "BLOCKED_STAGE_A" in statuses:
        return "BLOCKED_STAGE_A"
    return "PASS"


def _fixed_frame_view(saved: Mapping[str, object], view: str) -> Mapping[str, object]:
    values = saved.get("views")
    if not isinstance(values, list):
        raise AuditError("control.fixedFrame.views must be a list.")
    for item in values:
        if isinstance(item, Mapping) and item.get("view") == view:
            return item
    raise AuditError(f"control.fixedFrame has no {view} record.")


def _load_summaries(paths: list[Path]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AuditError(f"Cannot read M13B summary {path}: {error}") from error
        root = _mapping(payload, str(path))
        if root.get("schemaVersion") != "m13b-iou-proxy-v1":
            raise AuditError(f"{path} has an unexpected M13B schema version.")
        values = root.get("records")
        if not isinstance(values, list) or len(values) != 1:
            raise AuditError(f"{path} must contain exactly one M13B record.")
        record = _mapping(values[0], f"{path}.records[0]")
        case_id = record.get("caseId")
        if not isinstance(case_id, str) or case_id in records:
            raise AuditError(f"{path} has a missing or duplicate case ID.")
        records[case_id] = record
    return records


def _shared_bounds(
    control: Mapping[str, object], experiment: Mapping[str, object]
) -> dict[str, tuple[float, float, float, float]]:
    control_bounds = _bounds(control)
    experiment_bounds = _bounds(experiment)
    if control_bounds != experiment_bounds:
        raise AuditError("M13B arms do not declare the same shared-frame bounds.")
    return control_bounds


def _bounds(saved: Mapping[str, object]) -> dict[str, tuple[float, float, float, float]]:
    shared = _mapping(saved.get("sharedBounds"), "sharedBounds")
    values = shared.get("bounds")
    if not isinstance(values, list):
        raise AuditError("Saved shared bounds must be a list.")
    result: dict[str, tuple[float, float, float, float]] = {}
    for item in values:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            raise AuditError("Saved shared bounds have an invalid entry.")
        numbers = item[1]
        if not isinstance(numbers, list) or len(numbers) != 4:
            raise AuditError("Saved shared bounds must have four numbers per view.")
        if not all(isinstance(value, (int, float)) for value in numbers):
            raise AuditError("Saved shared bounds must contain numbers.")
        result[item[0]] = cast(
            tuple[float, float, float, float], tuple(float(value) for value in numbers)
        )
    return result


def _mechanical_summary(saved: Mapping[str, object]) -> dict[str, object]:
    return {
        field: saved.get(field)
        for field in (
            "partCount",
            "connectedComponents",
            "collisionPairs",
            "unsupportedPlacements",
            "invalidInterfaces",
            "protectedSpaceViolations",
        )
    }


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} must be an object.")
    return cast(dict[str, object], value)


def _strings(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError(f"{name} must be a list of strings.")
    return value


def _int(value: object, name: str) -> int:
    if not isinstance(value, int):
        raise AuditError(f"{name} must be an integer.")
    return value


def _float(value: object, name: str) -> float:
    if not isinstance(value, (int, float)):
        raise AuditError(f"{name} must be a number.")
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
