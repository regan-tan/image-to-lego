"""Run the private, offline M7B fixed-lattice 2x2 factorial experiment."""

from __future__ import annotations

import argparse
import json
import subprocess
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
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)
from app.conversion.surface_metric_v2 import evaluate_surface_metric_v2  # noqa: E402

SCHEMA_VERSION = "m7b-controlled-fidelity-experiment-v1"
SOLVER_TARGET_PARTS = 24
CAPS = (30, 60)
EVIDENCE_RESOLUTIONS = (1, 2)
CASE_IDS = ("duck", "mansion", "realistic-man")
FIXED_GRIDS = {
    "duck": core.GridSize(5, 7, 12),
    "mansion": core.GridSize(7, 4, 12),
    "realistic-man": core.GridSize(3, 5, 18),
}
MAX_BATCH_SECONDS = 18 * 60


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=CASE_IDS)
    parser.add_argument("--source-evidence-resolution", type=int, choices=EVIDENCE_RESOLUTIONS)
    parser.add_argument("--max-parts", type=int, choices=CAPS)
    parser.add_argument("--metric-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--summarize-existing", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        if arguments.summarize_existing:
            result = summarize_existing(arguments.manifest, arguments.output_dir)
        else:
            result = run_experiment(
                arguments.manifest,
                arguments.output_dir,
                case_id=arguments.case,
                source_evidence_resolution=arguments.source_evidence_resolution,
                max_parts=arguments.max_parts,
                metric_timeout_seconds=arguments.metric_timeout_seconds,
            )
    except (OSError, ValueError) as error:
        print(f"Experiment validation failed: {error}", file=sys.stderr)
        return 2
    records = result["records"]
    assert isinstance(records, list)
    print(json.dumps({"status": result["status"], "records": len(records)}, indent=2))
    return 0


def run_experiment(
    manifest_path: Path,
    output_dir: Path,
    *,
    case_id: str | None = None,
    source_evidence_resolution: int | None = None,
    max_parts: int | None = None,
    metric_timeout_seconds: float = 30.0,
) -> dict[str, object]:
    if metric_timeout_seconds <= 0:
        raise ValueError("--metric-timeout-seconds must be greater than zero.")
    cases = _m7b_cases(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    records: list[dict[str, object]] = []
    selected_case_ids = (case_id,) if case_id is not None else CASE_IDS
    selected_resolutions = (
        (source_evidence_resolution,)
        if source_evidence_resolution is not None
        else EVIDENCE_RESOLUTIONS
    )
    selected_caps = (max_parts,) if max_parts is not None else CAPS
    for selected_case_id in selected_case_ids:
        case = cases[selected_case_id]
        source = verify_case_source(case)
        for evidence_resolution in selected_resolutions:
            for selected_cap in selected_caps:
                if perf_counter() - started >= MAX_BATCH_SECONDS:
                    records.append(
                        _not_run_budget(selected_case_id, evidence_resolution, selected_cap)
                    )
                    continue
                record = _record_run(
                    source,
                    case_id=selected_case_id,
                    up_axis=case.up_axis,
                    grid=FIXED_GRIDS[selected_case_id],
                    source_evidence_resolution=evidence_resolution,
                    max_parts=selected_cap,
                    output_dir=output_dir,
                    metric_timeout_seconds=metric_timeout_seconds,
                )
                records.append(record)
                _write_json(
                    output_dir
                    / f"{selected_case_id}-e{evidence_resolution}-cap{selected_cap}.json",
                    record,
                )
    result = _summary(records)
    result["elapsedSeconds"] = round(perf_counter() - started, 6)
    if case_id is None and source_evidence_resolution is None and max_parts is None:
        _write_json(output_dir / "summary.json", result)
    return result


def summarize_existing(manifest_path: Path, output_dir: Path) -> dict[str, object]:
    """Build a complete canonical summary from the twelve durable point records."""
    cases = _m7b_cases(manifest_path)
    expected_paths = {
        f"{case_id}-e{resolution}-cap{cap}.json"
        for case_id in CASE_IDS
        for resolution in EVIDENCE_RESOLUTIONS
        for cap in CAPS
    }
    actual_paths = {path.name for path in output_dir.glob("*-e*-cap*.json")}
    if actual_paths != expected_paths:
        raise ValueError("Expected exactly the 12 canonical durable M7B point records.")

    records: list[dict[str, object]] = []
    for case_id in CASE_IDS:
        case = cases[case_id]
        for resolution in EVIDENCE_RESOLUTIONS:
            for cap in CAPS:
                path = output_dir / f"{case_id}-e{resolution}-cap{cap}.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError(f"Experiment record {path.name} is not an object.")
                _validate_existing_record(payload, path.name, case, resolution, cap)
                records.append(payload)

    result = _summary(records)
    _write_json(output_dir / "summary.json", result)
    return result


def _summary(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "completed"
        if all(record["status"] != "not_run_budget" for record in records)
        else "budget_exhausted",
        "codeRevision": _git_revision(),
        "batchBudgetSeconds": MAX_BATCH_SECONDS,
        "controls": {
            "algorithmVersion": "surface-grid-v6-fixed-lattice-diagnostic",
            "solverTargetParts": SOLVER_TARGET_PARTS,
            "caps": list(CAPS),
            "sourceEvidenceResolutions": list(EVIDENCE_RESOLUTIONS),
            "sourceEvidenceVersion": "source-evidence-voxel-v1",
            "surfaceMetricVersion": "placement-surface-proxy-v2-chunked",
        },
        "records": records,
    }


def _m7b_cases(manifest_path: Path) -> dict[str, BenchmarkCase]:
    manifest = load_manifest(manifest_path)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != set(CASE_IDS):
        raise ValueError("M7B manifest must contain exactly duck, mansion, and realistic-man.")
    if any(case.target_parts != SOLVER_TARGET_PARTS for case in cases.values()):
        raise ValueError("M7B manifest targetParts must be 24 for every source.")
    return cases


def _validate_existing_record(
    record: dict[str, object],
    filename: str,
    case: BenchmarkCase,
    resolution: int,
    cap: int,
) -> None:
    expected = {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": case.case_id,
        "sourceSha256": case.source_sha256,
        "upAxis": case.up_axis.value,
        "sourceEvidenceResolution": resolution,
        "sourceEvidenceVersion": "source-evidence-voxel-v1",
        "solverTargetParts": SOLVER_TARGET_PARTS,
        "maxParts": cap,
        "grid": _grid_record(FIXED_GRIDS[case.case_id]),
    }
    for field, expected_value in expected.items():
        if record.get(field) != expected_value:
            raise ValueError(f"Experiment record {filename} has an unexpected {field}.")


def _record_run(
    source: bytes,
    *,
    case_id: str,
    up_axis: core.Axis,
    grid: core.GridSize,
    source_evidence_resolution: int,
    max_parts: int,
    output_dir: Path,
    metric_timeout_seconds: float,
) -> dict[str, object]:
    started = perf_counter()
    base = {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "upAxis": up_axis.value,
        "sourceEvidenceResolution": source_evidence_resolution,
        "sourceEvidenceVersion": "source-evidence-voxel-v1",
        "solverTargetParts": SOLVER_TARGET_PARTS,
        "maxParts": max_parts,
        "grid": _grid_record(grid),
    }
    try:
        result = convert_fixed_grid(
            source,
            grid_size=grid,
            solver_target_parts=SOLVER_TARGET_PARTS,
            max_parts=max_parts,
            up_axis=up_axis,
            source_evidence_resolution=source_evidence_resolution,
            shape_aware=True,
        )
    except (core.ConversionError, ValueError) as error:
        return {
            **base,
            "status": "failed",
            "failureReason": str(error),
            "runtimeSeconds": _elapsed(started),
        }
    model = result.model
    mesh, scaled_vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(SOLVER_TARGET_PARTS, up_axis), grid
    )
    metric = evaluate_surface_metric_v2(
        scaled_vertices, faces, model.placements, timeout_seconds=metric_timeout_seconds
    )
    masks = render_silhouette_masks(
        scaled_vertices,
        faces,
        core._placement_boxes(model.placements),
        slope_vertices=core._slope_vertices(model.placements),
        wedge_vertices=core._wedge_vertices(model.placements),
    )
    image_stem = f"{case_id}-e{source_evidence_resolution}-cap{max_parts}"
    for view, (source_mask, model_mask) in masks.items():
        benchmark.make_overlay(source_mask, model_mask).save(
            output_dir / f"{image_stem}-{view}.png"
        )
    final_cells = frozenset(
        cell for placement in model.placements for cell in core._placement_source_cells(placement)
    )
    diagnostics = model.metadata.diagnostics
    assert diagnostics is not None
    buildability = analyze_buildability(model.placements)
    return {
        **base,
        "status": "completed",
        "runtimeSeconds": _elapsed(started),
        "source": {
            "triangleCount": len(faces),
            "watertight": bool(mesh.is_watertight),
            "sourceSubcellCount": result.source_subcell_count,
        },
        "placementGeometrySha256": _placement_hash(model.placements),
        "actualParts": model.part_count,
        "candidateCounts": {
            "beforeProtection": diagnostics.candidate_count_before_protection,
            "afterProtection": diagnostics.candidate_count_after_protection,
            "afterReachabilityPruning": diagnostics.candidate_count_after_reachability_pruning,
        },
        "solverStatus": {
            "stageOne": diagnostics.stage_one_status,
            "stageTwo": diagnostics.stage_two_status,
        },
        "stageAttribution": {
            "sourceSurfaceOccupancy": len(result.source_cells),
            "projectionHullAdditions": len(result.projection_hull_cells - result.source_cells),
            "projectionHullOccupancy": len(result.projection_hull_cells),
            "finalOccupancy": len(final_cells),
            "againstReducedSourceEvidence": _projection_metrics(final_cells, result.source_cells),
            "againstProjectionHull": _projection_metrics(final_cells, result.projection_hull_cells),
        },
        "silhouetteV1": {
            "front": model.metadata.fidelity.front_iou,
            "side": model.metadata.fidelity.side_iou,
            "top": model.metadata.fidelity.top_iou,
            "mean": model.metadata.fidelity.mean_iou,
        },
        "surfaceMetricV2": metric.record(),
        "safeguards": {
            "physicalCollisionPairs": len(colliding_placement_pairs(model.placements)),
            "unsupportedEvaluatedPlacements": buildability.unsupported_placement_count,
            "connectedComponents": buildability.connected_component_count,
            "protectedEmptyCells": len(result.protected_empty_cells),
        },
        "fallbackReason": diagnostics.shape_aware_rejection_reason,
    }


def _projection_metrics(
    final_cells: frozenset[core.GridPosition], target_cells: frozenset[core.GridPosition]
) -> dict[str, dict[str, int | float]]:
    return {
        view: _one_projection_metrics(_project(final_cells, view), _project(target_cells, view))
        for view in ("front", "side", "top")
    }


def _one_projection_metrics(
    actual: set[tuple[int, int]], target: set[tuple[int, int]]
) -> dict[str, int | float]:
    true_positive = len(actual & target)
    false_positive = len(actual - target)
    false_negative = len(target - actual)
    union = true_positive + false_positive + false_negative
    return {
        "truePositive": true_positive,
        "falsePositive": false_positive,
        "falseNegative": false_negative,
        "iou": round(true_positive / union, 6) if union else 1.0,
    }


def _project(cells: frozenset[core.GridPosition], view: str) -> set[tuple[int, int]]:
    if view == "front":
        return {(cell.x, cell.z) for cell in cells}
    if view == "side":
        return {(cell.y, cell.z) for cell in cells}
    return {(cell.x, cell.y) for cell in cells}


def _grid_record(grid: core.GridSize) -> dict[str, object]:
    return {
        "widthStuds": grid.width_studs,
        "depthStuds": grid.depth_studs,
        "heightPlates": grid.height_plates,
        "nominalEnvelopeMm": {
            "width": grid.width_studs * core.STUD_WIDTH_MM,
            "depth": grid.depth_studs * core.STUD_WIDTH_MM,
            "height": grid.height_plates * core.PLATE_HEIGHT_MM,
        },
    }


def _placement_hash(placements: tuple[core.BrickPlacement, ...]) -> str:
    records = [
        (
            placement.brick_type.part_id,
            placement.position.x,
            placement.position.y,
            placement.position.z,
            placement.orientation_degrees,
            placement.color_id,
        )
        for placement in placements
    ]
    return sha256(json.dumps(records, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _not_run_budget(case_id: str, resolution: int, max_parts: int) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": case_id,
        "sourceEvidenceResolution": resolution,
        "maxParts": max_parts,
        "status": "not_run_budget",
        "failureReason": "18-minute serial batch budget exhausted",
    }


def _git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _elapsed(started: float) -> float:
    return round(perf_counter() - started, 6)


if __name__ == "__main__":
    raise SystemExit(main())
