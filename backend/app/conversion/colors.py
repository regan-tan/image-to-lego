"""Small deterministic helpers for mapping source colors to LEGO-like colors."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import pow
from typing import SupportsFloat, cast

DEFAULT_COLOR = "light_bluish_gray"

Rgb = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class PaletteColor:
    name: str
    rgb: Rgb


# Declaration order is also the stable tie-break for equally close colors.
LEGO_PALETTE = (
    PaletteColor("black", (5, 19, 29)),
    PaletteColor("white", (244, 244, 244)),
    PaletteColor("light_bluish_gray", (160, 165, 169)),
    PaletteColor("dark_bluish_gray", (108, 110, 104)),
    PaletteColor("red", (201, 26, 9)),
    PaletteColor("dark_red", (114, 14, 15)),
    PaletteColor("orange", (254, 138, 24)),
    PaletteColor("yellow", (242, 205, 55)),
    PaletteColor("tan", (228, 205, 158)),
    PaletteColor("reddish_brown", (88, 42, 18)),
    PaletteColor("dark_brown", (53, 33, 0)),
    PaletteColor("green", (35, 120, 65)),
    PaletteColor("dark_green", (24, 70, 50)),
    PaletteColor("lime", (187, 233, 11)),
    PaletteColor("blue", (0, 85, 191)),
    PaletteColor("dark_blue", (10, 52, 99)),
)


def normalize_rgb(color: Sequence[object]) -> Rgb | None:
    """Convert normalized or byte RGB(A) values to RGB; transparent samples are ignored."""
    if len(color) < 3:
        return None
    try:
        components = [float(cast(SupportsFloat, component)) for component in color[:4]]
    except (TypeError, ValueError):
        return None
    if not all(component == component for component in components):
        return None
    if len(components) == 4 and components[3] <= 0:
        return None
    scale = 255.0 if max(components[:3]) <= 1.0 else 1.0
    return tuple(max(0, min(255, round(component * scale))) for component in components[:3])  # type: ignore[return-value]


def apply_base_color_factor(color: Sequence[object], factor: Sequence[object]) -> Rgb | None:
    """Apply a glTF linear base-color multiplier to an sRGB texture sample."""
    rgb = normalize_rgb(color)
    if rgb is None or len(factor) < 3:
        return None
    try:
        components = [float(cast(SupportsFloat, component)) for component in factor[:4]]
    except (TypeError, ValueError):
        return None
    if not all(component == component for component in components):
        return None

    scale = 255.0 if max(components) > 1.0 else 1.0
    normalized = [max(0.0, min(1.0, component / scale)) for component in components]
    if len(normalized) == 4 and normalized[3] <= 0:
        return None

    return tuple(
        round(_linear_to_srgb(_srgb_to_linear(channel / 255.0) * normalized[index]) * 255)
        for index, channel in enumerate(rgb)
    )  # type: ignore[return-value]


def nearest_palette_color(rgb: Rgb) -> str:
    """Choose the closest palette color in CIE Lab space using stable palette-order ties."""
    source_lab = _rgb_to_lab(rgb)
    best = LEGO_PALETTE[0]
    best_distance = _lab_distance_squared(source_lab, _rgb_to_lab(best.rgb))
    for palette_color in LEGO_PALETTE[1:]:
        distance = _lab_distance_squared(source_lab, _rgb_to_lab(palette_color.rgb))
        if distance < best_distance:
            best = palette_color
            best_distance = distance
    return best.name


def most_common_palette_color(colors: Sequence[str]) -> str:
    """Return the most common color, resolving ties in palette declaration order."""
    counts = {palette_color.name: 0 for palette_color in LEGO_PALETTE}
    for color in colors:
        if color in counts:
            counts[color] += 1
    return max(LEGO_PALETTE, key=lambda palette_color: counts[palette_color.name]).name


def _rgb_to_lab(rgb: Rgb) -> tuple[float, float, float]:
    red, green, blue = (_srgb_to_linear(component / 255.0) for component in rgb)
    x = (red * 0.4124 + green * 0.3576 + blue * 0.1805) / 0.95047
    y = red * 0.2126 + green * 0.7152 + blue * 0.0722
    z = (red * 0.0193 + green * 0.1192 + blue * 0.9505) / 1.08883
    fx, fy, fz = (_lab_component(value) for value in (x, y, z))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else pow((value + 0.055) / 1.055, 2.4)


def _linear_to_srgb(value: float) -> float:
    return 12.92 * value if value <= 0.0031308 else 1.055 * pow(value, 1.0 / 2.4) - 0.055


def _lab_component(value: float) -> float:
    return pow(value, 1.0 / 3.0) if value > 0.008856 else 7.787 * value + 16.0 / 116.0


def _lab_distance_squared(
    left: tuple[float, float, float], right: tuple[float, float, float]
) -> float:
    return sum((left[index] - right[index]) ** 2 for index in range(3))
