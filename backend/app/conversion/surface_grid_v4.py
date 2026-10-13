"""Bounded CP-SAT packing for the opt-in surface-grid-v4 converter."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from time import perf_counter

from ortools.sat.python import cp_model

from app.conversion.buildability import analyze_buildability
from app.conversion.core import BrickPlacement, BrickType, ConversionError, GridPosition, GridSize

STAGE_ONE_MAX_SECONDS = 60.0
STAGE_TWO_MAX_SECONDS = 20.0
SOLVER_RANDOM_SEED = 0
SOLVER_WORKERS = 1

ProjectionPixel = tuple[str, int, int]
SupportContact = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SolverStage:
    status: str
    objective_value: int | None
    runtime_seconds: float
    is_optimal: bool


@dataclass(frozen=True, slots=True)
class V4PackingResult:
    placements: tuple[BrickPlacement, ...]
    stage_one: SolverStage
    stage_two: SolverStage
    achieved_coverage: int
    candidate_count: int


class V4SolveFailure(ConversionError):
    """Stage one ended without a structurally valid CP-SAT incumbent."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    placement: BrickPlacement
    cells: frozenset[GridPosition]


@dataclass(frozen=True, slots=True)
class _Model:
    model: cp_model.CpModel
    selected: tuple[cp_model.IntVar, ...]
    coverage: tuple[cp_model.IntVar, ...]


def solve_surface_grid_v4(
    target_cells: Collection[GridPosition],
    required_pixels: Collection[ProjectionPixel],
    locked_slope_cells: Collection[GridPosition],
    catalogue: tuple[BrickType, ...],
) -> V4PackingResult:
    """Select non-overlapping, direct-support-connected rectangles inside A.

    ``target_cells`` is a candidate witness volume. It is deliberately not a
    volume that must be filled. Locked slope cells contribute fixed projection
    coverage but cannot be occupied by new rectangular placements.
    """
    target = frozenset(target_cells)
    if not target:
        raise V4SolveFailure("surface-grid-v4 has no rectangular candidate volume.")

    candidates = _support_reachable_candidates(_enumerate_candidates(target, catalogue), target)
    required = frozenset(required_pixels)
    fixed_pixels = _pixels_for_cells(locked_slope_cells)
    variable_pixels = tuple(sorted(required - fixed_pixels, key=_pixel_order))
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
    stage_one_solver, stage_one = _solve(stage_one_model.model, STAGE_ONE_MAX_SECONDS)
    if stage_one.objective_value is None:
        raise V4SolveFailure("surface-grid-v4 stage one did not find a feasible solution.")

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
    stage_two_solver, stage_two = _solve(stage_two_model.model, STAGE_TWO_MAX_SECONDS)

    selected_ids = stage_one_ids
    if stage_two.objective_value is not None:
        selected_ids = _selected_ids(stage_two_solver, stage_two_model.selected)
        if _coverage_score(selected_ids, candidates, variable_pixels) != achieved_coverage:
            raise V4SolveFailure("Stage two changed the stage-one projection coverage.")

    placements = tuple(candidates[candidate_id].placement for candidate_id in selected_ids)
    _validate_placements(placements, target)
    return V4PackingResult(
        placements=placements,
        stage_one=stage_one,
        stage_two=stage_two,
        achieved_coverage=achieved_coverage + len(required & fixed_pixels),
        candidate_count=len(candidates),
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
            if brick_type.shape != "rectangular":
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
    model: cp_model.CpModel, time_limit_seconds: float
) -> tuple[cp_model.CpSolver, SolverStage]:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
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
    )


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
    placements: tuple[BrickPlacement, ...], target: frozenset[GridPosition]
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
    for placement in placements:
        if placement.position.z == base_z:
            continue
        footprint = _stud_footprint(placement)
        if not any(
            lower.position.z + lower.brick_type.height_plates == placement.position.z
            and footprint & _stud_footprint(lower)
            for lower in placements
        ):
            raise V4SolveFailure("A selected rectangular placement has no direct support.")
    if analyze_buildability(placements).unsupported_placement_count:
        raise V4SolveFailure("stud-connectivity-v1 found an unsupported rectangular placement.")


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
