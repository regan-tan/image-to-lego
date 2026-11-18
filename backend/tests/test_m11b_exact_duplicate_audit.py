from dataclasses import replace

from app.conversion import core
from app.conversion.physical_scale_experiment import _audit_candidate_duplicates
from app.conversion.surface_grid_v4 import _Candidate


def _part(part_id: str, *, family: str = "plate") -> core.BrickType:
    base = next(part for part in core.BRICK_CATALOGUE if part.part_id == "3024")
    return replace(base, part_id=part_id, family=family)


def _candidate(
    part: core.BrickType, position: core.GridPosition, cells: frozenset[core.GridPosition]
) -> _Candidate:
    return _Candidate(core.BrickPlacement(part, position, 0), cells)


def _counts(
    *candidates: _Candidate, locked: tuple[core.BrickPlacement, ...] = ()
) -> tuple[int, ...]:
    target = frozenset(cell for candidate in candidates for cell in candidate.cells)
    return _audit_candidate_duplicates(tuple(candidates), target, locked)


def test_identical_synthetic_candidates_are_the_only_fully_removable_pair() -> None:
    cells = frozenset({core.GridPosition(0, 0, 0)})
    candidate = _candidate(_part("synthetic-a"), core.GridPosition(0, 0, 0), cells)

    counts = _counts(candidate, candidate)

    assert counts[0] == 2
    assert counts[2] == counts[4] == counts[6] == counts[8] == 1


def test_same_body_with_different_connector_contract_is_not_mechanically_equivalent() -> None:
    cells = frozenset({core.GridPosition(0, 0, 0)})
    rectangular = _candidate(_part("rectangular"), core.GridPosition(0, 0, 0), cells)
    unevaluated = _candidate(
        _part("unevaluated", family="slope_33"), core.GridPosition(0, 0, 0), cells
    )

    counts = _counts(rectangular, unevaluated)

    assert counts[2] == 1  # Same three-view silhouette.
    assert counts[4] == 1  # Same occupied physical microcells.
    assert counts[6] == 0
    assert counts[8] == 0


def test_same_silhouette_with_different_physical_body_is_not_removable() -> None:
    cells = frozenset({core.GridPosition(0, 0, 0)})
    plate = _candidate(_part("plate"), core.GridPosition(0, 0, 0), cells)
    brick = _candidate(
        replace(_part("brick"), family="brick", height_plates=3),
        core.GridPosition(0, 0, 0),
        cells,
    )

    counts = _counts(plate, brick)

    assert counts[2] == 1
    assert counts[4] == counts[6] == counts[8] == 0


def test_different_support_or_collision_context_never_becomes_fully_removable() -> None:
    part = _part("support-test")
    base_cells = frozenset({core.GridPosition(0, 0, 0)})
    raised_cells = frozenset({core.GridPosition(0, 0, 1)})
    base = _candidate(part, core.GridPosition(0, 0, 0), base_cells)
    raised = _candidate(part, core.GridPosition(0, 0, 1), raised_cells)
    locked = core.BrickPlacement(_part("locked"), core.GridPosition(0, 0, 0), 0)

    counts = _counts(base, raised, locked=(locked,))

    assert counts[8] == 0


def test_different_mandatory_coverage_contribution_is_not_removable() -> None:
    part = _part("coverage-test")
    first = _candidate(part, core.GridPosition(0, 0, 0), frozenset({core.GridPosition(0, 0, 0)}))
    second = _candidate(part, core.GridPosition(1, 0, 0), frozenset({core.GridPosition(1, 0, 0)}))

    counts = _counts(first, second)

    assert counts[8] == 0


def test_part_identity_preserves_distinct_export_representation() -> None:
    cells = frozenset({core.GridPosition(0, 0, 0)})
    first = _candidate(_part("export-a"), core.GridPosition(0, 0, 0), cells)
    second = _candidate(_part("export-b"), core.GridPosition(0, 0, 0), cells)

    counts = _counts(first, second)

    assert counts[4] == 1
    assert counts[8] == 0
