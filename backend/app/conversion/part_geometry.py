"""Loading for static, LDraw-derived visual part geometry."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from json import loads
from math import isfinite
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PartGeometry:
    part_id: str
    positions: tuple[float, ...]
    indices: tuple[int, ...]
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]


ASSET_DIRECTORY = Path(__file__).with_name("part_geometry_assets")


@cache
def load_part_geometry(part_id: str) -> PartGeometry | None:
    """Load an immutable generated mesh, or return None for legacy rectangular parts."""
    path = ASSET_DIRECTORY / f"{part_id}.json"
    if not path.is_file():
        return None
    try:
        payload = loads(path.read_text(encoding="utf-8"))
        positions = tuple(float(value) for value in payload["positions"])
        indices = tuple(int(value) for value in payload["indices"])
        bounds = payload["bounds"]
        minimum = tuple(float(value) for value in bounds["minimum"])
        maximum = tuple(float(value) for value in bounds["maximum"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid geometry asset for part {part_id}.") from error
    if (
        payload.get("partId") != part_id
        or len(positions) == 0
        or len(positions) % 3 != 0
        or len(indices) == 0
        or len(indices) % 3 != 0
        or len(minimum) != 3
        or len(maximum) != 3
        or not all(isfinite(value) for value in (*positions, *minimum, *maximum))
        or any(index < 0 or index >= len(positions) // 3 for index in indices)
    ):
        raise ValueError(f"Invalid geometry asset for part {part_id}.")
    return PartGeometry(part_id, positions, indices, minimum, maximum)
