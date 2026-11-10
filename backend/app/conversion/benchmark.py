"""Offline, deterministic diagnostics for the conversion fidelity benchmark.

This module deliberately depends on the converter's internal coordinate helpers:
the benchmark measures the source in exactly the normalized grid coordinate system
used by ``convert_glb``.  It is not used by production conversion.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Final, cast

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from app.conversion import core

BENCHMARK_SCHEMA_VERSION: Final = "conversion-benchmark-v1"
FIXTURE_VERSION: Final = "synthetic-fixtures-v1"
GEOMETRY_METRICS_VERSION: Final = "placement-surface-proxy-v1"
SURFACE_SAMPLE_COUNT: Final = 384
MAX_SURFACE_TRIANGLES: Final = 20_000
NEAREST_SURFACE_BATCH_SIZE: Final = 16
OVERLAY_LEGEND_HEIGHT: Final = 26
OVERLAP_COLOR: Final = (48, 158, 76)
MISSING_COLOR: Final = (218, 74, 117)
EXTRA_COLOR: Final = (237, 143, 45)
BACKGROUND_COLOR: Final = (255, 255, 255)

Point3D = tuple[float, float, float]
Face = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class SyntheticCase:
    case_id: str
    name: str
    expected_characteristic: str
    default_target_parts: int
    up_axis: core.Axis
    mesh: trimesh.Trimesh


@dataclass(frozen=True, slots=True)
class GeometricMetrics:
    metrics_version: str
    status: str
    reason: str | None
    sample_count_per_surface: int | None
    symmetric_chamfer_mm: float | None
    percentile_95_nearest_surface_mm: float | None
    normalized_symmetric_chamfer: float | None
    source_to_lego_mean_mm: float | None
    lego_to_source_mean_mm: float | None
    source_bounding_box_diagonal_mm: float | None
    volumetric_iou: float | None
    volumetric_status: str
    volumetric_reason: str | None


@dataclass(frozen=True, slots=True)
class OpeningDiagnostic:
    status: str
    view: str
    protected_void_pixels: int | None
    filled_void_pixels: int | None
    filled_void_ratio: float | None
    reason: str | None


def synthetic_cases() -> tuple[SyntheticCase, ...]:
    """Return a stable, modest-size suite without committing binary fixtures."""
    return (
        _case("box", "Rectangular box", "axis-aligned volume", 12, trimesh.creation.box((4, 3, 2))),
        _case(
            "thin-wall", "Thin wall", "thin planar detail", 12, trimesh.creation.box((5, 0.35, 3))
        ),
        _case(
            "sphere",
            "Icosphere",
            "smooth curved surface",
            16,
            trimesh.creation.icosphere(subdivisions=2, radius=1.8),
        ),
        _case(
            "cylinder",
            "Cylinder",
            "round vertical profile",
            16,
            trimesh.creation.cylinder(radius=1.5, height=3.6, sections=20),
        ),
        _case("pyramid", "Square pyramid", "sloped roof faces", 16, _pyramid_mesh()),
        _case("l-profile", "L-shaped compound", "concave top footprint", 16, _l_profile_mesh()),
        _case(
            "ring",
            "Ring with opening",
            "through-opening visible in top projection",
            16,
            _ring_mesh(),
        ),
        _case("open-box", "Open box", "non-watertight robustness case", 12, _open_box_mesh()),
    )


def glb_bytes(mesh: trimesh.Trimesh) -> bytes:
    """Export deterministic fixture bytes through the existing trimesh dependency."""
    exported = mesh.export(file_type="glb")
    if not isinstance(exported, bytes):
        raise ValueError("Synthetic fixture did not export GLB bytes.")
    return exported


def aligned_source_mesh(
    source: bytes, settings: core.ConversionSettings, grid_size: core.GridSize
) -> tuple[trimesh.Trimesh, list[Point3D], list[Face]]:
    """Load and transform source vertices exactly as the converter does."""
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, settings.up_axis)
    scaled = core._scale_vertices_to_grid(normalized, grid_size)
    return mesh, scaled, faces


def evaluate_geometric_fidelity(
    source_vertices: list[Point3D],
    source_faces: list[Face],
    placements: tuple[core.BrickPlacement, ...],
    *,
    sample_count: int = SURFACE_SAMPLE_COUNT,
) -> GeometricMetrics:
    """Measure a bounded symmetric nearest-surface distance in physical millimetres.

    LEGO faces are an exterior-surface proxy: primitive triangles are sampled,
    but inter-part faces are not fully boolean-unioned away. The metric is
    intentionally named as a proxy rather than exact exterior geometry.
    """
    if sample_count <= 0:
        raise ValueError("sample_count must be greater than zero.")
    if not np.all(np.isfinite(np.asarray(source_vertices, dtype=float))):
        return _unavailable_geometry("source surface geometry contains non-finite coordinates")
    source_triangles = _triangles_from_mesh(source_vertices, source_faces)
    lego_triangles = _placement_triangles(placements)
    if len(source_triangles) == 0:
        return _unavailable_geometry("source mesh has no non-degenerate triangles")
    if len(lego_triangles) == 0:
        return _unavailable_geometry("converted model has no supported placement surfaces")
    if not np.all(np.isfinite(source_triangles)) or not np.all(np.isfinite(lego_triangles)):
        return _unavailable_geometry("surface geometry contains non-finite coordinates")
    if len(source_triangles) > MAX_SURFACE_TRIANGLES or len(lego_triangles) > MAX_SURFACE_TRIANGLES:
        return _unavailable_geometry("surface triangle limit exceeded")

    source_mm = _grid_to_mm(source_triangles)
    lego_mm = _grid_to_mm(lego_triangles)
    source_samples = _sample_surface(source_mm, sample_count)
    lego_samples = _sample_surface(lego_mm, sample_count)
    source_to_lego = _nearest_surface_distances(source_samples, lego_mm)
    lego_to_source = _nearest_surface_distances(lego_samples, source_mm)
    all_distances = np.concatenate((source_to_lego, lego_to_source))
    if not np.all(np.isfinite(all_distances)):
        return _unavailable_geometry("nearest-surface calculation was non-finite")
    diagonal = _bounding_diagonal_mm(source_mm)
    symmetric = float((source_to_lego.mean() + lego_to_source.mean()) / 2)
    return GeometricMetrics(
        metrics_version=GEOMETRY_METRICS_VERSION,
        status="available",
        reason=None,
        sample_count_per_surface=sample_count,
        symmetric_chamfer_mm=round(symmetric, 6),
        percentile_95_nearest_surface_mm=round(float(np.percentile(all_distances, 95)), 6),
        normalized_symmetric_chamfer=round(symmetric / diagonal, 6) if diagonal else None,
        source_to_lego_mean_mm=round(float(source_to_lego.mean()), 6),
        lego_to_source_mean_mm=round(float(lego_to_source.mean()), 6),
        source_bounding_box_diagonal_mm=round(diagonal, 6),
        volumetric_iou=None,
        volumetric_status="not_computed",
        volumetric_reason=(
            "No shape-faithful common volumetric discretization is defined for this milestone."
        ),
    )


def opening_void_diagnostic(
    masks: dict[str, tuple[Image.Image, Image.Image]],
) -> OpeningDiagnostic:
    """Report LEGO coverage inside source-enclosed voids in the top projection only."""
    source, output = masks["top"]
    protected = _enclosed_empty_pixels(source)
    if not protected:
        return OpeningDiagnostic(
            "not_applicable", "top", None, None, None, "no enclosed top-view void"
        )
    filled = sum(bool(output.getpixel(point)) for point in protected)
    return OpeningDiagnostic(
        "available",
        "top",
        len(protected),
        filled,
        round(filled / len(protected), 6),
        None,
    )


def make_overlay(source: Image.Image, output: Image.Image) -> Image.Image:
    """Create a fixed-color diagnostic image: green overlap, magenta missing, orange extra."""
    if source.size != output.size:
        raise ValueError("Source and output masks must have matching sizes.")
    image = Image.new(
        "RGB", (source.width, source.height + OVERLAY_LEGEND_HEIGHT), BACKGROUND_COLOR
    )
    pixels = image.load()
    assert pixels is not None
    for y in range(source.height):
        for x in range(source.width):
            source_filled = bool(source.getpixel((x, y)))
            output_filled = bool(output.getpixel((x, y)))
            if source_filled and output_filled:
                pixels[x, y] = OVERLAP_COLOR
            elif source_filled:
                pixels[x, y] = MISSING_COLOR
            elif output_filled:
                pixels[x, y] = EXTRA_COLOR
    draw = ImageDraw.Draw(image)
    labels = ((OVERLAP_COLOR, "overlap"), (MISSING_COLOR, "missing"), (EXTRA_COLOR, "extra"))
    for index, (color, label) in enumerate(labels):
        left = 2 + index * 42
        draw.rectangle((left, source.height + 4, left + 7, source.height + 11), fill=color)
        draw.text((left, source.height + 13), label, fill=(0, 0, 0))
    return image


def case_record(
    *,
    case_id: str,
    case_name: str,
    source: bytes,
    settings: core.ConversionSettings,
    model: core.LegoModel,
    source_mesh: trimesh.Trimesh,
    source_faces: list[Face],
    geometric: GeometricMetrics,
    opening: OpeningDiagnostic,
    runtime_seconds: float,
    expected_characteristic: str | None = None,
) -> dict[str, object]:
    """Build the stable benchmark record without changing production metadata."""
    fidelity = asdict(model.metadata.fidelity)
    return {
        "schemaVersion": BENCHMARK_SCHEMA_VERSION,
        "status": "completed",
        "caseId": case_id,
        "caseName": case_name,
        "expectedCharacteristic": expected_characteristic,
        "fixtureVersion": FIXTURE_VERSION if expected_characteristic is not None else None,
        "sourceSha256": sha256(source).hexdigest(),
        "algorithmVersion": settings.algorithm_version,
        "upAxis": settings.up_axis.value,
        "converterSettings": {
            "targetParts": settings.target_parts,
            "experimentalStagedWedgeRefinement": settings.experimental_staged_wedge_refinement,
        },
        "gridDimensions": {
            "widthStuds": model.metadata.grid_size.width_studs,
            "depthStuds": model.metadata.grid_size.depth_studs,
            "heightPlates": model.metadata.grid_size.height_plates,
        },
        "source": {
            "triangleCount": len(source_faces),
            "watertight": bool(source_mesh.is_watertight),
            "coordinateAlignment": "normalized-source-to-converter-grid-v1",
        },
        "parts": {
            "target": settings.target_parts,
            "actual": model.part_count,
            "delta": model.part_count - settings.target_parts,
            "errorRatio": round(
                abs(model.part_count - settings.target_parts) / settings.target_parts, 6
            ),
        },
        "silhouette": fidelity,
        "geometric": asdict(geometric),
        "openingDiagnostic": asdict(opening),
        "runtime": {"seconds": round(runtime_seconds, 6), "environmentDependent": True},
    }


def failed_record(case_id: str, case_name: str, reason: str) -> dict[str, object]:
    return {
        "schemaVersion": BENCHMARK_SCHEMA_VERSION,
        "status": "failed",
        "caseId": case_id,
        "caseName": case_name,
        "failureReason": reason,
    }


def _case(
    case_id: str,
    name: str,
    characteristic: str,
    target: int,
    mesh: trimesh.Trimesh,
) -> SyntheticCase:
    return SyntheticCase(case_id, name, characteristic, target, core.Axis.Y, mesh)


def _pyramid_mesh() -> trimesh.Trimesh:
    vertices = np.array(((-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0), (0, 0, 3)), dtype=float)
    faces = np.array(((0, 1, 2), (0, 2, 3), (0, 4, 1), (1, 4, 2), (2, 4, 3), (3, 4, 0)))
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _l_profile_mesh() -> trimesh.Trimesh:
    return cast(
        trimesh.Trimesh,
        trimesh.util.concatenate(
            (trimesh.creation.box((4, 1.4, 2)), trimesh.creation.box((1.4, 4, 2)))
        ),
    )


def _ring_mesh() -> trimesh.Trimesh:
    vertices: list[tuple[float, float, float]] = []
    faces: list[Face] = []
    segments = 20
    for z in (-0.4, 0.4):
        for radius in (0.8, 1.8):
            vertices.extend(
                (
                    radius * np.cos(2 * np.pi * index / segments),
                    radius * np.sin(2 * np.pi * index / segments),
                    z,
                )
                for index in range(segments)
            )
    for index in range(segments):
        next_index = (index + 1) % segments
        bottom_inner, bottom_outer = index, segments + index
        top_inner, top_outer = 2 * segments + index, 3 * segments + index
        bottom_inner_next, bottom_outer_next = next_index, segments + next_index
        top_inner_next, top_outer_next = 2 * segments + next_index, 3 * segments + next_index
        faces.extend(
            (
                (bottom_inner, bottom_outer, bottom_outer_next),
                (bottom_inner, bottom_outer_next, bottom_inner_next),
            )
        )
        faces.extend(
            ((top_inner, top_outer_next, top_outer), (top_inner, top_inner_next, top_outer_next))
        )
        faces.extend(
            (
                (bottom_inner, bottom_inner_next, top_inner_next),
                (bottom_inner, top_inner_next, top_inner),
            )
        )
        faces.extend(
            (
                (bottom_outer, top_outer_next, bottom_outer_next),
                (bottom_outer, top_outer, top_outer_next),
            )
        )
    # Source Y is converted to LEGO Z for the suite's Y-up setting. Swapping
    # source Y/Z makes the annulus visible as a top-view through-opening.
    source_vertices = np.asarray(vertices, dtype=float)[:, (0, 2, 1)]
    return trimesh.Trimesh(vertices=source_vertices, faces=np.array(faces), process=False)


def _open_box_mesh() -> trimesh.Trimesh:
    mesh = trimesh.creation.box((3, 2, 2))
    top_face_indices = np.where(mesh.face_normals[:, 2] > 0.9)[0]
    return trimesh.Trimesh(
        vertices=mesh.vertices, faces=np.delete(mesh.faces, top_face_indices, axis=0), process=False
    )


def _triangles_from_mesh(vertices: list[Point3D], faces: list[Face]) -> np.ndarray:
    points = np.asarray(vertices, dtype=float)
    triangles = points[np.asarray(faces, dtype=int)]
    return _non_degenerate_triangles(triangles)


def _placement_triangles(placements: tuple[core.BrickPlacement, ...]) -> np.ndarray:
    triangles: list[np.ndarray] = []
    for placement in placements:
        if placement.brick_type.shape == "rectangular":
            triangles.append(_box_triangles(core._placement_boxes((placement,))[0]))
    for vertices in core._slope_vertices(placements):
        triangles.append(_slope_triangles(vertices))
    for vertices in core._wedge_vertices(placements):
        triangles.append(_prism_triangles(vertices))
    if not triangles:
        return np.empty((0, 3, 3), dtype=float)
    return _non_degenerate_triangles(np.concatenate(triangles))


def _box_triangles(box: tuple[float, float, float, float, float, float]) -> np.ndarray:
    minimum_x, minimum_y, minimum_z, maximum_x, maximum_y, maximum_z = box
    vertices = np.array(
        (
            (minimum_x, minimum_y, minimum_z),
            (maximum_x, minimum_y, minimum_z),
            (maximum_x, maximum_y, minimum_z),
            (minimum_x, maximum_y, minimum_z),
            (minimum_x, minimum_y, maximum_z),
            (maximum_x, minimum_y, maximum_z),
            (maximum_x, maximum_y, maximum_z),
            (minimum_x, maximum_y, maximum_z),
        ),
        dtype=float,
    )
    faces = np.array(
        (
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (1, 2, 6),
            (1, 6, 5),
            (2, 3, 7),
            (2, 7, 6),
            (3, 0, 4),
            (3, 4, 7),
        )
    )
    return cast(np.ndarray, vertices[faces])


def _slope_triangles(vertices: tuple[Point3D, ...]) -> np.ndarray:
    faces = np.array(
        ((0, 1, 2), (3, 5, 4), (0, 4, 1), (0, 3, 4), (1, 4, 5), (1, 5, 2), (0, 2, 5), (0, 5, 3))
    )
    return cast(np.ndarray, np.asarray(vertices, dtype=float)[faces])


def _prism_triangles(vertices: tuple[Point3D, ...]) -> np.ndarray:
    half = len(vertices) // 2
    faces: list[Face] = []
    for index in range(1, half - 1):
        faces.extend(((0, index, index + 1), (half, half + index + 1, half + index)))
    for index in range(half):
        next_index = (index + 1) % half
        faces.extend(
            ((index, next_index, half + next_index), (index, half + next_index, half + index))
        )
    return cast(np.ndarray, np.asarray(vertices, dtype=float)[np.asarray(faces, dtype=int)])


def _non_degenerate_triangles(triangles: np.ndarray) -> np.ndarray:
    areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1
    )
    return triangles[areas > 1e-12]


def _grid_to_mm(triangles: np.ndarray) -> np.ndarray:
    return cast(
        np.ndarray,
        triangles * np.array((core.STUD_WIDTH_MM, core.STUD_WIDTH_MM, core.PLATE_HEIGHT_MM)),
    )


def _sample_surface(triangles: np.ndarray, count: int) -> np.ndarray:
    double_areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]), axis=1
    )
    cumulative = np.cumsum(double_areas)
    total = cumulative[-1]
    positions = (np.arange(count, dtype=float) + 0.5) / count * total
    indices = np.searchsorted(cumulative, positions, side="right")
    first = _radical_inverse(np.arange(1, count + 1), 2)
    second = _radical_inverse(np.arange(1, count + 1), 3)
    root_first = np.sqrt(first)
    weights = np.column_stack((1 - root_first, root_first * (1 - second), root_first * second))
    return cast(np.ndarray, np.einsum("ij,ijk->ik", weights, triangles[indices]))


def _radical_inverse(values: np.ndarray, base: int) -> np.ndarray:
    result = np.zeros(len(values), dtype=float)
    fraction = 1.0 / base
    current = values.copy()
    while np.any(current):
        result += fraction * (current % base)
        current //= base
        fraction /= base
    return result


def _nearest_surface_distances(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Return exact nearest-triangle distances in batches bounded by sample count."""
    results: list[np.ndarray] = []
    for start in range(0, len(points), NEAREST_SURFACE_BATCH_SIZE):
        batch = points[start : start + NEAREST_SURFACE_BATCH_SIZE]
        results.append(np.sqrt(_nearest_squared_distances(batch, triangles)))
    return np.concatenate(results)


def _nearest_squared_distances(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    point = points[:, np.newaxis, :]
    first = triangles[np.newaxis, :, 0, :]
    second = triangles[np.newaxis, :, 1, :]
    third = triangles[np.newaxis, :, 2, :]
    first_second = second - first
    first_third = third - first
    normal = np.cross(first_second, first_third)
    normal_squared = np.sum(normal * normal, axis=2)
    offset = point - first
    projected = (
        point
        - np.sum(offset * normal, axis=2, keepdims=True) / normal_squared[:, :, np.newaxis] * normal
    )
    dot00 = np.sum(first_second * first_second, axis=2)
    dot01 = np.sum(first_second * first_third, axis=2)
    dot11 = np.sum(first_third * first_third, axis=2)
    projected_offset = projected - first
    denominator = dot00 * dot11 - dot01 * dot01
    coordinate_v = (
        dot11 * np.sum(projected_offset * first_second, axis=2)
        - dot01 * np.sum(projected_offset * first_third, axis=2)
    ) / denominator
    coordinate_w = (
        dot00 * np.sum(projected_offset * first_third, axis=2)
        - dot01 * np.sum(projected_offset * first_second, axis=2)
    ) / denominator
    inside = (coordinate_v >= 0) & (coordinate_w >= 0) & (coordinate_v + coordinate_w <= 1)
    plane_distance = np.sum((point - projected) ** 2, axis=2)
    plane_distance = np.where(inside, plane_distance, np.inf)
    edge_distances = (
        _point_segment_squared(point, first, second),
        _point_segment_squared(point, second, third),
        _point_segment_squared(point, third, first),
    )
    return np.minimum(plane_distance, np.minimum.reduce(edge_distances)).min(axis=1)


def _point_segment_squared(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    vector = end - start
    fraction = np.sum((points - start) * vector, axis=2) / np.sum(vector * vector, axis=2)
    closest = start + np.clip(fraction, 0.0, 1.0)[:, :, np.newaxis] * vector
    return np.sum((points - closest) ** 2, axis=2)


def _bounding_diagonal_mm(triangles: np.ndarray) -> float:
    points = triangles.reshape(-1, 3)
    return float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))


def _unavailable_geometry(reason: str) -> GeometricMetrics:
    return GeometricMetrics(
        GEOMETRY_METRICS_VERSION,
        "unavailable",
        reason,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "not_computed",
        "No geometry metric is available.",
    )


def _enclosed_empty_pixels(mask: Image.Image) -> set[tuple[int, int]]:
    empty = {
        (x, y)
        for y in range(mask.height)
        for x in range(mask.width)
        if not bool(mask.getpixel((x, y)))
    }
    exterior = {(x, y) for x, y in empty if x in (0, mask.width - 1) or y in (0, mask.height - 1)}
    pending: deque[tuple[int, int]] = deque(exterior)
    while pending:
        x, y = pending.popleft()
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if neighbor in empty and neighbor not in exterior:
                exterior.add(neighbor)
                pending.append(neighbor)
    return empty - exterior
