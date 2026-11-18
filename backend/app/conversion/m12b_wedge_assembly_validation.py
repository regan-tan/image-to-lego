"""Offline assembly diagnostics for the deliberately narrow M12A wedge experiment.

This is not a converter validator.  It combines M12A's reviewed 41769a
interfaces with its analytic nonrectangular body test so synthetic assemblies
can be classified without admitting any new part interaction.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from app.conversion.core import BrickPlacement
from app.conversion.m12a_wedge_mechanics import (
    ExperimentalConnection,
    ExperimentalPlacementError,
    has_ground_support,
    mechanical_adjacency,
    physical_collision,
    projection_polygon,
    validate_placement,
)

_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class AssemblyValidationReport:
    """Deterministic findings for one small synthetic assembly."""

    placements: tuple[BrickPlacement, ...]
    collision_pairs: tuple[tuple[int, int], ...]
    connection_edges: tuple[ExperimentalConnection, ...]
    unsupported_placement_indices: tuple[int, ...]
    connected_components: tuple[tuple[int, ...], ...]
    isolated_placement_indices: tuple[int, ...]
    invalid_interface_pairs: tuple[tuple[int, int], ...]
    invalid_placement_indices: tuple[int, ...]
    part_counts: tuple[tuple[str, int], ...]
    projection_consistent: bool
    export_representable: None = None

    @property
    def is_valid(self) -> bool:
        """Whether this narrow experiment accepts the complete assembly."""
        return not (
            self.collision_pairs
            or self.unsupported_placement_indices
            or self.invalid_interface_pairs
            or self.invalid_placement_indices
            or len(self.connected_components) != 1
        )


def validate_synthetic_assembly(
    placements: Collection[BrickPlacement],
) -> AssemblyValidationReport:
    """Classify an M12B fixture without raising for its expected invalid cases.

    A part at z=0 is grounded. Every elevated placement must have a reviewed
    direct support edge. Touching at a shared horizontal plane without such an
    edge is explicitly invalid rather than being treated as support.
    """
    placement_list = tuple(placements)
    invalid_placements = tuple(
        index
        for index, placement in enumerate(placement_list)
        if not _is_valid_placement(placement)
    )
    if invalid_placements:
        return _invalid_placement_report(placement_list, invalid_placements)

    edges = mechanical_adjacency(placement_list)
    collision_pairs = tuple(
        (first_index, second_index)
        for first_index, first in enumerate(placement_list)
        for second_index, second in enumerate(placement_list[first_index + 1 :], first_index + 1)
        if physical_collision(first, second)
    )
    supported_indices = {edge.upper_index for edge in edges}
    unsupported = tuple(
        index
        for index, placement in enumerate(placement_list)
        if not has_ground_support(placement) and index not in supported_indices
    )
    edge_pairs = {(edge.lower_index, edge.upper_index) for edge in edges}
    invalid_interfaces = tuple(
        (first_index, second_index)
        for first_index, first in enumerate(placement_list)
        for second_index, second in enumerate(placement_list[first_index + 1 :], first_index + 1)
        if _touches_without_connection(first, second, first_index, second_index, edge_pairs)
    )
    components = _connected_components(len(placement_list), edges)
    isolated = tuple(component[0] for component in components if len(component) == 1)
    counts = tuple(
        sorted(
            (part_id, sum(p.brick_type.part_id == part_id for p in placement_list))
            for part_id in {p.brick_type.part_id for p in placement_list}
        )
    )
    return AssemblyValidationReport(
        placement_list,
        collision_pairs,
        edges,
        unsupported,
        components,
        isolated,
        invalid_interfaces,
        (),
        counts,
        _projection_is_consistent(placement_list),
    )


def _is_valid_placement(placement: BrickPlacement) -> bool:
    try:
        validate_placement(placement)
    except ExperimentalPlacementError:
        return False
    return True


def _invalid_placement_report(
    placements: tuple[BrickPlacement, ...], invalid: tuple[int, ...]
) -> AssemblyValidationReport:
    counts = tuple(
        sorted(
            (part_id, sum(p.brick_type.part_id == part_id for p in placements))
            for part_id in {p.brick_type.part_id for p in placements}
        )
    )
    return AssemblyValidationReport(
        placements,
        (),
        (),
        (),
        tuple((index,) for index in range(len(placements))),
        tuple(range(len(placements))),
        (),
        invalid,
        counts,
        False,
    )


def _touches_without_connection(
    first: BrickPlacement,
    second: BrickPlacement,
    first_index: int,
    second_index: int,
    edge_pairs: set[tuple[int, int]],
) -> bool:
    lower, upper = (first, second) if first.position.z <= second.position.z else (second, first)
    lower_index, upper_index = (
        (first_index, second_index)
        if first.position.z <= second.position.z
        else (second_index, first_index)
    )
    return (
        lower.position.z + lower.brick_type.height_plates == upper.position.z
        and (lower_index, upper_index) not in edge_pairs
        and _polygons_overlap(projection_polygon(lower), projection_polygon(upper))
    )


def _polygons_overlap(
    first: tuple[tuple[float, float], ...], second: tuple[tuple[float, float], ...]
) -> bool:
    return any(_point_in_polygon(second, point) for point in first) or any(
        _point_in_polygon(first, point) for point in second
    )


def _point_in_polygon(polygon: tuple[tuple[float, float], ...], point: tuple[float, float]) -> bool:
    previous = polygon[-1]
    for current in polygon:
        if (current[0] - previous[0]) * (point[1] - previous[1]) - (current[1] - previous[1]) * (
            point[0] - previous[0]
        ) < -_EPSILON:
            return False
        previous = current
    return True


def _connected_components(
    placement_count: int, edges: tuple[ExperimentalConnection, ...]
) -> tuple[tuple[int, ...], ...]:
    neighbors = {index: set[int]() for index in range(placement_count)}
    for edge in edges:
        neighbors[edge.lower_index].add(edge.upper_index)
        neighbors[edge.upper_index].add(edge.lower_index)
    components: list[tuple[int, ...]] = []
    visited: set[int] = set()
    for start in range(placement_count):
        if start in visited:
            continue
        pending = [start]
        component: set[int] = set()
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            visited.add(index)
            pending.extend(neighbors[index] - component)
        components.append(tuple(sorted(component)))
    return tuple(components)


def _projection_is_consistent(placements: tuple[BrickPlacement, ...]) -> bool:
    """Ensure each placement retains one deterministic non-empty projection."""
    return all(len(projection_polygon(placement)) >= 3 for placement in placements)
