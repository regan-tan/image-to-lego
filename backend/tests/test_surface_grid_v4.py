from __future__ import annotations

import pytest
import trimesh
from ortools.sat.python import cp_model

import app.conversion.surface_grid_v4 as surface_grid_v4
from app.conversion import core
from app.conversion.buildability import analyze_buildability
from app.conversion.surface_grid_v4 import (
    SolverStage,
    V4SolveFailure,
    _stage_one_deterministic_budget,
    projection_hull_target,
    solve_surface_grid_v4,
)
from app.workers.conversion_worker import serialize_lego_model


def _one_by_one_plate() -> core.BrickType:
    return next(
        part
        for part in core.BRICK_CATALOGUE
        if part.shape == "rectangular"
        and part.length_studs == 1
        and part.width_studs == 1
        and part.height_plates == 1
    )


def _required(cells: set[core.GridPosition]) -> set[tuple[str, int, int]]:
    return {
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    }


def test_v4_is_the_default_algorithm_version() -> None:
    settings = core.ConversionSettings(target_parts=8)

    assert settings.algorithm_version == core.SURFACE_GRID_V4
    assert core.ALGORITHM_VERSION == core.SURFACE_GRID_V4


@pytest.mark.parametrize(
    ("target_parts", "expected_budget"),
    (
        (100, 20.0),
        (300, 20.0),
        (599, 20.0),
        (600, 40.0),
        (601, 40.0),
    ),
)
def test_stage_one_budget_scales_for_detailed_conversions(
    target_parts: int, expected_budget: float
) -> None:
    assert _stage_one_deterministic_budget(target_parts) == expected_budget


def test_stage_two_budget_remains_unchanged() -> None:
    assert surface_grid_v4.STAGE_TWO_MAX_DETERMINISTIC_TIME == 7.25


def test_projection_hull_keeps_locked_slope_cells_out_of_rectangular_target() -> None:
    rectangle = core.GridPosition(0, 0, 0)
    locked_slope = core.GridPosition(1, 0, 0)

    target, required = projection_hull_target(
        {rectangle},
        {locked_slope},
        core.GridSize(2, 1, 1),
    )

    assert target == frozenset({rectangle})
    assert ("front", 1, 0) in required
    assert ("top", 1, 0) in required


def test_default_and_explicit_algorithm_versions_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v3_model = object()
    v4_model = object()
    monkeypatch.setattr(core, "_convert_surface_grid_v3", lambda *_: v3_model)
    monkeypatch.setattr(core, "_convert_surface_grid_v4", lambda *_: v4_model)

    assert core.convert_glb(b"source", core.ConversionSettings(target_parts=8)) is v4_model
    assert (
        core.convert_glb(
            b"source",
            core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V3),
        )
        is v3_model
    )
    assert (
        core.convert_glb(
            b"source",
            core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V4),
        )
        is v4_model
    )


def test_v4_occupancy_prevents_overlapping_placements() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)}

    result = solve_surface_grid_v4(
        cells, _required(cells), (), core.BRICK_CATALOGUE, target_parts=100
    )
    occupied = [
        cell for placement in result.placements for cell in core._placement_cells(placement)
    ]

    assert len(occupied) == len(set(occupied))


def test_v4_does_not_select_an_unsupported_non_base_placement() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(0, 0, 3)}

    result = solve_surface_grid_v4(
        cells,
        {("front", 0, 3)},
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert result.placements == ()


def test_v4_selects_directly_supported_placement() -> None:
    cells = {core.GridPosition(0, 0, z) for z in range(4)}

    result = solve_surface_grid_v4(
        cells, _required(cells), (), core.BRICK_CATALOGUE, target_parts=100
    )

    assert any(placement.position.z > 0 for placement in result.placements)
    assert analyze_buildability(result.placements).unsupported_placement_count == 0


def test_v4_projection_coverage_is_exact_or_of_occupied_cells() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(0, 1, 0)}

    result = solve_surface_grid_v4(
        cells,
        {("front", 0, 0)},
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert result.achieved_coverage == 1
    assert result.placements


def test_stage_two_preserves_stage_one_coverage_and_is_deterministic() -> None:
    cells = {core.GridPosition(x, 0, 0) for x in range(2)}
    required = _required(cells)

    first = solve_surface_grid_v4(
        cells, required, (), core.BRICK_CATALOGUE, target_parts=100
    )
    second = solve_surface_grid_v4(
        cells, required, (), core.BRICK_CATALOGUE, target_parts=100
    )

    assert first.achieved_coverage == len(required)
    assert first.placements == second.placements
    assert first.stage_two.objective_value is not None


def test_stage_one_optimal_solution_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSolver:
        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == 0

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        return FakeSolver(), SolverStage("OPTIMAL", 3, 0.0, True)

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0)},
        _required({core.GridPosition(0, 0, 0)}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert len(result.placements) == 1
    assert result.stage_one.status == "OPTIMAL"


def test_stage_one_feasible_solution_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSolver:
        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == 0

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        return FakeSolver(), SolverStage("FEASIBLE", 3, 0.0, False)

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0)},
        _required({core.GridPosition(0, 0, 0)}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert len(result.placements) == 1
    assert result.stage_one.status == "FEASIBLE"


@pytest.mark.parametrize(
    "stage_one",
    (SolverStage("UNKNOWN", None, 0.0, False), SolverStage("INFEASIBLE", None, 0.0, False)),
)
def test_stage_one_without_a_usable_incumbent_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    stage_one: SolverStage,
) -> None:
    def fake_solve(*_: object) -> tuple[object, SolverStage]:
        return object(), stage_one

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    with pytest.raises(V4SolveFailure, match="usable incumbent"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 0)},
            _required({core.GridPosition(0, 0, 0)}),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
        )


@pytest.mark.parametrize(
    ("stage_two", "expected_x"),
    [
        (SolverStage("OPTIMAL", 1, 0.0, True), 1),
        (SolverStage("FEASIBLE", 1, 0.0, False), 1),
        (SolverStage("UNKNOWN", None, 0.0, False), 0),
    ],
)
def test_stage_two_uses_a_usable_solution_or_falls_back_to_stage_one(
    monkeypatch: pytest.MonkeyPatch,
    stage_two: SolverStage,
    expected_x: int,
) -> None:
    calls = 0

    class FakeSolver:
        def __init__(self, selected_id: int) -> None:
            self.selected_id = selected_id

        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == self.selected_id

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeSolver(0), SolverStage("OPTIMAL", 1, 0.0, True)
        return FakeSolver(1), stage_two

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)},
        {("side", 0, 0)},
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert result.placements[0].position.x == expected_x


def test_solver_uses_deterministic_work_budgets_without_a_wall_clock_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeParameters:
        def __init__(self) -> None:
            self.max_deterministic_time = float("inf")
            self.num_search_workers = 0
            self.random_seed = 0
            self._max_time_in_seconds = float("inf")
            self.max_time_in_seconds_was_set = False

        @property
        def max_time_in_seconds(self) -> float:
            return self._max_time_in_seconds

        @max_time_in_seconds.setter
        def max_time_in_seconds(self, value: float) -> None:
            self.max_time_in_seconds_was_set = True
            self._max_time_in_seconds = value

    class FakeSolver:
        def __init__(self) -> None:
            self.parameters = FakeParameters()
            self.objective_value = 1.0

        def solve(self, model: cp_model.CpModel) -> int:
            return int(cp_model.OPTIMAL)

        def status_name(self, status: int) -> str:
            return "OPTIMAL"

    solvers: list[FakeSolver] = []

    def new_solver() -> FakeSolver:
        solver = FakeSolver()
        solvers.append(solver)
        return solver

    monkeypatch.setattr("app.conversion.surface_grid_v4.cp_model.CpSolver", new_solver)

    surface_grid_v4._solve(
        cp_model.CpModel(), surface_grid_v4.STAGE_ONE_MAX_DETERMINISTIC_TIME
    )
    surface_grid_v4._solve(
        cp_model.CpModel(), surface_grid_v4.STAGE_TWO_MAX_DETERMINISTIC_TIME
    )

    assert [solver.parameters.max_deterministic_time for solver in solvers] == [20.0, 7.25]
    assert all(not solver.parameters.max_time_in_seconds_was_set for solver in solvers)
    assert all(solver.parameters.num_search_workers == 1 for solver in solvers)
    assert all(solver.parameters.random_seed == 0 for solver in solvers)


def test_empty_rectangular_volume_with_required_coverage_fails_explicitly() -> None:
    with pytest.raises(V4SolveFailure, match="no rectangular candidate volume"):
        solve_surface_grid_v4(
            (),
            {("front", 0, 0)},
            (),
            (_one_by_one_plate(),),
            target_parts=100,
        )


def test_empty_rectangular_candidates_with_required_coverage_fail_explicitly() -> None:
    with pytest.raises(V4SolveFailure, match="no rectangular candidates"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 0)},
            {("front", 0, 0)},
            (),
            (),
            target_parts=100,
        )


def test_locked_slope_only_conversion_skips_rectangular_solving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slope_shell = frozenset(
        {
            core.GridPosition(0, 0, 1),
            core.GridPosition(1, 0, 2),
            core.GridPosition(2, 0, 4),
        }
    )
    monkeypatch.setattr(core, "_surface_cells", lambda *_: slope_shell)

    def fail_if_solver_runs(*_: object) -> object:
        pytest.fail("Slope-only conversion should not invoke CP-SAT.")

    monkeypatch.setattr(surface_grid_v4, "_solve", fail_if_solver_runs)

    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)
    model = core.convert_glb(
        source,
        core.ConversionSettings(target_parts=24, algorithm_version=core.SURFACE_GRID_V4),
    )

    actual_placements = [
        (placement.brick_type.part_id, placement.position) for placement in model.placements
    ]
    assert actual_placements == [("4286", core.GridPosition(0, 0, 1))]
    buildability = analyze_buildability(model.placements)
    assert buildability.evaluated_placement_count == 0
    assert buildability.unevaluated_placement_count == 1
    serialized = serialize_lego_model(model)
    assert b'"partId":"4286"' in serialized
    assert b'"fidelity"' in serialized


def test_v4_real_path_serializes_the_canonical_output() -> None:
    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)

    model = core.convert_glb(
        source,
        core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V4),
    )
    serialized = serialize_lego_model(model)

    assert model.metadata.algorithm_version == core.SURFACE_GRID_V4
    assert b'"algorithmVersion":"surface-grid-v4"' in serialized
    assert b'"buildability"' in serialized
