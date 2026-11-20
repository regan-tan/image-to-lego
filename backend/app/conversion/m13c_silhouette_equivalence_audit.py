"""Offline M13C reconstruction and exact silhouette comparison helpers.

This module deliberately consumes completed M13B records.  It never invokes a
solver: placement IDs are reconstructed against the checked-in catalogue and
all raster comparisons use explicit, recorded frames.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256

from PIL import Image

from app.conversion import core
from app.conversion.evaluation_alignment import (
    SilhouetteComparison,
    evaluate_completed_assembly,
    stable_placement_id,
)
from app.conversion.fidelity import SILHOUETTE_RESOLUTION
from app.conversion.m12c_wedge_fidelity_experiment import (
    _raster_pixels,
    fixed_frame_score,
    preflight_wedge_candidates,
)
from app.conversion.m13a_objective_alignment_audit import (
    VIEW_AXES,
    ArrangementMetrics,
    Bounds,
    _render_geometry,
    combined_native_bounds,
    evaluate_native,
    evaluate_shared_bounds,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.surface_grid_v4 import (
    _Candidate,
    _enumerate_candidates,
    _exclude_locked_body_collisions,
    _support_reachable_candidates,
    projection_hull_target,
)

VIEWS = ("front", "side", "top")
PLACEMENT_ID = re.compile(
    r"^(?P<part_id>[^@,:]+)@(?P<x>-?\d+),(?P<y>-?\d+),(?P<z>-?\d+):(?P<orientation>-?\d+)$"
)
AUDIT_RESULT_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "M13C silhouette equivalence audit",
    "type": "object",
    "required": ["schemaVersion", "stageA", "candidateCeiling", "records"],
    "properties": {
        "schemaVersion": {"const": "m13c-silhouette-equivalence-audit-v1"},
        "stageA": {"enum": ["PASS", "FAIL"]},
        "candidateCeiling": {"type": ["object", "null"]},
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "caseId",
                    "source",
                    "placementComparison",
                    "mechanical",
                    "parity",
                    "stageA",
                    "comparison",
                    "candidateCeiling",
                ],
            },
        },
    },
}


class AuditError(ValueError):
    """Saved M13B evidence cannot be safely reconstructed or compared."""


@dataclass(frozen=True, slots=True)
class MaskComparison:
    source_sha256: str
    control_sha256: str
    experiment_sha256: str
    xor_pixels: int
    control_only_pixels: int
    experiment_only_pixels: int
    intersection_pixels: int
    union_pixels: int
    jaccard: float
    exactly_identical: bool


@dataclass(frozen=True, slots=True)
class M13bPreprocessing:
    """Deterministic M13B inputs available before its first solver call."""

    source_vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]
    target_cells: frozenset[core.GridPosition]
    required_pixels: frozenset[tuple[str, int, int]]
    protected_empty_cells: frozenset[core.GridPosition]
    initial_locked_slope_placements: tuple[core.BrickPlacement, ...]


@dataclass(frozen=True, slots=True)
class M13bCandidatePreflight:
    """No-solve evidence for the historical M12C/M13B candidate preflight."""

    candidates: tuple[_Candidate, ...]
    candidate_rasters: tuple[frozenset[tuple[str, int, int]], ...] | None
    locked_pixels: frozenset[tuple[str, int, int]] | None
    source_pixels: frozenset[tuple[str, int, int]] | None
    status: str
    raw_rectangle_count: int
    collision_filtered_rectangle_count: int
    support_reachable_rectangle_count: int
    eligible_wedge_count: int
    combined_candidate_count: int


def reconstruct_placements(placement_ids: Sequence[str]) -> tuple[core.BrickPlacement, ...]:
    """Recreate ordered physical placements from M13B's stable identifiers."""
    placements: list[core.BrickPlacement] = []
    for placement_id in placement_ids:
        match = PLACEMENT_ID.fullmatch(placement_id)
        if match is None:
            raise AuditError(f"Invalid placement ID: {placement_id!r}.")
        part_id = match["part_id"]
        part = PART_BY_ID.get(part_id)
        if part is None:
            raise AuditError(f"Placement references unknown catalogue part {part_id!r}.")
        orientation = int(match["orientation"])
        if orientation % 90:
            raise AuditError(f"Placement orientation must be a multiple of 90: {placement_id!r}.")
        placement = core.BrickPlacement(
            part,
            core.GridPosition(int(match["x"]), int(match["y"]), int(match["z"])),
            orientation,
        )
        if stable_placement_id(placement) != placement_id:
            raise AuditError(f"Placement ID cannot be reproduced: {placement_id!r}.")
        placements.append(placement)
    return tuple(placements)


def verify_source_sha256(source: bytes, expected_sha256: object) -> str:
    """Return a verified source digest and reject missing or mismatched evidence."""
    if not isinstance(expected_sha256, str):
        raise AuditError("Saved source SHA-256 must be a string.")
    actual = sha256(source).hexdigest()
    if actual != expected_sha256:
        raise AuditError("Saved source SHA-256 does not match the verified source bytes.")
    return actual


def placement_comparison(
    control: Collection[core.BrickPlacement], experiment: Collection[core.BrickPlacement]
) -> dict[str, int | bool]:
    """Compare placement multisets without implying any 3D equivalence."""
    left = Counter(stable_placement_id(item) for item in control)
    right = Counter(stable_placement_id(item) for item in experiment)
    shared = sum((left & right).values())
    return {
        "sharedPlacements": shared,
        "uniqueToControl": sum((left - right).values()),
        "uniqueToExperiment": sum((right - left).values()),
        "partCountDifference": sum(right.values()) - sum(left.values()),
        "identicalPlacementMultiset": left == right,
    }


def render_masks_in_bounds(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Collection[core.BrickPlacement],
    bounds: Mapping[str, Bounds],
) -> dict[str, tuple[Image.Image, Image.Image]]:
    """Render source and LEGO geometry in one validated explicit 128px frame."""
    if set(bounds) != set(VIEWS):
        raise AuditError("Frame bounds must contain front, side, and top views.")
    placement_tuple = tuple(placements)
    boxes = core._placement_boxes(placement_tuple)
    slopes = core._slope_vertices(placement_tuple)
    wedges = core._wedge_vertices(placement_tuple)
    return {
        view: (
            _render_geometry(source_vertices, faces, (), (), (), VIEW_AXES[view], bounds[view]),
            _render_geometry((), (), boxes, slopes, wedges, VIEW_AXES[view], bounds[view]),
        )
        for view in VIEWS
    }


def compare_mask_triplets(
    control: Mapping[str, tuple[Image.Image, Image.Image]],
    experiment: Mapping[str, tuple[Image.Image, Image.Image]],
    bounds: Mapping[str, Bounds],
) -> dict[str, dict[str, object]]:
    """Fingerprint A/B masks only after confirming both use the same frame."""
    if set(control) != set(VIEWS) or set(experiment) != set(VIEWS):
        raise AuditError("Mask sets must contain front, side, and top views.")
    _validate_bounds(bounds)
    result: dict[str, dict[str, object]] = {}
    for view in VIEWS:
        source_a, lego_a = control[view]
        source_b, lego_b = experiment[view]
        if (
            source_a.size != source_b.size
            or lego_a.size != lego_b.size
            or source_a.size != lego_a.size
        ):
            raise AuditError(f"{view} masks have incompatible dimensions.")
        source_a_bytes = _mask_bytes(source_a)
        source_b_bytes = _mask_bytes(source_b)
        if source_a_bytes != source_b_bytes:
            raise AuditError(f"{view} source masks differ in a declared shared frame.")
        metrics = _compare_masks(source_a, lego_a, lego_b)
        result[view] = {
            **asdict(metrics),
            "frame": {
                "bounds": list(bounds[view]),
                "rasterWidth": source_a.width,
                "rasterHeight": source_a.height,
            },
        }
    return result


def native_comparison_metadata(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    control: Collection[core.BrickPlacement],
    experiment: Collection[core.BrickPlacement],
) -> dict[str, object]:
    """Record native metrics; direct pixel comparison is allowed only for equal bounds."""
    control_metrics = evaluate_native(source_vertices, faces, control)
    experiment_metrics = evaluate_native(source_vertices, faces, experiment)
    control_bounds = dict(control_metrics.bounds)
    experiment_bounds = dict(experiment_metrics.bounds)
    same_bounds = control_bounds == experiment_bounds
    result: dict[str, object] = {
        "control": asdict(control_metrics),
        "experiment": asdict(experiment_metrics),
        "boundsIdentical": same_bounds,
        "pixelComparison": "not-performed-different-native-bounds",
    }
    if same_bounds:
        control_masks = render_masks_in_bounds(source_vertices, faces, control, control_bounds)
        experiment_masks = render_masks_in_bounds(
            source_vertices, faces, experiment, control_bounds
        )
        result["pixelComparison"] = compare_mask_triplets(
            control_masks, experiment_masks, control_bounds
        )
    return result


def parity_record(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Sequence[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
    saved: Mapping[str, object],
    shared_bounds: Mapping[str, Bounds],
) -> dict[str, object]:
    """Independently reproduce every saved M13B metric needed for the gate."""
    expected_ids = _string_list(saved.get("placementIds"), "placementIds")
    identity_matches = [stable_placement_id(item) for item in placements] == expected_ids
    fixed = fixed_frame_score(source_vertices, faces, placements, target_cells)
    source_counts = _fixed_source_counts(source_vertices, faces, placements, target_cells)
    fixed_views = {
        item.view: {
            "truePositives": item.true_positives,
            "falsePositives": item.false_positives,
            "falseNegatives": source_counts[item.view] - item.true_positives,
        }
        for item in fixed.views
    }
    fixed_mean = sum(
        _iou(
            values["truePositives"],
            values["falsePositives"],
            values["truePositives"] + values["falseNegatives"],
        )
        for values in fixed_views.values()
    ) / len(VIEWS)
    frozen = evaluate_completed_assembly(source_vertices, faces, placements)
    shared = evaluate_shared_bounds(source_vertices, faces, placements, shared_bounds)
    fixed_failures = fixed_frame_parity_failures(fixed_views, fixed_mean, saved.get("fixedFrame"))
    frozen_failures = frozen_silhouette_parity_failures(frozen, saved.get("frozenSilhouetteV1"))
    shared_failures = shared_bounds_parity_failures(shared, saved.get("sharedBounds"))
    placement_failures = (
        ()
        if identity_matches
        else ("placementIds: expected saved ordered placement IDs, got reconstructed IDs",)
    )
    part_count_failures = (
        ()
        if len(placements) == saved.get("partCount")
        else (f"partCount: expected {saved.get('partCount')!r}, got {len(placements)}",)
    )
    checks = {
        "placementIdentity": identity_matches,
        "partCount": len(placements) == saved.get("partCount"),
        "fixedFrame": not fixed_failures,
        "frozenSilhouetteV1": not frozen_failures,
        "sharedBounds": not shared_failures,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "failures": {
            "placementIdentity": list(placement_failures),
            "partCount": list(part_count_failures),
            "fixedFrame": list(fixed_failures),
            "frozenSilhouetteV1": list(frozen_failures),
            "sharedBounds": list(shared_failures),
        },
        "reconstructed": {
            "placementIds": [stable_placement_id(item) for item in placements],
            "partCount": len(placements),
            "fixedFrame": {"views": fixed_views, "meanIou": fixed_mean},
            "frozenSilhouetteV1": asdict(frozen),
            "sharedBounds": asdict(shared),
        },
    }


def shared_bounds_for_pair(
    source_vertices: Sequence[tuple[float, float, float]],
    control: Collection[core.BrickPlacement],
    experiment: Collection[core.BrickPlacement],
) -> dict[str, Bounds]:
    """Use the M13B source-plus-both-assemblies shared-frame definition."""
    return combined_native_bounds(source_vertices, control, experiment)


def reconstruct_m13b_target_cells(
    source: bytes, grid: core.GridSize, up_axis: core.Axis
) -> tuple[
    list[tuple[float, float, float]], list[tuple[int, int, int]], frozenset[core.GridPosition]
]:
    """Recreate M13B's aligned source and fixed target cells without solving."""
    preprocessing = reconstruct_m13b_preprocessing(source, grid, up_axis)
    return preprocessing.source_vertices, preprocessing.faces, preprocessing.target_cells


def reconstruct_m13b_preprocessing(
    source: bytes, grid: core.GridSize, up_axis: core.Axis
) -> M13bPreprocessing:
    """Reproduce fixed-grid preprocessing through projection-hull construction only."""
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, up_axis)
    occupancy = core._source_occupancy(normalized, faces, grid)
    locked, locked_cells = core._place_supported_slopes(occupancy.surface_cells)
    locked_occupied = frozenset(
        cell for placement in locked for cell in core._placement_source_cells(placement)
    )
    rectangles = core.pack_occupied_cells(occupancy.surface_cells - locked_cells)
    exterior = frozenset(
        cell
        for placement in rectangles
        for cell in core._placement_cells(placement)
        if cell not in locked_occupied
    )
    protected = core._v5_protected_empty_cells(occupancy, grid)
    target, required_pixels = projection_hull_target(
        exterior, locked_cells, grid, protected_empty_cells=protected
    )
    target = target - locked_occupied
    return M13bPreprocessing(
        core._scale_vertices_to_grid(normalized, grid),
        faces,
        target,
        required_pixels,
        protected,
        locked,
    )


def candidate_coverage_ceiling(
    source_pixels: Collection[tuple[str, int, int]],
    locked_pixels: Collection[tuple[str, int, int]],
    candidate_pixels: Collection[Collection[tuple[str, int, int]]],
    observed_iou: Mapping[str, float],
    bounds: Mapping[str, Bounds],
) -> dict[str, object]:
    """Measure the relaxed M13C candidate-union coverage ceiling by fixed view."""
    source = frozenset(source_pixels)
    locked = frozenset(locked_pixels)
    candidates = frozenset().union(*(frozenset(item) for item in candidate_pixels))
    views: dict[str, dict[str, object]] = {}
    ceiling_values: list[float] = []
    for view in VIEWS:
        source_view = frozenset(pixel for pixel in source if pixel[0] == view)
        locked_view = frozenset(pixel for pixel in locked if pixel[0] == view)
        candidates_view = frozenset(pixel for pixel in candidates if pixel[0] == view)
        union_view = locked_view | candidates_view
        tp_upper = len(source_view & union_view)
        fp_lower = len(locked_view - source_view)
        denominator = len(source_view) + fp_lower
        iou_upper = 1.0 if denominator == 0 else round(tp_upper / denominator, 6)
        ceiling_values.append(iou_upper)
        observed = observed_iou[view]
        views[view] = {
            "sourceForegroundPixels": len(source_view),
            "sourcePixelsCoveredByLockedGeometry": len(source_view & locked_view),
            "sourcePixelsCoveredByEligibleCandidate": len(source_view & candidates_view),
            "sourcePixelsCoverableByCandidateOrLockedUnion": tp_upper,
            "sourcePixelsNotCoverable": len(source_view - union_view),
            "lockedOnlyFalsePositivePixels": fp_lower,
            "truePositiveUpperBound": tp_upper,
            "falsePositiveLowerBound": fp_lower,
            "optimisticIouUpperBound": iou_upper,
            "observedM13bFixedFrameIou": observed,
            "absoluteGapToObservedIou": round(abs(iou_upper - observed), 6),
            "frame": {
                "bounds": list(bounds[view]),
                "rasterWidth": SILHOUETTE_RESOLUTION,
                "rasterHeight": SILHOUETTE_RESOLUTION,
                "projection": {"front": "XZ", "side": "YZ", "top": "XY"}[view],
            },
        }
    return {
        "status": "RELAXED_UPPER_BOUND",
        "emptyMaskConvention": "IoU upper bound is 1.0 when its denominator is zero.",
        "relaxations": [
            "candidate mutual exclusion and collision conflicts",
            "verified support requirements",
            "global connectivity",
            "part-count limits",
            "mandatory coverage interactions",
            "other simultaneous selection restrictions",
        ],
        "views": views,
        "meanOptimisticIouUpperBound": round(sum(ceiling_values) / len(ceiling_values), 6),
    }


def candidate_preflight_failures(
    expected_count: object,
    candidates: Collection[_Candidate],
    control_placements: Collection[core.BrickPlacement],
) -> tuple[str, ...]:
    """Fail closed when reconstructed M13B eligibility differs from its saved evidence."""
    failures: list[str] = []
    if expected_count != len(candidates):
        failures.append(
            f"Candidate count mismatch: expected {expected_count!r}, got {len(candidates)}."
        )
    candidate_ids = {stable_placement_id(candidate.placement) for candidate in candidates}
    control_ids = {
        stable_placement_id(item)
        for item in control_placements
        if item.brick_type.shape == "rectangular"
    }
    missing_control_ids = sorted(control_ids - candidate_ids)
    if missing_control_ids:
        failures.append(
            "Control placements are absent from the reconstructed eligible candidate set: "
            + ", ".join(missing_control_ids)
        )
    return tuple(failures)


def stage_b_allowed(*parity_records: Mapping[str, object]) -> bool:
    """Keep the candidate audit behind successful Stage A reconstruction parity."""
    return all(record.get("passed") is True for record in parity_records)


def m13b_no_wedge_candidate_preflight(
    preprocessing: M13bPreprocessing,
    locked_placements: Collection[core.BrickPlacement],
) -> M13bCandidatePreflight:
    """Recreate M12C/M13B's candidate filter and exact fixed-frame rasters without solving."""
    raw = _enumerate_candidates(preprocessing.target_cells, core.BRICK_CATALOGUE)
    collision_filtered = _exclude_locked_body_collisions(raw, locked_placements)
    support_reachable = _support_reachable_candidates(
        collision_filtered, preprocessing.target_cells
    )
    candidates, wedges, preflight = preflight_wedge_candidates(
        target_cells=preprocessing.target_cells,
        protected_empty_cells=preprocessing.protected_empty_cells,
        locked_placements=locked_placements,
    )
    if candidates != support_reachable:
        raise AuditError("M13B candidate preflight does not match its documented filtering order.")
    if preflight.status != "READY":
        return M13bCandidatePreflight(
            candidates,
            None,
            None,
            None,
            preflight.status,
            len(raw),
            len(collision_filtered),
            len(support_reachable),
            len(wedges),
            preflight.total_candidate_count,
        )
    rasters, locked_pixels, source_pixels = _raster_pixels(
        preprocessing.source_vertices,
        preprocessing.faces,
        candidates,
        tuple(locked_placements),
        preprocessing.target_cells,
    )
    return M13bCandidatePreflight(
        candidates,
        rasters,
        locked_pixels,
        source_pixels,
        preflight.status,
        len(raw),
        len(collision_filtered),
        len(support_reachable),
        len(wedges),
        preflight.total_candidate_count,
    )


def m13b_fixed_frame_bounds(
    source_vertices: Sequence[tuple[float, float, float]],
    target_cells: Collection[core.GridPosition],
) -> dict[str, Bounds]:
    """Return M12C/M13B's fixed source-plus-grid projection bounds."""
    if not target_cells:
        raise AuditError("M13B fixed-frame bounds require target cells.")
    maximum = tuple(
        max(
            [vertex[axis] for vertex in source_vertices]
            + [float(max((cell.x, cell.y, cell.z)[axis] for cell in target_cells) + 1)]
        )
        for axis in range(3)
    )
    return {
        "front": (0.0, maximum[0], 0.0, maximum[2]),
        "side": (0.0, maximum[1], 0.0, maximum[2]),
        "top": (0.0, maximum[0], 0.0, maximum[1]),
    }


def _compare_masks(
    source: Image.Image, control: Image.Image, experiment: Image.Image
) -> MaskComparison:
    source_bytes = _mask_bytes(source)
    control_bytes = _mask_bytes(control)
    experiment_bytes = _mask_bytes(experiment)
    control_foreground = {index for index, value in enumerate(control_bytes) if value}
    experiment_foreground = {index for index, value in enumerate(experiment_bytes) if value}
    intersection = control_foreground & experiment_foreground
    union = control_foreground | experiment_foreground
    return MaskComparison(
        sha256(source_bytes).hexdigest(),
        sha256(control_bytes).hexdigest(),
        sha256(experiment_bytes).hexdigest(),
        len(control_foreground ^ experiment_foreground),
        len(control_foreground - experiment_foreground),
        len(experiment_foreground - control_foreground),
        len(intersection),
        len(union),
        1.0 if not union else round(len(intersection) / len(union), 6),
        control_bytes == experiment_bytes,
    )


def _mask_bytes(mask: Image.Image) -> bytes:
    if mask.size != (SILHOUETTE_RESOLUTION, SILHOUETTE_RESOLUTION):
        raise AuditError("M13C requires the frozen 128 by 128 raster resolution.")
    return bytes(bool(pixel) for pixel in mask.get_flattened_data())


def _validate_bounds(bounds: Mapping[str, Bounds]) -> None:
    if set(bounds) != set(VIEWS):
        raise AuditError("Frame metadata must contain all three projection bounds.")
    for view, value in bounds.items():
        if len(value) != 4 or value[0] >= value[1] or value[2] >= value[3]:
            raise AuditError(f"{view} has invalid projection bounds.")


def _fixed_source_counts(
    source_vertices: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    placements: Sequence[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
) -> dict[str, int]:
    from app.conversion.m12c_wedge_fidelity_experiment import _raster_pixels

    _, _, source = _raster_pixels(source_vertices, faces, (), placements, frozenset(target_cells))
    return {view: sum(pixel[0] == view for pixel in source) for view in VIEWS}


def _iou(true_positives: int, false_positives: int, source_foreground: int) -> float:
    denominator = source_foreground + false_positives
    return 1.0 if denominator == 0 else true_positives / denominator


def fixed_frame_parity_failures(
    actual_views: Mapping[str, Mapping[str, int]], actual_mean: float, saved: object
) -> tuple[str, ...]:
    if not isinstance(saved, Mapping) or not isinstance(saved.get("views"), list):
        return ("fixedFrame: missing required metric object",)
    expected = {item.get("view"): item for item in saved["views"] if isinstance(item, Mapping)}
    if set(expected) != set(VIEWS):
        return ("fixedFrame.views: expected front, side, and top records",)
    failures: list[str] = []
    for view in VIEWS:
        expected_view = expected[view]
        _compare_required_fields(
            failures,
            f"fixedFrame.{view}",
            expected_view,
            actual_views[view],
        )
        source_foreground = (
            actual_views[view]["truePositives"] + actual_views[view]["falseNegatives"]
        )
        actual_iou = _iou(
            actual_views[view]["truePositives"],
            actual_views[view]["falsePositives"],
            source_foreground,
        )
        _compare_required_fields(
            failures,
            f"fixedFrame.{view}",
            expected_view,
            {"iou": actual_iou},
        )
    _compare_required_fields(failures, "fixedFrame", saved, {"meanIou": actual_mean})
    return tuple(failures)


def frozen_silhouette_parity_failures(
    actual: SilhouetteComparison, expected: object
) -> tuple[str, ...]:
    """Compare M13B's frozen schema by meaning, not dictionary representation."""
    saved = _required_mapping(expected, "frozenSilhouetteV1")
    if saved is None:
        return ("frozenSilhouetteV1: missing required metric object",)
    failures: list[str] = []
    actual_views = {"front": actual.front, "side": actual.side, "top": actual.top}
    for view in VIEWS:
        saved_view = _required_mapping(saved.get(view), f"frozenSilhouetteV1.{view}")
        if saved_view is None:
            failures.append(f"frozenSilhouetteV1.{view}: missing required view metadata")
            continue
        actual_view = actual_views[view]
        _compare_required_fields(
            failures,
            f"frozenSilhouetteV1.{view}",
            saved_view,
            {
                "true_positives": actual_view.true_positives,
                "false_positives": actual_view.false_positives,
                "false_negatives": actual_view.false_negatives,
                "iou": actual_view.iou,
                "source_equals_lego": actual_view.source_equals_lego,
            },
        )
    _compare_required_fields(
        failures,
        "frozenSilhouetteV1",
        saved,
        {"mean_iou": actual.mean_iou, "source_equals_lego": actual.source_equals_lego},
    )
    return tuple(failures)


def shared_bounds_parity_failures(actual: ArrangementMetrics, expected: object) -> tuple[str, ...]:
    """Strictly compare M13B's shared frame and view metrics after normalization."""
    saved = _required_mapping(expected, "sharedBounds")
    if saved is None:
        return ("sharedBounds: missing required metric object",)
    failures: list[str] = []
    _compare_required_fields(failures, "sharedBounds", saved, {"frame": actual.frame})
    saved_bounds = _saved_bounds_with_failures(saved.get("bounds"), failures)
    actual_bounds = dict(actual.bounds)
    actual_views = {"front": actual.front, "side": actual.side, "top": actual.top}
    for view in VIEWS:
        if view not in saved_bounds:
            failures.append(f"sharedBounds.{view}.bounds: missing required bounds")
        elif saved_bounds[view] != actual_bounds[view]:
            failures.append(
                f"sharedBounds.{view}.bounds: expected {list(saved_bounds[view])!r}, "
                f"got {list(actual_bounds[view])!r}"
            )
        saved_view = _required_mapping(saved.get(view), f"sharedBounds.{view}")
        if saved_view is None:
            failures.append(f"sharedBounds.{view}: missing required view metrics")
            continue
        actual_view = actual_views[view]
        _compare_required_fields(
            failures,
            f"sharedBounds.{view}",
            saved_view,
            {
                "true_positives": actual_view.true_positives,
                "false_positives": actual_view.false_positives,
                "false_negatives": actual_view.false_negatives,
                "iou": actual_view.iou,
            },
        )
    if SILHOUETTE_RESOLUTION != 128:
        failures.append(f"sharedBounds.rasterResolution: expected 128, got {SILHOUETTE_RESOLUTION}")
    if VIEW_AXES != {"front": (0, 2), "side": (1, 2), "top": (0, 1)}:
        failures.append("sharedBounds.projectionSemantics: frozen XZ/YZ/XY mapping changed")
    return tuple(failures)


def _compare_required_fields(
    failures: list[str], path: str, expected: Mapping[str, object], actual: Mapping[str, object]
) -> None:
    for field, actual_value in actual.items():
        if field not in expected:
            failures.append(f"{path}.{field}: missing required metadata")
        elif expected[field] != actual_value:
            failures.append(f"{path}.{field}: expected {expected[field]!r}, got {actual_value!r}")


def _required_mapping(value: object, path: str) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return value


def _saved_bounds_with_failures(value: object, failures: list[str]) -> dict[str, Bounds]:
    if not isinstance(value, list):
        failures.append("sharedBounds.bounds: missing required frame metadata")
        return {}
    bounds: dict[str, Bounds] = {}
    for item in value:
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
            failures.append("sharedBounds.bounds: invalid frame metadata")
            continue
        values = item[1]
        if (
            not isinstance(values, list)
            or len(values) != 4
            or not all(isinstance(number, (int, float)) for number in values)
        ):
            failures.append(f"sharedBounds.{item[0]}.bounds: invalid frame metadata")
            continue
        if item[0] in bounds:
            failures.append(f"sharedBounds.{item[0]}.bounds: duplicate frame metadata")
            continue
        bounds[item[0]] = (
            float(values[0]),
            float(values[1]),
            float(values[2]),
            float(values[3]),
        )
    unexpected = set(bounds) - set(VIEWS)
    if unexpected:
        failures.append(f"sharedBounds.bounds: unexpected views {sorted(unexpected)!r}")
    return bounds


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError(f"Saved {name} must be a list of strings.")
    return value
