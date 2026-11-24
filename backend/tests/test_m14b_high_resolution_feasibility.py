from __future__ import annotations

import json
from pathlib import Path

from app.conversion import core
from app.conversion.m14b_high_resolution_feasibility import (
    M14BInput,
    _rejected_placement_record,
    diagnose_and_construct_seed,
    run_experiment,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate
from scripts.run_m14b_high_resolution_feasibility import _write_interruption


def _prepared(*, baseline_x: int = 0) -> M14BInput:
    position = core.GridPosition(0, 0, 0)
    placement = core.BrickPlacement(PART_BY_ID["3024"], position, 0)
    return M14BInput(
        grid=core.GridSize(1, 1, 1),
        target_cells=frozenset({position}),
        required_pixels=frozenset({("front", 0, 0), ("side", 0, 0), ("top", 0, 0)}),
        locked=(),
        locked_cells=frozenset(),
        baseline_rectangles=(
            core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(baseline_x, 0, 0), 0),
        ),
        candidates_before_collision=1,
        candidates_after_collision=1,
        candidates_after_collision_filter=(_Candidate(placement, frozenset({position})),),
        candidates=(_Candidate(placement, frozenset({position})),),
        triangle_count=12,
        source_cells=1,
    )


def test_m14b_compares_identical_model_with_a_validated_complete_hint() -> None:
    result = run_experiment(
        _prepared(), max_parts=1, effective_grid_target=1, deterministic_time=1.0
    )

    warm_start = result["warmStart"]
    assert warm_start["validated"] is True
    assert warm_start["reason"] == "validated_against_stage_one_constraints"
    assert result["unhinted"]["status"] == "OPTIMAL"
    assert result["hinted"] is not None
    assert result["hinted"]["status"] == "OPTIMAL"
    assert result["unhinted"]["model"] == result["hinted"]["model"]
    assert result["unhinted"]["model"]["coverageVariables"] == 3


def test_m14b_does_not_add_a_hint_when_baseline_was_removed() -> None:
    result = run_experiment(
        _prepared(baseline_x=1), max_parts=1, effective_grid_target=1, deterministic_time=1.0
    )

    warm_start = result["warmStart"]
    assert warm_start["validated"] is False
    assert warm_start["reason"] == "no_meaningful_compatible_seed"
    assert result["hinted"] is None


def test_rejected_seed_placement_is_classified_from_actual_candidate_stages() -> None:
    prepared = _prepared(baseline_x=1)
    diagnostics = diagnose_and_construct_seed(prepared, (("front", 0, 0),), max_parts=1)

    assert diagnostics.rejected[0]["reason"] == "absent_from_initial_enumeration"


def test_seed_construction_adds_a_retained_direct_supporter_deterministically() -> None:
    lower = core.GridPosition(0, 0, 0)
    upper = core.GridPosition(0, 0, 1)
    lower_placement = core.BrickPlacement(PART_BY_ID["3024"], lower, 0)
    upper_placement = core.BrickPlacement(PART_BY_ID["3024"], upper, 0)
    lower_candidate = _Candidate(lower_placement, frozenset({lower}))
    upper_candidate = _Candidate(upper_placement, frozenset({upper}))
    prepared = M14BInput(
        core.GridSize(1, 1, 2),
        frozenset({lower, upper}),
        frozenset({("front", 0, 0), ("front", 0, 1)}),
        (),
        frozenset(),
        (upper_placement,),
        2,
        2,
        (lower_candidate, upper_candidate),
        (lower_candidate, upper_candidate),
        2,
        2,
    )

    first = diagnose_and_construct_seed(prepared, tuple(prepared.required_pixels), max_parts=2)
    second = diagnose_and_construct_seed(prepared, tuple(prepared.required_pixels), max_parts=2)

    assert first.selected_ids == second.selected_ids == (0, 1)
    assert first.coverage_pixels == 2


def test_seed_construction_fails_closed_when_support_chain_exceeds_part_cap() -> None:
    lower = core.GridPosition(0, 0, 0)
    upper = core.GridPosition(0, 0, 1)
    lower_placement = core.BrickPlacement(PART_BY_ID["3024"], lower, 0)
    upper_placement = core.BrickPlacement(PART_BY_ID["3024"], upper, 0)
    lower_candidate = _Candidate(lower_placement, frozenset({lower}))
    upper_candidate = _Candidate(upper_placement, frozenset({upper}))
    prepared = M14BInput(
        core.GridSize(1, 1, 2),
        frozenset({lower, upper}),
        frozenset({("front", 0, 0), ("front", 0, 1)}),
        (),
        frozenset(),
        (upper_placement,),
        2,
        2,
        (lower_candidate, upper_candidate),
        (lower_candidate, upper_candidate),
        2,
        2,
    )

    diagnostics = diagnose_and_construct_seed(
        prepared, tuple(prepared.required_pixels), max_parts=1
    )

    assert diagnostics.selected_ids is None
    assert diagnostics.reason == "no_meaningful_compatible_seed"


def test_rejected_placement_with_missing_support_contact_reports_zero_supporters() -> None:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(1, 11, 2), 0)
    placement_id = "3024@1,11,2:0"

    record = _rejected_placement_record(
        placement,
        placement_id,
        {
            "initial_enumeration": {placement_id: 0},
            "locked_body_collision": {placement_id: 0},
            "support_reachability": {},
        },
        (_Candidate(placement, frozenset({placement.position})),),
        {},
        (((1.0, 11.0, 2.0),),),
        {},
    )

    assert record["reason"] == "removed_by_support_reachability"
    assert record["retainedPossibleSupporterCount"] == 0


def test_rejected_placement_mixed_support_contacts_counts_only_retained_supporters() -> None:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(1, 11, 2), 0)
    supporter = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(1, 11, 1), 0)
    placement_id = "3024@1,11,2:0"
    supporter_id = "3024@1,11,1:0"
    candidates = (
        _Candidate(placement, frozenset({placement.position})),
        _Candidate(supporter, frozenset({supporter.position})),
    )

    record = _rejected_placement_record(
        placement,
        placement_id,
        {
            "initial_enumeration": {placement_id: 0},
            "locked_body_collision": {placement_id: 0},
            "support_reachability": {},
        },
        candidates,
        {(1.0, 11.0, 2.0): (1,)},
        (((1.0, 11.0, 2.0), (2.0, 11.0, 2.0)), ()),
        {supporter_id: 1},
    )

    assert record["retainedPossibleSupporterCount"] == 1


def test_runner_records_keyboard_interruption_with_preflight(tmp_path: Path) -> None:
    output_path = tmp_path / "interrupted.json"
    preflight: dict[str, object] = {"sourceSha256": "test-sha"}

    _write_interruption(output_path, preflight)

    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "preflight": preflight,
        "schemaVersion": "m14b-high-resolution-run-state-v1",
        "status": "interrupted",
    }
