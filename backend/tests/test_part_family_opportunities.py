from __future__ import annotations

from PIL import Image, ImageDraw

from app.conversion.part_family_opportunities import (
    OpportunityFamily,
    OpportunityReport,
    analyze_part_family_opportunities,
)

MASK_SIZE = (32, 32)


def test_axis_aligned_rectangle_has_no_shape_family_opportunity() -> None:
    rectangle = _polygon(((6, 6), (25, 6), (25, 25), (6, 25)))

    report = analyze_part_family_opportunities(_views(rectangle, rectangle))

    assert not report.evidence


def test_diagonal_vertical_boundary_is_additional_slope_evidence() -> None:
    target = _polygon(((4, 27), (27, 27), (27, 4)))
    output = _polygon(((4, 4), (27, 4), (27, 27), (4, 27)))

    report = analyze_part_family_opportunities(_views(target, output))

    assert _families(report, "front") == {OpportunityFamily.ADDITIONAL_SLOPE}


def test_diagonal_top_boundary_is_wedge_evidence() -> None:
    target = _polygon(((4, 27), (27, 27), (27, 4)))
    output = _polygon(((4, 4), (27, 4), (27, 27), (4, 27)))

    report = analyze_part_family_opportunities(_views(_blank(), _blank(), top=(target, output)))

    assert _families(report, "top") == {OpportunityFamily.WEDGE}


def test_smooth_convex_vertical_boundary_is_curved_slope_evidence() -> None:
    target = _ellipse((4, 4, 27, 27))
    output = _polygon(((4, 4), (27, 4), (27, 27), (4, 27)))

    report = analyze_part_family_opportunities(_views(target, output))

    assert _families(report, "front") == {OpportunityFamily.CURVED_SLOPE}


def test_concave_vertical_shape_is_inverted_slope_evidence() -> None:
    target = _blank()
    draw = ImageDraw.Draw(target)
    draw.rectangle((4, 4, 27, 9), fill=1)
    draw.rectangle((4, 4, 9, 27), fill=1)
    draw.rectangle((22, 4, 27, 27), fill=1)
    output = _polygon(((4, 4), (27, 4), (27, 27), (4, 27)))

    report = analyze_part_family_opportunities(_views(target, output))

    assert _families(report, "front") == {OpportunityFamily.INVERTED_SLOPE}


def test_small_detail_is_resolution_limited_not_new_family_evidence() -> None:
    target = _blank()
    ImageDraw.Draw(target).rectangle((10, 10, 12, 12), fill=1)

    report = analyze_part_family_opportunities(_views(target, _blank()))

    assert _families(report, "front") == {OpportunityFamily.RESOLUTION_LIMITED}


def test_weak_ambiguous_residual_remains_unclassified() -> None:
    target = _blank()
    ImageDraw.Draw(target).line((4, 16, 22, 16), fill=1)

    report = analyze_part_family_opportunities(_views(target, _blank()))

    assert _families(report, "front") == {OpportunityFamily.UNCLASSIFIED}


def test_same_masks_produce_identical_report() -> None:
    target = _polygon(((4, 27), (27, 27), (27, 4)))
    output = _polygon(((4, 4), (27, 4), (27, 27), (4, 27)))
    masks = _views(target, output)

    assert analyze_part_family_opportunities(masks) == analyze_part_family_opportunities(masks)


def _views(
    front_target: Image.Image,
    front_output: Image.Image,
    *,
    top: tuple[Image.Image, Image.Image] | None = None,
) -> dict[str, tuple[Image.Image, Image.Image]]:
    blank = _blank()
    return {
        "front": (front_target, front_output),
        "side": (blank, blank),
        "top": top if top is not None else (blank, blank),
    }


def _families(report: OpportunityReport, view: str) -> set[OpportunityFamily]:
    return {item.family for item in report.evidence if item.view == view}


def _blank() -> Image.Image:
    return Image.new("1", MASK_SIZE)


def _polygon(points: tuple[tuple[int, int], ...]) -> Image.Image:
    image = _blank()
    ImageDraw.Draw(image).polygon(points, fill=1)
    return image


def _ellipse(bounds: tuple[int, int, int, int]) -> Image.Image:
    image = _blank()
    ImageDraw.Draw(image).ellipse(bounds, fill=1)
    return image
