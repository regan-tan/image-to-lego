"""Exact fixed-frame IoU dominance model for the offline M13E-B3 Duck study."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Final

from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.m12c_wedge_fidelity_experiment import (
    _add_locked_support,
    _add_mandatory_coverage,
    _add_rectangular_nonoverlap,
    _add_verified_support,
)
from app.conversion.m13d_tp_fp_feasibility_experiment import (
    DEFAULT_DETERMINISTIC_TIME_SECONDS,
    SOLVER_RANDOM_SEED,
    SOLVER_WORKERS,
    VIEWS,
    _deterministic_time_consumed,
    _validated_selection_ids,
    validate_view_metrics,
)
from app.conversion.surface_grid_v4 import _Candidate

Pixel = tuple[str, int, int]
IOU_BASIS_POINT_SCALE: Final = 10_000
ORTOOLS_INT64_MAX: Final = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class IoUDominanceResult:
    """A satisfaction-model result; objective fields are intentionally absent."""

    status: str
    deterministic_time_seconds: float
    runtime_seconds: float
    selected_ids: tuple[int, ...]
    views: Mapping[str, Mapping[str, int]]
    dominance_values: Mapping[str, int]
    deterministic_time_consumed: float | None = None
    response_statistics: str | None = None
    variable_count: int | None = None
    constraint_count: int | None = None


@dataclass(frozen=True, slots=True)
class ModelComponentCount:
    """Variables and constraints added by one named B3 model component."""

    variables: int
    constraints: int


@dataclass(frozen=True, slots=True)
class IoUDominanceModel:
    """The B3 model and the expressions needed to read one CP-SAT response."""

    model: cp_model.CpModel
    selected: tuple[cp_model.IntVar, ...]
    true_positives: Mapping[str, cp_model.LinearExpr]
    false_positives: Mapping[str, cp_model.LinearExpr]
    dominance: Mapping[str, cp_model.LinearExpr]
    source_foreground: Mapping[str, int]
    component_counts: Mapping[str, ModelComponentCount]


def dominance_value(
    source_foreground: int, control_tp: int, control_fp: int, tp: int, fp: int
) -> int:
    """Return the exact cross-multiplied IoU difference against Control."""
    return (source_foreground + control_fp) * tp - control_tp * (source_foreground + fp)


def has_strict_per_view_dominance(
    views: Mapping[str, Mapping[str, int]],
    source_foreground_by_view: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
) -> bool:
    """Test dominance with integers, including strict improvement in one view."""
    values = dominance_values(views, source_foreground_by_view, control_views)
    return all(value >= 0 for value in values.values()) and sum(values.values()) >= 1


def strict_dominance_views(
    views: Mapping[str, Mapping[str, int]],
    source_foreground_by_view: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
) -> frozenset[str]:
    """Return the views satisfying one arm of B3.1's exact decomposition."""
    return frozenset(
        view
        for view, value in dominance_values(views, source_foreground_by_view, control_views).items()
        if value >= 1
        and all(
            other_value >= 0
            for other_view, other_value in dominance_values(
                views, source_foreground_by_view, control_views
            ).items()
            if other_view != view
        )
    )


def dominance_values(
    views: Mapping[str, Mapping[str, int]],
    source_foreground_by_view: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
) -> dict[str, int]:
    """Calculate exact dominance expressions from independently countable metrics."""
    _validate_control_inputs(source_foreground_by_view, control_views)
    validate_view_metrics(views, source_foreground_by_view)
    return {
        view: dominance_value(
            source_foreground_by_view[view],
            control_views[view]["truePositives"],
            control_views[view]["falsePositives"],
            views[view]["truePositives"],
            views[view]["falsePositives"],
        )
        for view in VIEWS
    }


def solve_iou_dominance_feasibility(
    *,
    candidates: Sequence[_Candidate],
    candidate_rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    required_pixels: Collection[Pixel],
    locked_placements: Collection[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
    fixed_coverage_pixels: Collection[Pixel],
    control_views: Mapping[str, Mapping[str, int]],
    max_parts: int,
    deterministic_time_seconds: float = DEFAULT_DETERMINISTIC_TIME_SECONDS,
    required_selected_ids: Collection[int] | None = None,
    require_strict_improvement: bool = True,
    strict_view: str | None = None,
    iou_change_basis_points: Mapping[str, int] | None = None,
    on_built_model: Callable[
        [IoUDominanceModel, float], tuple[IoUDominanceResult, cp_model.CpSolver]
    ]
    | None = None,
) -> IoUDominanceResult:
    """Solve B3 without M13D/B2 TP floors, FP caps, or an optimization objective."""
    if deterministic_time_seconds <= 0:
        raise ValueError("The deterministic time budget must be positive.")
    built = build_iou_dominance_model(
        candidates=candidates,
        candidate_rasters=candidate_rasters,
        source_pixels=source_pixels,
        locked_pixels=locked_pixels,
        required_pixels=required_pixels,
        locked_placements=locked_placements,
        target_cells=target_cells,
        fixed_coverage_pixels=fixed_coverage_pixels,
        control_views=control_views,
        max_parts=max_parts,
        required_selected_ids=required_selected_ids,
        require_strict_improvement=require_strict_improvement,
        strict_view=strict_view,
        iou_change_basis_points=iou_change_basis_points,
    )
    if on_built_model is not None:
        result, _ = on_built_model(built, deterministic_time_seconds)
    else:
        result, _ = solve_built_iou_dominance_model(
            built, deterministic_time_seconds=deterministic_time_seconds
        )
    return result


def build_iou_dominance_model(
    *,
    candidates: Sequence[_Candidate],
    candidate_rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    required_pixels: Collection[Pixel],
    locked_placements: Collection[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
    fixed_coverage_pixels: Collection[Pixel],
    control_views: Mapping[str, Mapping[str, int]],
    max_parts: int,
    required_selected_ids: Collection[int] | None = None,
    require_strict_improvement: bool = True,
    strict_view: str | None = None,
    iou_change_basis_points: Mapping[str, int] | None = None,
    enforce_iou_constraints: bool = True,
) -> IoUDominanceModel:
    """Build B3's exact model and retain a component-by-component size audit."""
    if len(candidates) != len(candidate_rasters):
        raise ValueError("Candidates and raster footprints must have matching lengths.")
    if not target_cells:
        raise ValueError("Target cells cannot be empty.")
    if strict_view is not None and strict_view not in VIEWS:
        raise ValueError("The strict view must be one of the fixed-frame views.")
    if strict_view is not None and (not require_strict_improvement or not enforce_iou_constraints):
        raise ValueError("A strict view requires strict improvement.")
    thresholds = _validated_iou_change_basis_points(iou_change_basis_points)
    if thresholds is not None and (
        require_strict_improvement or strict_view is not None or not enforce_iou_constraints
    ):
        raise ValueError("IoU thresholds cannot be combined with B3 dominance constraints.")
    source = frozenset(source_pixels)
    source_foreground = {view: sum(pixel[0] == view for pixel in source) for view in VIEWS}
    _validate_control_inputs(source_foreground, control_views)
    if thresholds is not None:
        _validate_iou_threshold_coefficient_bounds(source_foreground, control_views, thresholds)

    model = cp_model.CpModel()
    component_counts: dict[str, ModelComponentCount] = {}

    def count_component(name: str, before_variables: int, before_constraints: int) -> None:
        component_counts[name] = ModelComponentCount(
            len(model.proto.variables) - before_variables,
            len(model.proto.constraints) - before_constraints,
        )

    before_variables, before_constraints = _model_size(model)
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(len(candidates)))
    count_component("candidate_selection_variables", before_variables, before_constraints)
    required_ids = _validated_selection_ids(
        required_selected_ids, len(selected), "required candidate selection"
    )
    before_variables, before_constraints = _model_size(model)
    if required_ids is not None:
        for index, variable in enumerate(selected):
            model.add(variable == int(index in required_ids))
    count_component("required_candidate_selection", before_variables, before_constraints)

    candidate_tuple = tuple(candidates)
    locked = tuple(locked_placements)
    target = frozenset(target_cells)
    before_variables, before_constraints = _model_size(model)
    _add_rectangular_nonoverlap(model, selected, candidate_tuple, target)
    count_component("rectangular_nonoverlap", before_variables, before_constraints)
    before_variables, before_constraints = _model_size(model)
    _add_verified_support(model, selected, candidate_tuple, locked, min(cell.z for cell in target))
    count_component("verified_support", before_variables, before_constraints)
    before_variables, before_constraints = _model_size(model)
    _add_locked_support(model, selected, candidate_tuple, locked, min(cell.z for cell in target))
    count_component("locked_support", before_variables, before_constraints)
    before_variables, before_constraints = _model_size(model)
    _add_mandatory_coverage(
        model,
        selected,
        candidate_tuple,
        tuple(sorted(set(required_pixels) - set(fixed_coverage_pixels))),
    )
    count_component("mandatory_coverage", before_variables, before_constraints)
    before_variables, before_constraints = _model_size(model)
    model.add(sum(selected) <= max_parts - len(locked))
    count_component("part_cap", before_variables, before_constraints)

    locked_output = frozenset(locked_pixels)
    by_pixel: dict[Pixel, list[int]] = defaultdict(list)
    for candidate_id, raster in enumerate(candidate_rasters):
        for pixel in frozenset(raster):
            if pixel not in locked_output:
                by_pixel[pixel].append(candidate_id)
    before_variables, before_constraints = _model_size(model)
    coverage = {
        pixel: model.new_bool_var(f"covered_{pixel[0]}_{pixel[1]}_{pixel[2]}") for pixel in by_pixel
    }
    count_component("coverage_variables", before_variables, before_constraints)
    before_variables, before_constraints = _model_size(model)
    for pixel, variable in coverage.items():
        model.add_max_equality(variable, [selected[index] for index in by_pixel[pixel]])
    count_component("coverage_max_equalities", before_variables, before_constraints)

    tp_by_view: dict[str, cp_model.LinearExpr] = {}
    fp_by_view: dict[str, cp_model.LinearExpr] = {}
    d_by_view: dict[str, cp_model.LinearExpr] = {}
    before_variables, before_constraints = _model_size(model)
    for view in VIEWS:
        source_view = {pixel for pixel in source if pixel[0] == view}
        locked_view = {pixel for pixel in locked_output if pixel[0] == view}
        tp = cp_model.LinearExpr.Sum(
            [len(source_view & locked_view)]
            + [
                variable
                for pixel, variable in coverage.items()
                if pixel[0] == view and pixel in source_view
            ]
        )
        fp = cp_model.LinearExpr.Sum(
            [len(locked_view - source_view)]
            + [
                variable
                for pixel, variable in coverage.items()
                if pixel[0] == view and pixel not in source_view
            ]
        )
        baseline = control_views[view]
        d_value = (source_foreground[view] + baseline["falsePositives"]) * tp - baseline[
            "truePositives"
        ] * (source_foreground[view] + fp)
        if enforce_iou_constraints:
            if thresholds is None:
                model.add(d_value >= 0)
            else:
                _add_iou_change_threshold(
                    model, tp, fp, source_foreground[view], baseline, thresholds[view]
                )
        tp_by_view[view] = tp
        fp_by_view[view] = fp
        d_by_view[view] = d_value
    count_component("non_strict_per_view_dominance", before_variables, before_constraints)
    before_variables, before_constraints = _model_size(model)
    if strict_view is not None:
        model.add(d_by_view[strict_view] >= 1)
    elif require_strict_improvement and enforce_iou_constraints:
        model.add(cp_model.LinearExpr.Sum(list(d_by_view.values())) >= 1)
    count_component("strict_dominance", before_variables, before_constraints)

    return IoUDominanceModel(
        model,
        selected,
        tp_by_view,
        fp_by_view,
        d_by_view,
        source_foreground,
        component_counts,
    )


def solve_built_iou_dominance_model(
    built: IoUDominanceModel,
    *,
    deterministic_time_seconds: float,
    log_search_progress: bool = False,
    log_to_response: bool = False,
    log_to_stdout: bool = True,
) -> tuple[IoUDominanceResult, cp_model.CpSolver]:
    """Solve a model created by :func:`build_iou_dominance_model` without modifying it."""
    if deterministic_time_seconds <= 0:
        raise ValueError("The deterministic time budget must be positive.")

    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = deterministic_time_seconds
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    solver.parameters.log_search_progress = log_search_progress
    if hasattr(solver.parameters, "log_to_response"):
        solver.parameters.log_to_response = log_to_response
    if log_search_progress and hasattr(solver.parameters, "log_to_stdout"):
        solver.parameters.log_to_stdout = log_to_stdout
    status = solver.status_name(solver.solve(built.model))
    response_statistics, variable_count, constraint_count = _solver_diagnostics(built.model, solver)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return IoUDominanceResult(
            status,
            deterministic_time_seconds,
            solver.wall_time,
            (),
            {},
            {},
            _deterministic_time_consumed(solver),
            response_statistics,
            variable_count,
            constraint_count,
        ), solver
    views = {
        view: {
            "truePositives": int(solver.value(built.true_positives[view])),
            "falsePositives": int(solver.value(built.false_positives[view])),
            "falseNegatives": built.source_foreground[view]
            - int(solver.value(built.true_positives[view])),
        }
        for view in VIEWS
    }
    validate_view_metrics(views, built.source_foreground)
    return IoUDominanceResult(
        status,
        deterministic_time_seconds,
        solver.wall_time,
        tuple(
            index for index, variable in enumerate(built.selected) if solver.boolean_value(variable)
        ),
        views,
        {view: int(solver.value(built.dominance[view])) for view in VIEWS},
        _deterministic_time_consumed(solver),
        response_statistics,
        variable_count,
        constraint_count,
    ), solver


def classify_iou_dominance_status(status: str, *, control_preflight_passed: bool) -> str:
    """Keep parity failure distinct from strict-dominance infeasibility."""
    if not control_preflight_passed:
        return "MODEL_PARITY_FAILED"
    return {
        "OPTIMAL": "VERIFIED_DOMINATING_WITNESS",
        "FEASIBLE": "VERIFIED_DOMINATING_WITNESS",
        "INFEASIBLE": "PROVEN_NO_PER_VIEW_DOMINANCE",
        "UNKNOWN": "INCONCLUSIVE",
    }.get(status, "INCONCLUSIVE")


def model_fingerprint(
    *,
    candidate_ids: Sequence[str],
    locked_ids: Sequence[str],
    required_pixels: Collection[Pixel],
    fixed_coverage_pixels: Collection[Pixel],
    control_views: Mapping[str, Mapping[str, int]],
    strict_view: str | None = None,
    iou_change_basis_points: Mapping[str, int] | None = None,
    mean_iou_guided: bool = False,
) -> str:
    """Fingerprint B3's exact hard constraints and integer dominance formulation."""
    if strict_view is not None and strict_view not in VIEWS:
        raise ValueError("The strict view must be one of the fixed-frame views.")
    thresholds = _validated_iou_change_basis_points(iou_change_basis_points)
    if thresholds is not None and strict_view is not None:
        raise ValueError("IoU thresholds cannot be combined with a strict B3 view.")
    if mean_iou_guided and (strict_view is not None or thresholds is not None):
        raise ValueError("The mean-IoU surrogate cannot be combined with B3/B4 IoU constraints.")
    constraints = (
        ["historical-hard-constraints"]
        if mean_iou_guided
        else (
            ["historical-hard-constraints", "D_v >= 0", f"D_{strict_view} >= 1"]
            if strict_view is not None
            else (
                ["historical-hard-constraints", "exact-iou-basis-point-thresholds"]
                if thresholds is not None
                else ["historical-hard-constraints", "D_v >= 0", "sum(D_v) >= 1"]
            )
        )
    )
    payload = {
        "candidateIds": list(candidate_ids),
        "lockedIds": list(locked_ids),
        "requiredPixels": sorted(required_pixels),
        "fixedCoveragePixels": sorted(fixed_coverage_pixels),
        "controlViews": control_views,
        "constraints": constraints,
        "iouChangeBasisPoints": thresholds,
        "objective": "linearized-fixed-frame-mean-iou-v1" if mean_iou_guided else None,
        "solver": {
            "randomSeed": SOLVER_RANDOM_SEED,
            "workers": SOLVER_WORKERS,
            "deterministicTimeSeconds": DEFAULT_DETERMINISTIC_TIME_SECONDS,
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validate_control_inputs(
    source_foreground_by_view: Mapping[str, int], control_views: Mapping[str, Mapping[str, int]]
) -> None:
    if set(source_foreground_by_view) != set(VIEWS) or set(control_views) != set(VIEWS):
        raise ValueError(
            "Control metrics and source foreground must contain all fixed-frame views."
        )
    for view in VIEWS:
        source = source_foreground_by_view[view]
        metrics = control_views[view]
        tp, fp = metrics.get("truePositives"), metrics.get("falsePositives")
        if not isinstance(source, int) or isinstance(source, bool) or source <= 0:
            raise ValueError(f"Source foreground for {view} must be a positive integer.")
        if not isinstance(tp, int) or isinstance(tp, bool) or not 0 <= tp <= source:
            raise ValueError(f"Control TP for {view} is invalid.")
        if not isinstance(fp, int) or isinstance(fp, bool) or fp < 0:
            raise ValueError(f"Control FP for {view} is invalid.")


def _validated_iou_change_basis_points(
    thresholds: Mapping[str, int] | None,
) -> dict[str, int] | None:
    if thresholds is None:
        return None
    if set(thresholds) != set(VIEWS):
        raise ValueError("IoU thresholds must contain all fixed-frame views.")
    result = dict(thresholds)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in result.values()):
        raise ValueError("IoU thresholds must be integer basis points.")
    return result


def _add_iou_change_threshold(
    model: cp_model.CpModel,
    tp: cp_model.LinearExpr,
    fp: cp_model.LinearExpr,
    source_foreground: int,
    baseline: Mapping[str, int],
    basis_points: int,
) -> None:
    """Add the B4 threshold with signed exact integer basis points."""
    denominator = source_foreground + baseline["falsePositives"]
    right_multiplier = IOU_BASIS_POINT_SCALE * baseline["truePositives"] + (
        basis_points * denominator
    )
    model.add(
        IOU_BASIS_POINT_SCALE * denominator * tp >= right_multiplier * (source_foreground + fp)
    )


def _validate_iou_threshold_coefficient_bounds(
    source_foreground: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
    thresholds: Mapping[str, int],
) -> None:
    """Reject unsupported coefficients before allocating a CP-SAT model."""
    for view in VIEWS:
        baseline = control_views[view]
        denominator = source_foreground[view] + baseline["falsePositives"]
        right_multiplier = IOU_BASIS_POINT_SCALE * baseline["truePositives"] + (
            thresholds[view] * denominator
        )
        coefficients = (
            IOU_BASIS_POINT_SCALE * denominator,
            right_multiplier,
            source_foreground[view],
            right_multiplier * source_foreground[view],
        )
        if any(abs(value) > ORTOOLS_INT64_MAX for value in coefficients):
            raise ValueError("IoU threshold coefficient exceeds the OR-Tools int64 domain.")


def _solver_diagnostics(model: cp_model.CpModel, solver: cp_model.CpSolver) -> tuple[str, int, int]:
    """Keep raw CP-SAT evidence available without interpreting an UNKNOWN cause."""
    proto = model.proto
    return solver.response_stats(), len(proto.variables), len(proto.constraints)


def _model_size(model: cp_model.CpModel) -> tuple[int, int]:
    return len(model.proto.variables), len(model.proto.constraints)
