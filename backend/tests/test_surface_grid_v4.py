from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import trimesh
from ortools.sat.python import cp_model

import app.conversion.surface_grid_v4 as surface_grid_v4
from app.conversion import benchmark, core
from app.conversion.buildability import analyze_buildability
from app.conversion.mechanical_connectors import (
    MechanicalInterfaceKind,
    resolve_part_mechanical_metadata,
    transform_connector_to_world,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.physical_geometry import colliding_placement_pairs
from app.conversion.surface_grid_v4 import (
    SolverStage,
    V4SolveFailure,
    _stage_one_deterministic_budget,
    projection_hull_target,
    solve_surface_grid_v4,
)
from app.workers.conversion_worker import serialize_lego_model

DOG_MODEL_PATH = Path.home() / "Downloads" / "dog-model.glb"


def _one_by_one_plate() -> core.BrickType:
    return next(
        part
        for part in core.BRICK_CATALOGUE
        if part.shape == "rectangular"
        and part.length_studs == 1
        and part.width_studs == 1
        and part.height_plates == 1
    )


def _two_by_one_plate() -> core.BrickType:
    return next(
        part
        for part in core.BRICK_CATALOGUE
        if part.shape == "rectangular"
        and part.length_studs == 2
        and part.width_studs == 1
        and part.height_plates == 1
    )


def _slope_4286(*, x: int = 0, y: int = 0, z: int = 1, orientation: int = 0) -> core.BrickPlacement:
    return core.BrickPlacement(PART_BY_ID["4286"], core.GridPosition(x, y, z), orientation)


def _required(cells: set[core.GridPosition]) -> set[tuple[str, int, int]]:
    return {
        pixel
        for cell in cells
        for pixel in (("front", cell.x, cell.z), ("side", cell.y, cell.z), ("top", cell.x, cell.y))
    }


def test_v4_is_the_default_algorithm_version() -> None:
    settings = core.ConversionSettings(target_parts=8)

    assert settings.algorithm_version == core.SURFACE_GRID_V4
    assert core.ALGORITHM_VERSION == core.SURFACE_GRID_V4


@pytest.mark.parametrize(
    ("target_parts", "expected_budget"),
    (
        (100, 20.0),
        (300, 20.0),
        (599, 20.0),
        (600, 40.0),
        (601, 40.0),
    ),
)
def test_stage_one_budget_scales_for_detailed_conversions(
    target_parts: int, expected_budget: float
) -> None:
    assert _stage_one_deterministic_budget(target_parts) == expected_budget


def test_stage_two_budget_remains_unchanged() -> None:
    assert surface_grid_v4.STAGE_TWO_MAX_DETERMINISTIC_TIME == 7.25


def test_projection_hull_keeps_locked_slope_cells_out_of_rectangular_target() -> None:
    rectangle = core.GridPosition(0, 0, 0)
    locked_slope = core.GridPosition(1, 0, 0)

    target, required = projection_hull_target(
        {rectangle},
        {locked_slope},
        core.GridSize(2, 1, 1),
    )

    assert target == frozenset({rectangle})
    assert ("front", 1, 0) in required
    assert ("top", 1, 0) in required


def test_default_and_explicit_algorithm_versions_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v3_model = object()
    v4_model = object()
    monkeypatch.setattr(core, "_convert_surface_grid_v3", lambda *_: v3_model)
    monkeypatch.setattr(core, "_convert_surface_grid_v4", lambda *_: v4_model)

    assert core.convert_glb(b"source", core.ConversionSettings(target_parts=8)) is v4_model
    assert (
        core.convert_glb(
            b"source",
            core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V3),
        )
        is v3_model
    )
    assert (
        core.convert_glb(
            b"source",
            core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V4),
        )
        is v4_model
    )


def test_v4_occupancy_prevents_overlapping_placements() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)}

    result = solve_surface_grid_v4(
        cells, _required(cells), (), core.BRICK_CATALOGUE, target_parts=100
    )
    occupied = [
        cell for placement in result.placements for cell in core._placement_cells(placement)
    ]

    assert len(occupied) == len(set(occupied))


def test_hard_part_limit_accepts_a_feasible_exact_boundary() -> None:
    cell = core.GridPosition(0, 0, 0)

    result = solve_surface_grid_v4(
        {cell},
        _required({cell}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        max_parts=1,
    )

    assert len(result.placements) == 1


def test_hard_part_limit_counts_locked_parts_and_blocks_repair() -> None:
    support_cell = core.GridPosition(0, 0, 0)

    with pytest.raises(V4SolveFailure, match="local part bound"):
        solve_surface_grid_v4(
            {support_cell},
            (),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
            locked_placements=(_slope_4286(),),
            max_parts=1,
        )


def test_hard_part_limit_includes_successful_repair_output() -> None:
    support_cell = core.GridPosition(0, 0, 0)

    result = solve_surface_grid_v4(
        {support_cell},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(_slope_4286(),),
        max_parts=2,
    )

    assert len(result.placements) + 1 == 2
    buildability = analyze_buildability((_slope_4286(), *result.placements))
    assert buildability.unsupported_placement_count == 0


def test_projection_hull_rejects_explicitly_protected_empty_cells() -> None:
    occupied = {core.GridPosition(0, 0, 0), core.GridPosition(2, 0, 0)}
    protected = {core.GridPosition(1, 0, 0)}

    target, _ = projection_hull_target(
        occupied,
        (),
        core.GridSize(3, 1, 1),
        protected_empty_cells=protected,
    )

    assert core.GridPosition(1, 0, 0) not in target


def test_watertight_source_occupancy_keeps_a_face_enclosed_cell_safe() -> None:
    grid_size = core.GridSize(3, 3, 3)
    surface = frozenset(
        core.GridPosition(x, y, z)
        for x in range(3)
        for y in range(3)
        for z in range(3)
        if (x, y, z) != (1, 1, 1)
    )

    interior = core._safe_interior_cells(surface, grid_size, mesh_is_watertight=True)

    assert interior == {core.GridPosition(1, 1, 1)}


@pytest.mark.parametrize(
    ("exterior_cell", "connection"),
    (
        (core.GridPosition(0, 1, 1), "face"),
        (core.GridPosition(0, 0, 1), "edge"),
        (core.GridPosition(0, 0, 0), "corner"),
    ),
)
def test_v5_protects_empty_space_connected_to_exterior(
    exterior_cell: core.GridPosition, connection: str
) -> None:
    grid_size = core.GridSize(3, 3, 3)
    cavity = core.GridPosition(1, 1, 1)
    surface = frozenset(
        core.GridPosition(x, y, z)
        for x in range(3)
        for y in range(3)
        for z in range(3)
        if core.GridPosition(x, y, z) not in {cavity, exterior_cell}
    )
    occupancy = core.SourceOccupancy(
        surface_cells=surface,
        safe_interior_cells=core._safe_interior_cells(
            surface,
            grid_size,
            mesh_is_watertight=True,
        ),
        mesh_is_watertight=True,
    )

    protected = core._v5_protected_empty_cells(occupancy, grid_size)

    assert exterior_cell in protected, connection
    if connection == "face":
        assert cavity in protected
    else:
        assert cavity not in protected


def test_slope_source_cells_follow_the_ramp_profile_not_its_bounding_box() -> None:
    slope = _slope_4286()

    occupied = core._placement_source_cells(slope)

    assert core.GridPosition(0, 0, 3) not in occupied
    assert core.GridPosition(2, 0, 3) in occupied


def test_reliable_repair_prunes_optional_candidates_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = surface_grid_v4._Candidate(
        core.BrickPlacement(_one_by_one_plate(), core.GridPosition(0, 0, 0), 0),
        frozenset({core.GridPosition(0, 0, 0)}),
    )
    candidates = tuple(candidate for _ in range(surface_grid_v4.MAX_RELIABLE_REPAIR_CANDIDATES + 4))
    monkeypatch.setattr(surface_grid_v4, "MAX_RELIABLE_REPAIR_CANDIDATES", 3)

    pruned = surface_grid_v4._prune_reliable_repair_candidates(
        candidates,
        set(range(7)),
        {0},
        {core.GridPosition(0, 0, 0)},
    )

    assert pruned == {0, 1, 2}


def test_reliable_repair_candidate_limit_reports_essential_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = surface_grid_v4._Candidate(
        core.BrickPlacement(_one_by_one_plate(), core.GridPosition(0, 0, 0), 0),
        frozenset({core.GridPosition(0, 0, 0)}),
    )
    monkeypatch.setattr(surface_grid_v4, "MAX_RELIABLE_REPAIR_CANDIDATES", 2)

    with pytest.raises(V4SolveFailure, match="reason=candidate_limit_exhausted"):
        surface_grid_v4._prune_reliable_repair_candidates(
            (candidate, candidate, candidate),
            {0, 1, 2},
            {0, 1, 2},
            {core.GridPosition(0, 0, 0)},
        )


def test_reliable_version_is_explicit_and_preserves_a_hard_cap() -> None:
    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)

    model = core.convert_glb(
        source,
        core.ConversionSettings(
            target_parts=8,
            max_parts=8,
            algorithm_version=core.SURFACE_GRID_V5_RELIABLE,
        ),
    )

    assert model.metadata.algorithm_version == core.SURFACE_GRID_V5_RELIABLE
    assert model.part_count <= 8
    assert analyze_buildability(model.placements).unsupported_placement_count == 0
    assert colliding_placement_pairs(model.placements) == ()


def test_shape_aware_version_is_explicit_and_uses_the_reliable_fallback() -> None:
    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)

    model = core.convert_glb(
        source,
        core.ConversionSettings(
            target_parts=8,
            max_parts=8,
            algorithm_version=core.SURFACE_GRID_V6_SHAPE_AWARE,
        ),
    )

    assert model.metadata.algorithm_version == core.SURFACE_GRID_V6_SHAPE_AWARE
    assert model.part_count <= 8
    assert model.metadata.diagnostics is not None
    assert model.metadata.diagnostics.physical_collision_pair_count == 0
    assert model.metadata.diagnostics.unsupported_evaluated_placement_count == 0
    assert model.metadata.diagnostics.shape_aware_rejection_reason is not None
    assert colliding_placement_pairs(model.placements) == ()
    serialized = serialize_lego_model(model)
    assert b'"shapeAware"' in serialized
    assert b'"physicalCollisionPairs":0' in serialized


def test_shape_aware_refinement_selects_4286_for_a_source_ramp() -> None:
    """The candidate wins only because its actual slope silhouette fits the mesh."""
    brick = PART_BY_ID["3005"]
    baseline = tuple(
        core.BrickPlacement(brick, core.GridPosition(x, 0, 0), 0)
        for x in range(3)
    )
    source_slope = _slope_4286(z=0)
    vertices = core._slope_vertices((source_slope,))[0]
    faces = (
        (0, 1, 2),
        (3, 5, 4),
        (0, 4, 1),
        (0, 3, 4),
        (1, 4, 5),
        (1, 5, 2),
        (0, 2, 5),
        (0, 5, 3),
    )

    refined, candidate_count, accepted_count, rejected_count = core._shape_aware_4286_refinement(
        baseline,
        vertices,
        faces,
        core.GridSize(3, 1, 3),
        target_parts=3,
        protected_empty_cells=frozenset(),
        max_parts=3,
    )

    assert candidate_count == 2
    assert accepted_count == 1
    assert rejected_count == 1
    assert [(placement.brick_type.part_id, placement.position) for placement in refined] == [
        ("4286", core.GridPosition(0, 0, 0))
    ]
    refined_score = core._fidelity_for_placements(vertices, faces, refined, 3).mean_iou
    baseline_score = core._fidelity_for_placements(vertices, faces, baseline, 3).mean_iou
    assert refined_score > baseline_score
    assert analyze_buildability(refined).unsupported_placement_count == 0


def test_shape_aware_refinement_preserves_baseline_when_a_slope_worsens_source_fit() -> None:
    brick = PART_BY_ID["3005"]
    baseline = tuple(
        core.BrickPlacement(brick, core.GridPosition(x, 0, 0), 0)
        for x in range(3)
    )
    vertices = (
        (0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0), (0.0, 1.0, 0.0),
        (0.0, 0.0, 3.0), (3.0, 0.0, 3.0), (3.0, 1.0, 3.0), (0.0, 1.0, 3.0),
    )
    faces = ((0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6))

    refined, _, accepted_count, rejected_count = core._shape_aware_4286_refinement(
        baseline, vertices, faces, core.GridSize(3, 1, 3), 3, frozenset(), 3
    )

    assert refined == baseline
    assert accepted_count == 0
    assert rejected_count == 2


def test_shape_aware_policy_rejects_silhouette_gain_with_material_chamfer_regression() -> None:
    baseline = core._fidelity_for_placements(
        ((0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0)),
        ((0, 1, 2),),
        (),
        3,
    )
    proposal = replace(baseline, mean_iou=baseline.mean_iou + 0.01)
    incumbent_geometry = SimpleNamespace(
        status="available", symmetric_chamfer_mm=2.628469, percentile_95_nearest_surface_mm=8.008274
    )
    proposal_geometry = SimpleNamespace(
        status="available", symmetric_chamfer_mm=2.700512, percentile_95_nearest_surface_mm=8.096295
    )

    assert not core._shape_aware_fidelity_is_acceptable(
        baseline, proposal, incumbent_geometry, proposal_geometry
    )


def test_reliable_capped_open_box_produces_a_mechanically_valid_incumbent() -> None:
    open_box = next(case for case in benchmark.synthetic_cases() if case.case_id == "open-box")

    model = core.convert_glb(
        benchmark.glb_bytes(open_box.mesh),
        core.ConversionSettings(
            target_parts=100,
            max_parts=100,
            algorithm_version=core.SURFACE_GRID_V5_RELIABLE,
        ),
    )

    assert model.part_count <= 100
    assert model.metadata.grid_size == core.GridSize(8, 5, 15)
    assert model.metadata.diagnostics is not None
    assert model.metadata.diagnostics.stage_one_has_incumbent
    assert analyze_buildability(model.placements).unsupported_placement_count == 0


def test_reliable_uncapped_sphere_repairs_every_elevated_locked_slope() -> None:
    sphere = next(case for case in benchmark.synthetic_cases() if case.case_id == "sphere")
    source = benchmark.glb_bytes(sphere.mesh)
    settings = core.ConversionSettings(
        target_parts=100,
        algorithm_version=core.SURFACE_GRID_V5_RELIABLE,
    )

    model = core.convert_glb(source, settings)

    assert model.placements
    assert model.metadata.diagnostics is not None
    assert model.metadata.diagnostics.stage_one_has_incumbent
    assert model.metadata.diagnostics.stage_two_has_incumbent

    # The reliable conversion locks the v3 slopes, then repairs their verified
    # connectors. CP-SAT may return different feasible rectangular incumbents
    # on different supported platforms, so validate the mechanical contract
    # instead of an incidental total part count.
    baseline = core._convert_surface_grid_v3(
        source,
        core.ConversionSettings(target_parts=settings.target_parts, up_axis=settings.up_axis),
    )
    locked_slopes = tuple(
        placement
        for placement in baseline.placements
        if placement.brick_type.shape != "rectangular"
    )
    final_slopes = tuple(
        placement
        for placement in model.placements
        if placement.brick_type.shape != "rectangular"
    )
    assert model.metadata.grid_size == baseline.metadata.grid_size
    assert core._placement_geometry(final_slopes) == core._placement_geometry(locked_slopes)

    buildability = analyze_buildability(model.placements)
    base_z = min(placement.position.z for placement in model.placements)
    supported_indices = {edge.upper_placement_index for edge in buildability.edges}
    elevated_locked_slope_indices = {
        index
        for index, placement in enumerate(model.placements)
        if placement.brick_type.shape != "rectangular" and placement.position.z > base_z
    }
    assert elevated_locked_slope_indices
    assert all(
        resolve_part_mechanical_metadata(model.placements[index].brick_type) is not None
        for index in elevated_locked_slope_indices
    )
    assert elevated_locked_slope_indices <= supported_indices
    assert buildability.unsupported_placement_count == 0

    occupied_cells: set[core.GridPosition] = set()
    for placement in model.placements:
        placement_cells = core._placement_source_cells(placement)
        assert not occupied_cells & placement_cells
        occupied_cells.update(placement_cells)

    mesh = core._load_mesh(source)
    vertices = [
        (float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices.tolist()
    ]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces.tolist()]
    source_occupancy = core._source_occupancy(
        core._normalize_vertices(vertices, settings.up_axis),
        faces,
        baseline.metadata.grid_size,
    )
    protected_empty_cells = core._v5_protected_empty_cells(
        source_occupancy,
        baseline.metadata.grid_size,
    )
    assert not any(
        core._placement_source_cells(placement) & protected_empty_cells
        for placement in model.placements
    )


def test_legacy_converter_rejects_a_hard_part_limit() -> None:
    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)

    with pytest.raises(core.ConversionError, match="surface-grid-v5-reliable"):
        core.convert_glb(
            source,
            core.ConversionSettings(target_parts=8, max_parts=8),
        )


def test_v4_does_not_select_an_unsupported_non_base_placement() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(0, 0, 3)}

    result = solve_surface_grid_v4(
        cells,
        {("front", 0, 3)},
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert result.placements == ()


def test_v4_selects_directly_supported_placement() -> None:
    cells = {core.GridPosition(0, 0, z) for z in range(4)}

    result = solve_surface_grid_v4(
        cells, _required(cells), (), core.BRICK_CATALOGUE, target_parts=100
    )

    assert any(placement.position.z > 0 for placement in result.placements)
    assert analyze_buildability(result.placements).unsupported_placement_count == 0


@pytest.mark.parametrize("support_x", (0, 1, 2))
def test_locked_4286_requires_one_real_receiver_aligned_rectangular_support(
    support_x: int,
) -> None:
    lower_cell = core.GridPosition(support_x, 0, 0)
    slope = _slope_4286()

    result = solve_surface_grid_v4(
        {lower_cell},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    assert [placement.position for placement in result.placements] == [lower_cell]
    assert analyze_buildability((slope, *result.placements)).unsupported_placement_count == 0


def test_locked_4286_can_select_any_of_several_real_rectangular_supporters() -> None:
    lower_cells = {core.GridPosition(x, 0, 0) for x in range(3)}
    slope = _slope_4286()

    result = solve_surface_grid_v4(
        lower_cells,
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    assert len(result.placements) == 1
    assert result.placements[0].position in lower_cells
    assert analyze_buildability((slope, *result.placements)).unsupported_placement_count == 0


def test_valid_locked_baseline_is_an_exact_repair_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lower_cell = core.GridPosition(0, 0, 0)
    slope = _slope_4286()
    baseline = solve_surface_grid_v4(
        {lower_cell},
        _required({lower_cell}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    def fail_if_repair_runs(*_: object) -> object:
        pytest.fail("A mechanically valid baseline must not build a repair model.")

    monkeypatch.setattr(surface_grid_v4, "_solve_support_repair", fail_if_repair_runs)
    result = solve_surface_grid_v4(
        {lower_cell},
        _required({lower_cell}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    assert result.placements == baseline.placements
    assert analyze_buildability((slope, *result.placements)).unsupported_placement_count == 0


def test_local_repair_adds_support_without_replacing_an_unrelated_baseline_placement() -> None:
    supporter_cell = core.GridPosition(0, 0, 0)
    baseline_cell = core.GridPosition(10, 0, 0)
    slope = _slope_4286()

    result = solve_surface_grid_v4(
        {supporter_cell, baseline_cell},
        _required({baseline_cell}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    assert {placement.position for placement in result.placements} == {
        supporter_cell,
        baseline_cell,
    }
    assert analyze_buildability((slope, *result.placements)).unsupported_placement_count == 0


def test_local_repair_keeps_an_intersecting_replacement_that_preserves_coverage() -> None:
    """A required supporter needs a replacement beyond the old local region."""
    baseline = core.BrickPlacement(_two_by_one_plate(), core.GridPosition(0, 0, 0), 0)
    required_supporter = core.BrickPlacement(_two_by_one_plate(), core.GridPosition(1, 0, 0), 0)
    replacement = core.BrickPlacement(_two_by_one_plate(), core.GridPosition(-1, 0, 0), 0)
    candidates = tuple(
        surface_grid_v4._Candidate(placement, core._placement_cells(placement))
        for placement in (baseline, required_supporter, replacement)
    )
    candidate_males = tuple(
        frozenset(surface_grid_v4._male_connector_coordinates((candidate.placement,)))
        for candidate in candidates
    )
    candidate_receivers = tuple(
        frozenset(surface_grid_v4._receiver_connector_coordinates(candidate.placement))
        for candidate in candidates
    )
    locked_slope = _slope_4286(x=2)
    target_cells = frozenset(cell for candidate in candidates for cell in candidate.cells)
    variable_pixels = tuple(
        sorted(
            surface_grid_v4._pixels_for_cells(candidates[0].cells),
            key=surface_grid_v4._pixel_order,
        )
    )
    cells_by_pixel = surface_grid_v4._cells_by_pixel(target_cells)
    local_ids = surface_grid_v4._repair_local_candidate_ids(
        candidates,
        frozenset({0}),
        {1},
        set(),
        set(),
        candidate_males,
        candidate_receivers,
        set(),
        base_z=0,
    )

    assert local_ids == (0, 1, 2)

    with pytest.raises(V4SolveFailure, match="local part bound"):
        surface_grid_v4._solve_support_repair(
            candidates,
            frozenset({0}),
            frozenset(),
            (0, 1),
            (locked_slope,),
            candidate_males,
            candidate_receivers,
            set(),
            0,
            variable_pixels,
            cells_by_pixel,
            allowed_repair_count=3,
        )

    repaired = surface_grid_v4._solve_support_repair(
        candidates,
        frozenset({0}),
        frozenset(),
        local_ids,
        (locked_slope,),
        candidate_males,
        candidate_receivers,
        set(),
        0,
        variable_pixels,
        cells_by_pixel,
        allowed_repair_count=3,
    )

    assert repaired.repaired_ids == (1, 2)
    repaired_placements = tuple(
        candidates[candidate_id].placement for candidate_id in repaired.repaired_ids
    )
    assert analyze_buildability(
        (locked_slope, *repaired_placements)
    ).unsupported_placement_count == 0


def test_compact_local_repair_stays_within_its_derived_part_bound() -> None:
    slope = _slope_4286()

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0)},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    component = result.repair_diagnostics.components[0]
    assert component.selected_repair_count == 1
    assert component.allowed_repair_count == 2
    assert component.maximum_support_chain_depth == 1
    assert [stage.status for stage in component.solver_stages] == ["OPTIMAL", "OPTIMAL", "OPTIMAL"]
    assert analyze_buildability((slope, *result.placements)).unsupported_placement_count == 0


def test_local_repair_rejects_a_support_chain_that_exceeds_its_derived_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slope = _slope_4286(z=10)
    chain_cells = {core.GridPosition(0, 0, z) for z in range(10)}

    with pytest.raises(V4SolveFailure, match="local part bound"):
        solve_surface_grid_v4(
            chain_cells,
            (),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
            locked_placements=(slope,),
        )

    monkeypatch.setattr(surface_grid_v4, "REPAIR_ALLOWANCE_PER_UNSUPPORTED_CONSUMER", 10)
    unrestricted_result = solve_surface_grid_v4(
        chain_cells,
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    component = unrestricted_result.repair_diagnostics.components[0]
    assert component.selected_repair_count == 10
    assert component.maximum_support_chain_depth == 10
    assert analyze_buildability(
        (slope, *unrestricted_result.placements)
    ).unsupported_placement_count == 0


def test_one_local_repair_candidate_can_support_overlapping_slope_receiver_sets() -> None:
    shared_supporter = core.GridPosition(2, 0, 0)
    baseline_cell = core.GridPosition(10, 0, 0)
    lower_slope = _slope_4286()
    adjacent_slope = _slope_4286(x=2)

    result = solve_surface_grid_v4(
        {shared_supporter, baseline_cell},
        _required({baseline_cell}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(lower_slope, adjacent_slope),
    )

    assert {placement.position for placement in result.placements} == {
        shared_supporter,
        baseline_cell,
    }
    assert analyze_buildability(
        (lower_slope, adjacent_slope, *result.placements)
    ).unsupported_placement_count == 0


def test_locked_4286_does_not_accept_bounding_box_overlap_or_the_wrong_vertical_level() -> None:
    slope = _slope_4286()

    with pytest.raises(V4SolveFailure, match="no possible mechanical supporter"):
        solve_surface_grid_v4(
            {core.GridPosition(3, 0, 0)},
            (),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
            locked_placements=(slope,),
        )

    with pytest.raises(V4SolveFailure, match="no possible mechanical supporter"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 1)},
            (),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
            locked_placements=(_slope_4286(z=3),),
        )


@pytest.mark.parametrize("orientation", (0, 90, 180, 270))
def test_locked_4286_receiver_constraint_uses_the_existing_rotation_transform(
    orientation: int,
) -> None:
    slope = _slope_4286(x=10, y=20, orientation=orientation)
    metadata = resolve_part_mechanical_metadata(slope.brick_type)
    assert metadata is not None
    receiver = next(
        connector
        for connector in metadata.connectors
        if connector.interface_kind == MechanicalInterfaceKind.STUD_RECEIVER
    )
    world_receiver = transform_connector_to_world(
        receiver,
        slope.brick_type,
        slope.position,
        slope.orientation_degrees,
    )
    lower_cell = core.GridPosition(
        int(world_receiver.coordinate[0] - 0.5),
        int(world_receiver.coordinate[1] - 0.5),
        int(world_receiver.coordinate[2] - 1),
    )

    result = solve_surface_grid_v4(
        {lower_cell},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(slope,),
    )

    assert result.placements[0].position == lower_cell
    assert analyze_buildability((slope, *result.placements)).unsupported_placement_count == 0


def test_ground_locked_4286_needs_no_lower_rectangular_support() -> None:
    result = solve_surface_grid_v4(
        {core.GridPosition(5, 0, 1)},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(_slope_4286(z=1),),
    )

    assert result.placements == ()


def test_locked_verified_placement_can_receive_support_from_another_locked_placement() -> None:
    lower_slope = _slope_4286(z=0)
    upper_slope = _slope_4286(x=2, z=3)

    result = solve_surface_grid_v4(
        {core.GridPosition(10, 0, 0)},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(lower_slope, upper_slope),
    )

    assert result.placements == ()
    assert analyze_buildability((lower_slope, upper_slope)).unsupported_placement_count == 0


def test_unevaluated_locked_part_does_not_create_a_support_constraint() -> None:
    wedge = core.BrickPlacement(PART_BY_ID["41769"], core.GridPosition(0, 0, 3), 0)

    result = solve_surface_grid_v4(
        {core.GridPosition(5, 0, 0)},
        (),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
        locked_placements=(wedge,),
    )

    assert result.placements == ()
    assert analyze_buildability((wedge,)).evaluated_placement_count == 0


def test_impossible_locked_4286_support_fails_before_producing_a_model() -> None:
    with pytest.raises(V4SolveFailure, match="no possible mechanical supporter"):
        solve_surface_grid_v4(
            {core.GridPosition(10, 0, 0)},
            (),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
            locked_placements=(_slope_4286(),),
        )


def test_final_v4_buildability_gate_includes_locked_verified_placements() -> None:
    unrelated_ground = core.BrickPlacement(PART_BY_ID["3020"], core.GridPosition(10, 0, 0), 0)
    with pytest.raises(V4SolveFailure, match="unsupported evaluated placement"):
        surface_grid_v4._validate_placements(
            (),
            frozenset({core.GridPosition(10, 0, 0)}),
            (unrelated_ground, _slope_4286()),
        )


def test_final_v4_validation_accepts_a_rectangle_supported_by_locked_4286() -> None:
    slope = _slope_4286(z=0)
    upper_plate = core.BrickPlacement(
        _one_by_one_plate(), core.GridPosition(2, 0, 3), 0
    )

    surface_grid_v4._validate_placements(
        (upper_plate,),
        frozenset({core.GridPosition(2, 0, 0), core.GridPosition(2, 0, 3)}),
        (slope,),
    )


def test_v4_projection_coverage_is_exact_or_of_occupied_cells() -> None:
    cells = {core.GridPosition(0, 0, 0), core.GridPosition(0, 1, 0)}

    result = solve_surface_grid_v4(
        cells,
        {("front", 0, 0)},
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert result.achieved_coverage == 1
    assert result.placements


def test_stage_two_preserves_stage_one_coverage_and_is_deterministic() -> None:
    cells = {core.GridPosition(x, 0, 0) for x in range(2)}
    required = _required(cells)

    first = solve_surface_grid_v4(
        cells, required, (), core.BRICK_CATALOGUE, target_parts=100
    )
    second = solve_surface_grid_v4(
        cells, required, (), core.BRICK_CATALOGUE, target_parts=100
    )

    assert first.achieved_coverage == len(required)
    assert first.placements == second.placements
    assert first.stage_two.objective_value is not None


def test_stage_one_optimal_solution_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSolver:
        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == 0

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        return FakeSolver(), SolverStage("OPTIMAL", 3, 0.0, True)

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0)},
        _required({core.GridPosition(0, 0, 0)}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert len(result.placements) == 1
    assert result.stage_one.status == "OPTIMAL"


def test_stage_one_feasible_solution_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSolver:
        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == 0

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        return FakeSolver(), SolverStage("FEASIBLE", 3, 0.0, False)

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0)},
        _required({core.GridPosition(0, 0, 0)}),
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert len(result.placements) == 1
    assert result.stage_one.status == "FEASIBLE"


@pytest.mark.parametrize(
    "stage_one",
    (SolverStage("UNKNOWN", None, 0.0, False), SolverStage("INFEASIBLE", None, 0.0, False)),
)
def test_stage_one_without_a_usable_incumbent_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    stage_one: SolverStage,
) -> None:
    def fake_solve(*_: object) -> tuple[object, SolverStage]:
        return object(), stage_one

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    with pytest.raises(V4SolveFailure, match="usable incumbent"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 0)},
            _required({core.GridPosition(0, 0, 0)}),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
        )


def test_unknown_stage_one_is_not_reported_as_infeasible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.conversion.surface_grid_v4._solve",
        lambda *_: (object(), SolverStage("UNKNOWN", None, 0.0, False)),
    )

    with pytest.raises(V4SolveFailure, match="reason=limit_exhausted"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 0)},
            _required({core.GridPosition(0, 0, 0)}),
            (),
            (_one_by_one_plate(),),
            target_parts=100,
        )


@pytest.mark.parametrize(
    ("stage_two", "expected_x"),
    [
        (SolverStage("OPTIMAL", 1, 0.0, True), 1),
        (SolverStage("FEASIBLE", 1, 0.0, False), 1),
        (SolverStage("UNKNOWN", None, 0.0, False), 0),
    ],
)
def test_stage_two_uses_a_usable_solution_or_falls_back_to_stage_one(
    monkeypatch: pytest.MonkeyPatch,
    stage_two: SolverStage,
    expected_x: int,
) -> None:
    calls = 0

    class FakeSolver:
        def __init__(self, selected_id: int) -> None:
            self.selected_id = selected_id

        def boolean_value(self, variable: cp_model.IntVar) -> bool:
            return variable.Index() == self.selected_id

    def fake_solve(*_: object) -> tuple[FakeSolver, SolverStage]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return FakeSolver(0), SolverStage("OPTIMAL", 1, 0.0, True)
        return FakeSolver(1), stage_two

    monkeypatch.setattr("app.conversion.surface_grid_v4._solve", fake_solve)

    result = solve_surface_grid_v4(
        {core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)},
        {("side", 0, 0)},
        (),
        (_one_by_one_plate(),),
        target_parts=100,
    )

    assert result.placements[0].position.x == expected_x


def test_solver_uses_deterministic_work_budgets_without_a_wall_clock_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeParameters:
        def __init__(self) -> None:
            self.max_deterministic_time = float("inf")
            self.num_search_workers = 0
            self.random_seed = 0
            self._max_time_in_seconds = float("inf")
            self.max_time_in_seconds_was_set = False

        @property
        def max_time_in_seconds(self) -> float:
            return self._max_time_in_seconds

        @max_time_in_seconds.setter
        def max_time_in_seconds(self, value: float) -> None:
            self.max_time_in_seconds_was_set = True
            self._max_time_in_seconds = value

    class FakeSolver:
        def __init__(self) -> None:
            self.parameters = FakeParameters()
            self.objective_value = 1.0
            self.best_objective_bound = 1.0

        def solve(self, model: cp_model.CpModel) -> int:
            return int(cp_model.OPTIMAL)

        def status_name(self, status: int) -> str:
            return "OPTIMAL"

    solvers: list[FakeSolver] = []

    def new_solver() -> FakeSolver:
        solver = FakeSolver()
        solvers.append(solver)
        return solver

    monkeypatch.setattr("app.conversion.surface_grid_v4.cp_model.CpSolver", new_solver)

    surface_grid_v4._solve(
        cp_model.CpModel(), surface_grid_v4.STAGE_ONE_MAX_DETERMINISTIC_TIME
    )
    surface_grid_v4._solve(
        cp_model.CpModel(), surface_grid_v4.STAGE_TWO_MAX_DETERMINISTIC_TIME
    )

    assert [solver.parameters.max_deterministic_time for solver in solvers] == [20.0, 7.25]
    assert all(not solver.parameters.max_time_in_seconds_was_set for solver in solvers)
    assert all(solver.parameters.num_search_workers == 1 for solver in solvers)
    assert all(solver.parameters.random_seed == 0 for solver in solvers)


def test_empty_rectangular_volume_with_required_coverage_fails_explicitly() -> None:
    with pytest.raises(V4SolveFailure, match="no rectangular candidate volume"):
        solve_surface_grid_v4(
            (),
            {("front", 0, 0)},
            (),
            (_one_by_one_plate(),),
            target_parts=100,
        )


def test_empty_rectangular_candidates_with_required_coverage_fail_explicitly() -> None:
    with pytest.raises(V4SolveFailure, match="no rectangular candidates"):
        solve_surface_grid_v4(
            {core.GridPosition(0, 0, 0)},
            {("front", 0, 0)},
            (),
            (),
            target_parts=100,
        )


def test_locked_slope_only_conversion_skips_rectangular_solving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slope_shell = frozenset(
        {
            core.GridPosition(0, 0, 1),
            core.GridPosition(1, 0, 2),
            core.GridPosition(2, 0, 4),
        }
    )
    monkeypatch.setattr(core, "_surface_cells", lambda *_: slope_shell)

    def fail_if_solver_runs(*_: object) -> object:
        pytest.fail("Slope-only conversion should not invoke CP-SAT.")

    monkeypatch.setattr(surface_grid_v4, "_solve", fail_if_solver_runs)

    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)
    model = core.convert_glb(
        source,
        core.ConversionSettings(target_parts=24, algorithm_version=core.SURFACE_GRID_V4),
    )

    actual_placements = [
        (placement.brick_type.part_id, placement.position) for placement in model.placements
    ]
    assert actual_placements == [("4286", core.GridPosition(0, 0, 1))]
    buildability = analyze_buildability(model.placements)
    assert buildability.evaluated_placement_count == 1
    assert buildability.unevaluated_placement_count == 0
    serialized = serialize_lego_model(model)
    assert b'"partId":"4286"' in serialized
    assert b'"fidelity"' in serialized


def test_v4_real_path_serializes_the_canonical_output() -> None:
    source = trimesh.creation.box(extents=(4.0, 3.0, 2.0)).export(file_type="glb")
    assert isinstance(source, bytes)

    model = core.convert_glb(
        source,
        core.ConversionSettings(target_parts=8, algorithm_version=core.SURFACE_GRID_V4),
    )
    serialized = serialize_lego_model(model)

    assert model.metadata.algorithm_version == core.SURFACE_GRID_V4
    assert b'"algorithmVersion":"surface-grid-v4"' in serialized
    assert b'"buildability"' in serialized


@pytest.mark.skipif(
    not DOG_MODEL_PATH.is_file(),
    reason="The local dog-model.glb regression fixture is not available.",
)
def test_v4_local_dog_model_support_repair_regression() -> None:
    source = DOG_MODEL_PATH.read_bytes()

    assert len(source) == 1_393_684
    model = core.convert_glb(
        source,
        core.ConversionSettings(
            target_parts=300,
            up_axis=core.Axis.Y,
            algorithm_version=core.SURFACE_GRID_V4,
        ),
    )

    assert model.part_count == 571
    assert analyze_buildability(model.placements).unsupported_placement_count == 0
