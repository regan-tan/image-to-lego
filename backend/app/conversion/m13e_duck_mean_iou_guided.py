"""Linear first-order mean-IoU surrogate for the offline M13E-B5 Duck pilot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from ortools.sat.python import cp_model

from app.conversion.m13d_tp_fp_feasibility_experiment import RASTER_PIXELS_PER_VIEW, VIEWS
from app.conversion.m13e_duck_iou_dominance import ORTOOLS_INT64_MAX

SURROGATE_SCALE: Final = 100_000_000
ROUNDING_POLICY: Final = "nearest integer; exact half values round away from zero"


@dataclass(frozen=True, slots=True)
class LinearizedMeanIouObjective:
    """Quantized first-order objective coefficients and their exact references."""

    scale: int
    rounding_policy: str
    true_positive_coefficients: Mapping[str, int]
    false_positive_coefficients: Mapping[str, int]
    exact_true_positive_coefficients: Mapping[str, Fraction]
    exact_false_positive_coefficients: Mapping[str, Fraction]
    coefficient_errors: Mapping[str, Mapping[str, Fraction]]
    theoretical_absolute_bound: int


def linearized_mean_iou_objective(
    source_foreground: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
    *,
    scale: int = SURROGATE_SCALE,
) -> LinearizedMeanIouObjective:
    """Quantize J's variable coefficients with checked, deterministic integer arithmetic."""
    if not isinstance(scale, int) or isinstance(scale, bool) or scale <= 0:
        raise ValueError("The surrogate scale must be a positive integer.")
    tp_coefficients: dict[str, int] = {}
    fp_coefficients: dict[str, int] = {}
    exact_tp: dict[str, Fraction] = {}
    exact_fp: dict[str, Fraction] = {}
    errors: dict[str, dict[str, Fraction]] = {}
    for view in VIEWS:
        source = source_foreground[view]
        control_tp = control_views[view]["truePositives"]
        control_fp = control_views[view]["falsePositives"]
        denominator = source + control_fp
        tp = Fraction(scale, denominator)
        fp = Fraction(-scale * control_tp, denominator * denominator)
        tp_coefficients[view] = _round_fraction_away_from_zero(tp)
        fp_coefficients[view] = _round_fraction_away_from_zero(fp)
        exact_tp[view], exact_fp[view] = tp, fp
        errors[view] = {
            "truePositive": Fraction(tp_coefficients[view]) - tp,
            "falsePositive": Fraction(fp_coefficients[view]) - fp,
        }
    bound = sum(
        RASTER_PIXELS_PER_VIEW * (abs(tp_coefficients[view]) + abs(fp_coefficients[view]))
        for view in VIEWS
    )
    if bound > ORTOOLS_INT64_MAX:
        raise ValueError("The surrogate objective theoretical bound exceeds OR-Tools int64.")
    return LinearizedMeanIouObjective(
        scale,
        ROUNDING_POLICY,
        tp_coefficients,
        fp_coefficients,
        exact_tp,
        exact_fp,
        errors,
        bound,
    )


def add_linearized_mean_iou_objective(
    model: cp_model.CpModel,
    true_positives: Mapping[str, cp_model.LinearExpr],
    false_positives: Mapping[str, cp_model.LinearExpr],
    objective: LinearizedMeanIouObjective,
) -> None:
    """Maximize the quantized variable terms of the first-order surrogate J."""
    model.maximize(
        cp_model.LinearExpr.Sum(
            [
                objective.true_positive_coefficients[view] * true_positives[view]
                + objective.false_positive_coefficients[view] * false_positives[view]
                for view in VIEWS
            ]
        )
    )


def surrogate_value(
    views: Mapping[str, Mapping[str, int]], objective: LinearizedMeanIouObjective
) -> int:
    """Evaluate the same quantized variable objective independently."""
    return sum(
        objective.true_positive_coefficients[view] * views[view]["truePositives"]
        + objective.false_positive_coefficients[view] * views[view]["falsePositives"]
        for view in VIEWS
    )


def _round_fraction_away_from_zero(value: Fraction) -> int:
    """Round an exact fraction to its nearest integer, resolving ties away from zero."""
    magnitude, remainder = divmod(abs(value.numerator), value.denominator)
    if 2 * remainder >= value.denominator:
        magnitude += 1
    return magnitude if value >= 0 else -magnitude
