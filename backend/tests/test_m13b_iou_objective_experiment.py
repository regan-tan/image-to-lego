from __future__ import annotations

import pytest

from app.conversion import core
from app.conversion.m12c_wedge_fidelity_experiment import optimise_with_wedge
from app.conversion.m13b_iou_objective_experiment import (
    CP_SAT_INT64_LIMIT,
    FixedFrameReference,
    ViewObjectiveCoefficients,
    derive_coefficients,
    finite_difference_gradients,
    improves_reference_iou,
    integer_proxy_score,
    iou,
    validate_coefficient_bounds,
)


def test_one_view_tp_minus_fp_counterexample_lowers_iou() -> None:
    # This is the M13A correction: raw TP-FP rises from 40 to 41, while the
    # fixed-frame IoU falls because TP and FP both fall.
    assert 80 - 39 > 90 - 50
    assert iou(80, 39, 100) < iou(90, 50, 100)


def test_reference_iou_inequality_is_equivalent_to_direct_iou_comparison() -> None:
    source_foreground = 100
    reference_iou = iou(90, 50, source_foreground)
    for true_positives, false_positives in ((90, 50), (91, 52), (80, 39), (100, 70)):
        assert improves_reference_iou(
            true_positives=true_positives,
            false_positives=false_positives,
            reference_iou=reference_iou,
            source_foreground=source_foreground,
        ) == (iou(true_positives, false_positives, source_foreground) > reference_iou)


def test_gradient_matches_independent_finite_differences() -> None:
    reference = FixedFrameReference(100, 90, 50)
    tp_gradient, fp_gradient = finite_difference_gradients(reference)
    epsilon = 1e-4
    reference_iou = iou(90, 50, 100)
    assert ((90 + epsilon) / 150 - reference_iou) / epsilon == pytest.approx(tp_gradient, rel=1e-5)
    assert (90 / (150 + epsilon) - reference_iou) / epsilon == pytest.approx(fp_gradient, rel=1e-5)


def test_proxy_uses_unequal_view_contributions() -> None:
    references = _references((100, 90, 50), (10, 5, 0), (10, 5, 0))
    coefficients = derive_coefficients(references)
    assert coefficients["front"].true_positive < coefficients["side"].true_positive


def test_proxy_can_improve_mean_iou() -> None:
    references = _references((100, 50, 50), (100, 50, 50), (100, 50, 50))
    coefficients = derive_coefficients(references)
    control = {view: (50, 50) for view in references}
    candidate = {view: (51, 49) for view in references}
    assert integer_proxy_score(references, coefficients, candidate) > integer_proxy_score(
        references, coefficients, control
    )
    assert _mean_iou(references, candidate) > _mean_iou(references, control)


def test_proxy_can_fail_to_improve_actual_mean_iou() -> None:
    references = _references((100, 90, 50), (10, 5, 0), (10, 5, 0))
    coefficients = derive_coefficients(references)
    control = {
        view: (reference.true_positives, reference.false_positives)
        for view, reference in references.items()
    }
    candidate = {"front": (0, 0), "side": (5, 0), "top": (10, 0)}
    assert integer_proxy_score(references, coefficients, candidate) > integer_proxy_score(
        references, coefficients, control
    )
    assert _mean_iou(references, candidate) < _mean_iou(references, control)


def test_half_up_rounding_and_coefficients_are_deterministic() -> None:
    references = _references((4, 2, 0), (4, 2, 0), (4, 2, 0))
    first = derive_coefficients(references, scale=10)
    assert first == derive_coefficients(references, scale=10)
    assert first["front"].true_positive == 3


def test_overflow_and_empty_masks_are_rejected() -> None:
    coefficients = {
        view: ViewObjectiveCoefficients(CP_SAT_INT64_LIMIT, CP_SAT_INT64_LIMIT)
        for view in ("front", "side", "top")
    }
    with pytest.raises(ValueError, match="int64"):
        validate_coefficient_bounds(coefficients, maximum_raster_pixels=2, candidate_count=1)
    with pytest.raises(ValueError, match="empty source"):
        derive_coefficients(_references((0, 0, 0), (1, 0, 0), (1, 0, 0)))


def test_equal_weights_reproduce_m12c_default_for_a_deterministic_fixture() -> None:
    target = frozenset(core.GridPosition(x, 0, 0) for x in range(2))
    kwargs = {
        "source_vertices": ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        "faces": ((0, 1, 2),),
        "target_cells": target,
        "required_pixels": (),
        "locked_placements": (),
        "max_parts": 2,
        "include_wedges": False,
    }
    baseline = optimise_with_wedge(**kwargs)
    weighted = optimise_with_wedge(
        **kwargs,
        view_objective_weights={view: (1, 1) for view in ("front", "side", "top")},
    )
    assert weighted.placements == baseline.placements
    assert weighted.objective_value == baseline.objective_value


def _references(
    front: tuple[int, int, int], side: tuple[int, int, int], top: tuple[int, int, int]
) -> dict[str, FixedFrameReference]:
    return {
        view: FixedFrameReference(*values)
        for view, values in zip(("front", "side", "top"), (front, side, top), strict=True)
    }


def _mean_iou(
    references: dict[str, FixedFrameReference], measurements: dict[str, tuple[int, int]]
) -> float:
    return (
        sum(
            iou(*measurements[view], references[view].source_foreground)
            for view in ("front", "side", "top")
        )
        / 3
    )
