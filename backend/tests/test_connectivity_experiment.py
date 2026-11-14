import pytest

from app.conversion import benchmark
from app.conversion.buildability import analyze_buildability
from app.conversion.connectivity_experiment import (
    MAX_CONNECTION_PAIRS,
    MAX_CONNECTIVITY_CANDIDATES,
    ObjectiveEdgeStrategy,
    PotentialConnection,
    _select_objective_pairs,
    assess_baseline_feasibility,
    exhaustive_verified_connection_pairs,
    indexed_verified_connection_pairs,
    run_source_mesh_experiment,
    solve_coverage_preserving_connectivity,
    verified_connection_pairs,
)
from app.conversion.core import (
    SURFACE_GRID_V7_CONNECTIVITY_AWARE,
    BrickPlacement,
    ConversionError,
    ConversionSettings,
    GridPosition,
    convert_glb,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.physical_geometry import colliding_placement_pairs


def _plate(x: int, y: int, z: int) -> BrickPlacement:
    return BrickPlacement(PART_BY_ID["3024"], GridPosition(x, y, z), 0)


def test_final_baseline_is_feasible_with_exact_orientation_height_and_locked_slope() -> None:
    lower = BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 90)
    slope = BrickPlacement(PART_BY_ID["4286"], GridPosition(0, 0, 3), 0)

    feasibility = assess_baseline_feasibility(
        (lower, slope),
        (lower,),
        ((0,),),
        frozen_placements=(slope,),
        max_parts=2,
        protected_empty_cells=(),
    )

    assert feasibility.feasible
    assert feasibility.baseline_candidate_indices == (0,)


def test_baseline_feasibility_reports_vocabulary_and_coverage_mismatches() -> None:
    grounded = _plate(0, 0, 0)
    unsupported = _plate(2, 0, 1)

    feasibility = assess_baseline_feasibility(
        (grounded, unsupported),
        (grounded, _plate(4, 0, 0)),
        ((1,),),
        frozen_placements=(),
        max_parts=2,
        protected_empty_cells=(),
    )

    assert not feasibility.feasible
    assert "candidate_vocabulary_mismatch" in feasibility.reasons
    assert "support_constraint_mismatch" in feasibility.reasons
    assert "projection_coverage_mismatch" in feasibility.reasons


def test_verified_pairs_exclude_overlap_unevaluated_and_wrong_height() -> None:
    valid_lower = _plate(0, 0, 0)
    valid_upper = _plate(0, 0, 1)
    overlap = _plate(0, 0, 0)
    wrong_height = _plate(2, 0, 2)
    wedge = BrickPlacement(PART_BY_ID["41769"], GridPosition(4, 0, 0), 0)

    pairs = verified_connection_pairs((valid_lower, valid_upper, overlap, wrong_height, wedge))

    assert (0, 1) in {(pair.first_candidate_index, pair.second_candidate_index) for pair in pairs}
    assert all(3 not in (pair.first_candidate_index, pair.second_candidate_index) for pair in pairs)
    assert all(4 not in (pair.first_candidate_index, pair.second_candidate_index) for pair in pairs)


def test_connection_objective_selects_a_real_bridge_without_extra_parts() -> None:
    # Two equally covering choices: candidate 1 is isolated while candidate 2
    # completes a verified vertical chain from candidate 0 to candidate 3.
    lower = _plate(0, 0, 0)
    isolated = _plate(3, 0, 0)
    bridge = _plate(0, 0, 1)
    upper = _plate(0, 0, 2)

    result = solve_coverage_preserving_connectivity(
        (lower, isolated, bridge, upper),
        ((0,), (1, 2), (3,)),
        max_parts=3,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.selected_candidate_indices == (0, 2, 3)
    assert result.selected_connection_pair_count == 2
    assert result.selected_stud_contact_count == 2
    assert result.buildability.connected_component_count == 1
    assert result.buildability.largest_connected_component_ratio == 1.0


def test_pair_score_counts_one_graph_edge_for_multiple_studs() -> None:
    lower = BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0)
    upper = BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 3), 0)

    pairs = verified_connection_pairs((lower, upper))

    assert len(pairs) == 1
    assert pairs[0].stud_contact_count == 8


def test_indexed_pairs_match_exhaustive_oracle_for_mixed_fixture() -> None:
    # The same fixture exercises a single stud, a multi-stud connection, a
    # rotated part, wrong-height candidates, overlap, duplicate coordinates,
    # and an unevaluated family.  Compare the complete edge records, not only
    # the count, before trusting the sparse index.
    placements = (
        _plate(0, 0, 0),
        _plate(0, 0, 1),
        BrickPlacement(PART_BY_ID["3001"], GridPosition(4, 0, 0), 90),
        BrickPlacement(PART_BY_ID["3001"], GridPosition(4, 0, 3), 90),
        _plate(0, 0, 0),
        _plate(0, 0, 3),
        BrickPlacement(PART_BY_ID["41769"], GridPosition(8, 0, 0), 0),
        _plate(10, 0, 0),
        _plate(10, 0, 1),
    )

    indexed, metrics = indexed_verified_connection_pairs(placements)

    assert indexed == exhaustive_verified_connection_pairs(placements)
    assert indexed == tuple(
        sorted(
            indexed,
            key=lambda pair: (pair.first_candidate_index, pair.second_candidate_index),
        )
    )
    assert metrics.candidate_pair_comparisons < metrics.naive_candidate_pair_comparisons
    indexed_pair_ids = {
        (pair.first_candidate_index, pair.second_candidate_index) for pair in indexed
    }
    assert len(indexed_pair_ids) == len(indexed)


def test_frozen_verified_placement_can_supply_direct_support() -> None:
    lower = _plate(0, 0, 0)
    upper = _plate(0, 0, 1)

    result = solve_coverage_preserving_connectivity(
        (upper,),
        ((0,),),
        max_parts=2,
        frozen_placements=(lower,),
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.selected_candidate_indices == (0,)
    assert result.buildability.connected_component_count == 1
    assert result.buildability.unsupported_placement_count == 0


def test_pair_bound_limits_only_the_objective_not_the_legal_graph(monkeypatch) -> None:
    import app.conversion.connectivity_experiment as experiment

    monkeypatch.setattr(experiment, "MAX_CONNECTION_PAIRS", 3)
    candidates = tuple(_plate(0, 0, 0) for _ in range(2)) + tuple(_plate(0, 0, 1) for _ in range(2))

    result = solve_coverage_preserving_connectivity(candidates, (), max_parts=4)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.potential_connection_pair_count == 4
    assert result.pair_metrics.compatible_pair_count == 4
    assert result.modeled_connection_pair_count == 3
    assert result.modeled_connection_pair_count < result.potential_connection_pair_count


def test_connected_v6_baseline_skips_the_optimizer_before_v7_preprocessing() -> None:
    box = next(case for case in benchmark.synthetic_cases() if case.case_id == "box")

    result = run_source_mesh_experiment(
        benchmark.glb_bytes(box.mesh), target_parts=12, max_parts=12
    )

    assert result.candidate_count == 0
    assert result.eligibility_reason == "baseline_already_connected"
    assert result.proposal.status == "BASELINE_ALREADY_CONNECTED"
    assert result.rejection_reason == "baseline_already_connected"
    baseline_pairs, _metrics = indexed_verified_connection_pairs(result.baseline.placements)
    assert len(baseline_pairs) == len(analyze_buildability(result.baseline.placements).edges)


def test_spatial_selection_round_robins_deterministically_across_buckets(monkeypatch) -> None:
    import app.conversion.connectivity_experiment as experiment

    monkeypatch.setattr(experiment, "MAX_CONNECTION_PAIRS", 2)
    placements = (
        _plate(0, 0, 0),
        _plate(0, 0, 1),
        _plate(1, 0, 1),
        _plate(8, 0, 0),
        _plate(8, 0, 1),
    )
    pairs = (
        PotentialConnection(0, 1, 1),
        PotentialConnection(0, 2, 8),
        PotentialConnection(3, 4, 1),
    )

    selected = _select_objective_pairs(
        pairs,
        placements,
        strategy=ObjectiveEdgeStrategy.SPATIALLY_BALANCED,
        candidate_baseline_components=(None,) * len(placements),
    )

    assert {(pair.first_candidate_index, pair.second_candidate_index) for pair in selected} == {
        (0, 2),
        (3, 4),
    }


def test_component_aware_selection_keeps_cross_component_opportunity(monkeypatch) -> None:
    import app.conversion.connectivity_experiment as experiment

    monkeypatch.setattr(experiment, "MAX_CONNECTION_PAIRS", 1)
    placements = (_plate(0, 0, 0), _plate(0, 0, 1), _plate(8, 0, 0))
    pairs = (PotentialConnection(0, 1, 8), PotentialConnection(1, 2, 1))

    selected = _select_objective_pairs(
        pairs,
        placements,
        strategy=ObjectiveEdgeStrategy.BASELINE_COMPONENT_AWARE,
        candidate_baseline_components=(0, 0, 1),
    )

    assert selected == (PotentialConnection(1, 2, 1),)


def test_selected_part_limit_prevents_objective_part_count_inflation() -> None:
    result = solve_coverage_preserving_connectivity(
        (_plate(0, 0, 0), _plate(0, 0, 1), _plate(0, 0, 2)),
        (),
        max_parts=3,
        selected_part_limit=2,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert len(result.placements) == 2


def test_v7_cylinder_improvement_survives_the_production_conversion_entry_point() -> None:
    cylinder = next(case for case in benchmark.synthetic_cases() if case.case_id == "cylinder")

    model = convert_glb(
        benchmark.glb_bytes(cylinder.mesh),
        ConversionSettings(
            target_parts=16,
            max_parts=16,
            algorithm_version=SURFACE_GRID_V7_CONNECTIVITY_AWARE,
        ),
    )

    buildability = analyze_buildability(model.placements)
    diagnostics = model.metadata.diagnostics
    assert model.part_count == 4
    assert buildability.connected_component_count == 1
    assert buildability.unsupported_placement_count == 0
    assert colliding_placement_pairs(model.placements) == ()
    assert diagnostics is not None
    assert diagnostics.connectivity_accepted
    assert diagnostics.connectivity_eligibility_reason is None
    assert diagnostics.connectivity_verified_pair_count == 7_260
    assert diagnostics.connectivity_modeled_edge_count == MAX_CONNECTION_PAIRS


def test_candidate_limit_falls_back_to_the_unchanged_v6_baseline(monkeypatch) -> None:
    import app.conversion.connectivity_experiment as experiment

    cylinder = next(case for case in benchmark.synthetic_cases() if case.case_id == "cylinder")
    source = benchmark.glb_bytes(cylinder.mesh)
    settings = ConversionSettings(
        target_parts=16,
        max_parts=16,
        algorithm_version=SURFACE_GRID_V7_CONNECTIVITY_AWARE,
    )
    v6 = convert_glb(
        source,
        ConversionSettings(
            target_parts=16,
            max_parts=16,
            algorithm_version="surface-grid-v6-shape-aware",
        ),
    )
    monkeypatch.setattr(experiment, "MAX_CONNECTIVITY_CANDIDATES", 1)

    v7 = convert_glb(source, settings)

    assert v7.placements == v6.placements
    assert v7.metadata.diagnostics is not None
    assert not v7.metadata.diagnostics.connectivity_optimization_attempted
    assert v7.metadata.diagnostics.connectivity_eligibility_reason == "candidate_limit_exceeded"
    assert v7.metadata.diagnostics.connectivity_fallback_reason == "candidate_limit_exceeded"


def test_candidate_limit_is_a_named_bounded_work_policy() -> None:
    assert MAX_CONNECTIVITY_CANDIDATES >= 1


def test_v7_requires_an_explicit_hard_part_limit() -> None:
    cylinder = next(case for case in benchmark.synthetic_cases() if case.case_id == "cylinder")

    with pytest.raises(ConversionError, match="requires a maximum parts limit"):
        convert_glb(
            benchmark.glb_bytes(cylinder.mesh),
            ConversionSettings(
                target_parts=16,
                algorithm_version=SURFACE_GRID_V7_CONNECTIVITY_AWARE,
            ),
        )
