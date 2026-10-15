"""Deterministic stud-connectivity diagnostics for completed LEGO placements."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Literal

from app.conversion.core import BrickPlacement

BUILDABILITY_ANALYSIS_VERSION = "stud-connectivity-v1"
VERTICAL_INSERTION_ACCESSIBILITY_VERSION = "vertical-insertion-v1"
INSTRUCTION_PRECEDENCE_ANALYSIS_VERSION = "insertion-aware-instructions-v1"
MAX_PLACEMENTS_PER_INSTRUCTION_STEP = 6
_SUPPORTED_FAMILIES = frozenset({"brick", "plate"})


@dataclass(frozen=True, slots=True)
class ConnectionEdge:
    """A vertical stud connection from a lower placement to an upper placement."""

    lower_placement_index: int
    upper_placement_index: int
    stud_count: int


@dataclass(frozen=True, slots=True)
class BuildabilityAnalysis:
    """Aggregate stud-connectivity diagnostics for one completed LEGO model."""

    edges: tuple[ConnectionEdge, ...]
    evaluated_placement_count: int
    unevaluated_placement_count: int
    connected_component_count: int
    largest_connected_component_size: int
    largest_connected_component_ratio: float
    isolated_placement_count: int
    unsupported_placement_count: int


@dataclass(frozen=True, slots=True)
class InstructionStep:
    """One deterministic guide step referencing canonical placement indexes."""

    step_number: int
    placement_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BlockedInsertion:
    """One rectangular placement blocked during its straight-down insertion."""

    placement_index: int
    blocker_placement_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class VerticalInsertionAccessibility:
    """Step-start straight-down insertion diagnostics for a completed model."""

    evaluated_placement_count: int
    unevaluated_placement_count: int
    accessible_placement_count: int
    blocked_placement_count: int
    blocked_insertions: tuple[BlockedInsertion, ...]


@dataclass(frozen=True, slots=True)
class PrecedenceEdge:
    """One hard ordering rule between placements."""

    predecessor_placement_index: int
    successor_placement_index: int
    edge_type: Literal["structural", "insertion"]


@dataclass(frozen=True, slots=True)
class InstructionPrecedenceAnalysis:
    """Combined support and vertical-insertion ordering diagnostics."""

    structural_edges: tuple[PrecedenceEdge, ...]
    insertion_edges: tuple[PrecedenceEdge, ...]
    cyclic_components: tuple[tuple[int, ...], ...]
    cyclic_placement_indices: tuple[int, ...]
    cyclic_structural_edge_count: int
    cyclic_insertion_edge_count: int
    schedulable_evaluated_placement_count: int
    unresolved_vertical_insertion_placement_indices: tuple[int, ...]

    @property
    def total_precedence_edge_count(self) -> int:
        return len(
            {
                (edge.predecessor_placement_index, edge.successor_placement_index)
                for edge in (*self.structural_edges, *self.insertion_edges)
            }
        )


class BuildInstructionOrderingError(ValueError):
    """The stud-connectivity graph cannot provide a valid instruction order."""


class InstructionStepValidationError(ValueError):
    """Instruction steps do not cover a model in a mechanically valid order."""


def analyze_buildability(placements: Collection[BrickPlacement]) -> BuildabilityAnalysis:
    """Analyze supported brick and plate placements without changing the conversion output.

    A supported placement is unsupported when its bottom is above the model's minimum
    placement z plane and no evaluated rectangular placement connects directly below it.
    """
    placement_list = tuple(placements)
    evaluated = tuple(
        (index, placement)
        for index, placement in enumerate(placement_list)
        if _is_connector_supported(placement)
    )
    edges = _connection_edges(evaluated)
    evaluated_indices = {index for index, _ in evaluated}
    adjacency = {index: set[int]() for index in evaluated_indices}
    connected_from_below: set[int] = set()
    for edge in edges:
        adjacency[edge.lower_placement_index].add(edge.upper_placement_index)
        adjacency[edge.upper_placement_index].add(edge.lower_placement_index)
        connected_from_below.add(edge.upper_placement_index)

    component_sizes = _component_sizes(adjacency)
    evaluated_count = len(evaluated)
    largest_component_size = max(component_sizes, default=0)
    base_z = min((placement.position.z for placement in placement_list), default=0)
    unsupported_count = sum(
        placement.position.z != base_z and index not in connected_from_below
        for index, placement in evaluated
    )

    return BuildabilityAnalysis(
        edges=edges,
        evaluated_placement_count=evaluated_count,
        unevaluated_placement_count=len(placement_list) - evaluated_count,
        connected_component_count=len(component_sizes),
        largest_connected_component_size=largest_component_size,
        largest_connected_component_ratio=(largest_component_size / evaluated_count)
        if evaluated_count
        else 0.0,
        isolated_placement_count=sum(not neighbors for neighbors in adjacency.values()),
        unsupported_placement_count=unsupported_count,
    )


def analyze_instruction_precedence(
    placements: Collection[BrickPlacement],
) -> InstructionPrecedenceAnalysis:
    """Build deterministic support and straight-down insertion precedence edges.

    An insertion edge ``A -> B`` means B's final rectangular fit geometry would
    block A's straight-down insertion if B were already installed. Slopes remain
    unevaluated and never contribute insertion edges.
    """
    placement_list = tuple(placements)
    buildability = analyze_buildability(placement_list)
    structural_edges = tuple(
        PrecedenceEdge(
            edge.lower_placement_index,
            edge.upper_placement_index,
            "structural",
        )
        for edge in buildability.edges
    )
    insertion_edges = _insertion_precedence_edges(placement_list)
    cyclic_components = _cyclic_components(
        len(placement_list), (*structural_edges, *insertion_edges)
    )
    cyclic_placement_indices = tuple(
        index for component in cyclic_components for index in component
    )
    cyclic_component_by_index = {
        index: component_id
        for component_id, component in enumerate(cyclic_components)
        for index in component
    }
    cyclic_structural_edge_count = sum(
        cyclic_component_by_index.get(edge.predecessor_placement_index)
        == cyclic_component_by_index.get(edge.successor_placement_index)
        and edge.predecessor_placement_index in cyclic_component_by_index
        for edge in structural_edges
    )
    cyclic_insertion_edge_count = sum(
        cyclic_component_by_index.get(edge.predecessor_placement_index)
        == cyclic_component_by_index.get(edge.successor_placement_index)
        and edge.predecessor_placement_index in cyclic_component_by_index
        for edge in insertion_edges
    )
    evaluated_placement_count = sum(
        _is_connector_supported(placement) for placement in placement_list
    )

    return InstructionPrecedenceAnalysis(
        structural_edges=structural_edges,
        insertion_edges=insertion_edges,
        cyclic_components=cyclic_components,
        cyclic_placement_indices=cyclic_placement_indices,
        cyclic_structural_edge_count=cyclic_structural_edge_count,
        cyclic_insertion_edge_count=cyclic_insertion_edge_count,
        schedulable_evaluated_placement_count=evaluated_placement_count
        - len(cyclic_placement_indices),
        unresolved_vertical_insertion_placement_indices=cyclic_placement_indices,
    )


def analyze_vertical_insertion_accessibility(
    placements: Collection[BrickPlacement],
    instruction_steps: Sequence[InstructionStep],
) -> VerticalInsertionAccessibility:
    """Check rectangular placements against geometry built before each guide step.

    ``vertical-insertion-v1`` only proves that a brick or plate can translate
    straight down into its final pose without crossing previously placed
    rectangular fit geometry. Pieces in the same step are deliberately not
    blockers because the guide does not define an internal insertion order.
    Slopes are unevaluated and are not given invented bounding-box mechanics.
    """
    placement_list = tuple(placements)
    validate_instruction_steps(placement_list, instruction_steps)

    built_indices: list[int] = []
    blocked_insertions: list[BlockedInsertion] = []
    evaluated_count = 0
    accessible_count = 0

    for step in instruction_steps:
        for placement_index in step.placement_indices:
            placement = placement_list[placement_index]
            if not _is_connector_supported(placement):
                continue

            evaluated_count += 1
            target_top_z = placement.position.z + placement.brick_type.height_plates
            target_footprint = _stud_footprint(placement)
            blocker_indices: list[int] = []
            for built_index in built_indices:
                built = placement_list[built_index]
                if not _is_connector_supported(built):
                    continue
                if built.position.z + built.brick_type.height_plates <= target_top_z:
                    continue
                if target_footprint & _stud_footprint(built):
                    blocker_indices.append(built_index)

            blockers = tuple(sorted(blocker_indices))
            if blockers:
                blocked_insertions.append(BlockedInsertion(placement_index, blockers))
            else:
                accessible_count += 1

        built_indices.extend(step.placement_indices)

    return VerticalInsertionAccessibility(
        evaluated_placement_count=evaluated_count,
        unevaluated_placement_count=len(placement_list) - evaluated_count,
        accessible_placement_count=accessible_count,
        blocked_placement_count=len(blocked_insertions),
        blocked_insertions=tuple(blocked_insertions),
    )


def order_placements_for_instructions(
    placements: Collection[BrickPlacement],
) -> tuple[BrickPlacement, ...]:
    """Return a deterministic precedence-aware placement order.

    This reuses ``stud-connectivity-v1`` edges for rectangular bricks and plates.
    It does not verify insertion accessibility, collision-free assembly, or partial-build stability.
    Unevaluated placements, including slopes, have no invented mechanical edge. They are
    positioned by the same coordinate-based presentation order after every evaluated
    placement below their base z level; this is not a verified mechanical dependency.
    """
    placement_list = tuple(placements)
    precedence = analyze_instruction_precedence(placement_list)
    return tuple(
        placement_list[index]
        for index in _ordered_placement_indices(placement_list, precedence)
    )


def generate_instruction_steps(
    placements: Collection[BrickPlacement],
) -> tuple[InstructionStep, ...]:
    """Batch the canonical order into deterministic, support-safe local guide steps.

    A direct ``stud-connectivity-v1`` support edge always crosses a step boundary.
    Unevaluated placements, including slopes, retain presentation ordering only: they do
    not gain inferred mechanical dependencies. Evaluated regions are local branches of
    the connectivity graph and are used only to keep the presentation near the active
    part of the model.
    """
    placement_list = tuple(placements)
    analysis = analyze_buildability(placement_list)
    precedence = analyze_instruction_precedence(placement_list)
    canonical_indices = _ordered_placement_indices(placement_list, precedence)
    canonical_rank = {index: rank for rank, index in enumerate(canonical_indices)}
    prerequisites = _prerequisites_by_placement(
        placement_list,
        _schedulable_precedence_edges(precedence),
    )
    structural_prerequisites = _prerequisites_by_placement(
        placement_list,
        precedence.structural_edges,
    )
    component_ids = _component_ids_by_placement(placement_list, analysis.edges)
    region_ids = _subassembly_region_ids_by_placement(
        placement_list,
        structural_prerequisites,
        component_ids,
        canonical_rank,
    )
    evaluated_indices = {
        index
        for index, placement in enumerate(placement_list)
        if _is_connector_supported(placement)
    }
    evaluated_before = {
        index: frozenset(
            earlier_index
            for earlier_index in canonical_indices[: canonical_rank[index]]
            if earlier_index in evaluated_indices
        )
        for index in range(len(placement_list))
        if index not in evaluated_indices
    }

    assigned: set[int] = set()
    steps: list[InstructionStep] = []
    active_region: int | None = None
    active_component: int | None = None
    while len(assigned) < len(placement_list):
        eligible = [
            index
            for index in canonical_indices
            if index not in assigned
            and prerequisites[index].issubset(assigned)
            and (index in evaluated_indices or evaluated_before[index].issubset(assigned))
        ]
        if not eligible:
            raise BuildInstructionOrderingError(
                "No placement is eligible for the next instruction step."
            )

        first_index = _first_step_placement(
            eligible,
            active_region=active_region,
            active_component=active_component,
            region_ids=region_ids,
            component_ids=component_ids,
            canonical_rank=canonical_rank,
        )
        selected = [first_index]
        eligible.remove(first_index)
        active_region = region_ids.get(first_index)
        active_component = component_ids.get(first_index)
        while eligible and len(selected) < MAX_PLACEMENTS_PER_INSTRUCTION_STEP:
            next_index = min(
                eligible,
                key=lambda index: _step_candidate_key(
                    index=index,
                    selected_indices=selected,
                    placement_list=placement_list,
                    region_ids=region_ids,
                    component_ids=component_ids,
                    active_region=active_region,
                    active_component=active_component,
                    canonical_rank=canonical_rank,
                ),
            )
            selected.append(next_index)
            eligible.remove(next_index)

        assigned.update(selected)
        steps.append(InstructionStep(len(steps) + 1, tuple(selected)))

    instruction_steps = tuple(steps)
    validate_instruction_steps(placement_list, instruction_steps)
    _validate_schedulable_precedence_steps(placement_list, instruction_steps, precedence)
    return instruction_steps


def validate_instruction_steps(
    placements: Collection[BrickPlacement],
    instruction_steps: Sequence[InstructionStep],
) -> None:
    """Reject incomplete, duplicated, oversized, or mechanically invalid guide steps."""
    placement_list = tuple(placements)
    step_by_placement: dict[int, int] = {}
    for expected_step_number, step in enumerate(instruction_steps, start=1):
        if step.step_number != expected_step_number:
            raise InstructionStepValidationError("Instruction step numbers must be contiguous.")
        if len(step.placement_indices) > MAX_PLACEMENTS_PER_INSTRUCTION_STEP:
            raise InstructionStepValidationError("An instruction step exceeds the placement limit.")
        for placement_index in step.placement_indices:
            if placement_index < 0 or placement_index >= len(placement_list):
                raise InstructionStepValidationError(
                    "An instruction step references an unknown placement."
                )
            if placement_index in step_by_placement:
                raise InstructionStepValidationError(
                    "A placement appears in more than one instruction step."
                )
            step_by_placement[placement_index] = step.step_number

    missing_indices = set(range(len(placement_list))) - set(step_by_placement)
    if missing_indices:
        raise InstructionStepValidationError(
            "An instruction step is missing one or more placements."
        )

    for edge in analyze_buildability(placement_list).edges:
        lower_step = step_by_placement[edge.lower_placement_index]
        upper_step = step_by_placement[edge.upper_placement_index]
        if lower_step >= upper_step:
            raise InstructionStepValidationError(
                "A stud-connectivity support must appear in an earlier instruction step."
            )


def _validate_schedulable_precedence_steps(
    placements: tuple[BrickPlacement, ...],
    instruction_steps: Sequence[InstructionStep],
    precedence: InstructionPrecedenceAnalysis,
) -> None:
    step_by_placement = {
        placement_index: step.step_number
        for step in instruction_steps
        for placement_index in step.placement_indices
    }
    for edge in _schedulable_precedence_edges(precedence):
        predecessor_step = step_by_placement[edge.predecessor_placement_index]
        successor_step = step_by_placement[edge.successor_placement_index]
        if predecessor_step >= successor_step:
            raise BuildInstructionOrderingError(
                "A schedulable precedence requirement did not cross a step boundary."
            )


def _ordered_placement_indices(
    placements: tuple[BrickPlacement, ...],
    precedence: InstructionPrecedenceAnalysis,
) -> tuple[int, ...]:
    outgoing: list[list[int]] = [[] for _ in placements]
    incoming_counts = [0 for _ in placements]

    for edge in _schedulable_precedence_edges(precedence):
        predecessor = placements[edge.predecessor_placement_index]
        successor = placements[edge.successor_placement_index]
        if edge.edge_type == "structural" and predecessor.position.z >= successor.position.z:
            raise BuildInstructionOrderingError(
                "stud-connectivity-v1 produced a non-upward support dependency."
            )
        outgoing[edge.predecessor_placement_index].append(edge.successor_placement_index)
        incoming_counts[edge.successor_placement_index] += 1

    ready: list[tuple[tuple[int, int, int, int, int, str, int, int], int]] = []
    for index, incoming_count in enumerate(incoming_counts):
        if incoming_count == 0:
            heappush(ready, (_instruction_order_key(placements[index], index), index))

    ordered_indices: list[int] = []
    while ready:
        _, index = heappop(ready)
        ordered_indices.append(index)
        for dependent_index in outgoing[index]:
            incoming_counts[dependent_index] -= 1
            if incoming_counts[dependent_index] == 0:
                dependent = placements[dependent_index]
                heappush(
                    ready,
                    (_instruction_order_key(dependent, dependent_index), dependent_index),
                )

    if len(ordered_indices) != len(placements):
        raise BuildInstructionOrderingError(
            "Instruction precedence scheduling unexpectedly retained a cycle."
        )
    return tuple(ordered_indices)


def _prerequisites_by_placement(
    placements: tuple[BrickPlacement, ...],
    edges: Sequence[PrecedenceEdge],
) -> tuple[frozenset[int], ...]:
    prerequisites = [set[int]() for _ in placements]
    for edge in edges:
        prerequisites[edge.successor_placement_index].add(edge.predecessor_placement_index)
    return tuple(frozenset(indices) for indices in prerequisites)


def _component_ids_by_placement(
    placements: tuple[BrickPlacement, ...],
    edges: Sequence[ConnectionEdge],
) -> dict[int, int]:
    evaluated_indices = {
        index for index, placement in enumerate(placements) if _is_connector_supported(placement)
    }
    adjacency = {index: set[int]() for index in evaluated_indices}
    for edge in edges:
        adjacency[edge.lower_placement_index].add(edge.upper_placement_index)
        adjacency[edge.upper_placement_index].add(edge.lower_placement_index)

    component_ids: dict[int, int] = {}
    for component_id, start_index in enumerate(sorted(adjacency)):
        if start_index in component_ids:
            continue
        pending = [start_index]
        while pending:
            index = pending.pop()
            if index in component_ids:
                continue
            component_ids[index] = component_id
            pending.extend(sorted(adjacency[index], reverse=True))
    return component_ids


def _subassembly_region_ids_by_placement(
    placements: tuple[BrickPlacement, ...],
    prerequisites: Sequence[frozenset[int]],
    component_ids: dict[int, int],
    canonical_rank: dict[int, int],
) -> dict[int, int]:
    """Assign local presentation regions without adding mechanical graph edges.

    Each evaluated component is split at direct support forks. A branch inherits its
    supporter's region until a placement has multiple direct dependents, when each
    dependent starts its own local region. Unevaluated placements are attached to the
    nearest evaluated region only for presentation.
    """
    dependents = [set[int]() for _ in placements]
    for index, placement_prerequisites in enumerate(prerequisites):
        for prerequisite in placement_prerequisites:
            dependents[prerequisite].add(index)

    region_ids: dict[int, int] = {}
    next_region_id = 0
    for index in sorted(component_ids, key=canonical_rank.__getitem__):
        placement_prerequisites = prerequisites[index]
        if not placement_prerequisites:
            region_ids[index] = next_region_id
            next_region_id += 1
            continue

        primary_support = min(
            placement_prerequisites,
            key=lambda support_index: (
                _placement_distance(placements[index], placements[support_index]),
                canonical_rank[support_index],
            ),
        )
        if len(dependents[primary_support]) > 1 and dependents[index]:
            region_ids[index] = next_region_id
            next_region_id += 1
        else:
            region_ids[index] = region_ids[primary_support]

    evaluated_indices = tuple(sorted(component_ids, key=canonical_rank.__getitem__))
    for index in range(len(placements)):
        if index in region_ids or not evaluated_indices:
            continue
        nearest_evaluated = min(
            evaluated_indices,
            key=lambda evaluated_index: (
                _placement_distance(placements[index], placements[evaluated_index]),
                canonical_rank[evaluated_index],
            ),
        )
        region_ids[index] = region_ids[nearest_evaluated]
        component_ids[index] = component_ids[nearest_evaluated]
    return region_ids


def _first_step_placement(
    eligible: Sequence[int],
    *,
    active_region: int | None,
    active_component: int | None,
    region_ids: dict[int, int],
    component_ids: dict[int, int],
    canonical_rank: dict[int, int],
) -> int:
    """Choose a step anchor, keeping the previous local region when possible."""
    return min(
        eligible,
        key=lambda index: (
            0 if active_region is not None and region_ids.get(index) == active_region else 1,
            0
            if active_component is not None and component_ids.get(index) == active_component
            else 1,
            canonical_rank[index],
        ),
    )


def _step_candidate_key(
    *,
    index: int,
    selected_indices: Sequence[int],
    placement_list: tuple[BrickPlacement, ...],
    region_ids: dict[int, int],
    component_ids: dict[int, int],
    active_region: int | None,
    active_component: int | None,
    canonical_rank: dict[int, int],
) -> tuple[int, int, int, int]:
    same_region = active_region is not None and region_ids.get(index) == active_region
    same_component = active_component is not None and component_ids.get(index) == active_component
    distance = min(
        _placement_distance(placement_list[index], placement_list[selected_index])
        for selected_index in selected_indices
    )
    return (
        0 if same_region else 1,
        0 if same_component else 1,
        distance,
        canonical_rank[index],
    )


def _placement_distance(left: BrickPlacement, right: BrickPlacement) -> int:
    return (
        abs(left.position.x - right.position.x)
        + abs(left.position.y - right.position.y)
        + abs(left.position.z - right.position.z)
    )


def _is_connector_supported(placement: BrickPlacement) -> bool:
    return (
        placement.brick_type.shape == "rectangular"
        and placement.brick_type.family in _SUPPORTED_FAMILIES
    )


def _instruction_order_key(
    placement: BrickPlacement,
    original_index: int,
) -> tuple[int, int, int, int, int, str, int, int]:
    fitter_order = placement.brick_type.fitter_order
    return (
        placement.position.z,
        placement.position.y,
        placement.position.x,
        fitter_order is None,
        fitter_order if fitter_order is not None else 0,
        placement.brick_type.part_id,
        placement.orientation_degrees,
        original_index,
    )


def _connection_edges(
    evaluated: tuple[tuple[int, BrickPlacement], ...],
) -> tuple[ConnectionEdge, ...]:
    placements_by_bottom_z: dict[int, list[tuple[int, BrickPlacement]]] = defaultdict(list)
    for index, placement in evaluated:
        placements_by_bottom_z[placement.position.z].append((index, placement))

    edges: list[ConnectionEdge] = []
    for lower_index, lower in evaluated:
        upper_z = lower.position.z + lower.brick_type.height_plates
        lower_footprint = _stud_footprint(lower)
        for upper_index, upper in placements_by_bottom_z[upper_z]:
            overlap = lower_footprint & _stud_footprint(upper)
            if overlap:
                edges.append(ConnectionEdge(lower_index, upper_index, len(overlap)))
    return tuple(edges)


def _insertion_precedence_edges(
    placements: tuple[BrickPlacement, ...],
) -> tuple[PrecedenceEdge, ...]:
    edges: list[PrecedenceEdge] = []
    for target_index, target in enumerate(placements):
        if not _is_connector_supported(target):
            continue
        target_top_z = target.position.z + target.brick_type.height_plates
        target_footprint = _stud_footprint(target)
        for blocker_index, blocker in enumerate(placements):
            if target_index == blocker_index or not _is_connector_supported(blocker):
                continue
            if blocker.position.z + blocker.brick_type.height_plates <= target_top_z:
                continue
            if target_footprint & _stud_footprint(blocker):
                edges.append(PrecedenceEdge(target_index, blocker_index, "insertion"))
    return tuple(edges)


def _cyclic_components(
    placement_count: int,
    edges: Sequence[PrecedenceEdge],
) -> tuple[tuple[int, ...], ...]:
    adjacency = [set[int]() for _ in range(placement_count)]
    reverse_adjacency = [set[int]() for _ in range(placement_count)]
    for edge in edges:
        adjacency[edge.predecessor_placement_index].add(edge.successor_placement_index)
        reverse_adjacency[edge.successor_placement_index].add(edge.predecessor_placement_index)

    finish_order: list[int] = []
    visited: set[int] = set()
    for start_index in range(placement_count):
        if start_index in visited:
            continue
        pending: list[tuple[int, bool]] = [(start_index, False)]
        while pending:
            index, exiting = pending.pop()
            if exiting:
                finish_order.append(index)
                continue
            if index in visited:
                continue
            visited.add(index)
            pending.append((index, True))
            pending.extend((neighbor, False) for neighbor in sorted(adjacency[index], reverse=True))

    components: list[tuple[int, ...]] = []
    assigned: set[int] = set()
    for start_index in reversed(finish_order):
        if start_index in assigned:
            continue
        component: list[int] = []
        reverse_pending = [start_index]
        while reverse_pending:
            index = reverse_pending.pop()
            if index in assigned:
                continue
            assigned.add(index)
            component.append(index)
            reverse_pending.extend(sorted(reverse_adjacency[index], reverse=True))
        if len(component) > 1:
            components.append(tuple(sorted(component)))
    return tuple(sorted(components, key=lambda component: component[0]))


def _schedulable_precedence_edges(
    precedence: InstructionPrecedenceAnalysis,
) -> tuple[PrecedenceEdge, ...]:
    """Keep structural edges and only relax insertion edges inside an SCC.

    A cyclic region cannot satisfy every straight-down constraint. Retaining its
    pre-existing structural order keeps the canonical model complete without
    claiming the affected placements are vertically accessible.
    """
    cyclic_component_by_index = {
        index: component_id
        for component_id, component in enumerate(precedence.cyclic_components)
        for index in component
    }
    return tuple(
        edge
        for edge in (*precedence.structural_edges, *precedence.insertion_edges)
        if not (
            edge.edge_type == "insertion"
            and cyclic_component_by_index.get(edge.predecessor_placement_index)
            == cyclic_component_by_index.get(edge.successor_placement_index)
            and edge.predecessor_placement_index in cyclic_component_by_index
        )
    )


def _stud_footprint(placement: BrickPlacement) -> frozenset[tuple[int, int]]:
    length = placement.brick_type.length_studs
    width = placement.brick_type.width_studs
    if placement.orientation_degrees in (90, 270):
        length, width = width, length
    return frozenset(
        (placement.position.x + x, placement.position.y + y)
        for y in range(width)
        for x in range(length)
    )


def _component_sizes(adjacency: dict[int, set[int]]) -> tuple[int, ...]:
    remaining = set(adjacency)
    sizes: list[int] = []
    while remaining:
        current = remaining.pop()
        size = 0
        pending = [current]
        while pending:
            index = pending.pop()
            size += 1
            for neighbor in adjacency[index]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        sizes.append(size)
    return tuple(sizes)
