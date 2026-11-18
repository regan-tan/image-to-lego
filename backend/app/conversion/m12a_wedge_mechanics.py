"""Offline-only, conservative mechanics experiment for LEGO wedge plate 41769.

This module is intentionally not imported by the converter.  It models only the
source-backed top studs of a grounded 41769 wedge plate.  The source shows
underside geometry and the LDCad Shadow Library supplies five inherited female
snap cylinders for the exact without-chamfer variant.  The experiment exposes
only those vertical stud receivers.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from math import isclose
from typing import Final

from app.conversion.connector_evidence import CanonicalDirection
from app.conversion.core import BrickPlacement
from app.conversion.mechanical_connectors import (
    MechanicalInterfaceKind,
    MechanicalProvenance,
    WorldMechanicalConnector,
    matching_vertical_connectors,
    resolve_part_mechanical_metadata,
    transform_connector_to_world,
)
from app.conversion.part_coordinates import PartLocalFrame, rotate_part_local
from app.conversion.wedge_41769_41770 import transformed_footprint

EXPERIMENTAL_PART_ID: Final = "41769"
EXPERIMENTAL_ORIENTATIONS: Final = (0, 90, 180, 270)
STUD_WIDTH_MM: Final = 8.0
PLATE_HEIGHT_MM: Final = 3.2
_EPSILON: Final = 1e-9
# Directly extracted from the checked-in LDraw source's four ``stud.dat`` instances.
_SOURCE_TOP_STUDS: Final = ((0.5, 1.5, 1.0), (1.5, 1.5, 1.0), (2.5, 1.5, 1.0), (3.5, 1.5, 1.0))
# The LDCad 41770as01 female-cylinder grid and singleton, transformed through
# 41769a's source reflection. These are not a family rule or a chamfered-variant rule.
_VERIFIED_UNDERSIDE_RECEIVERS: Final = (
    (0.5, 1.5, 0.0),
    (1.5, 1.5, 0.0),
    (2.5, 1.5, 0.0),
    (3.5, 0.5, 0.0),
    (3.5, 1.5, 0.0),
)

Point2 = tuple[float, float]


class ExperimentalPlacementError(ValueError):
    """A placement lies outside this deliberately narrow experiment."""


@dataclass(frozen=True, slots=True)
class ExperimentalConnection:
    lower_index: int
    upper_index: int
    stud_count: int


def validate_placement(placement: BrickPlacement) -> None:
    """Validate grid placement and the limited experimental part vocabulary."""
    if min(placement.position.x, placement.position.y, placement.position.z) < 0:
        raise ExperimentalPlacementError(
            "Experimental placements must stay in the non-negative grid."
        )
    if placement.brick_type.part_id == EXPERIMENTAL_PART_ID:
        if placement.orientation_degrees not in EXPERIMENTAL_ORIENTATIONS:
            raise ExperimentalPlacementError("41769 supports only quarter-turn orientations.")
        return
    if placement.brick_type.shape != "rectangular":
        raise ExperimentalPlacementError(
            "Only rectangular parts may interact with experimental 41769."
        )
    if placement.orientation_degrees not in EXPERIMENTAL_ORIENTATIONS:
        raise ExperimentalPlacementError(
            "Rectangular parts support only quarter-turn orientations."
        )


def projection_polygon(placement: BrickPlacement) -> tuple[Point2, ...]:
    """Return the exact lattice-plane exterior footprint used for projection."""
    validate_placement(placement)
    if placement.brick_type.part_id == EXPERIMENTAL_PART_ID:
        return transformed_footprint(
            EXPERIMENTAL_PART_ID,
            placement.position.x,
            placement.position.y,
            placement.orientation_degrees,
        )
    length, width = _oriented_dimensions(placement)
    x, y = placement.position.x, placement.position.y
    return ((x, y), (x + length, y), (x + length, y + width), (x, y + width))


def physical_collision(first: BrickPlacement, second: BrickPlacement) -> bool:
    """Conservatively reject intersecting wedge/rectangular body envelopes.

    The wedge's one-plate body is its non-rectangular exterior prism, not its
    4x2 rectangular bounding box.  Its hollow underside is intentionally kept
    occupied, which can reject an otherwise possible fit but cannot accept an
    intersection through that unverified cavity.
    """
    validate_placement(first)
    validate_placement(second)
    if not _vertical_interiors_overlap(first, second):
        return False
    intersection = _clip_convex(projection_polygon(first), projection_polygon(second))
    return _polygon_area(intersection) > _EPSILON


def contains_body_point(placement: BrickPlacement, point: tuple[float, float, float]) -> bool:
    """Query the conservative body envelope at a continuous world-space point."""
    validate_placement(placement)
    x, y, z = point
    if not placement.position.z < z < placement.position.z + placement.brick_type.height_plates:
        return False
    return _point_in_convex_polygon(projection_polygon(placement), (x, y))


def is_supported(lower: BrickPlacement, upper: BrickPlacement) -> bool:
    """Return the verified direct-support rule, never an inferred attachment."""
    validate_placement(lower)
    validate_placement(upper)
    matches = matching_vertical_connectors(_world_male_connectors(lower), _world_connectors(upper))
    return bool(matches)


def has_ground_support(placement: BrickPlacement) -> bool:
    """Ground support is available only at the model's bottom plate plane."""
    validate_placement(placement)
    return placement.position.z == 0


def underside_receiver_coordinates(
    placement: BrickPlacement,
) -> tuple[tuple[float, float, float], ...]:
    """Return 41769a's five reviewed receiver coordinates in world space."""
    validate_placement(placement)
    if placement.brick_type.part_id != EXPERIMENTAL_PART_ID:
        return ()
    frame = PartLocalFrame(4, 2, 1)
    return tuple(
        _translate(rotate_part_local(receiver, frame, placement.orientation_degrees), placement)
        for receiver in _VERIFIED_UNDERSIDE_RECEIVERS
    )


def mechanical_adjacency(
    placements: Collection[BrickPlacement],
) -> tuple[ExperimentalConnection, ...]:
    """Return deterministic, source-backed connections for a safe test assembly."""
    placement_list = tuple(placements)
    for placement in placement_list:
        validate_placement(placement)
    edges: list[ExperimentalConnection] = []
    for lower_index, lower in enumerate(placement_list):
        for upper_index, upper in enumerate(placement_list):
            if lower_index == upper_index or not is_supported(lower, upper):
                continue
            matches = matching_vertical_connectors(
                _world_male_connectors(lower), _world_connectors(upper)
            )
            count = len(matches)
            if count:
                edges.append(ExperimentalConnection(lower_index, upper_index, count))
    return tuple(sorted(edges, key=lambda edge: (edge.lower_index, edge.upper_index)))


def validate_assembly(
    placements: Collection[BrickPlacement],
) -> tuple[ExperimentalConnection, ...]:
    """Accept only collision-free, grounded experimental assemblies.

    Every non-grounded part must have a verified direct support edge. This is
    not a general buildability validator; it deliberately rejects any
    relationship whose mechanics were not established for M12A.
    """
    placement_list = tuple(placements)
    edges = mechanical_adjacency(placement_list)
    for index, placement in enumerate(placement_list):
        if has_ground_support(placement):
            continue
        if not any(edge.upper_index == index for edge in edges):
            raise ExperimentalPlacementError("A placement lacks verified direct support.")
    for first_index, first in enumerate(placement_list):
        for second in placement_list[first_index + 1 :]:
            if physical_collision(first, second):
                raise ExperimentalPlacementError("Experimental assembly contains a body collision.")
    return edges


def _world_top_connectors(placement: BrickPlacement) -> tuple[WorldMechanicalConnector, ...]:
    if placement.brick_type.part_id != EXPERIMENTAL_PART_ID:
        return _world_connectors(placement)
    frame = PartLocalFrame(4, 2, 1)
    return tuple(
        WorldMechanicalConnector(
            _translate(rotate_part_local(stud, frame, placement.orientation_degrees), placement),
            CanonicalDirection.POSITIVE_Z,
            MechanicalInterfaceKind.MALE_STUD,
            MechanicalProvenance.SOURCE_BACKED,
        )
        for stud in _SOURCE_TOP_STUDS
    )


def _world_male_connectors(placement: BrickPlacement) -> tuple[WorldMechanicalConnector, ...]:
    return tuple(
        connector
        for connector in _world_top_connectors(placement)
        if connector.interface_kind == MechanicalInterfaceKind.MALE_STUD
    )


def _world_connectors(placement: BrickPlacement) -> tuple[WorldMechanicalConnector, ...]:
    if placement.brick_type.part_id == EXPERIMENTAL_PART_ID:
        top_connectors = _world_top_connectors(placement)
        return top_connectors + tuple(
            WorldMechanicalConnector(
                receiver,
                CanonicalDirection.NEGATIVE_Z,
                MechanicalInterfaceKind.STUD_RECEIVER,
                MechanicalProvenance.CURATED_VERIFIED,
            )
            for receiver in underside_receiver_coordinates(placement)
        )
    metadata = resolve_part_mechanical_metadata(placement.brick_type)
    if metadata is None:
        return ()
    return tuple(
        transform_connector_to_world(
            connector, placement.brick_type, placement.position, placement.orientation_degrees
        )
        for connector in metadata.connectors
    )


def _translate(
    point: tuple[float, float, float], placement: BrickPlacement
) -> tuple[float, float, float]:
    return (
        point[0] + placement.position.x,
        point[1] + placement.position.y,
        point[2] + placement.position.z,
    )


def _oriented_dimensions(placement: BrickPlacement) -> tuple[int, int]:
    length, width = placement.brick_type.length_studs, placement.brick_type.width_studs
    return (width, length) if placement.orientation_degrees in (90, 270) else (length, width)


def _vertical_interiors_overlap(first: BrickPlacement, second: BrickPlacement) -> bool:
    first_top = first.position.z + first.brick_type.height_plates
    second_top = second.position.z + second.brick_type.height_plates
    return max(first.position.z, second.position.z) < min(first_top, second_top)


def _clip_convex(subject: tuple[Point2, ...], clip: tuple[Point2, ...]) -> tuple[Point2, ...]:
    output = list(subject)
    for start, end in zip(clip, (*clip[1:], clip[0]), strict=True):
        source = output
        output = []
        if not source:
            return ()
        for previous, current in zip([source[-1], *source[:-1]], source, strict=True):
            previous_inside = _left_of(start, end, previous) >= -_EPSILON
            current_inside = _left_of(start, end, current) >= -_EPSILON
            if current_inside != previous_inside:
                output.append(_line_intersection(previous, current, start, end))
            if current_inside:
                output.append(current)
        if not output:
            return ()
    return tuple(output)


def _left_of(start: Point2, end: Point2, point: Point2) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])


def _line_intersection(
    first_start: Point2,
    first_end: Point2,
    second_start: Point2,
    second_end: Point2,
) -> Point2:
    first_dx, first_dy = first_end[0] - first_start[0], first_end[1] - first_start[1]
    second_dx, second_dy = second_end[0] - second_start[0], second_end[1] - second_start[1]
    denominator = first_dx * second_dy - first_dy * second_dx
    if isclose(denominator, 0.0, abs_tol=_EPSILON):
        return first_end
    numerator = (second_start[0] - first_start[0]) * second_dy - (
        second_start[1] - first_start[1]
    ) * second_dx
    ratio = numerator / denominator
    return (first_start[0] + ratio * first_dx, first_start[1] + ratio * first_dy)


def _polygon_area(polygon: tuple[Point2, ...]) -> float:
    if len(polygon) < 3:
        return 0.0
    pairs = zip(polygon, (*polygon[1:], polygon[0]), strict=True)
    return abs(sum(x1 * y2 - y1 * x2 for (x1, y1), (x2, y2) in pairs)) / 2


def _point_in_convex_polygon(polygon: tuple[Point2, ...], point: Point2) -> bool:
    return all(
        _left_of(start, end, point) >= -_EPSILON
        for start, end in zip(polygon, (*polygon[1:], polygon[0]), strict=True)
    )
