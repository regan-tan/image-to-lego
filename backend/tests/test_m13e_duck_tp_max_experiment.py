from __future__ import annotations

import pytest

from app.conversion import core
from app.conversion.m13d_tp_fp_feasibility_experiment import (
    FeasibilityResult,
    solve_tp_fp_feasibility,
    validate_view_metrics,
)
from app.conversion.m13e_duck_tp_max_experiment import (
    classify_tp_max_result,
    fixed_frame_mean_iou,
    total_true_positives,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _control_views() -> dict[str, dict[str, int]]:
    return {
        "front": {"truePositives": 1, "falsePositives": 1},
        "side": {"truePositives": 0, "falsePositives": 0},
        "top": {"truePositives": 0, "falsePositives": 0},
    }


def test_max_tp_preserves_per_view_floors_and_fp_caps() -> None:
    first, second = _candidate(0), _candidate(1)
    result = solve_tp_fp_feasibility(
        candidates=(first, second),
        candidate_rasters=(
            {("front", 0, 0), ("front", 9, 0)},
            {("front", 1, 0)},
        ),
        source_pixels={("front", 0, 0), ("front", 1, 0)},
        locked_pixels=(),
        required_pixels=(),
        locked_placements=(),
        target_cells={first.placement.position, second.placement.position},
        fixed_coverage_pixels=(),
        control_views=_control_views(),
        max_parts=2,
        objective_mode="max_tp",
    )

    assert result.status == "OPTIMAL"
    assert result.objective_value == 2
    assert result.views["front"] == {
        "truePositives": 2,
        "falsePositives": 1,
        "falseNegatives": 0,
    }
    assert classify_tp_max_result(result, _control_views()) == "OPTIMAL_WITH_TP_IMPROVEMENT"


def test_overlapping_rasters_count_tp_once_and_hints_do_not_change_constraints() -> None:
    first, second = _candidate(0), _candidate(1)
    kwargs = {
        "candidates": (first, second),
        "candidate_rasters": ({("front", 0, 0)}, {("front", 0, 0), ("front", 1, 0)}),
        "source_pixels": {("front", 0, 0), ("front", 1, 0)},
        "locked_pixels": (),
        "required_pixels": (),
        "locked_placements": (),
        "target_cells": {first.placement.position, second.placement.position},
        "fixed_coverage_pixels": (),
        "control_views": _control_views(),
        "max_parts": 2,
        "objective_mode": "max_tp",
    }
    no_hint = solve_tp_fp_feasibility(**kwargs)
    hinted = solve_tp_fp_feasibility(**kwargs, hint_selected_ids=(0,))

    assert no_hint.objective_value == hinted.objective_value == 2
    assert total_true_positives(no_hint.views) == 2
    validate_view_metrics(
        no_hint.views, {"front": 2, "side": 0, "top": 0}, total_tp=no_hint.objective_value
    )


def test_invalid_tp_aggregate_and_statuses_fail_closed_or_remain_inconclusive() -> None:
    views = {
        "front": {"truePositives": 1, "falsePositives": 0, "falseNegatives": 0},
        "side": {"truePositives": 0, "falsePositives": 0, "falseNegatives": 0},
        "top": {"truePositives": 0, "falsePositives": 0, "falseNegatives": 0},
    }
    with pytest.raises(ValueError, match="aggregate TP"):
        validate_view_metrics(views, {"front": 1, "side": 0, "top": 0}, total_tp=2)

    assert fixed_frame_mean_iou(views) == 1.0
    control = _control_views()
    improved = FeasibilityResult(
        "FEASIBLE",
        30.0,
        0.0,
        2,
        3,
        (),
        {
            "front": {"truePositives": 2, "falsePositives": 1},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
    )
    unchanged = FeasibilityResult(
        "OPTIMAL",
        30.0,
        0.0,
        1,
        1,
        (),
        {
            "front": {"truePositives": 1, "falsePositives": 1},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
    )

    assert classify_tp_max_result(improved, control) == "FEASIBLE_WITH_TP_IMPROVEMENT"
    assert classify_tp_max_result(unchanged, control) == "OPTIMAL_WITH_UNCHANGED_TP"
    assert (
        classify_tp_max_result(FeasibilityResult("UNKNOWN", 30.0, 0.0, None, None, (), {}), control)
        == "UNKNOWN"
    )
    assert (
        classify_tp_max_result(
            FeasibilityResult("INFEASIBLE", 30.0, 0.0, None, None, (), {}), control
        )
        == "INFEASIBLE_DESPITE_VERIFIED_CONTROL"
    )
