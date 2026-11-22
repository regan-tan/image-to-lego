"""Static, no-solver measurements for the pinned M13 Duck reconstruction.

This module intentionally describes independent candidate-union geometry.  Its
numbers do not claim that the union is selectable as one mechanically valid
assembly.  The M13F runner owns source reconstruction and provenance checks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from hashlib import sha256

from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13d_tp_fp_feasibility_experiment import VIEWS
from app.conversion.m13e_duck_iou_incidence_compression import build_incidence_compression
from app.conversion.surface_grid_v4 import _Candidate

Pixel = tuple[str, int, int]


def pixel_hash(pixels: Collection[Pixel]) -> str:
    """Return the historical coordinate-list SHA-256 used for raster parity."""
    text = "\n".join(f"{view}:{first}:{second}" for view, first, second in sorted(set(pixels)))
    return sha256(text.encode()).hexdigest()


def projection_hashes(**masks: Collection[Pixel]) -> dict[str, dict[str, str]]:
    """Hash each named projection mask separately for every fixed-frame view."""
    return {
        name: {
            view: pixel_hash(frozenset(pixel for pixel in pixels if pixel[0] == view))
            for view in VIEWS
        }
        for name, pixels in masks.items()
    }


def candidate_id_hash(candidates: Sequence[_Candidate]) -> str:
    """Fingerprint the ordered historical candidate vocabulary and placements."""
    ids = [stable_placement_id(candidate.placement) for candidate in candidates]
    return sha256("\n".join(ids).encode()).hexdigest()


def static_inventory(
    *,
    candidates: Sequence[_Candidate],
    candidate_rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    control_pixels: Collection[Pixel],
    preflight_counts: Mapping[str, int],
) -> dict[str, object]:
    """Measure fixed-frame coverage and preflight filters without solving."""
    if len(candidates) != len(candidate_rasters):
        raise ValueError("Candidates and candidate rasters must have matching lengths.")
    source = frozenset(source_pixels)
    locked = frozenset(locked_pixels)
    control = frozenset(control_pixels)
    candidate_union = frozenset().union(*(frozenset(raster) for raster in candidate_rasters))
    available_union = locked | candidate_union
    compression = build_incidence_compression(candidate_rasters, source, locked)

    views: dict[str, object] = {}
    for view in VIEWS:
        source_view = _for_view(source, view)
        locked_view = _for_view(locked, view)
        candidate_view = _for_view(candidate_union, view)
        control_view = _for_view(control, view)
        coverable_foreground = source_view & candidate_view
        views[view] = {
            "sourceForegroundPixels": len(source_view),
            "uniqueLockedForegroundPixels": len(locked_view & source_view),
            "uniqueLockedBackgroundPixels": len(locked_view - source_view),
            "control": _metrics(source_view, control_view),
            "permanentlyUnreachableForegroundPixels": len(source_view - available_union),
            "candidateCoverableForegroundMissedByControl": len(coverable_foreground - control_view),
            "candidateCoverableBackgroundCoveredByControl": len(
                (candidate_view - source_view) & control_view
            ),
            "candidateUnion": {
                "uniqueForegroundPixels": len(candidate_view & source_view),
                "uniqueBackgroundPixels": len(candidate_view - source_view),
                "foregroundPixelsNotCoverableByLockedOrCandidateUnion": len(
                    source_view - available_union
                ),
            },
        }

    incidence_sizes = Counter(len(group.candidate_ids) for group in compression.groups)
    group_pixel_weights = Counter(
        len(group.candidate_ids)
        for group in compression.groups
        for _ in range(sum(group.tp_weights.values()) + sum(group.fp_weights.values()))
    )
    raw_count = preflight_counts["rawRectangles"]
    locked_count = preflight_counts["afterLockedBodyCollision"]
    reachable_count = preflight_counts["afterSupportReachability"]
    return {
        "views": views,
        "candidateUnionLimitations": {
            "candidateUnionProjectionHashes": projection_hashes(candidateUnion=candidate_union)[
                "candidateUnion"
            ],
            "relaxations": [
                "occupancy mutual exclusion and collision combinations",
                "verified support combinations",
                "mandatory coarse coverage interactions",
                "part cap",
                "post-solve connected-component reporting",
            ],
            "interpretation": (
                "Independent candidate-union coverage is an optimistic geometric envelope, not "
                "a simultaneously feasible assembly."
            ),
        },
        "incidenceGroups": {
            "groupCount": len(compression.groups),
            "candidateIncidenceSizeDistribution": _counter_payload(incidence_sizes),
            "pixelWeightByIncidenceSize": _counter_payload(group_pixel_weights),
            "touchableNonLockedPixelCount": compression.touchable_pixel_count,
            "candidatePixelReferenceCount": compression.candidate_reference_count,
            "permanentlyUncoveredForegroundByView": dict(compression.permanently_uncovered_tp),
        },
        "candidateExclusions": {
            "rawRectangularCandidates": raw_count,
            "excludedByLockedBodyCollision": raw_count - locked_count,
            "excludedBySupportReachabilityAfterCollisionFilter": locked_count - reachable_count,
            "eligibleRectangularCandidates": reachable_count,
            "protectedSpace": {
                "excludedRectangularCandidates": 0,
                "status": "NOT_A_RECTANGULAR_PREFLIGHT_FILTER",
                "note": (
                    "Protected empty space was applied to optional wedge eligibility. The "
                    "historical no-wedge run did not enumerate wedge candidates."
                ),
            },
            "partVocabulary": {
                "status": "NOT_DETERMINABLE_WITHOUT_A_COUNTERFACTUAL_VOCABULARY",
                "note": (
                    "The historical catalogue defines what was enumerated; it cannot count "
                    "placements absent from an unimplemented alternative vocabulary."
                ),
            },
        },
    }


def active_restriction_classification() -> dict[str, object]:
    """Classify historical constraints without making an ablation causality claim."""
    return {
        "directCandidatePlacementExclusions": [
            "locked-body collision filtering for rectangular candidates",
            "support-reachability pruning after collision filtering",
            "the fixed historical part vocabulary (scope, not a countable rejection filter)",
        ],
        "combinationRestrictions": [
            "rectangular occupancy mutual exclusion",
            "verified direct support requirements",
            "support requirements for locked placements",
            "mandatory coarse projection coverage",
            "maximum part count",
        ],
        "postSolveOrFixedGeometry": [
            "locked slope geometry is fixed rather than an optional candidate family",
            (
                "protected-space, collision, support, and interface checks validate "
                "completed assemblies"
            ),
            (
                "connected-component count is reported after solving, not enforced by "
                "the historical CP-SAT model"
            ),
        ],
        "requiresSeparateAblationForCausalImportance": [
            "occupancy",
            "support",
            "mandatory coarse coverage",
            "protected space",
            "part cap",
            "locked geometry",
            "part vocabulary",
        ],
        "interpretation": (
            "Presence or tightness alone does not establish a causal fidelity bottleneck."
        ),
    }


def controlled_ablation_matrix() -> list[dict[str, object]]:
    """Return an execution plan only; M13F never creates a solver model."""
    common = {
        "candidateModel": "historical ordered 1,449 rectangular candidates plus locked geometry",
        "objective": "unchanged M13E-B5 quantized fixed-frame surrogate",
        "evaluation": (
            "independent exact fixed-frame and frozen silhouette-v1 IoUs for every incumbent"
        ),
        "status": "PREPARED_NOT_EXECUTED",
    }
    return [
        {"arm": "control", "changedConstraintFamily": "none", **common},
        {
            "arm": "mandatory-coarse-coverage-relaxed",
            "changedConstraintFamily": "mandatory coarse coverage only",
            "change": (
                "remove only coarse coverage clauses; retain occupancy, support, locked geometry, "
                "protected space, and cap"
            ),
            "mechanicalValidity": (
                "potentially historically inadmissible because coarse coverage is relaxed"
            ),
            **common,
        },
    ]


def next_generation_proposals() -> list[dict[str, object]]:
    """Name minimal future vocabulary studies; no new candidate is implemented here."""
    return [
        {
            "proposal": (
                "Add verified narrow 1-wide curved or faceted profile pieces at existing grid "
                "coordinates"
            ),
            "targets": "candidate-union foreground gaps and stair-step profile limits",
            "newPiecesOrPlacements": (
                "a small documented catalogue of orientation-aware non-rectangular placements"
            ),
            "gridChange": False,
            "lockedGeometryChange": False,
            "preservedHistoricalConstraints": (
                "collision, support, protected space, mandatory coverage, cap, and post-solve "
                "validation"
            ),
            "comparability": (
                "record ordered candidate IDs, per-view projection hashes, source SHA-256, and "
                "evaluate with unchanged frames/evaluators"
            ),
        },
        {
            "proposal": (
                "Add smaller rectangular footprint placements where the existing catalogue has no "
                "1-wide fit"
            ),
            "targets": (
                "candidate-coverable foreground missed by Control caused by coarse rectangle "
                "granularity"
            ),
            "newPiecesOrPlacements": (
                "only manufactured, mechanically modelled smaller brick or plate footprints"
            ),
            "gridChange": False,
            "lockedGeometryChange": False,
            "preservedHistoricalConstraints": "all historical physical constraints",
            "comparability": (
                "keep the source, grid, fixed frames, Control arm, and candidate provenance "
                "format unchanged"
            ),
        },
        {
            "proposal": (
                "Evaluate a separately versioned finer lattice only after vocabulary studies"
            ),
            "targets": (
                "unreachable silhouette detail that cannot be represented at the current lattice"
            ),
            "newPiecesOrPlacements": "new placements generated on a new grid version",
            "gridChange": True,
            "lockedGeometryChange": "must be regenerated and separately pinned",
            "preservedHistoricalConstraints": (
                "same constraint families, revalidated against the new grid"
            ),
            "comparability": (
                "not directly candidate-comparable; preserve source hash and report a new "
                "grid/provenance version beside historical results"
            ),
        },
    ]


def _for_view(pixels: Collection[Pixel], view: str) -> frozenset[Pixel]:
    return frozenset(pixel for pixel in pixels if pixel[0] == view)


def _metrics(source: Collection[Pixel], output: Collection[Pixel]) -> dict[str, int]:
    return {
        "truePositives": len(set(source) & set(output)),
        "falsePositives": len(set(output) - set(source)),
        "falseNegatives": len(set(source) - set(output)),
    }


def _counter_payload(counts: Counter[int]) -> dict[str, int]:
    return {str(key): counts[key] for key in sorted(counts)}
