"""Offline common-frame geometry metrics for physical-scale experiments.

The frozen silhouette-v1 metric chooses bounds from each model.  This module
keeps that metric untouched and supplies a separate, fixed source-defined
frame so differently sized diagnostic grids can be compared honestly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Final

from PIL import Image, ImageDraw

from app.conversion import core
from app.conversion.fidelity import _SLOPE_PRISM_FACES, binary_mask_iou
from app.conversion.part_catalogue import SLOPE_33_FAMILY

NORMALIZED_GEOMETRY_VERSION: Final = "scale-normalized-geometry-v1"
RASTER_RESOLUTION: Final = 256
_VIEWS: Final = {"front": (0, 2), "side": (1, 2), "top": (0, 1)}

Point3D = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class NormalizedSilhouette:
    metrics_version: str
    status: str
    reason: str | None
    front_iou: float | None
    side_iou: float | None
    top_iou: float | None
    mean_iou: float | None
    false_positive_pixels: dict[str, int] | None
    false_negative_pixels: dict[str, int] | None

    def record(self) -> dict[str, object]:
        return asdict(self)


def evaluate_scale_normalized_silhouette(
    source_vertices: Sequence[Point3D],
    source_faces: Sequence[tuple[int, int, int]],
    placements: Sequence[core.BrickPlacement],
    *,
    nominal_grid: core.GridSize,
) -> NormalizedSilhouette:
    """Compare source and LEGO geometry in one source-defined, dimensionless frame.

    The source is translated to its minimum and uniformly scaled to the largest
    source extent.  LEGO placements retain their real 8 mm/stud and 3.2
    mm/plate proportions, then use the same type of uniform scale derived from
    the nominal output envelope.  No individual view is independently fitted.
    """
    if not source_vertices or not source_faces or not placements:
        return _unavailable("source geometry or placements are empty")
    if not all(isfinite(value) for vertex in source_vertices for value in vertex):
        return _unavailable("source geometry contains non-finite coordinates")
    source = _normalize_source(source_vertices)
    lego_boxes, lego_slopes = _normalize_lego(placements, nominal_grid)
    source_masks = _source_masks(source, source_faces)
    lego_masks = _lego_masks(lego_boxes, lego_slopes)
    ious: dict[str, float] = {}
    false_positive: dict[str, int] = {}
    false_negative: dict[str, int] = {}
    for view in _VIEWS:
        source_mask = source_masks[view]
        lego_mask = lego_masks[view]
        ious[view] = binary_mask_iou(source_mask, lego_mask)
        source_values = list(source_mask.get_flattened_data())
        lego_values = list(lego_mask.get_flattened_data())
        false_positive[view] = sum(
            bool(lego_pixel) and not bool(source_pixel)
            for source_pixel, lego_pixel in zip(source_values, lego_values, strict=True)
        )
        false_negative[view] = sum(
            bool(source_pixel) and not bool(lego_pixel)
            for source_pixel, lego_pixel in zip(source_values, lego_values, strict=True)
        )
    return NormalizedSilhouette(
        NORMALIZED_GEOMETRY_VERSION,
        "available",
        None,
        ious["front"],
        ious["side"],
        ious["top"],
        round(sum(ious.values()) / len(ious), 6),
        false_positive,
        false_negative,
    )


def _normalize_source(vertices: Sequence[Point3D]) -> tuple[Point3D, ...]:
    minimum = tuple(min(vertex[axis] for vertex in vertices) for axis in range(3))
    maximum = tuple(max(vertex[axis] for vertex in vertices) for axis in range(3))
    largest_extent = max(maximum[axis] - minimum[axis] for axis in range(3))
    if largest_extent <= 0:
        raise ValueError("Source geometry has no positive extent.")
    return tuple(
        (
            (vertex[0] - minimum[0]) / largest_extent,
            (vertex[1] - minimum[1]) / largest_extent,
            (vertex[2] - minimum[2]) / largest_extent,
        )
        for vertex in vertices
    )


def _normalize_lego(
    placements: Sequence[core.BrickPlacement], nominal_grid: core.GridSize
) -> tuple[tuple[tuple[Point3D, ...], ...], tuple[tuple[Point3D, ...], ...]]:
    envelope = (
        nominal_grid.width_studs * core.STUD_WIDTH_MM,
        nominal_grid.depth_studs * core.STUD_WIDTH_MM,
        nominal_grid.height_plates * core.PLATE_HEIGHT_MM,
    )
    denominator = max(envelope)
    if denominator <= 0:
        raise ValueError("Nominal grid must have positive physical extent.")
    non_slope_placements = tuple(
        placement for placement in placements if placement.brick_type.family != SLOPE_33_FAMILY
    )
    boxes = core._placement_boxes(non_slope_placements)
    normalized_boxes = tuple(
        tuple(
            (x / denominator, y / denominator, z / denominator)
            for x in (box[0] * core.STUD_WIDTH_MM, box[3] * core.STUD_WIDTH_MM)
            for y in (box[1] * core.STUD_WIDTH_MM, box[4] * core.STUD_WIDTH_MM)
            for z in (box[2] * core.PLATE_HEIGHT_MM, box[5] * core.PLATE_HEIGHT_MM)
        )
        for box in boxes
    )
    normalized_slopes = tuple(
        tuple(
            (
                x * core.STUD_WIDTH_MM / denominator,
                y * core.STUD_WIDTH_MM / denominator,
                z * core.PLATE_HEIGHT_MM / denominator,
            )
            for x, y, z in slope
        )
        for slope in core._slope_vertices(tuple(placements))
    )
    return normalized_boxes, normalized_slopes


def _source_masks(
    vertices: Sequence[Point3D], faces: Sequence[tuple[int, int, int]]
) -> dict[str, Image.Image]:
    masks = {view: Image.new("1", (RASTER_RESOLUTION, RASTER_RESOLUTION)) for view in _VIEWS}
    for view, projection in _VIEWS.items():
        draw = ImageDraw.Draw(masks[view])
        for face in faces:
            draw.polygon([_pixel(vertices[index], projection) for index in face], fill=1)
    return masks


def _lego_masks(
    boxes: Sequence[Sequence[Point3D]], slopes: Sequence[Sequence[Point3D]]
) -> dict[str, Image.Image]:
    masks = {view: Image.new("1", (RASTER_RESOLUTION, RASTER_RESOLUTION)) for view in _VIEWS}
    for view, projection in _VIEWS.items():
        draw = ImageDraw.Draw(masks[view])
        first_axis, second_axis = projection
        for box in boxes:
            coordinates = [(vertex[first_axis], vertex[second_axis]) for vertex in box]
            draw.rectangle(
                (
                    min(_pixel_1d(first) for first, _ in coordinates),
                    min(_pixel_1d(second) for _, second in coordinates),
                    max(_pixel_1d(first) for first, _ in coordinates),
                    max(_pixel_1d(second) for _, second in coordinates),
                ),
                fill=1,
            )
        for slope in slopes:
            for face in _SLOPE_PRISM_FACES:
                draw.polygon([_pixel(slope[index], projection) for index in face], fill=1)
    return masks


def _pixel(point: Point3D, projection: tuple[int, int]) -> tuple[int, int]:
    return (
        _pixel_1d(point[projection[0]]),
        RASTER_RESOLUTION - 1 - _pixel_1d(point[projection[1]]),
    )


def _pixel_1d(value: float) -> int:
    return min(RASTER_RESOLUTION - 1, max(0, round(value * (RASTER_RESOLUTION - 1))))


def _unavailable(reason: str) -> NormalizedSilhouette:
    return NormalizedSilhouette(
        NORMALIZED_GEOMETRY_VERSION, "unavailable", reason, None, None, None, None, None, None
    )
