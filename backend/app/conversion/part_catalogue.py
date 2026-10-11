"""Runtime loading for the checked-in canonical LEGO part catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, loads
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

BRICK_HEIGHT_PLATES = 3
PLATE_HEIGHT_PLATES = 1
SLOPE_33_FAMILY = "slope_33"
_GENERATED_CATALOGUE_PATH = Path(__file__).with_name("generated_part_catalogue.json")


@dataclass(frozen=True, slots=True)
class BrickDimensions:
    length_studs: int
    width_studs: int
    height_plates: int = BRICK_HEIGHT_PLATES


@dataclass(frozen=True, slots=True)
class LegoPart:
    """One canonical LEGO part, including its current fitter eligibility."""

    part_id: str
    name: str
    family: str
    width_studs: int
    length_studs: int
    height_plates: int
    shape: str = "rectangular"
    slope_profile: str | None = None
    geometry_asset: str | None = None
    ldraw_id: str | None = None
    bricklink_id: str | None = None
    fitter_enabled: bool = False
    fitter_order: int | None = None

    @property
    def dimensions(self) -> BrickDimensions:
        return BrickDimensions(self.length_studs, self.width_studs, self.height_plates)

    @property
    def catalogue_key(self) -> str:
        display_family = self.family.split("_", maxsplit=1)[0]
        return f"{display_family}_{self.width_studs}x{self.length_studs}"


def _load_generated_catalogue() -> tuple[LegoPart, ...]:
    try:
        payload = loads(_GENERATED_CATALOGUE_PATH.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as error:
        raise RuntimeError("The generated LEGO catalogue could not be loaded.") from error
    if not isinstance(payload, list) or not all(isinstance(record, dict) for record in payload):
        raise RuntimeError("The generated LEGO catalogue has an invalid structure.")

    parts: list[LegoPart] = []
    for record in payload:
        parts.append(
            LegoPart(
                part_id=cast(str, record["partId"]),
                name=cast(str, record["name"]),
                family=cast(str, record["family"]),
                width_studs=cast(int, record["widthStuds"]),
                length_studs=cast(int, record["lengthStuds"]),
                height_plates=cast(int, record["heightPlates"]),
                shape=cast(str, record["shape"]),
                slope_profile=cast(str | None, record["slopeProfile"]),
                geometry_asset=cast(str | None, record["geometryAsset"]),
                ldraw_id=cast(str | None, record["ldrawId"]),
                bricklink_id=cast(str | None, record["bricklinkId"]),
                fitter_enabled=cast(bool, record["fitterEnabled"]),
                fitter_order=cast(int | None, record["fitterOrder"]),
            )
        )
    return tuple(parts)


ALL_PARTS: Final = _load_generated_catalogue()
FITTER_PARTS: Final = tuple(
    sorted(
        (part for part in ALL_PARTS if part.fitter_enabled),
        key=lambda part: cast(int, part.fitter_order),
    )
)
PART_BY_ID: Final = MappingProxyType({part.part_id: part for part in ALL_PARTS})

# Compatibility aliases for existing converter code and downstream imports.
LEGO_PART_CATALOGUE = FITTER_PARTS


def legacy_grid_catalogue() -> tuple[LegoPart, ...]:
    """Use brick footprints at one plate high while preserving v2 grid selection."""
    return tuple(
        LegoPart(
            part_id=part.part_id,
            name=part.name,
            family=part.family,
            width_studs=part.width_studs,
            length_studs=part.length_studs,
            height_plates=PLATE_HEIGHT_PLATES,
        )
        for part in FITTER_PARTS
        if part.family == "brick"
    )
