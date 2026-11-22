"""Run the opt-in, no-solver M13F Duck reconstruction bottleneck audit."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core
from app.conversion.evaluation_alignment import evaluate_completed_assembly, stable_placement_id
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage
from app.conversion.m12c_wedge_fidelity_experiment import (
    _raster_pixels,
    fixed_frame_score,
    validate_completed_arrangement,
)
from app.conversion.m13c_silhouette_equivalence_audit import (
    AuditError,
    candidate_preflight_failures,
    m13b_fixed_frame_bounds,
    m13b_no_wedge_candidate_preflight,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
    verify_source_sha256,
)
from app.conversion.m13e_duck_control_hint_experiment import (
    DUCK_CANDIDATE_COUNT,
    DUCK_CONTROL_VIEWS,
    DUCK_GRID,
    DUCK_MAX_PARTS,
    DUCK_SOURCE_SHA256,
    control_candidate_indices,
)
from app.conversion.m13f_duck_reconstruction_audit import (
    active_restriction_classification,
    candidate_id_hash,
    controlled_ablation_matrix,
    next_generation_proposals,
    projection_hashes,
    static_inventory,
)
from app.conversion.real_world_benchmark import load_manifest, verify_case_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Refusing to overwrite an existing audit output directory.")
    payload = run_audit(args.manifest, args.summary)
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["status"] == "PASS" else 1


def run_audit(manifest_path: Path, summary_path: Path) -> dict[str, object]:
    """Reconstruct the pinned model and return static evidence only."""
    try:
        record = _load_duck_record(summary_path)
        cases = {case.case_id: case for case in load_manifest(manifest_path).cases}
        if set(cases) != {"duck"}:
            raise AuditError("M13F requires a manifest containing only the pinned Duck case.")
        source = verify_case_source(cases["duck"])
        if verify_source_sha256(source, record.get("sourceSha256")) != DUCK_SOURCE_SHA256:
            raise AuditError("Pinned Duck source SHA-256 does not match M13F.")
        configuration = _mapping(record.get("configuration"), "configuration")
        if (
            configuration.get("grid") != DUCK_GRID
            or configuration.get("candidateCount") != DUCK_CANDIDATE_COUNT
            or configuration.get("wedge41769aEnabled") is not False
        ):
            raise AuditError("Historical Duck configuration does not match the pinned M13F model.")
        control = reconstruct_placements(
            _strings(_mapping(record.get("control"), "control").get("placementIds"))
        )
        locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
        preprocessing = reconstruct_m13b_preprocessing(
            source, core.GridSize(**DUCK_GRID), cases["duck"].up_axis
        )
        if tuple(stable_placement_id(item) for item in locked) != tuple(
            stable_placement_id(item) for item in preprocessing.initial_locked_slope_placements
        ):
            raise AuditError("Historical locked placement identity does not match preprocessing.")
        preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
        failures = candidate_preflight_failures(DUCK_CANDIDATE_COUNT, preflight.candidates, control)
        if failures or any(
            value is None
            for value in (
                preflight.candidate_rasters,
                preflight.source_pixels,
                preflight.locked_pixels,
            )
        ):
            raise AuditError(
                "; ".join(failures) or "Duck candidate preflight did not produce rasters."
            )
        assert preflight.candidate_rasters is not None
        assert preflight.source_pixels is not None
        assert preflight.locked_pixels is not None
        control_views = _saved_views(_mapping(record.get("control"), "control"))
        if control_views != DUCK_CONTROL_VIEWS:
            raise AuditError("Historical Duck Control metrics do not match the pinned values.")
        control_indices = control_candidate_indices(
            preflight.candidates,
            [
                stable_placement_id(item)
                for item in control
                if item.brick_type.shape == "rectangular"
            ],
        )
        control_pixels = frozenset(preflight.locked_pixels).union(
            *(preflight.candidate_rasters[index] for index in control_indices)
        )
        fixed = fixed_frame_score(
            preprocessing.source_vertices, preprocessing.faces, control, preprocessing.target_cells
        )
        actual_views = {
            item.view: {
                "truePositives": item.true_positives,
                "falsePositives": item.false_positives,
            }
            for item in fixed.views
        }
        if actual_views != control_views:
            raise AuditError("Control fixed-frame TP/FP parity failed.")
        _, rendered_control, rendered_source = _raster_pixels(
            preprocessing.source_vertices,
            preprocessing.faces,
            (),
            control,
            preprocessing.target_cells,
        )
        if (
            frozenset(rendered_source) != frozenset(preflight.source_pixels)
            or frozenset(rendered_control) != control_pixels
        ):
            raise AuditError(
                "Control candidate-raster union differs from the fixed-frame renderer."
            )
        mechanical = validate_completed_arrangement(
            control, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
        )
        if not mechanical.is_valid:
            raise AuditError("Historical Control failed completed-arrangement validation.")
        inventory = static_inventory(
            candidates=preflight.candidates,
            candidate_rasters=preflight.candidate_rasters,
            source_pixels=preflight.source_pixels,
            locked_pixels=preflight.locked_pixels,
            control_pixels=control_pixels,
            preflight_counts={
                "rawRectangles": preflight.raw_rectangle_count,
                "afterLockedBodyCollision": preflight.collision_filtered_rectangle_count,
                "afterSupportReachability": preflight.support_reachable_rectangle_count,
            },
        )
        inventory["controlPartCapAndConnectivity"] = {
            "maxParts": DUCK_MAX_PARTS,
            "controlPartCount": len(control),
            "unusedPartCapacity": DUCK_MAX_PARTS - len(control),
            "partCapSatisfied": mechanical.part_cap_satisfied,
            "connectedComponentCount": len(mechanical.connected_components),
            "connectivityStatus": "REPORTED_POST_SOLVE_NOT_ENFORCED_BY_HISTORICAL_CP_SAT",
        }
        fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels
        selected_coarse_coverage = frozenset(
            pixel
            for index in control_indices
            for cell in preflight.candidates[index].cells
            for pixel in (
                ("front", cell.x, cell.z),
                ("side", cell.y, cell.z),
                ("top", cell.x, cell.y),
            )
        )
        restrictions = active_restriction_classification()
        restrictions["controlObservedStatus"] = {
            "occupancy": {
                "satisfied": not mechanical.collision_pairs,
                "conflictingPairCount": len(mechanical.collision_pairs),
                "slack": "NOT_A_SCALAR_SLACK_CONSTRAINT",
            },
            "support": {
                "satisfied": not mechanical.unsupported_placement_indices,
                "unsupportedPlacementCount": len(mechanical.unsupported_placement_indices),
            },
            "mandatoryCoarseCoverage": {
                "satisfied": preprocessing.required_pixels
                <= fixed_coverage | selected_coarse_coverage,
                "uncoveredRequirementCount": len(
                    preprocessing.required_pixels - fixed_coverage - selected_coarse_coverage
                ),
                "slack": "NOT_A_SCALAR_SLACK_CONSTRAINT",
            },
            "protectedSpace": {
                "satisfied": not mechanical.protected_space_violations,
                "violationCount": len(mechanical.protected_space_violations),
            },
            "partCap": {
                "satisfied": mechanical.part_cap_satisfied,
                "unusedPartCapacity": DUCK_MAX_PARTS - len(control),
            },
            "lockedGeometry": {
                "status": "FIXED_HISTORICAL_INPUT",
                "importance": "REQUIRES_SEPARATE_ABLATION",
            },
            "partVocabulary": {
                "status": "FIXED_HISTORICAL_INPUT",
                "importance": "REQUIRES_SEPARATE_ABLATION",
            },
        }
        frozen = asdict(
            evaluate_completed_assembly(preprocessing.source_vertices, preprocessing.faces, control)
        )
        return {
            "schemaVersion": "m13f-duck-reconstruction-audit-v1",
            "status": "PASS",
            "solverInvocation": "none",
            "privateOptimizationPerformed": False,
            "provenance": {
                "sourceSha256": sha256(source).hexdigest(),
                "candidateCount": len(preflight.candidates),
                "candidateIdsSha256": candidate_id_hash(preflight.candidates),
                "lockedPlacementIds": [stable_placement_id(item) for item in locked],
                "controlPlacementIdsSha256": sha256(
                    "\n".join(stable_placement_id(item) for item in control).encode()
                ).hexdigest(),
                "fixedFrameBounds": {
                    view: list(bounds)
                    for view, bounds in m13b_fixed_frame_bounds(
                        preprocessing.source_vertices, preprocessing.target_cells
                    ).items()
                },
                "projectionHashes": projection_hashes(
                    source=preflight.source_pixels,
                    locked=preflight.locked_pixels,
                    candidateUnion=frozenset().union(*preflight.candidate_rasters),
                    control=control_pixels,
                    renderedControl=rendered_control,
                ),
            },
            "staticInventory": inventory,
            "controlEvaluation": {
                "fixedFrame": {
                    view: {
                        **metrics,
                        "falseNegatives": sum(pixel[0] == view for pixel in preflight.source_pixels)
                        - metrics["truePositives"],
                    }
                    for view, metrics in control_views.items()
                },
                "frozenSilhouetteV1": frozen,
                "mechanical": asdict(mechanical),
            },
            "activeRestrictionClassification": restrictions,
            "preparedAblations": controlled_ablation_matrix(),
            "candidateVocabularyProposals": next_generation_proposals(),
            "limits": [
                "No CP-SAT model was constructed or solved.",
                "Candidate-union coverage does not prove simultaneous feasibility or causality.",
                (
                    "This audit cannot prove global fixed-frame or frozen silhouette-v1 mean-IoU "
                    "optimality."
                ),
                (
                    "Frozen silhouette-v1 is independently measured for Control only; it is not "
                    "optimized by this audit."
                ),
            ],
        }
    except (AuditError, KeyError, OSError, TypeError, ValueError) as error:
        return {
            "schemaVersion": "m13f-duck-reconstruction-audit-v1",
            "status": "PRECHECK_FAILED",
            "solverInvocation": "none",
            "privateOptimizationPerformed": False,
            "diagnostics": [str(error)],
        }


def _load_duck_record(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records")
    if (
        payload.get("schemaVersion") != "m13b-iou-proxy-v1"
        or not isinstance(records, list)
        or len(records) != 1
    ):
        raise AuditError(f"{path} is not a single-record M13B summary.")
    record = _mapping(records[0], "record")
    if record.get("caseId") != "duck":
        raise AuditError("M13F requires the Duck M13B summary.")
    return record


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} must be an object.")
    return cast(dict[str, object], value)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError("placementIds must be a list of strings.")
    return value


def _saved_views(control: dict[str, object]) -> dict[str, dict[str, int]]:
    fixed = _mapping(control.get("fixedFrame"), "control.fixedFrame")
    values = fixed.get("views")
    if not isinstance(values, list):
        raise AuditError("control.fixedFrame.views must be a list.")
    result: dict[str, dict[str, int]] = {}
    for value in values:
        item = _mapping(value, "control.fixedFrame.views entry")
        view = item.get("view")
        tp, fp = item.get("truePositives"), item.get("falsePositives")
        if not isinstance(view, str) or not isinstance(tp, int) or not isinstance(fp, int):
            raise AuditError("control fixed-frame view is invalid.")
        result[view] = {"truePositives": tp, "falsePositives": fp}
    return result


if __name__ == "__main__":
    raise SystemExit(main())
