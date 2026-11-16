from __future__ import annotations

from app.conversion import benchmark, core
from app.conversion.fidelity_attribution import (
    cell_boxes,
    score_cell_occupancy,
    source_surface_cells,
)


def _box_source() -> bytes:
    case = next(case for case in benchmark.synthetic_cases() if case.case_id == "box")
    return benchmark.glb_bytes(case.mesh)


def test_cell_occupancy_uses_one_coherent_3d_set_for_all_three_views() -> None:
    source = _box_source()
    grid = core.GridSize(4, 4, 4)
    _, vertices, faces = benchmark.aligned_source_mesh(
        source, core.ConversionSettings(4, core.Axis.Y), grid
    )
    cells = frozenset((core.GridPosition(0, 0, 0), core.GridPosition(2, 1, 3)))

    first = score_cell_occupancy(vertices, faces, cells)
    second = score_cell_occupancy(vertices, faces, cells)

    assert first == second
    assert len(cell_boxes(cells)) == len(cells)
    assert set(first.false_positives) == {"front", "side", "top"}
    assert set(first.false_negatives) == {"front", "side", "top"}


def test_source_cells_follow_v6_alignment_and_fit_the_explicit_grid() -> None:
    source = _box_source()
    grid = core.GridSize(4, 5, 6)
    cells, watertight = source_surface_cells(source, grid_size=grid, up_axis=core.Axis.Y)

    assert cells
    assert watertight
    assert all(
        0 <= cell.x < grid.width_studs
        and 0 <= cell.y < grid.depth_studs
        and 0 <= cell.z < grid.height_plates
        for cell in cells
    )
