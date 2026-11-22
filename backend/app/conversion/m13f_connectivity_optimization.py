"""Exact mechanical connectivity constraints for the opt-in M13F study.

This module is deliberately independent from the production converter.  Its
graph is made only from the calibrated connector matcher used by the existing
buildability validator; touching bounding boxes are never treated as edges.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app.conversion.connectivity_experiment import (
    PairEnumerationMetrics,
    PotentialConnection,
    exhaustive_verified_connection_pairs,
    indexed_verified_connection_pairs,
)
from app.conversion.core import BrickPlacement
from app.conversion.physical_geometry import placements_overlap


@dataclass(frozen=True, slots=True)
class ConnectivityGraph:
    """The complete candidate-plus-locked graph under mechanical semantics."""

    candidate_count: int
    locked_count: int
    edges: tuple[PotentialConnection, ...]
    metrics: PairEnumerationMetrics


@dataclass(frozen=True, slots=True)
class ConnectivityEncoding:
    """Auditable size information for one added single-commodity-flow encoding."""

    root_mode: str
    directed_flow_variable_count: int
    root_selection_variable_count: int
    constraint_count: int


@dataclass(frozen=True, slots=True)
class SeparatorCut:
    """One globally valid cut generated from a disconnected selected component."""

    component_nodes: tuple[int, ...]
    boundary_candidate_indices: tuple[int, ...]
    representative_candidate_index: int | None
    includes_locked_placement: bool

    @property
    def canonical_identifier(self) -> str:
        """Return a stable identifier suitable for checkpoint diagnostics."""
        representative = (
            "locked"
            if self.representative_candidate_index is None
            else str(self.representative_candidate_index)
        )
        return (
            f"component={','.join(map(str, self.component_nodes))};"
            f"boundary={','.join(map(str, self.boundary_candidate_indices))};"
            f"representative={representative}"
        )


@dataclass(frozen=True, slots=True)
class ContactGraphAudit:
    """A bounded independent comparison of indexed and naive graph enumeration."""

    placement_count: int
    indexed_pair_count: int
    exhaustive_pair_count: int
    matches: bool
    required_positive_pair_count: int
    required_positive_pairs_found: int
    required_negative_pair_count: int
    required_negative_pairs_absent: int
    required_overlapping_pair_count: int


def mechanical_connectivity_graph(
    candidates: Collection[BrickPlacement], locked: Collection[BrickPlacement]
) -> ConnectivityGraph:
    """Enumerate every legal contact with the validator's exact connector join."""
    candidate_tuple = tuple(candidates)
    locked_tuple = tuple(locked)
    edges, metrics = indexed_verified_connection_pairs((*candidate_tuple, *locked_tuple))
    return ConnectivityGraph(len(candidate_tuple), len(locked_tuple), edges, metrics)


def audit_contact_graph_subset(
    placements: Collection[BrickPlacement],
    *,
    required_positive_pairs: Collection[tuple[int, int]] = (),
    required_negative_pairs: Collection[tuple[int, int]] = (),
    required_overlapping_pairs: Collection[tuple[int, int]] = (),
) -> ContactGraphAudit:
    """Compare the indexed matcher to the naive exact matcher for a bounded subset."""
    placement_tuple = tuple(placements)
    indexed, _metrics = indexed_verified_connection_pairs(placement_tuple)
    exhaustive = exhaustive_verified_connection_pairs(placement_tuple)
    indexed_pairs = {(pair.first_candidate_index, pair.second_candidate_index) for pair in indexed}
    positive_pairs = {tuple(sorted(pair)) for pair in required_positive_pairs}
    negative_pairs = {tuple(sorted(pair)) for pair in required_negative_pairs}
    overlapping_pairs = {tuple(sorted(pair)) for pair in required_overlapping_pairs}
    if any(
        first == second or first < 0 or second >= len(placement_tuple)
        for first, second in positive_pairs
    ):
        raise ValueError("Required positive audit pairs must name two subset placements.")
    if any(
        first == second or first < 0 or second >= len(placement_tuple)
        for first, second in negative_pairs
    ):
        raise ValueError("Required negative audit pairs must name two subset placements.")
    if any(
        first == second or first < 0 or second >= len(placement_tuple)
        for first, second in overlapping_pairs
    ):
        raise ValueError("Required overlapping audit pairs must name two subset placements.")
    if any(
        not placements_overlap(placement_tuple[first], placement_tuple[second])
        for first, second in overlapping_pairs
    ):
        raise ValueError("Required overlapping audit pairs must physically overlap.")
    return ContactGraphAudit(
        placement_count=len(placement_tuple),
        indexed_pair_count=len(indexed),
        exhaustive_pair_count=len(exhaustive),
        matches=indexed == exhaustive,
        required_positive_pair_count=len(positive_pairs),
        required_positive_pairs_found=len(positive_pairs & indexed_pairs),
        required_negative_pair_count=len(negative_pairs),
        required_negative_pairs_absent=len(negative_pairs - indexed_pairs),
        required_overlapping_pair_count=len(overlapping_pairs),
    )


def add_single_component_constraint(
    model: cp_model.CpModel,
    selected: Sequence[cp_model.IntVar],
    graph: ConnectivityGraph,
) -> ConnectivityEncoding:
    """Require all selected candidates and fixed locked parts to be one component.

    A sparse single commodity flow sends one unit to each selected candidate and
    each non-root locked part.  With locked geometry, its first placement is a
    fixed root.  Without it, exactly one selected candidate becomes the root,
    which preserves feasible connected assemblies regardless of where they sit.
    """
    if len(selected) != graph.candidate_count:
        raise ValueError(
            "Selected variables and connectivity candidates must have matching lengths."
        )
    total_nodes = graph.candidate_count + graph.locked_count
    if total_nodes == 0:
        raise ValueError("Connectivity requires at least one candidate or locked placement.")

    before_constraints = len(model.proto.constraints)
    demand_bound = total_nodes
    incident: dict[int, list[tuple[int, cp_model.IntVar]]] = defaultdict(list)
    directed_flow_count = 0
    for edge_index, edge in enumerate(graph.edges):
        first_to_second = model.new_int_var(0, demand_bound, f"connectivity_flow_{edge_index}_ab")
        second_to_first = model.new_int_var(0, demand_bound, f"connectivity_flow_{edge_index}_ba")
        for flow, endpoint in (
            (first_to_second, edge.first_candidate_index),
            (second_to_first, edge.second_candidate_index),
        ):
            incident[endpoint].append((1, flow))
        incident[edge.first_candidate_index].append((-1, second_to_first))
        incident[edge.second_candidate_index].append((-1, first_to_second))
        for flow in (first_to_second, second_to_first):
            for endpoint in (edge.first_candidate_index, edge.second_candidate_index):
                if endpoint < graph.candidate_count:
                    model.add(flow <= demand_bound * selected[endpoint])
        directed_flow_count += 2

    def balance(node: int) -> cp_model.LinearExpr:
        return cp_model.LinearExpr.Sum([sign * flow for sign, flow in incident[node]])

    if graph.locked_count:
        root = graph.candidate_count
        model.add(balance(root) == total_nodes - 1)
        for candidate_index, variable in enumerate(selected):
            model.add(balance(candidate_index) == -variable)
        for locked_index in range(1, graph.locked_count):
            model.add(balance(graph.candidate_count + locked_index) == -1)
        root_mode = "first-locked-placement"
        root_count = 0
    else:
        roots = tuple(
            model.new_bool_var(f"connectivity_root_{index}") for index in range(total_nodes)
        )
        model.add(sum(roots) == 1)
        root_flows = tuple(
            model.new_int_var(0, demand_bound, f"connectivity_root_flow_{index}")
            for index in range(total_nodes)
        )
        for index, (root_variable, root_flow, variable) in enumerate(
            zip(roots, root_flows, selected, strict=True)
        ):
            model.add(root_variable <= variable)
            model.add(root_flow <= demand_bound * root_variable)
            model.add(balance(index) - root_flow == -variable)
        model.add(sum(root_flows) == sum(selected))
        root_mode = "selected-candidate"
        root_count = len(roots)

    return ConnectivityEncoding(
        root_mode=root_mode,
        directed_flow_variable_count=directed_flow_count,
        root_selection_variable_count=root_count,
        constraint_count=len(model.proto.constraints) - before_constraints,
    )


def add_selectable_root_variables(
    model: cp_model.CpModel, selected: Sequence[cp_model.IntVar], graph: ConnectivityGraph
) -> tuple[cp_model.IntVar, ...]:
    """Choose one selected root when the experiment has no locked placement."""
    if graph.locked_count:
        return ()
    roots = tuple(
        model.new_bool_var(f"connectivity_root_{index}") for index in range(len(selected))
    )
    model.add(sum(roots) == 1)
    for root, variable in zip(roots, selected, strict=True):
        model.add(root <= variable)
    return roots


def selected_graph_components(
    graph: ConnectivityGraph, selected_indices: Collection[int]
) -> tuple[tuple[int, ...], ...]:
    """Return deterministic components under the complete exact contact graph."""
    selected_nodes = set(selected_indices) | set(
        range(graph.candidate_count, graph.candidate_count + graph.locked_count)
    )
    adjacency = {node: set[int]() for node in selected_nodes}
    for edge in graph.edges:
        if edge.first_candidate_index in adjacency and edge.second_candidate_index in adjacency:
            adjacency[edge.first_candidate_index].add(edge.second_candidate_index)
            adjacency[edge.second_candidate_index].add(edge.first_candidate_index)
    components: list[tuple[int, ...]] = []
    while adjacency:
        start = min(adjacency)
        component: list[int] = []
        pending = [start]
        while pending:
            node = pending.pop()
            if node not in adjacency:
                continue
            component.append(node)
            pending.extend(adjacency.pop(node))
        components.append(tuple(sorted(component)))
    return tuple(components)


def separator_cut(graph: ConnectivityGraph, component: Collection[int]) -> SeparatorCut:
    """Construct the complete optional boundary of one selected component."""
    nodes = frozenset(component)
    if not nodes:
        raise ValueError("A separator cut requires at least one component node.")
    boundary: set[int] = set()
    for edge in graph.edges:
        first_inside = edge.first_candidate_index in nodes
        second_inside = edge.second_candidate_index in nodes
        if first_inside == second_inside:
            continue
        outside = edge.second_candidate_index if first_inside else edge.first_candidate_index
        if outside < graph.candidate_count:
            boundary.add(outside)
        else:
            raise ValueError("A component boundary cannot contain a selected locked placement.")
    candidates = sorted(node for node in nodes if node < graph.candidate_count)
    return SeparatorCut(
        component_nodes=tuple(sorted(nodes)),
        boundary_candidate_indices=tuple(sorted(boundary)),
        representative_candidate_index=candidates[0] if candidates else None,
        includes_locked_placement=any(node >= graph.candidate_count for node in nodes),
    )


def separator_cuts(
    graph: ConnectivityGraph, component: Collection[int]
) -> tuple[SeparatorCut, ...]:
    """Return one valid boundary cut for every selected optional node in ``component``.

    Every cut has the same complete exact boundary but a different right-hand
    selected node.  A connected assembly containing that node must cross the
    boundary on a path to the fixed root, so none of these cuts excludes a
    connected assembly.  Keeping all of them makes a separator materially
    stronger than choosing its lowest-index representative alone.
    """
    base = separator_cut(graph, component)
    representatives = tuple(node for node in base.component_nodes if node < graph.candidate_count)
    if not representatives:
        return (base,)
    return tuple(
        SeparatorCut(
            component_nodes=base.component_nodes,
            boundary_candidate_indices=base.boundary_candidate_indices,
            representative_candidate_index=representative,
            includes_locked_placement=base.includes_locked_placement,
        )
        for representative in representatives
    )


def add_separator_cut(
    model: cp_model.CpModel,
    selected: Sequence[cp_model.IntVar],
    cut: SeparatorCut,
    *,
    fixed_root_node: int | None,
    selectable_roots: Sequence[cp_model.IntVar] = (),
) -> None:
    """Add a valid connectivity cut without materialising per-edge flow variables.

    If a selected component does not contain the fixed root, every connected
    assembly containing its representative must select a vertex in its complete
    outside boundary.  With a selectable root, the component may instead be the
    root component, represented by a selected root variable inside it.
    """
    component = set(cut.component_nodes)
    if fixed_root_node is not None and fixed_root_node in component:
        raise ValueError("A fixed-root component does not require a separator cut.")
    boundary = sum(selected[index] for index in cut.boundary_candidate_indices)
    if cut.representative_candidate_index is None:
        if fixed_root_node is None:
            raise ValueError("A rootless component needs a selected representative.")
        model.add(boundary >= 1)
        return
    representative = selected[cut.representative_candidate_index]
    if fixed_root_node is not None:
        model.add(boundary >= representative)
        return
    roots_inside = sum(root for index, root in enumerate(selectable_roots) if index in component)
    model.add(boundary + roots_inside >= representative)


def add_exact_mask_constraints(
    model: cp_model.CpModel,
    selected: Sequence[cp_model.IntVar],
    candidate_rasters: Sequence[Collection[tuple[str, int, int]]],
    locked_pixels: Collection[tuple[str, int, int]],
    target_pixels: Collection[tuple[str, int, int]],
) -> int:
    """Pin candidate-union masks, grouping pixels with identical OR inputs.

    Locked pixels are already unconditional.  Candidate-touchable pixels are
    grouped by their exact candidate incidence signature, so duplicate raster
    pixels create one equality rather than one variable per pixel.
    """
    if len(selected) != len(candidate_rasters):
        raise ValueError("Selected variables and candidate rasters must have matching lengths.")
    locked = frozenset(locked_pixels)
    target = frozenset(target_pixels)
    incidence: dict[tuple[int, ...], set[tuple[str, int, int]]] = defaultdict(set)
    by_pixel: dict[tuple[str, int, int], set[int]] = defaultdict(set)
    for index, raster in enumerate(candidate_rasters):
        for pixel in raster:
            if pixel not in locked:
                by_pixel[pixel].add(index)
    if any(pixel not in target for pixel in locked):
        raise ValueError("Exact target mask omits an unconditional locked pixel.")
    for pixel, indices in by_pixel.items():
        incidence[tuple(sorted(indices))].add(pixel)
    constraint_count = 0
    for signature, pixels in sorted(incidence.items()):
        desired = {pixel in target for pixel in pixels}
        if len(desired) != 1:
            raise ValueError("Exact target mask splits an inseparable raster incidence group.")
        covered = model.new_bool_var(f"exact_mask_covered_{constraint_count}")
        model.add_max_equality(covered, [selected[index] for index in signature])
        model.add(covered == int(desired.pop()))
        constraint_count += 2
    uncovered_targets = target - locked - frozenset(by_pixel)
    if uncovered_targets:
        raise ValueError(
            "Exact target mask contains pixels unreachable by locked or candidate geometry."
        )
    return constraint_count


def selected_graph_component_count(
    graph: ConnectivityGraph, selected_indices: Collection[int]
) -> int:
    """Count components in a chosen graph; used as a solver-independent check."""
    return len(selected_graph_components(graph, selected_indices))
