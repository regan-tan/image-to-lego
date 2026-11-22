from __future__ import annotations

from scripts.run_m13e_duck_iou_compressed_split import (
    HISTORICAL_FRONT_STRICT,
    _arm_classification,
    _combined_classification,
    _combined_status,
)


def _records(*statuses: str) -> list[object]:
    return [
        {"strictView": view, "status": status}
        for view, status in zip(("front", "side", "top"), statuses, strict=True)
    ]


def test_historical_front_reference_is_arm_scoped_and_infeasible() -> None:
    assert HISTORICAL_FRONT_STRICT["strictView"] == "front"
    assert HISTORICAL_FRONT_STRICT["status"] == "INFEASIBLE"
    assert "not a three-arm proof" in str(HISTORICAL_FRONT_STRICT["scope"])


def test_infeasible_fresh_arms_are_classified_as_arm_scoped() -> None:
    assert _arm_classification("side", "INFEASIBLE", "ignored") == "PROVEN_NO_SIDE_STRICT_DOMINANCE"


def test_all_infeasible_arms_prove_no_per_view_dominance() -> None:
    records = _records("INFEASIBLE", "INFEASIBLE", "INFEASIBLE")

    assert _combined_status(records) == "INFEASIBLE"
    assert _combined_classification(records) == "PROVEN_NO_PER_VIEW_DOMINANCE"


def test_verified_side_or_top_witness_proves_per_view_dominance() -> None:
    records = _records("INFEASIBLE", "FEASIBLE", "UNKNOWN")

    assert _combined_status(records) == "WITNESS_FOUND"
    assert _combined_classification(records) == "VERIFIED_PER_VIEW_DOMINANCE"


def test_unknown_without_witness_is_inconclusive() -> None:
    records = _records("INFEASIBLE", "UNKNOWN", "INFEASIBLE")

    assert _combined_status(records) == "INCONCLUSIVE"
    assert _combined_classification(records) == "INCONCLUSIVE"


def test_validation_failure_prevents_a_combined_proof() -> None:
    records = _records("INFEASIBLE", "RESULT_VERIFICATION_FAILED", "INFEASIBLE")

    assert _combined_status(records) == "VALIDATION_FAILED"
    assert _combined_classification(records) == "VALIDATION_FAILED"


def test_missing_or_misordered_arm_fails_closed() -> None:
    records = [
        {"strictView": "side", "status": "INFEASIBLE"},
        {"strictView": "front", "status": "INFEASIBLE"},
        {"strictView": "top", "status": "INFEASIBLE"},
    ]

    assert _combined_status(records) == "VALIDATION_FAILED"
