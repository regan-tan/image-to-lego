"""Deterministic GLB-to-LEGO conversion with geometry-preserving color mapping."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from math import isfinite, prod
from typing import Any, cast

import trimesh

from app.conversion.colors import (
    COLORS_BY_KEY,
    DEFAULT_COLOR,
    apply_base_color_factor,
    most_common_palette_color,
    nearest_available_color,
    nearest_palette_color,
    normalize_rgb,
)
from app.conversion.fidelity import FidelityMetrics, evaluate_fidelity
from app.conversion.part_catalogue import (
    BRICK_HEIGHT_PLATES,
    LEGO_PART_CATALOGUE,
    SLOPE_33_FAMILY,
    LegoPart,
    legacy_grid_catalogue,
)

logger = logging.getLogger(__name__)

SURFACE_GRID_V3 = "surface-grid-v3"
SURFACE_GRID_V4 = "surface-grid-v4"
ALGORITHM_VERSION = SURFACE_GRID_V4
OCCUPANCY_MODE = "surface"
STUD_WIDTH_MM = 8.0
PLATE_HEIGHT_MM = 3.2

# These bounds keep one conversion's memory use and packing work predictable.
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_TRIANGLE_COUNT = 100_000
MAX_TARGET_PARTS = 10_000
MAX_GRID_CELLS = 250_000
MINIMUM_AXIS_EXTENT = 1e-9
GRID_CELL_BUDGET_FACTORS = (0.5, 1.0, 2.0, 4.0, 8.0)
SLOPE_ORIENTATIONS = (0, 90, 180, 270)
SLOPE_33_PROFILE = "rise_33_3"
SLOPE_33_HEIGHT_PROFILES = ((0, 1, 3), (0, 2, 3))
_EMPTY_SPACE_NEIGHBOR_OFFSETS = tuple(
    (x_offset, y_offset, z_offset)
    for z_offset in (-1, 0, 1)
    for y_offset in (-1, 0, 1)
    for x_offset in (-1, 0, 1)
    if (x_offset, y_offset, z_offset) != (0, 0, 0)
)


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
    algorithm_version: str = ALGORITHM_VERSION


@dataclass(frozen=True, slots=True, order=True)
class GridPosition:
    x: int
    y: int
    z: int


@dataclass(frozen=True, slots=True)
class GridSize:
    width_studs: int
    depth_studs: int
    height_plates: int

    @property
    def cell_count(self) -> int:
        return self.width_studs * self.depth_studs * self.height_plates


BrickType = LegoPart
BRICK_CATALOGUE = LEGO_PART_CATALOGUE
LEGACY_BRICK_CATALOGUE = legacy_grid_catalogue()


@dataclass(frozen=True, slots=True)
class BrickPlacement:
    brick_type: LegoPart
    position: GridPosition
    orientation_degrees: int
    color: str = DEFAULT_COLOR
    color_id: str | None = None
    color_name: str | None = None
    color_hex: str | None = None


@dataclass(frozen=True, slots=True)
class ModelDimensions:
    width_studs: int
    depth_studs: int
    height_plates: int
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
    fidelity: FidelityMetrics


@dataclass(frozen=True, slots=True)
class LegoModel:
    placements: tuple[BrickPlacement, ...]
    part_count: int
    dimensions: ModelDimensions
    metadata: AlgorithmMetadata


@dataclass(frozen=True, slots=True)
class SourceOccupancy:
    """Voxel cells from the source mesh, separated by their safe-use meaning."""

    surface_cells: frozenset[GridPosition]
    safe_interior_cells: frozenset[GridPosition]


def convert_glb(glb_bytes: bytes, settings: ConversionSettings) -> LegoModel:
    """Convert GLB bytes into a deterministic surface model on a plate-height grid."""
    if settings.algorithm_version == SURFACE_GRID_V3:
        return _convert_surface_grid_v3(glb_bytes, settings)
    if settings.algorithm_version == SURFACE_GRID_V4:
        return _convert_surface_grid_v4(glb_bytes, settings)
    raise ConversionError("The requested conversion algorithm is not supported.")


def _convert_surface_grid_v3(glb_bytes: bytes, settings: ConversionSettings) -> LegoModel:
    """Preserve the established surface-grid-v3 conversion path unchanged."""
    _validate_settings(settings)
    if len(glb_bytes) > MAX_INPUT_BYTES:
        raise ConversionError("GLB input exceeds the configured size limit.")

    mesh = _load_mesh(glb_bytes)
    vertices = [
        (float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices.tolist()
    ]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces.tolist()]
    normalized_vertices = _normalize_vertices(vertices, settings.up_axis)

    legacy_grid_size, candidate_count = _select_legacy_grid(
        normalized_vertices,
        faces,
        settings.target_parts,
    )
    grid_size = GridSize(
        legacy_grid_size.width_studs,
        legacy_grid_size.depth_studs,
        legacy_grid_size.height_plates * BRICK_HEIGHT_PLATES,
    )
    if grid_size.cell_count > MAX_GRID_CELLS:
        raise ConversionError("Target parts would exceed the configured grid safety limit.")

    source_occupancy = _source_occupancy(normalized_vertices, faces, grid_size)
    occupied_cells = source_occupancy.surface_cells
    slope_placements, reserved_slope_cells = _place_supported_slopes(occupied_cells)
    remaining_cells = occupied_cells - reserved_slope_cells
    rectangular_placements = pack_occupied_cells(remaining_cells) if remaining_cells else ()
    placements = slope_placements + rectangular_placements
    occupied_cell_count = len(occupied_cells)
    placements = _color_placements(placements, normalized_vertices, faces, mesh, grid_size)
    dimensions = _model_dimensions(placements)
    scaled_vertices = _scale_vertices_to_grid(normalized_vertices, grid_size)
    metadata = AlgorithmMetadata(
        algorithm_version=SURFACE_GRID_V3,
        source_sha256=sha256(glb_bytes).hexdigest(),
        target_parts=settings.target_parts,
        occupied_cell_count=occupied_cell_count,
        grid_size=grid_size,
        candidate_count=candidate_count,
        occupancy_mode=OCCUPANCY_MODE,
        fidelity=evaluate_fidelity(
            scaled_vertices,
            faces,
            _placement_boxes(placements),
            slope_vertices=_slope_vertices(placements),
            target_parts=settings.target_parts,
        ),
    )
    return LegoModel(
        placements=placements,
        part_count=len(placements),
        dimensions=dimensions,
        metadata=metadata,
    )


def _convert_surface_grid_v4(glb_bytes: bytes, settings: ConversionSettings) -> LegoModel:
    """Use the validated structural CP-SAT formulation over the v3 projection hull."""
    from app.conversion.surface_grid_v4 import projection_hull_target, solve_surface_grid_v4

    baseline = _convert_surface_grid_v3(
        glb_bytes,
        ConversionSettings(target_parts=settings.target_parts, up_axis=settings.up_axis),
    )
    mesh = _load_mesh(glb_bytes)
    vertices = [
        (float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices.tolist()
    ]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces.tolist()]
    normalized_vertices = _normalize_vertices(vertices, settings.up_axis)
    source_occupancy = _source_occupancy(normalized_vertices, faces, baseline.metadata.grid_size)
    locked_slopes, locked_slope_cells = _place_supported_slopes(source_occupancy.surface_cells)
    baseline_slopes = tuple(
        placement
        for placement in baseline.placements
        if placement.brick_type.shape != "rectangular"
    )
    if _placement_geometry(locked_slopes) != _placement_geometry(baseline_slopes):
        raise ConversionError("Locked slopes did not reproduce surface-grid-v3 placements.")

    exterior_cells = frozenset(
        cell
        for placement in baseline.placements
        if placement.brick_type.shape == "rectangular"
        for cell in _placement_cells(placement)
    )
    target_cells, required_pixels = projection_hull_target(
        exterior_cells,
        locked_slope_cells,
        baseline.metadata.grid_size,
    )
    packing = solve_surface_grid_v4(
        target_cells,
        required_pixels,
        locked_slope_cells,
        BRICK_CATALOGUE,
        target_parts=settings.target_parts,
    )
    colored_rectangles = _color_placements(
        packing.placements,
        normalized_vertices,
        faces,
        mesh,
        baseline.metadata.grid_size,
    )
    placements = baseline_slopes + colored_rectangles
    dimensions = _model_dimensions(placements)
    scaled_vertices = _scale_vertices_to_grid(normalized_vertices, baseline.metadata.grid_size)
    occupied_cell_count = len(
        {cell for placement in colored_rectangles for cell in _placement_cells(placement)}
        | set(locked_slope_cells)
    )
    metadata = AlgorithmMetadata(
        algorithm_version=SURFACE_GRID_V4,
        source_sha256=sha256(glb_bytes).hexdigest(),
        target_parts=settings.target_parts,
        occupied_cell_count=occupied_cell_count,
        grid_size=baseline.metadata.grid_size,
        candidate_count=packing.candidate_count,
        occupancy_mode=OCCUPANCY_MODE,
        fidelity=evaluate_fidelity(
            scaled_vertices,
            faces,
            _placement_boxes(placements),
            slope_vertices=_slope_vertices(placements),
            target_parts=settings.target_parts,
        ),
    )
    return LegoModel(
        placements=placements,
        part_count=len(placements),
        dimensions=dimensions,
        metadata=metadata,
    )


def pack_occupied_cells(
    occupied_cells: Collection[GridPosition],
    catalogue: tuple[LegoPart, ...] = BRICK_CATALOGUE,
) -> tuple[BrickPlacement, ...]:
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
                placement = _first_fitting_brick(position, remaining, catalogue)
                placements.append(placement)
                remaining.difference_update(_placement_cells(placement))

    return tuple(placements)


def _select_legacy_grid(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    target_parts: int,
) -> tuple[GridSize, int]:
    """Select the v2 horizontal resolution before expanding vertical layers to plates."""
    best: tuple[int, int, GridSize] | None = None
    candidate_factors = list(GRID_CELL_BUDGET_FACTORS)
    evaluated_grid_sizes: set[GridSize] = set()
    candidate_count = 0
    factor_index = 0
    while factor_index < len(candidate_factors):
        factor = candidate_factors[factor_index]
        grid_size = _legacy_candidate_grid_size(vertices, target_parts, factor)
        if grid_size is None:
            break
        if grid_size in evaluated_grid_sizes:
            if factor_index == len(candidate_factors) - 1:
                candidate_factors.append(factor * 2)
            factor_index += 1
            continue

        evaluated_grid_sizes.add(grid_size)
        occupied_cells = _surface_cells(vertices, faces, grid_size)
        placements = pack_occupied_cells(occupied_cells, LEGACY_BRICK_CATALOGUE)
        candidate_count += 1
        candidate = (abs(len(placements) - target_parts), grid_size.cell_count, grid_size)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
        if len(placements) >= target_parts:
            break
        if factor_index == len(candidate_factors) - 1:
            candidate_factors.append(factor * 2)
        factor_index += 1

    if best is None:
        raise ConversionError("Target parts would exceed the configured grid safety limit.")
    return best[2], candidate_count


def _validate_settings(settings: ConversionSettings) -> None:
    if settings.target_parts <= 0:
        raise ConversionError("Target parts must be greater than zero.")
    if settings.target_parts > MAX_TARGET_PARTS:
        raise ConversionError("Target parts exceeds the configured safety limit.")
    if settings.algorithm_version not in {SURFACE_GRID_V3, SURFACE_GRID_V4}:
        raise ConversionError("The requested conversion algorithm is not supported.")


def _load_mesh(glb_bytes: bytes) -> trimesh.Trimesh:
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

    vertices = mesh.vertices.tolist()
    faces = mesh.faces.tolist()
    if not faces:
        raise ConversionError("GLB does not contain any triangles.")
    if len(faces) > MAX_TRIANGLE_COUNT:
        raise ConversionError("GLB triangle count exceeds the configured safety limit.")
    if any(len(vertex) != 3 or not all(isfinite(value) for value in vertex) for vertex in vertices):
        raise ConversionError("GLB contains non-finite vertex coordinates.")
    if any(len(face) != 3 for face in faces):
        raise ConversionError("GLB contains a non-triangle face.")

    return mesh


def _color_placements(
    placements: tuple[BrickPlacement, ...],
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    mesh: trimesh.Trimesh,
    grid_size: GridSize,
) -> tuple[BrickPlacement, ...]:
    face_colors, color_source = _face_colors(mesh, len(faces))
    cell_colors: dict[GridPosition, list[str]] = defaultdict(list)
    all_colors: list[str] = []
    maximum = (
        max(vertex[0] for vertex in vertices),
        max(vertex[1] for vertex in vertices),
        max(vertex[2] for vertex in vertices),
    )
    for face, rgb in zip(faces, face_colors, strict=True):
        if rgb is None:
            continue
        color = nearest_palette_color(rgb)
        all_colors.append(color)
        triangle = [vertices[index] for index in face]
        centroid = (
            sum(vertex[0] for vertex in triangle) / 3,
            sum(vertex[1] for vertex in triangle) / 3,
            sum(vertex[2] for vertex in triangle) / 3,
        )
        samples = [*triangle, centroid]
        for sample in samples:
            cell_colors[_point_to_grid_cell(sample, maximum, grid_size)].append(color)

    fallback = most_common_palette_color(all_colors) if all_colors else DEFAULT_COLOR
    colored: list[BrickPlacement] = []
    fallback_count = 0
    for placement in placements:
        colors = [
            color for cell in _placement_cells(placement) for color in cell_colors.get(cell, [])
        ]
        if colors:
            color = most_common_palette_color(colors)
        else:
            color = fallback
            fallback_count += 1
        try:
            verified_color = nearest_available_color(
                placement.brick_type.part_id,
                COLORS_BY_KEY[color].rgb,
            )
        except ValueError as error:
            raise ConversionError(str(error)) from error
        colored.append(
            BrickPlacement(
                brick_type=placement.brick_type,
                position=placement.position,
                orientation_degrees=placement.orientation_degrees,
                color=verified_color.key,
                color_id=verified_color.color_id,
                color_name=verified_color.name,
                color_hex=verified_color.hex,
            )
        )
    _log_color_samples(color_source, len(all_colors), fallback_count)
    return tuple(colored)


def _point_to_grid_cell(
    point: tuple[float, float, float], maximum: tuple[float, float, float], grid_size: GridSize
) -> GridPosition:
    scales = (grid_size.width_studs - 1, grid_size.depth_studs - 1, grid_size.height_plates - 1)
    coordinates = [round(point[index] / maximum[index] * scales[index]) for index in range(3)]
    return GridPosition(*coordinates)


def _face_colors(
    mesh: trimesh.Trimesh, face_count: int
) -> tuple[list[tuple[int, int, int] | None], str]:
    """Extract visual data without allowing malformed visuals to affect geometry conversion."""
    visual = cast(Any, mesh.visual)

    try:
        texture_colors = _texture_face_colors(mesh, visual)
        if any(texture_colors):
            return texture_colors, "texture"
    except (AttributeError, IndexError, TypeError, ValueError):
        logger.debug("Texture color extraction failed; trying other visual data.", exc_info=True)

    if bool(getattr(visual, "defined", False)):
        try:
            face_colors = _normalized_colors(getattr(visual, "face_colors", None))
            if getattr(visual, "kind", None) == "face" and len(face_colors) == face_count:
                return face_colors, "vertex/face"

            vertex_colors = _normalized_colors(getattr(visual, "vertex_colors", None))
            if len(vertex_colors) == len(mesh.vertices):
                colors = [
                    _average_rgb([vertex_colors[index] for index in face])
                    for face in mesh.faces.tolist()
                ]
                if any(colors):
                    return colors, "vertex/face"
            if len(face_colors) == face_count and any(face_colors):
                return face_colors, "vertex/face"
        except (AttributeError, IndexError, TypeError, ValueError):
            logger.debug(
                "Vertex/face color extraction failed; trying material data.", exc_info=True
            )

    try:
        material_colors = _material_face_colors(visual, face_count)
        if any(material_colors):
            return material_colors, "material"
    except (AttributeError, TypeError, ValueError):
        logger.debug("Material color extraction failed; using the neutral fallback.", exc_info=True)
    return [None] * face_count, "fallback"


def _texture_face_colors(
    mesh: trimesh.Trimesh, visual: object
) -> list[tuple[int, int, int] | None]:
    if getattr(visual, "kind", None) != "texture":
        return []

    uv = getattr(visual, "uv", None)
    material = getattr(visual, "material", None)
    image = getattr(material, "baseColorTexture", None)
    if image is None:
        image = getattr(material, "image", None)
    if uv is None or image is None or not hasattr(material, "to_color"):
        return []
    if len(uv) != len(mesh.vertices):
        return []

    face_uv = uv[mesh.faces].mean(axis=1)
    sampled = cast(Any, material).to_color(face_uv)
    if sampled is None or not hasattr(sampled, "tolist"):
        return []

    factor = getattr(material, "baseColorFactor", None)
    if factor is None:
        return _normalized_colors(sampled)
    return [
        apply_base_color_factor(color, cast(Sequence[object], factor)) for color in sampled.tolist()
    ]


def _material_face_colors(visual: object, face_count: int) -> list[tuple[int, int, int] | None]:
    material = getattr(visual, "material", None)
    for name in ("baseColorFactor", "diffuse"):
        value = getattr(material, name, None)
        if value is not None:
            color = normalize_rgb(cast(Sequence[object], value))
            if color is not None:
                return [color] * face_count
    return [None] * face_count


def _normalized_colors(colors: object) -> list[tuple[int, int, int] | None]:
    if colors is None or not hasattr(colors, "tolist"):
        return []
    return [normalize_rgb(cast(Sequence[object], color)) for color in colors.tolist()]


def _average_rgb(colors: Sequence[tuple[int, int, int] | None]) -> tuple[int, int, int] | None:
    usable = [color for color in colors if color is not None]
    if not usable:
        return None
    return tuple(round(sum(color[index] for color in usable) / len(usable)) for index in range(3))  # type: ignore[return-value]


def _log_color_samples(color_source: str, source_count: int, fallback_count: int) -> None:
    counts = {"texture": 0, "vertex/face": 0, "material": 0}
    if color_source in counts:
        counts[color_source] = source_count
    logger.debug(
        "Conversion color samples: texture=%d vertex/face=%d material=%d fallback=%d",
        counts["texture"],
        counts["vertex/face"],
        counts["material"],
        fallback_count,
    )


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


def _legacy_candidate_grid_size(
    vertices: list[tuple[float, float, float]], target_parts: int, factor: float
) -> GridSize | None:
    maximum = tuple(max(vertex[index] for vertex in vertices) for index in range(3))
    proportions = (
        maximum[0] / STUD_WIDTH_MM,
        maximum[1] / STUD_WIDTH_MM,
        maximum[2] / (PLATE_HEIGHT_MM * BRICK_HEIGHT_PLATES),
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
    scaled_vertices = _scale_vertices_to_grid(vertices, grid_size)
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
        or cell.z >= grid_size.height_plates
        for cell in cells
    ):
        raise ConversionError("Surface voxelization produced cells outside the requested grid.")
    return cells


def _source_occupancy(
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    grid_size: GridSize,
) -> SourceOccupancy:
    """Build a conservative source-volume mask without changing surface fitting.

    Only watertight meshes can prove an enclosed source volume. For those meshes,
    a cell is safe when a 26-neighbour flood fill from the grid boundary cannot
    reach it without crossing a surface voxel. Non-watertight meshes deliberately
    expose no safe interior cells so later repair cannot bridge a real opening.
    """
    surface_cells = _surface_cells(vertices, faces, grid_size)
    scaled_vertices = _scale_vertices_to_grid(vertices, grid_size)
    mesh = trimesh.Trimesh(vertices=scaled_vertices, faces=faces, process=False, validate=False)
    safe_interior_cells = _safe_interior_cells(
        surface_cells,
        grid_size,
        mesh_is_watertight=mesh.is_watertight,
    )
    return SourceOccupancy(surface_cells, safe_interior_cells)


def _safe_interior_cells(
    surface_cells: frozenset[GridPosition],
    grid_size: GridSize,
    *,
    mesh_is_watertight: bool,
) -> frozenset[GridPosition]:
    """Return only enclosed non-surface cells of a watertight source mesh."""
    if not mesh_is_watertight:
        return frozenset()

    all_cells = {
        GridPosition(x, y, z)
        for z in range(grid_size.height_plates)
        for y in range(grid_size.depth_studs)
        for x in range(grid_size.width_studs)
    }
    empty_cells = all_cells - surface_cells
    exterior_cells = {
        cell
        for cell in empty_cells
        if cell.x in (0, grid_size.width_studs - 1)
        or cell.y in (0, grid_size.depth_studs - 1)
        or cell.z in (0, grid_size.height_plates - 1)
    }
    pending = list(exterior_cells)
    while pending:
        cell = pending.pop()
        for x_offset, y_offset, z_offset in _EMPTY_SPACE_NEIGHBOR_OFFSETS:
            neighbor = GridPosition(
                cell.x + x_offset,
                cell.y + y_offset,
                cell.z + z_offset,
            )
            if neighbor in empty_cells and neighbor not in exterior_cells:
                exterior_cells.add(neighbor)
                pending.append(neighbor)
    return frozenset(empty_cells - exterior_cells)


def _scale_vertices_to_grid(
    vertices: list[tuple[float, float, float]], grid_size: GridSize
) -> list[tuple[float, float, float]]:
    maximum = tuple(max(vertex[index] for vertex in vertices) for index in range(3))
    return [
        (
            vertex[0] / maximum[0] * (grid_size.width_studs - 1),
            vertex[1] / maximum[1] * (grid_size.depth_studs - 1),
            vertex[2] / maximum[2] * (grid_size.height_plates - 1),
        )
        for vertex in vertices
    ]


def _first_fitting_brick(
    position: GridPosition,
    remaining: set[GridPosition],
    catalogue: tuple[LegoPart, ...],
) -> BrickPlacement:
    for brick_type in catalogue:
        if brick_type.shape != "rectangular":
            continue
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
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    return frozenset(
        GridPosition(placement.position.x + x, placement.position.y + y, placement.position.z + z)
        for z in range(dimensions.height_plates)
        for y in range(width)
        for x in range(length)
    )


def _placement_geometry(
    placements: Collection[BrickPlacement],
) -> tuple[tuple[str, GridPosition, int], ...]:
    return tuple(
        (placement.brick_type.part_id, placement.position, placement.orientation_degrees)
        for placement in placements
    )


def _placement_boxes(
    placements: tuple[BrickPlacement, ...],
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    boxes = []
    for placement in placements:
        if placement.brick_type.shape != "rectangular":
            continue
        dimensions = placement.brick_type.dimensions
        length = dimensions.length_studs
        width = dimensions.width_studs
        if placement.orientation_degrees in (90, 270):
            length, width = width, length
        boxes.append(
            (
                float(placement.position.x),
                float(placement.position.y),
                float(placement.position.z),
                float(placement.position.x + length),
                float(placement.position.y + width),
                float(placement.position.z + dimensions.height_plates),
            )
        )
    return tuple(boxes)


def _place_supported_slopes(
    occupied_cells: Collection[GridPosition],
) -> tuple[tuple[BrickPlacement, ...], frozenset[GridPosition]]:
    """Select non-overlapping exposed runs for each supported slope family."""
    slope_parts = tuple(part for part in BRICK_CATALOGUE if part.family == SLOPE_33_FAMILY)
    return _place_slope_33_family(occupied_cells, slope_parts)


def _place_slope_33_family(
    occupied_cells: Collection[GridPosition],
    slope_parts: Collection[LegoPart],
) -> tuple[tuple[BrickPlacement, ...], frozenset[GridPosition]]:
    """Fit the declared 33-degree profile using only the LEGO grid surface."""
    if not slope_parts:
        return (), frozenset()
    top_cells = _top_surface_cells(occupied_cells)
    selected: list[BrickPlacement] = []
    reserved: set[GridPosition] = set()

    for slope in slope_parts:
        for orientation in SLOPE_ORIENTATIONS:
            for y in range(max(cell.y for cell in top_cells) + 1):
                for x in range(max(cell.x for cell in top_cells) + 1):
                    candidate = _slope_33_candidate(top_cells, slope, x, y, orientation)
                    if candidate is None or not reserved.isdisjoint(candidate):
                        continue
                    selected.append(
                        BrickPlacement(
                            slope,
                            GridPosition(x, y, min(cell.z for cell in candidate)),
                            orientation,
                        )
                    )
                    reserved.update(candidate)

    return tuple(selected), frozenset(reserved)


def _top_surface_cells(occupied_cells: Collection[GridPosition]) -> frozenset[GridPosition]:
    highest: dict[tuple[int, int], GridPosition] = {}
    for cell in occupied_cells:
        coordinate = (cell.x, cell.y)
        existing = highest.get(coordinate)
        if existing is None or cell.z > existing.z:
            highest[coordinate] = cell
    return frozenset(highest.values())


def _slope_33_candidate(
    top_cells: Collection[GridPosition],
    slope: LegoPart,
    x: int,
    y: int,
    orientation: int,
) -> tuple[GridPosition, ...] | None:
    if slope.slope_profile != SLOPE_33_PROFILE:
        return None
    if orientation in (0, 180):
        positions = tuple(
            (x + length_offset, y + width_offset)
            for width_offset in range(slope.width_studs)
            for length_offset in range(slope.length_studs)
        )
    else:
        positions = tuple(
            (x + width_offset, y + length_offset)
            for width_offset in range(slope.width_studs)
            for length_offset in range(slope.length_studs)
        )
    by_position = {(cell.x, cell.y): cell for cell in top_cells}
    cells = tuple(by_position.get(position) for position in positions)
    if any(cell is None for cell in cells):
        return None
    candidates = cast(tuple[GridPosition, ...], cells)
    base_height = min(cell.z for cell in candidates)
    height_profiles = (
        SLOPE_33_HEIGHT_PROFILES
        if orientation in (0, 90)
        else tuple(tuple(reversed(profile)) for profile in SLOPE_33_HEIGHT_PROFILES)
    )
    if not any(
        all(
            cell.z == base_height + height_profile[index % slope.length_studs]
            for index, cell in enumerate(candidates)
        )
        for height_profile in height_profiles
    ):
        return None
    return candidates


def _slope_vertices(
    placements: Collection[BrickPlacement],
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    """Return simple outer triangular-prism geometry for supported slope families."""
    slopes = []
    for placement in placements:
        if placement.brick_type.family != SLOPE_33_FAMILY:
            continue
        base = placement.position
        dimensions = placement.brick_type.dimensions
        local_vertices = (
            (0.0, 0.0, 0.0),
            (float(dimensions.length_studs), 0.0, 0.0),
            (float(dimensions.length_studs), 0.0, float(dimensions.height_plates)),
            (0.0, float(dimensions.width_studs), 0.0),
            (float(dimensions.length_studs), float(dimensions.width_studs), 0.0),
            (
                float(dimensions.length_studs),
                float(dimensions.width_studs),
                float(dimensions.height_plates),
            ),
        )
        vertices = []
        for length, width, height in local_vertices:
            if placement.orientation_degrees == 0:
                horizontal = (base.x + length, base.y + width)
            elif placement.orientation_degrees == 90:
                horizontal = (base.x + width, base.y + length)
            elif placement.orientation_degrees == 180:
                horizontal = (base.x + dimensions.length_studs - length, base.y + width)
            else:
                horizontal = (base.x + width, base.y + dimensions.length_studs - length)
            vertices.append((horizontal[0], horizontal[1], base.z + height))
        slopes.append(tuple(vertices))
    return tuple(slopes)


def _model_dimensions(placements: tuple[BrickPlacement, ...]) -> ModelDimensions:
    maximum_x = 0
    maximum_y = 0
    maximum_z = 0
    for placement in placements:
        cells = _placement_cells(placement)
        maximum_x = max(maximum_x, max(cell.x for cell in cells) + 1)
        maximum_y = max(maximum_y, max(cell.y for cell in cells) + 1)
        placement_top = placement.position.z + placement.brick_type.dimensions.height_plates
        maximum_z = max(maximum_z, placement_top)

    return ModelDimensions(
        width_studs=maximum_x,
        depth_studs=maximum_y,
        height_plates=maximum_z,
        width_mm=maximum_x * STUD_WIDTH_MM,
        depth_mm=maximum_y * STUD_WIDTH_MM,
        height_mm=maximum_z * PLATE_HEIGHT_MM,
    )
