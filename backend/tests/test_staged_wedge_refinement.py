from __future__ import annotations

import pytest
import trimesh
from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.buildability import analyze_buildability, is_evaluated_rectangular
from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.staged_wedge_refinement import (
    _add_local_support_constraints,
    _Candidate,
    _possible_supporters,
    refine_wedges,
)
from app.conversion.wedge_41769_41770 import footprint_microcells, transformed_footprint


def _candidate(placement: BrickPlacement) -> _Candidate:
    return _Candidate(placement, frozenset())


def _support_model(
    candidates: tuple[_Candidate, ...], frozen: tuple[BrickPlacement, ...] = ()
) -> tuple[cp_model.CpModel, tuple[cp_model.IntVar, ...]]:
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"candidate_{index}") for index in range(len(candidates)))
    _add_local_support_constraints(model, selected, candidates, frozen)
    return model, selected


def test_wedge_handedness_and_rotations_have_distinct_footprints() -> None:
    right = footprint_microcells(transformed_footprint("41769", 0, 0, 0))
    left = footprint_microcells(transformed_footprint("41770", 0, 0, 0))
    rotated = footprint_microcells(transformed_footprint("41769", 0, 0, 90))

    assert right != left
    assert right != rotated


def test_local_refinement_selects_a_wedge_without_changing_frozen_piece() -> None:
    baseline = BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0)
    frozen = BrickPlacement(PART_BY_ID["3001"], GridPosition(8, 0, 0), 0)
    target_cells = {GridPosition(x, y, z) for z in range(3) for y in range(2) for x in range(4)}
    target_cells.update(
        GridPosition(x, y, z) for z in range(3) for y in range(2) for x in range(8, 12)
    )
    target_top = set(footprint_microcells(transformed_footprint("41769", 0, 0, 0)))
    target_top.update((x, y) for y in range(8) for x in range(32, 48))

    result = refine_wedges(
        (baseline, frozen),
        target_cells,
        target_top,
        lambda proposal: any(placement.brick_type.part_id == "41769" for placement in proposal),
    )

    assert result.attempted
    assert any(attempt.accepted for attempt in result.attempted)
    assert frozen in result.placements
    assert any(placement.brick_type.part_id == "41769" for placement in result.placements)


def test_rejected_local_refinement_keeps_the_baseline() -> None:
    baseline = BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0)
    target_cells = {GridPosition(x, y, z) for z in range(3) for y in range(2) for x in range(4)}
    target_top = footprint_microcells(transformed_footprint("41769", 0, 0, 0))

    result = refine_wedges((baseline,), target_cells, target_top, lambda _: False)

    assert result.placements == (baseline,)
    assert result.attempted
    assert not any(attempt.accepted for attempt in result.attempted)


def test_selected_rectangle_requires_valid_evaluated_support() -> None:
    frozen_base = BrickPlacement(PART_BY_ID["3020"], GridPosition(8, 0, 0), 0)
    upper_plate = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model((_candidate(upper_plate),), (frozen_base,))
    model.add(selected[0] == 1)

    assert cp_model.CpSolver().solve(model) == cp_model.INFEASIBLE


def test_alternative_rectangular_supporter_is_allowed() -> None:
    original_lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0)
    alternative_lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(1, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(1, 0, 1), 0)
    model, selected = _support_model(
        (_candidate(original_lower), _candidate(alternative_lower), _candidate(upper))
    )
    model.add(selected[0] == 0)
    model.add(selected[1] == 1)
    model.add(selected[2] == 1)

    assert cp_model.CpSolver().solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}


def test_frozen_outside_dependent_retains_local_support() -> None:
    lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0)
    frozen_upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model((_candidate(lower),), (frozen_upper,))
    model.add(selected[0] == 0)

    assert cp_model.CpSolver().solve(model) == cp_model.INFEASIBLE


def test_baseline_local_assignment_remains_feasible() -> None:
    lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model((_candidate(lower), _candidate(upper)))
    model.add(selected[0] == 1)
    model.add(selected[1] == 1)

    assert cp_model.CpSolver().solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}


def test_wedge_cannot_satisfy_support_constraint() -> None:
    lower_wedge = BrickPlacement(PART_BY_ID["41769"], GridPosition(0, 0, 0), 0)
    unrelated_base = BrickPlacement(PART_BY_ID["3020"], GridPosition(8, 0, 0), 0)
    upper_plate = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model(
        (_candidate(lower_wedge), _candidate(unrelated_base), _candidate(upper_plate))
    )
    model.add(selected[0] == 1)
    model.add(selected[2] == 1)

    assert cp_model.CpSolver().solve(model) == cp_model.INFEASIBLE
    assert not is_evaluated_rectangular(lower_wedge)


def test_unsupported_local_proposal_becomes_infeasible() -> None:
    frozen_base = BrickPlacement(PART_BY_ID["3020"], GridPosition(8, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model((_candidate(upper),), (frozen_base,))
    model.add(selected[0] == 1)

    assert cp_model.CpSolver().solve(model) == cp_model.INFEASIBLE


def test_valid_wedge_replacement_with_rectangle_support_can_solve() -> None:
    lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0)
    wedge = BrickPlacement(PART_BY_ID["41769"], GridPosition(4, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model(
        (_candidate(lower), _candidate(wedge), _candidate(upper))
    )
    for variable in selected:
        model.add(variable == 1)

    assert cp_model.CpSolver().solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}


def test_buildability_validator_agrees_with_local_support_constraints() -> None:
    frozen_base = BrickPlacement(PART_BY_ID["3020"], GridPosition(8, 0, 0), 0)
    lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    model, selected = _support_model((_candidate(lower), _candidate(upper)), (frozen_base,))
    model.add(selected[0] == 1)
    model.add(selected[1] == 1)

    assert cp_model.CpSolver().solve(model) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
    assert analyze_buildability((frozen_base, lower, upper)).unsupported_placement_count == 0
    assert analyze_buildability((frozen_base, upper)).unsupported_placement_count == 1


def test_possible_supporters_are_deterministic() -> None:
    lower = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 1), 0)
    candidates = (_candidate(lower), _candidate(upper))

    assert _possible_supporters(candidates, ()) == _possible_supporters(candidates, ())


def test_production_path_does_not_import_or_run_staged_refinement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_: object) -> object:
        raise AssertionError("Production conversion must not run staged refinement.")

    monkeypatch.setattr("app.conversion.staged_wedge_refinement.refine_wedges", fail_if_called)
    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")

    model = core.convert_glb(source, core.ConversionSettings(target_parts=8))

    assert model.metadata.algorithm_version == core.SURFACE_GRID_V4
