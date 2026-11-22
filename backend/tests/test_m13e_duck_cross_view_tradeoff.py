from __future__ import annotations

from fractions import Fraction

import pytest

from app.conversion import core
from app.conversion.m13e_duck_cross_view_tradeoff import (
    arm_thresholds,
    fixed_frame_mean_iou_fraction,
    threshold_holds,
    thresholds_hold,
)
from app.conversion.m13e_duck_iou_dominance import build_iou_dominance_model
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate
from scripts.run_m13e_duck_cross_view_tradeoff import _classification, _summary_status


def _views(front: int, side: int, top: int) -> dict[str, dict[str, int]]:
    return {
        view: {
            "truePositives": true_positives,
            "falsePositives": 0,
            "falseNegatives": 10_000 - true_positives,
        }
        for view, true_positives in (("front", front), ("side", side), ("top", top))
    }


def test_arm_thresholds_use_the_predeclared_gain_and_loss_formula() -> None:
    assert arm_thresholds("front", 25) == {"front": 51, "side": -25, "top": -25}


def test_exact_threshold_accepts_the_integer_boundary_without_float_rounding() -> None:
    assert threshold_holds(10_000, 5_000, 0, 5_021, 0, 21)
    assert not threshold_holds(10_000, 5_000, 0, 5_020, 0, 21)
    assert threshold_holds(10_000, 5_000, 0, 4_990, 0, -10)
    assert not threshold_holds(10_000, 5_000, 0, 4_989, 0, -10)


def test_predeclared_arm_implies_a_strict_exact_mean_improvement() -> None:
    control = _views(5_000, 5_000, 5_000)
    candidate = _views(5_021, 4_990, 4_990)
    thresholds = arm_thresholds("front", 10)
    source = {view: 10_000 for view in control}

    assert thresholds_hold(candidate, source, control, thresholds)
    assert fixed_frame_mean_iou_fraction(candidate) > fixed_frame_mean_iou_fraction(control)
    assert fixed_frame_mean_iou_fraction(candidate) - fixed_frame_mean_iou_fraction(
        control
    ) == Fraction(1, 30_000)


def test_invalid_target_or_unpredeclared_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="target view"):
        arm_thresholds("diagonal", 10)
    with pytest.raises(ValueError, match="predeclared"):
        arm_thresholds("front", 11)


def test_model_rejects_threshold_coefficients_outside_ortools_int64() -> None:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(0, 0, 0), 0)
    candidate = _Candidate(placement, frozenset({placement.position}))
    source = {(view, 0, 0) for view in ("front", "side", "top")}

    with pytest.raises(ValueError, match="int64"):
        build_iou_dominance_model(
            candidates=(candidate,),
            candidate_rasters=({("front", 0, 0)},),
            source_pixels=source,
            locked_pixels=(),
            required_pixels=(),
            locked_placements=(),
            target_cells={placement.position},
            fixed_coverage_pixels=(),
            control_views={
                view: {"truePositives": 0, "falsePositives": 0} for view in _views(1, 1, 1)
            },
            max_parts=1,
            require_strict_improvement=False,
            iou_change_basis_points={view: 1 << 63 for view in _views(1, 1, 1)},
        )


def test_arm_and_summary_classifications_are_scoped_to_the_finite_pilot() -> None:
    assert _classification({"status": "INFEASIBLE"}) == "PROVEN_INFEASIBLE_WITHIN_TESTED_ARM"
    assert _classification({"status": "UNKNOWN"}) == "INCONCLUSIVE"
    assert _summary_status([{"classification": "PROVEN_INFEASIBLE_WITHIN_TESTED_ARM"}]) == (
        "INCONCLUSIVE"
    )
    assert _summary_status([{"classification": "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT"}]) == (
        "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT"
    )
