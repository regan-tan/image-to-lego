"""Run the local-only M13B matched no-wedge objective experiment."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# ruff: noqa: E402
from app.conversion import benchmark, core  # noqa: E402
from app.conversion.catalogue_silhouette_experiment import (  # noqa: E402
    MAX_VARIABLE_RASTER_PIXELS,
)
from app.conversion.evaluation_alignment import (  # noqa: E402
    compare_frozen_evaluator_parity,
    evaluate_completed_assembly,
    stable_placement_id,
)
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage  # noqa: E402
from app.conversion.m12c_wedge_fidelity_experiment import (  # noqa: E402
    WedgeSolve,
    fixed_frame_score,
    optimise_with_wedge,
    preflight_wedge_candidates,
    validate_completed_arrangement,
)
from app.conversion.m13a_objective_alignment_audit import (  # noqa: E402
    Bounds,
    combined_native_bounds,
    evaluate_shared_bounds,
)
from app.conversion.m13b_iou_objective_experiment import (  # noqa: E402
    FixedFrameReference,
    ViewObjectiveCoefficients,
    derive_coefficients,
    fixed_frame_references,
    integer_proxy_score,
    iou,
    solver_view_weights,
    validate_coefficient_bounds,
)
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)

CASE_IDS = ("duck", "mansion", "realistic-man")
TARGET_PARTS = 24
MAX_PARTS = 60
GRIDS = {
    "duck": core.GridSize(5, 7, 12),
    "mansion": core.GridSize(7, 4, 12),
    "realistic-man": core.GridSize(3, 5, 18),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=CASE_IDS)
    args = parser.parse_args()
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M13B requires the three SHA-256-pinned M7B cases.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = (args.case,) if args.case else CASE_IDS
    records = [_run_case(cases[case_id]) for case_id in selected]
    _write(
        args.output_dir / "summary.json",
        {"schemaVersion": "m13b-iou-proxy-v1", "records": records},
    )
    return 0


def _run_case(case: BenchmarkCase) -> dict[str, object]:
    started = perf_counter()
    source = verify_case_source(case)
    grid = GRIDS[case.case_id]
    _, vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(TARGET_PARTS, case.up_axis), grid
    )
    baseline = convert_fixed_grid(
        source,
        grid_size=grid,
        solver_target_parts=TARGET_PARTS,
        max_parts=MAX_PARTS,
        up_axis=case.up_axis,
        source_evidence_resolution=1,
        shape_aware=True,
    )
    locked = tuple(
        placement
        for placement in baseline.model.placements
        if placement.brick_type.shape != "rectangular"
    )
    required = _required_pixels(baseline.projection_hull_cells)
    fixed = locked_source_profile_coverage(locked) & required
    control = optimise_with_wedge(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        locked_placements=locked,
        protected_empty_cells=baseline.protected_empty_cells,
        fixed_coverage_pixels=fixed,
        max_parts=MAX_PARTS,
        include_wedges=False,
    )
    if not control.placements:
        return _not_run_record(case, control.fallback_reason, perf_counter() - started)
    references = fixed_frame_references(
        vertices, faces, control.placements, tuple(baseline.projection_hull_cells)
    )
    coefficients = derive_coefficients(references)
    rectangles, _, preflight = preflight_wedge_candidates(
        target_cells=baseline.projection_hull_cells,
        protected_empty_cells=baseline.protected_empty_cells,
        locked_placements=locked,
    )
    validate_coefficient_bounds(
        coefficients,
        maximum_raster_pixels=MAX_VARIABLE_RASTER_PIXELS,
        candidate_count=len(rectangles),
    )
    proxy = optimise_with_wedge(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        locked_placements=locked,
        protected_empty_cells=baseline.protected_empty_cells,
        fixed_coverage_pixels=fixed,
        max_parts=MAX_PARTS,
        include_wedges=False,
        view_objective_weights=solver_view_weights(coefficients),
    )
    shared_bounds = combined_native_bounds(vertices, control.placements, proxy.placements)
    return {
        "schemaVersion": "m13b-iou-proxy-v1",
        "caseId": case.case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "configuration": {
            "upAxis": case.up_axis.value,
            "sourceEvidenceResolution": 1,
            "targetParts": TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "grid": asdict(grid),
            "wedge41769aEnabled": False,
            "candidateCount": len(rectangles),
            "candidatePreflight": {
                "controlCandidateCount": preflight.control_candidate_count,
                "status": preflight.status,
            },
        },
        "reference": {
            "views": {view: asdict(references[view]) for view in references},
            "coefficientScale": 1_000_000,
            "rounding": "integer half-up",
            "coefficients": {view: asdict(coefficients[view]) for view in coefficients},
        },
        "control": _solution_record(
            control,
            vertices,
            faces,
            baseline.projection_hull_cells,
            baseline.protected_empty_cells,
            references,
            coefficients,
            shared_bounds,
        ),
        "iouProxy": _solution_record(
            proxy,
            vertices,
            faces,
            baseline.projection_hull_cells,
            baseline.protected_empty_cells,
            references,
            coefficients,
            shared_bounds,
        ),
        "totalRuntimeSeconds": perf_counter() - started,
    }


def _solution_record(
    solve: WedgeSolve,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    target: frozenset[core.GridPosition],
    protected: frozenset[core.GridPosition],
    references: Mapping[str, FixedFrameReference],
    coefficients: Mapping[str, ViewObjectiveCoefficients],
    shared_bounds: Mapping[str, Bounds],
) -> dict[str, object]:
    placements = solve.placements
    result: dict[str, object] = {
        "status": solve.status,
        "objectiveValue": solve.objective_value,
        "bestObjectiveBound": solve.best_objective_bound,
        "optimalityGap": solve.optimality_gap,
        "runtimeSeconds": solve.runtime_seconds,
        "fallbackReason": solve.fallback_reason,
        "placementIds": [stable_placement_id(placement) for placement in placements],
    }
    if not placements:
        return result
    fixed = fixed_frame_score(vertices, faces, placements, target)
    measurements = {view.view: (view.true_positives, view.false_positives) for view in fixed.views}
    fixed_views = [
        {
            "view": view.view,
            "truePositives": view.true_positives,
            "falsePositives": view.false_positives,
            "falseNegatives": references[view.view].source_foreground - view.true_positives,
            "iou": iou(
                view.true_positives,
                view.false_positives,
                references[view.view].source_foreground,
            ),
        }
        for view in fixed.views
    ]
    fixed_mean_iou = (
        sum(
            iou(
                view.true_positives,
                view.false_positives,
                references[view.view].source_foreground,
            )
            for view in fixed.views
        )
        / 3
    )
    mechanical = validate_completed_arrangement(placements, protected, MAX_PARTS)
    result.update(
        {
            "rawTpMinusFp": fixed.score,
            "iouAwareLinearProxy": integer_proxy_score(references, coefficients, measurements),
            "fixedFrame": {
                "views": fixed_views,
                "meanIou": fixed_mean_iou,
            },
            "frozenSilhouetteV1": asdict(evaluate_completed_assembly(vertices, faces, placements)),
            "sharedBounds": asdict(
                evaluate_shared_bounds(vertices, faces, placements, shared_bounds)
            ),
            "evaluatorParity": asdict(compare_frozen_evaluator_parity(vertices, faces, placements)),
            "partCount": len(placements),
            "connectedComponents": len(mechanical.connected_components),
            "unsupportedPlacements": len(mechanical.unsupported_placement_indices),
            "collisionPairs": len(mechanical.collision_pairs),
            "invalidInterfaces": len(mechanical.invalid_interface_pairs),
            "protectedSpaceViolations": len(mechanical.protected_space_violations),
        }
    )
    return result


def _not_run_record(case: BenchmarkCase, reason: str | None, runtime: float) -> dict[str, object]:
    return {
        "schemaVersion": "m13b-iou-proxy-v1",
        "caseId": case.case_id,
        "fallbackReason": reason,
        "totalRuntimeSeconds": runtime,
    }


def _required_pixels(cells: frozenset[core.GridPosition]) -> frozenset[tuple[str, int, int]]:
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
