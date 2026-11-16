"""Run the offline-only M8C catalogue-constrained silhouette experiment."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.conversion.catalogue_silhouette_experiment import (  # noqa: E402
    optimise_catalogue_silhouette,
)
from app.conversion.fidelity import binary_mask_iou, render_silhouette_masks  # noqa: E402
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.physical_geometry import colliding_placement_pairs  # noqa: E402
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)
from app.conversion.surface_metric_v2 import evaluate_surface_metric_v2  # noqa: E402

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
    manifest = load_manifest(arguments.manifest)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M8C requires the three SHA-256-pinned M7B cases.")
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    selected = (arguments.case,) if arguments.case else CASE_IDS
    records = [_run_case(cases[case_id], arguments.output_dir) for case_id in selected]
    _write(arguments.output_dir / "summary.json", {"schemaVersion": "m8c-v1", "records": records})
    return 0


def _run_case(case: BenchmarkCase, output_dir: Path) -> dict[str, object]:
    case_id = case.case_id
    source = verify_case_source(case)
    grid = GRIDS[case_id]
    mesh, vertices, faces = benchmark.aligned_source_mesh(
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
    solved = optimise_catalogue_silhouette(
        source_vertices=vertices,
        faces=faces,
        target_cells=baseline.projection_hull_cells,
        required_pixels=_required_pixels(baseline.projection_hull_cells),
        locked_placements=tuple(
            placement
            for placement in baseline.model.placements
            if placement.brick_type.shape != "rectangular"
        ),
        max_parts=MAX_PARTS,
        target_parts=TARGET_PARTS,
    )
    experiment = _measurement(vertices, faces, solved.placements, baseline.protected_empty_cells)
    record: dict[str, object] = {
        "schemaVersion": "m8c-v1",
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "grid": asdict(grid),
        "baseline": _measurement(
            vertices, faces, baseline.model.placements, baseline.protected_empty_cells
        ),
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
            },
            "measurement": experiment,
        },
        "source": {"triangleCount": len(faces), "watertight": bool(mesh.is_watertight)},
    }
    _write(output_dir / f"{case_id}.json", record)
    return record


def _required_pixels(cells: frozenset[core.GridPosition]) -> frozenset[tuple[str, int, int]]:
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )


def _measurement(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    placements: tuple[core.BrickPlacement, ...],
    protected: frozenset[core.GridPosition],
) -> dict[str, object]:
    fidelity = core._fidelity_for_placements(vertices, faces, placements, TARGET_PARTS)
    buildability = analyze_buildability(placements)
    surface = evaluate_surface_metric_v2(vertices, faces, placements)
    cells = {cell for placement in placements for cell in core._placement_cells(placement)}
    return {
        "silhouetteV1": asdict(fidelity),
        "surfaceMetricV2": surface.record(),
        "actualParts": len(placements),
        "collisionPairs": len(colliding_placement_pairs(placements)),
        "unsupportedEvaluatedPlacements": buildability.unsupported_placement_count,
        "connectedComponents": buildability.connected_component_count,
        "protectedSpaceViolations": len(cells & protected),
        "falsePixels": _false_pixels(vertices, faces, placements),
    }


def _false_pixels(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    placements: tuple[core.BrickPlacement, ...],
) -> dict[str, object]:
    masks = render_silhouette_masks(
        vertices,
        faces,
        core._placement_boxes(placements),
        slope_vertices=core._slope_vertices(placements),
        wedge_vertices=core._wedge_vertices(placements),
    )
    views: dict[str, object] = {}
    for view, (source, output) in masks.items():
        pairs = tuple(zip(source.get_flattened_data(), output.get_flattened_data(), strict=True))
        views[view] = {
            "iou": binary_mask_iou(source, output),
            "falsePositives": sum(
                bool(output_pixel) and not bool(source_pixel)
                for source_pixel, output_pixel in pairs
            ),
            "falseNegatives": sum(
                bool(source_pixel) and not bool(output_pixel)
                for source_pixel, output_pixel in pairs
            ),
        }
    return views


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
