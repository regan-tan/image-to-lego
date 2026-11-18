"""Offline-only preflight helpers for the M10B physical-scale experiment."""

from __future__ import annotations

import tracemalloc
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Final

from app.conversion import core
from app.conversion.fixed_grid_experiment import _source_occupancy_for_evidence
from app.conversion.surface_grid_v4 import (
    _Candidate,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _male_connector_coordinates,
    _pixels_for_cells,
    _receiver_connector_coordinates,
    _support_contacts,
    _support_reachable_candidates,
    projection_hull_target,
)

PREFLIGHT_VERSION: Final = "m10b-physical-scale-preflight-v1"
CANDIDATE_LIMIT: Final = 4_000
SOLVER_TARGET_PARTS: Final = 24
BASELINE_CAP: Final = 60
LARGER_SCALE_CAP: Final = 120
EXACT_DUPLICATE_AUDIT_VERSION: Final = "m11b-exact-duplicate-audit-v1"
EXACT_DUPLICATE_AUDIT_MAX_CANDIDATES: Final = 12_000
EXACT_DUPLICATE_AUDIT_MAX_RUNTIME_SECONDS: Final = 180.0
EXACT_DUPLICATE_AUDIT_MAX_PEAK_MEMORY_BYTES: Final = 256 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class ExactDuplicateAudit:
    """Aggregate-only result from the read-only M11B candidate audit."""

    candidate_count: int
    projection_equivalent_groups: int
    projection_equivalent_duplicates: int
    geometry_equivalent_groups: int
    geometry_equivalent_duplicates: int
    mechanically_equivalent_groups: int
    mechanically_equivalent_duplicates: int
    fully_proven_equivalent_groups: int
    fully_proven_removable_duplicates: int
    runtime_seconds: float
    peak_memory_bytes: int

    @property
    def reduced_candidate_count(self) -> int:
        return self.candidate_count - self.fully_proven_removable_duplicates

    @property
    def maximum_exact_reduction_percent(self) -> float:
        if not self.candidate_count:
            return 0.0
        return round(self.fully_proven_removable_duplicates * 100 / self.candidate_count, 6)

    def record(self) -> dict[str, object]:
        record = asdict(self)
        record["reduced_candidate_count"] = self.reduced_candidate_count
        record["maximum_exact_reduction_percent"] = self.maximum_exact_reduction_percent
        return record


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


def audit_fixed_grid_candidate_duplicates(
    glb_bytes: bytes,
    *,
    grid: core.GridSize,
    up_axis: core.Axis,
    max_candidates: int = EXACT_DUPLICATE_AUDIT_MAX_CANDIDATES,
    max_runtime_seconds: float = EXACT_DUPLICATE_AUDIT_MAX_RUNTIME_SECONDS,
    max_peak_memory_bytes: int = EXACT_DUPLICATE_AUDIT_MAX_PEAK_MEMORY_BYTES,
) -> ExactDuplicateAudit:
    """Measure exact candidate classes without constructing a CP-SAT model.

    The complete placement identity is deliberately required for the final
    class.  Narrower signatures are reported as diagnostics only: matching a
    projection, body proxy, or local mechanical contacts does not by itself
    prove equal interactions with every other decision variable.
    """
    if max_candidates <= 0 or max_runtime_seconds <= 0 or max_peak_memory_bytes <= 0:
        raise ValueError("Exact-duplicate audit limits must be positive.")
    started = perf_counter()
    target, locked, candidates = _fixed_grid_candidates(glb_bytes, grid, up_axis)
    if len(candidates) > max_candidates:
        raise core.ConversionError("Diagnostic candidate count exceeds its configured limit.")
    # Tracing mesh loading and candidate creation overwhelms this deliberately
    # small diagnostic. Peak memory is therefore measured for the duplicate
    # analysis phase, after the already-bounded V6 enumeration has completed.
    tracemalloc.start()
    try:
        audit = _audit_candidate_duplicates(candidates, target, locked)
        _, peak_memory = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    runtime_seconds = perf_counter() - started
    if runtime_seconds > max_runtime_seconds:
        raise core.ConversionError(
            "Exact-duplicate diagnostic exceeded its configured runtime limit."
        )
    if peak_memory > max_peak_memory_bytes:
        raise core.ConversionError(
            "Exact-duplicate diagnostic exceeded its configured memory limit."
        )
    return ExactDuplicateAudit(*audit, runtime_seconds, peak_memory)


def _fixed_grid_candidates(
    glb_bytes: bytes, grid: core.GridSize, up_axis: core.Axis
) -> tuple[frozenset[core.GridPosition], tuple[core.BrickPlacement, ...], tuple[_Candidate, ...]]:
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
    target, _ = projection_hull_target(
        exterior, locked_slope_cells, grid, protected_empty_cells=protected
    )
    target = target - locked_occupied
    candidates = _exclude_locked_body_collisions(
        _enumerate_candidates(target, core.BRICK_CATALOGUE), locked_slopes
    )
    return target, locked_slopes, _support_reachable_candidates(candidates, target)


def _audit_candidate_duplicates(
    candidates: tuple[_Candidate, ...],
    target: frozenset[core.GridPosition],
    locked: tuple[core.BrickPlacement, ...],
) -> tuple[int, int, int, int, int, int, int, int, int]:
    """Return counts for increasingly strict, deterministic signatures."""
    from app.conversion.physical_geometry import local_physical_geometry

    base_z = min(cell.z for cell in target)
    producer_ids, consumer_contacts = _support_contacts(candidates, base_z)
    projection_groups: dict[object, int] = defaultdict(int)
    geometry_groups: dict[object, int] = defaultdict(int)
    mechanical_groups: dict[object, int] = defaultdict(int)
    full_groups: dict[object, int] = defaultdict(int)
    for candidate_id, candidate in enumerate(candidates):
        placement = candidate.placement
        pixels = tuple(sorted(_pixels_for_cells(candidate.cells)))
        # The immutable local set is shared from the cached physical geometry;
        # position/orientation make this an exact world-body representation
        # without retaining a second expanded microcell set per candidate.
        physical = (
            local_physical_geometry(placement.brick_type).occupied_local_microcells,
            placement.position,
            placement.orientation_degrees,
            placement.brick_type.length_studs,
            placement.brick_type.width_studs,
            placement.brick_type.height_plates,
        )
        producers = tuple(
            sorted(contact for contact, ids in producer_ids.items() if candidate_id in ids)
        )
        consumers = tuple(sorted(consumer_contacts[candidate_id]))
        males = tuple(sorted(_male_connector_coordinates((placement,))))
        receivers = tuple(sorted(_receiver_connector_coordinates(placement)))
        # Candidates already passed the exact same locked-body collision gate.
        locked_collision = (False,) * len(locked)
        projection_groups[pixels] += 1
        geometry_groups[physical] += 1
        mechanical = (physical, males, receivers, producers, consumers, locked_collision)
        mechanical_groups[mechanical] += 1
        # This identity is sufficient for all pairwise collision/support/coverage
        # coefficients and the serialized placement, not just their local proxies.
        full = (
            placement.brick_type.part_id,
            placement.position,
            placement.orientation_degrees,
            placement.color,
            placement.color_id,
            placement.color_name,
            placement.color_hex,
            candidate.cells,
            physical,
            mechanical,
            pixels,
        )
        full_groups[full] += 1
    return (
        len(candidates),
        _duplicate_group_count(projection_groups),
        _duplicate_count(projection_groups),
        _duplicate_group_count(geometry_groups),
        _duplicate_count(geometry_groups),
        _duplicate_group_count(mechanical_groups),
        _duplicate_count(mechanical_groups),
        _duplicate_group_count(full_groups),
        _duplicate_count(full_groups),
    )


def _duplicate_group_count(groups: dict[object, int]) -> int:
    return sum(count > 1 for count in groups.values())


def _duplicate_count(groups: dict[object, int]) -> int:
    return sum(count - 1 for count in groups.values() if count > 1)
