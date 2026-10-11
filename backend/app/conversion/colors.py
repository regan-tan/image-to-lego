"""Verified LEGO colour data and deterministic source-colour matching.

Display RGB values and LDraw codes come from the LDraw official colour table
(https://www.ldraw.org/article/547.html). BrickLink colour IDs and the supported
part/colour pairs were checked against the matching BrickLink catalogue pages
(https://www.bricklink.com/v2/catalog/catalogitem.page?P={part_id}) on
2026-10-11. The availability data means manufactured catalogue combinations,
not current marketplace stock.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import pow
from types import MappingProxyType
from typing import Final, SupportsFloat, cast

DEFAULT_COLOR = "light_bluish_gray"

Rgb = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class LegoColor:
    """One stable, serializable opaque LEGO colour."""

    key: str
    color_id: str
    name: str
    rgb: Rgb
    ldraw_code: int
    bricklink_color_id: int

    @property
    def hex(self) -> str:
        return "#" + "".join(f"{component:02X}" for component in self.rgb)


# Declaration order is also the stable tie-break for equally close colors.
LEGO_COLOR_CATALOGUE = (
    LegoColor("black", "ldraw:0", "Black", (5, 19, 29), 0, 11),
    LegoColor("white", "ldraw:15", "White", (244, 244, 244), 15, 1),
    LegoColor("light_bluish_gray", "ldraw:71", "Light Bluish Gray", (160, 165, 169), 71, 86),
    LegoColor("dark_bluish_gray", "ldraw:72", "Dark Bluish Gray", (108, 110, 104), 72, 85),
    LegoColor("red", "ldraw:4", "Red", (201, 26, 9), 4, 5),
    LegoColor("dark_red", "ldraw:320", "Dark Red", (114, 14, 15), 320, 59),
    LegoColor("orange", "ldraw:25", "Orange", (254, 138, 24), 25, 4),
    LegoColor("yellow", "ldraw:14", "Yellow", (242, 205, 55), 14, 3),
    LegoColor("tan", "ldraw:19", "Tan", (228, 205, 158), 19, 2),
    LegoColor("reddish_brown", "ldraw:70", "Reddish Brown", (88, 42, 18), 70, 88),
    LegoColor("dark_brown", "ldraw:308", "Dark Brown", (53, 33, 0), 308, 120),
    LegoColor("green", "ldraw:2", "Green", (35, 120, 65), 2, 6),
    LegoColor("dark_green", "ldraw:288", "Dark Green", (24, 70, 50), 288, 80),
    LegoColor("lime", "ldraw:27", "Lime", (187, 233, 11), 27, 34),
    LegoColor("blue", "ldraw:1", "Blue", (0, 85, 191), 1, 7),
    LegoColor("dark_blue", "ldraw:272", "Dark Blue", (10, 52, 99), 272, 63),
)
LEGO_PALETTE = LEGO_COLOR_CATALOGUE
COLORS_BY_KEY: Final = MappingProxyType({color.key: color for color in LEGO_COLOR_CATALOGUE})
COLORS_BY_ID: Final = MappingProxyType({color.color_id: color for color in LEGO_COLOR_CATALOGUE})

# These fourteen part IDs are the complete current surface-grid-v3 catalogue.
# Each set is deliberately static: do not infer an unlisted combination.
_VERIFIED_COLOR_IDS = frozenset(color.color_id for color in LEGO_COLOR_CATALOGUE)
PART_COLOR_AVAILABILITY: Final = MappingProxyType(
    {
        "3001": _VERIFIED_COLOR_IDS,
        "3002": _VERIFIED_COLOR_IDS,
        "3003": _VERIFIED_COLOR_IDS,
        "3010": _VERIFIED_COLOR_IDS,
        "3622": _VERIFIED_COLOR_IDS,
        "3020": _VERIFIED_COLOR_IDS,
        "3021": _VERIFIED_COLOR_IDS,
        "3004": _VERIFIED_COLOR_IDS,
        "3022": _VERIFIED_COLOR_IDS,
        "3710": _VERIFIED_COLOR_IDS,
        "3005": _VERIFIED_COLOR_IDS,
        "3623": _VERIFIED_COLOR_IDS,
        "3023": _VERIFIED_COLOR_IDS,
        "3024": _VERIFIED_COLOR_IDS,
        "4286": _VERIFIED_COLOR_IDS,
    }
)


def is_color_available(part_id: str, color_id: str) -> bool:
    return color_id in PART_COLOR_AVAILABILITY.get(part_id, frozenset())


def nearest_available_color(part_id: str, rgb: Rgb) -> LegoColor:
    """Choose the closest verified colour for a real part, with stable catalogue ties."""
    allowed_ids = PART_COLOR_AVAILABILITY.get(part_id)
    if not allowed_ids:
        raise ValueError(f"No verified LEGO colours are configured for part {part_id}.")

    source_lab = _rgb_to_lab(rgb)
    candidates = [color for color in LEGO_COLOR_CATALOGUE if color.color_id in allowed_ids]
    best = candidates[0]
    best_distance = _lab_distance_squared(source_lab, _rgb_to_lab(best.rgb))
    for color in candidates[1:]:
        distance = _lab_distance_squared(source_lab, _rgb_to_lab(color.rgb))
        if distance < best_distance:
            best = color
            best_distance = distance
    return best


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
    best = LEGO_COLOR_CATALOGUE[0]
    best_distance = _lab_distance_squared(source_lab, _rgb_to_lab(best.rgb))
    for color in LEGO_COLOR_CATALOGUE[1:]:
        distance = _lab_distance_squared(source_lab, _rgb_to_lab(color.rgb))
        if distance < best_distance:
            best = color
            best_distance = distance
    return best.key


def most_common_palette_color(colors: Sequence[str]) -> str:
    """Return the most common color, resolving ties in palette declaration order."""
    counts = {palette_color.key: 0 for palette_color in LEGO_PALETTE}
    for color in colors:
        if color in counts:
            counts[color] += 1
    return max(LEGO_PALETTE, key=lambda palette_color: counts[palette_color.key]).key


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
