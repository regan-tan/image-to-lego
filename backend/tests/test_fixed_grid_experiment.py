from __future__ import annotations

from dataclasses import replace

import pytest
from ortools.sat.python import cp_model

from app.conversion import benchmark, core
from app.conversion import surface_grid_v4 as surface_grid
from app.conversion.fixed_grid_experiment import convert_fixed_grid
from app.conversion.surface_metric_v2 import evaluate_surface_metric_v2


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


def test_one_x_evidence_reproduces_the_existing_fixed_lattice_occupancy() -> None:
    source = _box_source()
    grid = core.GridSize(5, 4, 6)
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    expected = core._source_occupancy(core._normalize_vertices(vertices, core.Axis.Y), faces, grid)

    result = _run(grid, 60)

    assert result.source_evidence_resolution == 1
    assert result.source_cells == expected.surface_cells
    assert result.source_subcell_count == len(expected.surface_cells)


def test_two_x_evidence_is_deterministic_and_keeps_the_same_physical_lattice() -> None:
    source = _box_source()
    grid = core.GridSize(5, 4, 6)
    first = convert_fixed_grid(
        source,
        grid_size=grid,
        solver_target_parts=12,
        max_parts=60,
        up_axis=core.Axis.Y,
        source_evidence_resolution=2,
    )
    second = convert_fixed_grid(
        source,
        grid_size=grid,
        solver_target_parts=12,
        max_parts=60,
        up_axis=core.Axis.Y,
        source_evidence_resolution=2,
    )

    assert first.model.metadata.grid_size == grid
    assert first.model.dimensions.width_mm <= grid.width_studs * core.STUD_WIDTH_MM
    assert first.source_cells == second.source_cells
    assert first.model.placements == second.model.placements
    assert first.source_subcell_count == second.source_subcell_count


def test_invalid_evidence_resolution_fails_explicitly() -> None:
    with pytest.raises(core.ConversionError, match="source evidence resolution"):
        convert_fixed_grid(
            _box_source(),
            grid_size=core.GridSize(5, 4, 6),
            solver_target_parts=12,
            max_parts=60,
            up_axis=core.Axis.Y,
            source_evidence_resolution=3,
        )


def test_surface_metric_v2_is_deterministic_and_reports_timeout_honestly() -> None:
    source = _box_source()
    result = _run(core.GridSize(5, 4, 6), 60)
    _, vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(12, core.Axis.Y), core.GridSize(5, 4, 6)
    )

    first = evaluate_surface_metric_v2(vertices, faces, result.model.placements)
    second = evaluate_surface_metric_v2(vertices, faces, result.model.placements)
    timed_out = evaluate_surface_metric_v2(
        vertices, faces, result.model.placements, timeout_seconds=1e-12
    )

    assert first.record() == second.record()
    assert first.status == "available"
    assert timed_out.status == "unavailable"
    assert timed_out.reason == "metric observation timeout exceeded"


def test_surface_metric_v2_preserves_v1_distance_ranking_on_a_synthetic_fixture() -> None:
    source = _box_source()
    result = _run(core.GridSize(5, 4, 6), 60)
    _, vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(12, core.Axis.Y), core.GridSize(5, 4, 6)
    )
    shifted = tuple(
        replace(
            placement,
            position=core.GridPosition(
                placement.position.x + 3, placement.position.y, placement.position.z
            ),
        )
        for placement in result.model.placements
    )
    v1_good = benchmark.evaluate_geometric_fidelity(vertices, faces, result.model.placements)
    v1_shifted = benchmark.evaluate_geometric_fidelity(vertices, faces, shifted)
    v2_good = evaluate_surface_metric_v2(vertices, faces, result.model.placements)
    v2_shifted = evaluate_surface_metric_v2(vertices, faces, shifted)

    assert v1_good.status == v1_shifted.status == "available"
    assert v2_good.status == v2_shifted.status == "available"
    assert v1_good.symmetric_chamfer_mm < v1_shifted.symmetric_chamfer_mm
    assert v2_good.symmetric_mean_mm < v2_shifted.symmetric_mean_mm


def test_v6_smoke_keeps_the_existing_mechanical_gates() -> None:
    result = convert_fixed_grid(
        _box_source(),
        grid_size=core.GridSize(3, 3, 3),
        solver_target_parts=4,
        max_parts=16,
        up_axis=core.Axis.Y,
        shape_aware=True,
    )

    assert result.model.metadata.algorithm_version == "surface-grid-v6-fixed-lattice-diagnostic"
    assert result.model.part_count <= 16
    assert result.model.metadata.diagnostics is not None
    assert result.model.metadata.diagnostics.physical_collision_pair_count == 0


def test_source_aware_diagnostic_is_deterministic_and_preserves_reliable_gates() -> None:
    source = _box_source()
    first = convert_fixed_grid(
        source,
        grid_size=core.GridSize(3, 3, 3),
        solver_target_parts=4,
        max_parts=16,
        up_axis=core.Axis.Y,
        source_aware=True,
    )
    second = convert_fixed_grid(
        source,
        grid_size=core.GridSize(3, 3, 3),
        solver_target_parts=4,
        max_parts=16,
        up_axis=core.Axis.Y,
        source_aware=True,
    )

    assert first.model.metadata.algorithm_version == (
        "surface-grid-v8-source-aware-fixed-lattice-diagnostic"
    )
    assert first.model.placements == second.model.placements
    assert first.model.part_count <= 16
    assert all(
        not (core._placement_source_cells(placement) & first.protected_empty_cells)
        for placement in first.model.placements
    )
    assert first.model.metadata.diagnostics is not None
    assert first.model.metadata.diagnostics.physical_collision_pair_count == 0


def test_source_aware_objective_prefers_source_cells_when_part_count_is_tied() -> None:
    source_cell = core.GridPosition(0, 0, 0)
    excess_cell = core.GridPosition(1, 0, 0)
    candidates = _objective_candidates(source_cell, excess_cell)
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"candidate_{index}") for index in range(2))
    model.add(sum(selected) == 1)
    model.minimize(
        surface_grid._source_aware_objective(selected, candidates, frozenset({source_cell}))
    )
    solver = cp_model.CpSolver()
    assert solver.solve(model) == cp_model.OPTIMAL

    assert solver.boolean_value(selected[0])
    assert not solver.boolean_value(selected[1])


def test_source_aware_objective_keeps_part_count_before_source_occupancy() -> None:
    source_cell = core.GridPosition(0, 0, 0)
    excess_cell = core.GridPosition(1, 0, 0)
    candidates = _objective_candidates(excess_cell, source_cell, source_cell)
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"candidate_{index}") for index in range(3))
    # Either select one excess candidate, or select both source candidates.
    model.add(selected[0] + selected[1] == 1)
    model.add(selected[0] + selected[2] == 1)
    model.minimize(
        surface_grid._source_aware_objective(selected, candidates, frozenset({source_cell}))
    )
    solver = cp_model.CpSolver()
    assert solver.solve(model) == cp_model.OPTIMAL

    assert solver.boolean_value(selected[0])
    assert not solver.boolean_value(selected[1])
    assert not solver.boolean_value(selected[2])


def _objective_candidates(
    *cells: core.GridPosition,
) -> tuple[surface_grid._Candidate, ...]:
    brick = next(part for part in core.BRICK_CATALOGUE if part.shape == "rectangular")
    return tuple(
        surface_grid._Candidate(
            core.BrickPlacement(brick, cell, 0),
            frozenset({cell}),
        )
        for cell in cells
    )
