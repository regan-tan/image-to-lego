"""Offline-only fixed-grid V5 experiment support.

This module is deliberately not imported by the API, workers, or ``convert_glb``.
It exposes the existing reliable packing safeguards with an explicitly supplied
grid so diagnostic sweeps can separate grid resolution from the hard part cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.conversion import core
from app.conversion.buildability import analyze_buildability
from app.conversion.physical_geometry import colliding_placement_pairs
from app.conversion.surface_grid_v4 import (
    _enumerate_candidates,
    projection_hull_target,
    solve_surface_grid_v4,
)


@dataclass(frozen=True, slots=True)
class FixedGridExperimentResult:
    """Completed diagnostic conversion and the cells used at each stage."""

    model: core.LegoModel
    source_cells: frozenset[core.GridPosition]
    projection_hull_cells: frozenset[core.GridPosition]
    protected_empty_cells: frozenset[core.GridPosition]
    required_projection_pixel_count: int


def convert_fixed_grid(
    glb_bytes: bytes,
    *,
    grid_size: core.GridSize,
    solver_target_parts: int,
    max_parts: int,
    up_axis: core.Axis,
) -> FixedGridExperimentResult:
    """Run reliable V5 packing at an exact grid without changing production routing."""
    _validate_request(glb_bytes, grid_size, solver_target_parts, max_parts)
    mesh = core._load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, up_axis)
    occupancy = core._source_occupancy(normalized, faces, grid_size)
    locked_slopes, locked_slope_cells = core._place_supported_slopes(occupancy.surface_cells)
    locked_occupied = frozenset(
        cell for placement in locked_slopes for cell in core._placement_source_cells(placement)
    )
    baseline_rectangles = core.pack_occupied_cells(occupancy.surface_cells - locked_slope_cells)
    exterior_cells = frozenset(
        cell
        for placement in baseline_rectangles
        for cell in core._placement_cells(placement)
        if cell not in locked_occupied
    )
    protected = core._v5_protected_empty_cells(occupancy, grid_size)
    unprotected_target, _ = projection_hull_target(exterior_cells, locked_slope_cells, grid_size)
    target_cells, required_pixels = projection_hull_target(
        exterior_cells, locked_slope_cells, grid_size, protected_empty_cells=protected
    )
    target_cells = target_cells - locked_occupied
    packing = solve_surface_grid_v4(
        target_cells,
        required_pixels,
        locked_slope_cells,
        core.BRICK_CATALOGUE,
        target_parts=solver_target_parts,
        locked_placements=locked_slopes,
        max_parts=max_parts,
        reliable_repair=True,
        avoid_locked_physical_collisions=True,
    )
    rectangles = core._color_placements(packing.placements, normalized, faces, mesh, grid_size)
    placements = locked_slopes + rectangles
    _validate_output(placements, protected, max_parts)
    scaled_vertices = core._scale_vertices_to_grid(normalized, grid_size)
    diagnostics = core.ConversionDiagnostics(
        requested_max_parts=max_parts,
        source_is_watertight=occupancy.mesh_is_watertight,
        surface_cell_count=len(occupancy.surface_cells),
        allowed_interior_cell_count=len(occupancy.safe_interior_cells),
        protected_empty_cell_count=len(protected),
        unknown_cell_count=0
        if occupancy.mesh_is_watertight
        else grid_size.cell_count - len(occupancy.surface_cells),
        candidate_count_before_protection=len(
            _enumerate_candidates(unprotected_target, core.BRICK_CATALOGUE)
        ),
        candidate_count_after_protection=len(
            _enumerate_candidates(target_cells, core.BRICK_CATALOGUE)
        ),
        candidate_count_after_reachability_pruning=packing.candidate_count,
        locked_placement_count=len(locked_slopes),
        stage_one_status=packing.stage_one.status,
        stage_one_has_incumbent=packing.stage_one.status in {"OPTIMAL", "FEASIBLE"},
        stage_two_status=packing.stage_two.status,
        stage_two_has_incumbent=packing.stage_two.status in {"OPTIMAL", "FEASIBLE"},
        repair_candidate_count=sum(
            item.candidate_count for item in packing.repair_diagnostics.components
        ),
        repair_final_placement_count=sum(
            item.selected_repair_count for item in packing.repair_diagnostics.components
        ),
        physical_collision_pair_count=0,
        unsupported_evaluated_placement_count=0,
    )
    model = core.LegoModel(
        placements=placements,
        part_count=len(placements),
        dimensions=core._model_dimensions(placements),
        metadata=core.AlgorithmMetadata(
            algorithm_version="surface-grid-v5-fixed-grid-diagnostic",
            source_sha256=sha256(glb_bytes).hexdigest(),
            target_parts=solver_target_parts,
            occupied_cell_count=len(
                {cell for placement in placements for cell in core._placement_cells(placement)}
            ),
            grid_size=grid_size,
            candidate_count=packing.candidate_count,
            occupancy_mode=core.OCCUPANCY_MODE,
            fidelity=core._fidelity_for_placements(
                scaled_vertices, faces, placements, solver_target_parts
            ),
            diagnostics=diagnostics,
        ),
    )
    return FixedGridExperimentResult(
        model, occupancy.surface_cells, target_cells, protected, len(required_pixels)
    )


def _validate_request(
    glb_bytes: bytes, grid_size: core.GridSize, solver_target_parts: int, max_parts: int
) -> None:
    if len(glb_bytes) > core.MAX_INPUT_BYTES:
        raise core.ConversionError("GLB input exceeds the configured size limit.")
    if min(grid_size.width_studs, grid_size.depth_studs, grid_size.height_plates) < 1:
        raise core.ConversionError("Diagnostic grid dimensions must be positive.")
    if grid_size.cell_count > core.MAX_GRID_CELLS:
        raise core.ConversionError("Diagnostic grid exceeds the configured grid safety limit.")
    if not 0 < solver_target_parts <= core.MAX_TARGET_PARTS:
        raise core.ConversionError("Diagnostic solver target is outside converter limits.")
    if not 0 < max_parts <= core.MAX_TARGET_PARTS:
        raise core.ConversionError("Diagnostic hard part cap is outside converter limits.")


def _validate_output(
    placements: tuple[core.BrickPlacement, ...],
    protected: frozenset[core.GridPosition],
    max_parts: int,
) -> None:
    if len(placements) > max_parts:
        raise core.ConversionError("Diagnostic conversion exceeded the requested hard part limit.")
    if any(core._placement_source_cells(placement) & protected for placement in placements):
        raise core.ConversionError("Diagnostic conversion occupied source-protected empty space.")
    if analyze_buildability(placements).unsupported_placement_count:
        raise core.ConversionError(
            "Diagnostic conversion produced unsupported evaluated placements."
        )
    if colliding_placement_pairs(placements):
        raise core.ConversionError("Diagnostic conversion detected physical body collisions.")
