"""Run the bounded, offline-only M8B fidelity-attribution experiment.

The runner is intentionally disconnected from FastAPI, workers, and
``convert_glb``.  It writes only hashes, metrics, and overlays beneath the
ignored artifacts directory; it never copies private source bytes or paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.conversion.fidelity import render_silhouette_masks  # noqa: E402
from app.conversion.fidelity_attribution import (  # noqa: E402
    score_cell_occupancy,
    source_surface_cells,
)
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.physical_geometry import colliding_placement_pairs  # noqa: E402
from app.conversion.real_world_benchmark import load_manifest, verify_case_source  # noqa: E402

SCHEMA_VERSION = "m8b-fidelity-attribution-v1"
CASE_IDS = ("duck", "mansion", "realistic-man")
TARGET_PARTS = 24
MAX_PARTS = 60
FIXED_GRIDS = {
    "duck": core.GridSize(5, 7, 12),
    "mansion": core.GridSize(7, 4, 12),
    "realistic-man": core.GridSize(3, 5, 18),
}
MAX_CASE_SECONDS = 180.0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=CASE_IDS)
    parser.add_argument("--summarize-existing", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        result = (
            summarize_existing(arguments.output_dir)
            if arguments.summarize_existing
            else run_experiment(arguments.manifest, arguments.output_dir, case_id=arguments.case)
        )
    except (OSError, ValueError, core.ConversionError) as error:
        print(f"Experiment validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "records": len(result["records"])}, indent=2))
    return 0


def run_experiment(
    manifest_path: Path, output_dir: Path, *, case_id: str | None = None
) -> dict[str, object]:
    manifest = load_manifest(manifest_path)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M8B manifest must contain exactly duck, mansion, and realistic-man.")
    if any(case.target_parts != TARGET_PARTS for case in cases.values()):
        raise ValueError("M8B manifest targetParts must be 24 for every source.")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_case_ids = (case_id,) if case_id else CASE_IDS
    records = []
    for selected_case_id in selected_case_ids:
        case = cases[selected_case_id]
        record = _run_case(
            verify_case_source(case),
            selected_case_id,
            case.up_axis,
            FIXED_GRIDS[selected_case_id],
            output_dir,
        )
        records.append(record)
        _write_json(output_dir / f"{selected_case_id}.json", record)
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "completed",
        "controls": {
            "targetParts": TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "silhouetteVersion": "silhouette-v1",
            "latticeDimensions": "8 mm x 8 mm x 3.2 mm",
            "caseBudgetSeconds": MAX_CASE_SECONDS,
        },
        "records": records,
    }
    _write_json(output_dir / "summary.json", result)
    return result


def summarize_existing(output_dir: Path) -> dict[str, object]:
    """Rebuild the combined report without rereading private source bytes."""
    records: list[dict[str, object]] = []
    for case_id in CASE_IDS:
        path = output_dir / f"{case_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("caseId") != case_id:
            raise ValueError(f"M8B record {path.name} is missing or invalid.")
        if payload.get("schemaVersion") != SCHEMA_VERSION:
            raise ValueError(f"M8B record {path.name} has an unexpected schema version.")
        records.append(payload)
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "completed",
        "controls": {
            "targetParts": TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "silhouetteVersion": "silhouette-v1",
            "latticeDimensions": "8 mm x 8 mm x 3.2 mm",
            "caseBudgetSeconds": MAX_CASE_SECONDS,
        },
        "records": records,
    }
    _write_json(output_dir / "summary.json", result)
    return result


def _run_case(
    source: bytes, case_id: str, up_axis: core.Axis, grid: core.GridSize, output_dir: Path
) -> dict[str, object]:
    started = perf_counter()
    mesh, vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(TARGET_PARTS, up_axis), grid
    )
    source_cells, watertight = source_surface_cells(source, grid_size=grid, up_axis=up_axis)
    stage_b = score_cell_occupancy(vertices, faces, source_cells)
    # This is a controlled representation diagnostic, not a second optimiser:
    # it shows the visible effect of V6's mandatory projection-hull witness set.
    fixed = convert_fixed_grid(
        source,
        grid_size=grid,
        solver_target_parts=TARGET_PARTS,
        max_parts=MAX_PARTS,
        up_axis=up_axis,
        shape_aware=True,
    )
    hull = score_cell_occupancy(vertices, faces, fixed.projection_hull_cells)
    model = fixed.model
    masks = render_silhouette_masks(
        vertices,
        faces,
        core._placement_boxes(model.placements),
        slope_vertices=core._slope_vertices(model.placements),
        wedge_vertices=core._wedge_vertices(model.placements),
    )
    for view, (source_mask, model_mask) in masks.items():
        benchmark.make_overlay(source_mask, model_mask).save(
            output_dir / f"{case_id}-v6-{view}.png"
        )
    diagnostics = model.metadata.diagnostics
    assert diagnostics is not None
    buildability = analyze_buildability(model.placements)
    elapsed = round(perf_counter() - started, 6)
    status = "completed" if elapsed <= MAX_CASE_SECONDS else "budget_exceeded_after_completion"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "source": {
            "triangleCount": len(faces),
            "watertight": bool(mesh.is_watertight and watertight),
        },
        "grid": _grid_record(grid),
        "stageAOriginal": {"kind": "reference mesh", "occupiedCells": None},
        "stageBIdealizedCells": {
            "feasibleSet": (
                "one coherent set of independent 1x1x1 lattice cells; no LEGO parts or mechanics"
            ),
            "surrogate": (
                "V6-aligned source surface voxelisation; deterministic feasible "
                "approximation, not an optimum proof"
            ),
            "occupiedCells": len(source_cells),
            "actualParts": None,
            "silhouetteV1": asdict(stage_b),
        },
        "projectionHullDiagnostic": {
            "feasibleSet": (
                "V6 projection-hull witness cells rendered as independent cells; "
                "no packing or mechanics"
            ),
            "occupiedCells": len(fixed.projection_hull_cells),
            "silhouetteV1": asdict(hull),
        },
        "stageCCatalogueConstrained": {
            "feasibleSet": (
                "existing V6 candidate catalogue, orientations, collision exclusion, "
                "reachability, support repair, protected-empty logic, 60-part cap, "
                "and mandatory projection coverage"
            ),
            "candidateCounts": {
                "beforeProtection": diagnostics.candidate_count_before_protection,
                "afterProtection": diagnostics.candidate_count_after_protection,
                "afterReachability": diagnostics.candidate_count_after_reachability_pruning,
            },
            "solver": _solver_record(diagnostics),
            "ablation": (
                "Direct source-mesh silhouette optimisation over the catalogue is not "
                "implemented; therefore this is not a catalogue fidelity upper bound."
            ),
        },
        "stageDActualV6": {
            "actualParts": model.part_count,
            "occupiedCells": len(
                {
                    cell
                    for placement in model.placements
                    for cell in core._placement_cells(placement)
                }
            ),
            "silhouetteV1": _model_silhouette(model),
            "safeguards": {
                "collisionPairs": len(colliding_placement_pairs(model.placements)),
                "unsupportedEvaluatedPlacements": buildability.unsupported_placement_count,
                "connectedComponents": buildability.connected_component_count,
            },
        },
        "runtimeSeconds": elapsed,
        "failureReason": None
        if status == "completed"
        else "case budget exceeded after V6 completed",
    }


def _solver_record(diagnostics: core.ConversionDiagnostics) -> dict[str, object]:
    return {
        "stageOne": diagnostics.stage_one_status,
        "stageTwo": diagnostics.stage_two_status,
        "optimality": (
            "Only stage one reports OPTIMAL in V6; stage two FEASIBLE is a bounded "
            "incumbent, not an optimality proof."
        ),
    }


def _model_silhouette(model: core.LegoModel) -> dict[str, float]:
    fidelity = model.metadata.fidelity
    return {
        "front": fidelity.front_iou,
        "side": fidelity.side_iou,
        "top": fidelity.top_iou,
        "mean": fidelity.mean_iou,
    }


def _grid_record(grid: core.GridSize) -> dict[str, object]:
    return {
        "widthStuds": grid.width_studs,
        "depthStuds": grid.depth_studs,
        "heightPlates": grid.height_plates,
        "physicalEnvelopeMm": {
            "width": grid.width_studs * core.STUD_WIDTH_MM,
            "depth": grid.depth_studs * core.STUD_WIDTH_MM,
            "height": grid.height_plates * core.PLATE_HEIGHT_MM,
        },
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
