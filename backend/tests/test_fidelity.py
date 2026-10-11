from PIL import Image

import app.conversion.core as converter_core
from app.conversion.core import BRICK_CATALOGUE, BrickPlacement, GridPosition
from app.conversion.fidelity import (
    METRIC_PRECISION,
    SILHOUETTE_RESOLUTION,
    binary_mask_iou,
    evaluate_fidelity,
)


def mask(points: set[tuple[int, int]]) -> Image.Image:
    result = Image.new("1", (4, 4))
    for point in points:
        result.putpixel(point, 1)
    return result


def rectangular_prism(
    maximum: tuple[float, float, float]
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    x, y, z = maximum
    vertices = [
        (0.0, 0.0, 0.0),
        (x, 0.0, 0.0),
        (x, y, 0.0),
        (0.0, y, 0.0),
        (0.0, 0.0, z),
        (x, 0.0, z),
        (x, y, z),
        (0.0, y, z),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    ]
    return vertices, faces


def test_binary_mask_iou_handles_identical_disjoint_partial_and_empty_masks() -> None:
    first = mask({(0, 0), (1, 0)})
    assert binary_mask_iou(first, first) == 1.0
    assert binary_mask_iou(first, mask({(3, 3)})) == 0.0
    assert binary_mask_iou(first, mask({(1, 0), (2, 0)})) == 0.333333
    assert binary_mask_iou(mask(set()), mask(set())) == 1.0
    assert binary_mask_iou(mask(set()), first) == 0.0


def test_equivalent_shape_has_higher_iou_than_coarse_shape() -> None:
    vertices, faces = rectangular_prism((4.0, 2.0, 1.0))
    close = evaluate_fidelity(
        vertices, faces, [(0.0, 0.0, 0.0, 4.0, 2.0, 1.0)], target_parts=1
    )
    coarse = evaluate_fidelity(
        vertices, faces, [(0.0, 0.0, 0.0, 2.0, 2.0, 1.0)], target_parts=1
    )

    assert all(0.0 <= value <= 1.0 for value in (close.front_iou, close.side_iou, close.top_iou))
    assert close.mean_iou > coarse.mean_iou
    assert close.mean_iou == round(
        (close.front_iou + close.side_iou + close.top_iou) / 3, METRIC_PRECISION
    )
    assert close.raster_resolution == SILHOUETTE_RESOLUTION


def test_l_shaped_source_scores_higher_for_a_matching_lego_outline() -> None:
    first_vertices, first_faces = rectangular_prism((4.0, 1.0, 1.0))
    second_vertices, second_faces = rectangular_prism((1.0, 3.0, 1.0))
    source_vertices = first_vertices + second_vertices
    offset = len(first_vertices)
    source_faces = first_faces + [
        (face[0] + offset, face[1] + offset, face[2] + offset) for face in second_faces
    ]
    matching = evaluate_fidelity(
        source_vertices,
        source_faces,
        [(0.0, 0.0, 0.0, 4.0, 1.0, 1.0), (0.0, 0.0, 0.0, 1.0, 3.0, 1.0)],
        target_parts=2,
    )
    rectangular = evaluate_fidelity(
        source_vertices, source_faces, [(0.0, 0.0, 0.0, 4.0, 3.0, 1.0)], target_parts=1
    )

    assert matching.top_iou > rectangular.top_iou
    assert matching.part_count_error_ratio == 0.0


def test_orientation_changes_the_lego_box_footprint() -> None:
    brick = BRICK_CATALOGUE[0]
    unrotated = BrickPlacement(brick, GridPosition(0, 0, 0), 0)
    rotated = BrickPlacement(brick, GridPosition(0, 0, 0), 90)

    assert converter_core._placement_boxes((unrotated,)) == (
        (0.0, 0.0, 0.0, 4.0, 2.0, 1.0),
    )
    assert converter_core._placement_boxes((rotated,)) == ((0.0, 0.0, 0.0, 2.0, 4.0, 1.0),)
