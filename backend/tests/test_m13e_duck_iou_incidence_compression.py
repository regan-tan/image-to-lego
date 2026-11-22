from __future__ import annotations

import json
from dataclasses import replace
from itertools import chain, combinations
from pathlib import Path

import pytest

from app.conversion import core
from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13c_silhouette_equivalence_audit import (
    m13b_no_wedge_candidate_preflight,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
)
from app.conversion.m13e_duck_control_hint_experiment import (
    DUCK_CONTROL_VIEWS,
    DUCK_GRID,
    control_candidate_indices,
)
from app.conversion.m13e_duck_iou_dominance import (
    build_iou_dominance_model,
    solve_built_iou_dominance_model,
)
from app.conversion.m13e_duck_iou_incidence_compression import (
    _validate_compression,
    build_compressed_iou_dominance_model,
    build_incidence_compression,
    evaluate_compressed_metrics,
    static_model_statistics,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.real_world_benchmark import load_manifest, verify_case_source
from app.conversion.surface_grid_v4 import _Candidate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
B2_FRONTIER = PROJECT_ROOT / "artifacts/m13e-duck-tp-fp-frontier/summary.json"


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _all_assignments(count: int) -> tuple[tuple[int, ...], ...]:
    return tuple(chain.from_iterable(combinations(range(count), size) for size in range(count + 1)))


def test_incidence_groups_preserve_every_assignment_with_asymmetric_view_weights() -> None:
    candidates = (_candidate(0), _candidate(1), _candidate(2))
    rasters = (
        {("front", 0, 0), ("front", 1, 0), ("side", 0, 0), ("top", 5, 0)},
        {("front", 0, 0), ("front", 1, 0), ("side", 2, 0), ("top", 5, 0)},
        {("front", 3, 0), ("side", 0, 0), ("top", 4, 0)},
    )
    source = {
        ("front", 0, 0),
        ("front", 1, 0),
        ("front", 3, 0),
        ("front", 9, 0),
        ("side", 0, 0),
        ("side", 8, 0),
        ("top", 4, 0),
        ("top", 8, 0),
    }
    locked = {("front", 7, 0), ("side", 7, 0), ("top", 7, 0)}
    source |= {("front", 7, 0), ("top", 7, 0)}
    control = {view: {"truePositives": 0, "falsePositives": 0} for view in ("front", "side", "top")}
    compression = build_incidence_compression(rasters, source, locked)

    assert len(compression.groups) == 4
    assert compression.permanently_uncovered_tp == {"front": 1, "side": 1, "top": 1}
    for selected in _all_assignments(len(candidates)):
        expected_covered = set(locked)
        expected_covered.update(
            pixel for index in selected for pixel in rasters[index] if pixel not in locked
        )
        expected = {
            view: {
                "truePositives": sum(
                    pixel[0] == view and pixel in source for pixel in expected_covered
                ),
                "falsePositives": sum(
                    pixel[0] == view and pixel not in source for pixel in expected_covered
                ),
                "falseNegatives": sum(pixel[0] == view for pixel in source - expected_covered),
            }
            for view in ("front", "side", "top")
        }
        actual, _ = evaluate_compressed_metrics(
            compression,
            selected,
            {view: sum(pixel[0] == view for pixel in source) for view in control},
            control,
        )
        assert actual == expected


def test_locked_pixel_union_is_constant_and_excluded_from_candidate_groups() -> None:
    candidates = (_candidate(0), _candidate(1), _candidate(2))
    rasters = (
        {
            ("front", 0, 0),
            ("front", 8, 0),
            ("side", 8, 0),
            ("top", 8, 0),
        },
        {
            ("front", 1, 0),
            ("front", 8, 0),
            ("side", 1, 0),
            ("top", 1, 0),
        },
        {("front", 1, 0), ("side", 2, 0), ("top", 2, 0)},
    )
    source = {
        ("front", 0, 0),
        ("front", 8, 0),
        ("side", 1, 0),
        ("side", 8, 0),
        ("top", 2, 0),
    }
    # The duplicate front pixel represents two locked parts overlapping in projection.
    locked = [
        ("front", 8, 0),
        ("front", 8, 0),
        ("side", 8, 0),
        ("top", 8, 0),
    ]
    control = {
        "front": {"truePositives": 1, "falsePositives": 1},
        "side": {"truePositives": 1, "falsePositives": 1},
        "top": {"truePositives": 1, "falsePositives": 1},
    }
    compression = build_incidence_compression(rasters, source, locked)

    assert compression.locked_tp == {"front": 1, "side": 1, "top": 0}
    assert compression.locked_fp == {"front": 0, "side": 0, "top": 1}
    assert compression.permanently_uncovered_tp == {"front": 0, "side": 0, "top": 0}
    assert compression.permanently_uncovered_fp == {"front": 0, "side": 0, "top": 0}
    assert compression.touchable_pixel_count == 6
    assert compression.candidate_reference_count == 7
    locked_union = frozenset(locked)
    candidate_dependent = frozenset().union(*rasters) - locked_union
    assert candidate_dependent == {
        ("front", 0, 0),
        ("front", 1, 0),
        ("side", 1, 0),
        ("side", 2, 0),
        ("top", 1, 0),
        ("top", 2, 0),
    }
    assert locked_union & frozenset().union(*rasters) == {
        ("front", 8, 0),
        ("side", 8, 0),
        ("top", 8, 0),
    }

    source_counts = {view: sum(pixel[0] == view for pixel in source) for view in control}
    for selected in _all_assignments(len(candidates)):
        covered = locked_union | frozenset(
            pixel for index in selected for pixel in rasters[index] if pixel not in locked_union
        )
        expected_views = {
            view: {
                "truePositives": sum(pixel[0] == view and pixel in source for pixel in covered),
                "falsePositives": sum(
                    pixel[0] == view and pixel not in source for pixel in covered
                ),
                "falseNegatives": sum(pixel[0] == view for pixel in source - covered),
            }
            for view in control
        }
        actual_views, actual_dominance = evaluate_compressed_metrics(
            compression, selected, source_counts, control
        )
        assert actual_views == expected_views
        assert actual_dominance == {
            view: (source_counts[view] + control[view]["falsePositives"])
            * expected_views[view]["truePositives"]
            - control[view]["truePositives"]
            * (source_counts[view] + expected_views[view]["falsePositives"])
            for view in control
        }


def test_compressed_cp_sat_metrics_match_reference_for_all_synthetic_assignments() -> None:
    candidates = (_candidate(0), _candidate(1))
    rasters = (
        {("front", 0, 0), ("side", 1, 0), ("top", 1, 0)},
        {("front", 0, 0), ("front", 2, 0), ("side", 2, 0)},
    )
    source = {("front", 0, 0), ("front", 3, 0), ("side", 1, 0), ("top", 1, 0)}
    kwargs = {
        "candidates": candidates,
        "candidate_rasters": rasters,
        "source_pixels": source,
        "locked_pixels": (("front", 0, 0), ("top", 0, 0), ("top", 0, 0)),
        "required_pixels": (),
        "locked_placements": (),
        "target_cells": {candidate.placement.position for candidate in candidates},
        "fixed_coverage_pixels": (),
        "control_views": {
            view: {"truePositives": 1, "falsePositives": 1} for view in ("front", "side", "top")
        },
        "max_parts": 2,
        "require_strict_improvement": False,
    }
    for selected in _all_assignments(len(candidates)):
        reference = build_iou_dominance_model(**kwargs, required_selected_ids=selected)
        compressed, _ = build_compressed_iou_dominance_model(
            **kwargs, required_selected_ids=selected
        )
        reference_result, _ = solve_built_iou_dominance_model(
            reference, deterministic_time_seconds=1
        )
        compressed_result, _ = solve_built_iou_dominance_model(
            compressed, deterministic_time_seconds=1
        )
        assert reference_result.status == compressed_result.status
        assert reference_result.views == compressed_result.views
        assert reference_result.dominance_values == compressed_result.dominance_values


def test_compressed_model_uses_each_designated_strict_view() -> None:
    candidates = (_candidate(0),)
    source = {(view, 0, 0) for view in ("front", "side", "top")}
    for strict_view in ("front", "side", "top"):
        built, _ = build_compressed_iou_dominance_model(
            candidates=candidates,
            candidate_rasters=({(strict_view, 0, 0)},),
            source_pixels=source,
            locked_pixels=(),
            required_pixels=(),
            locked_placements=(),
            target_cells={candidates[0].placement.position},
            fixed_coverage_pixels=(),
            control_views={
                view: {"truePositives": 0, "falsePositives": 0} for view in ("front", "side", "top")
            },
            max_parts=1,
            strict_view=strict_view,
        )
        result, _ = solve_built_iou_dominance_model(built, deterministic_time_seconds=1)

        assert result.status == "OPTIMAL"
        assert result.dominance_values[strict_view] >= 1
        assert built.component_counts["strict_dominance"].constraints == 1


def test_locked_accounting_validation_reports_expected_and_actual_counts() -> None:
    source = {("front", 0, 0), ("side", 0, 0), ("top", 0, 0)}
    locked = {("front", 0, 0), ("front", 1, 0), ("side", 0, 0), ("top", 1, 0)}
    rasters = ({("front", 1, 0), ("side", 1, 0), ("top", 1, 0)},)
    compression = build_incidence_compression(rasters, source, locked)
    corrupted = replace(compression, locked_fp={"front": 2, "side": 0, "top": 1})

    with pytest.raises(
        ValueError,
        match="Compressed locked background accounting failed for front: expected 1, got 2.",
    ):
        _validate_compression(corrupted, source, locked, rasters)


@pytest.mark.skipif(not B2_FRONTIER.exists(), reason="historical B2 evidence is not available")
def test_historical_control_and_available_b2_assignments_match_compressed_accounting() -> None:
    """Keep the available historical B2 assignments as fixed-frame parity evidence."""
    manifest = load_manifest(PROJECT_ROOT / "artifacts/m7b-corpus/manifest-duck.json")
    case = next(case for case in manifest.cases if case.case_id == "duck")
    source = verify_case_source(case)
    control_summary = json.loads(
        (PROJECT_ROOT / "artifacts/m13b-duck-final/summary.json").read_text(encoding="utf-8")
    )
    control_saved = control_summary["records"][0]["control"]
    assert isinstance(control_saved, dict)
    control = reconstruct_placements(control_saved["placementIds"])
    preprocessing = reconstruct_m13b_preprocessing(source, core.GridSize(**DUCK_GRID), case.up_axis)
    locked = tuple(
        placement for placement in control if placement.brick_type.shape != "rectangular"
    )
    preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
    assert preflight.candidate_rasters is not None
    assert preflight.source_pixels is not None
    assert preflight.locked_pixels is not None
    control_ids = [
        stable_placement_id(placement)
        for placement in control
        if placement.brick_type.shape == "rectangular"
    ]
    control_selection = control_candidate_indices(preflight.candidates, control_ids)
    compression = build_incidence_compression(
        preflight.candidate_rasters, preflight.source_pixels, preflight.locked_pixels
    )
    source_counts = {
        view: sum(pixel[0] == view for pixel in preflight.source_pixels)
        for view in DUCK_CONTROL_VIEWS
    }
    control_metrics, _ = evaluate_compressed_metrics(
        compression, control_selection, source_counts, DUCK_CONTROL_VIEWS
    )
    assert control_metrics == {
        view: {
            **metrics,
            "falseNegatives": source_counts[view] - metrics["truePositives"],
        }
        for view, metrics in DUCK_CONTROL_VIEWS.items()
    }

    frontier = json.loads(B2_FRONTIER.read_text(encoding="utf-8"))
    available_records = [record for record in frontier["records"] if "result" in record]
    assert available_records
    for record in available_records:
        result = record["result"]
        assert isinstance(result, dict)
        metrics, _ = evaluate_compressed_metrics(
            compression, result["selectedCandidateIndices"], source_counts, DUCK_CONTROL_VIEWS
        )
        assert metrics == result["views"]


def test_static_statistics_count_group_references_not_pixel_references() -> None:
    candidates = (_candidate(0), _candidate(1))
    rasters = ({("front", 0, 0), ("front", 1, 0)}, {("front", 0, 0), ("front", 1, 0)})
    built, compression = build_compressed_iou_dominance_model(
        candidates=candidates,
        candidate_rasters=rasters,
        source_pixels={("front", 0, 0), ("front", 1, 0), ("side", 0, 0), ("top", 0, 0)},
        locked_pixels=(),
        required_pixels=(),
        locked_placements=(),
        target_cells={candidate.placement.position for candidate in candidates},
        fixed_coverage_pixels=(),
        control_views={
            view: {"truePositives": 0, "falsePositives": 0} for view in ("front", "side", "top")
        },
        max_parts=2,
    )
    stats = static_model_statistics(built, compression)
    assert stats.coverage_variables == stats.distinct_incidence_signatures == 1
    assert stats.max_equality_candidate_references == 2
    assert stats.group_weight_totals["front"] == {"truePositives": 2, "falsePositives": 0}
