from __future__ import annotations

import pytest

from app.conversion import core
from app.conversion.m13d_tp_fp_feasibility_experiment import (
    FeasibilityResult,
    classify_result,
    solve_tp_fp_feasibility,
)
from app.conversion.m13e_duck_control_hint_experiment import (
    complete_selection_hint,
    control_candidate_indices,
    model_fingerprint,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _solve(hint: tuple[int, ...] | None = None):
    candidate = _candidate(0)
    return solve_tp_fp_feasibility(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0)},
        locked_pixels=(),
        required_pixels={("front", 0, 0)},
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
        max_parts=1,
        hint_selected_ids=hint,
    )


def test_control_ids_map_to_candidate_order_and_complete_hint_values() -> None:
    first, second = _candidate(0), _candidate(1)
    indices = control_candidate_indices(
        (first, second),
        (
            "3024@1,0,0:0",
            "3024@0,0,0:0",
        ),
    )

    assert indices == (1, 0)
    assert complete_selection_hint(2, indices) == (1, 1)


def test_control_mapping_rejects_missing_or_duplicate_ids() -> None:
    candidate = _candidate(0)
    with pytest.raises(ValueError, match="membership"):
        control_candidate_indices((candidate,), ("3024@9,0,0:0",))
    with pytest.raises(ValueError, match="duplicated"):
        control_candidate_indices((candidate,), ("3024@0,0,0:0", "3024@0,0,0:0"))


def test_invalid_hint_and_forced_invalid_control_assignment_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _solve((0, 0))

    result = _solve()
    assert result.status == "OPTIMAL"

    candidate = _candidate(0)
    forced = solve_tp_fp_feasibility(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0)},
        locked_pixels=(),
        required_pixels={("front", 0, 0)},
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
        max_parts=1,
        required_selected_ids=(),
    )
    assert forced.status == "INFEASIBLE"


def test_hint_is_guidance_and_preserves_proven_optimum() -> None:
    no_hint = _solve()
    hinted = _solve((0,))

    assert no_hint.status == "OPTIMAL"
    assert hinted.status == "OPTIMAL"
    assert no_hint.objective_value == hinted.objective_value == 0
    assert hinted.selected_ids == (0,)
    assert hinted.views["front"] == {
        "truePositives": 1,
        "falsePositives": 0,
        "falseNegatives": 0,
    }


def test_unknown_is_inconclusive_and_a_hint_is_not_an_incumbent() -> None:
    unknown = FeasibilityResult("UNKNOWN", 30.0, 0.0, None, None, (), {})
    control_views = {
        "front": {"truePositives": 0, "falsePositives": 0},
        "side": {"truePositives": 0, "falsePositives": 0},
        "top": {"truePositives": 0, "falsePositives": 0},
    }

    assert classify_result(unknown, control_views) == "INCONCLUSIVE"

    candidate = _candidate(0)
    hinted_but_infeasible = solve_tp_fp_feasibility(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0)},
        locked_pixels=(),
        required_pixels={("front", 0, 0)},
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
        max_parts=1,
        hint_selected_ids=(0,),
        required_selected_ids=(),
    )
    assert hinted_but_infeasible.status == "INFEASIBLE"
    assert hinted_but_infeasible.selected_ids == ()


def test_model_fingerprint_excludes_hint_assignment() -> None:
    fingerprint = model_fingerprint(
        candidate_ids=("3024@0,0,0:0",),
        locked_ids=(),
        required_pixels={("front", 0, 0)},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
    )

    assert fingerprint == model_fingerprint(
        candidate_ids=("3024@0,0,0:0",),
        locked_ids=(),
        required_pixels={("front", 0, 0)},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
    )
