from __future__ import annotations

from fractions import Fraction

import pytest

from app.conversion.m13e_duck_cross_view_tradeoff import fixed_frame_mean_iou_fraction
from app.conversion.m13e_duck_mean_iou_guided import (
    ROUNDING_POLICY,
    SURROGATE_SCALE,
    linearized_mean_iou_objective,
    surrogate_value,
)


def _views(
    front: tuple[int, int], side: tuple[int, int], top: tuple[int, int]
) -> dict[str, dict[str, int]]:
    return {
        view: {
            "truePositives": values[0],
            "falsePositives": values[1],
            "falseNegatives": 5 - values[0],
        }
        for view, values in (("front", front), ("side", side), ("top", top))
    }


def test_duck_coefficients_are_exactly_quantized_with_the_declared_policy() -> None:
    objective = linearized_mean_iou_objective(
        {"front": 7895, "side": 7075, "top": 7255},
        {
            "front": {"truePositives": 7803, "falsePositives": 3940},
            "side": {"truePositives": 6558, "falsePositives": 4002},
            "top": {"truePositives": 7227, "falsePositives": 5793},
        },
    )

    assert objective.scale == SURROGATE_SCALE
    assert objective.rounding_policy == ROUNDING_POLICY
    assert objective.true_positive_coefficients == {"front": 8450, "side": 9028, "top": 7664}
    assert objective.false_positive_coefficients == {"front": -5571, "side": -5345, "top": -4245}
    assert all(
        abs(error) <= Fraction(1, 2)
        for errors in objective.coefficient_errors.values()
        for error in errors.values()
    )


def test_surrogate_can_increase_while_exact_mean_iou_decreases() -> None:
    control = _views((1, 0), (1, 0), (1, 0))
    candidate = _views((0, 0), (3, 3), (1, 0))
    objective = linearized_mean_iou_objective(
        {"front": 5, "side": 5, "top": 5},
        {
            view: {key: control[view][key] for key in ("truePositives", "falsePositives")}
            for view in control
        },
    )

    assert surrogate_value(candidate, objective) > surrogate_value(control, objective)
    assert fixed_frame_mean_iou_fraction(candidate) < fixed_frame_mean_iou_fraction(control)


def test_scale_and_int64_bound_are_validated() -> None:
    with pytest.raises(ValueError, match="positive"):
        linearized_mean_iou_objective(
            {"front": 1, "side": 1, "top": 1},
            {view: {"truePositives": 0, "falsePositives": 0} for view in ("front", "side", "top")},
            scale=0,
        )
