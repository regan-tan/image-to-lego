"""The fixed real LEGO parts supported by the surface-grid-v3 converter."""

from __future__ import annotations

from dataclasses import dataclass

BRICK_HEIGHT_PLATES = 3
PLATE_HEIGHT_PLATES = 1


@dataclass(frozen=True, slots=True)
class BrickDimensions:
    length_studs: int
    width_studs: int
    height_plates: int = BRICK_HEIGHT_PLATES


@dataclass(frozen=True, slots=True)
class LegoPart:
    """A rectangular manufactured part used by the deterministic surface fitter."""

    part_id: str
    name: str
    family: str
    width_studs: int
    length_studs: int
    height_plates: int

    @property
    def dimensions(self) -> BrickDimensions:
        return BrickDimensions(self.length_studs, self.width_studs, self.height_plates)

    @property
    def catalogue_key(self) -> str:
        return f"{self.family}_{self.width_studs}x{self.length_studs}"


# Ordering is part of the deterministic fitter's largest-first tie breaking.
LEGO_PART_CATALOGUE = (
    LegoPart("3001", "Brick 2 x 4", "brick", 2, 4, BRICK_HEIGHT_PLATES),
    LegoPart("3002", "Brick 2 x 3", "brick", 2, 3, BRICK_HEIGHT_PLATES),
    LegoPart("3003", "Brick 2 x 2", "brick", 2, 2, BRICK_HEIGHT_PLATES),
    LegoPart("3010", "Brick 1 x 4", "brick", 1, 4, BRICK_HEIGHT_PLATES),
    LegoPart("3622", "Brick 1 x 3", "brick", 1, 3, BRICK_HEIGHT_PLATES),
    LegoPart("3020", "Plate 2 x 4", "plate", 2, 4, PLATE_HEIGHT_PLATES),
    LegoPart("3021", "Plate 2 x 3", "plate", 2, 3, PLATE_HEIGHT_PLATES),
    LegoPart("3004", "Brick 1 x 2", "brick", 1, 2, BRICK_HEIGHT_PLATES),
    LegoPart("3022", "Plate 2 x 2", "plate", 2, 2, PLATE_HEIGHT_PLATES),
    LegoPart("3710", "Plate 1 x 4", "plate", 1, 4, PLATE_HEIGHT_PLATES),
    LegoPart("3005", "Brick 1 x 1", "brick", 1, 1, BRICK_HEIGHT_PLATES),
    LegoPart("3623", "Plate 1 x 3", "plate", 1, 3, PLATE_HEIGHT_PLATES),
    LegoPart("3023", "Plate 1 x 2", "plate", 1, 2, PLATE_HEIGHT_PLATES),
    LegoPart("3024", "Plate 1 x 1", "plate", 1, 1, PLATE_HEIGHT_PLATES),
)


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
        for part in LEGO_PART_CATALOGUE
        if part.family == "brick"
    )
