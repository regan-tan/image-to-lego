"""Definitions and result checks for the opt-in M13E-B2 Duck pilot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.conversion.m13d_tp_fp_feasibility_experiment import VIEWS

SOURCE_FOREGROUND = {"front": 7895, "side": 7075, "top": 7255}
CONTROL_VIEWS = {
    "front": {"truePositives": 7803, "falsePositives": 3940},
    "side": {"truePositives": 6558, "falsePositives": 4002},
    "top": {"truePositives": 7227, "falsePositives": 5793},
}
CONTROL_AGGREGATE_FP = 13_735


@dataclass(frozen=True, slots=True)
class FrontierRow:
    label: str
    basis_points: int
    allowances: Mapping[str, int]


def calculate_tp_loss_allowances(
    source_foreground: Mapping[str, int], basis_points: int
) -> dict[str, int]:
    """Calculate floor(source pixels * percentage) using integer basis points."""
    if not isinstance(basis_points, int) or isinstance(basis_points, bool) or basis_points < 0:
        raise ValueError("TP-loss percentage must be a nonnegative integer number of basis points.")
    if set(source_foreground) != set(VIEWS):
        raise ValueError("Source foreground counts must contain exactly the fixed-frame views.")
    allowances: dict[str, int] = {}
    for view in VIEWS:
        pixels = source_foreground[view]
        if not isinstance(pixels, int) or isinstance(pixels, bool) or pixels < 0:
            raise ValueError(f"Invalid source foreground count for {view}.")
        allowances[view] = pixels * basis_points // 10_000
    return allowances


def predeclared_rows() -> tuple[FrontierRow, ...]:
    """Return the five locked B2 rows and reject any accidental arithmetic drift."""
    definitions = (("0%", 0), ("0.5%", 50), ("1%", 100), ("2%", 200), ("5%", 500))
    expected = (
        {"front": 0, "side": 0, "top": 0},
        {"front": 39, "side": 35, "top": 36},
        {"front": 78, "side": 70, "top": 72},
        {"front": 157, "side": 141, "top": 145},
        {"front": 394, "side": 353, "top": 362},
    )
    rows = tuple(
        FrontierRow(
            label, basis_points, calculate_tp_loss_allowances(SOURCE_FOREGROUND, basis_points)
        )
        for label, basis_points in definitions
    )
    if tuple(dict(row.allowances) for row in rows) != expected:
        raise RuntimeError("The predeclared M13E-B2 allowance table is inconsistent.")
    return rows


def tp_floors(
    control_views: Mapping[str, Mapping[str, int]], allowances: Mapping[str, int]
) -> dict[str, int]:
    """Return the only B2 model change: each Control TP floor minus its allowance."""
    if set(control_views) != set(VIEWS) or set(allowances) != set(VIEWS):
        raise ValueError("TP floors require all fixed-frame views.")
    return {view: control_views[view]["truePositives"] - allowances[view] for view in VIEWS}


def classify_frontier_status(status: str) -> str:
    """Report solver status without treating a bound or hint as an incumbent."""
    return {
        "OPTIMAL": "OPTIMAL",
        "FEASIBLE": "VERIFIED_INCUMBENT",
        "UNKNOWN": "UNKNOWN",
        "INFEASIBLE": "INFEASIBLE_DESPITE_VERIFIED_CONTROL",
    }.get(status, "UNKNOWN")


def optimal_fp_is_nested(records: Sequence[Mapping[str, object]]) -> bool:
    """Check monotonic minimum FP only across rows whose optimum was proven."""
    previous: int | None = None
    for record in records:
        if record.get("status") != "OPTIMAL":
            continue
        solver = record.get("solver")
        if not isinstance(solver, Mapping) or not isinstance(solver.get("objective_value"), int):
            return False
        objective = solver["objective_value"]
        if previous is not None and objective > previous:
            return False
        previous = objective
    return True


def verified_frozen_improvement(records: Sequence[Mapping[str, object]]) -> bool:
    """Return true only for independently verified incumbents with higher frozen mean IoU."""
    for record in records:
        if record.get("status") not in {"OPTIMAL", "FEASIBLE"}:
            continue
        result = record.get("result")
        if not isinstance(result, Mapping):
            continue
        change = result.get("frozenMeanIouChangeFromControl")
        if isinstance(change, int | float) and change > 0:
            return True
    return False
