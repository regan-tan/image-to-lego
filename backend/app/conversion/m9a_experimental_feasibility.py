"""Offline-only M9A feasible-set helpers.

This module is not imported by production conversion routing. It defines the
sole M9A fixed-geometry coverage contribution: locked slope source profiles.
"""

from __future__ import annotations

from collections.abc import Collection

from app.conversion import core
from app.conversion.evaluation_alignment import ProjectionPixel


def locked_source_profile_coverage(
    locked_placements: Collection[core.BrickPlacement],
) -> frozenset[ProjectionPixel]:
    """Return witnesses physically supplied by locked non-rectangular profiles."""
    cells = {
        cell
        for placement in locked_placements
        if placement.brick_type.shape != "rectangular"
        for cell in core._placement_source_cells(placement)
    }
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )
