from __future__ import annotations

from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.m12a_wedge_mechanics import (
    EXPERIMENTAL_PART_ID,
    contains_body_point,
    physical_collision,
)
from app.conversion.m12c_wedge_fidelity_experiment import (
    WedgeCandidate,
    _add_wedge_collisions,
    _whole_body_cells,
    fixed_frame_score,
    optimise_with_wedge,
    preflight_wedge_candidates,
    validate_completed_arrangement,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import (
    _Candidate,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _support_reachable_candidates,
)


def _cells(width: int = 4, depth: int = 2) -> frozenset[core.GridPosition]:
    return frozenset(core.GridPosition(x, y, 0) for y in range(depth) for x in range(width))


def _wedge_prism() -> tuple[
    tuple[tuple[float, float, float], ...], tuple[tuple[int, int, int], ...]
]:
    vertices = (
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        (4.0, 1.0, 0.0),
        (0.0, 2.0, 0.0),
        (0.0, 0.0, 1.0),
        (4.0, 0.0, 1.0),
        (4.0, 1.0, 1.0),
        (0.0, 2.0, 1.0),
    )
    return vertices, (
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    )


def test_preflight_preserves_control_candidates_and_has_safe_wedge_coverage() -> None:
    target = _cells()
    rectangles, wedges, report = preflight_wedge_candidates(target_cells=target)
    expected = _support_reachable_candidates(
        _exclude_locked_body_collisions(_enumerate_candidates(target, core.BRICK_CATALOGUE), ()),
        target,
    )

    assert rectangles == expected
    assert report.control_candidate_count == len(expected)
    wedge = next(
        candidate
        for candidate in wedges
        if candidate.placement.position == core.GridPosition(0, 0, 0)
        and candidate.placement.orientation_degrees == 0
    )
    assert wedge.coverage_cells == frozenset(core.GridPosition(x, 0, 0) for x in range(4))
    assert _whole_body_cells(wedge.placement) == wedge.coverage_cells


def test_wedge_collision_is_analytic_not_a_rectangular_box() -> None:
    wedge = core.BrickPlacement(PART_BY_ID[EXPERIMENTAL_PART_ID], core.GridPosition(0, 0, 0), 0)
    plate = PART_BY_ID["3024"]

    assert not contains_body_point(wedge, (0.25, 1.99, 0.5))
    assert contains_body_point(wedge, (3.5, 0.5, 0.5))
    assert physical_collision(wedge, core.BrickPlacement(plate, core.GridPosition(3, 0, 0), 0))


def test_solver_rejects_a_rectangle_before_an_overlapping_wedge() -> None:
    """The original defect only compared wedges with later candidates.

    Rectangles are enumerated before wedges, so the former implementation let
    this physically colliding pair through to post-solve validation.
    """
    rectangle = _Candidate(
        core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(3, 0, 0), 0),
        frozenset({core.GridPosition(3, 0, 0)}),
    )
    wedge = WedgeCandidate(
        core.BrickPlacement(PART_BY_ID[EXPERIMENTAL_PART_ID], core.GridPosition(0, 0, 0), 0),
        frozenset(),
    )
    model = cp_model.CpModel()
    selected = (model.new_bool_var("rectangle"), model.new_bool_var("wedge"))
    _add_wedge_collisions(model, selected, (rectangle, wedge))
    model.add(selected[0] == 1)
    model.add(selected[1] == 1)

    solver = cp_model.CpSolver()
    assert solver.status_name(solver.solve(model)) == "INFEASIBLE"


def test_solver_selects_wedge_for_independent_wedge_prism_fixture() -> None:
    vertices, faces = _wedge_prism()
    result = optimise_with_wedge(
        source_vertices=vertices,
        faces=faces,
        target_cells=_cells(),
        required_pixels=(),
        locked_placements=(),
        max_parts=1,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.fallback_reason is None
    assert len(result.placements) == 1
    assert result.placements[0].brick_type.part_id == EXPERIMENTAL_PART_ID
    assert validate_completed_arrangement(result.placements, (), 1).is_valid

    score = fixed_frame_score(vertices, faces, result.placements, _cells())
    assert result.objective_value == score.score * (result.preflight.total_candidate_count + 1) - 1


def test_wedge_fixed_frame_score_uses_wedge_geometry_not_the_historical_box_path() -> None:
    vertices, faces = _wedge_prism()
    wedge = core.BrickPlacement(PART_BY_ID[EXPERIMENTAL_PART_ID], core.GridPosition(0, 0, 0), 0)

    score = fixed_frame_score(vertices, faces, (wedge,), _cells())

    assert score.score > 0
    assert sum(view.true_positives for view in score.views) == score.true_positives
    assert sum(view.false_positives for view in score.views) == score.false_positives


def test_nonmatching_wedge_contact_is_not_support() -> None:
    wedge = core.BrickPlacement(PART_BY_ID[EXPERIMENTAL_PART_ID], core.GridPosition(0, 0, 1), 0)
    plate = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(0, 0, 0), 0)
    report = validate_completed_arrangement((plate, wedge), (), 2)

    assert report.unsupported_placement_indices == (1,)


def test_candidate_limit_is_reported_before_solver(monkeypatch) -> None:
    import app.conversion.m12c_wedge_fidelity_experiment as experiment

    monkeypatch.setattr(experiment, "MAX_CANDIDATES", 1)
    _, _, report = preflight_wedge_candidates(target_cells=_cells())

    assert report.status == "CANDIDATE_LIMIT_EXHAUSTED"


def test_elevated_locked_slope_requires_a_selected_verified_supporter() -> None:
    lower_cell = core.GridPosition(0, 0, 0)
    slope = core.BrickPlacement(PART_BY_ID["4286"], core.GridPosition(0, 0, 1), 0)

    result = optimise_with_wedge(
        source_vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        faces=((0, 1, 2),),
        target_cells=frozenset({lower_cell}),
        required_pixels=(),
        locked_placements=(slope,),
        max_parts=2,
        include_wedges=False,
    )

    assert result.fallback_reason is None
    assert any(item.position == lower_cell for item in result.placements)
    assert (
        validate_completed_arrangement(result.placements, (), 2).unsupported_placement_indices == ()
    )


def test_locked_slope_without_a_verified_candidate_supporter_is_infeasible() -> None:
    slope = core.BrickPlacement(PART_BY_ID["4286"], core.GridPosition(0, 0, 1), 0)

    result = optimise_with_wedge(
        source_vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        faces=((0, 1, 2),),
        target_cells=frozenset({core.GridPosition(3, 0, 0)}),
        required_pixels=(),
        locked_placements=(slope,),
        max_parts=2,
        include_wedges=False,
    )

    assert result.status == "INFEASIBLE"
    assert result.fallback_reason == "infeasible"


def test_fixed_locked_slope_support_does_not_require_a_new_candidate() -> None:
    lower_slope = core.BrickPlacement(PART_BY_ID["4286"], core.GridPosition(0, 0, 0), 0)
    upper_slope = core.BrickPlacement(PART_BY_ID["4286"], core.GridPosition(2, 0, 3), 0)

    result = optimise_with_wedge(
        source_vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        faces=((0, 1, 2),),
        target_cells=frozenset({core.GridPosition(5, 0, 0)}),
        required_pixels=(),
        locked_placements=(lower_slope, upper_slope),
        max_parts=3,
        include_wedges=False,
    )

    assert result.fallback_reason is None
    assert result.placements == (lower_slope, upper_slope)
