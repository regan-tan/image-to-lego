"""Offline-only utilities for M13B's fixed-reference IoU proxy experiment.

The proxy is a first-order approximation around a completed Control A result.
It is deliberately not an IoU optimizer and is not imported by production code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.conversion import core
from app.conversion.m12c_wedge_fidelity_experiment import _raster_pixels, fixed_frame_score

VIEWS = ("front", "side", "top")
COEFFICIENT_SCALE = 1_000_000
CP_SAT_INT64_LIMIT = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class FixedFrameReference:
    source_foreground: int
    true_positives: int
    false_positives: int

    @property
    def denominator(self) -> int:
        return self.source_foreground + self.false_positives


@dataclass(frozen=True, slots=True)
class ViewObjectiveCoefficients:
    true_positive: int
    false_positive: int


def fixed_frame_references(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Sequence[core.BrickPlacement],
    target_cells: Sequence[core.GridPosition],
) -> dict[str, FixedFrameReference]:
    """Measure source P and Control A's TP/FP in M12C's exact fixed frame."""
    target = frozenset(target_cells)
    if not target:
        raise ValueError("The fixed-frame reference requires at least one target cell.")
    _, _, source = _raster_pixels(source_vertices, faces, (), tuple(placements), target)
    score = fixed_frame_score(source_vertices, faces, placements, target)
    by_view = {view.view: view for view in score.views}
    return {
        view: FixedFrameReference(
            sum(pixel[0] == view for pixel in source),
            by_view[view].true_positives,
            by_view[view].false_positives,
        )
        for view in VIEWS
    }


def derive_coefficients(
    references: Mapping[str, FixedFrameReference], *, scale: int = COEFFICIENT_SCALE
) -> dict[str, ViewObjectiveCoefficients]:
    """Round the fixed-reference gradient with deterministic half-up integer rounding."""
    if scale <= 0:
        raise ValueError("Coefficient scale must be positive.")
    if set(references) != set(VIEWS):
        raise ValueError("References must contain front, side, and top views.")
    coefficients: dict[str, ViewObjectiveCoefficients] = {}
    for view in VIEWS:
        reference = references[view]
        if reference.source_foreground <= 0:
            raise ValueError(f"{view} has an empty source mask; IoU proxy is undefined.")
        denominator = reference.denominator
        if denominator <= 0:
            raise ValueError(f"{view} has a degenerate IoU denominator.")
        coefficients[view] = ViewObjectiveCoefficients(
            _round_half_up(scale, denominator),
            _round_half_up(scale * reference.true_positives, denominator * denominator),
        )
    return coefficients


def solver_view_weights(
    coefficients: Mapping[str, ViewObjectiveCoefficients],
) -> dict[str, tuple[int, int]]:
    """Adapt named M13B coefficients to M12C's optional offline solver seam."""
    return {
        view: (coefficients[view].true_positive, coefficients[view].false_positive)
        for view in VIEWS
    }


def integer_proxy_score(
    references: Mapping[str, FixedFrameReference],
    coefficients: Mapping[str, ViewObjectiveCoefficients],
    measurements: Mapping[str, tuple[int, int]],
) -> int:
    """Score TP/FP measurements with the same frozen reference weights."""
    if (
        set(references) != set(VIEWS)
        or set(coefficients) != set(VIEWS)
        or set(measurements) != set(VIEWS)
    ):
        raise ValueError("Scores must contain front, side, and top views.")
    return sum(
        coefficients[view].true_positive * measurements[view][0]
        - coefficients[view].false_positive * measurements[view][1]
        for view in VIEWS
    )


def validate_coefficient_bounds(
    coefficients: Mapping[str, ViewObjectiveCoefficients],
    *,
    maximum_raster_pixels: int,
    candidate_count: int,
) -> None:
    """Reject coefficient configurations that could overflow CP-SAT signed int64."""
    if maximum_raster_pixels < 0 or candidate_count < 0:
        raise ValueError("Maximum raster pixels and candidate count must not be negative.")
    if set(coefficients) != set(VIEWS):
        raise ValueError("Coefficients must contain front, side, and top views.")
    maximum_weight = max(
        coefficient
        for view in VIEWS
        for coefficient in (
            coefficients[view].true_positive,
            coefficients[view].false_positive,
        )
    )
    # A deliberately conservative bound: every variable pixel may contribute
    # the largest coefficient, and the tie-break is multiplied by candidates + 1.
    maximum_objective = maximum_raster_pixels * maximum_weight * (candidate_count + 1)
    if maximum_objective > CP_SAT_INT64_LIMIT:
        raise ValueError("IoU proxy coefficients exceed the CP-SAT signed int64 limit.")


def iou(true_positives: int, false_positives: int, source_foreground: int) -> float:
    if min(true_positives, false_positives, source_foreground) < 0:
        raise ValueError("IoU counts must not be negative.")
    denominator = source_foreground + false_positives
    if denominator == 0:
        return 1.0
    return true_positives / denominator


def improves_reference_iou(
    *,
    true_positives: int,
    false_positives: int,
    reference_iou: float,
    source_foreground: int,
) -> bool:
    """Use TP_new - r FP_new > r P, equivalent to IoU_new > r for fixed P."""
    return true_positives - reference_iou * false_positives > reference_iou * source_foreground


def finite_difference_gradients(reference: FixedFrameReference) -> tuple[float, float]:
    """Return the independently calculated analytic finite-difference limit."""
    denominator = reference.denominator
    if denominator <= 0:
        raise ValueError("The reference denominator must be positive.")
    return 1 / denominator, -reference.true_positives / (denominator * denominator)


def _round_half_up(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(numerator, denominator)
    return quotient + (2 * remainder >= denominator)
