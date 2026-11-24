"""Offline M14B diagnosis and warm-start experiment; never used by conversion."""

from __future__ import annotations

import tracemalloc
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from time import perf_counter

from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.fixed_grid_experiment import _source_occupancy_for_evidence
from app.conversion.surface_grid_v4 import (
    SOLVER_RANDOM_SEED,
    SOLVER_WORKERS,
    _add_part_limit,
    _build_model,
    _Candidate,
    _candidate_ids_by_cell,
    _cells_by_pixel,
    _coverage_score,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _pixels_for_cells,
    _support_contacts,
    _support_reachable_candidates,
    projection_hull_target,
)

SCHEMA_VERSION = "m14b-high-resolution-feasibility-v1"
DEFAULT_DETERMINISTIC_TIME = 40.0
MINIMUM_SEED_COVERAGE_PIXELS = 1


@dataclass(frozen=True, slots=True)
class M14BInput:
    grid: core.GridSize
    target_cells: frozenset[core.GridPosition]
    required_pixels: frozenset[tuple[str, int, int]]
    locked: tuple[core.BrickPlacement, ...]
    locked_cells: frozenset[core.GridPosition]
    baseline_rectangles: tuple[core.BrickPlacement, ...]
    candidates_before_collision: int
    candidates_after_collision: int
    candidates_after_collision_filter: tuple[_Candidate, ...]
    candidates: tuple[_Candidate, ...]
    triangle_count: int
    source_cells: int


@dataclass(frozen=True, slots=True)
class SeedDiagnostics:
    selected_ids: tuple[int, ...] | None
    reason: str
    total_baseline_placements: int
    mapped_placements: int
    rejected: tuple[dict[str, object], ...]
    coverage_pixels: int
    compatible_coverage_pixels: int
    incompatible_coverage_pixels: int
    construction_seconds: float
    validation_seconds: float = 0.0
    validation_status: str | None = None

    def record(self) -> dict[str, object]:
        return {
            "validated": self.selected_ids is not None
            and self.validation_status in {"FEASIBLE", "OPTIMAL"},
            "reason": self.reason,
            "totalV3Rectangles": self.total_baseline_placements,
            "mappedV3Rectangles": self.mapped_placements,
            "rejectedV3Rectangles": list(self.rejected),
            "selectedParts": 0 if self.selected_ids is None else len(self.selected_ids),
            "coveragePixels": self.coverage_pixels,
            "compatibleCoveragePixels": self.compatible_coverage_pixels,
            "incompatibleCoveragePixels": self.incompatible_coverage_pixels,
            "constructionSeconds": self.construction_seconds,
            "validationSeconds": self.validation_seconds,
            "validationStatus": self.validation_status,
        }


def build_input(glb_bytes: bytes, *, grid: core.GridSize, up_axis: core.Axis) -> M14BInput:
    """Reconstruct the exact reliable V4 stage-one candidate set offline."""
    mesh = core._load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, up_axis)
    occupancy, _ = _source_occupancy_for_evidence(normalized, faces, grid, 1)
    locked, locked_cells = core._place_supported_slopes(occupancy.surface_cells)
    locked_occupied = frozenset(
        cell for placement in locked for cell in core._placement_source_cells(placement)
    )
    baseline_rectangles = core.pack_occupied_cells(occupancy.surface_cells - locked_cells)
    exterior = frozenset(
        cell
        for placement in baseline_rectangles
        for cell in core._placement_cells(placement)
        if cell not in locked_occupied
    )
    protected = core._v5_protected_empty_cells(occupancy, grid)
    target, required = projection_hull_target(
        exterior, locked_cells, grid, protected_empty_cells=protected
    )
    target = target - locked_occupied
    before_collision = _enumerate_candidates(target, core.BRICK_CATALOGUE)
    after_collision = _exclude_locked_body_collisions(before_collision, locked)
    candidates = _support_reachable_candidates(after_collision, target)
    return M14BInput(
        grid,
        target,
        frozenset(required),
        tuple(locked),
        locked_cells,
        baseline_rectangles,
        len(before_collision),
        len(after_collision),
        after_collision,
        candidates,
        len(faces),
        len(occupancy.surface_cells),
    )


def run_experiment(
    prepared: M14BInput,
    *,
    max_parts: int,
    effective_grid_target: int,
    deterministic_time: float = DEFAULT_DETERMINISTIC_TIME,
) -> dict[str, object]:
    """Compare no hint and a validated V3 rectangular seed on one unchanged model."""
    if not prepared.candidates:
        raise ValueError("M14B has no retained candidates.")
    if max_parts < len(prepared.locked):
        raise ValueError("The hard part limit is lower than locked placements.")
    variable_pixels = tuple(
        sorted(prepared.required_pixels - _pixels_for_cells(prepared.locked_cells))
    )
    candidate_ids_by_cell = _candidate_ids_by_cell(prepared.target_cells, prepared.candidates)
    cells_by_pixel = _cells_by_pixel(prepared.target_cells)
    seed_diagnostics = diagnose_and_construct_seed(prepared, variable_pixels, max_parts=max_parts)
    selected_seed = seed_diagnostics.selected_ids
    if selected_seed is not None:
        validation_started = perf_counter()
        seed_valid, validation_status = _validate_seed(
            prepared,
            variable_pixels,
            candidate_ids_by_cell,
            cells_by_pixel,
            max_parts,
            selected_seed,
        )
        seed_diagnostics = SeedDiagnostics(
            selected_seed if seed_valid else None,
            "validated_against_stage_one_constraints"
            if seed_valid
            else f"seed_constraint_validation_{validation_status.lower()}",
            seed_diagnostics.total_baseline_placements,
            seed_diagnostics.mapped_placements,
            seed_diagnostics.rejected,
            seed_diagnostics.coverage_pixels,
            seed_diagnostics.compatible_coverage_pixels,
            seed_diagnostics.incompatible_coverage_pixels,
            seed_diagnostics.construction_seconds,
            perf_counter() - validation_started,
            validation_status,
        )
        selected_seed = seed_diagnostics.selected_ids
    tracemalloc.start()
    try:
        unhinted = _solve_arm(
            prepared,
            variable_pixels,
            candidate_ids_by_cell,
            cells_by_pixel,
            max_parts,
            deterministic_time,
            selected_seed=None,
        )
        hinted: dict[str, object] | None = None
        if selected_seed is not None:
            hinted = _solve_arm(
                prepared,
                variable_pixels,
                candidate_ids_by_cell,
                cells_by_pixel,
                max_parts,
                deterministic_time,
                selected_seed=selected_seed,
            )
        _, peak_memory = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "grid": asdict(prepared.grid),
        "effectiveGridTarget": effective_grid_target,
        "gridCellCount": prepared.grid.cell_count,
        "sourceTriangleCount": prepared.triangle_count,
        "sourceOccupancyCells": prepared.source_cells,
        "projectionHullCells": len(prepared.target_cells),
        "lockedPlacements": len(prepared.locked),
        "candidateCounts": {
            "beforeCollision": prepared.candidates_before_collision,
            "afterCollision": prepared.candidates_after_collision,
            "afterSupportReachability": len(prepared.candidates),
        },
        "warmStart": seed_diagnostics.record(),
        "unhinted": unhinted,
        "hinted": hinted,
        "peakPythonMemoryBytes": peak_memory,
    }


def diagnose_and_construct_seed(
    prepared: M14BInput,
    variable_pixels: tuple[tuple[str, int, int], ...],
    *,
    max_parts: int,
) -> SeedDiagnostics:
    """Classify the V3 seed, then close compatible choices under direct support."""
    started = perf_counter()
    initial_candidates = _enumerate_candidates(prepared.target_cells, core.BRICK_CATALOGUE)
    stages = (
        ("initial_enumeration", initial_candidates),
        ("locked_body_collision", prepared.candidates_after_collision_filter),
        ("support_reachability", prepared.candidates),
    )
    by_stage = {
        name: {
            stable_placement_id(candidate.placement): index
            for index, candidate in enumerate(candidates)
        }
        for name, candidates in stages
    }
    retained = by_stage["support_reachability"]
    initial_producers, initial_consumers = _support_contacts(
        initial_candidates, min(cell.z for cell in prepared.target_cells)
    )
    compatible: list[int] = []
    rejected: list[dict[str, object]] = []
    for placement in prepared.baseline_rectangles:
        placement_id = stable_placement_id(placement)
        candidate_id = retained.get(placement_id)
        if candidate_id is not None:
            compatible.append(candidate_id)
            continue
        rejected.append(
            _rejected_placement_record(
                placement,
                placement_id,
                by_stage,
                initial_candidates,
                initial_producers,
                initial_consumers,
                retained,
            )
        )
    selected = _support_closed_selection(prepared, compatible, max_parts)
    coverage = _coverage_score(selected, prepared.candidates, variable_pixels)
    compatible_coverage = _coverage_score(compatible, prepared.candidates, variable_pixels)
    incompatible_coverage = len(variable_pixels) - compatible_coverage
    reason = "constructed_compatible_seed"
    if len(selected) + len(prepared.locked) > max_parts:
        selected = ()
        coverage = 0
        reason = "constructed_seed_exceeds_hard_part_limit"
    elif coverage < MINIMUM_SEED_COVERAGE_PIXELS:
        selected = ()
        reason = "no_meaningful_compatible_seed"
    return SeedDiagnostics(
        tuple(selected) if selected else None,
        reason,
        len(prepared.baseline_rectangles),
        len(compatible),
        tuple(rejected),
        coverage,
        compatible_coverage,
        incompatible_coverage,
        perf_counter() - started,
    )


def _rejected_placement_record(
    placement: core.BrickPlacement,
    placement_id: str,
    by_stage: Mapping[str, Mapping[str, int]],
    initial_candidates: tuple[_Candidate, ...],
    initial_producers: Mapping[tuple[float, float, float], tuple[int, ...]],
    initial_consumers: tuple[tuple[tuple[float, float, float], ...], ...],
    retained: Mapping[str, int],
) -> dict[str, object]:
    if placement_id not in by_stage["initial_enumeration"]:
        reason = "absent_from_initial_enumeration"
    elif placement_id not in by_stage["locked_body_collision"]:
        reason = "removed_by_locked_body_collision"
    elif placement_id not in by_stage["support_reachability"]:
        reason = "removed_by_support_reachability"
    else:
        reason = "unclassified_candidate_identity_mismatch"
    initial_id = by_stage["initial_enumeration"].get(placement_id)
    contacts = () if initial_id is None else initial_consumers[initial_id]
    possible_supporters = {
        stable_placement_id(initial_candidates[candidate_id].placement)
        for contact in contacts
        for candidate_id in initial_producers.get(contact, ())
    }
    return {
        "placementId": placement_id,
        "partId": placement.brick_type.part_id,
        "position": {
            "x": placement.position.x,
            "y": placement.position.y,
            "z": placement.position.z,
        },
        "orientationDegrees": placement.orientation_degrees,
        "reason": reason,
        "supportDependencies": [list(contact) for contact in contacts],
        "retainedPossibleSupporterCount": sum(
            placement_id in retained for placement_id in possible_supporters
        ),
    }


def _support_closed_selection(
    prepared: M14BInput, initial_ids: list[int], max_parts: int
) -> tuple[int, ...]:
    """Add only retained, non-overlapping direct supporters in a stable order."""
    candidates = prepared.candidates
    base_z = min(cell.z for cell in prepared.target_cells)
    producers, consumers = _support_contacts(candidates, base_z)
    selected: set[int] = set()
    occupied: set[core.GridPosition] = set()

    def add(candidate_id: int) -> bool:
        if candidate_id in selected:
            return True
        checkpoint_ids = set(selected)
        checkpoint_cells = set(occupied)
        candidate = candidates[candidate_id]
        if candidate.cells & occupied or len(selected) + len(prepared.locked) >= max_parts:
            return False
        contacts = consumers[candidate_id]
        producer_ids = tuple(
            sorted({producer for contact in contacts for producer in producers.get(contact, ())})
        )
        if contacts and not producer_ids:
            return False
        if producer_ids and not any(producer in selected for producer in producer_ids):
            for producer in producer_ids:
                if add(producer):
                    break
                selected.clear()
                selected.update(checkpoint_ids)
                occupied.clear()
                occupied.update(checkpoint_cells)
            if not any(producer in selected for producer in producer_ids):
                selected.clear()
                selected.update(checkpoint_ids)
                occupied.clear()
                occupied.update(checkpoint_cells)
                return False
        if len(selected) + len(prepared.locked) >= max_parts:
            selected.clear()
            selected.update(checkpoint_ids)
            occupied.clear()
            occupied.update(checkpoint_cells)
            return False
        selected.add(candidate_id)
        occupied.update(candidate.cells)
        return True

    for candidate_id in sorted(
        initial_ids, key=lambda item: (candidates[item].placement.position.z, item)
    ):
        add(candidate_id)
    return tuple(sorted(selected))


def _validate_seed(
    prepared: M14BInput,
    variable_pixels: tuple[tuple[str, int, int], ...],
    candidate_ids_by_cell: Mapping[core.GridPosition, tuple[int, ...]],
    cells_by_pixel: Mapping[tuple[str, int, int], tuple[core.GridPosition, ...]],
    max_parts: int,
    selected_seed: tuple[int, ...],
) -> tuple[bool, str]:
    """Prove the complete seed satisfies the same hard stage-one constraints."""
    model = _build_model(
        prepared.candidates,
        prepared.target_cells,
        variable_pixels,
        candidate_ids_by_cell,
        cells_by_pixel,
    )
    _add_part_limit(model.model, model.selected, max_parts, len(prepared.locked))
    selected = frozenset(selected_seed)
    for index, variable in enumerate(model.selected):
        model.model.add(variable == int(index in selected))
    solver = cp_model.CpSolver()
    status = solver.solve(model.model)
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return True, solver.status_name(status)
    return False, solver.status_name(status)


def _solve_arm(
    prepared: M14BInput,
    variable_pixels: tuple[tuple[str, int, int], ...],
    candidate_ids_by_cell: Mapping[core.GridPosition, tuple[int, ...]],
    cells_by_pixel: Mapping[tuple[str, int, int], tuple[core.GridPosition, ...]],
    max_parts: int,
    deterministic_time: float,
    *,
    selected_seed: tuple[int, ...] | None,
) -> dict[str, object]:
    started = perf_counter()
    model = _build_model(
        prepared.candidates,
        prepared.target_cells,
        variable_pixels,
        candidate_ids_by_cell,
        cells_by_pixel,
    )
    _add_part_limit(model.model, model.selected, max_parts, len(prepared.locked))
    if selected_seed is not None:
        for index, variable in enumerate(model.selected):
            model.model.add_hint(variable, int(index in frozenset(selected_seed)))
    model.model.maximize(sum(model.coverage))
    construction_seconds = perf_counter() - started
    proto = model.model.proto
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = deterministic_time
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    solve_started = perf_counter()
    status = solver.solve(model.model)
    wall_seconds = perf_counter() - solve_started
    feasible = status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    response = solver.response_proto
    return {
        "model": {
            "variables": len(proto.variables),
            "constraints": len(proto.constraints),
            "coverageVariables": len(model.coverage),
        },
        "modelConstructionSeconds": construction_seconds,
        "status": solver.status_name(status),
        "solutionFound": feasible,
        "objective": int(round(solver.objective_value)) if feasible else None,
        "bestBound": int(round(solver.best_objective_bound)) if feasible else None,
        "deterministicTime": response.deterministic_time,
        "wallClockSeconds": wall_seconds,
        "responseStats": solver.response_stats(),
    }
