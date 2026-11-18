"""Run the bounded, private M10B physical-scale experiment offline.

This script never imports production conversion routing.  It writes only hashes
and aggregate measurements; source paths, GLBs, placements, and renders remain
private under the supplied ignored artifacts directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.conversion.fidelity import render_silhouette_masks  # noqa: E402
from app.conversion.fixed_grid_experiment import convert_fixed_grid  # noqa: E402
from app.conversion.physical_geometry import colliding_placement_pairs  # noqa: E402
from app.conversion.physical_scale_experiment import (  # noqa: E402
    BASELINE_CAP,
    CANDIDATE_LIMIT,
    LARGER_SCALE_CAP,
    SOLVER_TARGET_PARTS,
    nominal_envelope_mm,
    preflight_fixed_grid,
    scale_factors,
    scaled_grid,
)
from app.conversion.real_world_benchmark import load_manifest, verify_case_source  # noqa: E402
from app.conversion.scale_normalized_geometry import (  # noqa: E402
    evaluate_scale_normalized_silhouette,
)
from app.conversion.surface_grid_v4 import SolverStage  # noqa: E402
from app.conversion.surface_metric_v2 import evaluate_surface_metric_v2  # noqa: E402

SCHEMA_VERSION = "m10b-physical-scale-experiment-v1"
REALISTIC_MAN_PILOT_SCHEMA_VERSION = "m10b-realistic-man-scale-pilot-v1"
REALISTIC_MAN_CASE_ID = "realistic-man"
MAX_POINT_SECONDS = 180.0
METRIC_TIMEOUT_SECONDS = 30.0
BASELINE_GRIDS = {
    "duck": core.GridSize(5, 7, 12),
    "mansion": core.GridSize(7, 4, 12),
    "realistic-man": core.GridSize(3, 5, 18),
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=tuple(BASELINE_GRIDS))
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--realistic-man-pilot",
        action="store_true",
        help=(
            "Run the separately labelled Realistic-man-only exploratory pilot. "
            "This is the sole explicit exception to M10B's Duck-first progression rule."
        ),
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = run_experiment(
            arguments.manifest,
            arguments.output_dir,
            selected_case_ids=tuple(arguments.case) if arguments.case else None,
            preflight_only=arguments.preflight_only,
            realistic_man_pilot=arguments.realistic_man_pilot,
        )
    except (OSError, ValueError, core.ConversionError) as error:
        print(f"Experiment validation failed: {error}", file=sys.stderr)
        return 2
    records = summary["records"]
    assert isinstance(records, list)
    print(json.dumps({"status": summary["status"], "records": len(records)}, indent=2))
    return 0


def run_experiment(
    manifest_path: Path,
    output_dir: Path,
    *,
    selected_case_ids: tuple[str, ...] | None = None,
    preflight_only: bool = False,
    realistic_man_pilot: bool = False,
) -> dict[str, object]:
    manifest = load_manifest(manifest_path)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != set(BASELINE_GRIDS):
        raise ValueError("M10B requires the SHA-pinned Duck, Mansion, and Realistic-man manifest.")
    if manifest.corpus_status != "available":
        raise ValueError("M10B source corpus is unavailable; no measurements were run.")
    selected, schema_version, experiment_label = _select_experiment_cases(
        selected_case_ids, realistic_man_pilot
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    preflights: dict[str, dict[str, object]] = {}
    sources: dict[str, bytes] = {}
    for case_id in selected:
        case = cases[case_id]
        source = verify_case_source(case)
        sources[case_id] = source
        baseline = BASELINE_GRIDS[case_id]
        larger = scaled_grid(baseline, 1.5)
        preflight_measurement = preflight_fixed_grid(source, grid=larger, up_axis=case.up_axis)
        preflights[case_id] = _preflight_record(
            case_id, source, baseline, larger, preflight_measurement.record()
        )
    _write_json(
        output_dir / "preflight.json",
        {
            "schemaVersion": schema_version,
            "experimentLabel": experiment_label,
            "cases": preflights,
        },
    )
    if preflight_only:
        return {
            "schemaVersion": schema_version,
            "experimentLabel": experiment_label,
            "status": "preflight_completed",
            "preflights": preflights,
            "records": [],
        }

    records: list[dict[str, object]] = []
    # Original M10B always starts with Duck. The named pilot is intentionally separate.
    ordered_cases = tuple(
        case_id for case_id in ("duck", "mansion", "realistic-man") if case_id in selected
    )
    duck_passed = realistic_man_pilot
    for case_id in ordered_cases:
        if case_id != "duck" and not duck_passed:
            records.append(_skipped_record(case_id, "duck_pilot_not_credible"))
            continue
        case = cases[case_id]
        source = sources[case_id]
        baseline = BASELINE_GRIDS[case_id]
        records.append(_run_point(source, case_id, case.up_axis, baseline, baseline, BASELINE_CAP))
        larger = scaled_grid(baseline, 1.5)
        preflight_record = preflights[case_id]
        measured = preflight_record["measured"]
        assert isinstance(measured, dict)
        if not measured["accepted"]:
            records.append(_skipped_record(case_id, str(measured["decision"])))
            if case_id == "duck":
                duck_passed = False
            continue
        first_larger = _run_point(source, case_id, case.up_axis, baseline, larger, LARGER_SCALE_CAP)
        records.append(first_larger)
        if case_id == "duck":
            second_larger = _run_point(
                source, case_id, case.up_axis, baseline, larger, LARGER_SCALE_CAP
            )
            records.append(second_larger)
            duck_passed = _same_success(first_larger, second_larger)
    summary: dict[str, object] = {
        "schemaVersion": schema_version,
        "experimentLabel": experiment_label,
        "status": "completed" if records else "no_runs",
        "limits": {
            "candidateLimit": CANDIDATE_LIMIT,
            "pointRuntimeSeconds": MAX_POINT_SECONDS,
            "metricTimeoutSeconds": METRIC_TIMEOUT_SECONDS,
            "solverTargetParts": SOLVER_TARGET_PARTS,
            "baselineMaxParts": BASELINE_CAP,
            "largerScaleMaxParts": LARGER_SCALE_CAP,
            "solverWorkers": 1,
            "solverSeed": 0,
        },
        "preflights": preflights,
        "records": records,
        "duckPilotReproducible": None if realistic_man_pilot else duck_passed,
        "progressionException": (
            "Realistic-man-only exploratory pilot; original Duck-first M10B result is unchanged."
            if realistic_man_pilot
            else None
        ),
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _select_experiment_cases(
    selected_case_ids: tuple[str, ...] | None, realistic_man_pilot: bool
) -> tuple[tuple[str, ...], str, str]:
    if realistic_man_pilot:
        if selected_case_ids not in (None, (REALISTIC_MAN_CASE_ID,)):
            raise ValueError(
                "The Realistic-man pilot cannot be combined with other selected cases."
            )
        return (
            (REALISTIC_MAN_CASE_ID,),
            REALISTIC_MAN_PILOT_SCHEMA_VERSION,
            "M10B separately labelled Realistic-man 1x versus 1.5x exploratory pilot",
        )

    selected = selected_case_ids or tuple(BASELINE_GRIDS)
    if "duck" not in selected:
        raise ValueError(
            "Original M10B selections must include Duck; use --realistic-man-pilot for the "
            "separate Realistic-man-only experiment."
        )
    return selected, SCHEMA_VERSION, "M10B original Duck-first physical-scale experiment"


def _preflight_record(
    case_id: str,
    source: bytes,
    baseline: core.GridSize,
    larger: core.GridSize,
    measured: dict[str, object],
) -> dict[str, object]:
    return {
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "baselineGrid": _grid_record(baseline),
        "largerGrid": _grid_record(larger),
        "actualScaleFactors": scale_factors(larger, baseline),
        "genuinelyLargerLattice": larger.cell_count > baseline.cell_count,
        "intendedMaxParts": LARGER_SCALE_CAP,
        "measured": measured,
    }


def _run_point(
    source: bytes,
    case_id: str,
    up_axis: core.Axis,
    baseline_grid: core.GridSize,
    grid: core.GridSize,
    max_parts: int,
) -> dict[str, object]:
    started = perf_counter()
    base = {
        "caseId": case_id,
        "sourceSha256": sha256(source).hexdigest(),
        "grid": _grid_record(grid),
        "actualScaleFactors": scale_factors(grid, baseline_grid),
        "solverTargetParts": SOLVER_TARGET_PARTS,
        "maxParts": max_parts,
        "partBudgetIntervention": (
            "joint_scale_and_budget" if max_parts > BASELINE_CAP else "baseline_budget"
        ),
        "genuinelyLargerLattice": grid.cell_count > baseline_grid.cell_count,
    }
    try:
        result = convert_fixed_grid(
            source,
            grid_size=grid,
            solver_target_parts=SOLVER_TARGET_PARTS,
            max_parts=max_parts,
            up_axis=up_axis,
            shape_aware=True,
        )
    except (core.ConversionError, ValueError) as error:
        return {
            **base,
            "status": "failed",
            "failureReason": str(error),
            "runtimeSeconds": _elapsed(started),
        }
    runtime = _elapsed(started)
    if runtime > MAX_POINT_SECONDS:
        return {
            **base,
            "status": "infeasible_under_budget",
            "failureReason": "point_runtime_limit_exceeded",
            "runtimeSeconds": runtime,
        }
    model = result.model
    mesh, scaled_vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(SOLVER_TARGET_PARTS, up_axis), grid
    )
    surface = evaluate_surface_metric_v2(
        scaled_vertices, faces, model.placements, timeout_seconds=METRIC_TIMEOUT_SECONDS
    )
    frozen_masks = render_silhouette_masks(
        scaled_vertices,
        faces,
        core._placement_boxes(model.placements),
        slope_vertices=core._slope_vertices(model.placements),
        wedge_vertices=core._wedge_vertices(model.placements),
    )
    normalized = evaluate_scale_normalized_silhouette(
        core._normalize_vertices(
            [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices],
            up_axis,
        ),
        faces,
        model.placements,
        nominal_grid=grid,
    )
    diagnostics = model.metadata.diagnostics
    assert diagnostics is not None
    buildability = analyze_buildability(model.placements)
    final_cells = frozenset(
        cell for placement in model.placements for cell in core._placement_source_cells(placement)
    )
    return {
        **base,
        "status": "completed",
        "runtimeSeconds": runtime,
        "source": {"triangleCount": len(faces), "watertight": bool(mesh.is_watertight)},
        "actualParts": model.part_count,
        "partCapCompliant": model.part_count <= max_parts,
        "finalDimensionsMm": {
            "width": model.dimensions.width_mm,
            "depth": model.dimensions.depth_mm,
            "height": model.dimensions.height_mm,
        },
        "finalOccupiedCells": len(final_cells),
        "candidateCounts": {
            "beforeProtection": diagnostics.candidate_count_before_protection,
            "afterProtection": diagnostics.candidate_count_after_protection,
            "afterReachabilityPruning": diagnostics.candidate_count_after_reachability_pruning,
        },
        "solver": {
            "stageOne": _solver_stage_record(result.stage_one, "maximize"),
            "stageTwo": _solver_stage_record(result.stage_two, "minimize"),
        },
        "silhouetteV1": {
            "front": model.metadata.fidelity.front_iou,
            "side": model.metadata.fidelity.side_iou,
            "top": model.metadata.fidelity.top_iou,
            "mean": model.metadata.fidelity.mean_iou,
            "qualification": "cross-scale; dynamic bounds can confound comparisons",
        },
        "frozenProjectedPixels": _false_projection_pixels(frozen_masks),
        "surfaceMetricV2": surface.record(),
        "normalizedSilhouette": normalized.record(),
        "mechanical": {
            "physicalCollisionPairs": len(colliding_placement_pairs(model.placements)),
            "unsupportedEvaluatedPlacements": buildability.unsupported_placement_count,
            "protectedSpaceViolations": sum(
                bool(core._placement_source_cells(placement) & result.protected_empty_cells)
                for placement in model.placements
            ),
            "connectedComponents": buildability.connected_component_count,
            "largestConnectedComponent": buildability.largest_connected_component_size,
            "largestConnectedComponentRatio": buildability.largest_connected_component_ratio,
            "isolatedPlacements": buildability.isolated_placement_count,
        },
    }


def _solver_stage_record(stage: SolverStage, direction: str) -> dict[str, object]:
    """Record the CP-SAT result without implying a FEASIBLE incumbent is optimal."""
    gap: int | None = None
    if stage.objective_value is not None and stage.best_objective_bound is not None:
        gap = (
            stage.best_objective_bound - stage.objective_value
            if direction == "maximize"
            else stage.objective_value - stage.best_objective_bound
        )
    return {
        "status": stage.status,
        "objectiveValue": stage.objective_value,
        "bestObjectiveBound": stage.best_objective_bound,
        "absoluteGap": gap,
        "isProvenOptimal": stage.is_optimal,
        "deterministicTimeLimit": (20.0 if direction == "maximize" else 7.25),
        "runtimeSeconds": round(stage.runtime_seconds, 6),
    }


def _same_success(first: dict[str, object], second: dict[str, object]) -> bool:
    if first.get("status") != "completed" or second.get("status") != "completed":
        return False
    comparable = (
        "actualParts",
        "finalDimensionsMm",
        "candidateCounts",
        "normalizedSilhouette",
        "mechanical",
    )
    fields_match = all(first.get(field) == second.get(field) for field in comparable)
    return fields_match and _same_solver_result(first.get("solver"), second.get("solver"))


def _same_solver_result(first: object, second: object) -> bool:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return False
    stable_fields = (
        "status",
        "objectiveValue",
        "bestObjectiveBound",
        "absoluteGap",
        "isProvenOptimal",
        "deterministicTimeLimit",
    )
    for stage in ("stageOne", "stageTwo"):
        first_stage = first.get(stage)
        second_stage = second.get(stage)
        if not isinstance(first_stage, dict) or not isinstance(second_stage, dict):
            return False
        if any(first_stage.get(field) != second_stage.get(field) for field in stable_fields):
            return False
    return True


def _skipped_record(case_id: str, reason: str) -> dict[str, object]:
    return {"caseId": case_id, "status": "skipped", "failureReason": reason}


def _grid_record(grid: core.GridSize) -> dict[str, object]:
    return {
        "widthStuds": grid.width_studs,
        "depthStuds": grid.depth_studs,
        "heightPlates": grid.height_plates,
        "cellCount": grid.cell_count,
        "nominalEnvelopeMm": nominal_envelope_mm(grid),
    }


def _false_projection_pixels(
    masks: dict[str, tuple[Image.Image, Image.Image]],
) -> dict[str, dict[str, int]]:
    return {
        view: {
            "falsePositive": sum(
                bool(model_pixel) and not bool(source_pixel)
                for source_pixel, model_pixel in zip(
                    source_mask.get_flattened_data(), model_mask.get_flattened_data(), strict=True
                )
            ),
            "falseNegative": sum(
                bool(source_pixel) and not bool(model_pixel)
                for source_pixel, model_pixel in zip(
                    source_mask.get_flattened_data(), model_mask.get_flattened_data(), strict=True
                )
            ),
        }
        for view, (source_mask, model_mask) in masks.items()
    }


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _elapsed(started: float) -> float:
    return round(perf_counter() - started, 6)


if __name__ == "__main__":
    raise SystemExit(main())
