from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.conversion import benchmark, core
from app.conversion.physical_scale_experiment import (
    CANDIDATE_LIMIT,
    nominal_envelope_mm,
    preflight_fixed_grid,
    scale_factors,
    scaled_grid,
)
from app.conversion.scale_normalized_geometry import evaluate_scale_normalized_silhouette
from app.conversion.surface_grid_v4 import SolverStage

RUNNER_PATH = Path(__file__).parents[1] / "scripts" / "run_m10b_physical_scale_experiment.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_m10b_physical_scale_experiment", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _box_source() -> bytes:
    case = next(case for case in benchmark.synthetic_cases() if case.case_id == "box")
    return benchmark.glb_bytes(case.mesh)


def test_scaled_grid_increases_physical_lattice_with_real_lego_units() -> None:
    baseline = core.GridSize(5, 7, 12)
    larger = scaled_grid(baseline, 1.5)

    assert larger == core.GridSize(8, 10, 18)
    assert larger.cell_count > baseline.cell_count
    assert nominal_envelope_mm(larger) == {"width": 64.0, "depth": 80.0, "height": 57.6}
    assert scale_factors(larger, baseline) == {"width": 1.6, "depth": 1.428571, "height": 1.5}


def test_preflight_is_deterministic_and_respects_candidate_limit() -> None:
    source = _box_source()
    grid = core.GridSize(5, 4, 6)

    first = preflight_fixed_grid(source, grid=grid, up_axis=core.Axis.Y)
    second = preflight_fixed_grid(source, grid=grid, up_axis=core.Axis.Y)
    rejected = preflight_fixed_grid(source, grid=grid, up_axis=core.Axis.Y, candidate_limit=1)

    assert first == second
    assert first.candidate_count_after_reachability <= CANDIDATE_LIMIT
    assert not rejected.accepted
    assert rejected.decision == "candidate_limit_exceeded"


def test_normalized_silhouette_is_invariant_to_uniform_source_scale() -> None:
    plate = next(
        part
        for part in core.BRICK_CATALOGUE
        if part.length_studs == part.width_studs == part.height_plates == 1
    )
    placements = (core.BrickPlacement(plate, core.GridPosition(0, 0, 0), 0),)
    source = (
        (0.0, 0.0, 0.0),
        (8.0, 0.0, 0.0),
        (8.0, 8.0, 0.0),
        (0.0, 8.0, 0.0),
        (0.0, 0.0, 3.2),
        (8.0, 0.0, 3.2),
        (8.0, 8.0, 3.2),
        (0.0, 8.0, 3.2),
    )
    faces = ((0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6))

    original = evaluate_scale_normalized_silhouette(
        source, faces, placements, nominal_grid=core.GridSize(1, 1, 1)
    )
    scaled = evaluate_scale_normalized_silhouette(
        tuple((x * 2, y * 2, z * 2) for x, y, z in source),
        faces,
        placements,
        nominal_grid=core.GridSize(1, 1, 1),
    )

    assert original.status == scaled.status == "available"
    assert original.mean_iou == scaled.mean_iou
    assert original.false_positive_pixels == scaled.false_positive_pixels
    assert original.false_negative_pixels == scaled.false_negative_pixels


def test_realistic_man_pilot_is_an_explicit_exception_to_duck_first_gate() -> None:
    runner = _load_runner()

    selected, schema_version, label = runner._select_experiment_cases(None, True)

    assert selected == ("realistic-man",)
    assert schema_version == "m10b-realistic-man-scale-pilot-v1"
    assert "separately labelled" in label
    with pytest.raises(ValueError, match="must include Duck"):
        runner._select_experiment_cases(("realistic-man",), False)
    with pytest.raises(ValueError, match="cannot be combined"):
        runner._select_experiment_cases(("duck", "realistic-man"), True)


def test_solver_stage_record_distinguishes_feasible_from_optimal() -> None:
    runner = _load_runner()

    feasible = runner._solver_stage_record(SolverStage("FEASIBLE", 18, 0.5, False, 21), "maximize")
    optimal = runner._solver_stage_record(SolverStage("OPTIMAL", 12, 12, True, 12), "minimize")

    assert feasible["absoluteGap"] == 3
    assert feasible["isProvenOptimal"] is False
    assert feasible["deterministicTimeLimit"] == 20.0
    assert optimal["absoluteGap"] == 0
    assert optimal["isProvenOptimal"] is True
    assert optimal["deterministicTimeLimit"] == 7.25
