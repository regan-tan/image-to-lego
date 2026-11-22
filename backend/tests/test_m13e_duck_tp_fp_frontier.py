from __future__ import annotations

import pytest

from app.conversion import core
from app.conversion.m13d_tp_fp_feasibility_experiment import solve_tp_fp_feasibility
from app.conversion.m13e_duck_tp_fp_frontier import (
    CONTROL_AGGREGATE_FP,
    SOURCE_FOREGROUND,
    calculate_tp_loss_allowances,
    classify_frontier_status,
    optimal_fp_is_nested,
    predeclared_rows,
    tp_floors,
    verified_frozen_improvement,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _control_views() -> dict[str, dict[str, int]]:
    return {
        "front": {"truePositives": 1, "falsePositives": 0},
        "side": {"truePositives": 0, "falsePositives": 0},
        "top": {"truePositives": 0, "falsePositives": 0},
    }


def test_predeclared_allowances_use_exact_integer_basis_point_arithmetic() -> None:
    assert calculate_tp_loss_allowances(SOURCE_FOREGROUND, 50) == {
        "front": 39,
        "side": 35,
        "top": 36,
    }
    assert [dict(row.allowances) for row in predeclared_rows()] == [
        {"front": 0, "side": 0, "top": 0},
        {"front": 39, "side": 35, "top": 36},
        {"front": 78, "side": 70, "top": 72},
        {"front": 157, "side": 141, "top": 145},
        {"front": 394, "side": 353, "top": 362},
    ]
    with pytest.raises(ValueError, match="exactly"):
        calculate_tp_loss_allowances({"front": 1}, 50)


def test_tp_allowance_relaxes_only_floor_and_preserves_fp_cap() -> None:
    candidate = _candidate(0)
    kwargs = {
        "candidates": (candidate,),
        "candidate_rasters": (set(),),
        "source_pixels": {("front", 0, 0)},
        "locked_pixels": (),
        "required_pixels": (),
        "locked_placements": (),
        "target_cells": {candidate.placement.position},
        "fixed_coverage_pixels": (),
        "control_views": _control_views(),
        "max_parts": 1,
    }
    strict = solve_tp_fp_feasibility(**kwargs)
    relaxed = solve_tp_fp_feasibility(
        **kwargs, tp_loss_allowances={"front": 1, "side": 0, "top": 0}
    )

    assert strict.status == "INFEASIBLE"
    assert relaxed.status == "OPTIMAL"
    assert relaxed.objective_value == 0
    assert relaxed.views["front"]["truePositives"] == 0
    assert relaxed.views["front"]["falsePositives"] == 0
    assert tp_floors(_control_views(), {"front": 1, "side": 0, "top": 0})["front"] == 0


def test_invalid_allowance_and_frontier_status_checks_fail_closed() -> None:
    candidate = _candidate(0)
    with pytest.raises(ValueError, match="exactly"):
        solve_tp_fp_feasibility(
            candidates=(candidate,),
            candidate_rasters=(set(),),
            source_pixels=(),
            locked_pixels=(),
            required_pixels=(),
            locked_placements=(),
            target_cells={candidate.placement.position},
            fixed_coverage_pixels=(),
            control_views=_control_views(),
            max_parts=1,
            tp_loss_allowances={"front": 0},
        )
    assert classify_frontier_status("OPTIMAL") == "OPTIMAL"
    assert classify_frontier_status("FEASIBLE") == "VERIFIED_INCUMBENT"
    assert classify_frontier_status("UNKNOWN") == "UNKNOWN"
    assert classify_frontier_status("INFEASIBLE") == "INFEASIBLE_DESPITE_VERIFIED_CONTROL"
    assert optimal_fp_is_nested(
        [
            {"status": "OPTIMAL", "solver": {"objective_value": CONTROL_AGGREGATE_FP}},
            {"status": "OPTIMAL", "solver": {"objective_value": 13_000}},
        ]
    )
    assert not optimal_fp_is_nested(
        [
            {"status": "OPTIMAL", "solver": {"objective_value": 13_000}},
            {"status": "OPTIMAL", "solver": {"objective_value": CONTROL_AGGREGATE_FP}},
        ]
    )
    assert verified_frozen_improvement(
        [{"status": "OPTIMAL", "result": {"frozenMeanIouChangeFromControl": 0.001}}]
    )
    assert not verified_frozen_improvement(
        [{"status": "UNKNOWN", "result": {"frozenMeanIouChangeFromControl": 1.0}}]
    )
