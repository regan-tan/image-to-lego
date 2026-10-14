from app.conversion import BrickPlacement, GridPosition
from app.conversion.buildability import (
    ConnectionEdge,
    analyze_buildability,
    order_placements_for_instructions,
)
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


def test_instruction_order_places_a_simple_stack_from_lower_to_upper() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    lower = placement(brick)
    upper = placement(brick, z=3)

    assert order_placements_for_instructions((upper, lower)) == (lower, upper)


def test_instruction_order_preserves_a_three_piece_support_chain() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    first = placement(brick)
    second = placement(brick, z=3)
    third = placement(brick, z=6)

    assert order_placements_for_instructions((third, second, first)) == (first, second, third)


def test_instruction_order_places_every_direct_support_before_a_shared_upper_piece() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    left_support = placement(brick)
    right_support = placement(brick, x=4)
    upper = placement(brick, x=2, z=3)
    placements = (upper, right_support, left_support)

    ordered = order_placements_for_instructions(placements)

    assert ordered.index(left_support) < ordered.index(upper)
    assert ordered.index(right_support) < ordered.index(upper)
    assert analyze_buildability(placements).edges == (
        ConnectionEdge(1, 0, 4),
        ConnectionEdge(2, 0, 4),
    )


def test_instruction_order_uses_coordinate_tie_breaking_for_independent_pieces() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    first = placement(brick, x=0, y=0)
    second = placement(brick, x=2, y=0)
    third = placement(brick, x=0, y=2)

    assert order_placements_for_instructions((third, second, first)) == (first, second, third)


def test_instruction_order_handles_disconnected_evaluated_components_deterministically() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    lower = placement(brick)
    upper = placement(brick, z=3)
    disconnected = placement(brick, x=10)

    assert order_placements_for_instructions((upper, disconnected, lower)) == (
        lower,
        disconnected,
        upper,
    )


def test_instruction_order_keeps_unevaluated_slopes_without_inventing_support() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    lower = placement(brick)
    slope = placement(PART_BY_ID["4286"], z=3)
    placements = (slope, lower)

    ordered = order_placements_for_instructions(placements)

    assert ordered == (lower, slope)
    assert analyze_buildability(placements).edges == ()


def test_instruction_order_contains_every_placement_once_and_respects_all_edges() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick, x=2, z=6),
        placement(brick, x=4),
        placement(brick, x=2, z=3),
        placement(brick),
        placement(brick, x=10),
    )
    ordered = order_placements_for_instructions(placements)

    assert len(ordered) == len(placements)
    assert set(ordered) == set(placements)
    for edge in analyze_buildability(placements).edges:
        lower = placements[edge.lower_placement_index]
        upper = placements[edge.upper_placement_index]
        assert lower.position.z < upper.position.z
        assert ordered.index(lower) < ordered.index(upper)


def test_instruction_order_is_deterministic() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick, x=2, z=3),
        placement(PART_BY_ID["4286"], x=8, z=3),
        placement(brick, x=4),
        placement(brick),
    )

    assert order_placements_for_instructions(placements) == order_placements_for_instructions(
        placements
    )
