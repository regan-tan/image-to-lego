from __future__ import annotations

from app.conversion import core
from app.conversion.m13d_tp_fp_feasibility_experiment import (
    classify_result,
    solve_tp_fp_feasibility,
    validate_view_metrics,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import _Candidate


def _candidate(x: int) -> _Candidate:
    placement = core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, 0, 0), 0)
    return _Candidate(placement, frozenset({placement.position}))


def _mask_metrics(
    source: set[tuple[str, int, int]], output: frozenset[tuple[str, int, int]]
) -> dict[str, dict[str, int]]:
    return {
        view: {
            "truePositives": sum(pixel[0] == view and pixel in source for pixel in output),
            "falsePositives": sum(pixel[0] == view and pixel not in source for pixel in output),
            "falseNegatives": sum(pixel[0] == view and pixel not in output for pixel in source),
        }
        for view in ("front", "side", "top")
    }


def test_union_counts_overlapping_candidate_pixels_once_and_finds_improvement() -> None:
    first, second = _candidate(0), _candidate(1)
    source = {("front", 0, 0)}
    result = solve_tp_fp_feasibility(
        candidates=(first, second),
        candidate_rasters=({("front", 0, 0), ("front", 9, 0)}, {("front", 0, 0)}),
        source_pixels=source,
        locked_pixels=(),
        required_pixels=(),
        locked_placements=(),
        target_cells={first.placement.position, second.placement.position},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 1},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
        max_parts=2,
    )

    assert result.status == "OPTIMAL"
    assert result.views["front"] == {"truePositives": 1, "falsePositives": 0, "falseNegatives": 0}
    assert (
        classify_result(
            result,
            {
                "front": {"truePositives": 1, "falsePositives": 1},
                "side": {"truePositives": 0, "falsePositives": 0},
                "top": {"truePositives": 0, "falsePositives": 0},
            },
        )
        == "PROVEN_IMPROVEMENT"
    )


def test_locked_geometry_is_counted_and_per_view_bounds_are_enforced() -> None:
    candidate = _candidate(0)
    result = solve_tp_fp_feasibility(
        candidates=(candidate,),
        candidate_rasters=({("front", 0, 0)},),
        source_pixels={("front", 0, 0)},
        locked_pixels={("side", 9, 0)},
        required_pixels=(),
        locked_placements=(),
        target_cells={candidate.placement.position},
        fixed_coverage_pixels=(),
        control_views={
            "front": {"truePositives": 1, "falsePositives": 0},
            "side": {"truePositives": 0, "falsePositives": 0},
            "top": {"truePositives": 0, "falsePositives": 0},
        },
        max_parts=1,
    )

    assert result.status == "INFEASIBLE"


def test_distinct_per_view_fp_is_extracted_and_matches_aggregate_objective() -> None:
    first, second, third = (_candidate(index) for index in range(3))
    source = {("front", index, 0) for index in range(3)}
    candidate_rasters = (
        {("front", 0, 0), ("front", 10, 0)},
        {("front", 1, 0), ("side", 10, 0), ("side", 11, 0)},
        {("front", 2, 0), ("top", 10, 0), ("top", 11, 0), ("top", 12, 0)},
    )
    control_output = source | {
        ("front", 20, 0),
        ("front", 21, 0),
        ("side", 20, 0),
        ("side", 21, 0),
        ("side", 22, 0),
        ("top", 20, 0),
        ("top", 21, 0),
        ("top", 22, 0),
        ("top", 23, 0),
    }
    control_metrics = _mask_metrics(source, frozenset(control_output))
    control_views = {
        view: {
            "truePositives": values["truePositives"],
            "falsePositives": values["falsePositives"],
        }
        for view, values in control_metrics.items()
    }

    result = solve_tp_fp_feasibility(
        candidates=(first, second, third),
        candidate_rasters=candidate_rasters,
        source_pixels=source,
        locked_pixels=(),
        required_pixels=source,
        locked_placements=(),
        target_cells={item.placement.position for item in (first, second, third)},
        fixed_coverage_pixels=(),
        control_views=control_views,
        max_parts=3,
    )

    reconstructed_output = frozenset().union(*candidate_rasters)
    reconstructed_views = _mask_metrics(source, reconstructed_output)

    assert result.status == "OPTIMAL"
    assert result.selected_ids == (0, 1, 2)
    assert control_output != reconstructed_output
    assert result.views == reconstructed_views
    assert [result.views[view]["falsePositives"] for view in ("front", "side", "top")] == [1, 2, 3]
    assert result.objective_value == 6
    source_foreground = {"front": 3, "side": 0, "top": 0}
    validate_view_metrics(control_metrics, source_foreground)
    validate_view_metrics(result.views, source_foreground, total_fp=6)


def test_invalid_aggregate_or_view_metrics_fail_closed() -> None:
    views = {
        "front": {"truePositives": 1, "falsePositives": 1, "falseNegatives": 0},
        "side": {"truePositives": 0, "falsePositives": 2, "falseNegatives": 0},
        "top": {"truePositives": 0, "falsePositives": 3, "falseNegatives": 0},
    }

    try:
        validate_view_metrics(views, {"front": 1, "side": 0, "top": 0}, total_fp=7)
    except ValueError as error:
        assert "aggregate FP" in str(error)
    else:
        raise AssertionError("Mismatched aggregate FP must fail closed.")
