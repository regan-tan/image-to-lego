"""Offline measurements used by the M13A objective-alignment audit.

This module does not participate in conversion or solver selection.  It renders
already-completed arrangements with either explicitly supplied common bounds or
silhouette-v1's native bounds so a diagnostic can keep geometry constant while
changing only the frame.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from PIL import Image, ImageDraw

from app.conversion import core
from app.conversion.fidelity import (
    PROJECTION_PADDING_RATIO,
    SILHOUETTE_RESOLUTION,
    render_silhouette_masks,
)

Point3D = tuple[float, float, float]
Bounds = tuple[float, float, float, float]
VIEW_AXES: dict[str, tuple[int, int]] = {
    "front": (0, 2),
    "side": (1, 2),
    "top": (0, 1),
}
SLOPE_FACES = (
    (0, 1, 2),
    (3, 5, 4),
    (0, 4, 1),
    (0, 3, 4),
    (1, 4, 5),
    (1, 5, 2),
    (0, 2, 5),
    (0, 5, 3),
)


@dataclass(frozen=True, slots=True)
class ViewMetrics:
    true_positives: int
    false_positives: int
    false_negatives: int
    iou: float

    @property
    def tp_minus_fp(self) -> int:
        return self.true_positives - self.false_positives


@dataclass(frozen=True, slots=True)
class ArrangementMetrics:
    frame: str
    bounds: tuple[tuple[str, Bounds], ...]
    front: ViewMetrics
    side: ViewMetrics
    top: ViewMetrics

    @property
    def mean_iou(self) -> float:
        return round((self.front.iou + self.side.iou + self.top.iou) / 3, 6)

    @property
    def tp_minus_fp(self) -> int:
        return self.front.tp_minus_fp + self.side.tp_minus_fp + self.top.tp_minus_fp


def score_counts(true_positives: int, false_positives: int, false_negatives: int) -> ViewMetrics:
    """Calculate independently inspectable mask metrics from integer counts."""
    if min(true_positives, false_positives, false_negatives) < 0:
        raise ValueError("Mask counts must not be negative.")
    union = true_positives + false_positives + false_negatives
    return ViewMetrics(
        true_positives,
        false_positives,
        false_negatives,
        1.0 if union == 0 else round(true_positives / union, 6),
    )


def native_bounds(
    source_vertices: Sequence[Point3D], placements: Collection[core.BrickPlacement]
) -> dict[str, Bounds]:
    """Return silhouette-v1's source-plus-arrangement padded bounds."""
    placement_tuple = tuple(placements)
    boxes = core._placement_boxes(placement_tuple)
    geometry = (*core._slope_vertices(placement_tuple), *core._wedge_vertices(placement_tuple))
    return {
        view: _bounds_for_view(source_vertices, boxes, geometry, axes)
        for view, axes in VIEW_AXES.items()
    }


def evaluate_native(
    source_vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
) -> ArrangementMetrics:
    """Measure exactly with frozen silhouette-v1 masks and record its bounds."""
    placement_tuple = tuple(placements)
    masks = render_silhouette_masks(
        source_vertices,
        faces,
        core._placement_boxes(placement_tuple),
        slope_vertices=core._slope_vertices(placement_tuple),
        wedge_vertices=core._wedge_vertices(placement_tuple),
    )
    return _arrangement_metrics(
        "silhouette-v1-native", native_bounds(source_vertices, placement_tuple), masks
    )


def evaluate_shared_bounds(
    source_vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
    bounds: Mapping[str, Bounds],
) -> ArrangementMetrics:
    """Measure one arrangement in caller-supplied common bounds.

    ``bounds`` must be reused unchanged for every arrangement being compared.
    This is deliberately separate from silhouette-v1 and cannot replace it.
    """
    if set(bounds) != set(VIEW_AXES):
        raise ValueError("Common bounds must contain front, side, and top views.")
    placement_tuple = tuple(placements)
    boxes = core._placement_boxes(placement_tuple)
    slopes = core._slope_vertices(placement_tuple)
    wedges = core._wedge_vertices(placement_tuple)
    masks = {
        view: (
            _render_geometry(source_vertices, faces, (), (), (), axes, bounds[view]),
            _render_geometry((), (), boxes, slopes, wedges, axes, bounds[view]),
        )
        for view, axes in VIEW_AXES.items()
    }
    return _arrangement_metrics("shared-explicit", dict(bounds), masks)


def combined_native_bounds(
    source_vertices: Sequence[Point3D],
    left: Collection[core.BrickPlacement],
    right: Collection[core.BrickPlacement],
) -> dict[str, Bounds]:
    """Create one padded source-plus-both-arrangements frame for comparison."""
    return native_bounds(source_vertices, (*left, *right))


def _arrangement_metrics(
    frame: str,
    bounds: Mapping[str, Bounds],
    masks: Mapping[str, tuple[Image.Image, Image.Image]],
) -> ArrangementMetrics:
    measured = {view: _mask_counts(*masks[view]) for view in VIEW_AXES}
    return ArrangementMetrics(
        frame,
        tuple((view, bounds[view]) for view in VIEW_AXES),
        measured["front"],
        measured["side"],
        measured["top"],
    )


def _mask_counts(source: Image.Image, lego: Image.Image) -> ViewMetrics:
    true_positives = false_positives = false_negatives = 0
    for source_pixel, lego_pixel in zip(
        source.get_flattened_data(), lego.get_flattened_data(), strict=True
    ):
        if source_pixel and lego_pixel:
            true_positives += 1
        elif lego_pixel:
            false_positives += 1
        elif source_pixel:
            false_negatives += 1
    return score_counts(true_positives, false_positives, false_negatives)


def _bounds_for_view(
    source_vertices: Sequence[Point3D],
    boxes: Sequence[tuple[float, float, float, float, float, float]],
    geometry: Sequence[Sequence[Point3D]],
    axes: tuple[int, int],
) -> Bounds:
    first_axis, second_axis = axes
    points = [(point[first_axis], point[second_axis]) for point in source_vertices]
    for box in boxes:
        minimum = (box[0], box[1], box[2])
        maximum = (box[3], box[4], box[5])
        points.extend(
            (first, second)
            for first in (minimum[first_axis], maximum[first_axis])
            for second in (minimum[second_axis], maximum[second_axis])
        )
    for item in geometry:
        points.extend((point[first_axis], point[second_axis]) for point in item)
    if not points:
        return (0.0, 1.0, 0.0, 1.0)
    minimum_first = min(first for first, _ in points)
    maximum_first = max(first for first, _ in points)
    minimum_second = min(second for _, second in points)
    maximum_second = max(second for _, second in points)
    first_padding = max((maximum_first - minimum_first) * PROJECTION_PADDING_RATIO, 1e-9)
    second_padding = max((maximum_second - minimum_second) * PROJECTION_PADDING_RATIO, 1e-9)
    return (
        minimum_first - first_padding,
        maximum_first + first_padding,
        minimum_second - second_padding,
        maximum_second + second_padding,
    )


def _render_geometry(
    vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    boxes: Sequence[tuple[float, float, float, float, float, float]],
    slopes: Sequence[Sequence[Point3D]],
    wedges: Sequence[Sequence[Point3D]],
    axes: tuple[int, int],
    bounds: Bounds,
) -> Image.Image:
    image = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
    draw = ImageDraw.Draw(image)
    for face in faces:
        draw.polygon([_pixel(vertices[index], axes, bounds) for index in face], fill=1)
    for box in boxes:
        first = _pixel((box[0], box[1], box[2]), axes, bounds)
        second = _pixel((box[3], box[4], box[5]), axes, bounds)
        draw.rectangle((*map(min, first, second), *map(max, first, second)), fill=1)
    for slope in slopes:
        for face in SLOPE_FACES:
            draw.polygon([_pixel(slope[index], axes, bounds) for index in face], fill=1)
    for wedge in wedges:
        half = len(wedge) // 2
        draw.polygon([_pixel(point, axes, bounds) for point in wedge[:half]], fill=1)
        draw.polygon([_pixel(point, axes, bounds) for point in wedge[half:]], fill=1)
    return image


def _pixel(point: Point3D, axes: tuple[int, int], bounds: Bounds) -> tuple[int, int]:
    minimum_first, maximum_first, minimum_second, maximum_second = bounds
    return (
        _scaled_pixel(point[axes[0]], minimum_first, maximum_first),
        SILHOUETTE_RESOLUTION - 1 - _scaled_pixel(point[axes[1]], minimum_second, maximum_second),
    )


def _scaled_pixel(value: float, minimum: float, maximum: float) -> int:
    if not isfinite(value):
        raise ValueError("Projection coordinates must be finite.")
    pixel = round((value - minimum) / (maximum - minimum) * (SILHOUETTE_RESOLUTION - 1))
    return min(SILHOUETTE_RESOLUTION - 1, max(0, pixel))
