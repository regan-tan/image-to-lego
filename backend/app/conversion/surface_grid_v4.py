"""Bounded CP-SAT packing for the opt-in surface-grid-v4 converter."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from time import perf_counter

from ortools.sat.python import cp_model

from app.conversion.buildability import analyze_buildability, directly_supports
from app.conversion.core import BrickPlacement, BrickType, ConversionError, GridPosition, GridSize
from app.conversion.mechanical_connectors import (
    MechanicalInterfaceKind,
    WorldMechanicalConnector,
    resolve_part_mechanical_metadata,
    transform_connector_to_world,
)

# These are deterministic-work budgets, not wall-clock SLAs. Runtime can vary by machine.
STAGE_ONE_MAX_DETERMINISTIC_TIME = 20.0
DETAILED_STAGE_ONE_MAX_DETERMINISTIC_TIME = 40.0
DETAILED_TARGET_PARTS = 600
STAGE_TWO_MAX_DETERMINISTIC_TIME = 7.25
LOCAL_REPAIR_MAX_DETERMINISTIC_TIME = 7.25
SOLVER_RANDOM_SEED = 0
SOLVER_WORKERS = 1
LOCKED_SUPPORT_FAILURE = "A locked verified placement has no possible mechanical supporter."
LOCAL_REPAIR_BOUND_FAILURE = "surface-grid-v4 support repair could not fit its local part bound."
REPAIR_ALLOWANCE_PER_UNSUPPORTED_CONSUMER = 2

ProjectionPixel = tuple[str, int, int]
SupportContact = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SolverStage:
    status: str
    objective_value: int | None
    runtime_seconds: float
    is_optimal: bool
    best_objective_bound: int | None = None


@dataclass(frozen=True, slots=True)
class RepairComponentDiagnostics:
    """Deterministic evidence for one bounded local support repair."""

    component_id: int
    unsupported_locked_indices: tuple[int, ...]
    receiver_coordinates: tuple[tuple[float, float, float], ...]
    mutable_baseline_indices: tuple[int, ...]
    frozen_anchor_indices: tuple[int, ...]
    frozen_dependent_indices: tuple[int, ...]
    candidate_count: int
    selected_repair_count: int
    allowed_repair_count: int
    removed_baseline_count: int
    retained_baseline_count: int
    added_placement_count: int
    part_count_delta: int
    minimum_z: int | None
    maximum_z: int | None
    maximum_support_chain_depth: int
    baseline_projection_pixels: int
    repaired_projection_pixels: int
    lost_baseline_pixels: int
    new_pixels: int
    support_edges: tuple[tuple[int, int], ...]
    solver_stages: tuple[SolverStage, ...]
    runtime_seconds: float


@dataclass(frozen=True, slots=True)
class RepairDiagnostics:
    components: tuple[RepairComponentDiagnostics, ...]
    solver_call_count: int


@dataclass(frozen=True, slots=True)
class V4PackingResult:
    placements: tuple[BrickPlacement, ...]
    stage_one: SolverStage
    stage_two: SolverStage
    achieved_coverage: int
    candidate_count: int
    repair_diagnostics: RepairDiagnostics


class V4SolveFailure(ConversionError):
    """surface-grid-v4 could not produce a structurally valid CP-SAT result."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    placement: BrickPlacement
    cells: frozenset[GridPosition]


@dataclass(frozen=True, slots=True)
class _Model:
    model: cp_model.CpModel
    selected: tuple[cp_model.IntVar, ...]
    coverage: tuple[cp_model.IntVar, ...]


@dataclass(frozen=True, slots=True)
class _RepairSolveResult:
    repaired_ids: tuple[int, ...]
    selected_local_ids: frozenset[int]
    solver_stages: tuple[SolverStage, ...]


def solve_surface_grid_v4(
    target_cells: Collection[GridPosition],
    required_pixels: Collection[ProjectionPixel],
    locked_slope_cells: Collection[GridPosition],
    catalogue: tuple[BrickType, ...],
    *,
    target_parts: int,
    locked_placements: Collection[BrickPlacement] = (),
) -> V4PackingResult:
    """Select non-overlapping, direct-support-connected rectangles inside A.

    ``target_cells`` is a candidate witness volume. It is deliberately not a
    volume that must be filled. Locked slope cells contribute fixed projection
    coverage but cannot be occupied by new rectangular placements.
    """
    target = frozenset(target_cells)
    locked = tuple(locked_placements)
    required = frozenset(required_pixels)
    fixed_pixels = _pixels_for_cells(locked_slope_cells)
    variable_pixels = tuple(sorted(required - fixed_pixels, key=_pixel_order))
    if not target:
        _validate_fixed_placements(locked)
        if not variable_pixels:
            return _empty_packing_result(required, fixed_pixels, candidate_count=0)
        raise V4SolveFailure("surface-grid-v4 has no rectangular candidate volume.")

    candidates = _support_reachable_candidates(_enumerate_candidates(target, catalogue), target)

    if not candidates:
        _validate_fixed_placements(locked)
        if not variable_pixels:
            return _empty_packing_result(required, fixed_pixels, candidate_count=0)
        raise V4SolveFailure("surface-grid-v4 has no rectangular candidates for required coverage.")

    candidate_ids_by_cell = _candidate_ids_by_cell(target, candidates)
    cells_by_pixel = _cells_by_pixel(target)

    stage_one_model = _build_model(
        candidates,
        target,
        variable_pixels,
        candidate_ids_by_cell,
        cells_by_pixel,
    )
    stage_one_model.model.maximize(sum(stage_one_model.coverage))
    stage_one_solver, stage_one = _solve(
        stage_one_model.model, _stage_one_deterministic_budget(target_parts)
    )
    if not _has_usable_incumbent(stage_one):
        raise V4SolveFailure("surface-grid-v4 stage one did not provide a usable incumbent.")

    stage_one_ids = _selected_ids(stage_one_solver, stage_one_model.selected)
    achieved_coverage = stage_one.objective_value
    if _coverage_score(stage_one_ids, candidates, variable_pixels) != achieved_coverage:
        raise V4SolveFailure("Stage one coverage disagreed with its selected placements.")
    stage_two_model = _build_model(
        candidates,
        target,
        variable_pixels,
        candidate_ids_by_cell,
        cells_by_pixel,
    )
    stage_two_model.model.add(sum(stage_two_model.coverage) == achieved_coverage)
    stage_two_model.model.minimize(sum(stage_two_model.selected))
    _add_hint(stage_two_model, stage_one_ids)
    stage_two_solver, stage_two = _solve(stage_two_model.model, STAGE_TWO_MAX_DETERMINISTIC_TIME)

    selected_ids = stage_one_ids
    if _has_usable_incumbent(stage_two):
        selected_ids = _selected_ids(stage_two_solver, stage_two_model.selected)
        if _coverage_score(selected_ids, candidates, variable_pixels) != achieved_coverage:
            raise V4SolveFailure("Stage two changed the stage-one projection coverage.")

    placements, repair_diagnostics = _repair_locked_verified_support(
        candidates,
        selected_ids,
        locked,
        _model_base_z(target, locked),
        variable_pixels,
        cells_by_pixel,
    )
    _validate_placements(placements, target, locked)
    return V4PackingResult(
        placements=placements,
        stage_one=stage_one,
        stage_two=stage_two,
        achieved_coverage=achieved_coverage + len(required & fixed_pixels),
        candidate_count=len(candidates),
        repair_diagnostics=repair_diagnostics,
    )


def _stage_one_deterministic_budget(target_parts: int) -> float:
    if target_parts >= DETAILED_TARGET_PARTS:
        return DETAILED_STAGE_ONE_MAX_DETERMINISTIC_TIME
    return STAGE_ONE_MAX_DETERMINISTIC_TIME


def _empty_packing_result(
    required: frozenset[ProjectionPixel],
    fixed_pixels: frozenset[ProjectionPixel],
    *,
    candidate_count: int,
) -> V4PackingResult:
    skipped_stage = SolverStage(
        status="NOT_RUN",
        objective_value=0,
        runtime_seconds=0.0,
        is_optimal=False,
        best_objective_bound=0,
    )
    return V4PackingResult(
        placements=(),
        stage_one=skipped_stage,
        stage_two=skipped_stage,
        achieved_coverage=len(required & fixed_pixels),
        candidate_count=candidate_count,
        repair_diagnostics=RepairDiagnostics(components=(), solver_call_count=0),
    )


def projection_hull_target(
    rectangular_cells: Collection[GridPosition],
    locked_slope_cells: Collection[GridPosition],
    grid_size: GridSize,
) -> tuple[frozenset[GridPosition], frozenset[ProjectionPixel]]:
    """Build A from v3 exterior evidence while preserving locked slope cells."""
    exterior = frozenset(rectangular_cells)
    locked = frozenset(locked_slope_cells)
    if exterior & locked:
        raise ConversionError("Rectangular v3 cells overlap locked slope cells.")
    required = _pixels_for_cells(exterior | locked)
    target = frozenset(
        GridPosition(x, y, z)
        for z in range(grid_size.height_plates)
        for y in range(grid_size.depth_studs)
        for x in range(grid_size.width_studs)
        if ("front", x, z) in required
        and ("side", y, z) in required
        and ("top", x, y) in required
        and GridPosition(x, y, z) not in locked
    )
    return exterior | target, required


def _enumerate_candidates(
    target: frozenset[GridPosition],
    catalogue: tuple[BrickType, ...],
) -> tuple[_Candidate, ...]:
    candidates: list[_Candidate] = []
    for position in sorted(target, key=_cell_order):
        for brick_type in catalogue:
            if brick_type.shape != "rectangular" or not brick_type.verified_color_ids:
                continue
            orientations = (0,) if brick_type.length_studs == brick_type.width_studs else (0, 90)
            for orientation in orientations:
                placement = BrickPlacement(brick_type, position, orientation)
                cells = _placement_cells(placement)
                if cells.issubset(target):
                    candidates.append(_Candidate(placement, cells))
    return tuple(candidates)


def _support_reachable_candidates(
    candidates: tuple[_Candidate, ...],
    target: frozenset[GridPosition],
) -> tuple[_Candidate, ...]:
    """Keep only placements with a possible direct-support chain to A's base."""
    base_z = min(cell.z for cell in target)
    producers: dict[SupportContact, list[int]] = defaultdict(list)
    for candidate_id, candidate in enumerate(candidates):
        top_z = candidate.placement.position.z + candidate.placement.brick_type.height_plates
        for x, y in _stud_footprint(candidate.placement):
            producers[(x, y, top_z)].append(candidate_id)

    reachable: set[int] = set()
    for candidate_id, candidate in enumerate(candidates):
        placement = candidate.placement
        if placement.position.z == base_z:
            reachable.add(candidate_id)
            continue
        if any(
            producer in reachable
            for x, y in _stud_footprint(placement)
            for producer in producers[(x, y, placement.position.z)]
        ):
            reachable.add(candidate_id)
    return tuple(candidate for index, candidate in enumerate(candidates) if index in reachable)


def _build_model(
    candidates: tuple[_Candidate, ...],
    target: frozenset[GridPosition],
    variable_pixels: tuple[ProjectionPixel, ...],
    candidate_ids_by_cell: Mapping[GridPosition, tuple[int, ...]],
    cells_by_pixel: Mapping[ProjectionPixel, tuple[GridPosition, ...]],
) -> _Model:
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(len(candidates)))
    occupied = {
        cell: model.new_bool_var(f"z_{cell.x}_{cell.y}_{cell.z}")
        for cell in sorted(target, key=_cell_order)
    }
    coverage = tuple(
        model.new_bool_var(f"y_{view}_{first}_{second}") for view, first, second in variable_pixels
    )
    for cell, variable in occupied.items():
        model.add(variable == sum(selected[index] for index in candidate_ids_by_cell[cell]))

    base_z = min(cell.z for cell in target)
    producer_ids, consumer_contacts = _support_contacts(candidates, base_z)
    consumer_contact_set = {contact for values in consumer_contacts for contact in values}
    contacts = tuple(sorted(set(producer_ids) | consumer_contact_set))
    support = {
        contact: model.new_bool_var(f"s_{contact[0]}_{contact[1]}_{contact[2]}")
        for contact in contacts
    }
    for contact, variable in support.items():
        model.add(variable == sum(selected[index] for index in producer_ids.get(contact, ())))
    for candidate_id, contacts_for_candidate in enumerate(consumer_contacts):
        if contacts_for_candidate:
            model.add(
                selected[candidate_id]
                <= sum(support[contact] for contact in contacts_for_candidate)
            )

    for pixel, variable in zip(variable_pixels, coverage, strict=True):
        model.add_max_equality(variable, [occupied[cell] for cell in cells_by_pixel.get(pixel, ())])
    return _Model(model, selected, coverage)


def _support_contacts(
    candidates: tuple[_Candidate, ...],
    base_z: int,
) -> tuple[dict[SupportContact, tuple[int, ...]], tuple[tuple[SupportContact, ...], ...]]:
    producers: dict[SupportContact, list[int]] = defaultdict(list)
    consumers: list[tuple[SupportContact, ...]] = []
    for candidate_id, candidate in enumerate(candidates):
        placement = candidate.placement
        top_z = placement.position.z + placement.brick_type.height_plates
        footprint = _stud_footprint(placement)
        for x, y in footprint:
            producers[(x, y, top_z)].append(candidate_id)
        consumers.append(
            ()
            if placement.position.z == base_z
            else tuple((x, y, placement.position.z) for x, y in footprint)
        )
    return {contact: tuple(ids) for contact, ids in producers.items()}, tuple(consumers)


def _repair_locked_verified_support(
    candidates: tuple[_Candidate, ...],
    selected_ids: Collection[int],
    locked_placements: Collection[BrickPlacement],
    base_z: int,
    variable_pixels: tuple[ProjectionPixel, ...],
    cells_by_pixel: Mapping[ProjectionPixel, tuple[GridPosition, ...]],
) -> tuple[tuple[BrickPlacement, ...], RepairDiagnostics]:
    """Repair fixed verified support without perturbing the global packing.

    The global v4 CP-SAT model deliberately stays focused on projection packing.
    When a fixed 4286 has no selected rectangular supporter, this builds a small
    replacement model around the conflicting baseline rectangles.  Rectangles
    outside that region remain frozen, which avoids destabilising the global
    search merely to satisfy a handful of fixed connector consumers.
    """
    locked = tuple(locked_placements)
    baseline_ids = frozenset(selected_ids)
    baseline_placements = tuple(
        candidates[candidate_id].placement for candidate_id in sorted(baseline_ids)
    )
    if baseline_placements and not analyze_buildability(
        (*locked, *baseline_placements)
    ).unsupported_placement_count:
        return baseline_placements, RepairDiagnostics(components=(), solver_call_count=0)

    candidate_males = tuple(
        frozenset(_male_connector_coordinates((candidate.placement,))) for candidate in candidates
    )
    candidate_receivers = tuple(
        frozenset(_receiver_connector_coordinates(candidate.placement)) for candidate in candidates
    )
    locked_males = _male_connector_coordinates(locked)
    baseline_males = locked_males | set().union(
        *(candidate_males[candidate_id] for candidate_id in baseline_ids)
    )
    candidate_ids_by_male_coordinate: dict[tuple[float, float, float], list[int]] = defaultdict(
        list
    )
    for candidate_id, males in enumerate(candidate_males):
        for coordinate in males:
            candidate_ids_by_male_coordinate[coordinate].append(candidate_id)

    unsupported_locked: list[BrickPlacement] = []
    required_supporter_ids: set[int] = set()
    all_supporter_ids: set[int] = set()
    unsupported_locked_indices: list[int] = []
    for locked_index, consumer in enumerate(locked):
        if consumer.position.z == base_z:
            continue
        receivers = _receiver_connector_coordinates(consumer)
        if not receivers:
            continue
        if receivers & baseline_males:
            continue
        supporter_ids = sorted(
            {
                candidate_id
                for receiver_coordinate in receivers
                for candidate_id in candidate_ids_by_male_coordinate[receiver_coordinate]
            }
        )
        if not supporter_ids:
            raise V4SolveFailure(LOCKED_SUPPORT_FAILURE)
        all_supporter_ids.update(supporter_ids)
        smallest_supporter_size = min(
            len(candidates[candidate_id].cells) for candidate_id in supporter_ids
        )
        unsupported_locked.append(consumer)
        unsupported_locked_indices.append(locked_index)
        required_supporter_ids.update(
            candidate_id
            for candidate_id in supporter_ids
            if len(candidates[candidate_id].cells) == smallest_supporter_size
        )

    if not unsupported_locked:
        return (
            tuple(candidates[candidate_id].placement for candidate_id in sorted(baseline_ids)),
            RepairDiagnostics(components=(), solver_call_count=0),
        )

    mutable_baseline_ids = _repair_mutable_baseline_ids(
        candidates,
        baseline_ids,
        required_supporter_ids,
        candidate_males,
        candidate_receivers,
        locked_males,
        base_z,
    )
    frozen_ids = baseline_ids - mutable_baseline_ids
    frozen_cells = {
        cell for candidate_id in frozen_ids for cell in candidates[candidate_id].cells
    }
    frozen_males = locked_males | set().union(
        *(candidate_males[candidate_id] for candidate_id in frozen_ids)
    )
    anchored_supporter_ids = {
        candidate_id
        for candidate_id in all_supporter_ids
        if candidate_receivers[candidate_id] & frozen_males
        and not (candidates[candidate_id].cells & frozen_cells)
    }
    local_ids = _repair_local_candidate_ids(
        candidates,
        mutable_baseline_ids,
        required_supporter_ids,
        anchored_supporter_ids,
        frozen_cells,
        candidate_males,
        candidate_receivers,
        frozen_males,
        base_z,
    )
    if not local_ids:
        raise V4SolveFailure(LOCKED_SUPPORT_FAILURE)

    boundary_support_contacts = _repair_boundary_support_contacts(
        candidates,
        mutable_baseline_ids,
        required_supporter_ids,
        candidate_receivers,
        frozen_males,
    )
    allowed_repair_count = _repair_part_count_bound(
        len(mutable_baseline_ids),
        len(unsupported_locked),
        len(boundary_support_contacts),
    )
    repair_result = _solve_support_repair(
        candidates,
        baseline_ids,
        frozen_ids,
        local_ids,
        unsupported_locked,
        candidate_males,
        candidate_receivers,
        locked_males,
        base_z,
        variable_pixels,
        cells_by_pixel,
        allowed_repair_count,
    )
    component = _repair_component_diagnostics(
        candidates,
        baseline_ids,
        mutable_baseline_ids,
        frozen_ids,
        local_ids,
        repair_result,
        tuple(unsupported_locked_indices),
        unsupported_locked,
        candidate_males,
        candidate_receivers,
        frozen_males,
        base_z,
        variable_pixels,
        cells_by_pixel,
        allowed_repair_count,
    )
    return (
        tuple(candidates[candidate_id].placement for candidate_id in repair_result.repaired_ids),
        RepairDiagnostics(
            components=(component,),
            solver_call_count=len(repair_result.solver_stages),
        ),
    )


def _repair_component_diagnostics(
    candidates: tuple[_Candidate, ...],
    baseline_ids: frozenset[int],
    mutable_baseline_ids: frozenset[int],
    frozen_ids: frozenset[int],
    local_ids: tuple[int, ...],
    repair_result: _RepairSolveResult,
    unsupported_locked_indices: tuple[int, ...],
    unsupported_locked: Collection[BrickPlacement],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    frozen_males: set[tuple[float, float, float]],
    base_z: int,
    variable_pixels: tuple[ProjectionPixel, ...],
    cells_by_pixel: Mapping[ProjectionPixel, tuple[GridPosition, ...]],
    allowed_repair_count: int,
) -> RepairComponentDiagnostics:
    baseline_order = tuple(sorted(baseline_ids))
    baseline_indices = {candidate_id: index for index, candidate_id in enumerate(baseline_order)}
    selected_local_ids = repair_result.selected_local_ids
    selected_receivers = set().union(
        *(candidate_receivers[candidate_id] for candidate_id in selected_local_ids)
    )
    frozen_anchor_ids = {
        candidate_id
        for candidate_id in frozen_ids
        if candidate_males[candidate_id] & selected_receivers
    }
    baseline_pixels = _projection_pixels_for_candidate_ids(baseline_ids, candidates)
    repaired_pixels = _projection_pixels_for_candidate_ids(repair_result.repaired_ids, candidates)
    support_edges, maximum_support_chain_depth = _repair_support_graph(
        candidates,
        selected_local_ids,
        unsupported_locked,
        candidate_males,
        candidate_receivers,
        frozen_males,
        base_z,
    )
    selected_placements = tuple(
        candidates[candidate_id].placement for candidate_id in sorted(selected_local_ids)
    )
    removed_baseline_ids = mutable_baseline_ids - selected_local_ids
    retained_baseline_ids = mutable_baseline_ids & selected_local_ids
    added_ids = selected_local_ids - baseline_ids
    return RepairComponentDiagnostics(
        component_id=0,
        unsupported_locked_indices=unsupported_locked_indices,
        receiver_coordinates=tuple(
            sorted(
                {
                    coordinate
                    for placement in unsupported_locked
                    for coordinate in _receiver_connector_coordinates(placement)
                }
            )
        ),
        mutable_baseline_indices=tuple(
            baseline_indices[candidate_id] for candidate_id in sorted(mutable_baseline_ids)
        ),
        frozen_anchor_indices=tuple(
            baseline_indices[candidate_id] for candidate_id in sorted(frozen_anchor_ids)
        ),
        # The mutable closure moves every baseline dependent that could lose
        # support into the repair model, so a frozen dependent would violate
        # the component boundary invariant.
        frozen_dependent_indices=(),
        candidate_count=len(local_ids),
        selected_repair_count=len(selected_local_ids),
        allowed_repair_count=allowed_repair_count,
        removed_baseline_count=len(removed_baseline_ids),
        retained_baseline_count=len(retained_baseline_ids),
        added_placement_count=len(added_ids),
        part_count_delta=len(repair_result.repaired_ids) - len(baseline_ids),
        minimum_z=(min(placement.position.z for placement in selected_placements)
                   if selected_placements else None),
        maximum_z=(max(placement.position.z for placement in selected_placements)
                   if selected_placements else None),
        maximum_support_chain_depth=maximum_support_chain_depth,
        baseline_projection_pixels=len(baseline_pixels),
        repaired_projection_pixels=len(repaired_pixels),
        lost_baseline_pixels=len(baseline_pixels - repaired_pixels),
        new_pixels=len(repaired_pixels - baseline_pixels),
        support_edges=support_edges,
        solver_stages=repair_result.solver_stages,
        runtime_seconds=sum(stage.runtime_seconds for stage in repair_result.solver_stages),
    )


def _projection_pixels_for_candidate_ids(
    candidate_ids: Collection[int], candidates: tuple[_Candidate, ...]
) -> frozenset[ProjectionPixel]:
    return _pixels_for_cells(
        frozenset(
            cell for candidate_id in candidate_ids for cell in candidates[candidate_id].cells
        )
    )


def _repair_support_graph(
    candidates: tuple[_Candidate, ...],
    selected_local_ids: frozenset[int],
    unsupported_locked: Collection[BrickPlacement],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    frozen_males: set[tuple[float, float, float]],
    base_z: int,
) -> tuple[tuple[tuple[int, int], ...], int]:
    depths: dict[int, int] = {}
    edges: set[tuple[int, int]] = set()
    for candidate_id in sorted(
        selected_local_ids,
        key=lambda value: _cell_order(candidates[value].placement.position),
    ):
        placement = candidates[candidate_id].placement
        receivers = candidate_receivers[candidate_id]
        supporter_ids = tuple(
            supporter_id
            for supporter_id in selected_local_ids
            if candidate_males[supporter_id] & receivers
        )
        for supporter_id in supporter_ids:
            edges.add((supporter_id, candidate_id))
        if placement.position.z == base_z or receivers & frozen_males:
            depths[candidate_id] = 1
        else:
            depths[candidate_id] = 1 + max(depths[supporter_id] for supporter_id in supporter_ids)
    consumer_depths = [
        depths[supporter_id]
        for placement in unsupported_locked
        for supporter_id in selected_local_ids
        if candidate_males[supporter_id] & _receiver_connector_coordinates(placement)
    ]
    return tuple(sorted(edges)), max(consumer_depths, default=0)


def _repair_mutable_baseline_ids(
    candidates: tuple[_Candidate, ...],
    baseline_ids: frozenset[int],
    required_supporter_ids: set[int],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    locked_males: set[tuple[float, float, float]],
    base_z: int,
) -> frozenset[int]:
    """Expand only through baseline rectangles that could lose direct support."""
    supporter_cells = {
        cell for candidate_id in required_supporter_ids for cell in candidates[candidate_id].cells
    }
    mutable = {
        candidate_id
        for candidate_id in baseline_ids
        if candidates[candidate_id].cells & supporter_cells
    }
    while True:
        frozen_ids = baseline_ids - mutable
        frozen_males = locked_males | set().union(
            *(candidate_males[candidate_id] for candidate_id in frozen_ids)
        )
        newly_mutable = {
            candidate_id
            for candidate_id in frozen_ids
            if candidates[candidate_id].placement.position.z != base_z
            and not (candidate_receivers[candidate_id] & frozen_males)
        }
        if not newly_mutable:
            return frozenset(mutable)
        mutable.update(newly_mutable)


def _repair_local_candidate_ids(
    candidates: tuple[_Candidate, ...],
    mutable_baseline_ids: frozenset[int],
    required_supporter_ids: set[int],
    anchored_supporter_ids: set[int],
    frozen_cells: set[GridPosition],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    frozen_males: set[tuple[float, float, float]],
    base_z: int,
) -> tuple[int, ...]:
    repair_cells = {
        cell for candidate_id in mutable_baseline_ids for cell in candidates[candidate_id].cells
    }
    local_ids = {
        candidate_id
        for candidate_id, candidate in enumerate(candidates)
        if not (candidate.cells & frozen_cells)
        and (
            candidate_id in required_supporter_ids
            or candidate_id in anchored_supporter_ids
            or candidate.cells.issubset(repair_cells)
        )
    }
    producer_ids_by_coordinate: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for candidate_id, males in enumerate(candidate_males):
        if candidates[candidate_id].cells & frozen_cells:
            continue
        for coordinate in males:
            producer_ids_by_coordinate[coordinate].append(candidate_id)

    # A newly introduced supporter may itself sit above the base.  Add only its
    # direct supporters, recursively, instead of widening the repair across a
    # whole vertical column or returning to the global candidate set.
    pending = list(sorted(local_ids))
    while pending:
        candidate_id = pending.pop()
        if candidates[candidate_id].placement.position.z == base_z:
            continue
        receivers = candidate_receivers[candidate_id]
        if receivers & frozen_males:
            continue
        supporter_ids = {
            supporter_id
            for coordinate in receivers
            for supporter_id in producer_ids_by_coordinate.get(coordinate, ())
        }
        if not supporter_ids:
            continue
        smallest_supporter_size = min(
            len(candidates[supporter_id].cells) for supporter_id in supporter_ids
        )
        for supporter_id in sorted(supporter_ids):
            if len(candidates[supporter_id].cells) != smallest_supporter_size:
                continue
            if supporter_id not in local_ids:
                local_ids.add(supporter_id)
                pending.append(supporter_id)
    return tuple(sorted(local_ids))


def _repair_boundary_support_contacts(
    candidates: tuple[_Candidate, ...],
    mutable_baseline_ids: frozenset[int],
    required_supporter_ids: set[int],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    frozen_males: set[tuple[float, float, float]],
) -> frozenset[tuple[float, float, float]]:
    """Return frozen direct-support contacts the local component can retain."""
    component_ids = mutable_baseline_ids | required_supporter_ids
    return frozenset(
        coordinate
        for candidate_id in component_ids
        for coordinate in candidate_receivers[candidate_id]
        if coordinate in frozen_males
    )


def _repair_part_count_bound(
    mutable_baseline_count: int,
    unsupported_consumer_count: int,
    boundary_support_contact_count: int,
) -> int:
    """Limit a local repair relative to the structure it is permitted to change.

    Retaining every mutable baseline placement is always permitted.  Each
    unsupported fixed consumer receives room for a direct supporter plus one
    connecting placement, while each existing frozen boundary contact receives
    room for one local connection.  The bound is independent of targetParts.
    """
    return (
        mutable_baseline_count
        + REPAIR_ALLOWANCE_PER_UNSUPPORTED_CONSUMER * unsupported_consumer_count
        + boundary_support_contact_count
    )


def _solve_support_repair(
    candidates: tuple[_Candidate, ...],
    baseline_ids: frozenset[int],
    frozen_ids: frozenset[int],
    local_ids: tuple[int, ...],
    unsupported_locked: Collection[BrickPlacement],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    locked_males: set[tuple[float, float, float]],
    base_z: int,
    variable_pixels: tuple[ProjectionPixel, ...],
    cells_by_pixel: Mapping[ProjectionPixel, tuple[GridPosition, ...]],
    allowed_repair_count: int,
) -> _RepairSolveResult:
    """Solve the bounded replacement model with coverage before packing changes."""
    frozen_males = locked_males | set().union(
        *(candidate_males[candidate_id] for candidate_id in frozen_ids)
    )
    frozen_cells = {
        cell for candidate_id in frozen_ids for cell in candidates[candidate_id].cells
    }
    baseline_coverage = _coverage_score(baseline_ids, candidates, variable_pixels)
    model = cp_model.CpModel()
    selected = {
        candidate_id: model.new_bool_var(f"repair_{candidate_id}")
        for candidate_id in local_ids
    }
    model.add(sum(selected.values()) <= allowed_repair_count)
    _add_repair_non_overlap_constraints(model, selected, candidates)
    _add_repair_support_constraints(
        model,
        selected,
        candidates,
        candidate_males,
        candidate_receivers,
        frozen_males,
        base_z,
    )
    _add_locked_support_repair_constraints(
        model,
        selected,
        unsupported_locked,
        candidate_males,
        frozen_males,
    )
    coverage = _repair_coverage_variables(
        model,
        selected,
        candidates,
        frozen_cells,
        variable_pixels,
        cells_by_pixel,
    )
    model.add(sum(coverage) >= baseline_coverage)
    model.maximize(sum(coverage))
    solver, stage_one = _solve(model, LOCAL_REPAIR_MAX_DETERMINISTIC_TIME)
    if not _has_usable_incumbent(stage_one):
        raise V4SolveFailure(LOCAL_REPAIR_BOUND_FAILURE)

    achieved_coverage = stage_one.objective_value
    assert achieved_coverage is not None
    model.add(sum(coverage) == achieved_coverage)
    changes = sum(
        1 - selected[candidate_id] if candidate_id in baseline_ids else selected[candidate_id]
        for candidate_id in local_ids
    )
    model.minimize(changes)
    _add_repair_hint(model, selected, solver)
    changed_solver, changed_stage = _solve(model, LOCAL_REPAIR_MAX_DETERMINISTIC_TIME)
    selected_solver = solver
    solver_stages = [stage_one]
    if _has_usable_incumbent(changed_stage):
        changed_placement_count = changed_stage.objective_value
        assert changed_placement_count is not None
        model.add(changes == changed_placement_count)
        model.minimize(sum(selected.values()))
        _add_repair_hint(model, selected, changed_solver)
        parts_solver, parts_stage = _solve(model, LOCAL_REPAIR_MAX_DETERMINISTIC_TIME)
        solver_stages.append(changed_stage)
        solver_stages.append(parts_stage)
        selected_solver = parts_solver if _has_usable_incumbent(parts_stage) else changed_solver
    else:
        solver_stages.append(changed_stage)
    repaired_local_ids = {
        candidate_id
        for candidate_id, variable in selected.items()
        if selected_solver.boolean_value(variable)
    }
    repaired_ids = tuple(sorted(frozen_ids | repaired_local_ids))
    if _coverage_score(repaired_ids, candidates, variable_pixels) < baseline_coverage:
        raise V4SolveFailure("surface-grid-v4 support repair degraded baseline coverage.")
    if len(repaired_local_ids) > allowed_repair_count:
        raise V4SolveFailure("surface-grid-v4 support repair exceeded its local part bound.")
    return _RepairSolveResult(
        repaired_ids=repaired_ids,
        selected_local_ids=frozenset(repaired_local_ids),
        solver_stages=tuple(solver_stages),
    )


def _add_repair_non_overlap_constraints(
    model: cp_model.CpModel,
    selected: Mapping[int, cp_model.IntVar],
    candidates: tuple[_Candidate, ...],
) -> None:
    candidate_ids_by_cell: dict[GridPosition, list[int]] = defaultdict(list)
    for candidate_id in selected:
        for cell in candidates[candidate_id].cells:
            candidate_ids_by_cell[cell].append(candidate_id)
    for candidate_ids in candidate_ids_by_cell.values():
        model.add(sum(selected[candidate_id] for candidate_id in candidate_ids) <= 1)


def _add_repair_support_constraints(
    model: cp_model.CpModel,
    selected: Mapping[int, cp_model.IntVar],
    candidates: tuple[_Candidate, ...],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    candidate_receivers: tuple[frozenset[tuple[float, float, float]], ...],
    frozen_males: set[tuple[float, float, float]],
    base_z: int,
) -> None:
    producers: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for candidate_id in selected:
        for coordinate in candidate_males[candidate_id]:
            producers[coordinate].append(candidate_id)
    for candidate_id, variable in selected.items():
        if candidates[candidate_id].placement.position.z == base_z:
            continue
        receivers = candidate_receivers[candidate_id]
        if receivers & frozen_males:
            continue
        supporter_ids = sorted(
            {
                supporter_id
                for coordinate in receivers
                for supporter_id in producers.get(coordinate, ())
            }
        )
        if supporter_ids:
            model.add(variable <= sum(selected[supporter_id] for supporter_id in supporter_ids))
        else:
            model.add(variable == 0)


def _add_locked_support_repair_constraints(
    model: cp_model.CpModel,
    selected: Mapping[int, cp_model.IntVar],
    unsupported_locked: Collection[BrickPlacement],
    candidate_males: tuple[frozenset[tuple[float, float, float]], ...],
    frozen_males: set[tuple[float, float, float]],
) -> None:
    producers: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for candidate_id in selected:
        for coordinate in candidate_males[candidate_id]:
            producers[coordinate].append(candidate_id)
    for placement in unsupported_locked:
        receivers = _receiver_connector_coordinates(placement)
        if receivers & frozen_males:
            continue
        supporter_ids = sorted(
            {
                candidate_id
                for coordinate in receivers
                for candidate_id in producers.get(coordinate, ())
            }
        )
        if not supporter_ids:
            raise V4SolveFailure(LOCKED_SUPPORT_FAILURE)
        model.add(sum(selected[candidate_id] for candidate_id in supporter_ids) >= 1)


def _repair_coverage_variables(
    model: cp_model.CpModel,
    selected: Mapping[int, cp_model.IntVar],
    candidates: tuple[_Candidate, ...],
    frozen_cells: set[GridPosition],
    variable_pixels: tuple[ProjectionPixel, ...],
    cells_by_pixel: Mapping[ProjectionPixel, tuple[GridPosition, ...]],
) -> tuple[cp_model.IntVar | int, ...]:
    coverage: list[cp_model.IntVar | int] = []
    for pixel in variable_pixels:
        ray_cells = frozenset(cells_by_pixel.get(pixel, ()))
        if ray_cells & frozen_cells:
            coverage.append(1)
            continue
        sources = [
            selected[candidate_id]
            for candidate_id in selected
            if candidates[candidate_id].cells & ray_cells
        ]
        if not sources:
            coverage.append(0)
            continue
        variable = model.new_bool_var(f"repair_coverage_{pixel[0]}_{pixel[1]}_{pixel[2]}")
        model.add_max_equality(variable, sources)
        coverage.append(variable)
    return tuple(coverage)


def _add_repair_hint(
    model: cp_model.CpModel,
    selected: Mapping[int, cp_model.IntVar],
    solver: cp_model.CpSolver,
) -> None:
    model.clear_hints()  # type: ignore[no-untyped-call]  # OR-Tools lacks a typed stub.
    for variable in selected.values():
        model.add_hint(variable, solver.boolean_value(variable))


def _male_connector_coordinates(
    placements: Collection[BrickPlacement],
) -> set[tuple[float, float, float]]:
    return {
        connector.coordinate
        for placement in placements
        for connector in _world_connectors(placement)
        if connector.interface_kind == MechanicalInterfaceKind.MALE_STUD
    }


def _receiver_connector_coordinates(
    placement: BrickPlacement,
) -> set[tuple[float, float, float]]:
    return {
        connector.coordinate
        for connector in _world_connectors(placement)
        if connector.interface_kind == MechanicalInterfaceKind.STUD_RECEIVER
    }


def _world_connectors(
    placement: BrickPlacement,
) -> tuple[WorldMechanicalConnector, ...]:
    metadata = resolve_part_mechanical_metadata(placement.brick_type)
    if metadata is None:
        return ()
    return tuple(
        transform_connector_to_world(
            connector,
            placement.brick_type,
            placement.position,
            placement.orientation_degrees,
        )
        for connector in metadata.connectors
    )


def _model_base_z(
    target: Collection[GridPosition], locked_placements: Collection[BrickPlacement]
) -> int:
    z_levels = tuple(cell.z for cell in target) + tuple(
        placement.position.z for placement in locked_placements
    )
    return min(z_levels)


def _validate_fixed_placements(locked_placements: Collection[BrickPlacement]) -> None:
    if analyze_buildability(locked_placements).unsupported_placement_count:
        raise V4SolveFailure(LOCKED_SUPPORT_FAILURE)


def _candidate_ids_by_cell(
    target: frozenset[GridPosition], candidates: tuple[_Candidate, ...]
) -> dict[GridPosition, tuple[int, ...]]:
    by_cell: dict[GridPosition, list[int]] = {cell: [] for cell in sorted(target, key=_cell_order)}
    for candidate_id, candidate in enumerate(candidates):
        for cell in candidate.cells:
            by_cell[cell].append(candidate_id)
    return {cell: tuple(ids) for cell, ids in by_cell.items()}


def _cells_by_pixel(
    target: frozenset[GridPosition],
) -> dict[ProjectionPixel, tuple[GridPosition, ...]]:
    by_pixel: dict[ProjectionPixel, list[GridPosition]] = defaultdict(list)
    for cell in sorted(target, key=_cell_order):
        by_pixel[("front", cell.x, cell.z)].append(cell)
        by_pixel[("side", cell.y, cell.z)].append(cell)
        by_pixel[("top", cell.x, cell.y)].append(cell)
    return {pixel: tuple(cells) for pixel, cells in by_pixel.items()}


def _solve(
    model: cp_model.CpModel, deterministic_time_limit: float
) -> tuple[cp_model.CpSolver, SolverStage]:
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = deterministic_time_limit
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    started = perf_counter()
    status = solver.solve(model)
    runtime_seconds = perf_counter() - started
    feasible = status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
    return solver, SolverStage(
        status=solver.status_name(status),
        objective_value=int(round(solver.objective_value)) if feasible else None,
        runtime_seconds=runtime_seconds,
        is_optimal=status == cp_model.OPTIMAL,
        best_objective_bound=int(round(solver.best_objective_bound)) if feasible else None,
    )


def _has_usable_incumbent(stage: SolverStage) -> bool:
    return stage.status in {"OPTIMAL", "FEASIBLE"} and stage.objective_value is not None


def _add_hint(model: _Model, selected_ids: Collection[int]) -> None:
    selected_id_set = frozenset(selected_ids)
    for candidate_id, variable in enumerate(model.selected):
        model.model.add_hint(variable, int(candidate_id in selected_id_set))


def _selected_ids(
    solver: cp_model.CpSolver, selected: tuple[cp_model.IntVar, ...]
) -> tuple[int, ...]:
    return tuple(index for index, variable in enumerate(selected) if solver.boolean_value(variable))


def _coverage_score(
    selected_ids: Collection[int],
    candidates: tuple[_Candidate, ...],
    pixels: Collection[ProjectionPixel],
) -> int:
    selected_cells = {cell for index in selected_ids for cell in candidates[index].cells}
    return sum(
        any(cell in selected_cells for cell in _ray_cells(pixel, selected_cells))
        for pixel in pixels
    )


def _ray_cells(pixel: ProjectionPixel, cells: Collection[GridPosition]) -> tuple[GridPosition, ...]:
    view, first, second = pixel
    if view == "front":
        return tuple(cell for cell in cells if cell.x == first and cell.z == second)
    if view == "side":
        return tuple(cell for cell in cells if cell.y == first and cell.z == second)
    return tuple(cell for cell in cells if cell.x == first and cell.y == second)


def _validate_placements(
    placements: tuple[BrickPlacement, ...],
    target: frozenset[GridPosition],
    locked_placements: Collection[BrickPlacement],
) -> None:
    occupied: set[GridPosition] = set()
    base_z = min(cell.z for cell in target)
    for placement in placements:
        cells = _placement_cells(placement)
        if not cells.issubset(target):
            raise V4SolveFailure("A selected rectangular placement extends outside A.")
        if occupied & cells:
            raise V4SolveFailure("Selected rectangular placements overlap.")
        occupied.update(cells)
    possible_supporters = (*locked_placements, *placements)
    for placement in placements:
        if placement.position.z == base_z:
            continue
        if not any(
            lower != placement and directly_supports(lower, placement)
            for lower in possible_supporters
        ):
            raise V4SolveFailure("A selected rectangular placement has no direct support.")
    if analyze_buildability((*locked_placements, *placements)).unsupported_placement_count:
        raise V4SolveFailure("stud-connectivity-v1 found an unsupported evaluated placement.")


def _placement_cells(placement: BrickPlacement) -> frozenset[GridPosition]:
    length = placement.brick_type.length_studs
    width = placement.brick_type.width_studs
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    return frozenset(
        GridPosition(placement.position.x + x, placement.position.y + y, placement.position.z + z)
        for z in range(placement.brick_type.height_plates)
        for y in range(width)
        for x in range(length)
    )


def _stud_footprint(placement: BrickPlacement) -> frozenset[tuple[int, int]]:
    length = placement.brick_type.length_studs
    width = placement.brick_type.width_studs
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    return frozenset(
        (placement.position.x + x, placement.position.y + y)
        for y in range(width)
        for x in range(length)
    )


def _pixels_for_cells(cells: Collection[GridPosition]) -> frozenset[ProjectionPixel]:
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )


def _pixel_order(pixel: ProjectionPixel) -> tuple[int, int, int]:
    view, first, second = pixel
    return (("front", "side", "top").index(view), second, first)


def _cell_order(cell: GridPosition) -> tuple[int, int, int]:
    return (cell.z, cell.y, cell.x)
