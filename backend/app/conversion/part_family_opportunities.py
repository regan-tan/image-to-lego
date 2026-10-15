"""Deterministic silhouette-residual classification for part-family planning.

This diagnostic does not estimate a future IoU.  It classifies the visible
silhouette error left by the current vocabulary, one connected residual region
at a time, so its evidence totals remain directly auditable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from PIL import Image

from app.conversion.fidelity import binary_mask_iou

VIEW_NAMES: Final = ("front", "side", "top")
MIN_FEATURE_SPAN: Final = 5
SMALL_DETAIL_MAX_PIXELS: Final = 12
LINEARITY_MINIMUM: Final = 0.92
CURVE_DIRECTION_CHANGES_MINIMUM: Final = 1


class OpportunityFamily(StrEnum):
    ADDITIONAL_SLOPE = "additional_slope"
    WEDGE = "wedge"
    CURVED_SLOPE = "curved_slope"
    ROUND = "round"
    INVERTED_SLOPE = "inverted_slope"
    CORNER_FACET = "corner_facet"
    RESOLUTION_LIMITED = "resolution_limited"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class ViewResidual:
    view: str
    false_negative_pixels: int
    false_positive_pixels: int
    disagreement_pixels: int
    iou: float
    boundary_disagreement_pixels: int


@dataclass(frozen=True, slots=True)
class OpportunityEvidence:
    family: OpportunityFamily
    view: str
    residual_pixels: int
    false_negative_pixels: int
    false_positive_pixels: int
    confidence: float
    signal: str


@dataclass(frozen=True, slots=True)
class OpportunityReport:
    views: tuple[ViewResidual, ...]
    evidence: tuple[OpportunityEvidence, ...]

    @property
    def total_disagreement_pixels(self) -> int:
        return sum(view.disagreement_pixels for view in self.views)

    def family_pixels(self) -> dict[OpportunityFamily, int]:
        totals: Counter[OpportunityFamily] = Counter()
        for item in self.evidence:
            totals[item.family] += item.residual_pixels
        return dict(totals)


def analyze_part_family_opportunities(
    masks: dict[str, tuple[Image.Image, Image.Image]],
) -> OpportunityReport:
    """Classify each silhouette-v1 residual component exactly once.

    ``front`` and ``side`` are vertical views; ``top`` is the horizontal
    footprint.  Components with only a few raster pixels are kept separate as
    resolution-limited evidence instead of being promoted to a shape family.
    """
    if tuple(sorted(masks)) != VIEW_NAMES:
        raise ValueError("Masks must contain front, side, and top views.")

    views: list[ViewResidual] = []
    evidence: list[OpportunityEvidence] = []
    for view in VIEW_NAMES:
        target, output = masks[view]
        _validate_masks(target, output)
        false_negative, false_positive = _residual_sets(target, output)
        disagreement = false_negative | false_positive
        views.append(
            ViewResidual(
                view=view,
                false_negative_pixels=len(false_negative),
                false_positive_pixels=len(false_positive),
                disagreement_pixels=len(disagreement),
                iou=binary_mask_iou(target, output),
                boundary_disagreement_pixels=_boundary_disagreement(disagreement),
            )
        )
        for component in _components(disagreement):
            family, confidence, signal = _classify_component(target, component, view)
            evidence.append(
                OpportunityEvidence(
                    family=family,
                    view=view,
                    residual_pixels=len(component),
                    false_negative_pixels=len(component & false_negative),
                    false_positive_pixels=len(component & false_positive),
                    confidence=confidence,
                    signal=signal,
                )
            )
    return OpportunityReport(tuple(views), tuple(evidence))


def _validate_masks(target: Image.Image, output: Image.Image) -> None:
    if target.size != output.size:
        raise ValueError("Target and output masks must have matching sizes.")


def _residual_sets(
    target: Image.Image, output: Image.Image
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    false_negative: set[tuple[int, int]] = set()
    false_positive: set[tuple[int, int]] = set()
    for y in range(target.height):
        for x in range(target.width):
            target_filled = bool(target.getpixel((x, y)))
            output_filled = bool(output.getpixel((x, y)))
            if target_filled and not output_filled:
                false_negative.add((x, y))
            elif output_filled and not target_filled:
                false_positive.add((x, y))
    return false_negative, false_positive


def _components(pixels: set[tuple[int, int]]) -> tuple[frozenset[tuple[int, int]], ...]:
    remaining = set(pixels)
    components: list[frozenset[tuple[int, int]]] = []
    while remaining:
        start = min(remaining, key=lambda point: (point[1], point[0]))
        pending = [start]
        component: set[tuple[int, int]] = set()
        remaining.remove(start)
        while pending:
            point = pending.pop()
            component.add(point)
            for neighbor in _neighbors(point):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        components.append(frozenset(component))
    return tuple(components)


def _neighbors(point: tuple[int, int]) -> tuple[tuple[int, int], ...]:
    x, y = point
    return tuple(
        (x + x_offset, y + y_offset)
        for y_offset in (-1, 0, 1)
        for x_offset in (-1, 0, 1)
        if x_offset or y_offset
    )


def _boundary_disagreement(disagreement: set[tuple[int, int]]) -> int:
    return sum(
        any(neighbor not in disagreement for neighbor in _neighbors(point))
        for point in disagreement
    )


def _classify_component(
    target: Image.Image,
    component: frozenset[tuple[int, int]],
    view: str,
) -> tuple[OpportunityFamily, float, str]:
    if len(component) <= SMALL_DETAIL_MAX_PIXELS:
        return OpportunityFamily.RESOLUTION_LIMITED, 1.0, "small_residual"

    left, right, top, bottom = _expanded_bounds(component, target.size)
    local_rows = _target_edge_profiles(target, left, right, top, bottom)
    if _has_concavity(local_rows):
        return OpportunityFamily.INVERTED_SLOPE, 0.8, "multiple_target_spans"

    line_score = _best_linearity(local_rows)
    if line_score is not None and line_score[0] >= LINEARITY_MINIMUM:
        confidence = min(1.0, 0.55 + line_score[0] * 0.45)
        if view == "top":
            return OpportunityFamily.WEDGE, confidence, "straight_diagonal_horizontal_boundary"
        return OpportunityFamily.ADDITIONAL_SLOPE, confidence, "straight_diagonal_vertical_boundary"

    curve_changes = _curve_slope_changes(local_rows)
    if curve_changes >= CURVE_DIRECTION_CHANGES_MINIMUM:
        if view == "top":
            return OpportunityFamily.ROUND, 0.7, "curved_horizontal_boundary"
        return OpportunityFamily.CURVED_SLOPE, 0.7, "curved_vertical_boundary"

    if _has_two_axis_extent(component):
        return OpportunityFamily.CORNER_FACET, 0.45, "multi_axis_residual_without_strong_profile"
    return OpportunityFamily.UNCLASSIFIED, 0.2, "insufficient_shape_signal"


def _expanded_bounds(
    component: frozenset[tuple[int, int]], size: tuple[int, int]
) -> tuple[int, int, int, int]:
    xs = [point[0] for point in component]
    ys = [point[1] for point in component]
    return (
        max(0, min(xs) - 1),
        min(size[0] - 1, max(xs) + 1),
        max(0, min(ys) - 1),
        min(size[1] - 1, max(ys) + 1),
    )


def _target_edge_profiles(
    target: Image.Image, left: int, right: int, top: int, bottom: int
) -> tuple[tuple[int, int, int, int], ...]:
    profiles: list[tuple[int, int, int, int]] = []
    for y in range(top, bottom + 1):
        filled = [x for x in range(left, right + 1) if bool(target.getpixel((x, y)))]
        if filled:
            span_count = sum(
                previous + 1 != current
                for previous, current in zip(filled, filled[1:], strict=False)
            ) + 1
            profiles.append((y, min(filled), max(filled), span_count))
    return tuple(profiles)


def _has_concavity(profiles: tuple[tuple[int, int, int, int], ...]) -> bool:
    if len(profiles) < MIN_FEATURE_SPAN:
        return False
    return any(span_count > 1 for _, _, _, span_count in profiles)


def _best_linearity(
    profiles: tuple[tuple[int, int, int, int], ...]
) -> tuple[float, float] | None:
    if len(profiles) < MIN_FEATURE_SPAN:
        return None
    scores = (
        _linearity(tuple((y, left) for y, left, _, _ in profiles)),
        _linearity(tuple((y, right) for y, _, right, _ in profiles)),
    )
    valid = [score for score in scores if score is not None and abs(score[1]) >= 0.15]
    return max(valid, default=None)


def _linearity(points: tuple[tuple[int, int], ...]) -> tuple[float, float] | None:
    count = len(points)
    mean_x = sum(point[0] for point in points) / count
    mean_y = sum(point[1] for point in points) / count
    variance_x = sum((point[0] - mean_x) ** 2 for point in points)
    if variance_x == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance_x
    variance_y = sum((y - mean_y) ** 2 for _, y in points)
    if variance_y == 0:
        return (1.0, slope)
    residual = sum((y - (mean_y + slope * (x - mean_x))) ** 2 for x, y in points)
    return (max(0.0, 1.0 - residual / variance_y), slope)


def _curve_slope_changes(profiles: tuple[tuple[int, int, int, int], ...]) -> int:
    if len(profiles) < MIN_FEATURE_SPAN:
        return 0
    changes = 0
    for edge_index in (1, 2):
        values = [profile[edge_index] for profile in profiles]
        slopes = [
            right - left for left, right in zip(values, values[1:], strict=False)
        ]
        compact = [slope for slope in slopes if slope]
        changes = max(
            changes,
            sum(left != right for left, right in zip(compact, compact[1:], strict=False)),
        )
    return changes


def _has_two_axis_extent(component: frozenset[tuple[int, int]]) -> bool:
    xs = [point[0] for point in component]
    ys = [point[1] for point in component]
    return max(xs) - min(xs) >= MIN_FEATURE_SPAN and max(ys) - min(ys) >= MIN_FEATURE_SPAN
