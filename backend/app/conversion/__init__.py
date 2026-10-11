"""Pure deterministic mesh-to-LEGO conversion."""

from app.conversion.colors import DEFAULT_COLOR, LEGO_PALETTE, nearest_palette_color, normalize_rgb
from app.conversion.core import (
    ALGORITHM_VERSION,
    Axis,
    BrickPlacement,
    BrickType,
    ConversionError,
    ConversionSettings,
    GridPosition,
    GridSize,
    LegoModel,
    ModelDimensions,
    convert_glb,
    pack_occupied_cells,
)
from app.conversion.fidelity import FidelityMetrics
from app.conversion.part_catalogue import BrickDimensions, LegoPart

__all__ = [
    "ALGORITHM_VERSION",
    "Axis",
    "BrickDimensions",
    "BrickPlacement",
    "BrickType",
    "ConversionError",
    "ConversionSettings",
    "DEFAULT_COLOR",
    "FidelityMetrics",
    "GridPosition",
    "GridSize",
    "LegoModel",
    "LegoPart",
    "LEGO_PALETTE",
    "ModelDimensions",
    "convert_glb",
    "nearest_palette_color",
    "normalize_rgb",
    "pack_occupied_cells",
]
