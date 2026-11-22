"""Run the opt-in, paired M13E Duck Control-hint experiment with private inputs."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from hashlib import sha256
from importlib.metadata import version
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
from app.conversion.m12c_wedge_fidelity_experiment import (
    fixed_frame_score,
    validate_completed_arrangement,
)  # noqa: E402
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
    FeasibilityResult,
    classify_result,
    solve_tp_fp_feasibility,
    validate_view_metrics,
)
from app.conversion.m13e_duck_control_hint_experiment import (  # noqa: E402
    DUCK_CANDIDATE_COUNT,
    DUCK_CONTROL_VIEWS,
    DUCK_GRID,
    DUCK_MAX_PARTS,
    DUCK_SOURCE_SHA256,
    complete_selection_hint,
    control_candidate_indices,
    model_fingerprint,
)
from app.conversion.m13e_duck_tp_max_experiment import (  # noqa: E402
    classify_tp_max_result,
    fixed_frame_mean_iou,
    total_true_positives,
)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    record = _load_duck_summary(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E accepts a manifest containing only the pinned Duck case.")
    result = run_duck_experiment(cases["duck"], record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in result.items():
        filename = "summary.json" if name == "summary" else f"{name}.json"
        (args.output_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )
    return 0 if result["summary"]["status"] == "COMPLETE" else 1


def run_duck_experiment(
    case: BenchmarkCase,
    record: dict[str, object],
    *,
    objective_mode: str = "min_fp",
    tp_loss_allowances: dict[str, int] | None = None,
    arm_policies: tuple[tuple[str, bool], ...] | None = None,
    expected_source_foreground: dict[str, int] | None = None,
) -> dict[str, dict[str, object]]:
    """Perform M13E's gates then solve fresh no-hint and complete-hint models."""
    try:
        if objective_mode not in {"min_fp", "max_tp"}:
            raise ValueError("M13E objective mode must be 'min_fp' or 'max_tp'.")
        source = verify_case_source(case)
        config = _mapping(record.get("configuration"), "configuration")
        if config.get("grid") != DUCK_GRID or config.get("candidateCount") != DUCK_CANDIDATE_COUNT:
            raise AuditError("Pinned Duck grid or candidate count does not match M13E.")
        if config.get("wedge41769aEnabled") is not False:
            raise AuditError("M13E requires wedge 41769a to be disabled.")
        if verify_source_sha256(source, record.get("sourceSha256")) != DUCK_SOURCE_SHA256:
            raise AuditError("Pinned Duck source SHA-256 does not match M13E.")
        control_saved = _mapping(record.get("control"), "control")
        control = reconstruct_placements(_strings(control_saved.get("placementIds")))
        if len(control) > DUCK_MAX_PARTS:
            raise AuditError("Historical Duck Control exceeds the M13E part cap.")
        grid = core.GridSize(**DUCK_GRID)
        preprocessing = reconstruct_m13b_preprocessing(source, grid, case.up_axis)
        locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
        if tuple(stable_placement_id(item) for item in locked) != tuple(
            stable_placement_id(item) for item in preprocessing.initial_locked_slope_placements
        ):
            raise AuditError("Historical locked placement identity does not match preprocessing.")
        preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
        failures = candidate_preflight_failures(DUCK_CANDIDATE_COUNT, preflight.candidates, control)
        if (
            failures
            or preflight.status != "READY"
            or any(
                value is None
                for value in (
                    preflight.candidate_rasters,
                    preflight.source_pixels,
                    preflight.locked_pixels,
                )
            )
        ):
            raise AuditError("; ".join(failures) or "Duck candidate preflight failed.")
        assert preflight.candidate_rasters is not None
        assert preflight.source_pixels is not None
        assert preflight.locked_pixels is not None
        control_views = _saved_views(control_saved)
        if control_views != DUCK_CONTROL_VIEWS:
            raise AuditError("Historical Duck Control metrics do not match pinned M13E values.")
        source_counts = _source_foreground_by_view(preflight.source_pixels)
        if expected_source_foreground is not None and source_counts != expected_source_foreground:
            raise AuditError("Pinned Duck source foreground counts do not match the experiment.")
        validate_view_metrics(_with_false_negatives(control_views, source_counts), source_counts)
        fixed = fixed_frame_score(
            preprocessing.source_vertices, preprocessing.faces, control, preprocessing.target_cells
        )
        rendered_views = {
            view.view: {
                "truePositives": view.true_positives,
                "falsePositives": view.false_positives,
            }
            for view in fixed.views
        }
        if rendered_views != control_views:
            raise AuditError("Control fixed-frame TP/FP parity failed.")
        control_ids = [
            stable_placement_id(item) for item in control if item.brick_type.shape == "rectangular"
        ]
        indices = control_candidate_indices(preflight.candidates, control_ids)
        hint_values = complete_selection_hint(len(preflight.candidates), indices)
        fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels
        frame_bounds = m13b_fixed_frame_bounds(
            preprocessing.source_vertices, preprocessing.target_cells
        )
        control_mask = _mask_parity(
            preprocessing.source_vertices,
            preprocessing.faces,
            control,
            preprocessing.target_cells,
            preflight.source_pixels,
            preflight.locked_pixels,
            [preflight.candidate_rasters[index] for index in indices],
            frame_bounds,
        )
        if not control_mask["passed"]:
            raise AuditError("Control raster union differs from the independent M12C renderer.")
        validation = validate_completed_arrangement(
            control, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
        )
        if not validation.is_valid:
            raise AuditError("Control violates post-solve mechanical validation.")
        control_frozen = asdict(
            evaluate_completed_assembly(preprocessing.source_vertices, preprocessing.faces, control)
        )
        parity = solve_tp_fp_feasibility(
            candidates=preflight.candidates,
            candidate_rasters=preflight.candidate_rasters,
            source_pixels=preflight.source_pixels,
            locked_pixels=preflight.locked_pixels,
            required_pixels=preprocessing.required_pixels,
            locked_placements=locked,
            target_cells=preprocessing.target_cells,
            fixed_coverage_pixels=fixed_coverage,
            control_views=control_views,
            max_parts=DUCK_MAX_PARTS,
            required_selected_ids=indices,
            objective_mode=objective_mode,
        )
        if parity.status not in {"OPTIMAL", "FEASIBLE"}:
            raise AuditError(
                f"Control assignment violates reconstructed hard constraints: {parity.status}."
            )
        fingerprint = model_fingerprint(
            candidate_ids=[stable_placement_id(item.placement) for item in preflight.candidates],
            locked_ids=[stable_placement_id(item) for item in locked],
            required_pixels=preprocessing.required_pixels,
            fixed_coverage_pixels=fixed_coverage,
            control_views=control_views,
            objective_mode=objective_mode,
            tp_loss_allowances=tp_loss_allowances,
        )
        common = {
            "sourceSha256": DUCK_SOURCE_SHA256,
            "candidateCount": DUCK_CANDIDATE_COUNT,
            "maxParts": DUCK_MAX_PARTS,
            "grid": DUCK_GRID,
            "wedge41769aEnabled": False,
            "ortoolsVersion": version("ortools"),
            "deterministicTimeBudgetSeconds": 30.0,
            "randomSeed": 0,
            "solverWorkers": 1,
            "modelFingerprint": fingerprint,
            "controlPartCount": len(control),
            "controlCandidateIndices": list(indices),
            "controlHintValuesSha256": sha256(bytes(hint_values)).hexdigest(),
            "controlAssignmentValidation": "PASSED",
            "controlMaskParity": control_mask,
            "controlFixedFrameMeanIou": fixed_frame_mean_iou(
                _with_false_negatives(control_views, source_counts)
            ),
            "controlFrozenSilhouetteV1": control_frozen,
        }
        if tp_loss_allowances is not None:
            common["tpLossAllowances"] = tp_loss_allowances
        policies = arm_policies or (("duck-no-hint", False), ("duck-control-hint", True))
        if not policies or len({name for name, _ in policies}) != len(policies):
            raise ValueError("M13E arm policies must have unique names.")
        arms = [
            _run_arm(
                name,
                indices if use_control_hint else None,
                common,
                preflight,
                preprocessing,
                locked,
                fixed_coverage,
                control_views,
                source_counts,
                objective_mode,
                tp_loss_allowances,
            )
            for name, use_control_hint in policies
        ]
        status = (
            "RESULT_VERIFICATION_FAILED"
            if any(arm["status"] == "RESULT_VERIFICATION_FAILED" for arm in arms)
            else "COMPLETE"
        )
        result = {
            "summary": {
                "schemaVersion": _schema_version(objective_mode),
                "status": status,
                "modelFingerprint": fingerprint,
                "records": arms,
            }
        }
        if arm_policies is None:
            result["summary"]["hintOnlyChange"] = {"noHint": False, "controlHint": True}
        result.update({arm["arm"]: arm for arm in arms})
        return result
    except (AuditError, KeyError, TypeError, ValueError, OSError) as error:
        failure: dict[str, object] = {
            "caseId": "duck",
            "status": "MODEL_PARITY_FAILED",
            "diagnostics": [str(error)],
        }
        failure_result = {
            "summary": {
                "schemaVersion": _schema_version(objective_mode),
                "status": "MODEL_PARITY_FAILED",
                "records": [failure],
            },
        }
        for name, _ in arm_policies or (("duck-no-hint", False), ("duck-control-hint", True)):
            failure_result[name] = {**failure, "arm": name}
        return failure_result


def _run_arm(
    name: str,
    hint: tuple[int, ...] | None,
    common: dict[str, object],
    preflight: M13bCandidatePreflight,
    preprocessing: M13bPreprocessing,
    locked: tuple[core.BrickPlacement, ...],
    fixed_coverage: frozenset[tuple[str, int, int]],
    control_views: dict[str, dict[str, int]],
    source_counts: dict[str, int],
    objective_mode: str,
    tp_loss_allowances: dict[str, int] | None,
) -> dict[str, object]:
    assert preflight.candidate_rasters is not None
    assert preflight.source_pixels is not None
    assert preflight.locked_pixels is not None
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
        max_parts=DUCK_MAX_PARTS,
        hint_selected_ids=hint,
        objective_mode=objective_mode,
        tp_loss_allowances=tp_loss_allowances,
    )
    payload: dict[str, object] = {
        "caseId": "duck",
        "arm": name,
        "status": result.status,
        "classification": _classification(result, control_views, objective_mode),
        "objectiveMode": objective_mode,
        "hintPresent": hint is not None,
        "provenance": common,
        "solver": asdict(result),
        "incumbentAvailable": result.status in {"OPTIMAL", "FEASIBLE"},
    }
    if result.status not in {"OPTIMAL", "FEASIBLE"}:
        return payload
    assert result.objective_value is not None
    placements = (
        *locked,
        *(preflight.candidates[index].placement for index in result.selected_ids),
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
    if objective_mode == "min_fp":
        validate_view_metrics(views, source_counts, total_fp=result.objective_value)
    else:
        validate_view_metrics(views, source_counts, total_tp=result.objective_value)
    mask = _mask_parity(
        preprocessing.source_vertices,
        preprocessing.faces,
        placements,
        preprocessing.target_cells,
        preflight.source_pixels,
        preflight.locked_pixels,
        [preflight.candidate_rasters[index] for index in result.selected_ids],
        m13b_fixed_frame_bounds(preprocessing.source_vertices, preprocessing.target_cells),
    )
    mechanical = validate_completed_arrangement(
        placements, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
    )
    allowances = tp_loss_allowances or {view: 0 for view in control_views}
    meets_control_bounds = all(
        views[view]["truePositives"] >= control_views[view]["truePositives"] - allowances[view]
        and views[view]["falsePositives"] <= control_views[view]["falsePositives"]
        for view in control_views
    )
    if (
        views != result.views
        or not mask["passed"]
        or not mechanical.is_valid
        or not meets_control_bounds
    ):
        payload["status"] = "RESULT_VERIFICATION_FAILED"
        payload["diagnostics"] = [
            "Solver result failed independent rendering or mechanical verification."
        ]
        return payload
    frozen = evaluate_completed_assembly(
        preprocessing.source_vertices, preprocessing.faces, placements
    )
    control_frozen = common["controlFrozenSilhouetteV1"]
    assert isinstance(control_frozen, dict)
    payload["result"] = {
        "selectedCandidateIndices": list(result.selected_ids),
        "placementIds": [stable_placement_id(item) for item in placements],
        "placementIdsSha256": sha256(
            "\n".join(stable_placement_id(item) for item in placements).encode()
        ).hexdigest(),
        "partCount": len(placements),
        "views": views,
        "aggregateFp": sum(values["falsePositives"] for values in views.values()),
        "aggregateTp": total_true_positives(views),
        "totalFpReduction": sum(values["falsePositives"] for values in control_views.values())
        - sum(values["falsePositives"] for values in views.values()),
        "fixedFrameMeanIou": fixed_frame_mean_iou(views),
        "fixedFrameMeanIouChangeFromControl": round(
            fixed_frame_mean_iou(views) - float(common["controlFixedFrameMeanIou"]), 6
        ),
        "frozenSilhouetteV1": asdict(frozen),
        "frozenMeanIouChangeFromControl": round(
            frozen.mean_iou - float(control_frozen["mean_iou"]), 6
        ),
        "mechanical": asdict(mechanical),
        "connectedComponentCount": len(mechanical.connected_components),
        "independentMaskParity": mask,
    }
    return payload


def _classification(
    result: FeasibilityResult, control_views: dict[str, dict[str, int]], objective_mode: str
) -> str:
    if objective_mode == "max_tp":
        return classify_tp_max_result(result, control_views)
    return classify_result(result, control_views)


def _schema_version(objective_mode: str) -> str:
    return "m13e-duck-tp-max-v1" if objective_mode == "max_tp" else "m13e-duck-control-hint-v1"


def _load_duck_summary(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records")
    if (
        payload.get("schemaVersion") != "m13b-iou-proxy-v1"
        or not isinstance(records, list)
        or len(records) != 1
        or not isinstance(records[0], dict)
        or records[0].get("caseId") != "duck"
    ):
        raise AuditError("M13E requires one Duck-only M13B summary.")
    return records[0]


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} is missing.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
