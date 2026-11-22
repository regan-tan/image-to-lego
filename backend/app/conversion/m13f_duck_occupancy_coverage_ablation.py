"""Exact source-occupancy policy helpers for the opt-in M13F Duck study."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256

from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement

Pixel = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class OccupancyRequirement:
    """A historical coarse requirement paired with its source-raster evidence."""

    requirement: CoarseRequirement
    pixel_count: int
    source_foreground_pixels: int

    @property
    def fraction(self) -> Fraction:
        if self.pixel_count <= 0:
            raise ValueError("A coarse-cell raster region must contain at least one pixel.")
        return Fraction(self.source_foreground_pixels, self.pixel_count)


@dataclass(frozen=True, slots=True)
class CoveragePolicy:
    """One predeclared comparison policy; ``None`` means fully relaxed."""

    name: str
    minimum_occupancy: Fraction | None


POLICIES = (
    CoveragePolicy("historical", Fraction(0)),
    CoveragePolicy("nonempty-source-occupancy", Fraction(1, 1_000_000_000)),
    CoveragePolicy("source-occupancy-ge-5-percent", Fraction(5, 100)),
    CoveragePolicy("source-occupancy-ge-10-percent", Fraction(10, 100)),
    CoveragePolicy("source-occupancy-ge-25-percent", Fraction(25, 100)),
    CoveragePolicy("source-occupancy-ge-50-percent", Fraction(50, 100)),
    CoveragePolicy("fully-relaxed", None),
)


def occupancy_requirements(
    requirements: Sequence[CoarseRequirement],
    source_pixels: Collection[Pixel],
    coarse_cell_region: Callable[[Pixel], Collection[Pixel]],
) -> tuple[OccupancyRequirement, ...]:
    """Measure every historical requirement against the pinned source mask."""
    source = frozenset(source_pixels)
    records: list[OccupancyRequirement] = []
    for requirement in requirements:
        region = frozenset(coarse_cell_region(requirement.pixel))
        records.append(OccupancyRequirement(requirement, len(region), len(region & source)))
    return tuple(records)


def requirements_for_policy(
    policy: CoveragePolicy, records: Sequence[OccupancyRequirement]
) -> tuple[CoarseRequirement, ...]:
    """Choose mandatory cells with exact inclusive rational threshold semantics."""
    if policy.minimum_occupancy is None:
        return ()
    if policy.name == "nonempty-source-occupancy":
        return tuple(
            record.requirement for record in records if record.source_foreground_pixels > 0
        )
    return tuple(
        record.requirement for record in records if record.fraction >= policy.minimum_occupancy
    )


def requirement_set_sha256(requirements: Collection[CoarseRequirement]) -> str:
    """Hash only stable view/cell identities, in historical coordinate order."""
    text = "\n".join(
        f"{item.pixel[0]}:{item.pixel[1]}:{item.pixel[2]}"
        for item in sorted(requirements, key=lambda x: x.pixel)
    )
    return sha256(text.encode()).hexdigest()


def policy_definition(policy: CoveragePolicy) -> str:
    """Give a concise, unambiguous serialization of the policy boundary."""
    if policy.minimum_occupancy is None:
        return "No historical coarse requirement is mandatory."
    if policy.name == "nonempty-source-occupancy":
        return "sourceForegroundPixels > 0; exact integer comparison."
    threshold = policy.minimum_occupancy
    return (
        "sourceForegroundPixels / pixelCount >= "
        f"{threshold.numerator}/{threshold.denominator}; exact Fraction comparison."
    )
