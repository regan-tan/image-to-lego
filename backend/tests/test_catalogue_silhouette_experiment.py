from __future__ import annotations

from app.conversion import core
from app.conversion.catalogue_silhouette_experiment import (
    _raster_pixels,
    optimise_catalogue_silhouette,
)
from app.conversion.fidelity import render_silhouette_masks
from app.conversion.surface_grid_v4 import _enumerate_candidates


def test_catalogue_objective_selects_the_known_better_union_without_double_counting() -> None:
    """One part must cover the left source square rather than an equal right square."""
    result = optimise_catalogue_silhouette(
        source_vertices=(
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 1.0),
            (1.0, 1.0, 1.0),
            (0.0, 1.0, 1.0),
        ),
        faces=(
            (0, 1, 2),
            (0, 2, 3),
            (4, 6, 5),
            (4, 7, 6),
            (0, 4, 5),
            (0, 5, 1),
            (1, 5, 6),
            (1, 6, 2),
            (2, 6, 7),
            (2, 7, 3),
            (3, 7, 4),
            (3, 4, 0),
        ),
        target_cells=frozenset({core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)}),
        required_pixels=(),
        locked_placements=(),
        max_parts=1,
        target_parts=1,
    )

    assert result.status == "OPTIMAL"
    assert result.fallback_reason is None
    assert len(result.placements) == 1
    assert result.placements[0].position == core.GridPosition(0, 0, 0)
    assert result.candidate_count > 1
    assert result.variable_pixel_count > 0


def test_catalogue_objective_refuses_an_oversized_candidate_set(monkeypatch) -> None:
    import app.conversion.catalogue_silhouette_experiment as experiment

    monkeypatch.setattr(experiment, "MAX_CANDIDATES", 1)
    result = optimise_catalogue_silhouette(
        source_vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)),
        faces=((0, 1, 2),),
        target_cells=frozenset({core.GridPosition(0, 0, 0), core.GridPosition(1, 0, 0)}),
        required_pixels=(),
        locked_placements=(),
        max_parts=1,
        target_parts=1,
    )

    assert result.status == "NOT_RUN"
    assert result.fallback_reason == "candidate_limit_exhausted"


def test_objective_raster_is_selection_independent_and_not_silhouette_v1_masks() -> None:
    """The solver's fixed envelope is deliberately different from silhouette-v1.

    silhouette-v1 computes bounds from the selected output.  A CP-SAT candidate
    mask cannot do that because its pixels must be defined before selection.
    This regression test makes the documented surrogate boundary explicit.
    """
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 1.0))
    target = frozenset({core.GridPosition(0, 0, 0), core.GridPosition(2, 0, 0)})
    candidates = _enumerate_candidates(target, core.BRICK_CATALOGUE)
    candidate = next(item for item in candidates if item.placement.position.x == 2)
    _, _, fixed_source = _raster_pixels(vertices, ((0, 1, 2),), (candidate,), (), target)
    frozen_source, _ = render_silhouette_masks(
        vertices, ((0, 1, 2),), core._placement_boxes((candidate.placement,))
    )["front"]

    assert len(fixed_source) > 0
    assert fixed_source != frozenset(
        ("front", index % 128, index // 128)
        for index, value in enumerate(frozen_source.get_flattened_data())
        if value
    )
