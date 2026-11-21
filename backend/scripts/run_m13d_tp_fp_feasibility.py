"""Run the opt-in private M13D Stage B feasibility experiment."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core  # noqa: E402
from app.conversion.evaluation_alignment import (  # noqa: E402
    evaluate_completed_assembly,
    stable_placement_id,
)
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage  # noqa: E402
from app.conversion.m12c_wedge_fidelity_experiment import (  # noqa: E402
    _raster_pixels,
    fixed_frame_score,
    validate_completed_arrangement,
)
from app.conversion.m13c_silhouette_equivalence_audit import (  # noqa: E402
    AuditError,
    candidate_preflight_failures,
    m13b_fixed_frame_bounds,
    m13b_no_wedge_candidate_preflight,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
    verify_source_sha256,
)
from app.conversion.m13d_tp_fp_feasibility_experiment import (  # noqa: E402
    DEFAULT_DETERMINISTIC_TIME_SECONDS,
    classify_result,
    solve_tp_fp_feasibility,
    validate_view_metrics,
)
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)

CASE_IDS = ("duck", "mansion", "realistic-man")
EXPECTED_CANDIDATES = {"duck": 1449, "mansion": 3166, "realistic-man": 1043}
MAX_PARTS = 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--deterministic-time-seconds", type=float, default=DEFAULT_DETERMINISTIC_TIME_SECONDS
    )
    args = parser.parse_args()
    if len(args.summary) != 3:
        parser.error("Pass exactly three single-case M13B summaries.")
    summaries = _load_summaries(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(summaries) != set(CASE_IDS) or set(cases) != set(CASE_IDS):
        raise AuditError("M13D requires the three pinned historical cases and M13B summaries.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = [
        _run_case(cases[case_id], summaries[case_id], args.deterministic_time_seconds)
        for case_id in CASE_IDS
    ]
    payload = {"schemaVersion": "m13d-tp-fp-feasibility-v1", "records": records}
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for record in records:
        (args.output_dir / f"{record['caseId']}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    failures = {"PRECHECK_FAILED", "MODEL_PARITY_FAILED", "RESULT_VERIFICATION_FAILED"}
    return 0 if all(record["status"] not in failures for record in records) else 1


def _run_case(case: BenchmarkCase, record: dict[str, object], budget: float) -> dict[str, object]:
    case_id = case.case_id
    try:
        source = verify_case_source(case)
        config = record["configuration"]
        if not isinstance(config, dict):
            raise AuditError("configuration is missing.")
        grid_value = config["grid"]
        if not isinstance(grid_value, dict):
            raise AuditError("grid is missing.")
        grid = core.GridSize(
            grid_value["width_studs"], grid_value["depth_studs"], grid_value["height_plates"]
        )
        control_saved = record["control"]
        if not isinstance(control_saved, dict):
            raise AuditError("control is missing.")
        control = reconstruct_placements(_strings(control_saved.get("placementIds")))
        if verify_source_sha256(source, record.get("sourceSha256")) != sha256(source).hexdigest():
            raise AuditError("source verification failed.")
        if (
            config.get("candidateCount") != EXPECTED_CANDIDATES[case_id]
            or config.get("wedge41769aEnabled") is not False
        ):
            raise AuditError("historical configuration does not match M13D requirements.")
        locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
        preprocessing = reconstruct_m13b_preprocessing(source, grid, case.up_axis)
        preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
        failures = candidate_preflight_failures(
            EXPECTED_CANDIDATES[case_id], preflight.candidates, control
        )
        if (
            failures
            or preflight.status != "READY"
            or preflight.candidate_rasters is None
            or preflight.source_pixels is None
            or preflight.locked_pixels is None
        ):
            raise AuditError("; ".join(failures) or "candidate preflight failed")
        fixed = fixed_frame_score(
            preprocessing.source_vertices, preprocessing.faces, control, preprocessing.target_cells
        )
        control_views = {
            view.view: {
                "truePositives": view.true_positives,
                "falsePositives": view.false_positives,
            }
            for view in fixed.views
        }
        saved_views = _saved_views(control_saved)
        if control_views != saved_views:
            raise AuditError("Control fixed-frame TP/FP parity failed.")
        source_foreground_by_view = _source_foreground_by_view(preflight.source_pixels)
        validate_view_metrics(
            _with_false_negatives(control_views, source_foreground_by_view),
            source_foreground_by_view,
        )
        candidate_by_id = {
            stable_placement_id(item.placement): index
            for index, item in enumerate(preflight.candidates)
        }
        control_candidate_ids = [
            candidate_by_id.get(stable_placement_id(item))
            for item in control
            if item.brick_type.shape == "rectangular"
        ]
        if any(index is None for index in control_candidate_ids):
            raise AuditError("Control candidate membership failed.")
        control_rasters = [
            preflight.candidate_rasters[index]
            for index in control_candidate_ids
            if index is not None
        ]
        frame_bounds = m13b_fixed_frame_bounds(
            preprocessing.source_vertices, preprocessing.target_cells
        )
        control_mask_parity = _mask_parity(
            preprocessing.source_vertices,
            preprocessing.faces,
            control,
            preprocessing.target_cells,
            preflight.source_pixels,
            preflight.locked_pixels,
            control_rasters,
            frame_bounds,
        )
        if not control_mask_parity["passed"]:
            return {
                "caseId": case_id,
                "status": "MODEL_PARITY_FAILED",
                "diagnostics": [
                    "Control candidate raster union differs from fixed-frame renderer."
                ],
                "controlMaskParity": control_mask_parity,
            }
        fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels
        result = solve_tp_fp_feasibility(
            candidates=preflight.candidates,
            candidate_rasters=preflight.candidate_rasters,
            source_pixels=preflight.source_pixels,
            locked_pixels=preflight.locked_pixels,
            required_pixels=preprocessing.required_pixels,
            locked_placements=locked,
            target_cells=preprocessing.target_cells,
            fixed_coverage_pixels=fixed_coverage,
            control_views=control_views,
            max_parts=MAX_PARTS,
            deterministic_time_seconds=budget,
        )
        if result.status not in {"OPTIMAL", "FEASIBLE"}:
            return {
                "caseId": case_id,
                "status": result.status,
                "classification": classify_result(result, control_views),
                "provenance": {
                    "sourceSha256": sha256(source).hexdigest(),
                    "candidateCount": len(preflight.candidates),
                },
                "solver": asdict(result),
            }
        placements = (
            *locked,
            *(preflight.candidates[index].placement for index in result.selected_ids),
        )
        validation = validate_completed_arrangement(
            placements, preprocessing.protected_empty_cells, MAX_PARTS
        )
        final_fixed = fixed_frame_score(
            preprocessing.source_vertices,
            preprocessing.faces,
            placements,
            preprocessing.target_cells,
        )
        final_views = {
            item.view: {
                "truePositives": item.true_positives,
                "falsePositives": item.false_positives,
                "falseNegatives": len(
                    {pixel for pixel in preflight.source_pixels if pixel[0] == item.view}
                )
                - item.true_positives,
            }
            for item in final_fixed.views
        }
        model_views = {
            view: {
                key: values[key] for key in ("truePositives", "falsePositives", "falseNegatives")
            }
            for view, values in result.views.items()
        }
        if result.objective_value is None:
            raise AuditError("A solved M13D result is missing its aggregate FP objective.")
        validate_view_metrics(
            model_views, source_foreground_by_view, total_fp=result.objective_value
        )
        validate_view_metrics(final_views, source_foreground_by_view)
        result_mask_parity = _mask_parity(
            preprocessing.source_vertices,
            preprocessing.faces,
            placements,
            preprocessing.target_cells,
            preflight.source_pixels,
            preflight.locked_pixels,
            [preflight.candidate_rasters[index] for index in result.selected_ids],
            frame_bounds,
        )
        if final_views != model_views or not result_mask_parity["passed"]:
            return {
                "caseId": case_id,
                "status": "RESULT_VERIFICATION_FAILED",
                "diagnostics": [
                    "Solver result disagrees with independent fixed-frame verification."
                ],
                "solver": asdict(result),
                "modelViews": model_views,
                "independentViews": final_views,
                "maskParity": result_mask_parity,
                "selectedPlacementIds": [stable_placement_id(item) for item in placements],
            }
        if not validation.is_valid:
            raise AuditError("post-solve mechanical validation failed.")
        return {
            "caseId": case_id,
            "status": result.status,
            "classification": classify_result(result, control_views),
            "provenance": {
                "sourceSha256": sha256(source).hexdigest(),
                "candidateCount": len(preflight.candidates),
                "controlCandidateMembership": "verified",
            },
            "solver": asdict(result),
            "baseline": {"partCount": len(control), "views": control_views},
            "result": {
                "partCount": len(placements),
                "views": final_views,
                "totalFpReduction": sum(item["falsePositives"] for item in control_views.values())
                - sum(item["falsePositives"] for item in final_views.values()),
                "placementIds": [stable_placement_id(item) for item in placements],
                "placementIdsSha256": sha256(
                    "\n".join(stable_placement_id(item) for item in placements).encode()
                ).hexdigest(),
                "mechanical": asdict(validation),
                "frozenSilhouetteV1": asdict(
                    evaluate_completed_assembly(
                        preprocessing.source_vertices, preprocessing.faces, placements
                    )
                ),
            },
        }
    except (AuditError, KeyError, TypeError, ValueError, OSError) as error:
        return {"caseId": case_id, "status": "PRECHECK_FAILED", "diagnostics": [str(error)]}


def _load_summaries(paths: list[Path]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records")
        if (
            payload.get("schemaVersion") != "m13b-iou-proxy-v1"
            or not isinstance(records, list)
            or len(records) != 1
            or not isinstance(records[0], dict)
        ):
            raise AuditError(f"{path} is not a single-case M13B summary.")
        result[str(records[0]["caseId"])] = records[0]
    return result


def _saved_views(record: dict[str, object]) -> dict[str, dict[str, int]]:
    fixed = record.get("fixedFrame")
    if not isinstance(fixed, dict) or not isinstance(fixed.get("views"), list):
        raise AuditError("Control fixed-frame record is missing.")
    return {
        str(item["view"]): {
            "truePositives": int(item["truePositives"]),
            "falsePositives": int(item["falsePositives"]),
        }
        for item in fixed["views"]
        if isinstance(item, dict)
    }


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError("placement IDs are missing.")
    return value


def _source_foreground_by_view(
    source_pixels: frozenset[tuple[str, int, int]],
) -> dict[str, int]:
    return {
        view: sum(pixel[0] == view for pixel in source_pixels) for view in ("front", "side", "top")
    }


def _with_false_negatives(
    views: dict[str, dict[str, int]], source_foreground_by_view: dict[str, int]
) -> dict[str, dict[str, int]]:
    return {
        view: {
            **views[view],
            "falseNegatives": source_foreground_by_view[view] - views[view]["truePositives"],
        }
        for view in ("front", "side", "top")
    }


def _mask_parity(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    placements: tuple[core.BrickPlacement, ...],
    target_cells: frozenset[core.GridPosition],
    source_pixels: frozenset[tuple[str, int, int]],
    locked_pixels: frozenset[tuple[str, int, int]],
    selected_candidate_rasters: list[frozenset[tuple[str, int, int]]],
    bounds: dict[str, tuple[float, float, float, float]],
) -> dict[str, object]:
    """Compare candidate-raster OR accounting with M12C's fixed-frame renderer."""
    _, rendered_output, rendered_source = _raster_pixels(
        vertices, faces, (), placements, target_cells
    )
    model_output = frozenset(locked_pixels).union(*selected_candidate_rasters)
    views: dict[str, dict[str, object]] = {}
    for view in ("front", "side", "top"):
        expected = frozenset(pixel for pixel in rendered_output if pixel[0] == view)
        actual = frozenset(pixel for pixel in model_output if pixel[0] == view)
        source = frozenset(pixel for pixel in source_pixels if pixel[0] == view)
        expected_only = sorted(expected - actual)
        actual_only = sorted(actual - expected)
        views[view] = {
            "frameBounds": list(bounds[view]),
            "sourceMaskMatches": source
            == frozenset(pixel for pixel in rendered_source if pixel[0] == view),
            "expected": _mask_metrics(source, expected),
            "actual": _mask_metrics(source, actual),
            "xorPixels": len(expected_only) + len(actual_only),
            "expectedOnlyPixels": len(expected_only),
            "actualOnlyPixels": len(actual_only),
            "expectedSha256": _mask_hash(expected),
            "actualSha256": _mask_hash(actual),
            "differenceSample": {
                "expectedOnly": expected_only[:10],
                "actualOnly": actual_only[:10],
            },
        }
    return {
        "passed": all(
            item["xorPixels"] == 0 and item["sourceMaskMatches"] for item in views.values()
        ),
        "views": views,
    }


def _mask_metrics(
    source: frozenset[tuple[str, int, int]], output: frozenset[tuple[str, int, int]]
) -> dict[str, float | int]:
    tp, fp, fn = len(source & output), len(output - source), len(source - output)
    return {
        "truePositives": tp,
        "falsePositives": fp,
        "falseNegatives": fn,
        "iou": 1.0 if tp + fp + fn == 0 else round(tp / (tp + fp + fn), 6),
    }


def _mask_hash(pixels: frozenset[tuple[str, int, int]]) -> str:
    text = "\n".join(f"{view}:{first}:{second}" for view, first, second in sorted(pixels))
    return sha256(text.encode()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
