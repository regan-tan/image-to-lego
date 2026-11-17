"""Run the private, offline-only M9A baseline-feasibility experiment."""

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
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.conversion.catalogue_silhouette_experiment import (
    optimise_catalogue_silhouette,  # noqa: E402
)
from app.conversion.evaluation_alignment import (  # noqa: E402
    compare_frozen_evaluator_parity,
    evaluate_completed_assembly,
    fixed_frame_iou,
    fixed_frame_surrogate_score,
    stable_placement_id,
    verify_baseline_feasibility,
)
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage  # noqa: E402
from app.conversion.physical_geometry import colliding_placement_pairs  # noqa: E402
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)

SCHEMA_VERSION = "m9a-experimental-feasibility-v1"
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
    arguments = parser.parse_args()
    cases = {case.case_id: case for case in load_manifest(arguments.manifest).cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M9A requires exactly the three SHA-256-pinned M7B cases.")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    selected = (arguments.case,) if arguments.case else CASE_IDS
    records = [_run_case(cases[case_id], arguments.output_dir) for case_id in selected]
    summary = {"schemaVersion": SCHEMA_VERSION, "records": records}
    _write(arguments.output_dir / "summary.json", summary)
    return 0


def _run_case(case: BenchmarkCase, output_dir: Path) -> dict[str, object]:
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
    placements = baseline.model.placements
    locked = tuple(part for part in placements if part.brick_type.shape != "rectangular")
    required = _required_pixels(baseline.projection_hull_cells)
    fixed_coverage = locked_source_profile_coverage(locked) & required
    feasibility = verify_baseline_feasibility(
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        protected_empty_cells=baseline.protected_empty_cells,
        baseline_placements=placements,
        locked_projection_cells=tuple(
            cell for placement in locked for cell in core._placement_source_cells(placement)
        ),
        fixed_coverage_pixels=fixed_coverage,
        max_parts=MAX_PARTS,
    )
    solved = optimise_catalogue_silhouette(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        locked_placements=locked,
        fixed_coverage_pixels=fixed_coverage,
        max_parts=MAX_PARTS,
        target_parts=TARGET_PARTS,
    )
    record: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": case.case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "configuration": {
            "upAxis": case.up_axis.value,
            "sourceEvidenceResolution": 1,
            "targetParts": TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "grid": asdict(grid),
        },
        "coverage": {
            "requiredWitnessCount": len(required),
            "fixedLockedProfileWitnessCount": len(fixed_coverage),
            "remainingRectangleWitnessCount": len(required - fixed_coverage),
        },
        "baseline": _arrangement_record(
            vertices,
            faces,
            placements,
            baseline.protected_empty_cells,
            baseline.projection_hull_cells,
        ),
        "baselineFeasibility": asdict(feasibility),
        "solver": {
            "candidateCount": solved.candidate_count,
            "pixelEquivalenceGroupCount": solved.variable_pixel_count,
            "status": solved.status,
            "objectiveValue": solved.objective_value,
            "bestObjectiveBound": solved.best_objective_bound,
            "optimalityGap": solved.optimality_gap,
            "runtimeSeconds": solved.runtime_seconds,
            "fallbackReason": solved.fallback_reason,
            "placementIds": [stable_placement_id(item) for item in solved.placements],
        },
        "optimised": _arrangement_record(
            vertices,
            faces,
            solved.placements,
            baseline.protected_empty_cells,
            baseline.projection_hull_cells,
        )
        if solved.placements
        else None,
        "totalRuntimeSeconds": perf_counter() - started,
    }
    _write(output_dir / f"{case.case_id}.json", record)
    return record


def _arrangement_record(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    placements: tuple[core.BrickPlacement, ...],
    protected: frozenset[core.GridPosition],
    target: frozenset[core.GridPosition],
) -> dict[str, object]:
    cells = {cell for placement in placements for cell in core._placement_source_cells(placement)}
    buildability = analyze_buildability(placements)
    return {
        "placementIds": [stable_placement_id(item) for item in placements],
        "fixedFrameTpMinusFp": fixed_frame_surrogate_score(vertices, faces, placements, target),
        "fixedFrameIou": fixed_frame_iou(vertices, faces, placements, target),
        "frozenSilhouetteV1": asdict(evaluate_completed_assembly(vertices, faces, placements)),
        "evaluatorParity": asdict(compare_frozen_evaluator_parity(vertices, faces, placements)),
        "mechanicalValidation": {
            "collisionPairs": len(colliding_placement_pairs(placements)),
            "unsupportedPlacements": buildability.unsupported_placement_count,
            "connectedComponents": buildability.connected_component_count,
            "protectedSpaceViolations": len(cells & protected),
            "partCapSatisfied": len(placements) <= MAX_PARTS,
        },
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
