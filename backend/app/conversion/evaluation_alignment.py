"""Offline M8D checks for frozen silhouette evaluation and M8C feasibility.

This module deliberately calls the frozen ``silhouette-v1`` renderer for a
completed assembly.  It does not provide candidate masks to a solver and is
not imported by production conversion code.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from math import isfinite

from ortools.sat.python import cp_model
from PIL import Image, ImageDraw

from app.conversion import core
from app.conversion.buildability import analyze_buildability
from app.conversion.catalogue_silhouette_experiment import _pixels_for_geometry
from app.conversion.fidelity import (
    PROJECTION_PADDING_RATIO,
    SILHOUETTE_RESOLUTION,
    binary_mask_iou,
    render_silhouette_masks,
)
from app.conversion.physical_geometry import colliding_placement_pairs
from app.conversion.surface_grid_v4 import (
    _add_part_limit,
    _build_model,
    _Candidate,
    _candidate_ids_by_cell,
    _cells_by_pixel,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _support_reachable_candidates,
)

ProjectionPixel = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class ViewComparison:
    true_positives: int
    false_positives: int
    false_negatives: int
    iou: float
    source_equals_lego: bool


@dataclass(frozen=True, slots=True)
class SilhouetteComparison:
    front: ViewComparison
    side: ViewComparison
    top: ViewComparison
    mean_iou: float
    source_equals_lego: bool


@dataclass(frozen=True, slots=True)
class BaselineFeasibility:
    status: str
    candidate_count: int
    missing_placement_ids: tuple[str, ...]
    missing_mandatory_pixels: tuple[ProjectionPixel, ...]
    fixed_selection_status: str
    locked_placement_ids: tuple[str, ...]
    mandatory_coverage_satisfied: bool
    physical_projection_coverage_satisfied: bool
    protected_space_violations: int
    collision_pairs: int
    unsupported_placements: int
    part_cap_satisfied: bool
    fixed_geometry_coverage_pixel_count: int


@dataclass(frozen=True, slots=True)
class EvaluatorParityView:
    source_mask_difference_count: int
    lego_mask_difference_count: int
    true_positives_match: bool
    false_positives_match: bool
    false_negatives_match: bool
    iou_match: bool
    exact_pixel_match: bool


@dataclass(frozen=True, slots=True)
class EvaluatorParity:
    front: EvaluatorParityView
    side: EvaluatorParityView
    top: EvaluatorParityView
    exact_pixel_match: bool


def stable_placement_id(placement: core.BrickPlacement) -> str:
    """Return a private-artifact-safe, deterministic placement identifier."""
    position = placement.position
    return (
        f"{placement.brick_type.part_id}@{position.x},{position.y},{position.z}:"
        f"{placement.orientation_degrees}"
    )


def evaluate_completed_assembly(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
) -> SilhouetteComparison:
    """Compare a completed build against frozen silhouette-v1 pixel for pixel."""
    placement_tuple = tuple(placements)
    masks = render_silhouette_masks(
        source_vertices,
        faces,
        core._placement_boxes(placement_tuple),
        slope_vertices=core._slope_vertices(placement_tuple),
        wedge_vertices=core._wedge_vertices(placement_tuple),
    )
    comparisons = {view: _compare_masks(source, output) for view, (source, output) in masks.items()}
    front = comparisons["front"]
    side = comparisons["side"]
    top = comparisons["top"]
    return SilhouetteComparison(
        front,
        side,
        top,
        round((front.iou + side.iou + top.iou) / 3, 6),
        front.source_equals_lego and side.source_equals_lego and top.source_equals_lego,
    )


def compare_frozen_evaluator_parity(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
) -> EvaluatorParity:
    """Compare an independent diagnostic raster pass with frozen silhouette-v1."""
    placement_tuple = tuple(placements)
    boxes = core._placement_boxes(placement_tuple)
    slopes = core._slope_vertices(placement_tuple)
    wedges = core._wedge_vertices(placement_tuple)
    frozen = render_silhouette_masks(
        source_vertices, faces, boxes, slope_vertices=slopes, wedge_vertices=wedges
    )
    diagnostic = _render_diagnostic_masks(source_vertices, faces, boxes, slopes, wedges)
    views = {
        view: _parity_view(frozen[view], diagnostic[view]) for view in ("front", "side", "top")
    }
    return EvaluatorParity(
        views["front"],
        views["side"],
        views["top"],
        all(view.exact_pixel_match for view in views.values()),
    )


def fixed_frame_surrogate_score(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
) -> int:
    """Return M8C's TP-minus-FP score for one completed arrangement.

    This reproduces the original fixed source-plus-grid frame only.  It is not
    silhouette-v1 and remains unsuitable as evidence of final IoU equivalence.
    """
    target = tuple(target_cells)
    if not target:
        raise ValueError("The fixed-frame surrogate requires at least one target cell.")
    source_maximum = tuple(max(vertex[axis] for vertex in source_vertices) for axis in range(3))
    grid_maximum = (
        float(max(cell.x for cell in target) + 1),
        float(max(cell.y for cell in target) + 1),
        float(max(cell.z for cell in target) + 1),
    )
    maximum = tuple(max(source_maximum[axis], grid_maximum[axis]) for axis in range(3))
    bounds = {
        "front": (0.0, maximum[0], 0.0, maximum[2]),
        "side": (0.0, maximum[1], 0.0, maximum[2]),
        "top": (0.0, maximum[0], 0.0, maximum[1]),
    }
    source = _pixels_for_geometry(source_vertices, faces, (), (), bounds)
    placement_tuple = tuple(placements)
    output = _pixels_for_geometry(
        (),
        (),
        core._placement_boxes(placement_tuple),
        core._slope_vertices(placement_tuple),
        bounds,
    )
    return len(source & output) - len(output - source)


def fixed_frame_iou(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
) -> float:
    """Return exact union IoU in M8C's fixed frame, not silhouette-v1.

    This is useful for bounded M9A reporting. It remains a surrogate because
    frozen silhouette-v1 recomputes its padded bounds from the final assembly.
    """
    target = tuple(target_cells)
    if not target:
        raise ValueError("The fixed-frame surrogate requires at least one target cell.")
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
    placement_tuple = tuple(placements)
    output = _pixels_for_geometry(
        (),
        (),
        core._placement_boxes(placement_tuple),
        core._slope_vertices(placement_tuple),
        bounds,
    )
    union = source | output
    return 1.0 if not union else round(len(source & output) / len(union), 6)


def verify_baseline_feasibility(
    *,
    target_cells: Collection[core.GridPosition],
    required_pixels: Collection[ProjectionPixel],
    protected_empty_cells: Collection[core.GridPosition],
    baseline_placements: Collection[core.BrickPlacement],
    locked_projection_cells: Collection[core.GridPosition] | None = None,
    fixed_coverage_pixels: Collection[ProjectionPixel] = (),
    max_parts: int,
) -> BaselineFeasibility:
    """Check whether a reconstructed V6 build is selectable by the M8C model.

    V6 non-rectangular placements are M8C's locked geometry.  Every remaining
    baseline part must have the exact part ID, lattice position, and orientation
    of one rebuilt eligible M8C candidate.  This intentionally does not treat
    same-sized but differently identified catalogue parts as equivalent.
    """
    target = frozenset(target_cells)
    baseline = tuple(baseline_placements)
    locked = tuple(part for part in baseline if part.brick_type.shape != "rectangular")
    candidates = _support_reachable_candidates(
        _exclude_locked_body_collisions(
            _enumerate_candidates(target, core.BRICK_CATALOGUE), locked
        ),
        target,
    )
    candidate_ids = {stable_placement_id(candidate.placement) for candidate in candidates}
    selected = tuple(part for part in baseline if part.brick_type.shape == "rectangular")
    missing = tuple(
        stable_placement_id(part)
        for part in selected
        if stable_placement_id(part) not in candidate_ids
    )
    selected_cells = {
        cell
        for part in baseline
        if part.brick_type.shape == "rectangular"
        for cell in core._placement_cells(part)
    }
    locked_cells = (
        frozenset(locked_projection_cells)
        if locked_projection_cells is not None
        else frozenset(cell for part in locked for cell in core._placement_source_cells(part))
    )
    physical_coverage = _projection_pixels(selected_cells | locked_cells)
    required = frozenset(required_pixels)
    protected = frozenset(protected_empty_cells)
    buildability = analyze_buildability(baseline)
    protected_violations = len(selected_cells & protected)
    collisions = len(colliding_placement_pairs(baseline))
    part_cap = len(baseline) <= max_parts
    physical_coverage_satisfied = required.issubset(physical_coverage)
    selected_ids = {stable_placement_id(part) for part in selected}
    selected_candidate_ids = tuple(
        index
        for index, candidate in enumerate(candidates)
        if stable_placement_id(candidate.placement) in selected_ids
    )
    fixed_coverage = frozenset(fixed_coverage_pixels)
    # This remains empty for the historical M8D model. M9A supplies only
    # witnesses derived from locked source-profile geometry.
    model_status = _fixed_selection_status(
        candidates,
        target,
        required - fixed_coverage,
        selected_candidate_ids,
        len(locked),
        max_parts,
    )
    selected_candidate_cells = {
        cell for index in selected_candidate_ids for cell in candidates[index].cells
    }
    model_coverage = _projection_pixels(selected_candidate_cells)
    missing_pixels = tuple(sorted(required - model_coverage - fixed_coverage))
    coverage_satisfied = model_status in {"OPTIMAL", "FEASIBLE"}
    status = (
        "FEASIBLE"
        if not missing
        and coverage_satisfied
        and not protected_violations
        and not collisions
        and not buildability.unsupported_placement_count
        and part_cap
        else "INFEASIBLE"
    )
    return BaselineFeasibility(
        status,
        len(candidates),
        missing,
        missing_pixels,
        model_status,
        tuple(stable_placement_id(part) for part in locked),
        coverage_satisfied,
        physical_coverage_satisfied,
        protected_violations,
        collisions,
        buildability.unsupported_placement_count,
        part_cap,
        len(required & fixed_coverage),
    )


def _compare_masks(source: Image.Image, output: Image.Image) -> ViewComparison:
    # The two images have the same 128x128 size by the frozen renderer's contract.
    source_pixels = tuple(source.get_flattened_data())
    output_pixels = tuple(output.get_flattened_data())
    pairs = tuple(zip(source_pixels, output_pixels, strict=True))
    true_positives = sum(bool(left) and bool(right) for left, right in pairs)
    false_positives = sum(not bool(left) and bool(right) for left, right in pairs)
    false_negatives = sum(bool(left) and not bool(right) for left, right in pairs)
    return ViewComparison(
        true_positives,
        false_positives,
        false_negatives,
        binary_mask_iou(source, output),
        source_pixels == output_pixels,
    )


def _fixed_selection_status(
    candidates: tuple[_Candidate, ...],
    target: frozenset[core.GridPosition],
    required_pixels: frozenset[ProjectionPixel],
    selected_candidate_ids: tuple[int, ...],
    locked_count: int,
    max_parts: int,
) -> str:
    """Solve M8C's original hard model after fixing every baseline candidate."""
    model_data = _build_model(
        candidates,
        target,
        tuple(sorted(required_pixels)),
        _candidate_ids_by_cell(target, candidates),
        _cells_by_pixel(target),
    )
    _add_part_limit(model_data.model, model_data.selected, max_parts, locked_count)
    selected = frozenset(selected_candidate_ids)
    for index, variable in enumerate(model_data.selected):
        model_data.model.add(variable == int(index in selected))
    for coverage in model_data.coverage:
        model_data.model.add(coverage == 1)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    return solver.status_name(solver.solve(model_data.model))


def _render_diagnostic_masks(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    boxes: Sequence[tuple[float, float, float, float, float, float]],
    slopes: Sequence[tuple[tuple[float, float, float], ...]],
    wedges: Sequence[tuple[tuple[float, float, float], ...]],
) -> dict[str, tuple[Image.Image, Image.Image]]:
    """Independently reproduce the documented silhouette-v1 raster contract."""
    views = {"front": (0, 2), "side": (1, 2), "top": (0, 1)}
    return {
        name: _diagnostic_projection_masks(
            source_vertices, faces, boxes, slopes, wedges, projection
        )
        for name, projection in views.items()
    }


def _diagnostic_projection_masks(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    boxes: Sequence[tuple[float, float, float, float, float, float]],
    slopes: Sequence[tuple[tuple[float, float, float], ...]],
    wedges: Sequence[tuple[tuple[float, float, float], ...]],
    projection: tuple[int, int],
) -> tuple[Image.Image, Image.Image]:
    bounds = _diagnostic_bounds(source_vertices, boxes, slopes, wedges, projection)
    source = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
    lego = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
    source_draw = ImageDraw.Draw(source)
    lego_draw = ImageDraw.Draw(lego)
    for face in faces:
        source_draw.polygon(
            [_diagnostic_pixel(source_vertices[index], projection, bounds) for index in face],
            fill=1,
        )
    for box in boxes:
        first = _diagnostic_pixel((box[0], box[1], box[2]), projection, bounds)
        second = _diagnostic_pixel((box[3], box[4], box[5]), projection, bounds)
        left, right = sorted((first[0], second[0]))
        top, bottom = sorted((first[1], second[1]))
        lego_draw.rectangle((left, top, right, bottom), fill=1)
    slope_faces = (
        (0, 1, 2),
        (3, 5, 4),
        (0, 4, 1),
        (0, 3, 4),
        (1, 4, 5),
        (1, 5, 2),
        (0, 2, 5),
        (0, 5, 3),
    )
    for slope in slopes:
        for face in slope_faces:
            lego_draw.polygon(
                [_diagnostic_pixel(slope[index], projection, bounds) for index in face], fill=1
            )
    for wedge in wedges:
        half = len(wedge) // 2
        lego_draw.polygon(
            [_diagnostic_pixel(vertex, projection, bounds) for vertex in wedge[:half]], fill=1
        )
        lego_draw.polygon(
            [_diagnostic_pixel(vertex, projection, bounds) for vertex in wedge[half:]], fill=1
        )
    return source, lego


def _diagnostic_bounds(
    source_vertices: Sequence[tuple[float, float, float]],
    boxes: Sequence[tuple[float, float, float, float, float, float]],
    slopes: Sequence[tuple[tuple[float, float, float], ...]],
    wedges: Sequence[tuple[tuple[float, float, float], ...]],
    projection: tuple[int, int],
) -> tuple[float, float, float, float]:
    first_axis, second_axis = projection
    coordinates = [(vertex[first_axis], vertex[second_axis]) for vertex in source_vertices]
    for box in boxes:
        minimum = (box[0], box[1], box[2])
        maximum = (box[3], box[4], box[5])
        coordinates.extend(
            (first, second)
            for first in (minimum[first_axis], maximum[first_axis])
            for second in (minimum[second_axis], maximum[second_axis])
        )
    for geometry in (*slopes, *wedges):
        coordinates.extend((vertex[first_axis], vertex[second_axis]) for vertex in geometry)
    if not coordinates:
        return (0.0, 1.0, 0.0, 1.0)
    minimum_first = min(first for first, _ in coordinates)
    maximum_first = max(first for first, _ in coordinates)
    minimum_second = min(second for _, second in coordinates)
    maximum_second = max(second for _, second in coordinates)
    return (
        minimum_first - max((maximum_first - minimum_first) * PROJECTION_PADDING_RATIO, 1e-9),
        maximum_first + max((maximum_first - minimum_first) * PROJECTION_PADDING_RATIO, 1e-9),
        minimum_second - max((maximum_second - minimum_second) * PROJECTION_PADDING_RATIO, 1e-9),
        maximum_second + max((maximum_second - minimum_second) * PROJECTION_PADDING_RATIO, 1e-9),
    )


def _diagnostic_pixel(
    point: tuple[float, float, float],
    projection: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> tuple[int, int]:
    first_axis, second_axis = projection
    minimum_first, maximum_first, minimum_second, maximum_second = bounds
    return (
        _diagnostic_scaled_pixel(point[first_axis], minimum_first, maximum_first),
        SILHOUETTE_RESOLUTION
        - 1
        - _diagnostic_scaled_pixel(point[second_axis], minimum_second, maximum_second),
    )


def _diagnostic_scaled_pixel(value: float, minimum: float, maximum: float) -> int:
    if not isfinite(value):
        raise ValueError("Projection coordinates must be finite.")
    pixel = round((value - minimum) / (maximum - minimum) * (SILHOUETTE_RESOLUTION - 1))
    return min(SILHOUETTE_RESOLUTION - 1, max(0, pixel))


def _parity_view(
    frozen: tuple[Image.Image, Image.Image], diagnostic: tuple[Image.Image, Image.Image]
) -> EvaluatorParityView:
    frozen_source, frozen_lego = frozen
    diagnostic_source, diagnostic_lego = diagnostic
    source_difference = _pixel_difference_count(frozen_source, diagnostic_source)
    lego_difference = _pixel_difference_count(frozen_lego, diagnostic_lego)
    frozen_counts = _compare_masks(frozen_source, frozen_lego)
    diagnostic_counts = _compare_masks(diagnostic_source, diagnostic_lego)
    return EvaluatorParityView(
        source_difference,
        lego_difference,
        frozen_counts.true_positives == diagnostic_counts.true_positives,
        frozen_counts.false_positives == diagnostic_counts.false_positives,
        frozen_counts.false_negatives == diagnostic_counts.false_negatives,
        frozen_counts.iou == diagnostic_counts.iou,
        source_difference == 0 and lego_difference == 0,
    )


def _pixel_difference_count(first: Image.Image, second: Image.Image) -> int:
    return sum(
        left != right
        for left, right in zip(first.get_flattened_data(), second.get_flattened_data(), strict=True)
    )


def _projection_pixels(cells: Collection[core.GridPosition]) -> frozenset[ProjectionPixel]:
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )
