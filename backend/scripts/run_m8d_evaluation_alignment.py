"""Run the private, offline-only M8D evaluation-alignment experiment."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.catalogue_silhouette_experiment import (  # noqa: E402
    optimise_catalogue_silhouette,
)
from app.conversion.evaluation_alignment import (  # noqa: E402
    compare_frozen_evaluator_parity,
    evaluate_completed_assembly,
    fixed_frame_surrogate_score,
    stable_placement_id,
    verify_baseline_feasibility,
)
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
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
    arguments = parser.parse_args()
    cases = {case.case_id: case for case in load_manifest(arguments.manifest).cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M8D requires exactly the three SHA-256-pinned M7B cases.")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    case_ids = (arguments.case,) if arguments.case else CASE_IDS
    records = [_run_case(cases[case_id], arguments.output_dir) for case_id in case_ids]
    _write(arguments.output_dir / "summary.json", {"schemaVersion": "m8d-v1", "records": records})
    return 0


def _run_case(case: BenchmarkCase, output_dir: Path) -> dict[str, object]:
    source = verify_case_source(case)
    case_id = case.case_id
    grid = GRIDS[case_id]
    _, vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(TARGET_PARTS, case.up_axis), grid
    )
    baseline = convert_fixed_grid(
        source,
        grid_size=grid,
        solver_target_parts=TARGET_PARTS,
        max_parts=MAX_PARTS,
        up_axis=case.up_axis,
        shape_aware=True,
    )
    required = _required_pixels(baseline.projection_hull_cells)
    feasibility = verify_baseline_feasibility(
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        protected_empty_cells=baseline.protected_empty_cells,
        baseline_placements=baseline.model.placements,
        locked_projection_cells=tuple(
            cell
            for placement in baseline.model.placements
            if placement.brick_type.shape != "rectangular"
            for cell in core._placement_source_cells(placement)
        ),
        max_parts=MAX_PARTS,
    )
    locked = tuple(
        placement
        for placement in baseline.model.placements
        if placement.brick_type.shape != "rectangular"
    )
    solved = optimise_catalogue_silhouette(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=required,
        locked_placements=locked,
        max_parts=MAX_PARTS,
        target_parts=TARGET_PARTS,
    )
    record: dict[str, object] = {
        "schemaVersion": "m8d-v1",
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "grid": asdict(grid),
        "baseline": {
            "placementIds": [stable_placement_id(item) for item in baseline.model.placements],
            "m8cOriginalSurrogate": fixed_frame_surrogate_score(
                vertices, faces, baseline.model.placements, baseline.projection_hull_cells
            ),
            "evaluation": asdict(
                evaluate_completed_assembly(vertices, faces, baseline.model.placements)
            ),
            "evaluatorParity": asdict(
                compare_frozen_evaluator_parity(vertices, faces, baseline.model.placements)
            ),
            "feasibility": asdict(feasibility),
        },
        "m8c": {
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
            "evaluation": asdict(evaluate_completed_assembly(vertices, faces, solved.placements))
            if solved.placements
            else None,
            "evaluatorParity": asdict(
                compare_frozen_evaluator_parity(vertices, faces, solved.placements)
            )
            if solved.placements
            else None,
            "recomputedOriginalSurrogate": fixed_frame_surrogate_score(
                vertices, faces, solved.placements, baseline.projection_hull_cells
            )
            if solved.placements
            else None,
        },
    }
    _write(output_dir / f"{case_id}.json", record)
    return record


def _required_pixels(cells: frozenset[core.GridPosition]) -> frozenset[tuple[str, int, int]]:
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
