"""Deterministic stud-connectivity diagnostics for completed LEGO placements."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from heapq import heappop, heappush

from app.conversion.core import BrickPlacement

BUILDABILITY_ANALYSIS_VERSION = "stud-connectivity-v1"
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


class BuildInstructionOrderingError(ValueError):
    """The stud-connectivity graph cannot provide a valid instruction order."""


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
    analysis = analyze_buildability(placement_list)
    outgoing: list[list[int]] = [[] for _ in placement_list]
    incoming_counts = [0 for _ in placement_list]

    for edge in analysis.edges:
        lower = placement_list[edge.lower_placement_index]
        upper = placement_list[edge.upper_placement_index]
        if lower.position.z >= upper.position.z:
            raise BuildInstructionOrderingError(
                "stud-connectivity-v1 produced a non-upward support dependency."
            )
        outgoing[edge.lower_placement_index].append(edge.upper_placement_index)
        incoming_counts[edge.upper_placement_index] += 1

    ready: list[tuple[tuple[int, int, int, int, int, str, int, int], int]] = []
    for index, incoming_count in enumerate(incoming_counts):
        if incoming_count == 0:
            heappush(ready, (_instruction_order_key(placement_list[index], index), index))

    ordered_indices: list[int] = []
    while ready:
        _, index = heappop(ready)
        ordered_indices.append(index)
        for dependent_index in outgoing[index]:
            incoming_counts[dependent_index] -= 1
            if incoming_counts[dependent_index] == 0:
                dependent = placement_list[dependent_index]
                heappush(
                    ready,
                    (_instruction_order_key(dependent, dependent_index), dependent_index),
                )

    if len(ordered_indices) != len(placement_list):
        raise BuildInstructionOrderingError(
            "stud-connectivity-v1 produced a cyclic support dependency."
        )
    return tuple(placement_list[index] for index in ordered_indices)


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
