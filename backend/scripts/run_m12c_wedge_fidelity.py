"""Run the local-only M12C Control A / wedge 41769a comparison."""

from __future__ import annotations

import argparse
import json
import sys
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
    CatalogueSilhouetteSolve,
    optimise_catalogue_silhouette,
)
from app.conversion.evaluation_alignment import (  # noqa: E402
    compare_frozen_evaluator_parity,
    evaluate_completed_assembly,
    fixed_frame_iou,
    fixed_frame_surrogate_score,
)
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage  # noqa: E402
from app.conversion.m12c_wedge_fidelity_experiment import (  # noqa: E402
    WedgeAssemblyReport,
    WedgeSolve,
    fixed_frame_score,
    optimise_with_wedge,
    preflight_wedge_candidates,
    validate_completed_arrangement,
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
        raise ValueError("M12C requires the three SHA-256-pinned M7B cases.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = (args.case,) if args.case else CASE_IDS
    records = [_run_case(cases[case_id]) for case_id in selected]
    _write(
        args.output_dir / "summary.json",
        {"schemaVersion": "m12c-wedge-fidelity-v1", "records": records},
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
        item for item in baseline.model.placements if item.brick_type.shape != "rectangular"
    )
    required = _required_pixels(baseline.projection_hull_cells)
    fixed = locked_source_profile_coverage(locked) & required
    control = optimise_catalogue_silhouette(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        locked_placements=locked,
        fixed_coverage_pixels=fixed,
        max_parts=MAX_PARTS,
        target_parts=TARGET_PARTS,
    )
    matched_control = optimise_with_wedge(
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
    rectangles, wedges, preflight = preflight_wedge_candidates(
        target_cells=baseline.projection_hull_cells,
        protected_empty_cells=baseline.protected_empty_cells,
        locked_placements=locked,
    )
    experiment = optimise_with_wedge(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        locked_placements=locked,
        protected_empty_cells=baseline.protected_empty_cells,
        fixed_coverage_pixels=fixed,
        max_parts=MAX_PARTS,
    )
    return {
        "schemaVersion": "m12c-wedge-fidelity-v1",
        "caseId": case.case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "configuration": {
            "upAxis": case.up_axis.value,
            "sourceEvidenceResolution": 1,
            "targetParts": TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "grid": asdict(grid),
        },
        "preflight": {
            **asdict(preflight),
            "controlCandidateCountRebuilt": len(rectangles),
            "eligibleWedgeCountRebuilt": len(wedges),
        },
        "control": _solve_record(
            control,
            vertices,
            faces,
            baseline.projection_hull_cells,
            candidate_count=control.candidate_count,
            locked_count=len(locked),
        ),
        "matchedControl": _solve_record(
            matched_control,
            vertices,
            faces,
            baseline.projection_hull_cells,
            baseline.protected_empty_cells,
            candidate_count=len(rectangles),
            locked_count=len(locked),
        ),
        "experiment": _solve_record(
            experiment,
            vertices,
            faces,
            baseline.projection_hull_cells,
            baseline.protected_empty_cells,
            candidate_count=preflight.total_candidate_count,
            locked_count=len(locked),
        ),
        "totalRuntimeSeconds": perf_counter() - started,
    }


def _solve_record(
    solve: CatalogueSilhouetteSolve | WedgeSolve,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    target: frozenset[core.GridPosition],
    protected: frozenset[core.GridPosition] = frozenset(),
    candidate_count: int | None = None,
    locked_count: int = 0,
) -> dict[str, object]:
    placements = solve.placements
    result: dict[str, object] = {
        "status": solve.status,
        "objectiveValue": solve.objective_value,
        "bestObjectiveBound": solve.best_objective_bound,
        "optimalityGap": solve.optimality_gap,
        "runtimeSeconds": solve.runtime_seconds,
        "fallbackReason": solve.fallback_reason,
        "partCount": len(placements),
        "wedgeCount": sum(item.brick_type.part_id == "41769" for item in placements),
        "mechanicallyAccepted": solve.fallback_reason != "post_solve_validation_failed",
    }
    if isinstance(solve, WedgeSolve) and solve.rejected_validation is not None:
        result["rejectedSelection"] = _rejected_selection_record(
            solve.rejected_placements, solve.rejected_validation
        )
    if solve.objective_value is not None and candidate_count is not None:
        selected_count = len(placements) - locked_count
        numerator = solve.objective_value + selected_count
        denominator = candidate_count + 1
        if numerator % denominator == 0:
            result["solverImpliedTpMinusFp"] = numerator // denominator
        else:
            result["solverImpliedTpMinusFp"] = None
    if not placements:
        return result
    # Retain the historical helper for no-wedge reference only. M12C's
    # geometry-aware value is the one comparable to its solver objective.
    result["legacyFixedFrameTpMinusFp"] = fixed_frame_surrogate_score(
        vertices, faces, placements, target
    )
    result["legacyFixedFrameIou"] = fixed_frame_iou(vertices, faces, placements, target)
    result["m12cFixedFrameScore"] = asdict(fixed_frame_score(vertices, faces, placements, target))
    result["frozenSilhouetteV1"] = asdict(evaluate_completed_assembly(vertices, faces, placements))
    result["evaluatorParity"] = asdict(compare_frozen_evaluator_parity(vertices, faces, placements))
    result["mechanicalValidation"] = asdict(
        validate_completed_arrangement(placements, protected, MAX_PARTS)
    )
    return result


def _rejected_selection_record(
    placements: tuple[core.BrickPlacement, ...], validation: WedgeAssemblyReport
) -> dict[str, object]:
    items = tuple(_placement_record(index, placement) for index, placement in enumerate(placements))
    return {
        "placementIds": [item["id"] for item in items],
        "placements": items,
        "wedgePlacements": [item for item in items if item["partId"] == "41769"],
        "validation": asdict(validation),
        "collisionPairs": _pair_records(validation.collision_pairs, items, "body_collision"),
        "unsupportedPlacements": [
            {
                "placement": items[index],
                "reason": "no selected direct verified supporter or ground support",
            }
            for index in validation.unsupported_placement_indices
        ],
        "invalidInterfacePairs": _pair_records(
            validation.invalid_interface_pairs, items, "unverified_contact"
        ),
        "protectedSpaceViolations": [
            items[index] for index in validation.protected_space_violations
        ],
        "connectedComponentCount": len(validation.connected_components),
        "isolatedPlacementCount": len(validation.isolated_placement_indices),
        "failedPredicates": _failed_predicates(validation),
    }


def _placement_record(index: int, placement: core.BrickPlacement) -> dict[str, object]:
    position = placement.position
    placement_id = (
        f"{placement.brick_type.part_id}@{position.x},{position.y},{position.z}:"
        f"{placement.orientation_degrees}"
    )
    return {
        "index": index,
        "id": placement_id,
        "partId": placement.brick_type.part_id,
        "shape": placement.brick_type.shape,
        "position": {"x": position.x, "y": position.y, "z": position.z},
        "orientationDegrees": placement.orientation_degrees,
    }


def _pair_records(
    pairs: tuple[tuple[int, int], ...],
    placements: tuple[dict[str, object], ...],
    reason: str,
) -> list[dict[str, object]]:
    return [
        {"first": placements[first], "second": placements[second], "reason": reason}
        for first, second in pairs
    ]


def _failed_predicates(validation: WedgeAssemblyReport) -> list[str]:
    failed: list[str] = []
    if validation.collision_pairs:
        failed.append("collision_pairs")
    if validation.unsupported_placement_indices:
        failed.append("unsupported_placements")
    if validation.protected_space_violations:
        failed.append("protected_space_violations")
    if validation.invalid_interface_pairs:
        failed.append("invalid_interface_pairs")
    if not validation.part_cap_satisfied:
        failed.append("part_cap")
    return failed


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
