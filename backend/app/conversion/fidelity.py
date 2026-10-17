"""Deterministic orthographic silhouette metrics for completed LEGO models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from PIL import Image, ImageDraw

SILHOUETTE_METRICS_VERSION = "silhouette-v1"
SILHOUETTE_RESOLUTION = 128
METRIC_PRECISION = 6
PROJECTION_PADDING_RATIO = 0.01

Point3D = tuple[float, float, float]
Box = tuple[float, float, float, float, float, float]
Projection = tuple[int, int]
SlopeVertices = tuple[Point3D, ...]
WedgeVertices = tuple[Point3D, ...]

_SLOPE_PRISM_FACES = (
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
class FidelityMetrics:
    metrics_version: str
    raster_resolution: int
    front_iou: float
    side_iou: float
    top_iou: float
    mean_iou: float
    target_parts: int
    actual_parts: int
    part_count_delta: int
    part_count_error_ratio: float


def evaluate_fidelity(
    source_vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    lego_boxes: Sequence[Box],
    *,
    target_parts: int,
    slope_vertices: Sequence[SlopeVertices] = (),
    wedge_vertices: Sequence[WedgeVertices] = (),
) -> FidelityMetrics:
    """Measure a source mesh and completed LEGO solids in their shared grid space."""
    masks = render_silhouette_masks(
        source_vertices,
        faces,
        lego_boxes,
        slope_vertices=slope_vertices,
        wedge_vertices=wedge_vertices,
    )
    front_iou = binary_mask_iou(*masks["front"])
    side_iou = binary_mask_iou(*masks["side"])
    top_iou = binary_mask_iou(*masks["top"])
    actual_parts = len(lego_boxes) + len(slope_vertices) + len(wedge_vertices)
    part_count_delta = actual_parts - target_parts
    return FidelityMetrics(
        metrics_version=SILHOUETTE_METRICS_VERSION,
        raster_resolution=SILHOUETTE_RESOLUTION,
        front_iou=front_iou,
        side_iou=side_iou,
        top_iou=top_iou,
        mean_iou=_round_metric((front_iou + side_iou + top_iou) / 3),
        target_parts=target_parts,
        actual_parts=actual_parts,
        part_count_delta=part_count_delta,
        part_count_error_ratio=_round_metric(abs(part_count_delta) / target_parts),
    )


def render_silhouette_masks(
    source_vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    lego_boxes: Sequence[Box],
    *,
    slope_vertices: Sequence[SlopeVertices] = (),
    wedge_vertices: Sequence[WedgeVertices] = (),
) -> dict[str, tuple[Image.Image, Image.Image]]:
    """Rasterize target and output masks using the canonical silhouette-v1 views.

    The returned masks share bounds within each view and are intended for
    diagnostics that need the same geometry that ``evaluate_fidelity`` scores.
    """
    return {
        "front": _projection_masks(
            source_vertices, faces, lego_boxes, slope_vertices, wedge_vertices, (0, 2)
        ),
        "side": _projection_masks(
            source_vertices, faces, lego_boxes, slope_vertices, wedge_vertices, (1, 2)
        ),
        "top": _projection_masks(
            source_vertices, faces, lego_boxes, slope_vertices, wedge_vertices, (0, 1)
        ),
    }


def binary_mask_iou(first: Image.Image, second: Image.Image) -> float:
    """Return IoU for same-size binary masks, including deterministic empty-mask handling."""
    if first.size != second.size:
        raise ValueError("Binary masks must have the same dimensions.")
    intersection = 0
    union = 0
    for first_pixel, second_pixel in zip(
        first.get_flattened_data(), second.get_flattened_data(), strict=True
    ):
        first_filled = bool(first_pixel)
        second_filled = bool(second_pixel)
        if first_filled and second_filled:
            intersection += 1
        if first_filled or second_filled:
            union += 1
    return 1.0 if union == 0 else _round_metric(intersection / union)


def _projection_iou(
    source_vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    lego_boxes: Sequence[Box],
    slope_vertices: Sequence[SlopeVertices],
    wedge_vertices: Sequence[WedgeVertices],
    projection: Projection,
) -> float:
    return binary_mask_iou(
        *_projection_masks(
            source_vertices, faces, lego_boxes, slope_vertices, wedge_vertices, projection
        )
    )


def _projection_masks(
    source_vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    lego_boxes: Sequence[Box],
    slope_vertices: Sequence[SlopeVertices],
    wedge_vertices: Sequence[WedgeVertices],
    projection: Projection,
) -> tuple[Image.Image, Image.Image]:
    bounds = _projection_bounds(
        source_vertices, lego_boxes, slope_vertices, wedge_vertices, projection
    )
    source_mask = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
    lego_mask = Image.new("1", (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION))
    _draw_source_triangles(source_mask, source_vertices, faces, projection, bounds)
    _draw_lego_boxes(lego_mask, lego_boxes, projection, bounds)
    _draw_lego_slopes(lego_mask, slope_vertices, projection, bounds)
    _draw_lego_wedges(lego_mask, wedge_vertices, projection, bounds)
    return source_mask, lego_mask


def _projection_bounds(
    source_vertices: Sequence[Point3D],
    lego_boxes: Sequence[Box],
    slope_vertices: Sequence[SlopeVertices],
    wedge_vertices: Sequence[WedgeVertices],
    projection: Projection,
) -> tuple[float, float, float, float]:
    first_axis, second_axis = projection
    coordinates = [(vertex[first_axis], vertex[second_axis]) for vertex in source_vertices]
    for box in lego_boxes:
        minimum = (box[0], box[1], box[2])
        maximum = (box[3], box[4], box[5])
        coordinates.extend(
            (first, second)
            for first in (minimum[first_axis], maximum[first_axis])
            for second in (minimum[second_axis], maximum[second_axis])
        )
    for slope in slope_vertices:
        coordinates.extend((vertex[first_axis], vertex[second_axis]) for vertex in slope)
    for wedge in wedge_vertices:
        coordinates.extend((vertex[first_axis], vertex[second_axis]) for vertex in wedge)
    if not coordinates:
        return (0.0, 1.0, 0.0, 1.0)
    minimum_first = min(point[0] for point in coordinates)
    maximum_first = max(point[0] for point in coordinates)
    minimum_second = min(point[1] for point in coordinates)
    maximum_second = max(point[1] for point in coordinates)
    first_padding = max((maximum_first - minimum_first) * PROJECTION_PADDING_RATIO, 1e-9)
    second_padding = max((maximum_second - minimum_second) * PROJECTION_PADDING_RATIO, 1e-9)
    return (
        minimum_first - first_padding,
        maximum_first + first_padding,
        minimum_second - second_padding,
        maximum_second + second_padding,
    )


def _draw_source_triangles(
    mask: Image.Image,
    vertices: Sequence[Point3D],
    faces: Sequence[tuple[int, int, int]],
    projection: Projection,
    bounds: tuple[float, float, float, float],
) -> None:
    draw = ImageDraw.Draw(mask)
    for face in faces:
        triangle = [vertices[index] for index in face]
        draw.polygon([_to_pixel(vertex, projection, bounds) for vertex in triangle], fill=1)


def _draw_lego_boxes(
    mask: Image.Image,
    lego_boxes: Sequence[Box],
    projection: Projection,
    bounds: tuple[float, float, float, float],
) -> None:
    draw = ImageDraw.Draw(mask)
    first_axis, second_axis = projection
    for box in lego_boxes:
        minimum = (box[0], box[1], box[2])
        maximum = (box[3], box[4], box[5])
        first = _to_pixel(minimum, projection, bounds)
        second = _to_pixel(maximum, projection, bounds)
        left, right = sorted((first[0], second[0]))
        top, bottom = sorted((first[1], second[1]))
        draw.rectangle((left, top, right, bottom), fill=1)


def _draw_lego_slopes(
    mask: Image.Image,
    slope_vertices: Sequence[SlopeVertices],
    projection: Projection,
    bounds: tuple[float, float, float, float],
) -> None:
    draw = ImageDraw.Draw(mask)
    for slope in slope_vertices:
        for face in _SLOPE_PRISM_FACES:
            draw.polygon([_to_pixel(slope[index], projection, bounds) for index in face], fill=1)


def _draw_lego_wedges(
    mask: Image.Image,
    wedge_vertices: Sequence[WedgeVertices],
    projection: Projection,
    bounds: tuple[float, float, float, float],
) -> None:
    draw = ImageDraw.Draw(mask)
    for wedge in wedge_vertices:
        half = len(wedge) // 2
        draw.polygon([_to_pixel(vertex, projection, bounds) for vertex in wedge[:half]], fill=1)
        draw.polygon([_to_pixel(vertex, projection, bounds) for vertex in wedge[half:]], fill=1)


def _to_pixel(
    point: Point3D, projection: Projection, bounds: tuple[float, float, float, float]
) -> tuple[int, int]:
    minimum_first, maximum_first, minimum_second, maximum_second = bounds
    first_axis, second_axis = projection
    first = _scaled_pixel(point[first_axis], minimum_first, maximum_first)
    # Images grow downward, so the projection's second coordinate is deliberately flipped.
    second = (
        SILHOUETTE_RESOLUTION
        - 1
        - _scaled_pixel(point[second_axis], minimum_second, maximum_second)
    )
    return first, second


def _scaled_pixel(value: float, minimum: float, maximum: float) -> int:
    if not isfinite(value):
        raise ValueError("Projection coordinates must be finite.")
    normalized = (value - minimum) / (maximum - minimum)
    pixel = round(normalized * (SILHOUETTE_RESOLUTION - 1))
    return min(SILHOUETTE_RESOLUTION - 1, max(0, pixel))


def _round_metric(value: float) -> float:
    return round(value, METRIC_PRECISION)
