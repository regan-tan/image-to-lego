import json
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.m13c_silhouette_equivalence_audit import AuditError
from app.conversion.m13e_duck_iou_dominance import IoUDominanceModel
from app.conversion.m13f_duck_coarse_budget_frontier import (
    add_coarse_violation_budget,
    count_unmet_coarse_requirements,
    historical_coarse_requirements,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate
from scripts.run_m13f_duck_coarse_budget_frontier import (
    EXPECTED_CONTROL_FULL_VIEWS,
    _check_optimal_monotonicity,
    _historical_control_views,
    prepare_frontier,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DUCK_MANIFEST = REPOSITORY_ROOT / "artifacts" / "m7b-corpus" / "manifest-duck.json"
DUCK_SUMMARY = REPOSITORY_ROOT / "artifacts" / "m13b-duck-final" / "summary.json"
RELAXED_ABLATION = REPOSITORY_ROOT / "artifacts" / "m13f-duck-fp-coarse-ablation" / "summary.json"


def _frontier_arm(status: str, objective: float | None = None) -> dict[str, object]:
    return {
        "solver": {"status": status},
        "solverObjectiveValue": objective,
        "provenOptimalSurrogateObjectiveValue": objective if status == "OPTIMAL" else None,
    }


@pytest.mark.parametrize(
    "arms",
    [
        [],
        [_frontier_arm("OPTIMAL", 1.0)],
        [_frontier_arm("OPTIMAL", 1.0), _frontier_arm("OPTIMAL", 1.0)],
        [_frontier_arm("OPTIMAL", value) for value in range(7)],
    ],
)
def test_optimal_monotonicity_accepts_zero_to_seven_nondecreasing_arms(
    arms: list[dict[str, object]],
) -> None:
    _check_optimal_monotonicity(arms)


def test_optimal_monotonicity_rejects_decreasing_proven_values() -> None:
    with pytest.raises(AuditError, match="Optimal objective decreased"):
        _check_optimal_monotonicity([_frontier_arm("OPTIMAL", 2.0), _frontier_arm("OPTIMAL", 1.0)])


def test_optimal_monotonicity_ignores_nonoptimal_incumbents() -> None:
    _check_optimal_monotonicity(
        [
            _frontier_arm("OPTIMAL", 1.0),
            _frontier_arm("FEASIBLE", -100.0),
            _frontier_arm("UNKNOWN", None),
            _frontier_arm("INFEASIBLE", None),
            _frontier_arm("MODEL_INVALID", None),
            _frontier_arm("OPTIMAL", 2.0),
        ]
    )


def _candidate(index: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(index, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _built(count: int) -> IoUDominanceModel:
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(count))
    return IoUDominanceModel(model, selected, {}, {}, {}, {}, {})


def test_exact_violation_encoding_and_independent_count() -> None:
    candidates = (_candidate(0), _candidate(1))
    requirements = historical_coarse_requirements(
        candidates=candidates,
        required_pixels={("front", 0, 0), ("front", 1, 0)},
        fixed_coverage_pixels=(),
    )
    built = _built(2)
    add_coarse_violation_budget(built, requirements, budget=1)
    built.model.add(built.selected[0] == 1)
    built.model.add(built.selected[1] == 0)
    solver = cp_model.CpSolver()
    assert solver.status_name(solver.solve(built.model)) == "OPTIMAL"
    assert [item.pixel for item in count_unmet_coarse_requirements(requirements, (0,))] == [
        ("front", 1, 0)
    ]


def test_locked_coverage_is_excluded_and_empty_incidence_fails_closed() -> None:
    candidate = _candidate(0)
    assert (
        historical_coarse_requirements(
            candidates=(candidate,),
            required_pixels={("front", 9, 0)},
            fixed_coverage_pixels={("front", 9, 0)},
        )
        == ()
    )
    try:
        historical_coarse_requirements(
            candidates=(candidate,), required_pixels={("front", 9, 0)}, fixed_coverage_pixels=()
        )
    except ValueError as error:
        assert "no candidate incidence" in str(error)
    else:
        raise AssertionError("Expected missing candidate incidence to fail closed.")


def test_k_zero_matches_historical_requirement_and_feasible_sets_are_nested() -> None:
    candidate = _candidate(0)
    requirements = historical_coarse_requirements(
        candidates=(candidate,), required_pixels={("front", 0, 0)}, fixed_coverage_pixels=()
    )
    k_zero = _built(1)
    add_coarse_violation_budget(k_zero, requirements, budget=0)
    k_zero.model.add(k_zero.selected[0] == 0)
    solver = cp_model.CpSolver()
    assert solver.status_name(solver.solve(k_zero.model)) == "INFEASIBLE"
    assert not count_unmet_coarse_requirements(requirements, (0,))


def test_duplicate_requirements_fail_and_budget_35_admits_35_unmet_requirements() -> None:
    candidate = _candidate(0)
    try:
        historical_coarse_requirements(
            candidates=(candidate,),
            required_pixels=[("front", 0, 0), ("front", 0, 0)],
            fixed_coverage_pixels=(),
        )
    except ValueError as error:
        assert "duplicates" in str(error)
    else:
        raise AssertionError("Expected duplicate historical requirements to fail.")

    candidates = tuple(_candidate(index) for index in range(35))
    requirements = historical_coarse_requirements(
        candidates=candidates,
        required_pixels={("front", index, 0) for index in range(35)},
        fixed_coverage_pixels=(),
    )
    built = _built(35)
    add_coarse_violation_budget(built, requirements, budget=35)
    for selected in built.selected:
        built.model.add(selected == 0)
    solver = cp_model.CpSolver()
    assert solver.status_name(solver.solve(built.model)) == "OPTIMAL"


def test_historical_control_schema_requires_fixed_frame_view_records() -> None:
    with pytest.raises(AuditError, match="control.fixedFrame.views must be a list"):
        _historical_control_views({"fixedFrame": {}})

    malformed = {
        "fixedFrame": {
            "views": [
                {
                    "view": "front",
                    "truePositives": 7803,
                    "falsePositives": 3940,
                    "falseNegatives": "92",
                }
            ]
        }
    }
    with pytest.raises(AuditError, match="integer TP/FP/FN"):
        _historical_control_views(malformed)


@pytest.mark.skipif(
    not (DUCK_MANIFEST.exists() and DUCK_SUMMARY.exists()),
    reason="Private historical Duck artifacts are unavailable.",
)
def test_historical_duck_preflight_reads_fixed_frame_control_without_building_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def model_build_forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("no optimization model may be built during preflight")

    monkeypatch.setattr(
        "scripts.run_m13f_duck_coarse_budget_frontier.build_compressed_iou_dominance_model",
        model_build_forbidden,
    )

    summary = json.loads(DUCK_SUMMARY.read_text(encoding="utf-8"))
    saved_views = summary["records"][0]["control"]["fixedFrame"]["views"]
    assert {
        item["view"]: {
            "truePositives": item["truePositives"],
            "falsePositives": item["falsePositives"],
            "falseNegatives": item["falseNegatives"],
        }
        for item in saved_views
    } == EXPECTED_CONTROL_FULL_VIEWS

    prepared = prepare_frontier(DUCK_MANIFEST, DUCK_SUMMARY)

    assert prepared.control_views == {
        view: {
            "truePositives": values["truePositives"],
            "falsePositives": values["falsePositives"],
        }
        for view, values in EXPECTED_CONTROL_FULL_VIEWS.items()
    }
    assert prepared.source_counts == {"front": 7895, "side": 7075, "top": 7255}
    assert len(prepared.candidate_preflight.candidates) == 1449
    assert len(prepared.requirements) == 98
    assert not count_unmet_coarse_requirements(
        prepared.requirements, prepared.control_candidate_indices
    )


@pytest.mark.skipif(
    not (DUCK_MANIFEST.exists() and DUCK_SUMMARY.exists() and RELAXED_ABLATION.exists()),
    reason="Private historical Duck artifacts are unavailable.",
)
def test_historical_control_and_verified_relaxed_witness_match_coarse_budget() -> None:
    prepared = prepare_frontier(DUCK_MANIFEST, DUCK_SUMMARY)
    assert not count_unmet_coarse_requirements(
        prepared.requirements, prepared.control_candidate_indices
    )

    relaxed = json.loads(RELAXED_ABLATION.read_text(encoding="utf-8"))["arms"][
        "coarseCoverageRelaxed"
    ]
    assert relaxed["status"] == "OPTIMAL"
    assert relaxed["classification"] == "VERIFIED_FROZEN_MEAN_IMPROVEMENT"
    result = relaxed["result"]
    assert result["mandatoryCoarseCoverage"]["uncoveredRequirementCount"] == 35
    selected = tuple(result["selectedCandidateIndices"])
    assert len(count_unmet_coarse_requirements(prepared.requirements, selected)) == 35
