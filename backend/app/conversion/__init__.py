"""Pure deterministic mesh-to-LEGO conversion."""

from app.conversion.core import (
    ALGORITHM_VERSION,
    Axis,
    BrickDimensions,
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

__all__ = [
    "ALGORITHM_VERSION",
    "Axis",
    "BrickDimensions",
    "BrickPlacement",
    "BrickType",
    "ConversionError",
    "ConversionSettings",
    "GridPosition",
    "GridSize",
    "LegoModel",
    "ModelDimensions",
    "convert_glb",
    "pack_occupied_cells",
]
