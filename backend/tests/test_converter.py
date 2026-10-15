from dataclasses import replace

import pytest
import trimesh
from PIL import Image

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
    GridSize,
    _safe_interior_cells,
    convert_glb,
    pack_occupied_cells,
)
from app.conversion.part_catalogue import LEGO_PART_CATALOGUE


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
        GridPosition(placement.position.x + x, placement.position.y + y, placement.position.z + z)
        for z in range(dimensions.height_plates)
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


def placement_geometry(
    placements: tuple[BrickPlacement, ...],
) -> list[tuple[object, GridPosition, int]]:
    return [
        (placement.brick_type, placement.position, placement.orientation_degrees)
        for placement in placements
    ]


def test_conversion_is_deterministic() -> None:
    glb_bytes = box_glb()
    settings = ConversionSettings(target_parts=24)
    assert convert_glb(glb_bytes, settings) == convert_glb(glb_bytes, settings)


def test_slope_conversion_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    slope_shell = frozenset(
        {
            GridPosition(0, 0, 1),
            GridPosition(1, 0, 2),
            GridPosition(2, 0, 4),
        }
    )
    monkeypatch.setattr(converter_core, "_surface_cells", lambda *_: slope_shell)

    first = convert_glb(box_glb(), ConversionSettings(target_parts=24))
    second = convert_glb(box_glb(), ConversionSettings(target_parts=24))

    assert first == second
    assert [placement.brick_type.part_id for placement in first.placements] == ["4286"]


def test_fidelity_metadata_does_not_change_placement_representation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    glb_bytes = box_glb()
    settings = ConversionSettings(target_parts=24)
    baseline = convert_glb(glb_bytes, settings)
    monkeypatch.setattr(
        converter_core,
        "evaluate_fidelity",
        lambda *args, **kwargs: baseline.metadata.fidelity,
    )
    measured = convert_glb(glb_bytes, settings)

    assert measured.placements == baseline.placements
    assert measured.dimensions == baseline.dimensions


def test_source_vertex_colors_change_only_placement_colors() -> None:
    mesh = trimesh.creation.box(extents=(4.0, 3.0, 2.0))
    mesh.visual.vertex_colors = [
        (201, 26, 9, 255) if vertex[0] < 0 else (0, 85, 191, 255) for vertex in mesh.vertices
    ]
    settings = ConversionSettings(target_parts=24)

    neutral = convert_glb(box_glb(), settings)
    colored = convert_glb(glb_from_mesh(mesh), settings)

    assert placement_geometry(colored.placements) == placement_geometry(neutral.placements)
    assert len({placement.color for placement in colored.placements}) > 1


def test_texture_uv_colors_preserve_geometry_and_are_deterministic() -> None:
    left = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    left.apply_translation((-1.5, 0.0, 0.0))
    right = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
    right.apply_translation((1.5, 0.0, 0.0))
    mesh = trimesh.util.concatenate((left, right))
    neutral_glb = glb_from_mesh(mesh)

    texture = Image.new("RGB", (2, 1))
    texture.putdata([(201, 26, 9), (0, 85, 191)])
    uv = [(0.1 if vertex[0] < 0 else 0.9, 0.5) for vertex in mesh.vertices]
    material = trimesh.visual.material.PBRMaterial(  # type: ignore[no-untyped-call]
        baseColorTexture=texture,
        baseColorFactor=(1.0, 1.0, 1.0, 1.0),
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(  # type: ignore[no-untyped-call]
        uv=uv, material=material
    )
    textured_glb = glb_from_mesh(mesh)
    settings = ConversionSettings(target_parts=24)

    neutral = convert_glb(neutral_glb, settings)
    first = convert_glb(textured_glb, settings)
    second = convert_glb(textured_glb, settings)

    assert placement_geometry(first.placements) == placement_geometry(neutral.placements)
    assert {placement.color for placement in first.placements} == {"red", "blue"}
    assert first == second


def test_material_only_color_is_used_when_no_texture_or_vertex_colors_exist() -> None:
    mesh = trimesh.creation.box(extents=(4.0, 3.0, 2.0))
    material = trimesh.visual.material.PBRMaterial(  # type: ignore[no-untyped-call]
        baseColorFactor=(201, 26, 9, 255)
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(  # type: ignore[no-untyped-call]
        uv=[(0.0, 0.0)] * len(mesh.vertices),
        material=material,
    )

    model = convert_glb(glb_from_mesh(mesh), ConversionSettings(target_parts=24))

    assert {placement.color for placement in model.placements} == {"red"}


def test_face_colors_are_extracted_without_vertex_color_conversion() -> None:
    mesh = trimesh.creation.box(extents=(4.0, 3.0, 2.0))
    mesh.visual.face_colors = [
        (201, 26, 9, 255) if center[0] < 0 else (0, 85, 191, 255)
        for center in mesh.triangles_center
    ]

    colors, source = converter_core._face_colors(mesh, len(mesh.faces))

    assert source == "vertex/face"
    assert set(colors) == {(201, 26, 9), (0, 85, 191)}


def test_unusable_texture_uv_falls_back_without_changing_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = ConversionSettings(target_parts=24)
    neutral = convert_glb(box_glb(), settings)
    mesh = trimesh.creation.box(extents=(4.0, 3.0, 2.0))
    texture = Image.new("RGB", (1, 1), (201, 26, 9))
    mesh.visual = trimesh.visual.texture.TextureVisuals(  # type: ignore[no-untyped-call]
        uv=[(0.0, 0.0)],
        material=trimesh.visual.material.PBRMaterial(  # type: ignore[no-untyped-call]
            baseColorTexture=texture
        ),
    )
    monkeypatch.setattr(converter_core, "_load_mesh", lambda _: mesh)

    converted = convert_glb(box_glb(), settings)

    assert placement_geometry(converted.placements) == placement_geometry(neutral.placements)
    assert {placement.color for placement in converted.placements} == {"light_bluish_gray"}


def test_placements_have_no_overlap_and_exactly_cover_reported_surface_cells() -> None:
    model = convert_glb(box_glb(), ConversionSettings(target_parts=24))
    covered_cells = all_placement_cells(model.placements)
    assert len(covered_cells) == model.metadata.occupied_cell_count


def test_only_supported_bricks_and_orientations_are_emitted() -> None:
    model = convert_glb(box_glb(), ConversionSettings(target_parts=24))
    assert {placement.brick_type for placement in model.placements}.issubset(set(BRICK_CATALOGUE))
    assert {placement.orientation_degrees for placement in model.placements}.issubset(
        {0, 90, 180, 270}
    )
    assert {placement.color for placement in model.placements} == {"light_bluish_gray"}


def test_real_part_catalogue_has_the_supported_valid_shapes() -> None:
    assert len(LEGO_PART_CATALOGUE) == 15
    assert len({part.part_id for part in LEGO_PART_CATALOGUE}) == len(LEGO_PART_CATALOGUE)
    rectangular_parts = [part for part in LEGO_PART_CATALOGUE if part.shape == "rectangular"]
    assert {(part.family, part.width_studs, part.length_studs) for part in rectangular_parts} == {
        (family, width, length)
        for family in ("brick", "plate")
        for width, length in ((2, 4), (2, 3), (2, 2), (1, 4), (1, 3), (1, 2), (1, 1))
    }
    assert all(part.width_studs > 0 and part.length_studs > 0 for part in LEGO_PART_CATALOGUE)
    assert all(part.height_plates == 3 for part in LEGO_PART_CATALOGUE if part.family == "brick")
    assert all(part.height_plates == 1 for part in LEGO_PART_CATALOGUE if part.family == "plate")
    slope = next(part for part in LEGO_PART_CATALOGUE if part.part_id == "4286")
    slope_details = (
        slope.name,
        slope.family,
        slope.width_studs,
        slope.length_studs,
        slope.height_plates,
    )
    assert slope_details == (
        "Slope 33 3 x 1",
        "slope_33",
        1,
        3,
        3,
    )
    assert slope.shape == "slope_33_3x1"


def test_placements_reference_catalogue_parts() -> None:
    model = convert_glb(box_glb(), ConversionSettings(target_parts=24))
    assert all(placement.brick_type in LEGO_PART_CATALOGUE for placement in model.placements)
    assert all(placement.brick_type.part_id for placement in model.placements)
    assert all(placement.color_id is not None for placement in model.placements)
    assert all(
        placement.color_id is not None
        and placement.brick_type.supports_color_id(placement.color_id)
        for placement in model.placements
    )


def test_packing_keeps_horizontal_geometry_and_uses_a_plate_for_one_layer() -> None:
    occupied_cells = {GridPosition(x, y, 0) for y in range(2) for x in range(4)}
    placements = pack_occupied_cells(occupied_cells)
    assert len(placements) == 1
    assert placements[0].brick_type.part_id == "3020"
    assert placements[0].orientation_degrees == 0


def test_packing_rejects_parts_without_any_verified_color() -> None:
    one_by_one_plate = next(part for part in BRICK_CATALOGUE if part.part_id == "3024")
    unavailable = replace(
        one_by_one_plate,
        part_id="unavailable",
        verified_color_ids=frozenset(),
    )
    verified = replace(
        one_by_one_plate,
        part_id="verified",
        verified_color_ids=frozenset({"ldraw:4"}),
    )

    placements = pack_occupied_cells({GridPosition(0, 0, 0)}, (unavailable, verified))

    assert [placement.brick_type.part_id for placement in placements] == ["verified"]
    with pytest.raises(ConversionError, match="could not be covered"):
        pack_occupied_cells({GridPosition(0, 0, 0)}, (unavailable,))


def test_bricks_and_plates_use_explicit_plate_layer_heights() -> None:
    catalogue = {brick.catalogue_key: brick for brick in BRICK_CATALOGUE}

    assert catalogue["brick_2x4"].dimensions.height_plates == 3
    assert catalogue["plate_2x4"].dimensions.height_plates == 1


def test_packing_prefers_larger_bricks_then_plates_deterministically() -> None:
    occupied_cells = {GridPosition(x, y, z) for x in range(4) for y in range(2) for z in range(4)}

    first = pack_occupied_cells(occupied_cells)
    second = pack_occupied_cells(occupied_cells)

    assert first == second
    assert [placement.brick_type.catalogue_key for placement in first] == ["brick_2x4", "plate_2x4"]


def test_slope_33_family_selects_rising_and_falling_runs_in_all_four_orientations() -> None:
    runs = {
        0: (GridPosition(0, 0, 1), GridPosition(1, 0, 2), GridPosition(2, 0, 4)),
        90: (GridPosition(0, 0, 1), GridPosition(0, 1, 3), GridPosition(0, 2, 4)),
        180: (GridPosition(0, 0, 4), GridPosition(1, 0, 3), GridPosition(2, 0, 1)),
        270: (GridPosition(0, 0, 4), GridPosition(0, 1, 2), GridPosition(0, 2, 1)),
    }

    for orientation, cells in runs.items():
        slopes, reserved = converter_core._place_supported_slopes(set(cells))
        assert len(slopes) == 1
        assert slopes[0].brick_type.part_id == "4286"
        assert slopes[0].orientation_degrees == orientation
        assert reserved == set(cells)


def test_slope_33_family_rejects_non_monotonic_and_wrong_height_runs() -> None:
    non_monotonic = {
        GridPosition(0, 0, 1),
        GridPosition(1, 0, 3),
        GridPosition(2, 0, 2),
    }
    wrong_height = {
        GridPosition(0, 0, 1),
        GridPosition(1, 0, 2),
        GridPosition(2, 0, 3),
    }

    assert converter_core._place_supported_slopes(non_monotonic) == ((), frozenset())
    assert converter_core._place_supported_slopes(wrong_height) == ((), frozenset())


def test_slope_33_family_reserves_runs_before_rectangular_packing() -> None:
    occupied_cells = {
        GridPosition(0, 0, 1),
        GridPosition(1, 0, 2),
        GridPosition(2, 0, 4),
        GridPosition(3, 0, 5),
        GridPosition(4, 0, 7),
    }

    slopes, reserved = converter_core._place_supported_slopes(occupied_cells)
    rectangles = pack_occupied_cells(occupied_cells - reserved)

    assert len(slopes) == 1
    assert all(
        not converter_core._placement_cells(placement) & reserved for placement in rectangles
    )


def test_slope_33_family_supports_its_catalogue_width_and_has_no_overlap() -> None:
    slope = next(part for part in BRICK_CATALOGUE if part.part_id == "4286")
    two_wide_slope = replace(slope, part_id="test-slope", width_studs=2)
    occupied_cells = {
        GridPosition(x, y, height) for y in range(2) for x, height in enumerate((1, 2, 4))
    }

    slopes, reserved = converter_core._place_slope_33_family(occupied_cells, (two_wide_slope,))
    rectangles = pack_occupied_cells(occupied_cells - reserved) if occupied_cells - reserved else ()

    slope_details = [
        (placement.brick_type.part_id, placement.orientation_degrees) for placement in slopes
    ]
    assert slope_details == [("test-slope", 0)]
    assert all_placement_cells(slopes + rectangles)


def test_slope_33_family_uses_the_catalogue_candidate_order_deterministically() -> None:
    slope = next(part for part in BRICK_CATALOGUE if part.part_id == "4286")
    first_candidate = replace(slope, part_id="first-slope")
    second_candidate = replace(slope, part_id="second-slope")
    occupied_cells = {
        GridPosition(0, 0, 1),
        GridPosition(1, 0, 2),
        GridPosition(2, 0, 4),
    }

    first, _ = converter_core._place_slope_33_family(
        occupied_cells, (first_candidate, second_candidate)
    )
    second, _ = converter_core._place_slope_33_family(
        occupied_cells, (first_candidate, second_candidate)
    )

    assert first == second
    assert [placement.brick_type.part_id for placement in first] == ["first-slope"]


def test_4286_geometry_places_the_high_end_for_all_orientations() -> None:
    slope = next(part for part in BRICK_CATALOGUE if part.part_id == "4286")
    placements = tuple(
        BrickPlacement(slope, GridPosition(10, 20, 30), orientation)
        for orientation in (0, 90, 180, 270)
    )
    vertices = converter_core._slope_vertices(placements)

    assert vertices[0][2] == (13.0, 20.0, 33.0)
    assert vertices[1][2] == (10.0, 23.0, 33.0)
    assert vertices[2][2] == (10.0, 20.0, 33.0)
    assert vertices[3][2] == (10.0, 20.0, 33.0)


def test_target_parts_selects_a_finer_resolution_by_default() -> None:
    glb_bytes = box_glb()
    low_detail = convert_glb(glb_bytes, ConversionSettings(target_parts=8))
    high_detail = convert_glb(glb_bytes, ConversionSettings(target_parts=80))

    assert low_detail.metadata.grid_size != high_detail.metadata.grid_size
    assert high_detail.metadata.grid_size.cell_count > low_detail.metadata.grid_size.cell_count
    assert high_detail.part_count > low_detail.part_count


def test_v3_target_parts_approximately_changes_part_count() -> None:
    glb_bytes = box_glb()
    low_detail = convert_glb(
        glb_bytes,
        ConversionSettings(target_parts=8, algorithm_version=converter_core.SURFACE_GRID_V3),
    )
    high_detail = convert_glb(
        glb_bytes,
        ConversionSettings(target_parts=80, algorithm_version=converter_core.SURFACE_GRID_V3),
    )

    assert abs(high_detail.part_count - 80) < abs(low_detail.part_count - 80)


def test_larger_targets_select_monotonically_finer_grid_resolutions() -> None:
    glb_bytes = box_glb()
    models = [
        convert_glb(glb_bytes, ConversionSettings(target_parts=target)) for target in (80, 200, 400)
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
    one_by_one_brick = next(brick for brick in BRICK_CATALOGUE if brick.part_id == "3005")

    def fake_surface_cells(*_: object) -> frozenset[GridPosition]:
        return frozenset({GridPosition(0, 0, 0)})

    def fake_pack_occupied_cells(*_: object) -> tuple[BrickPlacement, ...]:
        part_count = next(candidate_counts)
        evaluated_counts.append(part_count)
        return tuple(
            BrickPlacement(one_by_one_brick, GridPosition(index, 0, 0), 0)
            for index in range(part_count)
        )

    monkeypatch.setattr(converter_core, "_surface_cells", fake_surface_cells)
    monkeypatch.setattr(converter_core, "pack_occupied_cells", fake_pack_occupied_cells)

    source_vertices: list[tuple[float, float, float]] = [
        (0.0, 0.0, 0.0),
        (4.0, 3.0, 2.0),
    ]
    vertices = converter_core._normalize_vertices(
        source_vertices,
        Axis.Y,
    )
    source_faces: list[tuple[int, int, int]] = [(0, 1, 1)]
    grid_size, candidate_count = converter_core._select_legacy_grid(
        vertices,
        source_faces,
        100,
    )

    assert len(evaluated_counts) > len(GRID_CELL_BUDGET_FACTORS)
    assert candidate_count == len(evaluated_counts)
    assert grid_size.cell_count > 0


def test_v3_preserves_v2_xy_selection_and_expands_only_vertical_layers() -> None:
    glb_bytes = box_glb()
    mesh = converter_core._load_mesh(glb_bytes)
    vertices: list[tuple[float, float, float]] = [
        (float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices.tolist()
    ]
    faces: list[tuple[int, int, int]] = [
        (int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces.tolist()
    ]
    normalized_vertices = converter_core._normalize_vertices(vertices, Axis.Y)
    legacy_grid_size, _ = converter_core._select_legacy_grid(normalized_vertices, faces, 24)

    model = convert_glb(glb_bytes, ConversionSettings(target_parts=24))

    assert model.metadata.grid_size.width_studs == legacy_grid_size.width_studs
    assert model.metadata.grid_size.depth_studs == legacy_grid_size.depth_studs
    assert model.metadata.grid_size.height_plates == legacy_grid_size.height_plates * 3


def test_up_axis_changes_the_lego_height_predictably() -> None:
    glb_bytes = box_glb(extents=(2.0, 6.0, 4.0))
    y_up = convert_glb(glb_bytes, ConversionSettings(target_parts=24, up_axis=Axis.Y))
    z_up = convert_glb(glb_bytes, ConversionSettings(target_parts=24, up_axis=Axis.Z))
    assert y_up.metadata.grid_size.height_plates > z_up.metadata.grid_size.height_plates


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


def surface_cells_with_empty_space(
    grid_size: GridSize, empty_cells: frozenset[GridPosition]
) -> frozenset[GridPosition]:
    return frozenset(
        GridPosition(x, y, z)
        for z in range(grid_size.height_plates)
        for y in range(grid_size.depth_studs)
        for x in range(grid_size.width_studs)
        if GridPosition(x, y, z) not in empty_cells
    )


def test_enclosed_cavity_is_safe_in_a_watertight_mesh() -> None:
    grid_size = GridSize(3, 3, 3)
    cavity = GridPosition(1, 1, 1)

    assert _safe_interior_cells(
        surface_cells_with_empty_space(grid_size, frozenset({cavity})),
        grid_size,
        mesh_is_watertight=True,
    ) == frozenset({cavity})


@pytest.mark.parametrize(
    ("exterior_cell", "connection"),
    (
        (GridPosition(0, 1, 1), "face"),
        (GridPosition(0, 0, 1), "edge"),
        (GridPosition(0, 0, 0), "corner"),
    ),
)
def test_empty_space_connected_to_exterior_is_not_safe(
    exterior_cell: GridPosition, connection: str
) -> None:
    grid_size = GridSize(3, 3, 3)
    cavity = GridPosition(1, 1, 1)

    safe_cells = _safe_interior_cells(
        surface_cells_with_empty_space(grid_size, frozenset({cavity, exterior_cell})),
        grid_size,
        mesh_is_watertight=True,
    )

    assert not safe_cells, connection


def test_non_watertight_mesh_has_no_safe_interior_cells() -> None:
    grid_size = GridSize(3, 3, 3)

    assert not _safe_interior_cells(
        surface_cells_with_empty_space(grid_size, frozenset({GridPosition(1, 1, 1)})),
        grid_size,
        mesh_is_watertight=False,
    )


@pytest.mark.parametrize("glb_bytes", [box_glb(), open_tetrahedron_glb()])
def test_watertight_and_non_watertight_meshes_use_surface_occupancy(glb_bytes: bytes) -> None:
    model = convert_glb(glb_bytes, ConversionSettings(target_parts=24))
    assert model.metadata.algorithm_version == ALGORITHM_VERSION
    assert model.metadata.occupancy_mode == "surface"
    assert model.part_count > 0
    assert len(all_placement_cells(model.placements)) < model.metadata.grid_size.cell_count
