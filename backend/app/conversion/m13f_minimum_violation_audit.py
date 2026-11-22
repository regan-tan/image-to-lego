"""Exact helpers for M13F-B3's optimum-score minimum-violation study."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from ortools.sat.python import cp_model

from app.conversion.m13e_duck_iou_dominance import IoUDominanceModel
from app.conversion.m13e_duck_mean_iou_guided import (
    LinearizedMeanIouObjective,
    surrogate_value,
)
from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement


def add_exact_surrogate_target(
    built: IoUDominanceModel,
    objective: LinearizedMeanIouObjective,
    target: int,
) -> None:
    """Require the B5 quantized objective to equal one historical target exactly."""
    if not isinstance(target, int) or isinstance(target, bool):
        raise ValueError("The exact surrogate target must be an integer.")
    expression = cp_model.LinearExpr.Sum(
        [
            objective.true_positive_coefficients[view] * built.true_positives[view]
            + objective.false_positive_coefficients[view] * built.false_positives[view]
            for view in ("front", "side", "top")
        ]
    )
    built.model.add(expression == target)


def add_minimum_violation_objective(
    model: cp_model.CpModel, violations: Sequence[cp_model.IntVar]
) -> None:
    """Minimize the already exact coarse-violation indicators."""
    if not violations:
        raise ValueError("At least one coarse-violation indicator is required.")
    model.minimize(cp_model.LinearExpr.Sum(violations))


def independently_count_violations(
    requirements: Sequence[CoarseRequirement], selected_ids: Collection[int]
) -> int:
    """Count unmet requirements without consulting CP-SAT's indicator values."""
    selected = frozenset(selected_ids)
    return sum(
        not requirement.covered_by_locked_geometry
        and not selected.intersection(requirement.candidate_ids)
        for requirement in requirements
    )


def exact_surrogate_matches(
    views: Mapping[str, Mapping[str, int]],
    objective: LinearizedMeanIouObjective,
    target: int,
) -> bool:
    """Evaluate target equality separately from the solver model."""
    return surrogate_value(views, objective) == target


def minimum_violation_conclusion(status: str) -> str:
    """State only the conclusion justified by a CP-SAT terminal status."""
    return {
        "OPTIMAL": "PROVEN_MINIMUM",
        "FEASIBLE": "UPPER_AND_LOWER_BOUNDS_ONLY",
        "INFEASIBLE": "TARGET_SCORE_INFEASIBLE",
        "UNKNOWN": "INCONCLUSIVE",
    }.get(status, "INCONCLUSIVE")
