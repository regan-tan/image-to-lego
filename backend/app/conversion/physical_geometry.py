"""Small, deterministic physical occupancy proxies for supported LEGO parts.

These shapes are deliberately separate from LDraw render meshes and connector
metadata.  They describe only the main body used by the shape-aware collision
gate.  Studs and underside interfaces are not body volume here because they
need their own mechanical contract.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from functools import cache
from hashlib import sha256
from math import sqrt

from app.conversion.core import BrickPlacement
from app.conversion.part_catalogue import LegoPart
from app.conversion.part_coordinates import PartLocalFrame, rotate_part_local
from app.conversion.wedge_41769_41770 import WEDGE_PART_IDS, transformed_footprint

SUBDIVISIONS_PER_STUD = 4
SUBDIVISIONS_PER_PLATE = 4
_EPSILON = 1e-9

MicroCell = tuple[int, int, int]
Point3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class PhysicalGeometry:
    """A cached, centre-sampled body proxy in canonical units."""

    part_id: str
    occupied_local_microcells: frozenset[MicroCell]
    fingerprint: str


def physical_microcells(placement: BrickPlacement) -> frozenset[MicroCell]:
    """Return body cells in world space; touching cells never overlap."""
    geometry = local_physical_geometry(placement.brick_type)
    frame = PartLocalFrame(
        placement.brick_type.length_studs,
        placement.brick_type.width_studs,
        placement.brick_type.height_plates,
    )
    cells: set[MicroCell] = set()
    for micro_x, micro_y, micro_z in geometry.occupied_local_microcells:
        point = (
            (micro_x + 0.5) / SUBDIVISIONS_PER_STUD,
            (micro_y + 0.5) / SUBDIVISIONS_PER_STUD,
            (micro_z + 0.5) / SUBDIVISIONS_PER_PLATE,
        )
        world_x, world_y, world_z = rotate_part_local(
            point, frame, placement.orientation_degrees
        )
        cells.add(
            (
                round((world_x + placement.position.x) * SUBDIVISIONS_PER_STUD - 0.5),
                round((world_y + placement.position.y) * SUBDIVISIONS_PER_STUD - 0.5),
                round((world_z + placement.position.z) * SUBDIVISIONS_PER_PLATE - 0.5),
            )
        )
    return frozenset(cells)


def placements_overlap(first: BrickPlacement, second: BrickPlacement) -> bool:
    """Whether two body proxies have interior sampled-volume overlap."""
    return bool(physical_microcells(first) & physical_microcells(second))


def colliding_placement_pairs(
    placements: Collection[BrickPlacement],
) -> tuple[tuple[int, int], ...]:
    """Find all body collisions in stable placement-index order."""
    indexed = tuple(placements)
    occupied_by_cell: dict[MicroCell, list[int]] = {}
    collisions: set[tuple[int, int]] = set()
    for index, placement in enumerate(indexed):
        for cell in physical_microcells(placement):
            existing = occupied_by_cell.setdefault(cell, [])
            collisions.update((previous, index) for previous in existing)
            existing.append(index)
    return tuple(sorted(collisions))


@cache
def local_physical_geometry(part: LegoPart) -> PhysicalGeometry:
    """Build one documented body proxy per part without using render-mesh bounds.

    15068 uses a quarter-cylinder profile as a conservative fitting/collision
    proxy.  It remains mechanically unevaluated and therefore cannot be emitted
    by the production fitter.  The proxy is intentionally not presented as an
    authoritative solid model of the hollow moulding.
    """
    cells = frozenset(
        (x, y, z)
        for z in range(part.height_plates * SUBDIVISIONS_PER_PLATE)
        for y in range(part.width_studs * SUBDIVISIONS_PER_STUD)
        for x in range(part.length_studs * SUBDIVISIONS_PER_STUD)
        if _contains_local_body(part, _microcell_centre(x, y, z))
    )
    fingerprint_input = (
        f"{part.part_id}:{SUBDIVISIONS_PER_STUD}:{SUBDIVISIONS_PER_PLATE}:"
        + ",".join(f"{x}/{y}/{z}" for x, y, z in sorted(cells))
    )
    return PhysicalGeometry(part.part_id, cells, sha256(fingerprint_input.encode()).hexdigest())


def _microcell_centre(x: int, y: int, z: int) -> Point3:
    return (
        (x + 0.5) / SUBDIVISIONS_PER_STUD,
        (y + 0.5) / SUBDIVISIONS_PER_STUD,
        (z + 0.5) / SUBDIVISIONS_PER_PLATE,
    )


def _contains_local_body(part: LegoPart, point: Point3) -> bool:
    x, y, z = point
    if not (0.0 <= x < part.length_studs and 0.0 <= y < part.width_studs):
        return False
    if part.part_id in WEDGE_PART_IDS:
        return z < 1.0 and _point_in_polygon(
            transformed_footprint(part.part_id, 0, 0, 0), (x, y)
        )
    if part.part_id == "4286":
        # Reviewed 33-degree 3 x 1 body profile; studs are interfaces, not body.
        roof = min(3.0, x + 0.5)
        return z < roof
    if part.part_id == "15068":
        # 2 x 2 curved slope: quarter-cylinder envelope, sampled at 1/4 plate.
        radius = 2.0
        return z < sqrt(radius * radius - (x - radius) ** 2)
    return z < part.height_plates


def _point_in_polygon(
    polygon: tuple[tuple[float, float], ...], point: tuple[float, float]
) -> bool:
    point_x, point_y = point
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        if (current_y > point_y) != (previous_y > point_y):
            boundary_x = (previous_x - current_x) * (point_y - current_y) / (
                previous_y - current_y
            ) + current_x
            if point_x < boundary_x - _EPSILON:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside
