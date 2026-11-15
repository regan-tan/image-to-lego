"""Run the private, offline M7B fixed-grid/cap diagnostic experiment.

The output contains hashes and measurements only, never source paths or bytes.
This script is intentionally outside production conversion routing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core  # noqa: E402
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.physical_geometry import colliding_placement_pairs  # noqa: E402
from app.conversion.real_world_benchmark import load_manifest, verify_case_source  # noqa: E402

SCHEMA_VERSION = "m7b-fixed-grid-experiment-v1"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--solver-target-parts", type=int, default=24)
    parser.add_argument("--fixed-grid", action="append", required=True, metavar="CASE=WxDxH")
    parser.add_argument("--cap", action="append", type=int)
    parser.add_argument("--grid-scale", action="append", type=float)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument(
        "--experiment",
        action="append",
        choices=("hard-cap", "grid-resolution"),
        dest="experiments",
    )
    return parser.parse_args()


def _parse_grids(values: list[str]) -> dict[str, core.GridSize]:
    grids: dict[str, core.GridSize] = {}
    for value in values:
        case_id, separator, dimensions = value.partition("=")
        fields = dimensions.lower().split("x")
        if not separator or len(fields) != 3 or not case_id:
            raise ValueError("--fixed-grid must be CASE=WIDTHxDEPTHxHEIGHT.")
        try:
            grid = core.GridSize(*(int(field) for field in fields))
        except ValueError as error:
            raise ValueError("--fixed-grid dimensions must be integers.") from error
        if min(grid.width_studs, grid.depth_studs, grid.height_plates) < 1:
            raise ValueError("--fixed-grid dimensions must be positive.")
        grids[case_id] = grid
    return grids


def _scaled_grid(grid: core.GridSize, scale: float) -> core.GridSize:
    if scale <= 0:
        raise ValueError("--grid-scale must be positive.")
    return core.GridSize(
        max(1, round(grid.width_studs * scale)),
        max(1, round(grid.depth_studs * scale)),
        max(1, round(grid.height_plates * scale)),
    )


def _grid_record(grid: core.GridSize) -> dict[str, object]:
    return {
        "dimensions": {
            "widthStuds": grid.width_studs,
            "depthStuds": grid.depth_studs,
            "heightPlates": grid.height_plates,
        },
        "physicalEnvelopeMm": {
            "width": grid.width_studs * core.STUD_WIDTH_MM,
            "depth": grid.depth_studs * core.STUD_WIDTH_MM,
            "height": grid.height_plates * core.PLATE_HEIGHT_MM,
        },
    }


def _project(cells: frozenset[core.GridPosition]) -> dict[str, set[tuple[int, int]]]:
    return {
        "front": {(cell.x, cell.z) for cell in cells},
        "side": {(cell.y, cell.z) for cell in cells},
        "top": {(cell.x, cell.y) for cell in cells},
    }


def _record_run(
    source: bytes,
    *,
    case_id: str,
    up_axis: core.Axis,
    experiment: str,
    grid: core.GridSize,
    solver_target_parts: int,
    max_parts: int,
) -> dict[str, object]:
    started = perf_counter()
    base: dict[str, object] = {
        "caseId": case_id,
        "experiment": experiment,
        "grid": _grid_record(grid),
        "solverTargetParts": solver_target_parts,
        "maxParts": max_parts,
    }
    try:
        result = convert_fixed_grid(
            source,
            grid_size=grid,
            solver_target_parts=solver_target_parts,
            max_parts=max_parts,
            up_axis=up_axis,
        )
    except (core.ConversionError, ValueError) as error:
        return {
            **base,
            "status": "failed",
            "failureReason": str(error),
            "runtimeSeconds": perf_counter() - started,
        }
    model = result.model
    final_cells = frozenset(
        cell for placement in model.placements for cell in core._placement_source_cells(placement)
    )
    source_projection = _project(result.source_cells)
    final_projection = _project(final_cells)
    buildability = analyze_buildability(model.placements)
    diagnostics = model.metadata.diagnostics
    assert diagnostics is not None
    return {
        **base,
        "status": "completed",
        "runtimeSeconds": perf_counter() - started,
        "actualParts": model.part_count,
        "solverStatus": {
            "stageOne": diagnostics.stage_one_status,
            "stageTwo": diagnostics.stage_two_status,
        },
        "candidateCounts": {
            "beforeProtection": diagnostics.candidate_count_before_protection,
            "afterProtection": diagnostics.candidate_count_after_protection,
            "afterReachabilityPruning": diagnostics.candidate_count_after_reachability_pruning,
        },
        "stageAttribution": {
            "sourceSurfaceOccupancy": len(result.source_cells),
            "projectionHullExpansion": len(result.projection_hull_cells - result.source_cells),
            "eligibleTargetCells": len(result.projection_hull_cells),
            "finalOccupiedCells": len(final_cells),
            "finalOnlyCells": len(final_cells - result.source_cells),
            "protectedEmptyCells": len(result.protected_empty_cells),
            "requiredProjectionPixels": result.required_projection_pixel_count,
            "projectedCoverage": {
                view: {
                    "sourcePixels": len(source_projection[view]),
                    "finalPixels": len(final_projection[view]),
                    "falsePositivePixels": len(final_projection[view] - source_projection[view]),
                    "falseNegativePixels": len(source_projection[view] - final_projection[view]),
                }
                for view in ("front", "side", "top")
            },
        },
        "silhouetteIou": {
            "front": model.metadata.fidelity.front_iou,
            "side": model.metadata.fidelity.side_iou,
            "top": model.metadata.fidelity.top_iou,
            "mean": model.metadata.fidelity.mean_iou,
        },
        "safeguards": {
            "physicalCollisionPairs": len(colliding_placement_pairs(model.placements)),
            "connectedComponents": buildability.connected_component_count,
            "unsupportedEvaluatedPlacements": buildability.unsupported_placement_count,
            "protectedSpaceViolations": sum(
                bool(core._placement_source_cells(placement) & result.protected_empty_cells)
                for placement in model.placements
            ),
        },
    }


def run_experiment(arguments: argparse.Namespace) -> dict[str, object]:
    manifest = load_manifest(arguments.manifest)
    grids = _parse_grids(arguments.fixed_grid)
    selected_cases = tuple(
        case
        for case in manifest.cases
        if arguments.case_ids is None or case.case_id in arguments.case_ids
    )
    if not selected_cases:
        raise ValueError("--case did not select a manifest case.")
    if set(grids) != {case.case_id for case in selected_cases}:
        raise ValueError(
            "--fixed-grid must supply exactly one grid for every selected manifest case."
        )
    caps = sorted(set(arguments.cap or [40, 60, 80]))
    if not caps:
        raise ValueError("At least one --cap is required.")
    records: list[dict[str, object]] = []
    grid_scales = arguments.grid_scale or [0.8, 1.0, 1.2]
    experiments = set(arguments.experiments or ["hard-cap", "grid-resolution"])
    for case in selected_cases:
        source = verify_case_source(case)
        fixed_grid = grids[case.case_id]
        fixed_cap = caps[len(caps) // 2]
        if "hard-cap" in experiments:
            for cap in caps:
                records.append(
                    _record_run(
                        source,
                        case_id=case.case_id,
                        up_axis=case.up_axis,
                        experiment="hard-cap",
                        grid=fixed_grid,
                        solver_target_parts=arguments.solver_target_parts,
                        max_parts=cap,
                    )
                )
        if "grid-resolution" in experiments:
            for scale in grid_scales:
                records.append(
                    _record_run(
                        source,
                        case_id=case.case_id,
                        up_axis=case.up_axis,
                        experiment="grid-resolution",
                        grid=_scaled_grid(fixed_grid, scale),
                        solver_target_parts=arguments.solver_target_parts,
                        max_parts=fixed_cap,
                    )
                )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceHashes": {case.case_id: case.source_sha256 for case in selected_cases},
        "configuration": {
            "solverTargetParts": arguments.solver_target_parts,
            "caps": caps,
            "gridScales": grid_scales,
            "fixedCapForGridSweep": caps[len(caps) // 2],
        },
        "records": records,
        "limitations": [
            "Grid-resolution runs use different physical envelopes; their silhouette IoU is not a "
            "matched-scale distance comparison.",
            "Projection coverage is voxel-grid attribution, while silhouette IoU is measured "
            "against original mesh triangles.",
        ],
    }


def main() -> int:
    arguments = parse_arguments()
    try:
        result = run_experiment(arguments)
    except (ValueError, OSError) as error:
        print(f"Experiment validation failed: {error}", file=sys.stderr)
        return 2
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
