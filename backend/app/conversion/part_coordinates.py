"""Canonical coordinates for authoritative LDraw part-local features.

This module deliberately does not infer mechanical connections. It converts
continuous LDraw locations into the application's part-local stud/plate frame
and can recognize the standard rectangular brick/plate stud grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Literal

LDU_PER_STUD = 20.0
LDU_PER_PLATE = 8.0
STANDARD_STUD_GRID_TOLERANCE = 1e-6

Point3 = tuple[float, float, float]
LongAxis = Literal["x", "z"]


@dataclass(frozen=True, slots=True)
class PartLocalFrame:
    """The catalogue dimensions and authoritative LDraw long axis for one part."""

    length_studs: int
    width_studs: int
    height_plates: int
    ldraw_long_axis: LongAxis


@dataclass(frozen=True, slots=True)
class StandardStudGridPosition:
    """A location on the standard rectangular brick/plate stud grid.

    This is not a general connector type. Source-backed studs and other LEGO
    interfaces may have valid continuous canonical coordinates outside it.
    """

    x: float
    y: float
    z: int


def ldraw_to_part_local(point: Point3, frame: PartLocalFrame) -> Point3:
    """Convert a continuous LDraw point to the canonical local stud/plate frame.

    The canonical origin is the lower-left footprint corner at the part's
    bottom plane.  ``x`` follows catalogue length, ``y`` follows catalogue
    width, and ``z`` increases upwards in plate units.  The LDraw origin is
    centred horizontally and its top surface is at LDraw y=0.
    """
    ldraw_x, ldraw_y, ldraw_z = point
    if frame.ldraw_long_axis == "x":
        local_x = ldraw_x / LDU_PER_STUD + frame.length_studs / 2
        local_y = ldraw_z / LDU_PER_STUD + frame.width_studs / 2
    else:
        local_x = ldraw_z / LDU_PER_STUD + frame.length_studs / 2
        local_y = ldraw_x / LDU_PER_STUD + frame.width_studs / 2
    local_z = frame.height_plates - ldraw_y / LDU_PER_PLATE
    return (local_x, local_y, local_z)


def part_local_to_ldraw(point: Point3, frame: PartLocalFrame) -> Point3:
    """Invert :func:`ldraw_to_part_local` without snapping or rounding."""
    local_x, local_y, local_z = point
    if frame.ldraw_long_axis == "x":
        ldraw_x = (local_x - frame.length_studs / 2) * LDU_PER_STUD
        ldraw_z = (local_y - frame.width_studs / 2) * LDU_PER_STUD
    else:
        ldraw_z = (local_x - frame.length_studs / 2) * LDU_PER_STUD
        ldraw_x = (local_y - frame.width_studs / 2) * LDU_PER_STUD
    ldraw_y = (frame.height_plates - local_z) * LDU_PER_PLATE
    return (ldraw_x, ldraw_y, ldraw_z)


def rotate_part_local(point: Point3, frame: PartLocalFrame, orientation_degrees: int) -> Point3:
    """Rotate a local point into a placement footprint at 0/90/180/270 degrees.

    ``90`` is clockwise when viewing the XY plane from positive z.  This is the
    established placement convention used by the frontend and wedge footprint.
    """
    x, y, z = point
    if orientation_degrees == 0:
        return (x, y, z)
    if orientation_degrees == 90:
        return (y, frame.length_studs - x, z)
    if orientation_degrees == 180:
        return (frame.length_studs - x, frame.width_studs - y, z)
    if orientation_degrees == 270:
        return (frame.width_studs - y, x, z)
    raise ValueError("Part orientation must be 0, 90, 180, or 270 degrees.")


def standard_stud_grid_coordinate(point: Point3) -> StandardStudGridPosition | None:
    """Return a standard rectangular stud-grid coordinate without moving it.

    Standard rectangular brick/plate stud centers use half-integer horizontal
    coordinates and integer vertical plate planes. The tolerance is only for
    deterministic decimal LDraw values, never an instruction to snap geometry.
    """
    x, y, z = point
    snapped_x = _half_integer_if_close(x)
    snapped_y = _half_integer_if_close(y)
    snapped_z = round(z)
    if snapped_x is None or snapped_y is None or not isclose(
        z, snapped_z, abs_tol=STANDARD_STUD_GRID_TOLERANCE
    ):
        return None
    return StandardStudGridPosition(snapped_x, snapped_y, snapped_z)


def is_standard_stud_grid_position(point: Point3) -> bool:
    """Whether a point is on the standard rectangular brick/plate stud grid."""
    return standard_stud_grid_coordinate(point) is not None


def _half_integer_if_close(value: float) -> float | None:
    snapped = round(value - 0.5) + 0.5
    if not isclose(value, snapped, abs_tol=STANDARD_STUD_GRID_TOLERANCE):
        return None
    return snapped
