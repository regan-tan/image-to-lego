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
    SolverStage,
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
    source_subcell_count: int
    source_evidence_resolution: int
    stage_one: SolverStage
    stage_two: SolverStage


def convert_fixed_grid(
    glb_bytes: bytes,
    *,
    grid_size: core.GridSize,
    solver_target_parts: int,
    max_parts: int,
    up_axis: core.Axis,
    source_evidence_resolution: int = 1,
    shape_aware: bool = False,
    source_aware: bool = False,
) -> FixedGridExperimentResult:
    """Run fixed-lattice diagnostic packing with optional V6 refinement."""
    _validate_request(
        glb_bytes, grid_size, solver_target_parts, max_parts, source_evidence_resolution
    )
    mesh = core._load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, up_axis)
    occupancy, subcell_count = _source_occupancy_for_evidence(
        normalized, faces, grid_size, source_evidence_resolution
    )
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
        source_evidence_cells=occupancy.surface_cells if source_aware else None,
    )
    rectangles = core._color_placements(packing.placements, normalized, faces, mesh, grid_size)
    baseline_placements = locked_slopes + rectangles
    scaled_vertices = core._scale_vertices_to_grid(normalized, grid_size)
    if shape_aware:
        placements, shape_candidates, shape_accepted, shape_rejected = (
            core._shape_aware_4286_refinement(
                baseline_placements,
                scaled_vertices,
                faces,
                grid_size,
                solver_target_parts,
                protected,
                max_parts,
            )
        )
    else:
        placements = baseline_placements
        shape_candidates = 0
        shape_accepted = 0
        shape_rejected = 0
    _validate_output(placements, protected, max_parts)
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
        shape_aware_candidate_count=shape_candidates,
        shape_aware_accepted_refinement_count=shape_accepted,
        shape_aware_rejected_refinement_count=shape_rejected,
        shape_aware_rejection_reason=(
            None
            if placements != baseline_placements
            else "No legal V6 shape refinement was accepted."
        )
        if shape_aware
        else None,
        physical_collision_pair_count=len(colliding_placement_pairs(placements)),
        unsupported_evaluated_placement_count=analyze_buildability(
            placements
        ).unsupported_placement_count,
    )
    model = core.LegoModel(
        placements=placements,
        part_count=len(placements),
        dimensions=core._model_dimensions(placements),
        metadata=core.AlgorithmMetadata(
            algorithm_version=(
                "surface-grid-v8-source-aware-fixed-lattice-diagnostic"
                if source_aware
                else (
                    "surface-grid-v6-fixed-lattice-diagnostic"
                    if shape_aware
                    else "surface-grid-v5-fixed-grid-diagnostic"
                )
            ),
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
        model,
        occupancy.surface_cells,
        target_cells,
        protected,
        len(required_pixels),
        subcell_count,
        source_evidence_resolution,
        packing.stage_one,
        packing.stage_two,
    )


def _validate_request(
    glb_bytes: bytes,
    grid_size: core.GridSize,
    solver_target_parts: int,
    max_parts: int,
    source_evidence_resolution: int,
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
    if source_evidence_resolution not in (1, 2):
        raise core.ConversionError("Diagnostic source evidence resolution must be 1 or 2.")


def _source_occupancy_for_evidence(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    grid_size: core.GridSize,
    resolution: int,
) -> tuple[core.SourceOccupancy, int]:
    if resolution == 1:
        occupancy = core._source_occupancy(vertices, faces, grid_size)
        return occupancy, len(occupancy.surface_cells)
    subcell_grid = core.GridSize(
        grid_size.width_studs * resolution,
        grid_size.depth_studs * resolution,
        grid_size.height_plates * resolution,
    )
    subcell_occupancy = core._source_occupancy(vertices, faces, subcell_grid)
    reduced = frozenset(
        core.GridPosition(cell.x // resolution, cell.y // resolution, cell.z // resolution)
        for cell in subcell_occupancy.surface_cells
    )
    occupancy = core.SourceOccupancy(
        reduced,
        core._safe_interior_cells(
            reduced, grid_size, mesh_is_watertight=subcell_occupancy.mesh_is_watertight
        ),
        subcell_occupancy.mesh_is_watertight,
    )
    return occupancy, len(subcell_occupancy.surface_cells)


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
