"""Offline measurements for enclosed top-view openings.

These functions report a source-projection mask and its overlap with placements.
They do not alter conversion candidate selection or production output.
"""

from __future__ import annotations

from collections.abc import Collection

from app.conversion.core import BrickPlacement, GridSize

OPENING_DIAGNOSTIC_SUBDIVISIONS = 4
_TRIANGLE_EPSILON = 1e-9


def projected_opening_microcells(
    scaled_vertices: Collection[tuple[float, float, float]],
    faces: Collection[tuple[int, int, int]],
    grid_size: GridSize,
) -> frozenset[tuple[int, int]]:
    """Return enclosed empty XY samples in a source mesh's projection.

    Callers should record source watertightness alongside this diagnostic. The
    result is a two-dimensional measurement, not a claim about empty volume.
    """
    vertices = tuple(scaled_vertices)
    width = grid_size.width_studs * OPENING_DIAGNOSTIC_SUBDIVISIONS
    depth = grid_size.depth_studs * OPENING_DIAGNOSTIC_SUBDIVISIONS
    triangles = tuple((vertices[a], vertices[b], vertices[c]) for a, b, c in faces)
    occupied = {
        (micro_x, micro_y)
        for micro_y in range(depth)
        for micro_x in range(width)
        if any(
            _point_in_projected_triangle(
                (
                    (micro_x + 0.5) / OPENING_DIAGNOSTIC_SUBDIVISIONS,
                    (micro_y + 0.5) / OPENING_DIAGNOSTIC_SUBDIVISIONS,
                ),
                triangle,
            )
            for triangle in triangles
        )
    }
    empty = {(micro_x, micro_y) for micro_y in range(depth) for micro_x in range(width)} - occupied
    exterior = {
        point for point in empty if point[0] in (0, width - 1) or point[1] in (0, depth - 1)
    }
    pending = list(exterior)
    while pending:
        micro_x, micro_y = pending.pop()
        for neighbor in (
            (micro_x - 1, micro_y),
            (micro_x + 1, micro_y),
            (micro_x, micro_y - 1),
            (micro_x, micro_y + 1),
        ):
            if neighbor in empty and neighbor not in exterior:
                exterior.add(neighbor)
                pending.append(neighbor)
    return frozenset(empty - exterior)


def placement_projected_opening_overlap(
    placement: BrickPlacement,
    opening_microcells: Collection[tuple[int, int]],
) -> int:
    """Count projected-opening samples covered by a rectangular placement."""
    if placement.brick_type.shape != "rectangular":
        return 0
    length = placement.brick_type.length_studs
    width = placement.brick_type.width_studs
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    occupied = {
        (micro_x, micro_y)
        for micro_y in range(
            placement.position.y * OPENING_DIAGNOSTIC_SUBDIVISIONS,
            (placement.position.y + width) * OPENING_DIAGNOSTIC_SUBDIVISIONS,
        )
        for micro_x in range(
            placement.position.x * OPENING_DIAGNOSTIC_SUBDIVISIONS,
            (placement.position.x + length) * OPENING_DIAGNOSTIC_SUBDIVISIONS,
        )
    }
    return len(occupied & set(opening_microcells))


def _point_in_projected_triangle(
    point: tuple[float, float],
    triangle: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
) -> bool:
    (first_x, first_y, _), (second_x, second_y, _), (third_x, third_y, _) = triangle
    point_x, point_y = point
    denominator = (second_y - third_y) * (first_x - third_x) + (third_x - second_x) * (
        first_y - third_y
    )
    if abs(denominator) <= _TRIANGLE_EPSILON:
        return False
    first_weight = (
        (second_y - third_y) * (point_x - third_x)
        + (third_x - second_x) * (point_y - third_y)
    ) / denominator
    second_weight = (
        (third_y - first_y) * (point_x - third_x)
        + (first_x - third_x) * (point_y - third_y)
    ) / denominator
    third_weight = 1.0 - first_weight - second_weight
    return min(first_weight, second_weight, third_weight) >= -_TRIANGLE_EPSILON
