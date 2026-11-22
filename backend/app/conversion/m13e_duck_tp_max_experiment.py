"""Classification and metric helpers for the offline M13E-B1 Duck experiment."""

from __future__ import annotations

from collections.abc import Mapping

from app.conversion.m13d_tp_fp_feasibility_experiment import VIEWS, FeasibilityResult


def classify_tp_max_result(
    result: FeasibilityResult, control_views: Mapping[str, Mapping[str, int]]
) -> str:
    """Classify a TP-maximization result without claiming a global IoU optimum."""
    if result.status == "INFEASIBLE":
        return "INFEASIBLE_DESPITE_VERIFIED_CONTROL"
    if result.status not in {"OPTIMAL", "FEASIBLE"}:
        return "UNKNOWN"
    improved = total_true_positives(result.views) > total_true_positives(control_views)
    if result.status == "OPTIMAL":
        return "OPTIMAL_WITH_TP_IMPROVEMENT" if improved else "OPTIMAL_WITH_UNCHANGED_TP"
    return "FEASIBLE_WITH_TP_IMPROVEMENT" if improved else "FEASIBLE_WITH_UNCHANGED_TP"


def total_true_positives(views: Mapping[str, Mapping[str, int]]) -> int:
    """Return a separately extracted total TP across the three fixed-frame views."""
    return sum(views[view]["truePositives"] for view in VIEWS)


def fixed_frame_mean_iou(views: Mapping[str, Mapping[str, int]]) -> float:
    """Return the mean per-view IoU for the fixed 128px frame only."""
    values = []
    for view in VIEWS:
        metrics = views[view]
        denominator = (
            metrics["truePositives"] + metrics["falsePositives"] + metrics["falseNegatives"]
        )
        values.append(1.0 if denominator == 0 else metrics["truePositives"] / denominator)
    return round(sum(values) / len(values), 6)
