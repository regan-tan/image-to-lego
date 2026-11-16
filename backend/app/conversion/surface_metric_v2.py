"""Offline-only bounded surface-proxy metric for the M7B experiment.

This deliberately leaves the historical v1 metric untouched.  It samples the
same primitive placement surfaces as v1, but its fixed chunk sizes allow the
larger private reconstructed meshes to be observed within a bounded amount of
memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Final

import numpy as np

from app.conversion import benchmark, core

METRICS_VERSION: Final = "placement-surface-proxy-v2-chunked"
SAMPLE_COUNT: Final = 2_048
MAX_SOURCE_TRIANGLES: Final = 50_000
MAX_PLACEMENT_TRIANGLES: Final = 10_000
POINT_CHUNK_SIZE: Final = 128
TRIANGLE_CHUNK_SIZE: Final = 2_048
DEFAULT_TIMEOUT_SECONDS: Final = 30.0


@dataclass(frozen=True, slots=True)
class SurfaceMetricV2:
    metrics_version: str
    status: str
    reason: str | None
    sample_count_per_surface: int | None
    source_to_lego_mean_mm: float | None
    lego_to_source_mean_mm: float | None
    symmetric_mean_mm: float | None
    percentile_95_nearest_surface_mm: float | None
    source_bounding_box_diagonal_mm: float | None
    normalized_symmetric_mean: float | None
    volumetric_iou: None
    volumetric_status: str

    def record(self) -> dict[str, object]:
        return asdict(self)


def evaluate_surface_metric_v2(
    source_vertices: list[benchmark.Point3D],
    source_faces: list[benchmark.Face],
    placements: tuple[core.BrickPlacement, ...],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> SurfaceMetricV2:
    """Return deterministic source/placement distances or an explicit unavailable result."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    started = perf_counter()
    try:
        source = benchmark._triangles_from_mesh(source_vertices, source_faces)
        placement = benchmark._placement_triangles(placements)
        if len(source) == 0:
            return _unavailable("source mesh has no non-degenerate triangles")
        if len(placement) == 0:
            return _unavailable("converted model has no supported placement surfaces")
        if len(source) > MAX_SOURCE_TRIANGLES:
            return _unavailable("source triangle limit exceeded")
        if len(placement) > MAX_PLACEMENT_TRIANGLES:
            return _unavailable("placement triangle limit exceeded")
        if not np.all(np.isfinite(source)) or not np.all(np.isfinite(placement)):
            return _unavailable("surface geometry contains non-finite coordinates")
        source_mm = benchmark._grid_to_mm(source)
        placement_mm = benchmark._grid_to_mm(placement)
        source_samples = benchmark._sample_surface(source_mm, SAMPLE_COUNT)
        placement_samples = benchmark._sample_surface(placement_mm, SAMPLE_COUNT)
        source_to_lego = _nearest_distances(source_samples, placement_mm, started, timeout_seconds)
        lego_to_source = _nearest_distances(placement_samples, source_mm, started, timeout_seconds)
        distances = np.concatenate((source_to_lego, lego_to_source))
        if not np.all(np.isfinite(distances)):
            return _unavailable("nearest-surface calculation was non-finite")
        source_mean = float(source_to_lego.mean())
        placement_mean = float(lego_to_source.mean())
        symmetric = (source_mean + placement_mean) / 2
        diagonal = benchmark._bounding_diagonal_mm(source_mm)
        return SurfaceMetricV2(
            METRICS_VERSION,
            "available",
            None,
            SAMPLE_COUNT,
            round(source_mean, 6),
            round(placement_mean, 6),
            round(symmetric, 6),
            round(float(np.percentile(distances, 95)), 6),
            round(diagonal, 6),
            round(symmetric / diagonal, 6) if diagonal else None,
            None,
            "not_computed",
        )
    except _MetricTimeout:
        return _unavailable("metric observation timeout exceeded")
    except (MemoryError, ValueError, FloatingPointError, np.linalg.LinAlgError) as error:
        return _unavailable(f"metric calculation failed: {error}")


class _MetricTimeout(Exception):
    pass


def _nearest_distances(
    points: np.ndarray, triangles: np.ndarray, started: float, timeout_seconds: float
) -> np.ndarray:
    result = np.empty(len(points), dtype=float)
    for point_start in range(0, len(points), POINT_CHUNK_SIZE):
        _check_timeout(started, timeout_seconds)
        point_chunk = points[point_start : point_start + POINT_CHUNK_SIZE]
        nearest = np.full(len(point_chunk), np.inf, dtype=float)
        for triangle_start in range(0, len(triangles), TRIANGLE_CHUNK_SIZE):
            _check_timeout(started, timeout_seconds)
            triangle_chunk = triangles[triangle_start : triangle_start + TRIANGLE_CHUNK_SIZE]
            squared = benchmark._nearest_squared_distances(point_chunk, triangle_chunk)
            nearest = np.minimum(nearest, squared)
        result[point_start : point_start + len(point_chunk)] = np.sqrt(nearest)
    return result


def _check_timeout(started: float, timeout_seconds: float) -> None:
    if perf_counter() - started > timeout_seconds:
        raise _MetricTimeout


def _unavailable(reason: str) -> SurfaceMetricV2:
    return SurfaceMetricV2(
        METRICS_VERSION,
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
    )
