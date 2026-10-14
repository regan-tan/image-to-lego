"""Deterministic stud-connectivity diagnostics for completed LEGO placements."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush

from app.conversion.core import BrickPlacement

BUILDABILITY_ANALYSIS_VERSION = "stud-connectivity-v1"
MAX_PLACEMENTS_PER_INSTRUCTION_STEP = 6
_SUPPORTED_FAMILIES = frozenset({"brick", "plate"})


@dataclass(frozen=True, slots=True)
class ConnectionEdge:
    """A vertical stud connection from a lower placement to an upper placement."""

    lower_placement_index: int
    upper_placement_index: int
    stud_count: int


@dataclass(frozen=True, slots=True)
class BuildabilityAnalysis:
    """Aggregate stud-connectivity diagnostics for one completed LEGO model."""

    edges: tuple[ConnectionEdge, ...]
    evaluated_placement_count: int
    unevaluated_placement_count: int
    connected_component_count: int
    largest_connected_component_size: int
    largest_connected_component_ratio: float
    isolated_placement_count: int
    unsupported_placement_count: int


@dataclass(frozen=True, slots=True)
class InstructionStep:
    """One deterministic guide step referencing canonical placement indexes."""

    step_number: int
    placement_indices: tuple[int, ...]


class BuildInstructionOrderingError(ValueError):
    """The stud-connectivity graph cannot provide a valid instruction order."""


class InstructionStepValidationError(ValueError):
    """Instruction steps do not cover a model in a mechanically valid order."""


def analyze_buildability(placements: Collection[BrickPlacement]) -> BuildabilityAnalysis:
    """Analyze supported brick and plate placements without changing the conversion output.

    A supported placement is unsupported when its bottom is above the model's minimum
    placement z plane and no evaluated rectangular placement connects directly below it.
    """
    placement_list = tuple(placements)
    evaluated = tuple(
        (index, placement)
        for index, placement in enumerate(placement_list)
        if _is_connector_supported(placement)
    )
    edges = _connection_edges(evaluated)
    evaluated_indices = {index for index, _ in evaluated}
    adjacency = {index: set[int]() for index in evaluated_indices}
    connected_from_below: set[int] = set()
    for edge in edges:
        adjacency[edge.lower_placement_index].add(edge.upper_placement_index)
        adjacency[edge.upper_placement_index].add(edge.lower_placement_index)
        connected_from_below.add(edge.upper_placement_index)

    component_sizes = _component_sizes(adjacency)
    evaluated_count = len(evaluated)
    largest_component_size = max(component_sizes, default=0)
    base_z = min((placement.position.z for placement in placement_list), default=0)
    unsupported_count = sum(
        placement.position.z != base_z and index not in connected_from_below
        for index, placement in evaluated
    )

    return BuildabilityAnalysis(
        edges=edges,
        evaluated_placement_count=evaluated_count,
        unevaluated_placement_count=len(placement_list) - evaluated_count,
        connected_component_count=len(component_sizes),
        largest_connected_component_size=largest_component_size,
        largest_connected_component_ratio=(largest_component_size / evaluated_count)
        if evaluated_count
        else 0.0,
        isolated_placement_count=sum(not neighbors for neighbors in adjacency.values()),
        unsupported_placement_count=unsupported_count,
    )


def order_placements_for_instructions(
    placements: Collection[BrickPlacement],
) -> tuple[BrickPlacement, ...]:
    """Return a deterministic support-before-dependent placement order.

    This reuses ``stud-connectivity-v1`` edges for rectangular bricks and plates.
    It does not verify insertion accessibility, collision-free assembly, or partial-build stability.
    Unevaluated placements, including slopes, have no invented mechanical edge. They are
    positioned by the same coordinate-based presentation order after every evaluated
    placement below their base z level; this is not a verified mechanical dependency.
    """
    placement_list = tuple(placements)
    return tuple(placement_list[index] for index in _ordered_placement_indices(placement_list))


def generate_instruction_steps(
    placements: Collection[BrickPlacement],
) -> tuple[InstructionStep, ...]:
    """Batch the canonical order into deterministic, support-safe guide steps.

    A direct ``stud-connectivity-v1`` support edge always crosses a step boundary.
    Unevaluated placements, including slopes, retain presentation ordering only: they do
    not gain inferred mechanical dependencies.
    """
    placement_list = tuple(placements)
    analysis = analyze_buildability(placement_list)
    canonical_indices = _ordered_placement_indices(placement_list)
    canonical_rank = {index: rank for rank, index in enumerate(canonical_indices)}
    prerequisites = _prerequisites_by_placement(placement_list, analysis.edges)
    component_ids = _component_ids_by_placement(placement_list, analysis.edges)
    evaluated_indices = {
        index
        for index, placement in enumerate(placement_list)
        if _is_connector_supported(placement)
    }
    evaluated_before = {
        index: frozenset(
            earlier_index
            for earlier_index in canonical_indices[: canonical_rank[index]]
            if earlier_index in evaluated_indices
        )
        for index in range(len(placement_list))
        if index not in evaluated_indices
    }

    assigned: set[int] = set()
    steps: list[InstructionStep] = []
    while len(assigned) < len(placement_list):
        eligible = [
            index
            for index in canonical_indices
            if index not in assigned
            and prerequisites[index].issubset(assigned)
            and (index in evaluated_indices or evaluated_before[index].issubset(assigned))
        ]
        if not eligible:
            raise BuildInstructionOrderingError(
                "No placement is eligible for the next instruction step."
            )

        selected = [eligible.pop(0)]
        anchor_component = component_ids.get(selected[0])
        while eligible and len(selected) < MAX_PLACEMENTS_PER_INSTRUCTION_STEP:
            next_index = min(
                eligible,
                key=lambda index: _step_candidate_key(
                    index=index,
                    selected_indices=selected,
                    placement_list=placement_list,
                    component_ids=component_ids,
                    anchor_component=anchor_component,
                    canonical_rank=canonical_rank,
                ),
            )
            selected.append(next_index)
            eligible.remove(next_index)

        assigned.update(selected)
        steps.append(InstructionStep(len(steps) + 1, tuple(selected)))

    instruction_steps = tuple(steps)
    validate_instruction_steps(placement_list, instruction_steps)
    return instruction_steps


def validate_instruction_steps(
    placements: Collection[BrickPlacement],
    instruction_steps: Sequence[InstructionStep],
) -> None:
    """Reject incomplete, duplicated, oversized, or mechanically invalid guide steps."""
    placement_list = tuple(placements)
    step_by_placement: dict[int, int] = {}
    for expected_step_number, step in enumerate(instruction_steps, start=1):
        if step.step_number != expected_step_number:
            raise InstructionStepValidationError("Instruction step numbers must be contiguous.")
        if len(step.placement_indices) > MAX_PLACEMENTS_PER_INSTRUCTION_STEP:
            raise InstructionStepValidationError("An instruction step exceeds the placement limit.")
        for placement_index in step.placement_indices:
            if placement_index < 0 or placement_index >= len(placement_list):
                raise InstructionStepValidationError(
                    "An instruction step references an unknown placement."
                )
            if placement_index in step_by_placement:
                raise InstructionStepValidationError(
                    "A placement appears in more than one instruction step."
                )
            step_by_placement[placement_index] = step.step_number

    missing_indices = set(range(len(placement_list))) - set(step_by_placement)
    if missing_indices:
        raise InstructionStepValidationError(
            "An instruction step is missing one or more placements."
        )

    for edge in analyze_buildability(placement_list).edges:
        lower_step = step_by_placement[edge.lower_placement_index]
        upper_step = step_by_placement[edge.upper_placement_index]
        if lower_step >= upper_step:
            raise InstructionStepValidationError(
                "A stud-connectivity support must appear in an earlier instruction step."
            )


def _ordered_placement_indices(placements: tuple[BrickPlacement, ...]) -> tuple[int, ...]:
    analysis = analyze_buildability(placements)
    outgoing: list[list[int]] = [[] for _ in placements]
    incoming_counts = [0 for _ in placements]

    for edge in analysis.edges:
        lower = placements[edge.lower_placement_index]
        upper = placements[edge.upper_placement_index]
        if lower.position.z >= upper.position.z:
            raise BuildInstructionOrderingError(
                "stud-connectivity-v1 produced a non-upward support dependency."
            )
        outgoing[edge.lower_placement_index].append(edge.upper_placement_index)
        incoming_counts[edge.upper_placement_index] += 1

    ready: list[tuple[tuple[int, int, int, int, int, str, int, int], int]] = []
    for index, incoming_count in enumerate(incoming_counts):
        if incoming_count == 0:
            heappush(ready, (_instruction_order_key(placements[index], index), index))

    ordered_indices: list[int] = []
    while ready:
        _, index = heappop(ready)
        ordered_indices.append(index)
        for dependent_index in outgoing[index]:
            incoming_counts[dependent_index] -= 1
            if incoming_counts[dependent_index] == 0:
                dependent = placements[dependent_index]
                heappush(
                    ready,
                    (_instruction_order_key(dependent, dependent_index), dependent_index),
                )

    if len(ordered_indices) != len(placements):
        raise BuildInstructionOrderingError(
            "stud-connectivity-v1 produced a cyclic support dependency."
        )
    return tuple(ordered_indices)


def _prerequisites_by_placement(
    placements: tuple[BrickPlacement, ...],
    edges: Sequence[ConnectionEdge],
) -> tuple[frozenset[int], ...]:
    prerequisites = [set[int]() for _ in placements]
    for edge in edges:
        prerequisites[edge.upper_placement_index].add(edge.lower_placement_index)
    return tuple(frozenset(indices) for indices in prerequisites)


def _component_ids_by_placement(
    placements: tuple[BrickPlacement, ...],
    edges: Sequence[ConnectionEdge],
) -> dict[int, int]:
    evaluated_indices = {
        index for index, placement in enumerate(placements) if _is_connector_supported(placement)
    }
    adjacency = {index: set[int]() for index in evaluated_indices}
    for edge in edges:
        adjacency[edge.lower_placement_index].add(edge.upper_placement_index)
        adjacency[edge.upper_placement_index].add(edge.lower_placement_index)

    component_ids: dict[int, int] = {}
    for component_id, start_index in enumerate(sorted(adjacency)):
        if start_index in component_ids:
            continue
        pending = [start_index]
        while pending:
            index = pending.pop()
            if index in component_ids:
                continue
            component_ids[index] = component_id
            pending.extend(sorted(adjacency[index], reverse=True))
    return component_ids


def _step_candidate_key(
    *,
    index: int,
    selected_indices: Sequence[int],
    placement_list: tuple[BrickPlacement, ...],
    component_ids: dict[int, int],
    anchor_component: int | None,
    canonical_rank: dict[int, int],
) -> tuple[int, int, int]:
    same_component = anchor_component is not None and component_ids.get(index) == anchor_component
    distance = min(
        _placement_distance(placement_list[index], placement_list[selected_index])
        for selected_index in selected_indices
    )
    return (0 if same_component else 1, distance, canonical_rank[index])


def _placement_distance(left: BrickPlacement, right: BrickPlacement) -> int:
    return (
        abs(left.position.x - right.position.x)
        + abs(left.position.y - right.position.y)
        + abs(left.position.z - right.position.z)
    )


def _is_connector_supported(placement: BrickPlacement) -> bool:
    return (
        placement.brick_type.shape == "rectangular"
        and placement.brick_type.family in _SUPPORTED_FAMILIES
    )


def _instruction_order_key(
    placement: BrickPlacement,
    original_index: int,
) -> tuple[int, int, int, int, int, str, int, int]:
    fitter_order = placement.brick_type.fitter_order
    return (
        placement.position.z,
        placement.position.y,
        placement.position.x,
        fitter_order is None,
        fitter_order if fitter_order is not None else 0,
        placement.brick_type.part_id,
        placement.orientation_degrees,
        original_index,
    )


def _connection_edges(
    evaluated: tuple[tuple[int, BrickPlacement], ...],
) -> tuple[ConnectionEdge, ...]:
    placements_by_bottom_z: dict[int, list[tuple[int, BrickPlacement]]] = defaultdict(list)
    for index, placement in evaluated:
        placements_by_bottom_z[placement.position.z].append((index, placement))

    edges: list[ConnectionEdge] = []
    for lower_index, lower in evaluated:
        upper_z = lower.position.z + lower.brick_type.height_plates
        lower_footprint = _stud_footprint(lower)
        for upper_index, upper in placements_by_bottom_z[upper_z]:
            overlap = lower_footprint & _stud_footprint(upper)
            if overlap:
                edges.append(ConnectionEdge(lower_index, upper_index, len(overlap)))
    return tuple(edges)


def _stud_footprint(placement: BrickPlacement) -> frozenset[tuple[int, int]]:
    length = placement.brick_type.length_studs
    width = placement.brick_type.width_studs
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    return frozenset(
        (placement.position.x + x, placement.position.y + y)
        for y in range(width)
        for x in range(length)
    )


def _component_sizes(adjacency: dict[int, set[int]]) -> tuple[int, ...]:
    remaining = set(adjacency)
    sizes: list[int] = []
    while remaining:
        current = remaining.pop()
        size = 0
        pending = [current]
        while pending:
            index = pending.pop()
            size += 1
            for neighbor in adjacency[index]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        sizes.append(size)
    return tuple(sizes)
