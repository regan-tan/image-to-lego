"""Record intermediate V6 grid geometry for a SHA-pinned local M7B corpus.

This is an offline investigation tool.  It imports converter internals so that
its stage counts describe the production converter exactly; it does not change
conversion behavior or write any source-model data to its output.
"""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core  # noqa: E402
from app.conversion.real_world_benchmark import (  # noqa: E402
    load_manifest,
    verify_case_source,
)
from app.conversion.surface_grid_v4 import projection_hull_target  # noqa: E402


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-parts", type=int, default=24)
    parser.add_argument("--max-parts", type=int, default=60)
    return parser.parse_args()


def _projected_cells(cells: frozenset[core.GridPosition]) -> dict[str, frozenset[tuple[int, int]]]:
    return {
        "front": frozenset((cell.x, cell.z) for cell in cells),
        "side": frozenset((cell.y, cell.z) for cell in cells),
        "top": frozenset((cell.x, cell.y) for cell in cells),
    }


def _projection_delta(
    source_cells: frozenset[core.GridPosition], output_cells: frozenset[core.GridPosition]
) -> dict[str, dict[str, int]]:
    source = _projected_cells(source_cells)
    output = _projected_cells(output_cells)
    return {
        view: {
            "sourcePixels": len(source[view]),
            "outputPixels": len(output[view]),
            "falsePositivePixels": len(output[view] - source[view]),
            "falseNegativePixels": len(source[view] - output[view]),
        }
        for view in ("front", "side", "top")
    }


def _case_diagnostic(
    source: bytes, target_parts: int, max_parts: int, up_axis: core.Axis
) -> dict[str, object]:
    effective_target = min(
        target_parts,
        max(1, max_parts // core.RELIABLE_HARD_CAP_GRID_DIVISOR),
    )
    settings = core.ConversionSettings(
        target_parts=target_parts,
        max_parts=max_parts,
        up_axis=up_axis,
        algorithm_version=core.SURFACE_GRID_V6_SHAPE_AWARE,
    )
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, settings.up_axis)
    v3 = core._convert_surface_grid_v3(
        source,
        core.ConversionSettings(target_parts=effective_target, up_axis=settings.up_axis),
    )
    occupancy = core._source_occupancy(normalized, faces, v3.metadata.grid_size)
    locked, locked_cells = core._place_supported_slopes(occupancy.surface_cells)
    locked_occupied = frozenset(
        cell for placement in locked for cell in core._placement_source_cells(placement)
    )
    exterior = frozenset(
        cell
        for placement in v3.placements
        if placement.brick_type.shape == "rectangular"
        for cell in core._placement_cells(placement)
        if cell not in locked_occupied
    )
    protected = core._v5_protected_empty_cells(occupancy, v3.metadata.grid_size)
    hull, required_pixels = projection_hull_target(
        exterior, locked_cells, v3.metadata.grid_size, protected_empty_cells=protected
    )
    hull = hull - locked_occupied
    model = core.convert_glb(source, settings)
    final_cells = frozenset(
        cell for placement in model.placements for cell in core._placement_source_cells(placement)
    )
    source_cells = occupancy.surface_cells
    return {
        "sourceSha256": sha256(source).hexdigest(),
        "effectiveGridTargetParts": effective_target,
        "gridDimensions": {
            "widthStuds": v3.metadata.grid_size.width_studs,
            "depthStuds": v3.metadata.grid_size.depth_studs,
            "heightPlates": v3.metadata.grid_size.height_plates,
        },
        "physicalDimensionsMm": {
            "width": v3.metadata.grid_size.width_studs * core.STUD_WIDTH_MM,
            "depth": v3.metadata.grid_size.depth_studs * core.STUD_WIDTH_MM,
            "height": v3.metadata.grid_size.height_plates * core.PLATE_HEIGHT_MM,
        },
        "cellCounts": {
            "grid": v3.metadata.grid_size.cell_count,
            "sourceSurface": len(source_cells),
            "v3RectangularExterior": len(exterior),
            "lockedSlope": len(locked_occupied),
            "projectionHullCandidate": len(hull),
            "projectionHullOnly": len(hull - source_cells),
            "protectedEmpty": len(protected),
            "finalOccupied": len(final_cells),
            "finalOnly": len(final_cells - source_cells),
            "sourceMissedByFinal": len(source_cells - final_cells),
            "requiredProjectionPixels": len(required_pixels),
        },
        "finalProjectionDeltaFromSourceSurface": _projection_delta(source_cells, final_cells),
        "partCount": model.part_count,
        "diagnostics": None
        if model.metadata.diagnostics is None
        else {
            "candidateCountBeforeProtection": (
                model.metadata.diagnostics.candidate_count_before_protection
            ),
            "candidateCountAfterProtection": (
                model.metadata.diagnostics.candidate_count_after_protection
            ),
            "candidateCountAfterReachabilityPruning": (
                model.metadata.diagnostics.candidate_count_after_reachability_pruning
            ),
            "shapeAwareAccepted": model.metadata.diagnostics.shape_aware_accepted_refinement_count,
            "shapeAwareRejected": model.metadata.diagnostics.shape_aware_rejected_refinement_count,
        },
    }


def run_diagnostic(
    manifest_path: Path, output_path: Path, target_parts: int, max_parts: int
) -> None:
    """Write deterministic stage counts for every SHA-pinned manifest source."""
    manifest = load_manifest(manifest_path)
    results: dict[str, object] = {
        "schemaVersion": "m7b-stage-attribution-v1",
        "targetParts": target_parts,
        "maxParts": max_parts,
        "cases": {},
    }
    cases = results["cases"]
    assert isinstance(cases, dict)
    for case in manifest.cases:
        if case.target_parts != target_parts:
            raise ValueError(
                "The requested target parts must match every manifest case for this diagnostic."
            )
        source = verify_case_source(case)
        cases[case.case_id] = _case_diagnostic(source, target_parts, max_parts, case.up_axis)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    arguments = parse_arguments()
    run_diagnostic(
        arguments.manifest, arguments.output, arguments.target_parts, arguments.max_parts
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
