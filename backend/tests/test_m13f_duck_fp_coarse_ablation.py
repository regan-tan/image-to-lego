from __future__ import annotations

from app.conversion import core
from app.conversion.m13e_duck_iou_incidence_compression import build_compressed_iou_dominance_model
from app.conversion.m13f_duck_fp_coarse_ablation import (
    attribute_control_false_positives,
    coarse_coverage_satisfied,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(index: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(index, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def test_attribution_separates_locked_and_overlapping_candidate_false_positives() -> None:
    result = attribute_control_false_positives(
        candidates=(_candidate(0), _candidate(1)),
        candidate_rasters=(
            {("front", 0, 0), ("front", 9, 0)},
            {("front", 1, 0), ("front", 9, 0)},
        ),
        selected_ids=(0, 1),
        source_pixels={("front", 0, 0), ("front", 1, 0)},
        locked_pixels={("front", 8, 0)},
        historical_valid=lambda selected: bool(selected),
    )

    assert result["falsePositivePartition"] == {
        "lockedGeometry": {"front": 1, "side": 0, "top": 0},
        "selectedRectanglesNotLocked": {"front": 1, "side": 0, "top": 0},
    }
    assert result["overlap"]["candidatePixelReferencesOnNonLockedControlFalsePositives"] == 2
    assert result["overlap"]["uniqueNonLockedControlFalsePositives"] == 1
    assert result["overlap"]["candidateIndicesByNonLockedControlFalsePositivePixel"] == {
        "front:9:0": [0, 1]
    }
    assert result["selectedCandidates"][0]["uniqueProjectedFalsePositiveContribution"] == 0
    assert result["selectedCandidates"][1]["uniqueProjectedFalsePositiveContribution"] == 0


def test_coarse_coverage_toggle_evaluation_is_exact() -> None:
    candidates = (_candidate(0),)
    required = {("front", 0, 0), ("side", 0, 0), ("top", 0, 0)}

    assert coarse_coverage_satisfied(
        candidates=candidates, selected_ids=(0,), required_pixels=required, fixed_coverage_pixels=()
    ) == {"satisfied": True, "uncoveredRequirementCount": 0}
    assert coarse_coverage_satisfied(
        candidates=candidates, selected_ids=(), required_pixels=required, fixed_coverage_pixels=()
    ) == {"satisfied": False, "uncoveredRequirementCount": 3}


def test_compressed_model_can_remove_only_mandatory_coverage_constraints() -> None:
    candidates = (_candidate(0),)
    common = {
        "candidates": candidates,
        "candidate_rasters": (set(),),
        "source_pixels": {("front", 0, 0), ("side", 0, 0), ("top", 0, 0)},
        "locked_pixels": (),
        "required_pixels": {("front", 0, 0)},
        "locked_placements": (),
        "target_cells": {candidates[0].placement.position},
        "fixed_coverage_pixels": (),
        "control_views": {
            view: {"truePositives": 0, "falsePositives": 0} for view in ("front", "side", "top")
        },
        "max_parts": 1,
        "require_strict_improvement": False,
        "enforce_iou_constraints": False,
    }
    historical, _ = build_compressed_iou_dominance_model(**common)
    relaxed, _ = build_compressed_iou_dominance_model(**common, enforce_mandatory_coverage=False)

    assert historical.component_counts["mandatory_coverage"].constraints == 1
    assert relaxed.component_counts["mandatory_coverage"].constraints == 0
