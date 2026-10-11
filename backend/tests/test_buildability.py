from app.conversion import BrickPlacement, GridPosition
from app.conversion.buildability import ConnectionEdge, analyze_buildability
from app.conversion.part_catalogue import PART_BY_ID, LegoPart


def catalogue_part(*, family: str, width: int, length: int) -> LegoPart:
    return next(
        part
        for part in PART_BY_ID.values()
        if part.family == family and part.width_studs == width and part.length_studs == length
    )


def placement(
    part: LegoPart,
    *,
    x: int = 0,
    y: int = 0,
    z: int = 0,
    orientation: int = 0,
) -> BrickPlacement:
    return BrickPlacement(part, GridPosition(x, y, z), orientation)


def test_full_2x4_overlap_counts_all_stud_connections() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)

    analysis = analyze_buildability((placement(brick), placement(brick, z=3)))

    assert analysis.edges == (ConnectionEdge(0, 1, 8),)
    assert analysis.evaluated_placement_count == 2
    assert analysis.connected_component_count == 1
    assert analysis.largest_connected_component_size == 2
    assert analysis.largest_connected_component_ratio == 1.0
    assert analysis.isolated_placement_count == 0
    assert analysis.unsupported_placement_count == 0


def test_partial_and_one_stud_overlaps_count_exact_stud_positions() -> None:
    lower = catalogue_part(family="brick", width=2, length=4)
    two_stud_plate = catalogue_part(family="plate", width=1, length=2)
    one_stud_plate = catalogue_part(family="plate", width=1, length=1)

    partial = analyze_buildability((placement(lower), placement(two_stud_plate, x=1, z=3)))
    corner = analyze_buildability((placement(lower), placement(one_stud_plate, x=3, y=1, z=3)))

    assert partial.edges == (ConnectionEdge(0, 1, 2),)
    assert corner.edges == (ConnectionEdge(0, 1, 1),)


def test_no_overlap_or_mismatched_z_plane_has_no_connection() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)

    no_overlap = analyze_buildability((placement(brick), placement(brick, x=4, z=3)))
    mismatched_plane = analyze_buildability((placement(brick), placement(brick, z=4)))

    assert no_overlap.edges == ()
    assert mismatched_plane.edges == ()


def test_90_and_270_degree_orientations_swap_rectangular_footprints() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    plate = catalogue_part(family="plate", width=1, length=4)

    analysis = analyze_buildability(
        (placement(brick, orientation=90), placement(plate, z=3, orientation=270))
    )

    assert analysis.edges == (ConnectionEdge(0, 1, 4),)


def test_components_and_isolated_placements_are_reported() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick),
        placement(brick, z=3),
        placement(brick, x=10),
    )

    analysis = analyze_buildability(placements)

    assert analysis.connected_component_count == 2
    assert analysis.largest_connected_component_size == 2
    assert analysis.largest_connected_component_ratio == 2 / 3
    assert analysis.isolated_placement_count == 1


def test_unsupported_evaluated_placements_need_a_direct_connection_below() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)

    analysis = analyze_buildability((placement(brick), placement(brick, x=10, z=3)))

    assert analysis.unsupported_placement_count == 1


def test_base_layer_evaluated_placements_are_not_unsupported() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)

    analysis = analyze_buildability((placement(brick), placement(brick, x=10)))

    assert analysis.unsupported_placement_count == 0


def test_unsupported_families_are_unevaluated_not_isolated() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    slope = PART_BY_ID["4286"]

    analysis = analyze_buildability((placement(brick), placement(slope, x=4)))

    assert analysis.evaluated_placement_count == 1
    assert analysis.unevaluated_placement_count == 1
    assert analysis.connected_component_count == 1
    assert analysis.isolated_placement_count == 1


def test_buildability_graph_output_is_deterministic() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick),
        placement(brick, z=3),
        placement(brick, x=10),
    )

    assert analyze_buildability(placements) == analyze_buildability(placements)
