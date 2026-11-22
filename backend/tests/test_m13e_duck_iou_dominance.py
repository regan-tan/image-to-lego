from __future__ import annotations

from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.m13e_duck_iou_dominance import (
    IoUDominanceResult,
    build_iou_dominance_model,
    classify_iou_dominance_status,
    dominance_value,
    dominance_values,
    has_strict_per_view_dominance,
    model_fingerprint,
    solve_iou_dominance_feasibility,
    strict_dominance_views,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate
from scripts.run_m13e_duck_solver_bottleneck import (
    DiagnosticArtifactError,
    DiagnosticCapture,
    _model_proto_sha256,
    _search_stage_evidence,
    _write_diagnostic_artifacts,
)


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _views(
    front: tuple[int, int], side: tuple[int, int], top: tuple[int, int]
) -> dict[str, dict[str, int]]:
    return {
        "front": {
            "truePositives": front[0],
            "falsePositives": front[1],
            "falseNegatives": 5 - front[0],
        },
        "side": {
            "truePositives": side[0],
            "falsePositives": side[1],
            "falseNegatives": 5 - side[0],
        },
        "top": {"truePositives": top[0], "falsePositives": top[1], "falseNegatives": 5 - top[0]},
    }


def _control() -> dict[str, dict[str, int]]:
    return {view: {"truePositives": 1, "falsePositives": 0} for view in ("front", "side", "top")}


def test_exact_cross_multiplication_accepts_strict_one_view_and_equal_others() -> None:
    candidate = _views((2, 0), (1, 0), (1, 0))
    values = dominance_values(candidate, {"front": 5, "side": 5, "top": 5}, _control())

    assert values == {"front": 5, "side": 0, "top": 0}
    assert has_strict_per_view_dominance(candidate, {"front": 5, "side": 5, "top": 5}, _control())


def test_exact_cross_multiplication_handles_tp_fp_tradeoffs_without_floats() -> None:
    # A TP gain with FP gain can be exact equality: 2/(5 + 5) equals 1/(5 + 0).
    assert dominance_value(5, 1, 0, 2, 5) == 0
    # A TP loss can dominate when the FP reduction is sufficiently large.
    assert dominance_value(10, 5, 10, 4, 0) == 30


def test_rejects_all_equal_and_one_worse_view_even_when_other_views_improve() -> None:
    equal = _views((1, 0), (1, 0), (1, 0))
    worse = _views((5, 0), (0, 0), (5, 0))
    source = {"front": 5, "side": 5, "top": 5}

    assert not has_strict_per_view_dominance(equal, source, _control())
    assert not has_strict_per_view_dominance(worse, source, _control())


def test_split_arm_union_is_exactly_equivalent_to_original_b3_condition() -> None:
    source = {"front": 5, "side": 5, "top": 5}
    cases = (
        _views((2, 0), (1, 0), (1, 0)),
        _views((1, 0), (1, 0), (1, 0)),
        _views((5, 0), (0, 0), (5, 0)),
        _views((1, 0), (2, 0), (3, 0)),
    )

    for candidate in cases:
        assert has_strict_per_view_dominance(candidate, source, _control()) == bool(
            strict_dominance_views(candidate, source, _control())
        )


def test_solver_has_no_tp_floor_or_fp_cap_and_requires_strict_dominance() -> None:
    candidate = _candidate(0)
    source = {(view, 0, 0) for view in ("front", "side", "top")}
    result = solve_iou_dominance_feasibility(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0), ("front", 1, 0), ("side", 0, 0)},),
        source_pixels=source,
        locked_pixels=(),
        required_pixels=(),
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 0, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
        max_parts=1,
    )

    assert result.status == "OPTIMAL"
    # The front FP increase is permitted; B3 has no inherited FP cap.
    assert result.views["front"]["falsePositives"] == 1
    assert result.dominance_values["front"] == 1


def test_control_only_preflight_can_be_feasible_while_strict_model_rejects_it() -> None:
    candidate = _candidate(0)
    kwargs = {
        "candidates": (candidate,),
        "candidate_rasters": ({("front", 0, 0), ("side", 0, 0), ("top", 0, 0)},),
        "source_pixels": {("front", 0, 0), ("side", 0, 0), ("top", 0, 0)},
        "locked_pixels": (),
        "required_pixels": (),
        "locked_placements": (),
        "target_cells": {candidate.placement.position},
        "fixed_coverage_pixels": (),
        "control_views": _control(),
        "max_parts": 1,
        "required_selected_ids": (0,),
    }
    preflight = solve_iou_dominance_feasibility(**kwargs, require_strict_improvement=False)
    strict = solve_iou_dominance_feasibility(**kwargs)

    assert preflight.status == "OPTIMAL"
    assert preflight.dominance_values == {"front": 0, "side": 0, "top": 0}
    assert strict.status == "INFEASIBLE"


def test_each_split_arm_has_its_designated_strict_constraint() -> None:
    source = {(view, 0, 0) for view in ("front", "side", "top")}
    for strict_view in ("front", "side", "top"):
        candidate = _candidate(0)
        result = solve_iou_dominance_feasibility(
            candidates=(candidate,),
            candidate_rasters=({(strict_view, 0, 0)},),
            source_pixels=source,
            locked_pixels=(),
            required_pixels=(),
            locked_placements=(),
            target_cells={candidate.placement.position},
            fixed_coverage_pixels=(),
            control_views={
                "front": {"truePositives": 0, "falsePositives": 0},
                "side": {"truePositives": 0, "falsePositives": 0},
                "top": {"truePositives": 0, "falsePositives": 0},
            },
            max_parts=1,
            strict_view=strict_view,
        )

        assert result.status == "OPTIMAL"
        assert result.dominance_values[strict_view] >= 1


def test_split_model_fingerprint_records_the_designated_strict_view() -> None:
    kwargs = {
        "candidate_ids": ("3024@0,0,0:0",),
        "locked_ids": (),
        "required_pixels": {("front", 0, 0)},
        "fixed_coverage_pixels": (),
        "control_views": _control(),
    }

    assert model_fingerprint(**kwargs, strict_view="front") != model_fingerprint(
        **kwargs, strict_view="side"
    )


def test_historical_hard_constraints_remain_active() -> None:
    candidate = _candidate(0)
    result = solve_iou_dominance_feasibility(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0), ("side", 0, 0), ("top", 0, 0)},
        locked_pixels=(),
        required_pixels={("side", 9, 9)},
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views=_control(),
        max_parts=1,
    )

    assert result.status == "INFEASIBLE"


def test_status_classification_never_treats_satisfaction_as_iou_optimality() -> None:
    assert (
        classify_iou_dominance_status("INFEASIBLE", control_preflight_passed=True)
        == "PROVEN_NO_PER_VIEW_DOMINANCE"
    )
    assert classify_iou_dominance_status("UNKNOWN", control_preflight_passed=True) == "INCONCLUSIVE"
    assert (
        classify_iou_dominance_status("FEASIBLE", control_preflight_passed=True)
        == "VERIFIED_DOMINATING_WITNESS"
    )
    assert (
        classify_iou_dominance_status("INFEASIBLE", control_preflight_passed=False)
        == "MODEL_PARITY_FAILED"
    )
    result = IoUDominanceResult("UNKNOWN", 30.0, 0.0, (), {}, {})
    assert result.selected_ids == ()


def test_component_counts_partition_the_built_model_size() -> None:
    candidate = _candidate(0)
    built = build_iou_dominance_model(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0), ("side", 0, 0), ("top", 0, 0)},
        locked_pixels=(),
        required_pixels=(),
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views={view: {"truePositives": 0, "falsePositives": 0} for view in _control()},
        max_parts=1,
        strict_view="front",
    )

    assert sum(item.variables for item in built.component_counts.values()) == len(
        built.model.proto.variables
    )
    assert sum(item.constraints for item in built.component_counts.values()) == len(
        built.model.proto.constraints
    )
    assert built.component_counts["strict_dominance"].constraints == 1


def test_log_evidence_does_not_overstate_budget_attribution() -> None:
    evidence = _search_stage_evidence(
        "Initial satisfaction model\nStarting presolve\n"
        "Presolved satisfaction model\nStarting search",
        "CpSolverResponse summary:",
    )

    assert evidence["lastConfirmedStage"] == "search"
    attribution = evidence["budgetAttribution"]
    assert isinstance(attribution, dict)
    assert attribution["determination"] == "NOT_ATTRIBUTABLE_FROM_STANDARD_LOG_ALONE"


def test_log_evidence_attributes_an_explicit_presolve_stop_without_search() -> None:
    evidence = _search_stage_evidence(
        "Initial satisfaction model\nStarting presolve\nStopped after presolve",
        "CpSolverResponse summary:",
    )

    assert evidence["lastConfirmedStage"] == "presolve"
    markers = evidence["confirmedMarkers"]
    assert isinstance(markers, dict)
    assert markers["stoppedAfterPresolve"]
    attribution = evidence["budgetAttribution"]
    assert isinstance(attribution, dict)
    assert attribution["determination"] == "PRESOLVE_MODEL_PROCESSING_CONSUMED_BUDGET"


def test_model_fingerprint_uses_installed_ortools_binary_export_deterministically() -> None:
    model = cp_model.CpModel()
    selected = model.new_bool_var("selected")
    model.add(selected == 1)

    assert _model_proto_sha256(model) == _model_proto_sha256(model)


def test_artifact_metadata_failure_preserves_raw_solver_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built = build_iou_dominance_model(
        candidates=(_candidate(0),),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0), ("side", 0, 0), ("top", 0, 0)},
        locked_pixels=(),
        required_pixels=(),
        locked_placements=(),
        target_cells={_candidate(0).placement.position},
        fixed_coverage_pixels=(),
        control_views={view: {"truePositives": 0, "falsePositives": 0} for view in _control()},
        max_parts=1,
        strict_view="front",
    )
    capture = DiagnosticCapture(
        model=built,
        result=IoUDominanceResult("UNKNOWN", 30.0, 0.0, (), {}, {}),
        solver_log="Stopped after presolve\n",
        solver_response="status: UNKNOWN",
    )

    def fail_fingerprint(_: cp_model.CpModel) -> str:
        raise OSError("export unavailable")

    monkeypatch.setattr(
        "scripts.run_m13e_duck_solver_bottleneck._model_proto_sha256", fail_fingerprint
    )

    with pytest.raises(DiagnosticArtifactError, match="raw solver evidence was saved"):
        _write_diagnostic_artifacts(tmp_path, {}, capture)

    assert (tmp_path / "solver.log").read_text(encoding="utf-8") == "Stopped after presolve\n"
    assert (tmp_path / "solver-response.txt").read_text(encoding="utf-8") == "status: UNKNOWN\n"
    assert "DIAGNOSTIC_ARTIFACT_FAILURE" in (
        tmp_path / "diagnostic-artifact-failure.json"
    ).read_text(encoding="utf-8")
