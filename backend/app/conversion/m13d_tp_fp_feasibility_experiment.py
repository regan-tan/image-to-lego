"""Opt-in CP-SAT experiment for M13D Stage B; not used by production conversion."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    status: str
    deterministic_time_seconds: float
    runtime_seconds: float
    objective_value: int | None
    best_objective_bound: int | None
    selected_ids: tuple[int, ...]
    views: Mapping[str, Mapping[str, int]]


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
) -> FeasibilityResult:
    """Minimize exact fixed-frame FP while retaining each Control view's TP/FP bounds."""
    if deterministic_time_seconds <= 0:
        raise ValueError("The deterministic time budget must be positive.")
    if len(candidates) != len(candidate_rasters):
        raise ValueError("Candidates and raster footprints must have matching lengths.")
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(len(candidates)))
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
        model.add(tp >= baseline["truePositives"])
        model.add(fp <= baseline["falsePositives"])
        tp_by_view[view] = tp
        fp_by_view[view] = fp
        source_foreground_by_view[view] = len(source_view)
    total_fp = cp_model.LinearExpr.Sum(list(fp_by_view.values()))
    model.minimize(total_fp)
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = deterministic_time_seconds
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    status = solver.status_name(solver.solve(model))
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return FeasibilityResult(
            status, deterministic_time_seconds, solver.wall_time, None, None, (), {}
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
    validate_view_metrics(values, source_foreground_by_view, total_fp=objective_value)
    return FeasibilityResult(
        status,
        deterministic_time_seconds,
        solver.wall_time,
        objective_value,
        int(round(solver.best_objective_bound)),
        tuple(index for index, variable in enumerate(selected) if solver.boolean_value(variable)),
        values,
    )


def validate_view_metrics(
    views: Mapping[str, Mapping[str, int]],
    source_foreground_by_view: Mapping[str, int],
    *,
    total_fp: int | None = None,
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
    if total_fp is not None:
        if not isinstance(total_fp, int) or isinstance(total_fp, bool) or total_fp < 0:
            raise ValueError("Aggregate FP must be a nonnegative integer.")
        extracted_total = sum(views[view]["falsePositives"] for view in VIEWS)
        if total_fp != extracted_total:
            raise ValueError("Solver aggregate FP does not equal the per-view FP sum.")


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
