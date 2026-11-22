"""Run the opt-in M13E-B3 Duck exact per-view IoU-dominance experiment."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from fractions import Fraction
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from ortools.sat.python import cp_model

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
    fixed_frame_score,
    validate_completed_arrangement,
)
from app.conversion.m13c_silhouette_equivalence_audit import (  # noqa: E402
    AuditError,
    M13bCandidatePreflight,
    M13bPreprocessing,
    candidate_preflight_failures,
    m13b_fixed_frame_bounds,
    m13b_no_wedge_candidate_preflight,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
    verify_source_sha256,
)
from app.conversion.m13d_tp_fp_feasibility_experiment import (  # noqa: E402
    validate_view_metrics,
)
from app.conversion.m13e_duck_control_hint_experiment import (  # noqa: E402
    DUCK_CANDIDATE_COUNT,
    DUCK_CONTROL_VIEWS,
    DUCK_GRID,
    DUCK_MAX_PARTS,
    DUCK_SOURCE_SHA256,
    control_candidate_indices,
)
from app.conversion.m13e_duck_cross_view_tradeoff import (  # noqa: E402
    fixed_frame_mean_iou_fraction,
    thresholds_hold,
)
from app.conversion.m13e_duck_iou_dominance import (  # noqa: E402
    IoUDominanceModel,
    IoUDominanceResult,
    build_iou_dominance_model,
    classify_iou_dominance_status,
    dominance_values,
    has_strict_per_view_dominance,
    model_fingerprint,
    solve_built_iou_dominance_model,
    solve_iou_dominance_feasibility,
)
from app.conversion.m13e_duck_mean_iou_guided import (  # noqa: E402
    LinearizedMeanIouObjective,
    add_linearized_mean_iou_objective,
    linearized_mean_iou_objective,
    surrogate_value,
)
from app.conversion.m13e_duck_tp_max_experiment import fixed_frame_mean_iou  # noqa: E402
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)
from scripts.run_m13d_tp_fp_feasibility import (  # noqa: E402
    _mask_parity,
    _saved_views,
    _source_foreground_by_view,
    _strings,
    _with_false_negatives,
)
from scripts.run_m13e_duck_hint import _load_duck_summary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/m13e-duck-iou-dominance")
    )
    args = parser.parse_args()
    record = _load_duck_summary(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B3 accepts a manifest containing only the pinned Duck case.")
    output = run_duck_iou_dominance(cases["duck"], record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(output["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "duck-iou-dominance.json").write_text(
        json.dumps(output["record"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if output["summary"]["status"] != "MODEL_PARITY_FAILED" else 1


def run_duck_iou_dominance(
    case: BenchmarkCase,
    record: dict[str, object],
    *,
    strict_view: str | None = None,
    strict_solver_callback: (
        Callable[[IoUDominanceModel, float], tuple[IoUDominanceResult, cp_model.CpSolver]] | None
    ) = None,
    compressed: bool = False,
    iou_change_basis_points: dict[str, int] | None = None,
    mean_iou_guided: bool = False,
    enforce_mandatory_coverage: bool = True,
) -> dict[str, dict[str, object]]:
    """Preflight Control separately, then solve the aggregate or one-view strict model."""
    try:
        source = verify_case_source(case)
        config = _mapping(record.get("configuration"), "configuration")
        if config.get("grid") != DUCK_GRID or config.get("candidateCount") != DUCK_CANDIDATE_COUNT:
            raise AuditError("Pinned Duck grid or candidate count does not match M13E-B3.")
        if config.get("wedge41769aEnabled") is not False:
            raise AuditError("M13E-B3 requires wedge 41769a to be disabled.")
        if verify_source_sha256(source, record.get("sourceSha256")) != DUCK_SOURCE_SHA256:
            raise AuditError("Pinned Duck source SHA-256 does not match M13E-B3.")
        control_saved = _mapping(record.get("control"), "control")
        control = reconstruct_placements(_strings(control_saved.get("placementIds")))
        if len(control) > DUCK_MAX_PARTS:
            raise AuditError("Historical Duck Control exceeds the M13E-B3 part cap.")
        preprocessing = reconstruct_m13b_preprocessing(
            source, core.GridSize(**DUCK_GRID), case.up_axis
        )
        locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
        expected_locked = tuple(
            stable_placement_id(item) for item in preprocessing.initial_locked_slope_placements
        )
        if tuple(stable_placement_id(item) for item in locked) != expected_locked:
            raise AuditError("Historical locked placement identity does not match preprocessing.")
        preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
        failures = candidate_preflight_failures(DUCK_CANDIDATE_COUNT, preflight.candidates, control)
        if (
            failures
            or preflight.status != "READY"
            or preflight.candidate_rasters is None
            or preflight.source_pixels is None
            or preflight.locked_pixels is None
        ):
            raise AuditError("; ".join(failures) or "Duck candidate preflight failed.")
        control_views = _saved_views(control_saved)
        if control_views != DUCK_CONTROL_VIEWS:
            raise AuditError("Historical Duck Control metrics do not match pinned M13E values.")
        source_counts = _source_foreground_by_view(preflight.source_pixels)
        if source_counts != {"front": 7895, "side": 7075, "top": 7255}:
            raise AuditError("Pinned Duck source foreground counts do not match M13E-B3.")
        control_full_views = _with_false_negatives(control_views, source_counts)
        validate_view_metrics(control_full_views, source_counts)
        control_fixed = fixed_frame_score(
            preprocessing.source_vertices, preprocessing.faces, control, preprocessing.target_cells
        )
        rendered_control = {
            item.view: {
                "truePositives": item.true_positives,
                "falsePositives": item.false_positives,
            }
            for item in control_fixed.views
        }
        if rendered_control != control_views:
            raise AuditError("Control fixed-frame TP/FP parity failed.")
        control_ids = [
            stable_placement_id(item) for item in control if item.brick_type.shape == "rectangular"
        ]
        indices = control_candidate_indices(preflight.candidates, control_ids)
        fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels
        bounds = m13b_fixed_frame_bounds(preprocessing.source_vertices, preprocessing.target_cells)
        control_mask = _mask_parity(
            preprocessing.source_vertices,
            preprocessing.faces,
            control,
            preprocessing.target_cells,
            preflight.source_pixels,
            preflight.locked_pixels,
            [preflight.candidate_rasters[index] for index in indices],
            bounds,
        )
        if not control_mask["passed"]:
            raise AuditError("Control raster union differs from the independent M12C renderer.")
        control_mechanical = validate_completed_arrangement(
            control, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
        )
        if not control_mechanical.is_valid:
            raise AuditError("Control violates post-solve mechanical validation.")
        model_kwargs = {
            "candidates": preflight.candidates,
            "candidate_rasters": preflight.candidate_rasters,
            "source_pixels": preflight.source_pixels,
            "locked_pixels": preflight.locked_pixels,
            "required_pixels": preprocessing.required_pixels,
            "locked_placements": locked,
            "target_cells": preprocessing.target_cells,
            "fixed_coverage_pixels": fixed_coverage,
            "control_views": control_views,
            "max_parts": DUCK_MAX_PARTS,
        }
        if mean_iou_guided and not compressed:
            raise ValueError("M13E-B5 requires the verified compressed B3 representation.")
        threshold_kwargs = (
            {
                "require_strict_improvement": False,
                "iou_change_basis_points": iou_change_basis_points,
            }
            if iou_change_basis_points is not None
            else {"strict_view": strict_view}
        )
        if mean_iou_guided:
            threshold_kwargs = {
                "require_strict_improvement": False,
                "enforce_iou_constraints": False,
            }
        compressed_uncompressed_parity: dict[str, object] | None = None
        if compressed:
            from app.conversion.m13e_duck_iou_incidence_compression import (
                build_compressed_iou_dominance_model,
            )

            control_built, _ = build_compressed_iou_dominance_model(
                **model_kwargs,
                required_selected_ids=indices,
                require_strict_improvement=False,
                enforce_mandatory_coverage=enforce_mandatory_coverage,
            )
            control_model, _ = solve_built_iou_dominance_model(
                control_built, deterministic_time_seconds=30.0
            )
            reference_control_built = build_iou_dominance_model(
                **model_kwargs,
                required_selected_ids=indices,
                require_strict_improvement=False,
            )
            reference_control_model, _ = solve_built_iou_dominance_model(
                reference_control_built, deterministic_time_seconds=30.0
            )
            if (
                reference_control_model.status not in {"OPTIMAL", "FEASIBLE"}
                or control_model.views != reference_control_model.views
                or control_model.dominance_values != reference_control_model.dominance_values
            ):
                raise AuditError(
                    "Compressed forced-Control TP/FP/FN or dominance values differ from "
                    "the uncompressed model."
                )
            compressed_uncompressed_parity = {
                "status": "PASSED",
                "compressed": asdict(control_model),
                "uncompressed": asdict(reference_control_model),
            }
        else:
            control_model = solve_iou_dominance_feasibility(
                **model_kwargs,
                required_selected_ids=indices,
                require_strict_improvement=False,
            )
        if control_model.status not in {"OPTIMAL", "FEASIBLE"}:
            raise AuditError("Control assignment violates reconstructed hard constraints.")
        if control_model.views != control_full_views or any(
            control_model.dominance_values.values()
        ):
            raise AuditError(
                "Control model metrics or exact dominance expressions do not equal zero."
            )
        fingerprint = model_fingerprint(
            candidate_ids=[stable_placement_id(item.placement) for item in preflight.candidates],
            locked_ids=[stable_placement_id(item) for item in locked],
            required_pixels=preprocessing.required_pixels,
            fixed_coverage_pixels=fixed_coverage,
            control_views=control_views,
            strict_view=strict_view,
            iou_change_basis_points=iou_change_basis_points,
            mean_iou_guided=mean_iou_guided,
        )
        provenance: dict[str, object] = {
            "sourceSha256": DUCK_SOURCE_SHA256,
            "candidateCount": DUCK_CANDIDATE_COUNT,
            "maxParts": DUCK_MAX_PARTS,
            "grid": DUCK_GRID,
            "wedge41769aEnabled": False,
            "ortoolsVersion": version("ortools"),
            "deterministicTimeBudgetSeconds": 30.0,
            "randomSeed": 0,
            "solverWorkers": 1,
            "mandatoryCoarseCoverageEnforced": enforce_mandatory_coverage,
            "modelFingerprint": fingerprint,
            "candidateIdsSha256": _id_hash(
                [stable_placement_id(item.placement) for item in preflight.candidates]
            ),
            "controlCandidateIndices": list(indices),
            "controlPlacementIdsSha256": _placement_hash(control),
        }
        control_preflight = {
            "status": "PASSED",
            "forcedControlSolver": asdict(control_model),
            "independentMaskParity": control_mask,
            "independentViews": control_full_views,
            "fixedFrameMeanIouExact": _fraction_text(
                fixed_frame_mean_iou_fraction(control_full_views)
            ),
            "dominanceValues": dominance_values(control_full_views, source_counts, control_views),
            "mechanical": asdict(control_mechanical),
            "frozenSilhouetteV1": asdict(
                evaluate_completed_assembly(
                    preprocessing.source_vertices, preprocessing.faces, control
                )
            ),
        }
        if compressed_uncompressed_parity is not None:
            control_preflight["compressedUncompressedParity"] = compressed_uncompressed_parity
        if compressed:
            if strict_solver_callback is not None:
                raise ValueError(
                    "Compressed mode does not accept an original-model solver callback."
                )
            strict_built, compression = build_compressed_iou_dominance_model(
                **model_kwargs,
                **threshold_kwargs,
                enforce_mandatory_coverage=enforce_mandatory_coverage,
            )
            reference_built = build_iou_dominance_model(**model_kwargs, **threshold_kwargs)
            from app.conversion.m13e_duck_iou_incidence_compression import (
                model_byte_size,
                model_proto_sha256,
                static_model_statistics,
            )

            compressed_statistics = asdict(static_model_statistics(strict_built, compression))
            reference_statistics = {
                "candidateSelectionVariables": reference_built.component_counts[
                    "candidate_selection_variables"
                ].variables,
                "coverageVariables": reference_built.component_counts[
                    "coverage_variables"
                ].variables,
                "maxEqualities": reference_built.component_counts[
                    "coverage_max_equalities"
                ].constraints,
                "maxEqualityCandidateReferences": compression.candidate_reference_count,
                "totalVariables": len(reference_built.model.proto.variables),
                "totalConstraints": len(reference_built.model.proto.constraints),
                "modelBytes": model_byte_size(reference_built.model),
                "distinctIncidenceSignatures": compression.touchable_pixel_count,
                "modelProtoSha256": model_proto_sha256(reference_built.model),
            }
            compressed_statistics["modelProtoSha256"] = model_proto_sha256(strict_built.model)
            objective = None
            if mean_iou_guided:
                objective = linearized_mean_iou_objective(source_counts, control_views)
                add_linearized_mean_iou_objective(
                    strict_built.model,
                    strict_built.true_positives,
                    strict_built.false_positives,
                    objective,
                )
            strict, strict_solver = solve_built_iou_dominance_model(
                strict_built, deterministic_time_seconds=30.0
            )
        else:
            strict = solve_iou_dominance_feasibility(
                **model_kwargs,
                **threshold_kwargs,
                on_built_model=strict_solver_callback,
            )
        result: dict[str, object] = {
            "caseId": "duck",
            "status": strict.status,
            "classification": (
                "INCONCLUSIVE"
                if iou_change_basis_points is not None or mean_iou_guided
                else classify_iou_dominance_status(strict.status, control_preflight_passed=True)
            ),
            "provenance": provenance,
            "modelFingerprint": fingerprint,
            "candidateProvenance": {
                "candidateCount": DUCK_CANDIDATE_COUNT,
                "candidateIdsSha256": provenance["candidateIdsSha256"],
                "controlCandidateIndices": provenance["controlCandidateIndices"],
            },
            "controlPreflight": control_preflight,
            "solver": asdict(strict),
        }
        if strict_view is not None:
            result["strictView"] = strict_view
        if iou_change_basis_points is not None:
            result["iouChangeBasisPoints"] = iou_change_basis_points
        if mean_iou_guided:
            assert objective is not None
            result["linearizedMeanIouObjective"] = {
                "scale": objective.scale,
                "roundingPolicy": objective.rounding_policy,
                "truePositiveCoefficients": dict(objective.true_positive_coefficients),
                "falsePositiveCoefficients": dict(objective.false_positive_coefficients),
                "exactTruePositiveCoefficients": {
                    view: str(value)
                    for view, value in objective.exact_true_positive_coefficients.items()
                },
                "exactFalsePositiveCoefficients": {
                    view: str(value)
                    for view, value in objective.exact_false_positive_coefficients.items()
                },
                "theoreticalAbsoluteBound": objective.theoretical_absolute_bound,
                "solverObjectiveValue": strict_solver.objective_value,
                "solverBestObjectiveBound": strict_solver.best_objective_bound,
            }
        if compressed:
            result["staticModelStatistics"] = {
                "reference": reference_statistics,
                "compressed": compressed_statistics,
            }
        if strict.status in {"OPTIMAL", "FEASIBLE"}:
            _add_verified_witness(
                result,
                strict,
                preflight,
                preprocessing,
                locked,
                source_counts,
                control_views,
                control,
                bounds,
                iou_change_basis_points,
                objective,
            )
        return {
            "summary": {
                "schemaVersion": "m13e-duck-iou-dominance-v1",
                "status": result["status"],
                "records": [result],
            },
            "record": result,
        }
    except (AuditError, KeyError, TypeError, ValueError, OSError) as error:
        result = {
            "caseId": "duck",
            "status": "MODEL_PARITY_FAILED",
            "classification": "MODEL_PARITY_FAILED",
            "diagnostics": [str(error)],
        }
        return {
            "summary": {
                "schemaVersion": "m13e-duck-iou-dominance-v1",
                "status": "MODEL_PARITY_FAILED",
                "records": [result],
            },
            "record": result,
        }


def _add_verified_witness(
    record: dict[str, object],
    strict: IoUDominanceResult,
    preflight: M13bCandidatePreflight,
    preprocessing: M13bPreprocessing,
    locked: tuple[core.BrickPlacement, ...],
    source_counts: dict[str, int],
    control_views: dict[str, dict[str, int]],
    control: tuple[core.BrickPlacement, ...],
    bounds: dict[str, tuple[float, float, float, float]],
    iou_change_basis_points: dict[str, int] | None = None,
    linearized_objective: LinearizedMeanIouObjective | None = None,
) -> None:
    """Independently validate every satisfaction witness before reporting it."""
    assert preflight.candidate_rasters is not None and preflight.source_pixels is not None
    placements = (
        *locked,
        *(preflight.candidates[index].placement for index in strict.selected_ids),
    )
    fixed = fixed_frame_score(
        preprocessing.source_vertices, preprocessing.faces, placements, preprocessing.target_cells
    )
    views = {
        item.view: {
            "truePositives": item.true_positives,
            "falsePositives": item.false_positives,
            "falseNegatives": source_counts[item.view] - item.true_positives,
        }
        for item in fixed.views
    }
    mask = _mask_parity(
        preprocessing.source_vertices,
        preprocessing.faces,
        placements,
        preprocessing.target_cells,
        preflight.source_pixels,
        preflight.locked_pixels,
        [preflight.candidate_rasters[index] for index in strict.selected_ids],
        bounds,
    )
    mechanical = validate_completed_arrangement(
        placements, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
    )
    values = dominance_values(views, source_counts, control_views)
    threshold_passed = iou_change_basis_points is None or thresholds_hold(
        views, source_counts, control_views, iou_change_basis_points
    )
    control_full_views = {
        view: {
            **control_views[view],
            "falseNegatives": source_counts[view] - control_views[view]["truePositives"],
        }
        for view in control_views
    }
    control_mean = fixed_frame_mean_iou_fraction(control_full_views)
    witness_mean = fixed_frame_mean_iou_fraction(views)
    if (
        views != strict.views
        or values != strict.dominance_values
        or not mask["passed"]
        or not mechanical.is_valid
        or (
            not thresholds_hold(views, source_counts, control_views, iou_change_basis_points)
            if iou_change_basis_points is not None
            else (
                linearized_objective is None
                and not has_strict_per_view_dominance(views, source_counts, control_views)
            )
        )
        or (iou_change_basis_points is not None and witness_mean <= control_mean)
    ):
        record["status"] = "RESULT_VERIFICATION_FAILED"
        record["classification"] = "RESULT_VERIFICATION_FAILED"
        record["diagnostics"] = [
            "Witness failed independent renderer, dominance, or mechanical validation."
        ]
        return
    frozen = evaluate_completed_assembly(
        preprocessing.source_vertices, preprocessing.faces, placements
    )
    control_frozen = evaluate_completed_assembly(
        preprocessing.source_vertices, preprocessing.faces, control
    )
    record["result"] = {
        "selectedCandidateIndices": list(strict.selected_ids),
        "placementIds": [stable_placement_id(item) for item in placements],
        "placementIdsSha256": _placement_hash(placements),
        "partCount": len(placements),
        "views": views,
        "dominanceValues": values,
        "perViewFixedFrameIou": _per_view_iou(views),
        "fixedFrameMeanIou": fixed_frame_mean_iou(views),
        "fixedFrameMeanIouExact": _fraction_text(witness_mean),
        "controlFixedFrameMeanIouExact": _fraction_text(control_mean),
        "frozenSilhouetteV1": asdict(frozen),
        "frozenMeanIouChangeFromControl": round(frozen.mean_iou - control_frozen.mean_iou, 6),
        "mechanical": asdict(mechanical),
        "connectedComponentCount": len(mechanical.connected_components),
        "independentMaskParity": mask,
    }
    if iou_change_basis_points is not None:
        record["classification"] = "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT"
        record["result"]["exactThresholdsPassed"] = threshold_passed
        record["result"]["fixedFrameMeanImprovesControl"] = witness_mean > control_mean
        record["result"]["frozenMeanExceedsTarget"] = frozen.mean_iou > 0.595249
        if frozen.mean_iou > 0.595249:
            record["classification"] = "VERIFIED_FROZEN_MEAN_IMPROVEMENT"
    elif linearized_objective is not None:
        record["result"]["surrogateObjectiveValue"] = surrogate_value(views, linearized_objective)
        record["result"]["fixedFrameMeanImprovesControl"] = witness_mean > control_mean
        record["classification"] = (
            "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT"
            if witness_mean > control_mean
            else "VALID_ASSEMBLY_NO_MEAN_IMPROVEMENT"
        )
        if frozen.mean_iou > control_frozen.mean_iou:
            record["classification"] = "VERIFIED_FROZEN_MEAN_IMPROVEMENT"


def _per_view_iou(views: dict[str, dict[str, int]]) -> dict[str, float]:
    return {
        view: round(
            values["truePositives"]
            / (values["truePositives"] + values["falsePositives"] + values["falseNegatives"]),
            6,
        )
        for view, values in views.items()
    }


def _fraction_text(value: Fraction) -> str:
    """Serialize a Fraction's exact numerator and denominator without float conversion."""
    return f"{value.numerator}/{value.denominator}"


def _placement_hash(placements: tuple[core.BrickPlacement, ...]) -> str:
    return _id_hash([stable_placement_id(item) for item in placements])


def _id_hash(ids: list[str]) -> str:
    return sha256("\n".join(ids).encode()).hexdigest()


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} is missing.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
