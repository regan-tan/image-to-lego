from fractions import Fraction

from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement
from app.conversion.m13f_duck_occupancy_coverage_ablation import (
    CoveragePolicy,
    occupancy_requirements,
    requirement_set_sha256,
    requirements_for_policy,
)


def test_thresholds_use_exact_inclusive_fraction_boundaries() -> None:
    requirements = (
        CoarseRequirement(("front", 0, 0), (0,), False),
        CoarseRequirement(("front", 1, 0), (1,), False),
        CoarseRequirement(("front", 2, 0), (2,), False),
    )
    regions = {
        ("front", 0, 0): {("front", 0, 0), ("front", 0, 1)},
        ("front", 1, 0): {("front", 1, 0), ("front", 1, 1)},
        ("front", 2, 0): {("front", 2, 0), ("front", 2, 1)},
    }
    records = occupancy_requirements(
        requirements,
        {("front", 0, 0), ("front", 1, 0), ("front", 1, 1)},
        regions.__getitem__,
    )
    selected = requirements_for_policy(CoveragePolicy("half", Fraction(1, 2)), records)
    assert [item.pixel for item in selected] == [("front", 0, 0), ("front", 1, 0)]
    assert requirements_for_policy(CoveragePolicy("fully-relaxed", None), records) == ()


def test_nonempty_excludes_zero_foreground_and_set_hash_is_order_independent() -> None:
    records = occupancy_requirements(
        (
            CoarseRequirement(("front", 1, 0), (1,), False),
            CoarseRequirement(("front", 0, 0), (0,), False),
        ),
        {("front", 0, 0)},
        lambda pixel: {pixel},
    )
    selected = requirements_for_policy(
        CoveragePolicy("nonempty-source-occupancy", Fraction(1, 1)), records
    )
    assert [item.pixel for item in selected] == [("front", 0, 0)]
    assert requirement_set_sha256(selected) == requirement_set_sha256(tuple(reversed(selected)))
