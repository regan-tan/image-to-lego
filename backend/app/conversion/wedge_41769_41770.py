"""Discrete XY geometry for the experimental 41769/41770 wedge plates.

This is fit and silhouette geometry only.  It intentionally does not make
claims about the parts' underside, clutch, or mechanical support.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

WEDGE_PART_IDS: Final = frozenset({"41769", "41770"})
WEDGE_PROJECTION_SUBDIVISIONS: Final = 4
WEDGE_LENGTH_STUDS: Final = 4
WEDGE_WIDTH_STUDS: Final = 2

FootprintPoint = tuple[float, float]
MicroCell = tuple[int, int]

_LOCAL_FOOTPRINTS: Final[dict[str, tuple[FootprintPoint, ...]]] = {
    "41769": ((0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 2.0)),
    "41770": ((0.0, 0.0), (4.0, 1.0), (4.0, 2.0), (0.0, 2.0)),
}


def oriented_dimensions(orientation_degrees: int) -> tuple[int, int]:
    if orientation_degrees in (0, 180):
        return WEDGE_LENGTH_STUDS, WEDGE_WIDTH_STUDS
    if orientation_degrees in (90, 270):
        return WEDGE_WIDTH_STUDS, WEDGE_LENGTH_STUDS
    raise ValueError("Wedge orientation must be 0, 90, 180, or 270 degrees.")


def transformed_footprint(
    part_id: str, x: int, y: int, orientation_degrees: int
) -> tuple[FootprintPoint, ...]:
    if part_id not in WEDGE_PART_IDS:
        raise ValueError(f"Unsupported wedge part: {part_id}.")
    length, width = WEDGE_LENGTH_STUDS, WEDGE_WIDTH_STUDS
    points: list[FootprintPoint] = []
    for local_x, local_y in _LOCAL_FOOTPRINTS[part_id]:
        if orientation_degrees == 0:
            rotated = (local_x, local_y)
        elif orientation_degrees == 90:
            rotated = (local_y, length - local_x)
        elif orientation_degrees == 180:
            rotated = (length - local_x, width - local_y)
        elif orientation_degrees == 270:
            rotated = (width - local_y, local_x)
        else:
            raise ValueError("Wedge orientation must be 0, 90, 180, or 270 degrees.")
        points.append((x + rotated[0], y + rotated[1]))
    return tuple(points)


def footprint_microcells(polygon: Collection[FootprintPoint]) -> frozenset[MicroCell]:
    points = tuple(polygon)
    cells: set[MicroCell] = set()
    for stud_y in range(int(min(y for _, y in points)), int(max(y for _, y in points))):
        for stud_x in range(int(min(x for x, _ in points)), int(max(x for x, _ in points))):
            for offset_y in range(WEDGE_PROJECTION_SUBDIVISIONS):
                for offset_x in range(WEDGE_PROJECTION_SUBDIVISIONS):
                    point = (
                        stud_x + (offset_x + 0.5) / WEDGE_PROJECTION_SUBDIVISIONS,
                        stud_y + (offset_y + 0.5) / WEDGE_PROJECTION_SUBDIVISIONS,
                    )
                    if _contains_point(points, point):
                        cells.add(
                            (
                                stud_x * WEDGE_PROJECTION_SUBDIVISIONS + offset_x,
                                stud_y * WEDGE_PROJECTION_SUBDIVISIONS + offset_y,
                            )
                        )
    return frozenset(cells)


def _contains_point(polygon: tuple[FootprintPoint, ...], point: FootprintPoint) -> bool:
    point_x, point_y = point
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        if (current_y > point_y) != (previous_y > point_y):
            boundary_x = (previous_x - current_x) * (point_y - current_y) / (
                previous_y - current_y
            ) + current_x
            if point_x < boundary_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside
