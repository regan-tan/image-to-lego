"""Bounded verified vertical-stud connectivity optimization.

The offline harness and production V7 adapter share one exact-V6-compatible
vocabulary.  The final graph is always measured by ``analyze_buildability``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from time import perf_counter

from ortools.sat.python import cp_model

from app.conversion.benchmark import GeometricMetrics, evaluate_geometric_fidelity
from app.conversion.buildability import BuildabilityAnalysis, analyze_buildability
from app.conversion.core import (
    BRICK_CATALOGUE,
    RELIABLE_HARD_CAP_GRID_DIVISOR,
    SURFACE_GRID_V7_CONNECTIVITY_AWARE,
    Axis,
    BrickPlacement,
    ConversionSettings,
    GridPosition,
    GridSize,
    LegoModel,
    _convert_surface_grid_v3,
    _fidelity_for_placements,
    _load_mesh,
    _model_dimensions,
    _normalize_vertices,
    _place_supported_slopes,
    _placement_cells,
    _placement_source_cells,
    _scale_vertices_to_grid,
    _source_occupancy,
    _v5_protected_empty_cells,
    convert_glb,
)
from app.conversion.fidelity import FidelityMetrics
from app.conversion.mechanical_connectors import (
    MechanicalInterfaceKind,
    WorldMechanicalConnector,
    matching_vertical_connectors,
    resolve_part_mechanical_metadata,
    transform_connector_to_world,
)
from app.conversion.physical_geometry import physical_microcells, placements_overlap
from app.conversion.surface_grid_v4 import (
    _enumerate_candidates,
    _pixels_for_cells,
    _support_reachable_candidates,
    projection_hull_target,
)

# This is deterministic work, not a wall-clock service-level agreement.
MAX_DETERMINISTIC_TIME = 5.0
MAX_CONNECTION_PAIRS = 2_000
# The connectivity formulation contains one selected variable and several
# constraints per candidate.  A bounded objective alone does not bound that
# preprocessing or model construction work.  This keeps the experimental V7
# attempt within the fixture scale that has an accepted complete-model result.
MAX_CONNECTIVITY_CANDIDATES = 2_000
MIN_OBJECTIVE_EDGES_PER_CONNECTED_CANDIDATE = 1
SOLVER_RANDOM_SEED = 0


class ObjectiveEdgeStrategy(StrEnum):
    """Bounded, deterministic ways to choose edges for the CP-SAT objective."""

    CURRENT = "current"
    SPATIALLY_BALANCED = "spatially-balanced"
    BASELINE_COMPONENT_AWARE = "baseline-component-aware"


@dataclass(frozen=True, slots=True)
class PotentialConnection:
    """One legal placement pair with one or more verified stud matches."""

    first_candidate_index: int
    second_candidate_index: int
    stud_contact_count: int


@dataclass(frozen=True, slots=True)
class PairEnumerationMetrics:
    """Measured work performed while finding mechanically eligible pair edges."""

    candidate_count: int
    naive_candidate_pair_comparisons: int
    indexed_connector_lookups: int
    candidate_pair_comparisons: int
    overlap_rejection_count: int
    incompatibility_rejection_count: int
    compatible_pair_count: int
    runtime_seconds: float


@dataclass(frozen=True, slots=True)
class ObjectiveSelectionMetrics:
    """Audit data for the reduced objective graph, not final buildability."""

    strategy: ObjectiveEdgeStrategy
    eligible_pair_count: int
    modeled_pair_count: int
    participating_candidate_count: int
    frozen_incident_pair_count: int
    cross_component_pair_count: int
    selected_cross_component_pair_count: int
    height_bucket_counts: tuple[tuple[int, int], ...]
    spatial_bucket_counts: tuple[tuple[tuple[int, int, int], int], ...]
    candidate_degree_counts: tuple[tuple[int, int], ...]


class ConnectionPairLimitExceeded(ValueError):
    """The complete mechanical graph is too large for the bounded objective."""


@dataclass(frozen=True, slots=True)
class ConnectivityExperimentResult:
    """Auditable result of the coverage-preserving edge-count experiment."""

    status: str
    selected_candidate_indices: tuple[int, ...]
    potential_connection_pair_count: int
    modeled_connection_pair_count: int
    selected_connection_pair_count: int
    selected_stud_contact_count: int
    constraint_count: int
    model_build_seconds: float
    runtime_seconds: float
    buildability: BuildabilityAnalysis
    placements: tuple[BrickPlacement, ...]
    pair_metrics: PairEnumerationMetrics
    selection_metrics: ObjectiveSelectionMetrics


@dataclass(frozen=True, slots=True)
class BaselineFeasibility:
    """Whether the completed V6 assembly satisfies this experiment's inputs."""

    feasible: bool
    reasons: tuple[str, ...]
    baseline_candidate_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourceMeshExperiment:
    """Matched offline V6-versus-connectivity experiment for one GLB source."""

    source_sha256: str
    grid_size: GridSize
    candidate_count: int
    protected_empty_cell_count: int
    required_coverage: int
    baseline: LegoModel
    proposal: ConnectivityExperimentResult
    proposal_fidelity_mean_iou: float | None
    rejection_reason: str | None
    total_runtime_seconds: float = 0.0
    proposal_fidelity: FidelityMetrics | None = None
    baseline_geometric_fidelity: GeometricMetrics | None = None
    proposal_geometric_fidelity: GeometricMetrics | None = None
    baseline_feasibility: BaselineFeasibility | None = None
    eligibility_reason: str | None = None


def verified_connection_pairs(
    candidates: Collection[BrickPlacement],
    *,
    maximum_pairs: int = MAX_CONNECTION_PAIRS,
) -> tuple[PotentialConnection, ...]:
    """Return all indexed verified edges or reject an oversized objective.

    This public convenience wrapper deliberately does not truncate.  A caller
    that needs diagnostics may use ``indexed_verified_connection_pairs`` and
    decide how to report an oversized objective without misrepresenting the
    mechanical graph.
    """
    pairs, _metrics = indexed_verified_connection_pairs(candidates)
    if len(pairs) > maximum_pairs:
        raise ConnectionPairLimitExceeded(
            f"Verified connection graph has {len(pairs)} pairs; limit is {maximum_pairs}."
        )
    return pairs


def exhaustive_verified_connection_pairs(
    candidates: Collection[BrickPlacement],
) -> tuple[PotentialConnection, ...]:
    """Small-fixture correctness oracle for the connector-coordinate index."""
    placements = tuple(candidates)
    world_connectors = tuple(_world_connectors(placement) for placement in placements)
    pairs: list[PotentialConnection] = []
    for first_index, first in enumerate(placements):
        if not world_connectors[first_index]:
            continue
        for second_index in range(first_index + 1, len(placements)):
            if placements_overlap(first, placements[second_index]):
                continue
            matches = matching_vertical_connectors(
                world_connectors[first_index], world_connectors[second_index]
            )
            if matches:
                pairs.append(PotentialConnection(first_index, second_index, len(matches)))
    return tuple(pairs)


def indexed_verified_connection_pairs(
    candidates: Collection[BrickPlacement],
) -> tuple[tuple[PotentialConnection, ...], PairEnumerationMetrics]:
    """Find exact verified edges by joining transformed male/receiver coordinates.

    Connector coordinates are generated by the production transform and used as
    exact keys.  They are half-stud/plate-grid values, so rounding would create
    false interfaces.  The final matcher remains the authority for direction
    and interface compatibility.
    """
    started = perf_counter()
    placements = tuple(candidates)
    world_connectors = tuple(_world_connectors(placement) for placement in placements)
    overlapping_pairs = frozenset(_overlapping_candidate_pairs(placements))
    males_by_coordinate: dict[
        tuple[float, float, float], list[tuple[int, WorldMechanicalConnector]]
    ] = defaultdict(list)
    receivers_by_coordinate: dict[
        tuple[float, float, float], list[tuple[int, WorldMechanicalConnector]]
    ] = defaultdict(list)
    lookup_count = 0
    for candidate_index, connectors in enumerate(world_connectors):
        for connector in connectors:
            if connector.interface_kind == MechanicalInterfaceKind.MALE_STUD:
                males_by_coordinate[connector.coordinate].append((candidate_index, connector))
            elif connector.interface_kind == MechanicalInterfaceKind.STUD_RECEIVER:
                receivers_by_coordinate[connector.coordinate].append((candidate_index, connector))

    connector_pairs_by_candidate_pair: dict[
        tuple[int, int], list[tuple[WorldMechanicalConnector, WorldMechanicalConnector]]
    ] = defaultdict(list)
    for coordinate, male_entries in males_by_coordinate.items():
        receiver_entries = receivers_by_coordinate.get(coordinate, ())
        lookup_count += len(male_entries)
        for male_index, male_connector in male_entries:
            for receiver_index, receiver_connector in receiver_entries:
                if male_index != receiver_index:
                    if male_index < receiver_index:
                        candidate_pair = (male_index, receiver_index)
                    else:
                        candidate_pair = (receiver_index, male_index)
                    connector_pairs_by_candidate_pair[candidate_pair].append(
                        (male_connector, receiver_connector)
                    )

    overlap_rejections = 0
    incompatibility_rejections = 0
    pairs: list[PotentialConnection] = []
    for first_index, second_index in sorted(connector_pairs_by_candidate_pair):
        if (first_index, second_index) in overlapping_pairs:
            overlap_rejections += 1
            continue
        candidate_connector_pairs = connector_pairs_by_candidate_pair[(first_index, second_index)]
        matches = matching_vertical_connectors(
            tuple(pair[0] for pair in candidate_connector_pairs),
            tuple(pair[1] for pair in candidate_connector_pairs),
        )
        if not matches:
            incompatibility_rejections += 1
            continue
        pairs.append(PotentialConnection(first_index, second_index, len(matches)))

    metrics = PairEnumerationMetrics(
        candidate_count=len(placements),
        naive_candidate_pair_comparisons=len(placements) * (len(placements) - 1) // 2,
        indexed_connector_lookups=lookup_count,
        candidate_pair_comparisons=len(connector_pairs_by_candidate_pair),
        overlap_rejection_count=overlap_rejections,
        incompatibility_rejection_count=incompatibility_rejections,
        compatible_pair_count=len(pairs),
        runtime_seconds=perf_counter() - started,
    )
    return tuple(pairs), metrics


def solve_coverage_preserving_connectivity(
    candidates: Collection[BrickPlacement],
    coverage_groups: Collection[Collection[int]],
    *,
    max_parts: int,
    required_coverage: int | None = None,
    frozen_placements: Collection[BrickPlacement] = (),
    objective_edge_strategy: ObjectiveEdgeStrategy = ObjectiveEdgeStrategy.CURRENT,
    candidate_baseline_components: Collection[int | None] | None = None,
    selected_part_limit: int | None = None,
    selected_hint_indices: Collection[int] = (),
) -> ConnectivityExperimentResult:
    """Maximize verified placement-pair edges after preserving coverage.

    Each coverage group represents one matched source projection requirement;
    a selected candidate in the group covers it.  The caller must build this
    vocabulary from legal candidates at a fixed source/grid/physical scale.
    """
    placements = tuple(candidates)
    frozen = tuple(frozen_placements)
    component_ids = _validated_component_ids(candidate_baseline_components, len(placements))
    groups = tuple(tuple(sorted(set(group))) for group in coverage_groups)
    if max_parts < 0:
        raise ValueError("max_parts must be non-negative.")
    if selected_part_limit is not None and not 0 <= selected_part_limit <= max_parts:
        raise ValueError("selected_part_limit must be between zero and max_parts.")
    if any(
        not group or any(index < 0 or index >= len(placements) for index in group)
        for group in groups
    ):
        raise ValueError("Coverage groups must contain known candidates.")
    pairs, pair_metrics = indexed_verified_connection_pairs(placements)
    modeled_pairs = _select_objective_pairs(
        pairs,
        placements,
        strategy=objective_edge_strategy,
        candidate_baseline_components=component_ids,
    )
    selection_metrics = _objective_selection_metrics(
        pairs,
        modeled_pairs,
        placements,
        objective_edge_strategy,
        component_ids,
        frozen,
    )
    model_started = perf_counter()
    model = cp_model.CpModel()
    selected = tuple(model.new_bool_var(f"selected_{index}") for index in range(len(placements)))
    coverage = tuple(model.new_bool_var(f"coverage_{index}") for index in range(len(groups)))
    if len(frozen) > max_parts:
        raise ValueError("Frozen placements exceed max_parts.")
    effective_part_limit = max_parts if selected_part_limit is None else selected_part_limit
    if len(frozen) > effective_part_limit:
        raise ValueError("Frozen placements exceed the selected part limit.")
    model.add(sum(selected) <= effective_part_limit - len(frozen))
    for index in selected_hint_indices:
        if not 0 <= index < len(selected):
            raise ValueError("Selected hint contains an unknown candidate.")
        model.add_hint(selected[index], 1)
    for first_index, second_index in _overlapping_candidate_pairs(placements):
        model.add(selected[first_index] + selected[second_index] <= 1)
    for variable, group in zip(coverage, groups, strict=True):
        model.add_max_equality(variable, [selected[index] for index in group])
    if required_coverage is None:
        required_coverage = len(groups)
    model.add(sum(coverage) >= required_coverage)

    connections = tuple(
        model.new_bool_var(f"connection_{index}") for index in range(len(modeled_pairs))
    )
    for variable, pair in zip(connections, modeled_pairs, strict=True):
        # Exact AND linearization: a pair contributes only when both endpoints
        # are selected, never for mere geometric proximity.
        model.add(variable <= selected[pair.first_candidate_index])
        model.add(variable <= selected[pair.second_candidate_index])
        model.add(
            variable
            >= selected[pair.first_candidate_index] + selected[pair.second_candidate_index] - 1
        )

    base_z = min((placement.position.z for placement in placements), default=0)
    for candidate_index, placement in enumerate(placements):
        if placement.position.z == base_z:
            continue
        supporter_indices = tuple(
            pair.first_candidate_index
            if pair.second_candidate_index == candidate_index
            else pair.second_candidate_index
            for pair in pairs
            if candidate_index in (pair.first_candidate_index, pair.second_candidate_index)
            and placements[
                pair.first_candidate_index
                if pair.second_candidate_index == candidate_index
                else pair.second_candidate_index
            ].position.z
            < placement.position.z
        )
        has_frozen_support = any(
            _has_verified_connection(frozen_placement, placement) for frozen_placement in frozen
        )
        if supporter_indices or has_frozen_support:
            model.add(
                selected[candidate_index]
                <= sum(selected[index] for index in supporter_indices) + int(has_frozen_support)
            )
        else:
            model.add(selected[candidate_index] == 0)

    model.maximize(sum(connections))
    model_build_seconds = perf_counter() - model_started
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = MAX_DETERMINISTIC_TIME
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = SOLVER_RANDOM_SEED
    started = perf_counter()
    status_code = solver.solve(model)
    runtime_seconds = perf_counter() - started
    status = solver.status_name(status_code)
    if status not in {"OPTIMAL", "FEASIBLE"}:
        return ConnectivityExperimentResult(
            status,
            (),
            len(pairs),
            len(modeled_pairs),
            0,
            0,
            _constraint_count(model),
            model_build_seconds,
            runtime_seconds,
            analyze_buildability(()),
            (),
            pair_metrics,
            selection_metrics,
        )
    selected_indices = tuple(
        index for index, variable in enumerate(selected) if solver.boolean_value(variable)
    )
    selected_pairs = tuple(
        pair
        for pair, variable in zip(modeled_pairs, connections, strict=True)
        if solver.boolean_value(variable)
    )
    final_placements = frozen + tuple(placements[index] for index in selected_indices)
    return ConnectivityExperimentResult(
        status=status,
        selected_candidate_indices=selected_indices,
        potential_connection_pair_count=len(pairs),
        modeled_connection_pair_count=len(modeled_pairs),
        selected_connection_pair_count=len(selected_pairs),
        selected_stud_contact_count=sum(pair.stud_contact_count for pair in selected_pairs),
        constraint_count=_constraint_count(model),
        model_build_seconds=model_build_seconds,
        runtime_seconds=runtime_seconds,
        buildability=analyze_buildability(final_placements),
        placements=final_placements,
        pair_metrics=pair_metrics,
        selection_metrics=selection_metrics,
    )


def assess_baseline_feasibility(
    baseline: Collection[BrickPlacement],
    candidates: Collection[BrickPlacement],
    coverage_groups: Collection[Collection[int]],
    *,
    frozen_placements: Collection[BrickPlacement],
    max_parts: int,
    protected_empty_cells: Collection[GridPosition],
) -> BaselineFeasibility:
    """Diagnose whether exact completed V6 placements fit the experiment.

    This deliberately checks the actual final assembly, rather than inferring
    compatibility from the source-preparation helpers shared by V5/V6.
    """
    final = tuple(baseline)
    vocabulary = tuple(candidates)
    frozen = tuple(frozen_placements)
    frozen_geometry = {_placement_key(placement) for placement in frozen}
    candidate_indices = {
        _placement_key(placement): index for index, placement in enumerate(vocabulary)
    }
    selected_indices: list[int] = []
    reasons: list[str] = []
    for placement in final:
        key = _placement_key(placement)
        if key in frozen_geometry:
            continue
        index = candidate_indices.get(key)
        if index is None:
            reasons.append("candidate_vocabulary_mismatch")
        else:
            selected_indices.append(index)
    final_non_rectangular = {
        _placement_key(placement)
        for placement in final
        if placement.brick_type.shape != "rectangular"
    }
    if final_non_rectangular != frozen_geometry:
        reasons.append("locked_placement_mismatch")
    if len(final) > max_parts:
        reasons.append("part_count_mismatch")
    if any(_placement_source_cells(placement) & set(protected_empty_cells) for placement in final):
        reasons.append("protected_space_mismatch")
    if any(
        placements_overlap(first, second)
        for index, first in enumerate(final)
        for second in final[index + 1 :]
    ):
        reasons.append("collision_mismatch")
    if analyze_buildability(final).unsupported_placement_count:
        reasons.append("support_constraint_mismatch")
    selected_set = set(selected_indices)
    if any(not selected_set.intersection(group) for group in coverage_groups):
        reasons.append("projection_coverage_mismatch")
    return BaselineFeasibility(
        feasible=not reasons,
        reasons=tuple(sorted(set(reasons))),
        baseline_candidate_indices=tuple(sorted(selected_set)),
    )


def run_source_mesh_experiment(
    glb_bytes: bytes,
    *,
    target_parts: int = 100,
    max_parts: int = 100,
    up_axis: Axis = Axis.Y,
    objective_edge_strategy: ObjectiveEdgeStrategy = ObjectiveEdgeStrategy.CURRENT,
    additional_part_allowance: int = 0,
) -> SourceMeshExperiment:
    """Run an offline experiment with the completed V6 assembly as incumbent.

    The source-derived candidates remain available, but final V6 rectangular
    placements are added exactly and final non-rectangular placements are
    frozen. This makes support repair and shape-aware refinement auditable
    instead of silently excluding them from a purportedly fair comparison.
    """
    started = perf_counter()
    if additional_part_allowance < 0:
        raise ValueError("additional_part_allowance must be non-negative.")
    settings = ConversionSettings(
        target_parts=target_parts,
        max_parts=max_parts,
        up_axis=up_axis,
        algorithm_version="surface-grid-v6-shape-aware",
    )
    baseline = convert_glb(glb_bytes, settings)
    baseline_buildability = analyze_buildability(baseline.placements)
    # V7 accepts only a strict reduction in completed-model component count.
    # A one-component V6 assembly therefore cannot be accepted, regardless of
    # vocabulary, objective edges, or solver result.
    if baseline_buildability.connected_component_count <= 1:
        proposal = _rejected_result("BASELINE_ALREADY_CONNECTED", 0)
        return SourceMeshExperiment(
            sha256(glb_bytes).hexdigest(),
            baseline.metadata.grid_size,
            0,
            0,
            0,
            baseline,
            proposal,
            None,
            "baseline_already_connected",
            perf_counter() - started,
            eligibility_reason="baseline_already_connected",
        )
    grid_target_parts = min(target_parts, max(1, max_parts // RELIABLE_HARD_CAP_GRID_DIVISOR))
    v3 = _convert_surface_grid_v3(
        glb_bytes, ConversionSettings(target_parts=grid_target_parts, up_axis=up_axis)
    )
    mesh = _load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized_vertices = _normalize_vertices(vertices, up_axis)
    occupancy = _source_occupancy(normalized_vertices, faces, v3.metadata.grid_size)
    locked, locked_cells = _place_supported_slopes(occupancy.surface_cells)
    locked_occupied = frozenset(
        cell for placement in locked for cell in _placement_source_cells(placement)
    )
    exterior = frozenset(
        cell
        for placement in v3.placements
        if placement.brick_type.shape == "rectangular"
        for cell in _placement_cells(placement)
        if cell not in locked_occupied
    )
    protected = _v5_protected_empty_cells(occupancy, v3.metadata.grid_size)
    target, required_pixels = projection_hull_target(
        exterior, locked_cells, v3.metadata.grid_size, protected_empty_cells=protected
    )
    target = target - locked_occupied
    source_candidates = _support_reachable_candidates(
        _enumerate_candidates(target, BRICK_CATALOGUE), target
    )
    source_candidate_placements = tuple(candidate.placement for candidate in source_candidates)
    baseline_frozen = tuple(
        placement
        for placement in baseline.placements
        if placement.brick_type.shape != "rectangular"
    )
    baseline_rectangles = tuple(
        placement
        for placement in baseline.placements
        if placement.brick_type.shape == "rectangular"
    )
    candidate_placements = _merge_candidate_placements(
        source_candidate_placements, baseline_rectangles
    )
    if len(candidate_placements) > MAX_CONNECTIVITY_CANDIDATES:
        proposal = _rejected_result("CANDIDATE_LIMIT_EXCEEDED", len(candidate_placements))
        return SourceMeshExperiment(
            sha256(glb_bytes).hexdigest(),
            v3.metadata.grid_size,
            len(candidate_placements),
            len(protected),
            0,
            baseline,
            proposal,
            None,
            "candidate_limit_exceeded",
            perf_counter() - started,
            eligibility_reason="candidate_limit_exceeded",
        )
    candidate_components = _baseline_component_ids(candidate_placements, baseline.placements)
    # Coverage is defined from the completed assembly, not from the earlier
    # V3 exterior used to seed the source vocabulary.
    fixed_pixels = _pixels_for_cells(
        frozenset(
            cell for placement in baseline_frozen for cell in _placement_source_cells(placement)
        )
    )
    required_pixels = _pixels_for_cells(
        frozenset(
            cell for placement in baseline.placements for cell in _placement_source_cells(placement)
        )
    )
    variable_pixels = tuple(sorted(set(required_pixels) - fixed_pixels))
    coverage_groups = tuple(
        tuple(
            index
            for index, candidate in enumerate(candidate_placements)
            if pixel in _pixels_for_cells(_placement_source_cells(candidate))
        )
        for pixel in variable_pixels
    )
    feasibility = assess_baseline_feasibility(
        baseline.placements,
        candidate_placements,
        coverage_groups,
        frozen_placements=baseline_frozen,
        max_parts=max_parts,
        protected_empty_cells=protected,
    )
    # An empty group means even the baseline-augmented vocabulary cannot
    # preserve the completed V6 projection definition.
    if any(not group for group in coverage_groups):
        proposal = _rejected_result("NO_COVERAGE_VOCABULARY", len(candidate_placements))
        return SourceMeshExperiment(
            sha256(glb_bytes).hexdigest(),
            v3.metadata.grid_size,
            len(candidate_placements),
            len(protected),
            len(variable_pixels),
            baseline,
            proposal,
            None,
            "coverage_vocabulary_incomplete",
            perf_counter() - started,
            baseline_feasibility=feasibility,
        )
    if not feasibility.feasible:
        proposal = _rejected_result("BASELINE_INFEASIBLE", len(candidate_placements))
        return SourceMeshExperiment(
            sha256(glb_bytes).hexdigest(),
            v3.metadata.grid_size,
            len(candidate_placements),
            len(protected),
            len(variable_pixels),
            baseline,
            proposal,
            None,
            "baseline_infeasible:" + ",".join(feasibility.reasons),
            perf_counter() - started,
            baseline_feasibility=feasibility,
        )
    proposal = solve_coverage_preserving_connectivity(
        candidate_placements,
        coverage_groups,
        max_parts=max_parts,
        frozen_placements=baseline_frozen,
        objective_edge_strategy=objective_edge_strategy,
        candidate_baseline_components=candidate_components,
        # An edge-count objective otherwise has an artificial incentive to
        # fill unused capacity with small plates.  Gate A comparisons first
        # hold the proposal to the completed V6 part count.
        selected_part_limit=min(max_parts, baseline.part_count + additional_part_allowance),
        selected_hint_indices=feasibility.baseline_candidate_indices,
    )
    collisions = sum(
        placements_overlap(first, second)
        for index, first in enumerate(proposal.placements)
        for second in proposal.placements[index + 1 :]
    )
    protected_violations = sum(
        bool(_placement_source_cells(placement) & protected) for placement in proposal.placements
    )
    fidelity = None
    proposal_fidelity = None
    baseline_geometric_fidelity = None
    proposal_geometric_fidelity = None
    reason = None
    if proposal.status not in {"OPTIMAL", "FEASIBLE"}:
        reason = "solver_without_incumbent"
    elif proposal.buildability.unsupported_placement_count:
        reason = "unsupported_placement"
    elif collisions:
        reason = "physical_collision"
    elif protected_violations:
        reason = "protected_space_violation"
    else:
        scaled = _scale_vertices_to_grid(normalized_vertices, v3.metadata.grid_size)
        proposal_fidelity = _fidelity_for_placements(
            scaled, faces, proposal.placements, target_parts
        )
        fidelity = proposal_fidelity.mean_iou
        baseline_geometric_fidelity = evaluate_geometric_fidelity(
            list(scaled), faces, baseline.placements
        )
        proposal_geometric_fidelity = evaluate_geometric_fidelity(
            list(scaled), faces, proposal.placements
        )
        if fidelity < baseline.metadata.fidelity.mean_iou:
            reason = "fidelity_regression"
        elif not _improves_connectivity(proposal.buildability, baseline_buildability):
            reason = "no_final_connectivity_improvement"
    return SourceMeshExperiment(
        sha256(glb_bytes).hexdigest(),
        v3.metadata.grid_size,
        len(candidate_placements),
        len(protected),
        len(variable_pixels),
        baseline,
        proposal,
        fidelity,
        reason,
        perf_counter() - started,
        proposal_fidelity,
        baseline_geometric_fidelity,
        proposal_geometric_fidelity,
        feasibility,
    )


def convert_surface_grid_v7_connectivity_aware(
    glb_bytes: bytes, settings: ConversionSettings
) -> LegoModel:
    """Run the bounded V7 search and retain V6 whenever its final output loses.

    This is deliberately a small production adapter over the proven offline
    experiment.  It never exposes an intermediate CP-SAT selection: every
    accepted placement set has passed the complete final-assembly checks in
    ``run_source_mesh_experiment``.
    """
    if settings.max_parts is None:
        raise ValueError("surface-grid-v7-connectivity-aware requires max_parts.")
    result = run_source_mesh_experiment(
        glb_bytes,
        target_parts=settings.target_parts,
        max_parts=settings.max_parts,
        up_axis=settings.up_axis,
        objective_edge_strategy=ObjectiveEdgeStrategy.BASELINE_COMPONENT_AWARE,
    )
    proposal = result.proposal
    accepted = result.rejection_reason is None and _geometric_fidelity_is_not_worse(result)
    fallback_reason = result.rejection_reason
    if not accepted and fallback_reason is None:
        fallback_reason = "geometric_fidelity_regression"

    final = proposal.placements if accepted else result.baseline.placements
    baseline_diagnostics = result.baseline.metadata.diagnostics
    if baseline_diagnostics is None:
        raise ValueError("surface-grid-v7-connectivity-aware requires V6 diagnostics.")
    diagnostics = replace(
        baseline_diagnostics,
        connectivity_optimization_attempted=result.eligibility_reason is None,
        connectivity_eligibility_reason=result.eligibility_reason,
        connectivity_candidate_count=result.candidate_count,
        connectivity_verified_pair_count=proposal.potential_connection_pair_count,
        connectivity_modeled_edge_count=proposal.modeled_connection_pair_count,
        connectivity_solver_status=proposal.status,
        connectivity_solver_runtime_seconds=proposal.runtime_seconds,
        connectivity_accepted=accepted,
        connectivity_fallback_reason=fallback_reason,
        physical_collision_pair_count=sum(
            placements_overlap(first, second)
            for index, first in enumerate(final)
            for second in final[index + 1 :]
        ),
        unsupported_evaluated_placement_count=analyze_buildability(final).unsupported_placement_count,
    )
    mesh = _load_mesh(glb_bytes)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = _normalize_vertices(vertices, settings.up_axis)
    scaled = _scale_vertices_to_grid(normalized, result.baseline.metadata.grid_size)
    return LegoModel(
        placements=final,
        part_count=len(final),
        dimensions=_model_dimensions(final),
        metadata=replace(
            result.baseline.metadata,
            algorithm_version=SURFACE_GRID_V7_CONNECTIVITY_AWARE,
            occupied_cell_count=len(
                {cell for placement in final for cell in _placement_cells(placement)}
            ),
            fidelity=_fidelity_for_placements(scaled, faces, final, settings.target_parts),
            diagnostics=diagnostics,
        ),
    )


def _geometric_fidelity_is_not_worse(result: SourceMeshExperiment) -> bool:
    """Keep V7 at least as faithful as V6 on every available canonical metric."""
    baseline = result.baseline_geometric_fidelity
    proposal = result.proposal_geometric_fidelity
    if baseline is None or proposal is None:
        return False
    if baseline.status != "available" or proposal.status != "available":
        return False
    metrics = (
        (proposal.symmetric_chamfer_mm, baseline.symmetric_chamfer_mm),
        (proposal.normalized_symmetric_chamfer, baseline.normalized_symmetric_chamfer),
        (proposal.percentile_95_nearest_surface_mm, baseline.percentile_95_nearest_surface_mm),
    )
    return all(
        candidate is not None and incumbent is not None and candidate <= incumbent
        for candidate, incumbent in metrics
    )


def _world_connectors(placement: BrickPlacement) -> tuple[WorldMechanicalConnector, ...]:
    metadata = resolve_part_mechanical_metadata(placement.brick_type)
    if metadata is None:
        return ()
    return tuple(
        transform_connector_to_world(
            connector, placement.brick_type, placement.position, placement.orientation_degrees
        )
        for connector in metadata.connectors
    )


def _placement_key(placement: BrickPlacement) -> tuple[str, int, int, int, int]:
    """Identity relevant to the experimental physical placement vocabulary."""
    return (
        placement.brick_type.part_id,
        placement.orientation_degrees,
        placement.position.x,
        placement.position.y,
        placement.position.z,
    )


def _merge_candidate_placements(
    source_candidates: Collection[BrickPlacement], baseline_rectangles: Collection[BrickPlacement]
) -> tuple[BrickPlacement, ...]:
    """Keep source candidates and append missing final V6 geometry exactly."""
    merged: dict[tuple[str, int, int, int, int], BrickPlacement] = {
        _placement_key(placement): placement for placement in source_candidates
    }
    for placement in baseline_rectangles:
        # Preserve V6's placement object (including its verified color) for an
        # exact incumbent rather than a geometrically similar reconstruction.
        merged[_placement_key(placement)] = placement
    return tuple(merged[key] for key in sorted(merged))


def _has_verified_connection(first: BrickPlacement, second: BrickPlacement) -> bool:
    return bool(matching_vertical_connectors(_world_connectors(first), _world_connectors(second)))


def _rejected_result(status: str, candidate_count: int) -> ConnectivityExperimentResult:
    pair_metrics = PairEnumerationMetrics(
        candidate_count=candidate_count,
        naive_candidate_pair_comparisons=0,
        indexed_connector_lookups=0,
        candidate_pair_comparisons=0,
        overlap_rejection_count=0,
        incompatibility_rejection_count=0,
        compatible_pair_count=0,
        runtime_seconds=0.0,
    )
    selection_metrics = ObjectiveSelectionMetrics(
        ObjectiveEdgeStrategy.CURRENT, 0, 0, 0, 0, 0, 0, (), (), ()
    )
    return ConnectivityExperimentResult(
        status,
        (),
        0,
        0,
        0,
        0,
        0,
        0.0,
        0.0,
        analyze_buildability(()),
        (),
        pair_metrics,
        selection_metrics,
    )


def _constraint_count(model: cp_model.CpModel) -> int:
    return len(model.proto.constraints)


def _overlapping_candidate_pairs(
    placements: Collection[BrickPlacement],
) -> tuple[tuple[int, int], ...]:
    """Index physical microcells so overlap constraints are not all-pairs work."""
    occupied_by_cell: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    overlaps: set[tuple[int, int]] = set()
    for candidate_index, placement in enumerate(placements):
        for cell in physical_microcells(placement):
            for other_index in occupied_by_cell[cell]:
                overlaps.add((other_index, candidate_index))
            occupied_by_cell[cell].append(candidate_index)
    return tuple(sorted(overlaps))


def _select_objective_pairs(
    pairs: tuple[PotentialConnection, ...],
    placements: tuple[BrickPlacement, ...],
    *,
    strategy: ObjectiveEdgeStrategy,
    candidate_baseline_components: tuple[int | None, ...],
) -> tuple[PotentialConnection, ...]:
    """Bound the edge objective without changing the legal placement vocabulary.

    Direct-support constraints retain the full verified graph.  The reduced
    graph only limits what the secondary edge-count objective can reward.  It
    first reserves one deterministic incident edge for every connected
    candidate, then fills the remaining objective budget in stable order.
    Thus coverage and support feasibility are unchanged, and small bridge
    fixtures retain every edge they need to demonstrate the mechanism.
    """
    if len(pairs) <= MAX_CONNECTION_PAIRS:
        return tuple(sorted(pairs, key=_pair_key))

    if strategy == ObjectiveEdgeStrategy.SPATIALLY_BALANCED:
        return _spatially_balanced_pairs(pairs, placements)
    if strategy == ObjectiveEdgeStrategy.BASELINE_COMPONENT_AWARE:
        return _component_aware_pairs(pairs, placements, candidate_baseline_components)
    return _current_pairs(pairs, len(placements))


def _current_pairs(
    pairs: tuple[PotentialConnection, ...], candidate_count: int
) -> tuple[PotentialConnection, ...]:

    by_candidate: list[list[PotentialConnection]] = [[] for _ in range(candidate_count)]
    for pair in pairs:
        by_candidate[pair.first_candidate_index].append(pair)
        by_candidate[pair.second_candidate_index].append(pair)

    selected: set[PotentialConnection] = set()
    for candidate_pairs in by_candidate:
        if not candidate_pairs:
            continue
        selected.update(
            sorted(
                candidate_pairs,
                key=lambda pair: (
                    -pair.stud_contact_count,
                    pair.first_candidate_index,
                    pair.second_candidate_index,
                ),
            )[:MIN_OBJECTIVE_EDGES_PER_CONNECTED_CANDIDATE]
        )
    if len(selected) > MAX_CONNECTION_PAIRS:
        # The complete graph is still known and support constraints still use
        # it. This is a deterministic objective-only safety limit.
        selected = set(
            sorted(
                selected,
                key=lambda pair: (
                    -pair.stud_contact_count,
                    pair.first_candidate_index,
                    pair.second_candidate_index,
                ),
            )[:MAX_CONNECTION_PAIRS]
        )

    for pair in pairs:
        if len(selected) == MAX_CONNECTION_PAIRS:
            break
        selected.add(pair)
    return tuple(sorted(selected, key=_pair_key))


def _spatially_balanced_pairs(
    pairs: tuple[PotentialConnection, ...], placements: tuple[BrickPlacement, ...]
) -> tuple[PotentialConnection, ...]:
    """Round-robin deterministic buckets by edge midpoint and height.

    A bucket is intentionally coarse (two-stud horizontal and one-brick vertical
    cells), so this limits dense local strata without pretending to measure a
    global structural graph.
    """
    buckets: dict[tuple[int, int, int], list[PotentialConnection]] = defaultdict(list)
    for pair in pairs:
        buckets[_pair_spatial_bucket(pair, placements)].append(pair)
    for bucket_pairs in buckets.values():
        bucket_pairs.sort(key=_pair_priority)
    selected: list[PotentialConnection] = []
    bucket_keys = tuple(sorted(buckets))
    depth = 0
    while len(selected) < MAX_CONNECTION_PAIRS:
        added = False
        for bucket in bucket_keys:
            bucket_pairs = buckets[bucket]
            if depth < len(bucket_pairs):
                selected.append(bucket_pairs[depth])
                added = True
                if len(selected) == MAX_CONNECTION_PAIRS:
                    break
        if not added:
            break
        depth += 1
    return tuple(sorted(selected, key=_pair_key))


def _component_aware_pairs(
    pairs: tuple[PotentialConnection, ...],
    placements: tuple[BrickPlacement, ...],
    component_ids: tuple[int | None, ...],
) -> tuple[PotentialConnection, ...]:
    """Prefer known cross-component opportunities, then balance the remainder."""
    bridging = tuple(
        pair
        for pair in pairs
        if component_ids[pair.first_candidate_index] is not None
        and component_ids[pair.second_candidate_index] is not None
        and component_ids[pair.first_candidate_index] != component_ids[pair.second_candidate_index]
    )
    selected = list(_spatially_balanced_with_limit(bridging, placements, MAX_CONNECTION_PAIRS))
    remaining = tuple(pair for pair in pairs if pair not in set(selected))
    selected.extend(
        _spatially_balanced_with_limit(remaining, placements, MAX_CONNECTION_PAIRS - len(selected))
    )
    return tuple(sorted(selected, key=_pair_key))


def _spatially_balanced_with_limit(
    pairs: tuple[PotentialConnection, ...],
    placements: tuple[BrickPlacement, ...],
    limit: int,
) -> tuple[PotentialConnection, ...]:
    original_limit = MAX_CONNECTION_PAIRS
    if limit >= original_limit:
        return _spatially_balanced_pairs(pairs, placements)
    buckets: dict[tuple[int, int, int], list[PotentialConnection]] = defaultdict(list)
    for pair in pairs:
        buckets[_pair_spatial_bucket(pair, placements)].append(pair)
    for bucket_pairs in buckets.values():
        bucket_pairs.sort(key=_pair_priority)
    selected: list[PotentialConnection] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for bucket in sorted(buckets):
            if depth < len(buckets[bucket]):
                selected.append(buckets[bucket][depth])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        depth += 1
    return tuple(selected)


def _pair_key(pair: PotentialConnection) -> tuple[int, int]:
    return (pair.first_candidate_index, pair.second_candidate_index)


def _pair_priority(pair: PotentialConnection) -> tuple[int, int, int]:
    return (-pair.stud_contact_count, pair.first_candidate_index, pair.second_candidate_index)


def _pair_spatial_bucket(
    pair: PotentialConnection, placements: tuple[BrickPlacement, ...]
) -> tuple[int, int, int]:
    first = placements[pair.first_candidate_index].position
    second = placements[pair.second_candidate_index].position
    return ((first.x + second.x) // 4, (first.y + second.y) // 4, (first.z + second.z) // 6)


def _validated_component_ids(
    component_ids: Collection[int | None] | None, candidate_count: int
) -> tuple[int | None, ...]:
    if component_ids is None:
        return (None,) * candidate_count
    result = tuple(component_ids)
    if len(result) != candidate_count:
        raise ValueError("candidate_baseline_components must match candidate count.")
    return result


def _objective_selection_metrics(
    eligible_pairs: tuple[PotentialConnection, ...],
    modeled_pairs: tuple[PotentialConnection, ...],
    placements: tuple[BrickPlacement, ...],
    strategy: ObjectiveEdgeStrategy,
    component_ids: tuple[int | None, ...],
    frozen: tuple[BrickPlacement, ...],
) -> ObjectiveSelectionMetrics:
    def is_cross_component(pair: PotentialConnection) -> bool:
        first = component_ids[pair.first_candidate_index]
        second = component_ids[pair.second_candidate_index]
        return first is not None and second is not None and first != second

    degrees: dict[int, int] = defaultdict(int)
    heights: dict[int, int] = defaultdict(int)
    buckets: dict[tuple[int, int, int], int] = defaultdict(int)
    for pair in modeled_pairs:
        degrees[pair.first_candidate_index] += 1
        degrees[pair.second_candidate_index] += 1
        heights[_pair_spatial_bucket(pair, placements)[2]] += 1
        buckets[_pair_spatial_bucket(pair, placements)] += 1
    frozen_incident = sum(
        _has_verified_connection(frozen_placement, placement)
        for frozen_placement in frozen
        for placement in placements
    )
    return ObjectiveSelectionMetrics(
        strategy=strategy,
        eligible_pair_count=len(eligible_pairs),
        modeled_pair_count=len(modeled_pairs),
        participating_candidate_count=len(degrees),
        frozen_incident_pair_count=frozen_incident,
        cross_component_pair_count=sum(is_cross_component(pair) for pair in eligible_pairs),
        selected_cross_component_pair_count=sum(is_cross_component(pair) for pair in modeled_pairs),
        height_bucket_counts=tuple(sorted(heights.items())),
        spatial_bucket_counts=tuple(sorted(buckets.items())),
        candidate_degree_counts=tuple(sorted(degrees.items())),
    )


def _improves_connectivity(proposal: BuildabilityAnalysis, baseline: BuildabilityAnalysis) -> bool:
    """Apply the documented final-assembly Gate A graph comparison."""
    return (
        proposal.connected_component_count < baseline.connected_component_count
        or proposal.largest_connected_component_ratio > baseline.largest_connected_component_ratio
    ) and (
        proposal.isolated_placement_count <= baseline.isolated_placement_count
        and proposal.unsupported_placement_count <= baseline.unsupported_placement_count
    )


def _baseline_component_ids(
    candidates: tuple[BrickPlacement, ...], baseline: tuple[BrickPlacement, ...]
) -> tuple[int | None, ...]:
    """Label exact baseline candidates without guessing component membership.

    Candidate placement IDs are deliberately absent when V6 support repair or
    shape-aware substitution produced a placement outside this experimental
    vocabulary.  Such a gap is diagnostic evidence, not a spatial heuristic.
    """
    analysis = analyze_buildability(baseline)
    adjacency: dict[int, set[int]] = {index: set() for index in range(len(baseline))}
    for edge in analysis.edges:
        adjacency[edge.lower_placement_index].add(edge.upper_placement_index)
        adjacency[edge.upper_placement_index].add(edge.lower_placement_index)
    labels: dict[BrickPlacement, int] = {}
    component_id = 0
    assigned: set[int] = set()
    for start in sorted(adjacency):
        if start in assigned:
            continue
        pending = [start]
        members: set[int] = set()
        while pending:
            index = pending.pop()
            if index in members:
                continue
            members.add(index)
            pending.extend(adjacency[index] - members)
        for index in members:
            labels[baseline[index]] = component_id
        assigned.update(members)
        component_id += 1
    return tuple(labels.get(candidate) for candidate in candidates)
