"""Read-only evidence helpers for the M13F-B5 metric audit."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from app.conversion import core
from app.conversion.fidelity import render_silhouette_masks

PixelCounts = dict[str, int]


def frozen_source_pixel_counts(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
) -> PixelCounts:
    """Measure frozen silhouette-v1 source masks under one assembly's native bounds."""
    placement_tuple = tuple(placements)
    masks = render_silhouette_masks(
        source_vertices,
        faces,
        core._placement_boxes(placement_tuple),
        slope_vertices=core._slope_vertices(placement_tuple),
        wedge_vertices=core._wedge_vertices(placement_tuple),
    )
    return {
        view: sum(1 for pixel in source.get_flattened_data() if pixel)
        for view, (source, _) in masks.items()
    }


def frozen_semantics() -> str:
    """Describe the intentionally assembly-dependent legacy evaluator contract."""
    return (
        "Frozen silhouette-v1 computes padded projection bounds from the source and the "
        "candidate assembly together, then rasterizes both at 128x128 inside those bounds."
    )


def connectivity_recommendation() -> dict[str, str]:
    """Keep graph connectivity separate from claims of physical stability."""
    return {
        "productionChange": "NONE",
        "selectionPolicy": (
            "For silhouette-equivalent, mechanically valid assemblies, prefer fewer connected "
            "components and then fewer parts as deterministic secondary criteria."
        ),
        "caveat": (
            "Graph connectivity alone does not establish collision-free insertion order, strength, "
            "or real-world structural stability."
        ),
    }
