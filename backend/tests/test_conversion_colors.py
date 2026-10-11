from app.conversion.colors import (
    COLORS_BY_ID,
    LEGO_COLOR_CATALOGUE,
    LEGO_PALETTE,
    PART_COLOR_AVAILABILITY,
    apply_base_color_factor,
    is_color_available,
    most_common_palette_color,
    nearest_available_color,
    nearest_palette_color,
    normalize_rgb,
)
from app.conversion.part_catalogue import LEGO_PART_CATALOGUE


def test_verified_color_catalogue_has_unique_ids_and_valid_rgb() -> None:
    assert len({color.color_id for color in LEGO_COLOR_CATALOGUE}) == len(LEGO_COLOR_CATALOGUE)
    assert all(
        all(0 <= component <= 255 for component in color.rgb) for color in LEGO_COLOR_CATALOGUE
    )


def test_verified_availability_references_only_current_parts_and_colors() -> None:
    current_part_ids = {part.part_id for part in LEGO_PART_CATALOGUE}
    assert set(PART_COLOR_AVAILABILITY) == current_part_ids
    assert all(allowed_ids for allowed_ids in PART_COLOR_AVAILABILITY.values())
    assert all(
        color_id in COLORS_BY_ID
        for allowed_ids in PART_COLOR_AVAILABILITY.values()
        for color_id in allowed_ids
    )


def test_exact_palette_colors_map_to_their_canonical_names() -> None:
    for palette_color in LEGO_PALETTE:
        assert nearest_palette_color(palette_color.rgb) == palette_color.key


def test_near_colors_and_ties_have_stable_results() -> None:
    assert nearest_palette_color((31, 116, 68)) == "green"
    assert most_common_palette_color(["red", "blue"]) == "red"


def test_nearest_available_color_is_deterministic_and_verified() -> None:
    first = nearest_available_color("3001", (31, 116, 68))
    second = nearest_available_color("3001", (31, 116, 68))
    assert first == second
    assert is_color_available("3001", first.color_id)


def test_normalize_rgb_supports_rgba_and_ignores_transparent_samples() -> None:
    assert normalize_rgb((1.0, 0.5, 0.0, 1.0)) == (255, 128, 0)
    assert normalize_rgb((12, 34, 56, 0)) is None
    assert normalize_rgb((12, 34)) is None


def test_base_color_factor_is_applied_as_a_linear_multiplier() -> None:
    assert apply_base_color_factor((128, 64, 32, 255), (255, 255, 255, 255)) == (128, 64, 32)
    assert apply_base_color_factor((128, 64, 32, 255), (128, 255, 255, 255)) == (93, 64, 32)
    assert apply_base_color_factor((128, 64, 32, 255), (255, 255, 255, 0)) is None
