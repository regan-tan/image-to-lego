from app.conversion.colors import (
    LEGO_PALETTE,
    apply_base_color_factor,
    most_common_palette_color,
    nearest_palette_color,
    normalize_rgb,
)


def test_exact_palette_colors_map_to_their_canonical_names() -> None:
    for palette_color in LEGO_PALETTE:
        assert nearest_palette_color(palette_color.rgb) == palette_color.name


def test_near_colors_and_ties_have_stable_results() -> None:
    assert nearest_palette_color((31, 116, 68)) == "green"
    assert most_common_palette_color(["red", "blue"]) == "red"


def test_normalize_rgb_supports_rgba_and_ignores_transparent_samples() -> None:
    assert normalize_rgb((1.0, 0.5, 0.0, 1.0)) == (255, 128, 0)
    assert normalize_rgb((12, 34, 56, 0)) is None
    assert normalize_rgb((12, 34)) is None


def test_base_color_factor_is_applied_as_a_linear_multiplier() -> None:
    assert apply_base_color_factor((128, 64, 32, 255), (255, 255, 255, 255)) == (128, 64, 32)
    assert apply_base_color_factor((128, 64, 32, 255), (128, 255, 255, 255)) == (93, 64, 32)
    assert apply_base_color_factor((128, 64, 32, 255), (255, 255, 255, 0)) is None
