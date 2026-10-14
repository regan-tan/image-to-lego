import pytest

from app.conversion import BrickPlacement, GridPosition
from app.conversion.buildability import (
    ConnectionEdge,
    InstructionStep,
    InstructionStepValidationError,
    analyze_buildability,
    generate_instruction_steps,
    order_placements_for_instructions,
    validate_instruction_steps,
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


def step_by_placement(steps: tuple[InstructionStep, ...]) -> dict[int, int]:
    return {
        placement_index: step.step_number
        for step in steps
        for placement_index in step.placement_indices
    }


def test_instruction_steps_keep_a_simple_stack_in_separate_steps() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (placement(brick, z=3), placement(brick))

    steps = generate_instruction_steps(placements)

    assigned_steps = step_by_placement(steps)
    assert assigned_steps[1] < assigned_steps[0]


def test_instruction_steps_keep_every_chain_dependency_in_a_later_step() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (placement(brick, z=6), placement(brick, z=3), placement(brick))

    steps = generate_instruction_steps(placements)

    assert [step.placement_indices for step in steps] == [(2,), (1,), (0,)]


def test_instruction_steps_allow_independent_supports_before_a_shared_upper_piece() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick, x=2, z=3),
        placement(brick, x=4),
        placement(brick),
    )

    steps = generate_instruction_steps(placements)

    assigned_steps = step_by_placement(steps)
    assert assigned_steps[1] == assigned_steps[2]
    assert assigned_steps[1] < assigned_steps[0]


def test_instruction_steps_batch_independent_ready_pieces_up_to_the_limit() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = tuple(placement(brick, x=index * 10) for index in range(6))

    steps = generate_instruction_steps(placements)

    assert steps == (InstructionStep(1, (0, 1, 2, 3, 4, 5)),)


def test_instruction_steps_split_more_than_six_ready_pieces_deterministically() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = tuple(placement(brick, x=index * 10) for index in range(8))

    steps = generate_instruction_steps(placements)

    assert steps == (InstructionStep(1, (0, 1, 2, 3, 4, 5)), InstructionStep(2, (6, 7)))


def test_instruction_steps_prefer_spatially_nearby_ready_pieces() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick, x=10),
        placement(brick, x=2),
        placement(brick, x=100),
        placement(brick),
    )

    steps = generate_instruction_steps(placements)

    assert steps[0].placement_indices == (3, 1, 0, 2)


def test_instruction_steps_complete_disconnected_components_deterministically() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick, x=20, z=3),
        placement(brick, x=20),
        placement(brick, z=3),
        placement(brick),
    )

    steps = generate_instruction_steps(placements)

    assert steps == (InstructionStep(1, (3, 1)), InstructionStep(2, (2, 0)))


def test_instruction_steps_continue_an_active_local_branch_before_a_deferred_branch() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    plate = catalogue_part(family="plate", width=1, length=1)
    base = placement(brick)
    branch_bases = tuple(
        placement(plate, x=index % 4, y=index // 4, z=3) for index in range(7)
    )
    branch_extension = placement(plate, z=4)

    steps = generate_instruction_steps((base, *branch_bases, branch_extension))

    assert 1 not in steps[1].placement_indices
    assert steps[2] == InstructionStep(3, (1,))
    assert steps[3] == InstructionStep(4, (8,))


def test_instruction_steps_finish_a_connected_component_before_starting_another() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    plate = catalogue_part(family="plate", width=1, length=1)
    first_component_bases = tuple(
        placement(plate, x=index % 4, y=index // 4) for index in range(6)
    )
    first_component_top = placement(brick, z=1)
    second_component = placement(brick, x=20)

    steps = generate_instruction_steps(
        (*first_component_bases, first_component_top, second_component)
    )

    assigned_steps = step_by_placement(steps)
    assert assigned_steps[6] <= assigned_steps[7]
    assert steps[0].placement_indices == (0, 1, 2, 3, 4, 5)


def test_instruction_steps_keep_unevaluated_slopes_as_presentation_only() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (placement(PART_BY_ID["4286"], z=3), placement(brick))

    steps = generate_instruction_steps(placements)

    assert steps == (InstructionStep(1, (1,)), InstructionStep(2, (0,)))
    assert analyze_buildability(placements).edges == ()


@pytest.mark.parametrize(
    "steps",
    [
        (InstructionStep(1, (0, 0)),),
        (InstructionStep(1, (0,)),),
        (InstructionStep(2, (0, 1)),),
    ],
)
def test_instruction_step_validation_rejects_duplicates_missing_and_number_gaps(
    steps: tuple[InstructionStep, ...],
) -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (placement(brick), placement(brick, x=10))

    with pytest.raises(InstructionStepValidationError):
        validate_instruction_steps(placements, steps)


def test_instruction_step_validation_rejects_dependencies_in_one_step() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (placement(brick), placement(brick, z=3))

    with pytest.raises(InstructionStepValidationError):
        validate_instruction_steps(placements, (InstructionStep(1, (0, 1)),))


def test_instruction_steps_are_deterministic() -> None:
    brick = catalogue_part(family="brick", width=2, length=4)
    placements = (
        placement(brick, x=2, z=3),
        placement(PART_BY_ID["4286"], x=8, z=3),
        placement(brick, x=4),
        placement(brick),
    )

    assert generate_instruction_steps(placements) == generate_instruction_steps(placements)
