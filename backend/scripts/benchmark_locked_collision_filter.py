"""Measure M14A's local locked-body collision-filter optimization offline.

The synthetic placements use no source GLB, network access, or production
conversion routing. Every case first verifies exact retained-candidate identity
and ordering against the pre-M14A pairwise predicate, then measures each
implementation independently.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.core import BrickPlacement, GridPosition  # noqa: E402
from app.conversion.part_catalogue import PART_BY_ID  # noqa: E402
from app.conversion.physical_geometry import placements_overlap  # noqa: E402
from app.conversion.surface_grid_v4 import (  # noqa: E402
    _Candidate,
    _exclude_locked_body_collisions,
)

DEFAULT_REPETITIONS = 3
# Keep the default three-repetition run comfortably local and bounded while
# still increasing pairwise work by a factor of 36 from first to last case.
BENCHMARK_CASES = ((48, 6), (96, 12), (144, 18))
CollisionFilter = Callable[
    [tuple[_Candidate, ...], tuple[BrickPlacement, ...]], tuple[_Candidate, ...]
]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    candidate_count: int
    locked_placement_count: int
    retained_candidate_count: int
    pairwise_seconds: float
    union_seconds: float

    @property
    def speedup(self) -> float:
        return self.pairwise_seconds / self.union_seconds


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repetitions",
        type=int,
        default=DEFAULT_REPETITIONS,
        help="Positive count of timing repetitions per implementation and case.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.repetitions < 1:
        print("--repetitions must be positive.", file=sys.stderr)
        return 2

    results = run_benchmark(arguments.repetitions)
    print("candidates locked retained pairwise_s union_s speedup")
    for result in results:
        print(
            f"{result.candidate_count:10d} {result.locked_placement_count:6d} "
            f"{result.retained_candidate_count:8d} {result.pairwise_seconds:10.6f} "
            f"{result.union_seconds:7.6f} {result.speedup:7.2f}x"
        )
    return 0


def run_benchmark(repetitions: int = DEFAULT_REPETITIONS) -> tuple[BenchmarkResult, ...]:
    """Run increasing synthetic workloads after proving exact result parity."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive.")

    results: list[BenchmarkResult] = []
    for candidate_count, locked_placement_count in BENCHMARK_CASES:
        candidates = _candidates(candidate_count)
        locked = _locked_placements(locked_placement_count)
        reference = _reference_pairwise_filter(candidates, locked)
        optimized = _exclude_locked_body_collisions(candidates, locked)
        _require_identical_candidates(reference, optimized)

        pairwise_seconds = _median_elapsed_seconds(
            _reference_pairwise_filter, candidates, locked, repetitions
        )
        union_seconds = _median_elapsed_seconds(
            _exclude_locked_body_collisions, candidates, locked, repetitions
        )
        results.append(
            BenchmarkResult(
                candidate_count,
                locked_placement_count,
                len(optimized),
                pairwise_seconds,
                union_seconds,
            )
        )
    return tuple(results)


def _reference_pairwise_filter(
    candidates: tuple[_Candidate, ...], locked_placements: tuple[BrickPlacement, ...]
) -> tuple[_Candidate, ...]:
    """The original M14A pairwise predicate, retained for offline comparison."""
    return tuple(
        candidate
        for candidate in candidates
        if all(
            not placements_overlap(candidate.placement, locked_placement)
            for locked_placement in locked_placements
        )
    )


def _median_elapsed_seconds(
    filter_function: CollisionFilter,
    candidates: tuple[_Candidate, ...],
    locked_placements: tuple[BrickPlacement, ...],
    repetitions: int,
) -> float:
    elapsed: list[float] = []
    for _ in range(repetitions):
        start = perf_counter()
        filter_function(candidates, locked_placements)
        elapsed.append(perf_counter() - start)
    return median(elapsed)


def _candidates(count: int) -> tuple[_Candidate, ...]:
    part_ids = ("3022", "3023", "3710", "3020")
    orientations = (0, 90)
    return tuple(
        _Candidate(
            BrickPlacement(
                PART_BY_ID[part_ids[index % len(part_ids)]],
                GridPosition(index * 8, 0, 0),
                orientations[index % len(orientations)],
            ),
            frozenset(),
        )
        for index in range(count)
    )


def _locked_placements(count: int) -> tuple[BrickPlacement, ...]:
    part_ids = ("4286", "41769", "41770", "15068", "3020")
    orientations = (0, 90, 180, 270)
    return tuple(
        BrickPlacement(
            PART_BY_ID[part_ids[index % len(part_ids)]],
            GridPosition(index * 8, 100, 0),
            orientations[index % len(orientations)],
        )
        for index in range(count)
    )


def _require_identical_candidates(
    reference: tuple[_Candidate, ...], optimized: tuple[_Candidate, ...]
) -> None:
    if len(reference) != len(optimized) or any(
        actual is not expected for actual, expected in zip(optimized, reference, strict=True)
    ):
        raise RuntimeError("Collision filters returned different candidate identities or ordering.")


if __name__ == "__main__":
    raise SystemExit(main())
