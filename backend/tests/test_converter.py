import pytest
import trimesh

import app.conversion.core as converter_core
from app.conversion.core import (
    ALGORITHM_VERSION,
    BRICK_CATALOGUE,
    GRID_CELL_BUDGET_FACTORS,
    MAX_INPUT_BYTES,
    MAX_TARGET_PARTS,
    Axis,
    BrickPlacement,
    ConversionError,
    ConversionSettings,
    GridPosition,
    convert_glb,
    pack_occupied_cells,
)


def glb_from_mesh(mesh: trimesh.Trimesh) -> bytes:
    exported = mesh.export(file_type="glb")
    assert isinstance(exported, bytes)
    return exported


def box_glb(*, extents: tuple[float, float, float] = (4.0, 3.0, 2.0)) -> bytes:
    return glb_from_mesh(trimesh.creation.box(extents=extents))


def open_tetrahedron_glb() -> bytes:
    mesh = trimesh.Trimesh(
        vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 2.0)],
        faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3)],
        process=False,
    )
    return glb_from_mesh(mesh)


def placement_cells(placement: BrickPlacement) -> set[GridPosition]:
    dimensions = placement.brick_type.dimensions
    length = dimensions.length_studs
    width = dimensions.width_studs
    if placement.orientation_degrees == 90:
        length, width = width, length
    return {
        GridPosition(placement.position.x + x, placement.position.y + y, placement.position.z)
        for y in range(width)
        for x in range(length)
    }


def all_placement_cells(placements: tuple[BrickPlacement, ...]) -> set[GridPosition]:
    cells: set[GridPosition] = set()
    for placement in placements:
        footprint = placement_cells(placement)
        assert cells.isdisjoint(footprint)
        cells.update(footprint)
    return cells


def test_conversion_is_deterministic() -> None:
    glb_bytes = box_glb()
    settings = ConversionSettings(target_parts=24)
    assert convert_glb(glb_bytes, settings) == convert_glb(glb_bytes, settings)


def test_placements_have_no_overlap_and_exactly_cover_reported_surface_cells() -> None:
    model = convert_glb(box_glb(), ConversionSettings(target_parts=24))
    covered_cells = all_placement_cells(model.placements)
    assert len(covered_cells) == model.metadata.occupied_cell_count


def test_only_supported_bricks_and_orientations_are_emitted() -> None:
    model = convert_glb(box_glb(), ConversionSettings(target_parts=24))
    assert {placement.brick_type for placement in model.placements}.issubset(set(BRICK_CATALOGUE))
    assert {placement.orientation_degrees for placement in model.placements}.issubset({0, 90})
    assert {placement.color for placement in model.placements} == {"light_bluish_gray"}


def test_packing_uses_largest_supported_brick_first() -> None:
    occupied_cells = {
        GridPosition(x, y, 0)
        for y in range(2)
        for x in range(4)
    }
    placements = pack_occupied_cells(occupied_cells)
    assert len(placements) == 1
    assert placements[0].brick_type.name == "brick_2x4"
    assert placements[0].orientation_degrees == 0


def test_target_parts_selects_a_different_resolution_and_approximately_changes_part_count() -> None:
    glb_bytes = box_glb()
    low_detail = convert_glb(glb_bytes, ConversionSettings(target_parts=8))
    high_detail = convert_glb(glb_bytes, ConversionSettings(target_parts=80))
    assert low_detail.metadata.grid_size != high_detail.metadata.grid_size
    assert high_detail.part_count > low_detail.part_count
    assert abs(high_detail.part_count - 80) < abs(low_detail.part_count - 80)


def test_larger_targets_select_monotonically_finer_grid_resolutions() -> None:
    glb_bytes = box_glb()
    models = [
        convert_glb(glb_bytes, ConversionSettings(target_parts=target))
        for target in (80, 200, 400)
    ]
    grid_cell_counts = [model.metadata.grid_size.cell_count for model in models]
    part_counts = [model.part_count for model in models]
    assert grid_cell_counts == sorted(grid_cell_counts)
    assert part_counts == sorted(part_counts)
    assert models[-1].metadata.candidate_count > len(GRID_CELL_BUDGET_FACTORS)


def test_calibration_expands_past_initial_candidate_range_and_selects_closest_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluated_counts: list[int] = []
    candidate_counts = iter((10, 20, 30, 40, 50, 95, 115))

    def fake_surface_cells(*_: object) -> frozenset[GridPosition]:
        return frozenset({GridPosition(0, 0, 0)})

    def fake_pack_occupied_cells(_: object) -> tuple[BrickPlacement, ...]:
        part_count = next(candidate_counts)
        evaluated_counts.append(part_count)
        return tuple(
            BrickPlacement(BRICK_CATALOGUE[-1], GridPosition(index, 0, 0), 0)
            for index in range(part_count)
        )

    monkeypatch.setattr(converter_core, "_surface_cells", fake_surface_cells)
    monkeypatch.setattr(converter_core, "pack_occupied_cells", fake_pack_occupied_cells)

    model = convert_glb(box_glb(), ConversionSettings(target_parts=100))

    assert len(evaluated_counts) > len(GRID_CELL_BUDGET_FACTORS)
    assert model.metadata.candidate_count == len(evaluated_counts)
    assert model.part_count == min(evaluated_counts, key=lambda count: abs(count - 100))


def test_up_axis_changes_the_lego_height_predictably() -> None:
    glb_bytes = box_glb(extents=(2.0, 6.0, 4.0))
    y_up = convert_glb(glb_bytes, ConversionSettings(target_parts=24, up_axis=Axis.Y))
    z_up = convert_glb(glb_bytes, ConversionSettings(target_parts=24, up_axis=Axis.Z))
    assert y_up.metadata.grid_size.height_bricks > z_up.metadata.grid_size.height_bricks


@pytest.mark.parametrize(
    "glb_bytes",
    [
        b"not a glb",
        glb_from_mesh(trimesh.Trimesh(vertices=[], faces=[], process=False)),
        glb_from_mesh(
            trimesh.Trimesh(
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
                process=False,
            )
        ),
    ],
)
def test_malformed_empty_and_degenerate_input_is_rejected(glb_bytes: bytes) -> None:
    with pytest.raises(ConversionError):
        convert_glb(glb_bytes, ConversionSettings(target_parts=10))


def test_non_finite_vertex_input_is_rejected() -> None:
    non_finite_mesh = trimesh.Trimesh(
        vertices=[(float("inf"), 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)],
        faces=[(0, 1, 2)],
        process=False,
    )
    modified = glb_from_mesh(non_finite_mesh)
    with pytest.raises(ConversionError, match="non-finite"):
        convert_glb(modified, ConversionSettings(target_parts=10))


def test_safety_limits_are_enforced() -> None:
    with pytest.raises(ConversionError, match="Target parts"):
        convert_glb(box_glb(), ConversionSettings(target_parts=MAX_TARGET_PARTS + 1))
    with pytest.raises(ConversionError, match="size limit"):
        convert_glb(b"x" * (MAX_INPUT_BYTES + 1), ConversionSettings(target_parts=10))


@pytest.mark.parametrize("glb_bytes", [box_glb(), open_tetrahedron_glb()])
def test_watertight_and_non_watertight_meshes_use_surface_occupancy(glb_bytes: bytes) -> None:
    model = convert_glb(glb_bytes, ConversionSettings(target_parts=24))
    assert model.metadata.algorithm_version == ALGORITHM_VERSION
    assert model.metadata.occupancy_mode == "surface"
    assert model.part_count > 0
    assert len(all_placement_cells(model.placements)) < model.metadata.grid_size.cell_count
