"""Offline-only preflight helpers for the M10B physical-scale experiment."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Final

from app.conversion import core
from app.conversion.fixed_grid_experiment import _source_occupancy_for_evidence
from app.conversion.surface_grid_v4 import (
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _support_contacts,
    _support_reachable_candidates,
    projection_hull_target,
)

PREFLIGHT_VERSION: Final = "m10b-physical-scale-preflight-v1"
CANDIDATE_LIMIT: Final = 4_000
SOLVER_TARGET_PARTS: Final = 24
BASELINE_CAP: Final = 60
LARGER_SCALE_CAP: Final = 120


@dataclass(frozen=True, slots=True)
class PhysicalScalePreflight:
    """Measured fixed-grid model-size indicators before CP-SAT is invoked."""

    grid: core.GridSize
    source_surface_cells: int
    protected_empty_cells: int
    target_cells: int
    required_projection_pixels: int
    locked_placements: int
    candidate_count_before_reachability: int
    candidate_count_after_reachability: int
    candidate_count_by_family: dict[str, int]
    support_contact_count: int
    accepted: bool
    decision: str

    def record(self) -> dict[str, object]:
        return asdict(self)


def scaled_grid(grid: core.GridSize, requested_scale: float) -> core.GridSize:
    """Round an explicit grid, retaining real LEGO-unit lattice positions."""
    if requested_scale <= 0:
        raise ValueError("Requested physical scale must be positive.")
    return core.GridSize(
        max(1, round(grid.width_studs * requested_scale)),
        max(1, round(grid.depth_studs * requested_scale)),
        max(1, round(grid.height_plates * requested_scale)),
    )


def nominal_envelope_mm(grid: core.GridSize) -> dict[str, float]:
    return {
        "width": grid.width_studs * core.STUD_WIDTH_MM,
        "depth": grid.depth_studs * core.STUD_WIDTH_MM,
        "height": grid.height_plates * core.PLATE_HEIGHT_MM,
    }


def scale_factors(grid: core.GridSize, baseline: core.GridSize) -> dict[str, float]:
    return {
        "width": round(grid.width_studs / baseline.width_studs, 6),
        "depth": round(grid.depth_studs / baseline.depth_studs, 6),
        "height": round(grid.height_plates / baseline.height_plates, 6),
    }


def preflight_fixed_grid(
    glb_bytes: bytes,
    *,
    grid: core.GridSize,
    up_axis: core.Axis,
    candidate_limit: int = CANDIDATE_LIMIT,
) -> PhysicalScalePreflight:
    """Measure the same V5 candidate inputs without starting an optimizer."""
    if candidate_limit <= 0:
        raise ValueError("Candidate limit must be positive.")
    if grid.cell_count > core.MAX_GRID_CELLS:
        raise core.ConversionError("Diagnostic grid exceeds the configured grid safety limit.")
    mesh = core._load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, up_axis)
    occupancy, _ = _source_occupancy_for_evidence(normalized, faces, grid, 1)
    locked_slopes, locked_slope_cells = core._place_supported_slopes(occupancy.surface_cells)
    locked_occupied = frozenset(
        cell for placement in locked_slopes for cell in core._placement_source_cells(placement)
    )
    rectangles = core.pack_occupied_cells(occupancy.surface_cells - locked_slope_cells)
    exterior = frozenset(
        cell
        for placement in rectangles
        for cell in core._placement_cells(placement)
        if cell not in locked_occupied
    )
    protected = core._v5_protected_empty_cells(occupancy, grid)
    target, required_pixels = projection_hull_target(
        exterior, locked_slope_cells, grid, protected_empty_cells=protected
    )
    target = target - locked_occupied
    candidates = _exclude_locked_body_collisions(
        _enumerate_candidates(target, core.BRICK_CATALOGUE), locked_slopes
    )
    reachable = _support_reachable_candidates(candidates, target)
    _, consumer_contacts = _support_contacts(reachable, min(cell.z for cell in target))
    family_counts = Counter(candidate.placement.brick_type.family for candidate in reachable)
    accepted = len(reachable) <= candidate_limit
    return PhysicalScalePreflight(
        grid,
        len(occupancy.surface_cells),
        len(protected),
        len(target),
        len(required_pixels),
        len(locked_slopes),
        len(candidates),
        len(reachable),
        dict(sorted(family_counts.items())),
        sum(len(contacts) for contacts in consumer_contacts),
        accepted,
        "accepted" if accepted else "candidate_limit_exceeded",
    )
