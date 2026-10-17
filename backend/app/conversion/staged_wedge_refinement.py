"""Bounded, opt-in local refinement with the 41769/41770 wedge plates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from time import perf_counter

from ortools.sat.python import cp_model
from PIL import Image, ImageDraw

from app.conversion.buildability import (
    analyze_buildability,
    directly_supports,
    is_evaluated_rectangular,
)
from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.wedge_41769_41770 import (
    WEDGE_PART_IDS,
    WEDGE_PROJECTION_SUBDIVISIONS,
    footprint_microcells,
    oriented_dimensions,
    transformed_footprint,
)

MAX_REFINEMENT_REGIONS = 3
LOCAL_MAX_DETERMINISTIC_TIME = 2.0
SOLVER_RANDOM_SEED = 0


@dataclass(frozen=True, slots=True)
class LocalSolve:
    region: tuple[int, int, int, int]
    residual_score: int
    candidate_count: int
    status: str
    runtime_seconds: float
    placements: tuple[BrickPlacement, ...]
    disagreement: int | None
    part_count: int | None
    support: LocalSupportDiagnostics
    accepted: bool


@dataclass(frozen=True, slots=True)
class RefinementResult:
    placements: tuple[BrickPlacement, ...]
    residual_region_count: int
    attempted: tuple[LocalSolve, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    placement: BrickPlacement
    microcells: frozenset[tuple[int, int, int]]


@dataclass(frozen=True, slots=True)
class LocalSupportDiagnostics:
    """Counts for the local constraints mirroring stud-connectivity-v1."""

    base_z: int
    mutable_evaluated_candidate_count: int
    requiring_support_count: int
    fixed_outside_support_count: int
    requiring_selectable_local_support_count: int
    frozen_dependent_count: int
    support_relation_count: int
    selected_evaluated_placement_count: int = 0
    selected_requiring_support_count: int = 0
    constraints_satisfied: bool = False
    independent_unsupported_placement_count: int | None = None
    model_variable_count: int = 0
    model_constraint_count: int = 0


@dataclass(frozen=True, slots=True)
class _PossibleSupporters:
    base_z: int
    candidate_local_supporters: tuple[tuple[int, tuple[int, ...]], ...]
    candidate_fixed_support: frozenset[int]
    frozen_local_supporters: tuple[tuple[int, tuple[int, ...]], ...]
    frozen_fixed_support: frozenset[int]


def source_top_microcells(
    vertices: Collection[tuple[float, float, float]],
    faces: Collection[tuple[int, int, int]],
    width_studs: int,
    depth_studs: int,
) -> frozenset[tuple[int, int]]:
    image = Image.new(
        "1",
        (width_studs * WEDGE_PROJECTION_SUBDIVISIONS, depth_studs * WEDGE_PROJECTION_SUBDIVISIONS),
    )
    draw = ImageDraw.Draw(image)
    points = tuple(vertices)
    for face in faces:
        draw.polygon(
            [
                (
                    round(points[index][0] * WEDGE_PROJECTION_SUBDIVISIONS),
                    round(points[index][1] * WEDGE_PROJECTION_SUBDIVISIONS),
                )
                for index in face
            ],
            fill=1,
        )
    return frozenset(
        (x, y) for y in range(image.height) for x in range(image.width) if image.getpixel((x, y))
    )


def refine_wedges(
    placements: Collection[BrickPlacement],
    target_cells: Collection[GridPosition],
    top_target_microcells: Collection[tuple[int, int]],
    accept: Callable[[tuple[BrickPlacement, ...]], bool],
    *,
    max_regions: int = MAX_REFINEMENT_REGIONS,
) -> RefinementResult:
    """Solve small non-overlapping local alternatives, retaining all other pieces.

    This deliberately returns unaccepted local attempts.  The caller owns final
    trusted silhouette scoring and the monotonic accept/reject decision.
    """
    incumbent = tuple(placements)
    target = frozenset(target_cells)
    target_microcells = frozenset(top_target_microcells)
    regions = _select_regions(_residual_components(target_microcells, incumbent), max_regions)
    attempts: list[LocalSolve] = []
    for region, score in regions:
        local_indices = tuple(
            index
            for index, placement in enumerate(incumbent)
            if _intersects_region(placement, region)
        )
        if not local_indices:
            continue
        frozen = tuple(
            placement for index, placement in enumerate(incumbent) if index not in local_indices
        )
        candidates = _local_candidates(
            tuple(incumbent[index] for index in local_indices),
            frozen,
            target,
            target_microcells,
            region,
        )
        attempt = _solve_local(
            region,
            score,
            candidates,
            frozen,
            _target_projection_pixels(target, target_microcells),
        )
        if attempt.status not in {"OPTIMAL", "FEASIBLE"}:
            attempts.append(attempt)
            continue
        proposal = frozen + attempt.placements
        accepted = accept(proposal)
        attempt = LocalSolve(
            attempt.region,
            attempt.residual_score,
            attempt.candidate_count,
            attempt.status,
            attempt.runtime_seconds,
            attempt.placements,
            attempt.disagreement,
            attempt.part_count,
            attempt.support,
            accepted,
        )
        attempts.append(attempt)
        if accepted:
            incumbent = proposal
    return RefinementResult(
        incumbent, len(_residual_components(target_microcells, placements)), tuple(attempts)
    )


def _residual_components(
    target: frozenset[tuple[int, int]], placements: Collection[BrickPlacement]
) -> tuple[frozenset[tuple[int, int]], ...]:
    output = {
        (micro_x, micro_y)
        for placement in placements
        for micro_x, micro_y, _ in _placement_microcells(placement)
    }
    remaining = set(target ^ output)
    components: list[frozenset[tuple[int, int]]] = []
    while remaining:
        start = min(remaining, key=lambda point: (point[1], point[0]))
        pending = [start]
        component: set[tuple[int, int]] = set()
        remaining.remove(start)
        while pending:
            point = pending.pop()
            component.add(point)
            for neighbor in _neighbors(point):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        components.append(frozenset(component))
    return tuple(components)


def _select_regions(
    components: tuple[frozenset[tuple[int, int]], ...],
    max_regions: int = MAX_REFINEMENT_REGIONS,
) -> tuple[tuple[tuple[int, int, int, int], int], ...]:
    ranked: list[tuple[int, tuple[int, int, int, int]]] = []
    for component in components:
        if len(component) < WEDGE_PROJECTION_SUBDIVISIONS:
            continue
        bounds = _stud_bounds(component)
        score = len(component) * _diagonal_span(component)
        if score:
            ranked.append((score, bounds))
    selected: list[tuple[tuple[int, int, int, int], int]] = []
    for score, bounds in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if any(_bounds_overlap(bounds, existing) for existing, _ in selected):
            continue
        selected.append((bounds, score))
        if len(selected) == max_regions:
            break
    return tuple(selected)


def _local_candidates(
    local: tuple[BrickPlacement, ...],
    frozen: tuple[BrickPlacement, ...],
    target: frozenset[GridPosition],
    target_microcells: frozenset[tuple[int, int]],
    region: tuple[int, int, int, int],
) -> tuple[_Candidate, ...]:
    frozen_microcells = {
        microcell for placement in frozen for microcell in _placement_microcells(placement)
    }
    candidates = [_Candidate(placement, _placement_microcells(placement)) for placement in local]
    min_x, max_x, min_y, max_y = region
    z_levels = sorted({placement.position.z for placement in local})
    for z in z_levels:
        for part_id in sorted(WEDGE_PART_IDS):
            for orientation in (0, 90, 180, 270):
                length, width = oriented_dimensions(orientation)
                for y in range(min_y - width + 1, max_y + 1):
                    for x in range(min_x - length + 1, max_x + 1):
                        cells = frozenset(
                            GridPosition(x + offset_x, y + offset_y, z)
                            for offset_y in range(width)
                            for offset_x in range(length)
                        )
                        if not cells.issubset(target):
                            continue
                        placement = BrickPlacement(
                            PART_BY_ID[part_id], GridPosition(x, y, z), orientation
                        )
                        microcells = _placement_microcells(placement)
                        if not _is_plausible_diagonal_candidate(
                            frozenset((micro_x, micro_y) for micro_x, micro_y, _ in microcells),
                            target_microcells,
                        ):
                            continue
                        if microcells & frozen_microcells:
                            continue
                        candidates.append(_Candidate(placement, microcells))
    return tuple(candidates)


def _solve_local(
    region: tuple[int, int, int, int],
    score: int,
    candidates: tuple[_Candidate, ...],
    frozen: tuple[BrickPlacement, ...],
    target_pixels: dict[str, frozenset[tuple[int, int]]],
) -> LocalSolve:
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"local_{index}") for index in range(len(candidates)))
    by_microcell: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        for microcell in candidate.microcells:
            by_microcell[microcell].append(index)
    for indexes in by_microcell.values():
        model.add(sum(selected[index] for index in indexes) <= 1)

    support = _add_local_support_constraints(model, selected, candidates, frozen)

    frozen_pixels = _projection_pixels_for_placements(frozen)
    candidate_pixels = tuple(_projection_pixels(candidate.microcells) for candidate in candidates)
    disagreement_terms: list[cp_model.LinearExpr] = []
    for view in ("front", "side", "top"):
        affected = set().union(*(pixels[view] for pixels in candidate_pixels))
        for pixel in affected:
            if pixel in frozen_pixels[view]:
                continue
            producers = [
                selected[index]
                for index, pixels in enumerate(candidate_pixels)
                if pixel in pixels[view]
            ]
            output = model.new_bool_var(f"{view}_{pixel[0]}_{pixel[1]}")
            model.add_max_equality(output, producers)
            disagreement_terms.append(1 - output if pixel in target_pixels[view] else output)
    disagreement = sum(disagreement_terms)
    model.minimize(disagreement)
    support = replace(
        support,
        model_variable_count=len(model.proto.variables),
        model_constraint_count=len(model.proto.constraints),
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = LOCAL_MAX_DETERMINISTIC_TIME
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    started = perf_counter()
    status = solver.solve(model)
    runtime = perf_counter() - started
    status_name = solver.status_name(status)
    chosen: tuple[BrickPlacement, ...] = ()
    best_disagreement: int | None = None
    part_count: int | None = None
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        best_disagreement = int(solver.objective_value)
        model.add(disagreement == best_disagreement)
        model.minimize(sum(selected))
        second_started = perf_counter()
        status = solver.solve(model)
        runtime += perf_counter() - second_started
        status_name = solver.status_name(status)
        chosen = tuple(
            candidate.placement
            for candidate, variable in zip(candidates, selected, strict=True)
            if solver.boolean_value(variable)
        )
        part_count = len(chosen)
        chosen_indexes = frozenset(
            index for index, variable in enumerate(selected) if solver.boolean_value(variable)
        )
        support = replace(
            support,
            selected_evaluated_placement_count=sum(
                is_evaluated_rectangular(candidates[index].placement) for index in chosen_indexes
            ),
            selected_requiring_support_count=sum(
                is_evaluated_rectangular(candidates[index].placement)
                and candidates[index].placement.position.z != support.base_z
                for index in chosen_indexes
            ),
            constraints_satisfied=_support_constraints_satisfied(
                chosen_indexes, candidates, frozen
            ),
            independent_unsupported_placement_count=analyze_buildability(
                frozen + chosen
            ).unsupported_placement_count,
        )
    return LocalSolve(
        region,
        score,
        len(candidates),
        status_name,
        runtime,
        chosen,
        best_disagreement,
        part_count,
        support,
        False,
    )


def _target_projection_pixels(
    target: frozenset[GridPosition], target_top: frozenset[tuple[int, int]]
) -> dict[str, frozenset[tuple[int, int]]]:
    """Project the local voxel target at the same deterministic grid resolution.

    This is deliberately family-neutral: any future locally fitted part is scored
    by its visible front, side, and top coverage rather than a part-specific bonus.
    """
    return {
        "front": frozenset(
            ((cell.x * WEDGE_PROJECTION_SUBDIVISIONS) + offset, cell.z)
            for cell in target
            for offset in range(WEDGE_PROJECTION_SUBDIVISIONS)
        ),
        "side": frozenset(
            ((cell.y * WEDGE_PROJECTION_SUBDIVISIONS) + offset, cell.z)
            for cell in target
            for offset in range(WEDGE_PROJECTION_SUBDIVISIONS)
        ),
        "top": target_top,
    }


def _projection_pixels_for_placements(
    placements: Collection[BrickPlacement],
) -> dict[str, frozenset[tuple[int, int]]]:
    by_view: dict[str, set[tuple[int, int]]] = {"front": set(), "side": set(), "top": set()}
    for placement in placements:
        pixels = _projection_pixels(_placement_microcells(placement))
        for view, view_pixels in pixels.items():
            by_view[view].update(view_pixels)
    return {view: frozenset(pixels) for view, pixels in by_view.items()}


def _projection_pixels(
    microcells: Collection[tuple[int, int, int]],
) -> dict[str, frozenset[tuple[int, int]]]:
    return {
        "front": frozenset((x, z) for x, _, z in microcells),
        "side": frozenset((y, z) for _, y, z in microcells),
        "top": frozenset((x, y) for x, y, _ in microcells),
    }


def _add_local_support_constraints(
    model: cp_model.CpModel,
    selected: tuple[cp_model.IntVar, ...],
    candidates: tuple[_Candidate, ...],
    frozen: Collection[BrickPlacement],
) -> LocalSupportDiagnostics:
    """Encode stud-connectivity-v1 support for local and frozen rectangles."""
    supporters = _possible_supporters(candidates, frozen)
    candidate_supporters = dict(supporters.candidate_local_supporters)
    frozen_supporters = dict(supporters.frozen_local_supporters)
    relation_count = 0

    for index, local_supporter_indexes in candidate_supporters.items():
        if candidates[index].placement.position.z == supporters.base_z:
            continue
        if index in supporters.candidate_fixed_support:
            continue
        relation_count += len(local_supporter_indexes)
        if local_supporter_indexes:
            model.add(selected[index] <= sum(selected[lower] for lower in local_supporter_indexes))
        else:
            model.add(selected[index] == 0)

    frozen_placements = tuple(frozen)
    frozen_dependent_count = 0
    for frozen_index, local_supporter_indexes in frozen_supporters.items():
        placement = frozen_placements[frozen_index]
        if placement.position.z == supporters.base_z or not local_supporter_indexes:
            continue
        frozen_dependent_count += 1
        if frozen_index in supporters.frozen_fixed_support:
            continue
        relation_count += len(local_supporter_indexes)
        model.add(sum(selected[lower] for lower in local_supporter_indexes) >= 1)

    requiring_support = tuple(
        index
        for index, _ in candidate_supporters.items()
        if candidates[index].placement.position.z != supporters.base_z
    )
    return LocalSupportDiagnostics(
        base_z=supporters.base_z,
        mutable_evaluated_candidate_count=len(candidate_supporters),
        requiring_support_count=len(requiring_support),
        fixed_outside_support_count=sum(
            index in supporters.candidate_fixed_support for index in requiring_support
        ),
        requiring_selectable_local_support_count=sum(
            index not in supporters.candidate_fixed_support for index in requiring_support
        ),
        frozen_dependent_count=frozen_dependent_count,
        support_relation_count=relation_count,
    )


def _possible_supporters(
    candidates: tuple[_Candidate, ...],
    frozen: Collection[BrickPlacement],
) -> _PossibleSupporters:
    """Build deterministic local support relations using stud-connectivity-v1 geometry."""
    frozen_placements = tuple(frozen)
    all_placements = tuple(candidate.placement for candidate in candidates) + frozen_placements
    base_z = min((placement.position.z for placement in all_placements), default=0)
    local_evaluated = tuple(
        index
        for index, candidate in enumerate(candidates)
        if is_evaluated_rectangular(candidate.placement)
    )
    frozen_evaluated = tuple(
        index
        for index, placement in enumerate(frozen_placements)
        if is_evaluated_rectangular(placement)
    )
    candidate_local_supporters = tuple(
        (
            index,
            tuple(
                lower_index
                for lower_index in local_evaluated
                if directly_supports(candidates[lower_index].placement, candidate.placement)
            ),
        )
        for index, candidate in enumerate(candidates)
        if is_evaluated_rectangular(candidate.placement)
    )
    candidate_fixed_support = frozenset(
        index
        for index, candidate in enumerate(candidates)
        if is_evaluated_rectangular(candidate.placement)
        and any(
            directly_supports(frozen_placements[lower_index], candidate.placement)
            for lower_index in frozen_evaluated
        )
    )
    frozen_local_supporters = tuple(
        (
            index,
            tuple(
                lower_index
                for lower_index in local_evaluated
                if directly_supports(candidates[lower_index].placement, placement)
            ),
        )
        for index, placement in enumerate(frozen_placements)
        if is_evaluated_rectangular(placement)
    )
    frozen_fixed_support = frozenset(
        index
        for index, placement in enumerate(frozen_placements)
        if is_evaluated_rectangular(placement)
        and any(
            lower_index != index
            and directly_supports(frozen_placements[lower_index], placement)
            for lower_index in frozen_evaluated
        )
    )
    return _PossibleSupporters(
        base_z,
        candidate_local_supporters,
        candidate_fixed_support,
        frozen_local_supporters,
        frozen_fixed_support,
    )


def _support_constraints_satisfied(
    selected_indexes: Collection[int],
    candidates: tuple[_Candidate, ...],
    frozen: Collection[BrickPlacement],
) -> bool:
    """Check the selected solution against the same local relations used by CP-SAT."""
    selected_set = frozenset(selected_indexes)
    supporters = _possible_supporters(candidates, frozen)
    for index, local_supporter_indexes in supporters.candidate_local_supporters:
        if (
            index not in selected_set
            or candidates[index].placement.position.z == supporters.base_z
            or index in supporters.candidate_fixed_support
        ):
            continue
        if not selected_set.intersection(local_supporter_indexes):
            return False
    frozen_placements = tuple(frozen)
    for index, local_supporter_indexes in supporters.frozen_local_supporters:
        if (
            frozen_placements[index].position.z == supporters.base_z
            or index in supporters.frozen_fixed_support
        ):
            continue
        if not selected_set.intersection(local_supporter_indexes):
            return False
    return True


def _placement_microcells(placement: BrickPlacement) -> frozenset[tuple[int, int, int]]:
    if placement.brick_type.part_id in WEDGE_PART_IDS:
        footprint = footprint_microcells(
            transformed_footprint(
                placement.brick_type.part_id,
                placement.position.x,
                placement.position.y,
                placement.orientation_degrees,
            )
        )
        return frozenset((x, y, placement.position.z) for x, y in footprint)
    length = placement.brick_type.length_studs
    width = placement.brick_type.width_studs
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    return frozenset(
        (
            (placement.position.x + x) * WEDGE_PROJECTION_SUBDIVISIONS + offset_x,
            (placement.position.y + y) * WEDGE_PROJECTION_SUBDIVISIONS + offset_y,
            placement.position.z + z,
        )
        for z in range(placement.brick_type.height_plates)
        for y in range(width)
        for x in range(length)
        for offset_y in range(WEDGE_PROJECTION_SUBDIVISIONS)
        for offset_x in range(WEDGE_PROJECTION_SUBDIVISIONS)
    )


def _stud_bounds(component: Collection[tuple[int, int]]) -> tuple[int, int, int, int]:
    return (
        min(x for x, _ in component) // WEDGE_PROJECTION_SUBDIVISIONS,
        max(x for x, _ in component) // WEDGE_PROJECTION_SUBDIVISIONS,
        min(y for _, y in component) // WEDGE_PROJECTION_SUBDIVISIONS,
        max(y for _, y in component) // WEDGE_PROJECTION_SUBDIVISIONS,
    )


def _intersects_region(placement: BrickPlacement, region: tuple[int, int, int, int]) -> bool:
    min_x, max_x, min_y, max_y = region
    return any(
        min_x <= x // WEDGE_PROJECTION_SUBDIVISIONS <= max_x
        and min_y <= y // WEDGE_PROJECTION_SUBDIVISIONS <= max_y
        for x, y, _ in _placement_microcells(placement)
    )


def _neighbors(point: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    x, y = point
    return ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))


def _diagonal_span(component: Collection[tuple[int, int]]) -> int:
    return min(
        max(x for x, _ in component) - min(x for x, _ in component),
        max(y for _, y in component) - min(y for _, y in component),
    )


def _is_plausible_diagonal_candidate(
    wedge_microcells: frozenset[tuple[int, int]],
    target_microcells: frozenset[tuple[int, int]],
) -> bool:
    minimum_x = min(x for x, _ in wedge_microcells)
    maximum_x = max(x for x, _ in wedge_microcells)
    minimum_y = min(y for _, y in wedge_microcells)
    maximum_y = max(y for _, y in wedge_microcells)
    bounding_microcells = frozenset(
        (micro_x, micro_y)
        for micro_y in range(minimum_y, maximum_y + 1)
        for micro_x in range(minimum_x, maximum_x + 1)
    )
    target_in_box = target_microcells & bounding_microcells
    if not target_in_box or target_in_box == bounding_microcells:
        return False
    return len(wedge_microcells ^ target_in_box) < len(bounding_microcells ^ target_in_box)


def _bounds_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    return not (
        left[1] < right[0] or right[1] < left[0] or left[3] < right[2] or right[3] < left[2]
    )
