import pytest

from app.conversion.colors import (
    COLORS_BY_ID,
    LEGO_COLOR_CATALOGUE,
    LEGO_PALETTE,
    apply_base_color_factor,
    most_common_palette_color,
    nearest_available_color,
    nearest_palette_color,
    normalize_rgb,
)
from app.conversion.part_catalogue import FITTER_PARTS, PART_BY_ID


def test_verified_color_catalogue_has_unique_ids_and_valid_rgb() -> None:
    assert len({color.color_id for color in LEGO_COLOR_CATALOGUE}) == len(LEGO_COLOR_CATALOGUE)
    assert all(
        all(0 <= component <= 255 for component in color.rgb) for color in LEGO_COLOR_CATALOGUE
    )


def test_verified_part_color_ids_reference_only_current_canonical_colors() -> None:
    assert all(part.verified_color_ids for part in FITTER_PARTS)
    assert all(
        color_id in COLORS_BY_ID for part in FITTER_PARTS for color_id in part.verified_color_ids
    )


def test_exact_palette_colors_map_to_their_canonical_names() -> None:
    for palette_color in LEGO_PALETTE:
        assert nearest_palette_color(palette_color.rgb) == palette_color.key


def test_near_colors_and_ties_have_stable_results() -> None:
    assert nearest_palette_color((31, 116, 68)) == "green"
    assert most_common_palette_color(["red", "blue"]) == "red"


def test_nearest_available_color_is_deterministic_and_verified() -> None:
    part = PART_BY_ID["3001"]
    first = nearest_available_color(part.verified_color_ids, (31, 116, 68))
    second = nearest_available_color(part.verified_color_ids, (31, 116, 68))
    assert first == second
    assert part.supports_color_id(first.color_id)


def test_part_and_color_can_exist_while_the_pair_is_not_verified() -> None:
    part = PART_BY_ID["3002"]
    assert "ldraw:308" in COLORS_BY_ID
    assert not part.supports_color_id("ldraw:308")


def test_unavailable_preferred_color_uses_the_nearest_verified_fallback() -> None:
    part = PART_BY_ID["3002"]
    color = nearest_available_color(part.verified_color_ids, COLORS_BY_ID["ldraw:308"].rgb)

    assert color.color_id in part.verified_color_ids
    assert color.color_id != "ldraw:308"


def test_no_verified_colors_is_explicit() -> None:
    with pytest.raises(ValueError, match="No verified LEGO colours"):
        nearest_available_color(frozenset(), (31, 116, 68))


def test_4286_supports_every_current_palette_color() -> None:
    slope = PART_BY_ID["4286"]
    assert all(slope.supports_color_id(color.color_id) for color in LEGO_PALETTE)


def test_normalize_rgb_supports_rgba_and_ignores_transparent_samples() -> None:
    assert normalize_rgb((1.0, 0.5, 0.0, 1.0)) == (255, 128, 0)
    assert normalize_rgb((12, 34, 56, 0)) is None
    assert normalize_rgb((12, 34)) is None


def test_base_color_factor_is_applied_as_a_linear_multiplier() -> None:
    assert apply_base_color_factor((128, 64, 32, 255), (255, 255, 255, 255)) == (128, 64, 32)
    assert apply_base_color_factor((128, 64, 32, 255), (128, 255, 255, 255)) == (93, 64, 32)
    assert apply_base_color_factor((128, 64, 32, 255), (255, 255, 255, 0)) is None
