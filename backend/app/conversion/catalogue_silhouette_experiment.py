"""Offline-only M8C catalogue silhouette optimisation.

This module is intentionally not imported by the API, workers, or ``convert_glb``.
It reuses the V6 candidate and mechanical formulation, but replaces the packing
objective with a bounded union-of-projected-geometry score.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model
from PIL import Image, ImageDraw

from app.conversion import core
from app.conversion.fidelity import SILHOUETTE_RESOLUTION
from app.conversion.surface_grid_v4 import (
    SOLVER_RANDOM_SEED,
    SOLVER_WORKERS,
    _add_part_limit,
    _build_model,
    _Candidate,
    _candidate_ids_by_cell,
    _cells_by_pixel,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _repair_locked_verified_support,
    _selected_ids,
    _support_reachable_candidates,
    _validate_placements,
)

MAX_CANDIDATES = 4_000
MAX_VARIABLE_RASTER_PIXELS = 49_152  # 128 x 128 pixels across three fixed views.
MAX_DETERMINISTIC_TIME = 20.0
Pixel = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class CatalogueSilhouetteSolve:
    placements: tuple[core.BrickPlacement, ...]
    candidate_count: int
    variable_pixel_count: int
    status: str
    objective_value: int | None
    best_objective_bound: int | None
    optimality_gap: int | None
    runtime_seconds: float
    fallback_reason: str | None


def optimise_catalogue_silhouette(
    *,
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    target_cells: Collection[core.GridPosition],
    required_pixels: Collection[tuple[str, int, int]],
    locked_placements: Collection[core.BrickPlacement],
    max_parts: int,
    target_parts: int,
) -> CatalogueSilhouetteSolve:
    """Optimise TP-minus-FP pixel union while retaining V6 hard constraints.

    The source and every candidate are rasterised once in a fixed source-plus-grid
    envelope.  This makes a candidate's pixel set independent of the selected
    combination.  The external report still evaluates completed builds with the
    unchanged silhouette-v1 renderer.
    """
    del target_parts  # The fixed lattice, not a preferred count, defines this experiment.
    target = frozenset(target_cells)
    locked = tuple(locked_placements)
    candidates = _support_reachable_candidates(
        _exclude_locked_body_collisions(
            _enumerate_candidates(target, core.BRICK_CATALOGUE), locked
        ),
        target,
    )
    if len(candidates) > MAX_CANDIDATES:
        return _not_run(len(candidates), "candidate_limit_exhausted")
    if not candidates:
        return _not_run(0, "no_eligible_candidates")

    candidate_pixels, fixed_pixels, source_pixels = _raster_pixels(
        source_vertices, faces, candidates, locked, target
    )
    candidate_union_pixels = {pixel for pixels in candidate_pixels for pixel in pixels}
    all_pixels = set(fixed_pixels) | candidate_union_pixels
    if len(all_pixels) > MAX_VARIABLE_RASTER_PIXELS:
        return _not_run(len(candidates), "raster_pixel_limit_exhausted")

    # Reuse V6 occupancy, direct-support, collision-by-cell, part-cap, and
    # mandatory source-projection coverage constraints.  The occupancy coverage
    # variables are not the silhouette objective; their only role is the V6
    # feasible-set contract.
    model_data = _build_model(
        candidates,
        target,
        tuple(sorted(set(required_pixels))),
        _candidate_ids_by_cell(target, candidates),
        _cells_by_pixel(target),
    )
    _add_part_limit(model_data.model, model_data.selected, max_parts, len(locked))
    for coverage in model_data.coverage:
        model_data.model.add(coverage == 1)

    by_pixel: dict[Pixel, list[int]] = defaultdict(list)
    for candidate_id, pixels in enumerate(candidate_pixels):
        for pixel in pixels:
            by_pixel[pixel].append(candidate_id)
    # Pixels with the same selecting-candidate set and source membership are
    # interchangeable. Grouping them is exactly equivalent to a pixel-level
    # union model while avoiding up to 49,152 Boolean variables.
    groups: dict[tuple[tuple[int, ...], bool], int] = defaultdict(int)
    fixed_true_positives = len(source_pixels & fixed_pixels)
    for pixel in all_pixels - fixed_pixels:
        groups[(tuple(by_pixel[pixel]), pixel in source_pixels)] += 1
    true_positive: cp_model.LinearExpr | int = fixed_true_positives
    false_positive: cp_model.LinearExpr | int = len(fixed_pixels - source_pixels)
    for group_id, ((candidate_ids, is_source), count) in enumerate(sorted(groups.items())):
        variable = model_data.model.new_bool_var(f"silhouette_group_{group_id}")
        model_data.model.add_max_equality(
            variable, [model_data.selected[index] for index in candidate_ids]
        )
        if is_source:
            true_positive += count * variable
        else:
            false_positive += count * variable
    # A one-unit final tie-break gives deterministic preference to fewer parts
    # without changing a TP-minus-FP difference.
    part_weight = len(candidates) + 1
    model_data.model.maximize(
        (true_positive - false_positive) * part_weight - sum(model_data.selected)
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = MAX_DETERMINISTIC_TIME
    solver.parameters.num_search_workers = SOLVER_WORKERS
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    status_code = solver.solve(model_data.model)
    status = solver.status_name(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return _not_run(
            len(candidates), "infeasible" if status == "INFEASIBLE" else "limit_exhausted", status
        )

    selected = _selected_ids(solver, model_data.selected)
    # The established local repair is retained for fixed slopes.  It can change
    # a bounded incumbent, so callers must score returned placements separately.
    placements, _ = _repair_locked_verified_support(
        candidates,
        selected,
        locked,
        min(cell.z for cell in target),
        tuple(sorted(set(required_pixels))),
        _cells_by_pixel(target),
        max_parts=max_parts,
        reliable_repair=True,
    )
    _validate_placements(placements, target, locked, max_parts=max_parts)
    objective = int(round(solver.objective_value))
    bound = int(round(solver.best_objective_bound))
    return CatalogueSilhouetteSolve(
        placements=(*locked, *placements),
        candidate_count=len(candidates),
        variable_pixel_count=len(groups),
        status=status,
        objective_value=objective,
        best_objective_bound=bound,
        optimality_gap=max(0, bound - objective),
        runtime_seconds=solver.wall_time,
        fallback_reason=None,
    )


def _not_run(
    candidate_count: int, reason: str, status: str = "NOT_RUN"
) -> CatalogueSilhouetteSolve:
    return CatalogueSilhouetteSolve((), candidate_count, 0, status, None, None, None, 0.0, reason)


def _raster_pixels(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    candidates: Sequence[_Candidate],
    locked: Sequence[core.BrickPlacement],
    target: Collection[core.GridPosition],
) -> tuple[tuple[frozenset[Pixel], ...], frozenset[Pixel], frozenset[Pixel]]:
    """Raster actual candidate bodies in a fixed grid-envelope coordinate frame."""
    maximum = (
        max(
            [vertex[0] for vertex in source_vertices] + [float(max(cell.x for cell in target) + 1)]
        ),
        max(
            [vertex[1] for vertex in source_vertices] + [float(max(cell.y for cell in target) + 1)]
        ),
        max(
            [vertex[2] for vertex in source_vertices] + [float(max(cell.z for cell in target) + 1)]
        ),
    )
    bounds = {
        "front": (0.0, maximum[0], 0.0, maximum[2]),
        "side": (0.0, maximum[1], 0.0, maximum[2]),
        "top": (0.0, maximum[0], 0.0, maximum[1]),
    }
    source = _pixels_for_geometry(source_vertices, faces, (), (), bounds)
    fixed = _pixels_for_geometry(
        (), (), core._placement_boxes(tuple(locked)), core._slope_vertices(locked), bounds
    )
    candidate_pixels = tuple(
        _pixels_for_geometry((), (), core._placement_boxes((candidate.placement,)), (), bounds)
        for candidate in candidates
    )
    return candidate_pixels, fixed, source


def _pixels_for_geometry(
    vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    boxes: Sequence[tuple[float, float, float, float, float, float]],
    slopes: Sequence[tuple[tuple[float, float, float], ...]],
    bounds: dict[str, tuple[float, float, float, float]],
) -> frozenset[Pixel]:
    result: set[Pixel] = set()
    views = {"front": (0, 2), "side": (1, 2), "top": (0, 1)}
    for name, projection in views.items():
        image = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
        draw = ImageDraw.Draw(image)
        for face in faces:
            draw.polygon(
                [_pixel(vertices[index], projection, bounds[name]) for index in face], fill=1
            )
        for box in boxes:
            first = _pixel((box[0], box[1], box[2]), projection, bounds[name])
            second = _pixel((box[3], box[4], box[5]), projection, bounds[name])
            draw.rectangle((*map(min, first, second), *map(max, first, second)), fill=1)
        for slope in slopes:
            # silhouette-v1 draws every prism face; drawing the two end polygons
            # is sufficient for an orthographic union and avoids private helpers.
            draw.polygon([_pixel(point, projection, bounds[name]) for point in slope], fill=1)
        result.update(
            (name, index % SILHOUETTE_RESOLUTION, index // SILHOUETTE_RESOLUTION)
            for index, value in enumerate(image.get_flattened_data())
            if value
        )
    return frozenset(result)


def _pixel(
    point: tuple[float, float, float],
    projection: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> tuple[int, int]:
    minimum_first, maximum_first, minimum_second, maximum_second = bounds
    first = round(
        (point[projection[0]] - minimum_first)
        / (maximum_first - minimum_first)
        * (SILHOUETTE_RESOLUTION - 1)
    )
    second = round(
        (point[projection[1]] - minimum_second)
        / (maximum_second - minimum_second)
        * (SILHOUETTE_RESOLUTION - 1)
    )
    return (
        min(SILHOUETTE_RESOLUTION - 1, max(0, first)),
        SILHOUETTE_RESOLUTION - 1 - min(SILHOUETTE_RESOLUTION - 1, max(0, second)),
    )
