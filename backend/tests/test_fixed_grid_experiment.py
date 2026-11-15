from __future__ import annotations

import pytest

from app.conversion import benchmark, core
from app.conversion.fixed_grid_experiment import convert_fixed_grid


def _box_source() -> bytes:
    case = next(case for case in benchmark.synthetic_cases() if case.case_id == "box")
    return benchmark.glb_bytes(case.mesh)


def _run(grid: core.GridSize, cap: int):
    return convert_fixed_grid(
        _box_source(),
        grid_size=grid,
        solver_target_parts=12,
        max_parts=cap,
        up_axis=core.Axis.Y,
    )


def test_cap_sweep_keeps_explicit_grid_and_solver_target_fixed() -> None:
    grid = core.GridSize(5, 4, 6)

    lower_cap = _run(grid, 40)
    higher_cap = _run(grid, 60)

    assert lower_cap.model.metadata.grid_size == grid
    assert higher_cap.model.metadata.grid_size == grid
    assert lower_cap.model.metadata.target_parts == 12
    assert higher_cap.model.metadata.target_parts == 12
    assert lower_cap.model.part_count <= 40
    assert higher_cap.model.part_count <= 60


def test_grid_change_is_reflected_without_changing_solver_target() -> None:
    result = _run(core.GridSize(6, 5, 7), 60)

    assert result.model.metadata.grid_size == core.GridSize(6, 5, 7)
    assert result.model.metadata.target_parts == 12
    assert result.model.dimensions.width_mm <= 6 * core.STUD_WIDTH_MM


def test_fixed_grid_output_preserves_collision_and_protected_space_safeguards() -> None:
    result = _run(core.GridSize(5, 4, 6), 60)

    assert result.model.metadata.diagnostics is not None
    assert result.model.metadata.diagnostics.physical_collision_pair_count == 0
    assert all(
        not (core._placement_source_cells(placement) & result.protected_empty_cells)
        for placement in result.model.placements
    )


def test_invalid_infeasible_setting_fails_explicitly() -> None:
    with pytest.raises(core.ConversionError, match="hard part cap"):
        _run(core.GridSize(5, 4, 6), 0)


def test_repeated_fixed_grid_runs_are_deterministic() -> None:
    first = _run(core.GridSize(5, 4, 6), 60)
    second = _run(core.GridSize(5, 4, 6), 60)

    assert first.model.placements == second.model.placements
    assert first.source_cells == second.source_cells
    assert first.projection_hull_cells == second.projection_hull_cells
