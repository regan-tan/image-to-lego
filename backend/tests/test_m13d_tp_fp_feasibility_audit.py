from __future__ import annotations

from app.conversion import core
from app.conversion.m13d_tp_fp_feasibility_audit import (
    assembly_error_attribution,
    candidate_conflicts,
    candidate_pixel_accounting,
    coverage_alternatives,
    mandatory_coverage_pressure,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(x: int, y: int, z: int, part_id: str = "3024") -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID[part_id], core.GridPosition(x, y, z), 0)
    return _Candidate(placement, core._placement_cells(placement))


def test_candidate_pixels_separate_locked_geometry_and_do_not_assume_marginality() -> None:
    candidate = _candidate(0, 0, 0)
    pixel = ("front", 0, 0)
    result = candidate_pixel_accounting((candidate,), ({pixel, ("front", 1, 0)},), {pixel}, {pixel})

    assert result[0]["views"]["front"] == {
        "foregroundPixels": 2,
        "truePositives": 1,
        "falsePositives": 1,
        "sourceCoverageBeyondLockedGeometry": 0,
        "falsePositivesBeyondLockedGeometry": 1,
    }


def test_coverage_alternatives_counts_multiplicity_without_double_counting() -> None:
    pixels = {("front", 0, 0), ("front", 1, 0), ("front", 2, 0)}
    result = coverage_alternatives(
        pixels,
        {("front", 0, 0)},
        ({("front", 1, 0)}, {("front", 1, 0), ("front", 2, 0)}),
    )

    assert result["views"]["front"]["coveredByLockedGeometry"] == 1
    assert result["views"]["front"]["exactlyOneEligibleCandidate"] == 1
    assert result["views"]["front"]["multipleEligibleCandidates"] == 1


def test_occupancy_conflicts_use_an_inverted_cell_index_and_report_support_options() -> None:
    first, overlap, separate, supported = (
        _candidate(0, 0, 0, "3004"),
        _candidate(0, 0, 0, "3004"),
        _candidate(5, 0, 0),
        _candidate(0, 0, 3, "3004"),
    )
    result = candidate_conflicts((first, overlap, separate, supported), ())

    assert result["occupancyMutualExclusionPairCount"] == 1
    assert result["candidatesWithNoKnownConflict"] == 2
    assert result["possibleSupporterCountDistribution"]
    assert "possible CP-SAT support choices" in result["supportInterpretation"]


def test_mandatory_coverage_reports_restrictive_requirements() -> None:
    candidate = _candidate(0, 0, 0)
    result = mandatory_coverage_pressure({("front", 0, 0), ("front", 9, 9)}, (candidate,), ())

    assert result["requiringCandidateCoverage"] == 2
    assert result["singleAlternativeRequirements"] == 1
    assert result["zeroAlternativeRequirements"] == 1


def test_assembly_attribution_identifies_exclusive_false_positive_without_legality_claim() -> None:
    first, second = _candidate(0, 0, 0).placement, _candidate(1, 0, 0).placement
    result = assembly_error_attribution(
        (first, second),
        ({("front", 0, 0)}, {("front", 9, 0)}),
        {("front", 0, 0)},
    )

    assert result["views"]["front"]["falsePositivePixelsWithOneSelectedPlacement"] == 1
    assert (
        result["selectedPlacementExclusiveContributions"][1]["exclusivePixels"]["front"][
            "falsePositives"
        ]
        == 1
    )
    assert "mandatory coverage" in result["removalCounterfactual"]
