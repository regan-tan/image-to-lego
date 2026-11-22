"""Exact incidence-compressed coverage encoding for the offline M13E-B3.3 study.

This module deliberately leaves :mod:`m13e_duck_iou_dominance` unchanged.  It
uses the same candidate variables and historical constraints, but replaces one
coverage Boolean per raster pixel with one Boolean per equal candidate-incidence
set.  A group Boolean is the OR of precisely the candidates covering every
pixel in that group; view-specific foreground/background multiplicities then
recover the original TP and FP counts exactly.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from ortools.sat.python import cp_model

from app.conversion import core
from app.conversion.fidelity import SILHOUETTE_RESOLUTION
from app.conversion.m12c_wedge_fidelity_experiment import (
    _add_locked_support,
    _add_mandatory_coverage,
    _add_rectangular_nonoverlap,
    _add_verified_support,
)
from app.conversion.m13d_tp_fp_feasibility_experiment import VIEWS, _validated_selection_ids
from app.conversion.m13e_duck_iou_dominance import (
    IoUDominanceModel,
    ModelComponentCount,
    Pixel,
    _add_iou_change_threshold,
    _validate_control_inputs,
    _validate_iou_threshold_coefficient_bounds,
    _validated_iou_change_basis_points,
    dominance_values,
)
from app.conversion.surface_grid_v4 import _Candidate


@dataclass(frozen=True, slots=True)
class IncidenceGroup:
    """Pixels with the same non-empty candidate coverage OR."""

    candidate_ids: tuple[int, ...]
    tp_weights: Mapping[str, int]
    fp_weights: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class IncidenceCompression:
    """The lossless grouping and its fixed-frame accounting constants."""

    groups: tuple[IncidenceGroup, ...]
    locked_tp: Mapping[str, int]
    locked_fp: Mapping[str, int]
    permanently_uncovered_tp: Mapping[str, int]
    permanently_uncovered_fp: Mapping[str, int]
    touchable_pixel_count: int
    candidate_reference_count: int


@dataclass(frozen=True, slots=True)
class StaticModelStatistics:
    """Comparable representation measurements, obtained without solving."""

    candidate_selection_variables: int
    coverage_variables: int
    max_equalities: int
    max_equality_candidate_references: int
    total_variables: int
    total_constraints: int
    model_bytes: int
    distinct_incidence_signatures: int
    group_weight_totals: Mapping[str, Mapping[str, int]]


def build_incidence_compression(
    candidate_rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
) -> IncidenceCompression:
    """Group every non-locked, candidate-touchable pixel by its exact OR inputs."""
    source = frozenset(source_pixels)
    locked = frozenset(locked_pixels)
    _validate_pixels(source | locked)
    by_pixel: dict[Pixel, set[int]] = defaultdict(set)
    for candidate_id, raster in enumerate(candidate_rasters):
        for pixel in frozenset(raster):
            _validate_pixels((pixel,))
            if pixel not in locked:
                by_pixel[pixel].add(candidate_id)

    grouped: dict[tuple[int, ...], list[Pixel]] = defaultdict(list)
    for pixel, candidate_ids in by_pixel.items():
        if candidate_ids:
            grouped[tuple(sorted(candidate_ids))].append(pixel)
    groups = tuple(
        IncidenceGroup(
            candidate_ids=signature,
            tp_weights={
                view: sum(pixel[0] == view and pixel in source for pixel in pixels)
                for view in VIEWS
            },
            fp_weights={
                view: sum(pixel[0] == view and pixel not in source for pixel in pixels)
                for view in VIEWS
            },
        )
        for signature, pixels in sorted(grouped.items())
    )
    covered = frozenset(by_pixel)
    return IncidenceCompression(
        groups=groups,
        locked_tp={
            view: sum(pixel[0] == view and pixel in source for pixel in locked) for view in VIEWS
        },
        locked_fp={
            view: sum(pixel[0] == view and pixel not in source for pixel in locked)
            for view in VIEWS
        },
        permanently_uncovered_tp={
            view: sum(pixel[0] == view for pixel in source - locked - covered) for view in VIEWS
        },
        permanently_uncovered_fp={view: 0 for view in VIEWS},
        touchable_pixel_count=len(covered),
        candidate_reference_count=sum(len(ids) for ids in by_pixel.values()),
    )


def build_compressed_iou_dominance_model(
    *,
    candidates: Sequence[_Candidate],
    candidate_rasters: Sequence[Collection[Pixel]],
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    required_pixels: Collection[Pixel],
    locked_placements: Collection[core.BrickPlacement],
    target_cells: Collection[core.GridPosition],
    fixed_coverage_pixels: Collection[Pixel],
    control_views: Mapping[str, Mapping[str, int]],
    max_parts: int,
    required_selected_ids: Collection[int] | None = None,
    require_strict_improvement: bool = True,
    strict_view: str | None = None,
    iou_change_basis_points: Mapping[str, int] | None = None,
    enforce_iou_constraints: bool = True,
    enforce_mandatory_coverage: bool = True,
) -> tuple[IoUDominanceModel, IncidenceCompression]:
    """Build the B3 model with its pixel coverage representation compressed exactly."""
    if len(candidates) != len(candidate_rasters):
        raise ValueError("Candidates and raster footprints must have matching lengths.")
    if not target_cells:
        raise ValueError("Target cells cannot be empty.")
    if strict_view is not None and strict_view not in VIEWS:
        raise ValueError("The strict view must be one of the fixed-frame views.")
    if strict_view is not None and (not require_strict_improvement or not enforce_iou_constraints):
        raise ValueError("A strict view requires strict improvement.")
    thresholds = _validated_iou_change_basis_points(iou_change_basis_points)
    if thresholds is not None and (
        require_strict_improvement or strict_view is not None or not enforce_iou_constraints
    ):
        raise ValueError("IoU thresholds cannot be combined with B3 dominance constraints.")
    source = frozenset(source_pixels)
    source_foreground = {view: sum(pixel[0] == view for pixel in source) for view in VIEWS}
    _validate_control_inputs(source_foreground, control_views)
    if thresholds is not None:
        _validate_iou_threshold_coefficient_bounds(source_foreground, control_views, thresholds)
    compression = build_incidence_compression(candidate_rasters, source, locked_pixels)
    _validate_compression(compression, source, locked_pixels, candidate_rasters)

    model = cp_model.CpModel()
    counts: dict[str, ModelComponentCount] = {}

    def counted(name: str, action: object) -> None:
        before = _model_size(model)
        assert callable(action)
        action()
        after = _model_size(model)
        counts[name] = ModelComponentCount(after[0] - before[0], after[1] - before[1])

    selected = tuple(model.new_bool_var(f"x_{index}") for index in range(len(candidates)))
    counts["candidate_selection_variables"] = ModelComponentCount(len(selected), 0)
    required_ids = _validated_selection_ids(
        required_selected_ids, len(selected), "required candidate selection"
    )
    if required_ids is None:
        counts["required_candidate_selection"] = ModelComponentCount(0, 0)
    else:
        counted(
            "required_candidate_selection",
            lambda: [
                model.add(variable == int(index in required_ids))
                for index, variable in enumerate(selected)
            ],
        )
    candidate_tuple, locked, target = (
        tuple(candidates),
        tuple(locked_placements),
        frozenset(target_cells),
    )
    counted(
        "rectangular_nonoverlap",
        lambda: _add_rectangular_nonoverlap(model, selected, candidate_tuple, target),
    )
    counted(
        "verified_support",
        lambda: _add_verified_support(
            model, selected, candidate_tuple, locked, min(cell.z for cell in target)
        ),
    )
    counted(
        "locked_support",
        lambda: _add_locked_support(
            model, selected, candidate_tuple, locked, min(cell.z for cell in target)
        ),
    )
    if enforce_mandatory_coverage:
        counted(
            "mandatory_coverage",
            lambda: _add_mandatory_coverage(
                model,
                selected,
                candidate_tuple,
                tuple(sorted(set(required_pixels) - set(fixed_coverage_pixels))),
            ),
        )
    else:
        counts["mandatory_coverage"] = ModelComponentCount(0, 0)
    counted("part_cap", lambda: model.add(sum(selected) <= max_parts - len(locked)))

    before = _model_size(model)
    coverage = tuple(
        model.new_bool_var(f"covered_group_{index}") for index in range(len(compression.groups))
    )
    after = _model_size(model)
    counts["coverage_variables"] = ModelComponentCount(after[0] - before[0], after[1] - before[1])
    counted(
        "coverage_max_equalities",
        lambda: [
            model.add_max_equality(variable, [selected[index] for index in group.candidate_ids])
            for group, variable in zip(compression.groups, coverage, strict=True)
        ],
    )
    tp_by_view: dict[str, cp_model.LinearExpr] = {}
    fp_by_view: dict[str, cp_model.LinearExpr] = {}
    dominance: dict[str, cp_model.LinearExpr] = {}
    before = _model_size(model)
    for view in VIEWS:
        tp = cp_model.LinearExpr.Sum(
            [
                compression.locked_tp[view],
                *[
                    group.tp_weights[view] * variable
                    for group, variable in zip(compression.groups, coverage, strict=True)
                ],
            ]
        )
        fp = cp_model.LinearExpr.Sum(
            [
                compression.locked_fp[view],
                *[
                    group.fp_weights[view] * variable
                    for group, variable in zip(compression.groups, coverage, strict=True)
                ],
            ]
        )
        baseline = control_views[view]
        value = (source_foreground[view] + baseline["falsePositives"]) * tp - baseline[
            "truePositives"
        ] * (source_foreground[view] + fp)
        if enforce_iou_constraints:
            if thresholds is None:
                model.add(value >= 0)
            else:
                _add_iou_change_threshold(
                    model, tp, fp, source_foreground[view], baseline, thresholds[view]
                )
        tp_by_view[view], fp_by_view[view], dominance[view] = tp, fp, value
    after = _model_size(model)
    counts["non_strict_per_view_dominance"] = ModelComponentCount(
        after[0] - before[0], after[1] - before[1]
    )
    if strict_view is not None:
        counted("strict_dominance", lambda: model.add(dominance[strict_view] >= 1))
    elif require_strict_improvement and enforce_iou_constraints:
        counted(
            "strict_dominance",
            lambda: model.add(cp_model.LinearExpr.Sum(list(dominance.values())) >= 1),
        )
    else:
        counts["strict_dominance"] = ModelComponentCount(0, 0)
    return IoUDominanceModel(
        model, selected, tp_by_view, fp_by_view, dominance, source_foreground, counts
    ), compression


def evaluate_compressed_metrics(
    compression: IncidenceCompression,
    selected_ids: Collection[int],
    source_foreground: Mapping[str, int],
    control_views: Mapping[str, Mapping[str, int]],
) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """Evaluate the compressed formulas directly for an arbitrary assignment."""
    selected = frozenset(selected_ids)
    views: dict[str, dict[str, int]] = {}
    for view in VIEWS:
        tp = compression.locked_tp[view] + sum(
            group.tp_weights[view]
            for group in compression.groups
            if selected.intersection(group.candidate_ids)
        )
        fp = compression.locked_fp[view] + sum(
            group.fp_weights[view]
            for group in compression.groups
            if selected.intersection(group.candidate_ids)
        )
        views[view] = {
            "truePositives": tp,
            "falsePositives": fp,
            "falseNegatives": source_foreground[view] - tp,
        }
    return views, dominance_values(views, source_foreground, control_views)


def static_model_statistics(
    built: IoUDominanceModel, compression: IncidenceCompression
) -> StaticModelStatistics:
    """Measure an un-solved CP-SAT model and its incidence accounting."""
    proto = built.model.proto
    return StaticModelStatistics(
        candidate_selection_variables=built.component_counts[
            "candidate_selection_variables"
        ].variables,
        coverage_variables=built.component_counts["coverage_variables"].variables,
        max_equalities=built.component_counts["coverage_max_equalities"].constraints,
        max_equality_candidate_references=sum(
            len(group.candidate_ids) for group in compression.groups
        ),
        total_variables=len(proto.variables),
        total_constraints=len(proto.constraints),
        model_bytes=model_byte_size(built.model),
        distinct_incidence_signatures=len(compression.groups),
        group_weight_totals={
            view: {
                "truePositives": sum(group.tp_weights[view] for group in compression.groups),
                "falsePositives": sum(group.fp_weights[view] for group in compression.groups),
            }
            for view in VIEWS
        },
    )


def _validate_compression(
    compression: IncidenceCompression,
    source_pixels: Collection[Pixel],
    locked_pixels: Collection[Pixel],
    candidate_rasters: Sequence[Collection[Pixel]],
) -> None:
    """Fail closed unless every compressed constant and group is exact.

    Locked pixels have constant coverage.  The reference encoding omits them
    from candidate OR variables even when a candidate raster also contains
    them, so their foreground and background counts must be validated against
    the unique locked union before candidate-dependent pixels are grouped.
    """
    source = frozenset(source_pixels)
    locked = frozenset(locked_pixels)
    _validate_pixels(source | locked)
    by_pixel: dict[Pixel, set[int]] = defaultdict(set)
    for candidate_id, raster in enumerate(candidate_rasters):
        for pixel in frozenset(raster):
            _validate_pixels((pixel,))
            if pixel not in locked:
                by_pixel[pixel].add(candidate_id)

    grouped: dict[tuple[int, ...], list[Pixel]] = defaultdict(list)
    for pixel, candidate_ids in by_pixel.items():
        if candidate_ids:
            grouped[tuple(sorted(candidate_ids))].append(pixel)
    expected_groups = tuple(
        IncidenceGroup(
            candidate_ids=signature,
            tp_weights={
                view: sum(pixel[0] == view and pixel in source for pixel in pixels)
                for view in VIEWS
            },
            fp_weights={
                view: sum(pixel[0] == view and pixel not in source for pixel in pixels)
                for view in VIEWS
            },
        )
        for signature, pixels in sorted(grouped.items())
    )
    if compression.groups != expected_groups:
        raise ValueError(
            "Compressed candidate-incidence groups do not match the non-locked raster pixels."
        )
    expected_touchable = len(by_pixel)
    if compression.touchable_pixel_count != expected_touchable:
        raise ValueError(
            "Compressed touchable-pixel count failed: "
            f"expected {expected_touchable}, got {compression.touchable_pixel_count}."
        )
    expected_references = sum(len(candidate_ids) for candidate_ids in by_pixel.values())
    if compression.candidate_reference_count != expected_references:
        raise ValueError(
            "Compressed candidate-reference count failed: "
            f"expected {expected_references}, got {compression.candidate_reference_count}."
        )
    for view in VIEWS:
        expected_locked_tp = sum(pixel[0] == view and pixel in source for pixel in locked)
        expected_locked_fp = sum(pixel[0] == view and pixel not in source for pixel in locked)
        if compression.locked_tp[view] != expected_locked_tp:
            raise ValueError(
                f"Compressed locked foreground accounting failed for {view}: "
                f"expected {expected_locked_tp}, got {compression.locked_tp[view]}."
            )
        if compression.locked_fp[view] != expected_locked_fp:
            raise ValueError(
                f"Compressed locked background accounting failed for {view}: "
                f"expected {expected_locked_fp}, got {compression.locked_fp[view]}."
            )
        expected_permanently_uncovered_tp = sum(
            pixel[0] == view for pixel in source - locked - frozenset(by_pixel)
        )
        if compression.permanently_uncovered_tp[view] != expected_permanently_uncovered_tp:
            raise ValueError(
                f"Compressed permanently uncovered foreground accounting failed for {view}: "
                f"expected {expected_permanently_uncovered_tp}, "
                f"got {compression.permanently_uncovered_tp[view]}."
            )
        if compression.permanently_uncovered_fp[view] != 0:
            raise ValueError(
                f"Compressed permanently uncovered background accounting failed for {view}: "
                f"expected 0, got {compression.permanently_uncovered_fp[view]}."
            )
        accounted_tp = (
            compression.locked_tp[view]
            + compression.permanently_uncovered_tp[view]
            + sum(group.tp_weights[view] for group in compression.groups)
        )
        source_foreground = sum(pixel[0] == view for pixel in source)
        if accounted_tp != source_foreground:
            raise ValueError(
                f"Compressed foreground accounting failed for {view}: "
                f"expected {source_foreground}, got {accounted_tp}."
            )


def _validate_pixels(pixels: Collection[Pixel]) -> None:
    if any(pixel[0] not in VIEWS for pixel in pixels):
        raise ValueError("Raster pixels must use one of the fixed-frame views.")
    if any(
        pixel[1] < 0
        or pixel[1] >= SILHOUETTE_RESOLUTION
        or pixel[2] < 0
        or pixel[2] >= SILHOUETTE_RESOLUTION
        for pixel in pixels
    ):
        raise ValueError("Raster pixels must remain inside the fixed-frame bounds.")


def _model_size(model: cp_model.CpModel) -> tuple[int, int]:
    return len(model.proto.variables), len(model.proto.constraints)


def model_byte_size(model: cp_model.CpModel) -> int:
    """Use OR-Tools' binary export because its wrapped proto has no public serializer."""
    with TemporaryDirectory(prefix="m13e-compressed-model-") as temporary_directory:
        path = Path(temporary_directory) / "model.pb"
        if not model.export_to_file(str(path)):
            raise OSError("OR-Tools did not export the CP-SAT model.")
        return path.stat().st_size


def model_proto_sha256(model: cp_model.CpModel) -> str:
    """Hash the binary encoding of a constructed model without invoking CP-SAT."""
    with TemporaryDirectory(prefix="m13e-compressed-model-") as temporary_directory:
        path = Path(temporary_directory) / "model.pb"
        if not model.export_to_file(str(path)):
            raise OSError("OR-Tools did not export the CP-SAT model.")
        return sha256(path.read_bytes()).hexdigest()
