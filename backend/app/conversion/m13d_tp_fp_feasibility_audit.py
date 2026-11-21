"""Offline, no-solver diagnostics for the historical M13B candidate model.

The functions in this module measure geometry and encode no feasibility claim.
They deliberately operate on M13C's already reconstructed candidate list and
fixed-frame rasters, so they cannot submit or run a CP-SAT model.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Sequence

from app.conversion import core
from app.conversion.buildability import directly_supports
from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.surface_grid_v4 import _Candidate

Pixel = tuple[str, int, int]
VIEWS = ("front", "side", "top")


def candidate_pixel_accounting(
    candidates: Sequence[_Candidate],
    rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
) -> list[dict[str, object]]:
    """Describe each candidate's own raster footprint, without summing overlaps."""
    source = frozenset(source_pixels)
    locked = frozenset(locked_pixels)
    records: list[dict[str, object]] = []
    for candidate, pixels in zip(candidates, rasters, strict=True):
        footprint = frozenset(pixels)
        placement = candidate.placement
        views = {view: _pixel_counts(footprint, source, locked, view) for view in VIEWS}
        records.append(
            {
                "placementId": stable_placement_id(placement),
                "partId": placement.brick_type.part_id,
                "shape": placement.brick_type.shape,
                "dimensions": {
                    "lengthStuds": placement.brick_type.length_studs,
                    "widthStuds": placement.brick_type.width_studs,
                    "heightPlates": placement.brick_type.height_plates,
                },
                "orientationDegrees": placement.orientation_degrees,
                "position": {
                    "x": placement.position.x,
                    "y": placement.position.y,
                    "z": placement.position.z,
                },
                "views": views,
            }
        )
    return records


def coverage_alternatives(
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    rasters: Sequence[Collection[Pixel]],
) -> dict[str, object]:
    """Count eligible alternatives for source pixels; locked pixels remain distinct."""
    source = frozenset(source_pixels)
    locked = frozenset(locked_pixels)
    covering: dict[Pixel, int] = Counter(
        pixel for raster in rasters for pixel in frozenset(raster) if pixel in source
    )
    views: dict[str, object] = {}
    for view in VIEWS:
        pixels = [pixel for pixel in source if pixel[0] == view]
        frequency = Counter(covering[pixel] for pixel in pixels if pixel not in locked)
        views[view] = {
            "sourcePixels": len(pixels),
            "coveredByLockedGeometry": sum(pixel in locked for pixel in pixels),
            "zeroEligibleCandidateCoverage": sum(
                pixel not in locked and covering[pixel] == 0 for pixel in pixels
            ),
            "exactlyOneEligibleCandidate": sum(
                pixel not in locked and covering[pixel] == 1 for pixel in pixels
            ),
            "multipleEligibleCandidates": sum(
                pixel not in locked and covering[pixel] > 1 for pixel in pixels
            ),
            "candidateCoverageFrequency": {
                str(count): frequency[count] for count in sorted(frequency)
            },
        }
    return {
        "views": views,
        "interpretation": "Raster uniqueness is not global placement necessity.",
    }


def candidate_conflicts(
    candidates: Sequence[_Candidate], locked: Collection[core.BrickPlacement]
) -> dict[str, object]:
    """Build occupancy conflicts with an inverted-cell index and support possibilities."""
    by_cell: dict[core.GridPosition, list[int]] = defaultdict(list)
    for index, candidate in enumerate(candidates):
        for cell in candidate.cells:
            by_cell[cell].append(index)
    overlaps: set[tuple[int, int]] = set()
    for ids in by_cell.values():
        for offset, left in enumerate(ids):
            overlaps.update((left, right) for right in ids[offset + 1 :])

    supporters: dict[int, list[int]] = defaultdict(list)
    locked_supporters: dict[int, int] = {}
    for upper_index, upper in enumerate(candidates):
        for lower_index, lower in enumerate(candidates):
            if lower_index != upper_index and directly_supports(lower.placement, upper.placement):
                supporters[upper_index].append(lower_index)
        locked_supporters[upper_index] = sum(
            directly_supports(item, upper.placement) for item in locked
        )
    degrees = Counter(index for pair in overlaps for index in pair)
    return {
        "occupancyMutualExclusionPairCount": len(overlaps),
        "knownPhysicalCollisionPairCount": len(overlaps),
        "physicalCollisionNote": (
            "For this historical no-wedge candidate set, rectangular occupancy overlap is the "
            "CP-SAT pairwise exclusion; locked body collisions were filtered before eligibility."
        ),
        "conflictDegreeDistribution": {
            str(value): sum(degrees[index] == value for index in range(len(candidates)))
            for value in sorted(set(degrees.values()) | {0})
        },
        "candidatesWithNoKnownConflict": sum(
            degrees[index] == 0 for index in range(len(candidates))
        ),
        "possibleSupporterCountDistribution": {
            str(value): sum(len(supporters[index]) == value for index in range(len(candidates)))
            for value in sorted({len(supporters[index]) for index in range(len(candidates))})
        },
        "candidatesWithLockedSupporter": sum(value > 0 for value in locked_supporters.values()),
        "supportInterpretation": (
            "Supporter lists are possible CP-SAT support choices, not a selected or globally "
            "feasible support proof."
        ),
    }


def mandatory_coverage_pressure(
    required: Collection[Pixel],
    candidates: Sequence[_Candidate],
    locked: Collection[core.BrickPlacement],
) -> dict[str, object]:
    """Report the actual coarse projection constraints from M13B, not 128px evidence."""
    candidate_pixels = [_projection_pixels(candidate.cells) for candidate in candidates]
    locked_pixels = _projection_pixels(
        frozenset(cell for placement in locked for cell in core._placement_source_cells(placement))
    )
    required_set = frozenset(required)
    alternatives = Counter(
        sum(pixel in pixels for pixels in candidate_pixels)
        for pixel in required_set - locked_pixels
    )
    return {
        "requiredProjectionPixels": len(required_set),
        "coveredByLockedGeometry": len(required_set & locked_pixels),
        "requiringCandidateCoverage": len(required_set - locked_pixels),
        "candidateAlternativeFrequency": {
            str(count): alternatives[count] for count in sorted(alternatives)
        },
        "zeroAlternativeRequirements": alternatives[0],
        "singleAlternativeRequirements": alternatives[1],
        "interpretation": (
            "These coarse grid-projection constraints can select pieces whose 128px raster "
            "footprint includes extra pixels; alternatives do not establish simultaneous "
            "feasibility."
        ),
    }


def assembly_error_attribution(
    placements: Sequence[core.BrickPlacement],
    placement_rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
) -> dict[str, object]:
    """Attribute completed-assembly pixels without claiming removals remain legal."""
    source = frozenset(source_pixels)
    counts: Counter[Pixel] = Counter(
        pixel for raster in placement_rasters for pixel in frozenset(raster)
    )
    foreground = frozenset(counts)
    views: dict[str, object] = {}
    for view in VIEWS:
        output = {pixel for pixel in foreground if pixel[0] == view}
        source_view = {pixel for pixel in source if pixel[0] == view}
        false_positive = output - source_view
        views[view] = {
            "truePositives": len(output & source_view),
            "falsePositives": len(false_positive),
            "falseNegatives": len(source_view - output),
            "falsePositivePixelsWithOneSelectedPlacement": sum(
                counts[pixel] == 1 for pixel in false_positive
            ),
            "falsePositivePixelsWithMultipleSelectedPlacements": sum(
                counts[pixel] > 1 for pixel in false_positive
            ),
        }
    contributions = []
    for placement, raster in zip(placements, placement_rasters, strict=True):
        pixels = frozenset(raster)
        contributions.append(
            {
                "placementId": stable_placement_id(placement),
                "exclusivePixels": {
                    view: {
                        "truePositives": sum(
                            pixel[0] == view and pixel in source and counts[pixel] == 1
                            for pixel in pixels
                        ),
                        "falsePositives": sum(
                            pixel[0] == view and pixel not in source and counts[pixel] == 1
                            for pixel in pixels
                        ),
                    }
                    for view in VIEWS
                },
            }
        )
    return {
        "views": views,
        "selectedPlacementExclusiveContributions": contributions,
        "removalCounterfactual": (
            "Exclusive pixels are geometric-only. Removing a placement can violate mandatory "
            "coverage, support, the part model, or other constraints."
        ),
    }


def _pixel_counts(
    footprint: frozenset[Pixel], source: frozenset[Pixel], locked: frozenset[Pixel], view: str
) -> dict[str, int]:
    pixels = {pixel for pixel in footprint if pixel[0] == view}
    return {
        "foregroundPixels": len(pixels),
        "truePositives": len(pixels & source),
        "falsePositives": len(pixels - source),
        "sourceCoverageBeyondLockedGeometry": len((pixels & source) - locked),
        "falsePositivesBeyondLockedGeometry": len((pixels - source) - locked),
    }


def _projection_pixels(cells: Collection[core.GridPosition]) -> frozenset[Pixel]:
    return frozenset(
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )
