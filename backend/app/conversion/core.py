"""Deterministic, geometry-only conversion from a GLB mesh to LEGO brick placements."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from math import isfinite, prod
from typing import cast

import trimesh

ALGORITHM_VERSION = "surface-grid-v1"
DEFAULT_COLOR = "light_bluish_gray"
OCCUPANCY_MODE = "surface"
STUD_WIDTH_MM = 8.0
BRICK_HEIGHT_MM = 9.6

# These bounds keep one conversion's memory use and packing work predictable.
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_TRIANGLE_COUNT = 100_000
MAX_TARGET_PARTS = 10_000
MAX_GRID_CELLS = 250_000
MINIMUM_AXIS_EXTENT = 1e-9
GRID_CELL_BUDGET_FACTORS = (0.5, 1.0, 2.0, 4.0, 8.0)


class Axis(StrEnum):
    X = "x"
    Y = "y"
    Z = "z"


class ConversionError(ValueError):
    """A GLB or setting cannot be converted safely into a LEGO model."""


@dataclass(frozen=True, slots=True)
class ConversionSettings:
    target_parts: int
    up_axis: Axis = Axis.Y


@dataclass(frozen=True, slots=True, order=True)
class GridPosition:
    x: int
    y: int
    z: int


@dataclass(frozen=True, slots=True)
class GridSize:
    width_studs: int
    depth_studs: int
    height_bricks: int

    @property
    def cell_count(self) -> int:
        return self.width_studs * self.depth_studs * self.height_bricks


@dataclass(frozen=True, slots=True)
class BrickDimensions:
    length_studs: int
    width_studs: int
    height_bricks: int = 1


@dataclass(frozen=True, slots=True)
class BrickType:
    name: str
    dimensions: BrickDimensions


BRICK_CATALOGUE = (
    BrickType("brick_2x4", BrickDimensions(4, 2)),
    BrickType("brick_2x3", BrickDimensions(3, 2)),
    BrickType("brick_2x2", BrickDimensions(2, 2)),
    BrickType("brick_1x4", BrickDimensions(4, 1)),
    BrickType("brick_1x3", BrickDimensions(3, 1)),
    BrickType("brick_1x2", BrickDimensions(2, 1)),
    BrickType("brick_1x1", BrickDimensions(1, 1)),
)


@dataclass(frozen=True, slots=True)
class BrickPlacement:
    brick_type: BrickType
    position: GridPosition
    orientation_degrees: int
    color: str = DEFAULT_COLOR


@dataclass(frozen=True, slots=True)
class ModelDimensions:
    width_studs: int
    depth_studs: int
    height_bricks: int
    width_mm: float
    depth_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class AlgorithmMetadata:
    algorithm_version: str
    source_sha256: str
    target_parts: int
    occupied_cell_count: int
    grid_size: GridSize
    candidate_count: int
    occupancy_mode: str


@dataclass(frozen=True, slots=True)
class LegoModel:
    placements: tuple[BrickPlacement, ...]
    part_count: int
    dimensions: ModelDimensions
    metadata: AlgorithmMetadata


def convert_glb(glb_bytes: bytes, settings: ConversionSettings) -> LegoModel:
    """Convert GLB bytes into a deterministic one-layer-brick surface model."""
    _validate_settings(settings)
    if len(glb_bytes) > MAX_INPUT_BYTES:
        raise ConversionError("GLB input exceeds the configured size limit.")

    vertices, faces = _load_triangles(glb_bytes)
    normalized_vertices = _normalize_vertices(vertices, settings.up_axis)

    best: tuple[int, int, tuple[BrickPlacement, ...], GridSize, int] | None = None
    candidate_factors = list(GRID_CELL_BUDGET_FACTORS)
    evaluated_grid_sizes: set[GridSize] = set()
    candidate_count = 0
    factor_index = 0
    while factor_index < len(candidate_factors):
        factor = candidate_factors[factor_index]
        grid_size = _candidate_grid_size(normalized_vertices, settings.target_parts, factor)
        if grid_size is None:
            break
        if grid_size in evaluated_grid_sizes:
            if factor_index == len(candidate_factors) - 1:
                candidate_factors.append(factor * 2)
            factor_index += 1
            continue

        evaluated_grid_sizes.add(grid_size)
        occupied_cells = _surface_cells(normalized_vertices, faces, grid_size)
        placements = pack_occupied_cells(occupied_cells)
        candidate_count += 1
        candidate = (
            abs(len(placements) - settings.target_parts),
            grid_size.cell_count,
            placements,
            grid_size,
            len(occupied_cells),
        )
        if best is None or candidate[:2] < best[:2]:
            best = candidate
        if len(placements) >= settings.target_parts:
            break
        if factor_index == len(candidate_factors) - 1:
            candidate_factors.append(factor * 2)
        factor_index += 1

    if best is None:
        raise ConversionError("Target parts would exceed the configured grid safety limit.")

    _, _, placements, grid_size, occupied_cell_count = best
    dimensions = _model_dimensions(placements)
    metadata = AlgorithmMetadata(
        algorithm_version=ALGORITHM_VERSION,
        source_sha256=sha256(glb_bytes).hexdigest(),
        target_parts=settings.target_parts,
        occupied_cell_count=occupied_cell_count,
        grid_size=grid_size,
        candidate_count=candidate_count,
        occupancy_mode=OCCUPANCY_MODE,
    )
    return LegoModel(
        placements=placements,
        part_count=len(placements),
        dimensions=dimensions,
        metadata=metadata,
    )


def pack_occupied_cells(occupied_cells: Collection[GridPosition]) -> tuple[BrickPlacement, ...]:
    """Cover occupied grid cells with the fixed catalogue in deterministic largest-first order."""
    remaining = set(occupied_cells)
    if not remaining:
        raise ConversionError("The mesh did not produce any occupied grid cells.")

    placements: list[BrickPlacement] = []
    maximum = GridPosition(
        max(cell.x for cell in remaining),
        max(cell.y for cell in remaining),
        max(cell.z for cell in remaining),
    )
    for z in range(maximum.z + 1):
        for y in range(maximum.y + 1):
            for x in range(maximum.x + 1):
                position = GridPosition(x, y, z)
                if position not in remaining:
                    continue
                placement = _first_fitting_brick(position, remaining)
                placements.append(placement)
                remaining.difference_update(_placement_cells(placement))

    return tuple(placements)


def _validate_settings(settings: ConversionSettings) -> None:
    if settings.target_parts <= 0:
        raise ConversionError("Target parts must be greater than zero.")
    if settings.target_parts > MAX_TARGET_PARTS:
        raise ConversionError("Target parts exceeds the configured safety limit.")


def _load_triangles(
    glb_bytes: bytes,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    try:
        scene = cast(
            trimesh.Scene,
            trimesh.load(BytesIO(glb_bytes), file_type="glb", force="scene"),
        )
        mesh = scene.to_geometry()
    except Exception as error:
        raise ConversionError("Input is not a readable GLB mesh.") from error

    if not isinstance(mesh, trimesh.Trimesh) or mesh.is_empty:
        raise ConversionError("GLB does not contain a mesh.")

    vertices = [
        (float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices.tolist()
    ]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces.tolist()]
    if not faces:
        raise ConversionError("GLB does not contain any triangles.")
    if len(faces) > MAX_TRIANGLE_COUNT:
        raise ConversionError("GLB triangle count exceeds the configured safety limit.")
    if any(len(vertex) != 3 or not all(isfinite(value) for value in vertex) for vertex in vertices):
        raise ConversionError("GLB contains non-finite vertex coordinates.")
    if any(len(face) != 3 for face in faces):
        raise ConversionError("GLB contains a non-triangle face.")

    return vertices, faces


def _normalize_vertices(
    vertices: list[tuple[float, float, float]], up_axis: Axis
) -> list[tuple[float, float, float]]:
    if not vertices:
        raise ConversionError("GLB does not contain any vertices.")

    lego_vertices = [_to_lego_axes(vertex, up_axis) for vertex in vertices]
    minimum = tuple(min(vertex[index] for vertex in lego_vertices) for index in range(3))
    maximum = tuple(max(vertex[index] for vertex in lego_vertices) for index in range(3))
    extents = tuple(maximum[index] - minimum[index] for index in range(3))
    if any(extent <= MINIMUM_AXIS_EXTENT for extent in extents):
        raise ConversionError("GLB mesh must have non-zero extent on all three axes.")

    return [
        (
            vertex[0] - minimum[0],
            vertex[1] - minimum[1],
            vertex[2] - minimum[2],
        )
        for vertex in lego_vertices
    ]


def _to_lego_axes(vertex: tuple[float, float, float], up_axis: Axis) -> tuple[float, float, float]:
    x, y, z = vertex
    if up_axis is Axis.X:
        return y, z, x
    if up_axis is Axis.Y:
        return x, -z, y
    return x, y, z


def _candidate_grid_size(
    vertices: list[tuple[float, float, float]], target_parts: int, factor: float
) -> GridSize | None:
    maximum = tuple(max(vertex[index] for vertex in vertices) for index in range(3))
    proportions = (
        maximum[0] / STUD_WIDTH_MM,
        maximum[1] / STUD_WIDTH_MM,
        maximum[2] / BRICK_HEIGHT_MM,
    )
    proportion_volume = prod(proportions)
    grid_size = _grid_size_for_budget(proportions, proportion_volume, target_parts * factor)
    if grid_size.cell_count > MAX_GRID_CELLS:
        return None
    return grid_size


def _grid_size_for_budget(
    proportions: tuple[float, float, float], proportion_volume: float, cell_budget: float
) -> GridSize:
    scale = (cell_budget / proportion_volume) ** (1.0 / 3.0)
    # Two samples per axis preserve a surface for small targets and avoid zero-span voxel grids.
    width = max(2, round(proportions[0] * scale))
    depth = max(2, round(proportions[1] * scale))
    height = max(2, round(proportions[2] * scale))
    return GridSize(width, depth, height)


def _surface_cells(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    grid_size: GridSize,
) -> frozenset[GridPosition]:
    maximum = tuple(max(vertex[index] for vertex in vertices) for index in range(3))
    scaled_vertices = [
        (
            vertex[0] / maximum[0] * (grid_size.width_studs - 1),
            vertex[1] / maximum[1] * (grid_size.depth_studs - 1),
            vertex[2] / maximum[2] * (grid_size.height_bricks - 1),
        )
        for vertex in vertices
    ]
    mesh = trimesh.Trimesh(vertices=scaled_vertices, faces=faces, process=False, validate=False)
    voxel_grid = mesh.voxelized(pitch=1.0)
    cells = frozenset(
        GridPosition(int(index[0]), int(index[1]), int(index[2]))
        for index in voxel_grid.sparse_indices.tolist()
    )
    if not cells:
        raise ConversionError("The mesh did not produce any surface cells.")
    if any(
        cell.x < 0
        or cell.y < 0
        or cell.z < 0
        or cell.x >= grid_size.width_studs
        or cell.y >= grid_size.depth_studs
        or cell.z >= grid_size.height_bricks
        for cell in cells
    ):
        raise ConversionError("Surface voxelization produced cells outside the requested grid.")
    return cells


def _first_fitting_brick(
    position: GridPosition, remaining: set[GridPosition]
) -> BrickPlacement:
    for brick_type in BRICK_CATALOGUE:
        orientations = (
            (0,)
            if brick_type.dimensions.length_studs == brick_type.dimensions.width_studs
            else (0, 90)
        )
        for orientation in orientations:
            placement = BrickPlacement(brick_type, position, orientation)
            if _placement_cells(placement).issubset(remaining):
                return placement
    raise ConversionError("A surface cell could not be covered by the supported brick catalogue.")


def _placement_cells(placement: BrickPlacement) -> frozenset[GridPosition]:
    dimensions = placement.brick_type.dimensions
    length = dimensions.length_studs
    width = dimensions.width_studs
    if placement.orientation_degrees == 90:
        length, width = width, length
    return frozenset(
        GridPosition(placement.position.x + x, placement.position.y + y, placement.position.z)
        for y in range(width)
        for x in range(length)
    )


def _model_dimensions(placements: tuple[BrickPlacement, ...]) -> ModelDimensions:
    maximum_x = 0
    maximum_y = 0
    maximum_z = 0
    for placement in placements:
        cells = _placement_cells(placement)
        maximum_x = max(maximum_x, max(cell.x for cell in cells) + 1)
        maximum_y = max(maximum_y, max(cell.y for cell in cells) + 1)
        maximum_z = max(maximum_z, placement.position.z + 1)

    return ModelDimensions(
        width_studs=maximum_x,
        depth_studs=maximum_y,
        height_bricks=maximum_z,
        width_mm=maximum_x * STUD_WIDTH_MM,
        depth_mm=maximum_y * STUD_WIDTH_MM,
        height_mm=maximum_z * BRICK_HEIGHT_MM,
    )
