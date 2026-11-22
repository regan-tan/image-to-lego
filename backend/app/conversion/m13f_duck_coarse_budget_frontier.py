"""Exact mandatory-coarse-coverage budget encoding for the offline M13F study."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app.conversion.m12c_wedge_fidelity_experiment import _candidate_coverage_pixels
from app.conversion.m13e_duck_iou_dominance import IoUDominanceModel
from app.conversion.surface_grid_v4 import _Candidate

Pixel = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class CoarseRequirement:
    """One historical projection cell that rectangular candidates must cover."""

    pixel: Pixel
    candidate_ids: tuple[int, ...]
    covered_by_locked_geometry: bool


def historical_coarse_requirements(
    *,
    candidates: Sequence[_Candidate],
    required_pixels: Collection[Pixel],
    fixed_coverage_pixels: Collection[Pixel],
) -> tuple[CoarseRequirement, ...]:
    """Reconstruct the exact unique requirements used by the historical model.

    A requirement is a front (x,z), side (y,z), or top (x,y) projection of a
    required grid cell not already covered by locked geometry.  Its candidate
    incidence is deliberately based on candidate cells, not raster pixels.
    """
    required = frozenset(required_pixels)
    fixed = frozenset(fixed_coverage_pixels)
    duplicate_count = len(tuple(required_pixels)) - len(required)
    if duplicate_count:
        raise ValueError("Historical required-pixel input contains duplicates.")
    requirements: list[CoarseRequirement] = []
    for pixel in sorted(required - fixed):
        ids = tuple(
            index
            for index, candidate in enumerate(candidates)
            if pixel in _candidate_coverage_pixels(candidate)
        )
        if not ids:
            raise ValueError(f"Historical coarse requirement {pixel!r} has no candidate incidence.")
        requirements.append(CoarseRequirement(pixel, ids, False))
    return tuple(requirements)


def count_unmet_coarse_requirements(
    requirements: Sequence[CoarseRequirement], selected_ids: Collection[int]
) -> tuple[CoarseRequirement, ...]:
    """Independently evaluate requirement satisfaction from candidate identities."""
    selected = frozenset(selected_ids)
    return tuple(
        requirement
        for requirement in requirements
        if not requirement.covered_by_locked_geometry
        and not selected.intersection(requirement.candidate_ids)
    )


def add_coarse_violation_budget(
    built: IoUDominanceModel,
    requirements: Sequence[CoarseRequirement],
    budget: int,
) -> tuple[cp_model.IntVar, ...]:
    """Add exact ``violation = 1 iff no incident candidate is selected`` clauses."""
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
        raise ValueError("The coarse-coverage budget must be a non-negative integer.")
    violations: list[cp_model.IntVar] = []
    for index, requirement in enumerate(requirements):
        if requirement.covered_by_locked_geometry:
            continue
        if not requirement.candidate_ids:
            raise ValueError(f"Coarse requirement {requirement.pixel!r} has no candidates.")
        violation = built.model.new_bool_var(f"coarse_violation_{index}")
        selected = [built.selected[candidate_id] for candidate_id in requirement.candidate_ids]
        # At least one selected candidate or a violation, and a selected candidate
        # forces the violation to zero: together these are an exact biconditional.
        built.model.add(sum(selected) + violation >= 1)
        for candidate in selected:
            built.model.add(candidate + violation <= 1)
        violations.append(violation)
    built.model.add(sum(violations) <= budget)
    return tuple(violations)
