"""Offline M13E Duck CP-SAT hint experiment helpers; never used by conversion."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from hashlib import sha256

from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13c_silhouette_equivalence_audit import AuditError
from app.conversion.surface_grid_v4 import _Candidate

DUCK_SOURCE_SHA256 = "77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e"
DUCK_CANDIDATE_COUNT = 1449
DUCK_MAX_PARTS = 60
DUCK_GRID = {"width_studs": 5, "depth_studs": 7, "height_plates": 12}
DUCK_CONTROL_VIEWS = {
    "front": {"truePositives": 7803, "falsePositives": 3940},
    "side": {"truePositives": 6558, "falsePositives": 4002},
    "top": {"truePositives": 7227, "falsePositives": 5793},
}


def control_candidate_indices(
    candidates: Sequence[_Candidate], control_placement_ids: Collection[str]
) -> tuple[int, ...]:
    """Map each rectangular Control placement exactly once into candidate order."""
    candidate_ids = [stable_placement_id(candidate.placement) for candidate in candidates]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise AuditError("Reconstructed candidate IDs are not unique.")
    candidate_by_id = {placement_id: index for index, placement_id in enumerate(candidate_ids)}
    rectangular_ids = tuple(control_placement_ids)
    if len(set(rectangular_ids)) != len(rectangular_ids):
        raise AuditError("Historical Control rectangular placement IDs are duplicated.")
    missing = [
        placement_id for placement_id in rectangular_ids if placement_id not in candidate_by_id
    ]
    if missing:
        raise AuditError(f"Control candidate membership failed: {missing[0]}")
    return tuple(candidate_by_id[placement_id] for placement_id in rectangular_ids)


def complete_selection_hint(candidate_count: int, selected_ids: Collection[int]) -> tuple[int, ...]:
    """Return a complete 0/1 selection vector for auditable AddHint construction."""
    selected = tuple(selected_ids)
    if len(set(selected)) != len(selected):
        raise AuditError("Control candidate indices are duplicated.")
    if any(index < 0 or index >= candidate_count for index in selected):
        raise AuditError("Control candidate index is out of range.")
    selected_set = frozenset(selected)
    return tuple(int(index in selected_set) for index in range(candidate_count))


def model_fingerprint(
    *,
    candidate_ids: Sequence[str],
    locked_ids: Sequence[str],
    required_pixels: Collection[tuple[str, int, int]],
    fixed_coverage_pixels: Collection[tuple[str, int, int]],
    control_views: Mapping[str, Mapping[str, int]],
    objective_mode: str = "min_fp",
    tp_loss_allowances: Mapping[str, int] | None = None,
) -> str:
    """Fingerprint mathematical inputs only; a search hint is intentionally excluded."""
    payload = {
        "candidateIds": list(candidate_ids),
        "lockedIds": list(locked_ids),
        "requiredPixels": sorted(required_pixels),
        "fixedCoveragePixels": sorted(fixed_coverage_pixels),
        "controlViews": control_views,
        "maxParts": DUCK_MAX_PARTS,
        "objective": (
            "minimize total fixed-frame FP"
            if objective_mode == "min_fp"
            else "maximize total fixed-frame TP"
        ),
        "solver": {"randomSeed": 0, "workers": 1, "deterministicTimeSeconds": 30.0},
    }
    if tp_loss_allowances is not None:
        payload["tpLossAllowances"] = dict(tp_loss_allowances)
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
