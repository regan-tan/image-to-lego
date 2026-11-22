from __future__ import annotations

from scripts.run_m13e_duck_iou_dominance_split import (
    _combined_classification,
    _combined_status,
)


def _records(*statuses: str) -> list[object]:
    return [
        {"strictView": view, "status": status}
        for view, status in zip(("front", "side", "top"), statuses, strict=True)
    ]


def test_all_infeasible_arms_prove_the_original_disjunction_infeasible() -> None:
    records = _records("INFEASIBLE", "INFEASIBLE", "INFEASIBLE")

    assert _combined_status(records) == "INFEASIBLE"
    assert _combined_classification(records) == "PROVEN_NO_PER_VIEW_DOMINANCE"


def test_one_valid_witness_proves_original_b3_satisfiable() -> None:
    records = _records("UNKNOWN", "FEASIBLE", "INFEASIBLE")

    assert _combined_status(records) == "WITNESS_FOUND"
    assert _combined_classification(records) == "VERIFIED_DOMINATING_WITNESS"


def test_unknown_arm_keeps_combined_result_inconclusive() -> None:
    records = _records("INFEASIBLE", "UNKNOWN", "INFEASIBLE")

    assert _combined_status(records) == "INCONCLUSIVE"
    assert _combined_classification(records) == "INCONCLUSIVE"


def test_model_parity_failure_is_not_counted_as_a_proof() -> None:
    records = _records("INFEASIBLE", "MODEL_PARITY_FAILED", "INFEASIBLE")

    assert _combined_status(records) == "MODEL_PARITY_FAILED"
