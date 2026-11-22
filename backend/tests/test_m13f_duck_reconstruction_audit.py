from __future__ import annotations

from app.conversion import core
from app.conversion.m13f_duck_reconstruction_audit import (
    candidate_id_hash,
    projection_hashes,
    static_inventory,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def test_static_inventory_reports_union_limits_without_feasibility_claim() -> None:
    candidates = (_candidate(0), _candidate(1))
    rasters = (
        {("front", 0, 0), ("front", 3, 0), ("side", 0, 0), ("top", 0, 0)},
        {("front", 1, 0), ("front", 3, 0), ("side", 1, 0), ("top", 1, 0)},
    )
    source = {
        ("front", 0, 0),
        ("front", 1, 0),
        ("front", 2, 0),
        ("side", 0, 0),
        ("top", 2, 0),
    }
    locked = {("front", 4, 0), ("top", 2, 0)}
    control = locked | rasters[0]
    result = static_inventory(
        candidates=candidates,
        candidate_rasters=rasters,
        source_pixels=source,
        locked_pixels=locked,
        control_pixels=control,
        preflight_counts={
            "rawRectangles": 9,
            "afterLockedBodyCollision": 7,
            "afterSupportReachability": 5,
        },
    )

    front = result["views"]["front"]
    assert front["sourceForegroundPixels"] == 3
    assert front["control"] == {"truePositives": 1, "falsePositives": 2, "falseNegatives": 2}
    assert front["permanentlyUnreachableForegroundPixels"] == 1
    assert front["candidateCoverableForegroundMissedByControl"] == 1
    assert front["candidateCoverableBackgroundCoveredByControl"] == 1
    assert result["candidateExclusions"]["excludedByLockedBodyCollision"] == 2
    assert result["candidateExclusions"]["excludedBySupportReachabilityAfterCollisionFilter"] == 2
    assert result["incidenceGroups"]["groupCount"] == 3
    assert (
        "not a simultaneously feasible assembly"
        in result["candidateUnionLimitations"]["interpretation"]
    )


def test_hashes_are_stable_and_view_scoped() -> None:
    candidates = (_candidate(0), _candidate(1))
    assert candidate_id_hash(candidates) == candidate_id_hash(candidates)
    hashes = projection_hashes(
        source={("front", 0, 0), ("side", 0, 0)},
        control={("front", 0, 0), ("side", 1, 0)},
    )
    assert (
        hashes["source"]["front"] != hashes["control"]["front"]
        or hashes["source"]["side"] != hashes["control"]["side"]
    )
    assert len(hashes["source"]["top"]) == 64
