from __future__ import annotations

from app.conversion import benchmark, core
from app.conversion.evaluation_alignment import (
    compare_frozen_evaluator_parity,
    evaluate_completed_assembly,
    fixed_frame_iou,
    stable_placement_id,
    verify_baseline_feasibility,
)
from app.conversion.fidelity import render_silhouette_masks
from app.conversion.fixed_grid_experiment import convert_fixed_grid
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage
from app.conversion.surface_grid_v4 import _enumerate_candidates


def test_completed_assembly_matches_frozen_masks_pixel_for_pixel() -> None:
    brick = _rectangular_part()
    placement = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0))
    faces = ((0, 1, 2),)

    result = evaluate_completed_assembly(vertices, faces, (placement,))
    frozen = render_silhouette_masks(
        vertices,
        faces,
        core._placement_boxes((placement,)),
        slope_vertices=core._slope_vertices((placement,)),
    )

    assert result.front.true_positives == sum(
        bool(left) and bool(right)
        for left, right in zip(
            frozen["front"][0].get_flattened_data(),
            frozen["front"][1].get_flattened_data(),
            strict=True,
        )
    )
    frozen_metrics = core._fidelity_for_placements(vertices, faces, (placement,), 1)
    assert result.front.iou == frozen_metrics.front_iou
    assert result.source_equals_lego is False
    parity = compare_frozen_evaluator_parity(vertices, faces, (placement,))
    assert parity.exact_pixel_match
    assert parity.front.source_mask_difference_count == 0
    assert parity.front.lego_mask_difference_count == 0
    assert parity.front.true_positives_match
    assert parity.front.false_positives_match
    assert parity.front.false_negatives_match
    assert parity.front.iou_match


def test_candidate_feasibility_requires_exact_part_position_and_orientation() -> None:
    brick = _rectangular_part()
    placement = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)
    target = core._placement_cells(placement)
    candidates = _enumerate_candidates(target, core.BRICK_CATALOGUE)
    assert any(candidate.placement == placement for candidate in candidates)

    feasible = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=(),
        protected_empty_cells=(),
        baseline_placements=(placement,),
        max_parts=1,
    )
    missing = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=(),
        protected_empty_cells=(),
        baseline_placements=(core.BrickPlacement(brick, core.GridPosition(20, 0, 0), 0),),
        max_parts=1,
    )

    assert feasible.status == "FEASIBLE"
    assert not feasible.missing_placement_ids
    missing_placement = core.BrickPlacement(brick, core.GridPosition(20, 0, 0), 0)
    assert missing.status == "INFEASIBLE"
    assert missing.missing_placement_ids == (stable_placement_id(missing_placement),)


def test_candidate_feasibility_reports_protected_space_and_part_cap() -> None:
    brick = _rectangular_part()
    placement = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)
    target = core._placement_cells(placement)

    result = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=(),
        protected_empty_cells=(core.GridPosition(0, 0, 0),),
        baseline_placements=(placement,),
        max_parts=0,
    )

    assert result.status == "INFEASIBLE"
    assert result.protected_space_violations == 1
    assert not result.part_cap_satisfied


def test_candidate_feasibility_reports_each_missing_mandatory_projection_pixel() -> None:
    brick = _rectangular_part()
    placement = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)

    result = verify_baseline_feasibility(
        target_cells=core._placement_cells(placement),
        required_pixels=(("front", 1, 0),),
        protected_empty_cells=(),
        baseline_placements=(placement,),
        max_parts=1,
    )

    assert result.status == "INFEASIBLE"
    assert result.missing_mandatory_pixels == (("front", 1, 0),)


def test_fixed_m8c_selection_rejects_the_three_historical_duck_witnesses() -> None:
    brick = _rectangular_part()
    baseline = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)
    required = (("front", 1, 11), ("front", 3, 11), ("side", 5, 7))
    target = {
        core.GridPosition(0, 0, 0),
        core.GridPosition(1, 0, 11),
        core.GridPosition(3, 0, 11),
        core.GridPosition(0, 5, 7),
    }

    result = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=required,
        protected_empty_cells=(),
        baseline_placements=(baseline,),
        max_parts=4,
    )

    assert result.status == "INFEASIBLE"
    assert result.fixed_selection_status == "INFEASIBLE"
    assert result.missing_mandatory_pixels == tuple(sorted(required))


def test_m9a_locked_slope_profile_supplies_only_its_own_mandatory_witnesses() -> None:
    slope = next(part for part in core.BRICK_CATALOGUE if part.family == core.SLOPE_33_FAMILY)
    placement = core.BrickPlacement(slope, core.GridPosition(0, 0, 0), 0)
    target = core._placement_source_cells(placement)
    supplied = locked_source_profile_coverage((placement,))
    required = (("front", 1, 1),)

    original = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=required,
        protected_empty_cells=(),
        baseline_placements=(placement,),
        max_parts=1,
    )
    corrected = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=required,
        protected_empty_cells=(),
        baseline_placements=(placement,),
        fixed_coverage_pixels=supplied,
        max_parts=1,
    )
    unrelated = verify_baseline_feasibility(
        target_cells=target,
        required_pixels=(("front", 99, 99),),
        protected_empty_cells=(),
        baseline_placements=(placement,),
        fixed_coverage_pixels=supplied,
        max_parts=1,
    )

    assert required[0] in supplied
    assert original.status == "INFEASIBLE"
    assert corrected.status == "FEASIBLE"
    assert corrected.fixed_geometry_coverage_pixel_count == 1
    assert unrelated.status == "INFEASIBLE"
    assert unrelated.missing_mandatory_pixels == (("front", 99, 99),)


def test_slope_projection_uses_the_frozen_prism_geometry() -> None:
    slope = next(part for part in core.BRICK_CATALOGUE if part.family == core.SLOPE_33_FAMILY)
    placement = core.BrickPlacement(slope, core.GridPosition(0, 0, 0), 90)
    vertices = ((0.0, 0.0, 0.0), (3.0, 0.0, 3.0), (0.0, 1.0, 0.0))

    result = evaluate_completed_assembly(vertices, ((0, 1, 2),), (placement,))
    frozen = core._fidelity_for_placements(vertices, ((0, 1, 2),), (placement,), 1)

    assert result.front.iou == frozen.front_iou
    assert result.side.iou == frozen.side_iou
    assert result.top.iou == frozen.top_iou
    assert compare_frozen_evaluator_parity(vertices, ((0, 1, 2),), (placement,)).exact_pixel_match


def test_v6_baseline_reconstruction_is_deterministic_for_alignment_input() -> None:
    box = next(case for case in benchmark.synthetic_cases() if case.case_id == "box")
    source = benchmark.glb_bytes(box.mesh)
    settings = dict(
        grid_size=core.GridSize(3, 3, 3),
        solver_target_parts=4,
        max_parts=16,
        up_axis=core.Axis.Y,
        shape_aware=True,
    )

    first = convert_fixed_grid(source, **settings)
    second = convert_fixed_grid(source, **settings)

    assert first.model.placements == second.model.placements


def test_tp_minus_fp_can_rank_arrangements_oppositely_to_iou() -> None:
    source_pixels = 30
    sparse_true_positives, sparse_false_positives = 20, 0
    complete_true_positives, complete_false_positives = 30, 11

    sparse_surrogate = sparse_true_positives - sparse_false_positives
    complete_surrogate = complete_true_positives - complete_false_positives
    sparse_iou = sparse_true_positives / (source_pixels + sparse_false_positives)
    complete_iou = complete_true_positives / (source_pixels + complete_false_positives)

    assert sparse_surrogate > complete_surrogate
    assert sparse_iou < complete_iou


def test_fixed_frame_iou_is_not_tp_minus_fp() -> None:
    brick = _rectangular_part()
    placement = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)
    score = fixed_frame_iou(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        ((0, 1, 2),),
        (placement,),
        core._placement_cells(placement),
    )

    assert 0.0 <= score <= 1.0


def _rectangular_part() -> core.BrickType:
    return next(
        part
        for part in core.BRICK_CATALOGUE
        if part.shape == "rectangular" and part.length_studs == 1 and part.width_studs == 1
    )
