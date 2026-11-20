"""Offline-only M12C solver adapter for the verified 41769a wedge.

This deliberately does not extend the production catalogue or the V6 solver.
The latter models candidates as rectangular cells; this adapter keeps those
candidates unchanged and adds a separately validated, nonrectangular wedge
candidate type for a bounded experiment only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model
from PIL import Image, ImageDraw

from app.conversion import core
from app.conversion.buildability import directly_supports
from app.conversion.catalogue_silhouette_experiment import (
    MAX_CANDIDATES,
    MAX_DETERMINISTIC_TIME,
    MAX_VARIABLE_RASTER_PIXELS,
    Pixel,
    _pixel,
    _pixels_for_geometry,
)
from app.conversion.fidelity import SILHOUETTE_RESOLUTION
from app.conversion.m12a_wedge_mechanics import (
    EXPERIMENTAL_ORIENTATIONS,
    EXPERIMENTAL_PART_ID,
    is_supported,
    physical_collision,
    projection_polygon,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import (
    SOLVER_RANDOM_SEED,
    SOLVER_WORKERS,
    _Candidate,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _placement_cells,
    _support_reachable_candidates,
)


@dataclass(frozen=True, slots=True)
class WedgeCandidate:
    """One eligible wedge and its conservative mandatory-coverage witnesses."""

    placement: core.BrickPlacement
    coverage_cells: frozenset[core.GridPosition]


@dataclass(frozen=True, slots=True)
class WedgePreflight:
    control_candidate_count: int
    wedge_candidate_count: int
    rejected_wedge_candidates: tuple[tuple[str, int], ...]
    total_candidate_count: int
    status: str


@dataclass(frozen=True, slots=True)
class WedgeSolve:
    placements: tuple[core.BrickPlacement, ...]
    preflight: WedgePreflight
    status: str
    objective_value: int | None
    best_objective_bound: int | None
    optimality_gap: int | None
    runtime_seconds: float
    fallback_reason: str | None
    rejected_placements: tuple[core.BrickPlacement, ...] = ()
    rejected_validation: WedgeAssemblyReport | None = None


@dataclass(frozen=True, slots=True)
class FixedFrameViewScore:
    view: str
    true_positives: int
    false_positives: int


@dataclass(frozen=True, slots=True)
class FixedFrameScore:
    """M12C's solver-frame score, including its real wedge raster geometry."""

    score: int
    true_positives: int
    false_positives: int
    views: tuple[FixedFrameViewScore, ...]


def preflight_wedge_candidates(
    *,
    target_cells: Collection[core.GridPosition],
    protected_empty_cells: Collection[core.GridPosition] = (),
    locked_placements: Collection[core.BrickPlacement] = (),
) -> tuple[tuple[_Candidate, ...], tuple[WedgeCandidate, ...], WedgePreflight]:
    """Return preserved Control A candidates plus safely eligible wedges.

    Wedge coverage contains only whole grid cells inside its physical polygon.
    This is intentionally conservative: a partial triangular cell never proves
    a mandatory source witness.  Collisions and final scoring use the full
    analytic body, not this safe coverage approximation.
    """
    target = frozenset(target_cells)
    locked = tuple(locked_placements)
    control = _support_reachable_candidates(
        _exclude_locked_body_collisions(
            _enumerate_candidates(target, core.BRICK_CATALOGUE), locked
        ),
        target,
    )
    if not target:
        return control, (), WedgePreflight(len(control), 0, (), len(control), "NO_CANDIDATES")
    protected = frozenset(protected_empty_cells)
    bounds = _envelope(target)
    rejected: dict[str, int] = defaultdict(int)
    wedges: list[WedgeCandidate] = []
    wedge_part = PART_BY_ID[EXPERIMENTAL_PART_ID]
    for z in range(bounds[2], bounds[5]):
        for y in range(bounds[1], bounds[4]):
            for x in range(bounds[0], bounds[3]):
                for orientation in EXPERIMENTAL_ORIENTATIONS:
                    placement = core.BrickPlacement(
                        wedge_part, core.GridPosition(x, y, z), orientation
                    )
                    reason = _wedge_rejection_reason(placement, bounds, protected, locked)
                    if reason is not None:
                        rejected[reason] += 1
                        continue
                    wedges.append(WedgeCandidate(placement, _whole_body_cells(placement)))
    total = len(control) + len(wedges)
    status = "READY" if total <= MAX_CANDIDATES else "CANDIDATE_LIMIT_EXHAUSTED"
    return (
        control,
        tuple(wedges),
        WedgePreflight(len(control), len(wedges), tuple(sorted(rejected.items())), total, status),
    )


def optimise_with_wedge(
    *,
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    target_cells: Collection[core.GridPosition],
    required_pixels: Collection[Pixel],
    locked_placements: Collection[core.BrickPlacement],
    protected_empty_cells: Collection[core.GridPosition] = (),
    fixed_coverage_pixels: Collection[Pixel] = (),
    max_parts: int,
    include_wedges: bool = True,
    view_objective_weights: Mapping[str, tuple[int, int]] | None = None,
) -> WedgeSolve:
    """Run the same TP-minus-FP experiment with safely modelled 41769a.

    The fixed locked-slope repair is intentionally absent: modifying a solved
    arrangement would invalidate the claimed optimum.  A case needing repair
    is therefore reported as unsupported rather than silently altered.
    """
    target = frozenset(target_cells)
    locked = tuple(locked_placements)
    rectangles, wedges, preflight = preflight_wedge_candidates(
        target_cells=target, protected_empty_cells=protected_empty_cells, locked_placements=locked
    )
    if preflight.status != "READY":
        return _not_run(preflight, "candidate_limit_exhausted")
    candidates = tuple(rectangles) + (tuple(wedges) if include_wedges else ())
    if not candidates:
        return _not_run(preflight, "no_eligible_candidates")
    pixels, fixed_pixels, source_pixels = _raster_pixels(
        source_vertices, faces, candidates, locked, target
    )
    all_pixels = set(fixed_pixels).union(*(set(item) for item in pixels))
    if len(all_pixels) > MAX_VARIABLE_RASTER_PIXELS:
        return _not_run(preflight, "raster_pixel_limit_exhausted")
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(len(candidates)))
    model.add(sum(selected) <= max_parts - len(locked))
    _add_rectangular_nonoverlap(model, selected, rectangles, target)
    _add_wedge_collisions(model, selected, candidates)
    _add_verified_support(model, selected, candidates, locked, min(cell.z for cell in target))
    _add_locked_support(model, selected, candidates, locked, min(cell.z for cell in target))
    _add_mandatory_coverage(
        model,
        selected,
        candidates,
        tuple(sorted(set(required_pixels) - set(fixed_coverage_pixels))),
    )
    by_pixel: dict[Pixel, list[int]] = defaultdict(list)
    for candidate_id, candidate_pixels in enumerate(pixels):
        for pixel in candidate_pixels:
            by_pixel[pixel].append(candidate_id)
    if view_objective_weights is None:
        # This is M12C's historical objective. Keep it as the default so its
        # existing no-wedge control remains unchanged.
        groups: dict[tuple[tuple[int, ...], bool], int] = defaultdict(int)
        for pixel in all_pixels - fixed_pixels:
            groups[(tuple(by_pixel[pixel]), pixel in source_pixels)] += 1
        true_positive: cp_model.LinearExpr | int = len(source_pixels & fixed_pixels)
        false_positive: cp_model.LinearExpr | int = len(fixed_pixels - source_pixels)
        for group_id, ((candidate_ids, is_source), count) in enumerate(sorted(groups.items())):
            covered = model.new_bool_var(f"silhouette_group_{group_id}")
            model.add_max_equality(covered, [selected[index] for index in candidate_ids])
            if is_source:
                true_positive += count * covered
            else:
                false_positive += count * covered
        primary_score = true_positive - false_positive
    else:
        _validate_view_objective_weights(view_objective_weights)
        groups_by_view: dict[tuple[tuple[int, ...], bool, str], int] = defaultdict(int)
        for pixel in all_pixels - fixed_pixels:
            groups_by_view[(tuple(by_pixel[pixel]), pixel in source_pixels, pixel[0])] += 1
        primary_score = sum(
            view_objective_weights[pixel[0]][0 if pixel in source_pixels else 1]
            * (1 if pixel in source_pixels else -1)
            for pixel in fixed_pixels
        )
        for group_id, ((candidate_ids, is_source, view), count) in enumerate(
            sorted(groups_by_view.items())
        ):
            covered = model.new_bool_var(f"silhouette_group_{group_id}")
            model.add_max_equality(covered, [selected[index] for index in candidate_ids])
            true_positive_weight, false_positive_weight = view_objective_weights[view]
            pixel_weight = true_positive_weight if is_source else -false_positive_weight
            primary_score += count * pixel_weight * covered
    model.maximize(primary_score * (len(candidates) + 1) - sum(selected))
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = MAX_DETERMINISTIC_TIME
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    status = solver.status_name(solver.solve(model))
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return _not_run(
            preflight, "infeasible" if status == "INFEASIBLE" else "limit_exhausted", status
        )
    placements = (
        *locked,
        *(
            candidate.placement
            for index, candidate in enumerate(candidates)
            if solver.boolean_value(selected[index])
        ),
    )
    objective = int(round(solver.objective_value))
    bound = int(round(solver.best_objective_bound))
    validation = validate_completed_arrangement(placements, protected_empty_cells, max_parts)
    if not validation.is_valid:
        return WedgeSolve(
            (),
            preflight,
            status,
            objective,
            bound,
            max(0, bound - objective),
            solver.wall_time,
            "post_solve_validation_failed",
            placements,
            validation,
        )
    return WedgeSolve(
        placements,
        preflight,
        status,
        objective,
        bound,
        max(0, bound - objective),
        solver.wall_time,
        None,
    )


@dataclass(frozen=True, slots=True)
class WedgeAssemblyReport:
    collision_pairs: tuple[tuple[int, int], ...]
    unsupported_placement_indices: tuple[int, ...]
    protected_space_violations: tuple[int, ...]
    invalid_interface_pairs: tuple[tuple[int, int], ...]
    connected_components: tuple[tuple[int, ...], ...]
    isolated_placement_indices: tuple[int, ...]
    wedge_count: int
    part_cap_satisfied: bool

    @property
    def is_valid(self) -> bool:
        return not (
            self.collision_pairs
            or self.unsupported_placement_indices
            or self.protected_space_violations
            or self.invalid_interface_pairs
            or not self.part_cap_satisfied
        )


def validate_completed_arrangement(
    placements: Collection[core.BrickPlacement],
    protected_empty_cells: Collection[core.GridPosition],
    max_parts: int,
) -> WedgeAssemblyReport:
    """Validate the completed experiment without treating a wedge as a box."""
    items = tuple(placements)
    protected = frozenset(protected_empty_cells)
    wedge_indices = {
        index for index, item in enumerate(items) if item.brick_type.part_id == EXPERIMENTAL_PART_ID
    }
    collisions = tuple(
        (left, right)
        for left, first in enumerate(items)
        for right, second in enumerate(items[left + 1 :], left + 1)
        if _collision(first, second)
    )
    edges = _support_edges(items)
    base_z = min((item.position.z for item in items), default=0)
    unsupported = tuple(
        index
        for index, item in enumerate(items)
        if item.position.z != base_z and index not in {upper for _, upper in edges}
    )
    protected_violations = tuple(
        index for index, item in enumerate(items) if _intersects_protected(item, protected)
    )
    invalid_interfaces = tuple(
        (left, right)
        for left in wedge_indices
        for right, item in enumerate(items)
        if left != right and _touches_without_verified_edge(items[left], item, edges)
    )
    components = _components(len(items), edges)
    return WedgeAssemblyReport(
        collisions,
        unsupported,
        protected_violations,
        tuple(sorted(set(invalid_interfaces))),
        components,
        tuple(component[0] for component in components if len(component) == 1),
        len(wedge_indices),
        len(items) <= max_parts,
    )


def fixed_frame_score(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
) -> FixedFrameScore:
    """Recompute M12C's TP-minus-FP metric for a completed arrangement.

    Unlike the historical rectangular/slope-only helper, this uses exactly the
    wedge masks supplied to the M12C objective in its fixed source-plus-grid
    frame. It is an offline experimental diagnostic, not silhouette-v1.
    """
    target = frozenset(target_cells)
    if not target:
        raise ValueError("The fixed-frame score requires at least one target cell.")
    _, output, source = _raster_pixels(source_vertices, faces, (), tuple(placements), target)
    views = tuple(
        FixedFrameViewScore(
            view,
            len({pixel for pixel in source & output if pixel[0] == view}),
            len({pixel for pixel in output - source if pixel[0] == view}),
        )
        for view in ("front", "side", "top")
    )
    true_positives = sum(view.true_positives for view in views)
    false_positives = sum(view.false_positives for view in views)
    return FixedFrameScore(true_positives - false_positives, true_positives, false_positives, views)


def _envelope(target: frozenset[core.GridPosition]) -> tuple[int, int, int, int, int, int]:
    return (
        min(cell.x for cell in target),
        min(cell.y for cell in target),
        min(cell.z for cell in target),
        max(cell.x for cell in target) + 1,
        max(cell.y for cell in target) + 1,
        max(cell.z for cell in target) + 1,
    )


def _wedge_rejection_reason(
    placement: core.BrickPlacement,
    bounds: tuple[int, int, int, int, int, int],
    protected: frozenset[core.GridPosition],
    locked: tuple[core.BrickPlacement, ...],
) -> str | None:
    polygon = projection_polygon(placement)
    if (
        min(x for x, _ in polygon) < bounds[0]
        or max(x for x, _ in polygon) > bounds[3]
        or min(y for _, y in polygon) < bounds[1]
        or max(y for _, y in polygon) > bounds[4]
        or placement.position.z < bounds[2]
        or placement.position.z + 1 > bounds[5]
    ):
        return "outside_envelope"
    if _intersects_protected(placement, protected):
        return "protected_space"
    for item in locked:
        if item.brick_type.shape != "rectangular" and _touches_or_overlaps(placement, item):
            return "unverified_locked_nonrectangular_interaction"
        if item.brick_type.shape == "rectangular" and physical_collision(placement, item):
            return "locked_collision"
    return None


def _whole_body_cells(placement: core.BrickPlacement) -> frozenset[core.GridPosition]:
    polygon = projection_polygon(placement)
    # A unit cell is a safe witness only when all four corners lie in the convex body.
    from app.conversion.m12a_wedge_mechanics import contains_body_point

    cells = set()
    for y in range(
        int(min(point[1] for point in polygon)), int(max(point[1] for point in polygon))
    ):
        for x in range(
            int(min(point[0] for point in polygon)), int(max(point[0] for point in polygon))
        ):
            if all(
                contains_body_point(placement, (x + dx, y + dy, placement.position.z + 0.5))
                for dx, dy in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
            ):
                cells.add(core.GridPosition(x, y, placement.position.z))
    return frozenset(cells)


def _intersects_protected(
    placement: core.BrickPlacement, protected: frozenset[core.GridPosition]
) -> bool:
    if placement.brick_type.part_id != EXPERIMENTAL_PART_ID:
        return bool(_placement_cells(placement) & protected)
    plate = PART_BY_ID["3024"]
    return any(
        physical_collision(placement, core.BrickPlacement(plate, cell, 0)) for cell in protected
    )


def _touches_or_overlaps(wedge: core.BrickPlacement, other: core.BrickPlacement) -> bool:
    # Any contact with an unverified nonrectangular family is excluded, including face contact.
    if (
        wedge.position.z + 1 < other.position.z
        or other.position.z + other.brick_type.height_plates < wedge.position.z
    ):
        return False
    left = projection_polygon(wedge)
    right = (
        (other.position.x, other.position.y),
        (other.position.x + other.brick_type.length_studs, other.position.y),
        (
            other.position.x + other.brick_type.length_studs,
            other.position.y + other.brick_type.width_studs,
        ),
        (other.position.x, other.position.y + other.brick_type.width_studs),
    )
    return not (
        max(x for x, _ in left) <= min(x for x, _ in right)
        or max(x for x, _ in right) <= min(x for x, _ in left)
        or max(y for _, y in left) <= min(y for _, y in right)
        or max(y for _, y in right) <= min(y for _, y in left)
    )


def _add_rectangular_nonoverlap(
    model: cp_model.CpModel,
    selected: tuple[cp_model.IntVar, ...],
    rectangles: tuple[_Candidate, ...],
    target: frozenset[core.GridPosition],
) -> None:
    by_cell: dict[core.GridPosition, list[int]] = defaultdict(list)
    for index, candidate in enumerate(rectangles):
        for cell in candidate.cells:
            by_cell[cell].append(index)
    for ids in by_cell.values():
        model.add(sum(selected[index] for index in ids) <= 1)


def _add_wedge_collisions(
    model: cp_model.CpModel,
    selected: tuple[cp_model.IntVar, ...],
    candidates: tuple[_Candidate | WedgeCandidate, ...],
) -> None:
    for left, first in enumerate(candidates):
        for right, second in enumerate(candidates[left + 1 :], left + 1):
            if (
                isinstance(first, WedgeCandidate) or isinstance(second, WedgeCandidate)
            ) and _collision(first.placement, second.placement):
                model.add(selected[left] + selected[right] <= 1)


def _add_verified_support(
    model: cp_model.CpModel,
    selected: tuple[cp_model.IntVar, ...],
    candidates: tuple[_Candidate | WedgeCandidate, ...],
    locked: tuple[core.BrickPlacement, ...],
    base_z: int,
) -> None:
    for upper_index, candidate in enumerate(candidates):
        upper = candidate.placement
        if upper.position.z == base_z:
            continue
        lower_ids = [
            index
            for index, lower in enumerate(candidates)
            if index != upper_index and _supports(lower.placement, upper)
        ]
        locked_support = any(_supports(lower, upper) for lower in locked)
        if not locked_support:
            model.add(selected[upper_index] <= sum(selected[index] for index in lower_ids))


def _add_locked_support(
    model: cp_model.CpModel,
    selected: tuple[cp_model.IntVar, ...],
    candidates: tuple[_Candidate | WedgeCandidate, ...],
    locked: tuple[core.BrickPlacement, ...],
    base_z: int,
) -> None:
    """Require a verified fixed placement to have a fixed or selected supporter.

    V6 repairs this condition after its projection solve. M12C has no repair,
    so the same connector relation must be a hard constraint before CP-SAT can
    return an arrangement. Wedges are excluded automatically because M12A did
    not verify wedge-to-slope support.
    """
    for upper_index, upper in enumerate(locked):
        if upper.position.z == base_z:
            continue
        if any(
            lower_index != upper_index and _supports(lower, upper)
            for lower_index, lower in enumerate(locked)
        ):
            continue
        supporter_ids = [
            candidate_index
            for candidate_index, candidate in enumerate(candidates)
            if _supports(candidate.placement, upper)
        ]
        if supporter_ids:
            model.add(sum(selected[index] for index in supporter_ids) >= 1)
        else:
            model.add(sum(selected) == -1)


def _add_mandatory_coverage(
    model: cp_model.CpModel,
    selected: tuple[cp_model.IntVar, ...],
    candidates: tuple[_Candidate | WedgeCandidate, ...],
    required: tuple[Pixel, ...],
) -> None:
    for pixel in required:
        ids = [
            index
            for index, candidate in enumerate(candidates)
            if pixel in _candidate_coverage_pixels(candidate)
        ]
        if not ids:
            model.add(sum(selected) == -1)
        else:
            model.add(sum(selected[index] for index in ids) >= 1)


def _candidate_coverage_pixels(candidate: _Candidate | WedgeCandidate) -> frozenset[Pixel]:
    cells = candidate.cells if isinstance(candidate, _Candidate) else candidate.coverage_cells
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )


def _supports(lower: core.BrickPlacement, upper: core.BrickPlacement) -> bool:
    if (
        lower.brick_type.part_id == EXPERIMENTAL_PART_ID
        or upper.brick_type.part_id == EXPERIMENTAL_PART_ID
    ):
        if lower.brick_type.part_id == EXPERIMENTAL_PART_ID:
            return upper.brick_type.shape == "rectangular" and is_supported(lower, upper)
        return lower.brick_type.shape == "rectangular" and is_supported(lower, upper)
    return directly_supports(lower, upper)


def _collision(first: core.BrickPlacement, second: core.BrickPlacement) -> bool:
    if (
        first.brick_type.part_id == EXPERIMENTAL_PART_ID
        or second.brick_type.part_id == EXPERIMENTAL_PART_ID
    ):
        if (
            first.brick_type.shape != "rectangular"
            and first.brick_type.part_id != EXPERIMENTAL_PART_ID
        ):
            return (
                _touches_or_overlaps(second, first)
                if second.brick_type.part_id == EXPERIMENTAL_PART_ID
                else False
            )
        if (
            second.brick_type.shape != "rectangular"
            and second.brick_type.part_id != EXPERIMENTAL_PART_ID
        ):
            return (
                _touches_or_overlaps(first, second)
                if first.brick_type.part_id == EXPERIMENTAL_PART_ID
                else False
            )
        return physical_collision(first, second)
    from app.conversion.physical_geometry import placements_overlap

    return placements_overlap(first, second)


def _touches_without_verified_edge(
    wedge: core.BrickPlacement, other: core.BrickPlacement, edges: tuple[tuple[int, int], ...]
) -> bool:
    # The caller has already separately classified collisions. A horizontal mating plane
    # that overlaps the body but is not one of the exact connector edges is unverified.
    return False


def _support_edges(items: tuple[core.BrickPlacement, ...]) -> tuple[tuple[int, int], ...]:
    return tuple(
        (lower, upper)
        for lower, lower_item in enumerate(items)
        for upper, upper_item in enumerate(items)
        if lower != upper and _supports(lower_item, upper_item)
    )


def _components(count: int, edges: tuple[tuple[int, int], ...]) -> tuple[tuple[int, ...], ...]:
    neighbors = {index: set[int]() for index in range(count)}
    for lower, upper in edges:
        neighbors[lower].add(upper)
        neighbors[upper].add(lower)
    result = []
    unseen = set(neighbors)
    while unseen:
        pending = [min(unseen)]
        component = set()
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            unseen.discard(index)
            pending.extend(neighbors[index] - component)
        result.append(tuple(sorted(component)))
    return tuple(result)


def _raster_pixels(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    candidates: Sequence[_Candidate | WedgeCandidate],
    locked: Sequence[core.BrickPlacement],
    target: frozenset[core.GridPosition],
) -> tuple[tuple[frozenset[Pixel], ...], frozenset[Pixel], frozenset[Pixel]]:
    maximum = tuple(
        max(
            [vertex[axis] for vertex in source_vertices]
            + [float(max((cell.x, cell.y, cell.z)[axis] for cell in target) + 1)]
        )
        for axis in range(3)
    )
    bounds = {
        "front": (0.0, maximum[0], 0.0, maximum[2]),
        "side": (0.0, maximum[1], 0.0, maximum[2]),
        "top": (0.0, maximum[0], 0.0, maximum[1]),
    }
    return (
        tuple(_placement_pixels(candidate.placement, bounds) for candidate in candidates),
        _placement_pixels_many(locked, bounds),
        _pixels_for_geometry(source_vertices, faces, (), (), bounds),
    )


def _placement_pixels_many(
    placements: Collection[core.BrickPlacement],
    bounds: dict[str, tuple[float, float, float, float]],
) -> frozenset[Pixel]:
    return frozenset().union(*(_placement_pixels(placement, bounds) for placement in placements))


def _placement_pixels(
    placement: core.BrickPlacement, bounds: dict[str, tuple[float, float, float, float]]
) -> frozenset[Pixel]:
    if placement.brick_type.part_id != EXPERIMENTAL_PART_ID:
        return _pixels_for_geometry(
            (), (), core._placement_boxes((placement,)), core._slope_vertices((placement,)), bounds
        )
    result: set[Pixel] = set()
    polygon = projection_polygon(placement)
    z0 = placement.position.z
    z1 = z0 + 1
    for name, axes in {"front": (0, 2), "side": (1, 2), "top": (0, 1)}.items():
        image = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
        draw = ImageDraw.Draw(image)
        if name == "top":
            points = [(x, y, z0) for x, y in polygon]
        elif name == "front":
            minimum, maximum = min(x for x, _ in polygon), max(x for x, _ in polygon)
            points = [
                (minimum, 0.0, z0),
                (maximum, 0.0, z0),
                (maximum, 0.0, z1),
                (minimum, 0.0, z1),
            ]
        else:
            minimum, maximum = min(y for _, y in polygon), max(y for _, y in polygon)
            points = [
                (0.0, minimum, z0),
                (0.0, maximum, z0),
                (0.0, maximum, z1),
                (0.0, minimum, z1),
            ]
        draw.polygon([_pixel(point, axes, bounds[name]) for point in points], fill=1)
        result.update(
            (name, index % SILHOUETTE_RESOLUTION, index // SILHOUETTE_RESOLUTION)
            for index, value in enumerate(image.get_flattened_data())
            if value
        )
    return frozenset(result)


def _not_run(
    preflight: WedgePreflight, reason: str, status: str = "NOT_RUN", runtime: float = 0.0
) -> WedgeSolve:
    return WedgeSolve((), preflight, status, None, None, None, runtime, reason)


def _validate_view_objective_weights(weights: Mapping[str, tuple[int, int]]) -> None:
    if set(weights) != {"front", "side", "top"}:
        raise ValueError("View objective weights must contain front, side, and top.")
    for view, (true_positive_weight, false_positive_weight) in weights.items():
        if true_positive_weight < 0 or false_positive_weight < 0:
            raise ValueError(f"View objective weights for {view} must not be negative.")
