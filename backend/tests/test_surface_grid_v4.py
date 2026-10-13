from __future__ import annotations

import pytest
import trimesh
from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.buildability import analyze_buildability
from app.conversion.surface_grid_v4 import (
    SolverStage,
    V4SolveFailure,
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


def test_v3_is_the_default_algorithm_version() -> None:
    settings = core.ConversionSettings(target_parts=8)

    assert settings.algorithm_version == core.SURFACE_GRID_V3
    assert core.ALGORITHM_VERSION == core.SURFACE_GRID_V3


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


def test_explicit_v4_dispatches_without_replacing_v3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v3_model = object()
    v4_model = object()
    monkeypatch.setattr(core, "_convert_surface_grid_v3", lambda *_: v3_model)
    monkeypatch.setattr(core, "_convert_surface_grid_v4", lambda *_: v4_model)

    assert core.convert_glb(b"source", core.ConversionSettings(target_parts=8)) is v3_model
    assert (
        core.convert_glb(
            b"source",
            core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V4),
        )
        is v4_model
    )


def test_v4_occupancy_prevents_overlapping_placements() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)}

    result = solve_surface_grid_v4(cells, _required(cells), (), core.BRICK_CATALOGUE)
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
    )

    assert result.placements == ()


def test_v4_selects_directly_supported_placement() -> None:
    cells = {core.GridPosition(0, 0, z) for z in range(4)}

    result = solve_surface_grid_v4(cells, _required(cells), (), core.BRICK_CATALOGUE)

    assert any(placement.position.z > 0 for placement in result.placements)
    assert analyze_buildability(result.placements).unsupported_placement_count == 0


def test_v4_projection_coverage_is_exact_or_of_occupied_cells() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(0, 1, 0)}

    result = solve_surface_grid_v4(
        cells,
        {("front", 0, 0)},
        (),
        (_one_by_one_plate(),),
    )

    assert result.achieved_coverage == 1
    assert result.placements


def test_stage_two_preserves_stage_one_coverage_and_is_deterministic() -> None:
    cells = {core.GridPosition(x, 0, 0) for x in range(2)}
    required = _required(cells)

    first = solve_surface_grid_v4(cells, required, (), core.BRICK_CATALOGUE)
    second = solve_surface_grid_v4(cells, required, (), core.BRICK_CATALOGUE)

    assert first.achieved_coverage == len(required)
    assert first.placements == second.placements
    assert first.stage_two.objective_value is not None


def test_stage_two_failure_uses_the_valid_stage_one_incumbent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeSolver:
        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == 0

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeSolver(), SolverStage("FEASIBLE", 3, 0.0, False)
        return FakeSolver(), SolverStage("UNKNOWN", None, 0.0, False)

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0)},
        _required({core.GridPosition(0, 0, 0)}),
        (),
        (_one_by_one_plate(),),
    )

    assert len(result.placements) == 1
    assert result.stage_two.objective_value is None


def test_stage_one_without_an_incumbent_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_solve(*_: object) -> tuple[object, SolverStage]:
        return object(), SolverStage("UNKNOWN", None, 0.0, False)

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    with pytest.raises(V4SolveFailure, match="stage one"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 0)},
            _required({core.GridPosition(0, 0, 0)}),
            (),
            (_one_by_one_plate(),),
        )


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
