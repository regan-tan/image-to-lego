"""Exact arithmetic for the offline M13E-B4 cross-view trade-off pilot."""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction
from typing import Final

from app.conversion.m13d_tp_fp_feasibility_experiment import VIEWS
from app.conversion.m13e_duck_iou_dominance import IOU_BASIS_POINT_SCALE

TRADEOFF_BUDGETS: Final = (10, 25, 50)


def arm_thresholds(target_view: str, loss_budget_basis_points: int) -> dict[str, int]:
    """Return one B4 arm's signed absolute-IoU thresholds in basis points."""
    if target_view not in VIEWS:
        raise ValueError("The target view must be one of the fixed-frame views.")
    if loss_budget_basis_points not in TRADEOFF_BUDGETS:
        raise ValueError("The loss budget is not one of the predeclared B4 values.")
    return {
        view: 2 * loss_budget_basis_points + 1 if view == target_view else -loss_budget_basis_points
        for view in VIEWS
    }


def threshold_holds(
    source_foreground: int,
    control_tp: int,
    control_fp: int,
    tp: int,
    fp: int,
    basis_points: int,
) -> bool:
    """Evaluate the specified B4 threshold using only integer arithmetic."""
    denominator = source_foreground + control_fp
    return IOU_BASIS_POINT_SCALE * denominator * tp >= (
        IOU_BASIS_POINT_SCALE * control_tp + basis_points * denominator
    ) * (source_foreground + fp)


def thresholds_hold(
    views: Mapping[str, Mapping[str, int]],
    source_foreground: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
    thresholds: Mapping[str, int],
) -> bool:
    """Validate all three B4 arms' exact threshold inequalities."""
    return all(
        threshold_holds(
            source_foreground[view],
            control_views[view]["truePositives"],
            control_views[view]["falsePositives"],
            views[view]["truePositives"],
            views[view]["falsePositives"],
            thresholds[view],
        )
        for view in VIEWS
    )


def fixed_frame_mean_iou_fraction(views: Mapping[str, Mapping[str, int]]) -> Fraction:
    """Return the mean of the three fixed-frame IoUs without float rounding."""
    return sum(
        (
            Fraction(
                values["truePositives"],
                values["truePositives"] + values["falsePositives"] + values["falseNegatives"],
            )
            for values in views.values()
        ),
        Fraction(),
    ) / len(VIEWS)
