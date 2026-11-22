"""Exact offline attribution helpers for the M13F Duck coarse-coverage study."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Sequence

from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13d_tp_fp_feasibility_experiment import VIEWS
from app.conversion.surface_grid_v4 import _Candidate

Pixel = tuple[str, int, int]


def attribute_control_false_positives(
    *,
    candidates: Sequence[_Candidate],
    candidate_rasters: Sequence[Collection[Pixel]],
    selected_ids: Collection[int],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    historical_valid: Callable[[Collection[int]], bool],
) -> dict[str, object]:
    """Attribute one fixed Control selection without claiming joint removability."""
    selected = _selected_ids(selected_ids, len(candidates))
    if len(candidates) != len(candidate_rasters):
        raise ValueError("Candidates and candidate rasters must have matching lengths.")
    source, locked = frozenset(source_pixels), frozenset(locked_pixels)
    selected_rasters = {index: frozenset(candidate_rasters[index]) for index in selected}
    candidate_union = frozenset().union(*selected_rasters.values()) if selected else frozenset()
    control = locked | candidate_union
    control_fp = control - source
    overlaps = Counter(
        pixel
        for raster in selected_rasters.values()
        for pixel in raster
        if pixel in control_fp - locked
    )
    overlapping_candidate_indices = {
        f"{pixel[0]}:{pixel[1]}:{pixel[2]}": [
            index for index in selected if pixel in selected_rasters[index]
        ]
        for pixel in sorted(overlaps)
    }

    per_candidate: list[dict[str, object]] = []
    for index in selected:
        raster = selected_rasters[index]
        without = locked | frozenset().union(
            *(other for other_index, other in selected_rasters.items() if other_index != index)
        )
        removal_metrics = {
            view: _metrics(_view(source, view), _view(without, view)) for view in VIEWS
        }
        before_metrics = {
            view: _metrics(_view(source, view), _view(control, view)) for view in VIEWS
        }
        deltas = {
            view: {
                key: removal_metrics[view][key] - before_metrics[view][key]
                for key in ("truePositives", "falsePositives", "falseNegatives")
            }
            for view in VIEWS
        }
        removed_foreground = (control - without) & source
        removed_background = (control - without) - source
        per_candidate.append(
            {
                "candidateIndex": index,
                "placementId": stable_placement_id(candidates[index].placement),
                "footprint": _per_view_counts(raster, source),
                "additiveBackgroundFootprint": len(raster - source - locked),
                "uniqueProjectedFalsePositiveContribution": len(removed_background),
                "uniqueProjectedForegroundContribution": len(removed_foreground),
                "removal": {
                    "perViewDelta": deltas,
                    "removesImportantForegroundCoverage": bool(removed_foreground),
                    "historicalConstraintsSatisfied": historical_valid(
                        tuple(other for other in selected if other != index)
                    ),
                },
            }
        )
    return {
        "control": {
            "perView": {view: _metrics(_view(source, view), _view(control, view)) for view in VIEWS}
        },
        "falsePositivePartition": {
            "lockedGeometry": _per_view_pixel_counts(control_fp & locked),
            "selectedRectanglesNotLocked": _per_view_pixel_counts(control_fp - locked),
        },
        "selectedCandidateCount": len(selected),
        "selectedCandidates": per_candidate,
        "overlap": {
            "candidatePixelReferencesOnNonLockedControlFalsePositives": sum(overlaps.values()),
            "uniqueNonLockedControlFalsePositives": len(control_fp - locked),
            "pixelsByCoveringSelectedCandidateCount": {
                str(count): sum(value == count for value in overlaps.values())
                for count in sorted(set(overlaps.values()))
            },
            "candidateIndicesByNonLockedControlFalsePositivePixel": overlapping_candidate_indices,
        },
    }


def coarse_coverage_satisfied(
    *,
    candidates: Sequence[_Candidate],
    selected_ids: Collection[int],
    required_pixels: Collection[Pixel],
    fixed_coverage_pixels: Collection[Pixel],
) -> dict[str, object]:
    """Evaluate the historical coarse requirement from selected candidate cells."""
    selected = _selected_ids(selected_ids, len(candidates))
    coarse = frozenset(
        pixel
        for index in selected
        for cell in candidates[index].cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    )
    uncovered = frozenset(required_pixels) - frozenset(fixed_coverage_pixels) - coarse
    return {"satisfied": not uncovered, "uncoveredRequirementCount": len(uncovered)}


def support_preprocessing_caveat() -> str:
    """State why this experiment cannot serve as a support-family ablation."""
    return (
        "Removing CP-SAT support clauses from the current 1,449-candidate set would not "
        "reintroduce the 74 placements pruned during candidate generation. A full support-family "
        "ablation requires separately hashed candidate provenance and controlled re-enumeration."
    )


def _selected_ids(selected_ids: Collection[int], candidate_count: int) -> tuple[int, ...]:
    selected = tuple(sorted(selected_ids))
    if len(selected) != len(set(selected)) or any(
        index < 0 or index >= candidate_count for index in selected
    ):
        raise ValueError("Selected candidate indices must be unique and in range.")
    return selected


def _view(pixels: Collection[Pixel], view: str) -> frozenset[Pixel]:
    return frozenset(pixel for pixel in pixels if pixel[0] == view)


def _metrics(source: Collection[Pixel], output: Collection[Pixel]) -> dict[str, int]:
    return {
        "truePositives": len(set(source) & set(output)),
        "falsePositives": len(set(output) - set(source)),
        "falseNegatives": len(set(source) - set(output)),
    }


def _per_view_counts(
    pixels: Collection[Pixel], source: Collection[Pixel]
) -> dict[str, dict[str, int]]:
    return {
        view: {
            "foregroundPixels": len(_view(pixels, view) & _view(source, view)),
            "backgroundPixels": len(_view(pixels, view) - _view(source, view)),
        }
        for view in VIEWS
    }


def _per_view_pixel_counts(pixels: Collection[Pixel]) -> dict[str, int]:
    return {view: len(_view(pixels, view)) for view in VIEWS}
