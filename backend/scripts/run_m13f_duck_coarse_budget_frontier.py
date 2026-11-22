"""Run the opt-in M13F Duck coarse-coverage budget frontier."""
# ruff: noqa: E402, E501

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core
from app.conversion.evaluation_alignment import evaluate_completed_assembly, stable_placement_id
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage
from app.conversion.m12c_wedge_fidelity_experiment import (
    fixed_frame_score,
    validate_completed_arrangement,
)
from app.conversion.m13c_silhouette_equivalence_audit import (
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
from app.conversion.m13d_tp_fp_feasibility_experiment import validate_view_metrics
from app.conversion.m13e_duck_control_hint_experiment import (
    DUCK_CANDIDATE_COUNT,
    DUCK_GRID,
    DUCK_MAX_PARTS,
    DUCK_SOURCE_SHA256,
    control_candidate_indices,
)
from app.conversion.m13e_duck_cross_view_tradeoff import fixed_frame_mean_iou_fraction
from app.conversion.m13e_duck_iou_dominance import (
    model_fingerprint,
    solve_built_iou_dominance_model,
)
from app.conversion.m13e_duck_iou_incidence_compression import (
    build_compressed_iou_dominance_model,
    model_proto_sha256,
)
from app.conversion.m13e_duck_mean_iou_guided import (
    add_linearized_mean_iou_objective,
    linearized_mean_iou_objective,
    surrogate_value,
)
from app.conversion.m13e_duck_tp_max_experiment import fixed_frame_mean_iou
from app.conversion.m13f_duck_coarse_budget_frontier import (
    CoarseRequirement,
    add_coarse_violation_budget,
    count_unmet_coarse_requirements,
    historical_coarse_requirements,
)
from app.conversion.real_world_benchmark import load_manifest, verify_case_source
from scripts.run_m13d_tp_fp_feasibility import _mask_parity, _source_foreground_by_view
from scripts.run_m13e_duck_hint import _load_duck_summary

BUDGETS = (0, 1, 2, 5, 10, 20, 35)
SCHEMA_VERSION = "m13f-duck-coarse-budget-frontier-v1"
CHECKPOINT_FILENAME = "PRIVATE_UNVALIDATED_CHECKPOINT.json"
DETERMINISTIC_TIME_LIMIT_SECONDS = 30.0
EXPECTED_CONTROL_FULL_VIEWS = {
    "front": {"truePositives": 7803, "falsePositives": 3940, "falseNegatives": 92},
    "side": {"truePositives": 6558, "falsePositives": 4002, "falseNegatives": 517},
    "top": {"truePositives": 7227, "falsePositives": 5793, "falseNegatives": 28},
}
EXPECTED_COARSE_REQUIREMENT_COUNT = 98


@dataclass(frozen=True)
class FrontierPreflight:
    """Validated historical inputs used by every M13F-B2 budget arm."""

    source: bytes
    preprocessing: M13bPreprocessing
    candidate_preflight: M13bCandidatePreflight
    locked: tuple[core.BrickPlacement, ...]
    requirements: tuple[CoarseRequirement, ...]
    fixed_coverage: frozenset[tuple[str, int, int]]
    control_candidate_indices: tuple[int, ...]
    control_views: dict[str, dict[str, int]]
    source_counts: dict[str, int]
    base_fingerprint: str


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("..") / "artifacts/m13f-duck-coarse-budget-frontier"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only from a matching private, unvalidated checkpoint.",
    )
    args = parser.parse_args()
    if args.output_dir.exists() and not args.resume:
        parser.error("Refusing to overwrite an existing experiment output directory.")
    args.output_dir.mkdir(parents=True)
    payload = run_frontier(
        args.manifest, args.summary, checkpoint_dir=args.output_dir, resume=args.resume
    )
    _write_json_atomically(args.output_dir / "summary.json", payload)
    return 0 if payload["status"] == "PASS" else 1


def run_frontier(
    manifest_path: Path,
    summary_path: Path,
    *,
    checkpoint_dir: Path | None = None,
    resume: bool = False,
) -> dict[str, object]:
    prepared = prepare_frontier(manifest_path, summary_path)
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    arms = _load_or_create_checkpoint(prepared, objective, checkpoint_dir, resume)
    completed_budgets = {arm["budget"] for arm in arms}
    for budget in BUDGETS:
        if budget in completed_budgets:
            continue
        arm = _run_arm(
            budget,
            prepared.candidate_preflight,
            prepared.preprocessing,
            prepared.locked,
            prepared.requirements,
            prepared.fixed_coverage,
            prepared.control_views,
            prepared.source_counts,
            objective,
        )
        arms.append(arm)
        _write_checkpoint(prepared, objective, checkpoint_dir, arms)
    arms.sort(key=lambda arm: arm["budget"])
    _check_optimal_monotonicity(arms)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "privateOptimizationPerformed": True,
        "coarseRequirements": {
            "count": len(prepared.requirements),
            "definition": "unique required orthographic projection pixels not already covered by locked geometry",
            "requirements": [
                {
                    "view": requirement.pixel[0],
                    "coordinates": [requirement.pixel[1], requirement.pixel[2]],
                    "candidateIndices": list(requirement.candidate_ids),
                }
                for requirement in prepared.requirements
            ],
        },
        "provenance": {
            "baseModelFingerprint": prepared.base_fingerprint,
            "sourceSha256": sha256(prepared.source).hexdigest(),
            "candidateCount": len(prepared.candidate_preflight.candidates),
            "candidateIdsSha256": sha256(
                "\n".join(
                    stable_placement_id(item.placement)
                    for item in prepared.candidate_preflight.candidates
                ).encode()
            ).hexdigest(),
        },
        "arms": arms,
        "limitations": [
            "The optimized surrogate is not exact mean IoU.",
            "Frozen silhouette-v1 is independently measured and need not be monotonic by budget.",
            "K > 0 witnesses with unmet requirements are historically inadmissible.",
        ],
    }


def _load_or_create_checkpoint(
    prepared: FrontierPreflight,
    objective: object,
    checkpoint_dir: Path | None,
    resume: bool,
) -> list[dict[str, object]]:
    if checkpoint_dir is None:
        if resume:
            raise ValueError("Cannot resume without a checkpoint directory.")
        return []
    checkpoint_path = checkpoint_dir / CHECKPOINT_FILENAME
    if not resume:
        _write_checkpoint(prepared, objective, checkpoint_dir, [])
        return []
    if not checkpoint_path.is_file():
        raise AuditError("Cannot resume without the private unvalidated checkpoint file.")
    checkpoint = _read_checkpoint(checkpoint_path)
    expected = _checkpoint_provenance(prepared, objective)
    if checkpoint.get("checkpointState") != "INCOMPLETE_UNVALIDATED":
        raise AuditError("Checkpoint is not an unvalidated M13F frontier checkpoint.")
    if checkpoint.get("provenance") != expected:
        raise AuditError(
            "Checkpoint provenance does not match the current M13F inputs/configuration."
        )
    arms = checkpoint.get("completedArms")
    if not isinstance(arms, list) or not all(isinstance(arm, dict) for arm in arms):
        raise AuditError("Checkpoint completed arms are malformed.")
    _verify_checkpoint_arms(arms, prepared, objective)
    return list(arms)


def _checkpoint_provenance(prepared: FrontierPreflight, objective: object) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "budgets": list(BUDGETS),
        "baseModelFingerprint": prepared.base_fingerprint,
        "sourceSha256": sha256(prepared.source).hexdigest(),
        "candidateCount": len(prepared.candidate_preflight.candidates),
        "candidateIdsSha256": sha256(
            "\n".join(
                stable_placement_id(item.placement)
                for item in prepared.candidate_preflight.candidates
            ).encode()
        ).hexdigest(),
        "coarseRequirementCount": len(prepared.requirements),
        "solver": {"deterministicTimeSeconds": DETERMINISTIC_TIME_LIMIT_SECONDS},
        "objective": {
            "scale": objective.scale,
            "roundingPolicy": objective.rounding_policy,
            "truePositiveCoefficients": dict(objective.true_positive_coefficients),
            "falsePositiveCoefficients": dict(objective.false_positive_coefficients),
            "theoreticalAbsoluteBound": objective.theoretical_absolute_bound,
        },
    }


def _write_checkpoint(
    prepared: FrontierPreflight,
    objective: object,
    checkpoint_dir: Path | None,
    arms: list[dict[str, object]],
) -> None:
    if checkpoint_dir is None:
        return
    payload = {
        "checkpointState": "INCOMPLETE_UNVALIDATED",
        "fullyValidatedFinalFrontier": False,
        "warning": "Private checkpoint only; this is not a fully validated final frontier.",
        "provenance": _checkpoint_provenance(prepared, objective),
        "completedArms": arms,
    }
    _write_json_atomically(checkpoint_dir / CHECKPOINT_FILENAME, payload)


def _read_checkpoint(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError("Private M13F checkpoint could not be read.") from error
    if not isinstance(payload, dict):
        raise AuditError("Private M13F checkpoint must be a JSON object.")
    return payload


def _verify_checkpoint_arms(
    arms: list[dict[str, object]], prepared: FrontierPreflight, objective: object
) -> None:
    budgets: list[int] = []
    for arm in arms:
        budget = arm.get("budget")
        model_hash = arm.get("solverModelProtoSha256")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget not in BUDGETS:
            raise AuditError("Checkpoint arm has an invalid coarse-coverage budget.")
        if not isinstance(model_hash, str):
            raise AuditError("Checkpoint arm is missing its solver model hash.")
        if budget in budgets:
            raise AuditError("Checkpoint repeats a coarse-coverage budget.")
        budgets.append(budget)
        if model_hash != _model_hash_for_budget(budget, prepared, objective):
            raise AuditError("Checkpoint solver model hash does not match the current arm model.")
    if budgets != list(BUDGETS[: len(budgets)]):
        raise AuditError("Checkpoint arms must be a contiguous prefix of M13F budgets.")


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
            temporary_file.write(json.dumps(payload, indent=2, sort_keys=True))
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


def prepare_frontier(manifest_path: Path, summary_path: Path) -> FrontierPreflight:
    """Load and independently validate historical M13B inputs without building a solver model."""
    record = _load_duck_summary(summary_path)
    cases = {case.case_id: case for case in load_manifest(manifest_path).cases}
    if set(cases) != {"duck"}:
        raise AuditError("M13F requires the pinned Duck-only manifest.")
    source = verify_case_source(cases["duck"])
    config = _mapping(record.get("configuration"), "configuration")
    if config.get("grid") != DUCK_GRID or config.get("candidateCount") != DUCK_CANDIDATE_COUNT:
        raise AuditError("Pinned Duck grid or candidate count does not match M13F-B2.")
    if config.get("wedge41769aEnabled") is not False:
        raise AuditError("M13F-B2 requires wedge 41769a to be disabled.")
    if verify_source_sha256(source, record.get("sourceSha256")) != DUCK_SOURCE_SHA256:
        raise AuditError("Pinned Duck source SHA-256 does not match M13F-B2.")
    control_saved = _mapping(record.get("control"), "control")
    control = reconstruct_placements(
        _strings(control_saved.get("placementIds"), "control.placementIds")
    )
    if len(control) > DUCK_MAX_PARTS:
        raise AuditError("Historical Duck Control exceeds the M13F-B2 part cap.")
    preprocessing = reconstruct_m13b_preprocessing(
        source, core.GridSize(**DUCK_GRID), cases["duck"].up_axis
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
        or preflight.candidate_rasters is None
        or preflight.source_pixels is None
        or preflight.locked_pixels is None
    ):
        raise AuditError("; ".join(failures) or "Candidate reconstruction failed.")
    assert preflight.candidate_rasters is not None
    assert preflight.source_pixels is not None
    assert preflight.locked_pixels is not None
    control_views = _historical_control_views(control_saved)
    source_counts = _source_foreground_by_view(preflight.source_pixels)
    if source_counts != {"front": 7895, "side": 7075, "top": 7255}:
        raise AuditError("Pinned Duck source foreground counts do not match M13F-B2.")
    validate_view_metrics(EXPECTED_CONTROL_FULL_VIEWS, source_counts)
    control_fixed = fixed_frame_score(
        preprocessing.source_vertices, preprocessing.faces, control, preprocessing.target_cells
    )
    rendered_control = {
        item.view: {
            "truePositives": item.true_positives,
            "falsePositives": item.false_positives,
            "falseNegatives": source_counts[item.view] - item.true_positives,
        }
        for item in control_fixed.views
    }
    if rendered_control != EXPECTED_CONTROL_FULL_VIEWS:
        raise AuditError("Control fixed-frame TP/FP/FN parity failed.")
    control_ids = [
        stable_placement_id(item) for item in control if item.brick_type.shape == "rectangular"
    ]
    control_indices = control_candidate_indices(preflight.candidates, control_ids)
    fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels
    requirements = historical_coarse_requirements(
        candidates=preflight.candidates,
        required_pixels=preprocessing.required_pixels,
        fixed_coverage_pixels=fixed_coverage,
    )
    if len(requirements) != EXPECTED_COARSE_REQUIREMENT_COUNT:
        raise AuditError("Historical M13F-B2 coarse requirement count is not 98.")
    if count_unmet_coarse_requirements(requirements, control_indices):
        raise AuditError("K=0 does not admit the historical Control selection.")
    bounds = m13b_fixed_frame_bounds(preprocessing.source_vertices, preprocessing.target_cells)
    control_mask = _mask_parity(
        preprocessing.source_vertices,
        preprocessing.faces,
        control,
        preprocessing.target_cells,
        preflight.source_pixels,
        preflight.locked_pixels,
        [preflight.candidate_rasters[index] for index in control_indices],
        bounds,
    )
    if not control_mask["passed"]:
        raise AuditError("Control raster union differs from the independent M12C renderer.")
    if not validate_completed_arrangement(
        control, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
    ).is_valid:
        raise AuditError("Control violates post-solve mechanical validation.")
    base_fingerprint = model_fingerprint(
        candidate_ids=[stable_placement_id(item.placement) for item in preflight.candidates],
        locked_ids=[stable_placement_id(item) for item in locked],
        required_pixels=preprocessing.required_pixels,
        fixed_coverage_pixels=fixed_coverage,
        control_views=control_views,
        mean_iou_guided=True,
    )
    return FrontierPreflight(
        source=source,
        preprocessing=preprocessing,
        candidate_preflight=preflight,
        locked=locked,
        requirements=requirements,
        fixed_coverage=fixed_coverage,
        control_candidate_indices=control_indices,
        control_views=control_views,
        source_counts=source_counts,
        base_fingerprint=base_fingerprint,
    )


def _run_arm(
    budget,
    preflight,
    preprocessing,
    locked,
    requirements,
    fixed_coverage,
    control_views,
    source_counts,
    objective,
):
    built, violations, model_hash = _build_arm_model(
        budget,
        preflight,
        preprocessing,
        locked,
        requirements,
        fixed_coverage,
        control_views,
        objective,
    )
    result, solver = solve_built_iou_dominance_model(
        built, deterministic_time_seconds=DETERMINISTIC_TIME_LIMIT_SECONDS
    )
    arm = {
        "budget": budget,
        "solver": asdict(result),
        "solverObjectiveValue": solver.objective_value
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "provenOptimalSurrogateObjectiveValue": solver.objective_value
        if result.status == "OPTIMAL"
        else None,
        "solverBestObjectiveBound": solver.best_objective_bound
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "solverModelProtoSha256": model_hash,
        "baseModelProvenance": "modelFingerprint identifies common historical base, not full budgeted model",
        "violationVariableCount": len(violations),
    }
    if result.status not in {"OPTIMAL", "FEASIBLE"}:
        return arm
    unmet = count_unmet_coarse_requirements(requirements, result.selected_ids)
    if len(unmet) > budget:
        raise AuditError("Independent coarse-requirement count exceeds budget.")
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
    validate_view_metrics(views, source_counts)
    bounds = m13b_fixed_frame_bounds(preprocessing.source_vertices, preprocessing.target_cells)
    parity = _mask_parity(
        preprocessing.source_vertices,
        preprocessing.faces,
        placements,
        preprocessing.target_cells,
        preflight.source_pixels,
        preflight.locked_pixels,
        [preflight.candidate_rasters[index] for index in result.selected_ids],
        bounds,
    )
    mechanical = validate_completed_arrangement(
        placements, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
    )
    if not parity["passed"] or not mechanical.is_valid or views != result.views:
        raise AuditError("Independent witness verification failed.")
    frozen = evaluate_completed_assembly(
        preprocessing.source_vertices, preprocessing.faces, placements
    )
    arm["result"] = {
        "selectedCandidateIndices": list(result.selected_ids),
        "placementIds": [stable_placement_id(item) for item in placements],
        "surrogateObjectiveValue": surrogate_value(views, objective),
        "views": views,
        "fixedFrameMeanIou": fixed_frame_mean_iou(views),
        "fixedFrameMeanIouExact": _fraction_text(fixed_frame_mean_iou_fraction(views)),
        "frozenSilhouetteV1": asdict(frozen),
        "partCount": len(placements),
        "connectedComponentCount": len(mechanical.connected_components),
        "mechanical": asdict(mechanical),
        "independentMaskParity": parity,
        "actualUnmetRequirementCount": len(unmet),
        "unmetRequirements": [
            {
                "view": item.pixel[0],
                "coordinates": [item.pixel[1], item.pixel[2]],
                "candidateIndices": list(item.candidate_ids),
            }
            for item in unmet
        ],
        "historicalAdmissibility": "SATISFIES_HISTORICAL_COARSE_COVERAGE"
        if not unmet
        else "HISTORICALLY_INADMISSIBLE_COARSE_COVERAGE_VIOLATED",
    }
    return arm


def _model_hash_for_budget(budget, prepared, objective) -> str:
    _, _, model_hash = _build_arm_model(
        budget,
        prepared.candidate_preflight,
        prepared.preprocessing,
        prepared.locked,
        prepared.requirements,
        prepared.fixed_coverage,
        prepared.control_views,
        objective,
    )
    return model_hash


def _build_arm_model(
    budget,
    preflight,
    preprocessing,
    locked,
    requirements,
    fixed_coverage,
    control_views,
    objective,
):
    built, _ = build_compressed_iou_dominance_model(
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
        require_strict_improvement=False,
        enforce_iou_constraints=False,
        enforce_mandatory_coverage=False,
    )
    violations = add_coarse_violation_budget(built, requirements, budget)
    add_linearized_mean_iou_objective(
        built.model, built.true_positives, built.false_positives, objective
    )
    model_hash = model_proto_sha256(built.model)
    return built, violations, model_hash


def _check_optimal_monotonicity(arms):
    values = [
        arm["provenOptimalSurrogateObjectiveValue"]
        for arm in arms
        if arm["solver"]["status"] == "OPTIMAL"
    ]
    if any(value is None for value in values):
        raise AuditError("OPTIMAL arm is missing its proven surrogate objective value.")
    if any(later < earlier for earlier, later in pairwise(values)):
        raise AuditError("Optimal objective decreased as a coarse-coverage budget increased.")


def _historical_control_views(control: dict[str, object]) -> dict[str, dict[str, int]]:
    """Read the M13B Control's fixed-frame list without accepting another result shape."""
    fixed_frame = _mapping(control.get("fixedFrame"), "control.fixedFrame")
    values = fixed_frame.get("views")
    if not isinstance(values, list):
        raise AuditError("control.fixedFrame.views must be a list.")
    views: dict[str, dict[str, int]] = {}
    for value in values:
        item = _mapping(value, "control.fixedFrame.views entry")
        view = item.get("view")
        metrics = {
            "truePositives": item.get("truePositives"),
            "falsePositives": item.get("falsePositives"),
            "falseNegatives": item.get("falseNegatives"),
        }
        if not isinstance(view, str) or any(
            not isinstance(metric, int) or isinstance(metric, bool) for metric in metrics.values()
        ):
            raise AuditError(
                "control.fixedFrame.views entries require a view and integer TP/FP/FN."
            )
        if view in views:
            raise AuditError(f"control.fixedFrame.views duplicates {view!r}.")
        views[view] = {name: int(metric) for name, metric in metrics.items()}
    if views != EXPECTED_CONTROL_FULL_VIEWS:
        raise AuditError("Historical Duck Control TP/FP/FN do not match pinned M13F-B2 values.")
    return {
        view: {
            "truePositives": values["truePositives"],
            "falsePositives": values["falsePositives"],
        }
        for view, values in views.items()
    }


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} must be an object.")
    return value


def _strings(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError(f"{name} must be a list of strings.")
    return value


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


if __name__ == "__main__":
    raise SystemExit(main())
