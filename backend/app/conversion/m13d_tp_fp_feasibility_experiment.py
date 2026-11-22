"""Opt-in CP-SAT experiment for M13D Stage B; not used by production conversion."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.m12c_wedge_fidelity_experiment import (
    _add_locked_support,
    _add_mandatory_coverage,
    _add_rectangular_nonoverlap,
    _add_verified_support,
)
from app.conversion.surface_grid_v4 import _Candidate

Pixel = tuple[str, int, int]
VIEWS = ("front", "side", "top")
DEFAULT_DETERMINISTIC_TIME_SECONDS = 30.0
SOLVER_RANDOM_SEED = 0
SOLVER_WORKERS = 1
RASTER_PIXELS_PER_VIEW = 128 * 128
ObjectiveMode = Literal["min_fp", "max_tp"]


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    status: str
    deterministic_time_seconds: float
    runtime_seconds: float
    objective_value: int | None
    best_objective_bound: int | None
    selected_ids: tuple[int, ...]
    views: Mapping[str, Mapping[str, int]]
    deterministic_time_consumed: float | None = None


def solve_tp_fp_feasibility(
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
    hint_selected_ids: Collection[int] | None = None,
    required_selected_ids: Collection[int] | None = None,
    objective_mode: ObjectiveMode = "min_fp",
    tp_loss_allowances: Mapping[str, int] | None = None,
) -> FeasibilityResult:
    """Optimize a retained M13D model under its per-view Control bounds."""
    if deterministic_time_seconds <= 0:
        raise ValueError("The deterministic time budget must be positive.")
    if objective_mode not in {"min_fp", "max_tp"}:
        raise ValueError("The objective mode must be 'min_fp' or 'max_tp'.")
    if len(candidates) != len(candidate_rasters):
        raise ValueError("Candidates and raster footprints must have matching lengths.")
    allowances = _validated_tp_loss_allowances(tp_loss_allowances, control_views)
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(len(candidates)))
    required_id_set = _validated_selection_ids(
        required_selected_ids, len(selected), "required candidate selection"
    )
    if required_id_set is not None:
        for index, variable in enumerate(selected):
            model.add(variable == int(index in required_id_set))
    if hint_selected_ids is not None:
        hinted_id_set = _validated_selection_ids(
            hint_selected_ids, len(selected), "candidate selection hint"
        )
        assert hinted_id_set is not None
        for index, variable in enumerate(selected):
            model.add_hint(variable, int(index in hinted_id_set))
    candidate_tuple = tuple(candidates)
    target = frozenset(target_cells)
    locked = tuple(locked_placements)
    _add_rectangular_nonoverlap(model, selected, candidate_tuple, target)
    _add_verified_support(model, selected, candidate_tuple, locked, min(cell.z for cell in target))
    _add_locked_support(model, selected, candidate_tuple, locked, min(cell.z for cell in target))
    _add_mandatory_coverage(
        model,
        selected,
        candidate_tuple,
        tuple(sorted(set(required_pixels) - set(fixed_coverage_pixels))),
    )
    model.add(sum(selected) <= max_parts - len(locked))

    source = frozenset(source_pixels)
    locked_output = frozenset(locked_pixels)
    by_pixel: dict[Pixel, list[int]] = defaultdict(list)
    for candidate_id, raster in enumerate(candidate_rasters):
        for pixel in frozenset(raster):
            if pixel not in locked_output:
                by_pixel[pixel].append(candidate_id)
    coverage = {
        pixel: model.new_bool_var(f"covered_{pixel[0]}_{pixel[1]}_{pixel[2]}") for pixel in by_pixel
    }
    for pixel, variable in coverage.items():
        model.add_max_equality(variable, [selected[index] for index in by_pixel[pixel]])

    tp_by_view: dict[str, cp_model.LinearExpr] = {}
    fp_by_view: dict[str, cp_model.LinearExpr] = {}
    source_foreground_by_view: dict[str, int] = {}
    for view in VIEWS:
        source_view = {pixel for pixel in source if pixel[0] == view}
        locked_view = {pixel for pixel in locked_output if pixel[0] == view}
        tp_terms: list[cp_model.LinearExpr | int] = [len(source_view & locked_view)]
        fp_terms: list[cp_model.LinearExpr | int] = [len(locked_view - source_view)]
        for pixel, variable in coverage.items():
            if pixel[0] != view:
                continue
            if pixel in source_view:
                tp_terms.append(variable)
            else:
                fp_terms.append(variable)
        tp = cp_model.LinearExpr.Sum(tp_terms)
        fp = cp_model.LinearExpr.Sum(fp_terms)
        baseline = control_views[view]
        model.add(tp >= baseline["truePositives"] - allowances[view])
        model.add(fp <= baseline["falsePositives"])
        tp_by_view[view] = tp
        fp_by_view[view] = fp
        source_foreground_by_view[view] = len(source_view)
    total_fp = cp_model.LinearExpr.Sum(list(fp_by_view.values()))
    total_tp = cp_model.LinearExpr.Sum(list(tp_by_view.values()))
    if objective_mode == "min_fp":
        model.minimize(total_fp)
    else:
        model.maximize(total_tp)
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = deterministic_time_seconds
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    status = solver.status_name(solver.solve(model))
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return FeasibilityResult(
            status,
            deterministic_time_seconds,
            solver.wall_time,
            None,
            None,
            (),
            {},
            _deterministic_time_consumed(solver),
        )
    values = {
        view: {
            "truePositives": int(solver.value(tp_by_view[view])),
            "falsePositives": int(solver.value(fp_by_view[view])),
            "falseNegatives": source_foreground_by_view[view] - int(solver.value(tp_by_view[view])),
        }
        for view in VIEWS
    }
    objective_value = int(round(solver.objective_value))
    if objective_mode == "min_fp":
        validate_view_metrics(values, source_foreground_by_view, total_fp=objective_value)
    else:
        validate_view_metrics(values, source_foreground_by_view, total_tp=objective_value)
    return FeasibilityResult(
        status,
        deterministic_time_seconds,
        solver.wall_time,
        objective_value,
        int(round(solver.best_objective_bound)),
        tuple(index for index, variable in enumerate(selected) if solver.boolean_value(variable)),
        values,
        _deterministic_time_consumed(solver),
    )


def _deterministic_time_consumed(solver: cp_model.CpSolver) -> float | None:
    """Return OR-Tools' measured deterministic time when the installed version exposes it."""
    value = getattr(solver.response_proto, "deterministic_time", None)
    return float(value) if isinstance(value, int | float) else None


def _validated_selection_ids(
    selected_ids: Collection[int] | None, candidate_count: int, name: str
) -> frozenset[int] | None:
    if selected_ids is None:
        return None
    values = tuple(selected_ids)
    if len(set(values)) != len(values):
        raise ValueError(f"The {name} contains duplicate indices.")
    if any(not isinstance(index, int) or isinstance(index, bool) for index in values):
        raise ValueError(f"The {name} indices must be integers.")
    if any(index < 0 or index >= candidate_count for index in values):
        raise ValueError(f"The {name} contains an out-of-range index.")
    return frozenset(values)


def _validated_tp_loss_allowances(
    allowances: Mapping[str, int] | None, control_views: Mapping[str, Mapping[str, int]]
) -> dict[str, int]:
    """Return per-view TP loss allowances without changing the historical default."""
    if allowances is None:
        return {view: 0 for view in VIEWS}
    if set(allowances) != set(VIEWS):
        raise ValueError("TP-loss allowances must contain exactly the fixed-frame views.")
    result: dict[str, int] = {}
    for view in VIEWS:
        allowance = allowances[view]
        baseline_tp = control_views[view]["truePositives"]
        if (
            not isinstance(allowance, int)
            or isinstance(allowance, bool)
            or allowance < 0
            or allowance > baseline_tp
        ):
            raise ValueError(f"Invalid TP-loss allowance for {view}.")
        result[view] = allowance
    return result


def validate_view_metrics(
    views: Mapping[str, Mapping[str, int]],
    source_foreground_by_view: Mapping[str, int],
    *,
    total_fp: int | None = None,
    total_tp: int | None = None,
) -> None:
    """Reject invalid fixed-frame metrics before they can be reported as evidence."""
    for view in VIEWS:
        metrics = views.get(view)
        source_foreground = source_foreground_by_view.get(view)
        if metrics is None or source_foreground is None:
            raise ValueError(f"Missing fixed-frame metrics for {view}.")
        if (
            not isinstance(source_foreground, int)
            or not 0 <= source_foreground <= RASTER_PIXELS_PER_VIEW
        ):
            raise ValueError(f"Invalid source foreground count for {view}.")
        true_positives = metrics.get("truePositives")
        false_positives = metrics.get("falsePositives")
        false_negatives = metrics.get("falseNegatives")
        if not (
            isinstance(true_positives, int)
            and not isinstance(true_positives, bool)
            and isinstance(false_positives, int)
            and not isinstance(false_positives, bool)
            and isinstance(false_negatives, int)
            and not isinstance(false_negatives, bool)
        ):
            raise ValueError(f"Fixed-frame metrics for {view} must be integers.")
        if any(
            value < 0 or value > RASTER_PIXELS_PER_VIEW
            for value in (true_positives, false_positives, false_negatives)
        ):
            raise ValueError(f"Fixed-frame metrics for {view} are outside the 128px raster.")
        if true_positives + false_negatives != source_foreground:
            raise ValueError(
                f"Fixed-frame TP/FN accounting does not match source foreground for {view}."
            )
    _validate_aggregate_metric(
        views,
        total_fp,
        "falsePositives",
        "FP",
        "Solver aggregate FP does not equal the per-view FP sum.",
    )
    _validate_aggregate_metric(
        views,
        total_tp,
        "truePositives",
        "TP",
        "Solver aggregate TP does not equal the per-view TP sum.",
    )


def _validate_aggregate_metric(
    views: Mapping[str, Mapping[str, int]],
    expected: int | None,
    field: str,
    name: str,
    mismatch_message: str,
) -> None:
    if expected is None:
        return
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        raise ValueError(f"Aggregate {name} must be a nonnegative integer.")
    if expected != sum(views[view][field] for view in VIEWS):
        raise ValueError(mismatch_message)


def classify_result(
    result: FeasibilityResult, control_views: Mapping[str, Mapping[str, int]]
) -> str:
    """Use status and strict aggregate FP change without conflating timeout with proof."""
    if result.status == "OPTIMAL":
        return "PROVEN_IMPROVEMENT" if _improved(result, control_views) else "PROVEN_UNCHANGED"
    if result.status == "FEASIBLE":
        return (
            "IMPROVED_INCUMBENT" if _improved(result, control_views) else "INCONCLUSIVE_UNCHANGED"
        )
    if result.status == "INFEASIBLE":
        return "MODEL_PARITY_FAILED"
    return "INCONCLUSIVE"


def _improved(result: FeasibilityResult, control_views: Mapping[str, Mapping[str, int]]) -> bool:
    return sum(values["falsePositives"] for values in result.views.values()) < sum(
        control_views[view]["falsePositives"] for view in VIEWS
    )
