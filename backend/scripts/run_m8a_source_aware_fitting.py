"""Run the private, offline M8A source-aware fitting comparison.

The script deliberately calls the fixed-grid diagnostic seam. It is not
imported by the API, workers, or ``convert_glb`` and writes only measurements,
hashes, and rendered masks below the ignored artifacts directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.conversion.fidelity import render_silhouette_masks  # noqa: E402
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.physical_geometry import colliding_placement_pairs  # noqa: E402
from app.conversion.real_world_benchmark import load_manifest, verify_case_source  # noqa: E402
from app.conversion.surface_metric_v2 import evaluate_surface_metric_v2  # noqa: E402

SCHEMA_VERSION = "m8a-source-aware-fitting-v1"
SOLVER_TARGET_PARTS = 24
MAX_PARTS = 60
SOURCE_EVIDENCE_RESOLUTION = 1
CASE_IDS = ("duck", "mansion", "realistic-man")
FIXED_GRIDS = {
    "duck": core.GridSize(5, 7, 12),
    "mansion": core.GridSize(7, 4, 12),
    "realistic-man": core.GridSize(3, 5, 18),
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=CASE_IDS)
    parser.add_argument("--metric-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--summarize-existing", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        result = (
            summarize_existing(arguments.output_dir)
            if arguments.summarize_existing
            else run_experiment(
                arguments.manifest,
                arguments.output_dir,
                arguments.metric_timeout_seconds,
                case_id=arguments.case,
            )
        )
    except (OSError, ValueError) as error:
        print(f"Experiment validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"]}, indent=2))
    return 0


def run_experiment(
    manifest_path: Path,
    output_dir: Path,
    metric_timeout_seconds: float = 30.0,
    *,
    case_id: str | None = None,
) -> dict[str, object]:
    if metric_timeout_seconds <= 0:
        raise ValueError("--metric-timeout-seconds must be greater than zero.")
    manifest = load_manifest(manifest_path)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M8A manifest must contain exactly duck, mansion, and realistic-man.")
    if any(case.target_parts != SOLVER_TARGET_PARTS for case in cases.values()):
        raise ValueError("M8A manifest targetParts must be 24 for every source.")

    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    selected_case_ids = (case_id,) if case_id is not None else CASE_IDS
    for selected_case_id in selected_case_ids:
        case = cases[selected_case_id]
        source = verify_case_source(case)
        baseline = _record_run(
            source,
            selected_case_id,
            case.up_axis,
            FIXED_GRIDS[selected_case_id],
            False,
            output_dir,
            metric_timeout_seconds,
        )
        prototype = _record_run(
            source,
            selected_case_id,
            case.up_axis,
            FIXED_GRIDS[selected_case_id],
            True,
            output_dir,
            metric_timeout_seconds,
        )
        record: dict[str, object] = {
            "caseId": selected_case_id,
            "sourceSha256": sha256(source).hexdigest(),
            "baseline": baseline,
            "prototype": prototype,
            "placementComparison": _placement_comparison(baseline, prototype),
        }
        records.append(record)
        _write_json(output_dir / f"{selected_case_id}.json", record)

    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "completed",
        "controls": {
            "sourceEvidenceResolution": SOURCE_EVIDENCE_RESOLUTION,
            "solverTargetParts": SOLVER_TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "fixedGrids": {case_id: _grid_record(grid) for case_id, grid in FIXED_GRIDS.items()},
            "baseline": "surface-grid-v6-fixed-lattice-diagnostic",
            "prototype": "source-aware excess-minimization then source-coverage maximization",
        },
        "records": records,
    }
    _write_json(output_dir / "summary.json", result)
    return result


def summarize_existing(output_dir: Path) -> dict[str, object]:
    """Rebuild the canonical summary without reading private source bytes."""
    records: list[dict[str, object]] = []
    for case_id in CASE_IDS:
        path = output_dir / f"{case_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("caseId") != case_id:
            raise ValueError(f"M8A record {path.name} is missing or invalid.")
        if not isinstance(payload.get("baseline"), dict) or not isinstance(
            payload.get("prototype"), dict
        ):
            raise ValueError(f"M8A record {path.name} lacks a paired result.")
        records.append(payload)
    result: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "completed",
        "controls": {
            "sourceEvidenceResolution": SOURCE_EVIDENCE_RESOLUTION,
            "solverTargetParts": SOLVER_TARGET_PARTS,
            "maxParts": MAX_PARTS,
            "fixedGrids": {case_id: _grid_record(grid) for case_id, grid in FIXED_GRIDS.items()},
            "baseline": "surface-grid-v6-fixed-lattice-diagnostic",
            "prototype": "source-aware excess-minimization then source-coverage maximization",
        },
        "records": records,
    }
    _write_json(output_dir / "summary.json", result)
    return result


def _record_run(
    source: bytes,
    case_id: str,
    up_axis: core.Axis,
    grid: core.GridSize,
    source_aware: bool,
    output_dir: Path,
    metric_timeout_seconds: float,
) -> dict[str, object]:
    started = perf_counter()
    result = convert_fixed_grid(
        source,
        grid_size=grid,
        solver_target_parts=SOLVER_TARGET_PARTS,
        max_parts=MAX_PARTS,
        up_axis=up_axis,
        source_evidence_resolution=SOURCE_EVIDENCE_RESOLUTION,
        shape_aware=True,
        source_aware=source_aware,
    )
    model = result.model
    mesh, scaled_vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(SOLVER_TARGET_PARTS, up_axis), grid
    )
    metric = evaluate_surface_metric_v2(
        scaled_vertices, faces, model.placements, timeout_seconds=metric_timeout_seconds
    )
    label = "prototype" if source_aware else "baseline"
    masks = render_silhouette_masks(
        scaled_vertices, faces, core._placement_boxes(model.placements),
        slope_vertices=core._slope_vertices(model.placements),
        wedge_vertices=core._wedge_vertices(model.placements),
    )
    for view, (source_mask, lego_mask) in masks.items():
        benchmark.make_overlay(source_mask, lego_mask).save(
            output_dir / f"{case_id}-{label}-{view}.png"
        )
    final_cells = frozenset(
        cell for placement in model.placements for cell in core._placement_source_cells(placement)
    )
    diagnostics = model.metadata.diagnostics
    assert diagnostics is not None
    buildability = analyze_buildability(model.placements)
    return {
        "algorithmVersion": model.metadata.algorithm_version,
        "runtimeSeconds": round(perf_counter() - started, 6),
        "actualParts": model.part_count,
        "placementGeometrySha256": _placement_hash(model.placements),
        "placementSignatures": _placement_signatures(model.placements),
        "solverStatus": {
            "stageOne": diagnostics.stage_one_status,
            "stageTwo": diagnostics.stage_two_status,
        },
        "candidateCounts": {
            "beforeProtection": diagnostics.candidate_count_before_protection,
            "afterProtection": diagnostics.candidate_count_after_protection,
            "afterReachabilityPruning": diagnostics.candidate_count_after_reachability_pruning,
        },
        "silhouetteV1": {
            "front": model.metadata.fidelity.front_iou, "side": model.metadata.fidelity.side_iou,
            "top": model.metadata.fidelity.top_iou, "mean": model.metadata.fidelity.mean_iou,
        },
        "surfaceMetricV2": metric.record(),
        "occupancy": {
            "source": len(result.source_cells),
            "projectionTarget": len(result.projection_hull_cells),
            "final": len(final_cells),
            "sourceRetained": len(final_cells & result.source_cells),
            "excess": len(final_cells - result.source_cells),
            "projected": _projection_comparison(final_cells, result.source_cells),
        },
        "safeguards": {
            "physicalCollisionPairs": len(colliding_placement_pairs(model.placements)),
            "unsupportedEvaluatedPlacements": buildability.unsupported_placement_count,
            "connectedComponents": buildability.connected_component_count,
            "isolatedPieces": buildability.isolated_placement_count,
            "protectedSpaceViolations": sum(
                bool(core._placement_source_cells(placement) & result.protected_empty_cells)
                for placement in model.placements
            ),
            "protectedEmptyCells": len(result.protected_empty_cells),
        },
        "source": {"triangleCount": len(faces), "watertight": bool(mesh.is_watertight)},
    }


def _projection_comparison(
    final_cells: frozenset[core.GridPosition], source_cells: frozenset[core.GridPosition]
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for view in ("front", "side", "top"):
        final = _project(final_cells, view)
        source = _project(source_cells, view)
        result[view] = {
            "sourceCoverage": len(final & source),
            "sourcePixels": len(source),
            "excessProjectedCoverage": len(final - source),
            "missingSourceCoverage": len(source - final),
        }
    return result


def _project(cells: frozenset[core.GridPosition], view: str) -> set[tuple[int, int]]:
    if view == "front":
        return {(cell.x, cell.z) for cell in cells}
    if view == "side":
        return {(cell.y, cell.z) for cell in cells}
    return {(cell.x, cell.y) for cell in cells}


def _grid_record(grid: core.GridSize) -> dict[str, object]:
    return {
        "widthStuds": grid.width_studs, "depthStuds": grid.depth_studs,
        "heightPlates": grid.height_plates,
        "physicalEnvelopeMm": {
            "width": grid.width_studs * core.STUD_WIDTH_MM,
            "depth": grid.depth_studs * core.STUD_WIDTH_MM,
            "height": grid.height_plates * core.PLATE_HEIGHT_MM,
        },
    }


def _placement_hash(placements: tuple[core.BrickPlacement, ...]) -> str:
    rows = _placement_signatures(placements)
    return sha256(json.dumps(rows, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _placement_signatures(placements: tuple[core.BrickPlacement, ...]) -> list[str]:
    rows = [
        (placement.brick_type.part_id, placement.position.x, placement.position.y,
         placement.position.z, placement.orientation_degrees, placement.color_id)
        for placement in placements
    ]
    return [sha256(json.dumps(row, separators=(",", ":")).encode()).hexdigest() for row in rows]


def _placement_comparison(
    baseline: dict[str, object], prototype: dict[str, object]
) -> dict[str, int]:
    baseline_signatures = baseline["placementSignatures"]
    prototype_signatures = prototype["placementSignatures"]
    assert isinstance(baseline_signatures, list)
    assert isinstance(prototype_signatures, list)
    baseline_set = set(baseline_signatures)
    prototype_set = set(prototype_signatures)
    return {
        "shared": len(baseline_set & prototype_set),
        "baselineOnly": len(baseline_set - prototype_set),
        "prototypeOnly": len(prototype_set - baseline_set),
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
