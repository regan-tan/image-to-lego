"""Independent, deterministic gates for the M13A diagnostic utility."""

from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.m13a_objective_alignment_audit import (
    combined_native_bounds,
    evaluate_native,
    evaluate_shared_bounds,
    score_counts,
)
from app.conversion.part_catalogue import PART_BY_ID


def test_summed_tp_minus_fp_can_rise_while_mean_iou_falls() -> None:
    # Independently specified counts: view one gains 11 pixels, but view two
    # loses all 10 source pixels.  The equal-weight mean falls despite the
    # pixel-count objective rising from 70 to 71.
    previous = (score_counts(50, 0, 50), score_counts(10, 0, 0), score_counts(10, 0, 0))
    current = (score_counts(61, 0, 39), score_counts(0, 0, 10), score_counts(10, 0, 0))
    assert sum(view.tp_minus_fp for view in current) == 71
    assert sum(view.tp_minus_fp for view in previous) == 70
    assert sum(view.iou for view in current) / 3 < sum(view.iou for view in previous) / 3


def test_one_view_tp_minus_fp_can_rise_while_fixed_frame_iou_falls() -> None:
    # M13A's original algebra incorrectly excluded this case.  FP falls by 11
    # but TP falls by 10, increasing TP-FP while worsening IoU.
    previous = score_counts(90, 50, 10)
    current = score_counts(80, 39, 20)
    assert current.tp_minus_fp > previous.tp_minus_fp
    assert current.iou < previous.iou


def test_native_bounds_change_when_completed_lego_extent_changes() -> None:
    source = _cube_vertices(0.0, 1.0)
    near = (BrickPlacement(PART_BY_ID["3024"], GridPosition(0, 0, 0), 0),)
    extended = (*near, BrickPlacement(PART_BY_ID["3024"], GridPosition(8, 0, 0), 0))
    assert (
        evaluate_native(source, _cube_faces(), near).bounds
        != evaluate_native(source, _cube_faces(), extended).bounds
    )


def test_shared_bounds_keep_an_unchanged_assembly_exactly_reproducible() -> None:
    source = _cube_vertices(0.0, 1.0)
    assembly = (BrickPlacement(PART_BY_ID["3024"], GridPosition(0, 0, 0), 0),)
    bounds = combined_native_bounds(source, assembly, assembly)
    first = evaluate_shared_bounds(source, _cube_faces(), assembly, bounds)
    second = evaluate_shared_bounds(source, _cube_faces(), assembly, bounds)
    assert first == second


def test_actual_wedge_geometry_is_not_its_rectangular_envelope() -> None:
    source = _cube_vertices(0.0, 1.0)
    wedge = (BrickPlacement(PART_BY_ID["41769"], GridPosition(0, 0, 0), 0),)
    box = (BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0),)
    bounds = combined_native_bounds(source, wedge, box)
    wedge_metrics = evaluate_shared_bounds(source, _cube_faces(), wedge, bounds)
    box_metrics = evaluate_shared_bounds(source, _cube_faces(), box, bounds)
    assert wedge_metrics.top.false_positives != box_metrics.top.false_positives


def test_native_rounding_matches_explicit_native_bounds_for_a_fractional_source() -> None:
    source = tuple((x + 0.25, y + 0.25, z + 0.25) for x, y, z in _cube_vertices(0.0, 1.0))
    wedge = (BrickPlacement(PART_BY_ID["41769"], GridPosition(0, 0, 0), 0),)
    native = evaluate_native(source, _cube_faces(), wedge)
    explicit = evaluate_shared_bounds(
        source,
        _cube_faces(),
        wedge,
        dict(native.bounds),
    )
    assert explicit.front == native.front
    assert explicit.side == native.side
    assert explicit.top == native.top


def _cube_vertices(minimum: float, maximum: float) -> tuple[tuple[float, float, float], ...]:
    return (
        (minimum, minimum, minimum),
        (maximum, minimum, minimum),
        (maximum, maximum, minimum),
        (minimum, maximum, minimum),
        (minimum, minimum, maximum),
        (maximum, minimum, maximum),
        (maximum, maximum, maximum),
        (minimum, maximum, maximum),
    )


def _cube_faces() -> tuple[tuple[int, int, int], ...]:
    return ((0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6))
