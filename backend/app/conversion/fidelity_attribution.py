"""Offline-only helpers for the M8B geometric-fidelity attribution experiment.

This module deliberately has no production imports.  It represents the
idealized stage as single grid cells, not as LEGO pieces: the source surface
voxelisation is a deterministic, bounded surrogate for a direct continuous
silhouette optimiser.  A cell is one stud by one stud by one plate.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from app.conversion import core
from app.conversion.fidelity import binary_mask_iou, render_silhouette_masks


@dataclass(frozen=True, slots=True)
class SilhouetteRecord:
    front: float
    side: float
    top: float
    mean: float
    false_positives: dict[str, int]
    false_negatives: dict[str, int]


def source_surface_cells(
    glb_bytes: bytes, *, grid_size: core.GridSize, up_axis: core.Axis
) -> tuple[frozenset[core.GridPosition], bool]:
    """Return V6-aligned source surface cells and source watertightness."""
    mesh = core._load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    occupancy = core._source_occupancy(
        core._normalize_vertices(vertices, up_axis), faces, grid_size
    )
    return occupancy.surface_cells, occupancy.mesh_is_watertight


def cell_boxes(
    cells: Collection[core.GridPosition],
) -> tuple[tuple[float, float, float, float, float, float], ...]:
    """Represent every occupied lattice cell as a unit axis-aligned box."""
    return tuple(
        (cell.x, cell.y, cell.z, cell.x + 1, cell.y + 1, cell.z + 1) for cell in sorted(cells)
    )


def score_cell_occupancy(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    cells: Collection[core.GridPosition],
) -> SilhouetteRecord:
    """Score one coherent 3D cell set with the frozen silhouette-v1 renderer."""
    masks = render_silhouette_masks(source_vertices, faces, cell_boxes(cells))
    scores: dict[str, float] = {}
    false_positives: dict[str, int] = {}
    false_negatives: dict[str, int] = {}
    for view, (source, output) in masks.items():
        scores[view] = binary_mask_iou(source, output)
        false_positives[view] = sum(
            bool(output_pixel) and not bool(source_pixel)
            for source_pixel, output_pixel in zip(
                source.get_flattened_data(), output.get_flattened_data(), strict=True
            )
        )
        false_negatives[view] = sum(
            bool(source_pixel) and not bool(output_pixel)
            for source_pixel, output_pixel in zip(
                source.get_flattened_data(), output.get_flattened_data(), strict=True
            )
        )
    return SilhouetteRecord(
        front=scores["front"],
        side=scores["side"],
        top=scores["top"],
        mean=round((scores["front"] + scores["side"] + scores["top"]) / 3, 6),
        false_positives=false_positives,
        false_negatives=false_negatives,
    )
