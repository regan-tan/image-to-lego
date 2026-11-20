from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

import pytest
import trimesh
from PIL import Image

from app.conversion import core
from app.conversion.benchmark import glb_bytes
from app.conversion.evaluation_alignment import evaluate_completed_assembly
from app.conversion.m13a_objective_alignment_audit import evaluate_shared_bounds
from app.conversion.m13c_silhouette_equivalence_audit import (
    AUDIT_RESULT_JSON_SCHEMA,
    AuditError,
    M13bPreprocessing,
    candidate_coverage_ceiling,
    candidate_preflight_failures,
    compare_mask_triplets,
    fixed_frame_parity_failures,
    frozen_silhouette_parity_failures,
    m13b_no_wedge_candidate_preflight,
    native_comparison_metadata,
    placement_comparison,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
    render_masks_in_bounds,
    shared_bounds_parity_failures,
    stage_b_allowed,
    verify_source_sha256,
)
from app.conversion.part_catalogue import PART_BY_ID

BOUNDS = {
    "front": (0.0, 2.0, 0.0, 2.0),
    "side": (0.0, 2.0, 0.0, 2.0),
    "top": (0.0, 2.0, 0.0, 2.0),
}
SOURCE_VERTICES = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
SOURCE_FACES = [(0, 1, 2)]


def _mask(*pixels: int) -> Image.Image:
    image = Image.new("1", (128, 128))
    for pixel in pixels:
        image.putpixel((pixel, 0), 1)
    return image


def _triplets(source: Image.Image, control: Image.Image, experiment: Image.Image):
    return (
        {view: (source, control) for view in BOUNDS},
        {view: (source, experiment) for view in BOUNDS},
    )


def _placement(x: int, y: int, z: int) -> core.BrickPlacement:
    return core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(x, y, z), 0)


def _historical_metrics() -> tuple[object, dict[str, object], object, dict[str, object]]:
    placements = (_placement(0, 0, 0),)
    frozen = evaluate_completed_assembly(SOURCE_VERTICES, SOURCE_FACES, placements)
    shared = evaluate_shared_bounds(SOURCE_VERTICES, SOURCE_FACES, placements, BOUNDS)
    saved_frozen = asdict(frozen)
    saved_shared = asdict(shared)
    saved_shared["bounds"] = [[view, list(bounds)] for view, bounds in shared.bounds]
    return frozen, saved_frozen, shared, saved_shared


def test_saved_placement_id_reconstructs_without_loss() -> None:
    placement_ids = ["3024@0,1,2:0", "3024@1,0,2:90"]

    placements = reconstruct_placements(placement_ids)

    assert [item.brick_type.part_id for item in placements] == ["3024", "3024"]
    assert [item.position for item in placements] == [
        core.GridPosition(0, 1, 2),
        core.GridPosition(1, 0, 2),
    ]
    assert [item.orientation_degrees for item in placements] == [0, 90]
    assert placement_comparison(placements, placements)["identicalPlacementMultiset"] is True


def test_result_schema_requires_audit_evidence_fields() -> None:
    assert AUDIT_RESULT_JSON_SCHEMA["required"] == [
        "schemaVersion",
        "stageA",
        "candidateCeiling",
        "records",
    ]


def test_invalid_placement_id_is_rejected() -> None:
    with pytest.raises(AuditError, match="unknown catalogue part"):
        reconstruct_placements(["not-a-part@0,0,0:0"])


def test_incorrect_source_sha_is_rejected() -> None:
    with pytest.raises(AuditError, match="does not match"):
        verify_source_sha256(b"synthetic-source", "0" * 64)


def test_historical_m13b_metric_schema_passes_semantic_parity() -> None:
    frozen, saved_frozen, shared, saved_shared = _historical_metrics()

    assert frozen_silhouette_parity_failures(frozen, saved_frozen) == ()
    assert shared_bounds_parity_failures(shared, saved_shared) == ()


def test_extra_harmless_serialization_metadata_is_normalized() -> None:
    frozen, saved_frozen, shared, saved_shared = _historical_metrics()
    saved_frozen["serializer"] = "historical-m13b"
    saved_shared["serializer"] = "historical-m13b"

    assert frozen_silhouette_parity_failures(frozen, saved_frozen) == ()
    assert shared_bounds_parity_failures(shared, saved_shared) == ()


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("true_positives", 999),
        ("false_positives", 999),
        ("false_negatives", 999),
        ("iou", 0.123456),
    ],
)
def test_frozen_metric_mismatches_report_the_exact_field(
    field: str, bad_value: int | float
) -> None:
    frozen, saved_frozen, _, _ = _historical_metrics()
    changed = deepcopy(saved_frozen)
    changed["front"][field] = bad_value

    failures = frozen_silhouette_parity_failures(frozen, changed)

    assert any(f"frozenSilhouetteV1.front.{field}:" in failure for failure in failures)


def test_frozen_mean_iou_mismatch_reports_the_exact_field() -> None:
    frozen, saved_frozen, _, _ = _historical_metrics()
    changed = deepcopy(saved_frozen)
    changed["mean_iou"] = 0.123456

    assert frozen_silhouette_parity_failures(frozen, changed) == (
        f"frozenSilhouetteV1.mean_iou: expected 0.123456, got {frozen.mean_iou}",
    )


def test_shared_bounds_mismatch_reports_the_exact_field() -> None:
    _, _, shared, saved_shared = _historical_metrics()
    changed = deepcopy(saved_shared)
    changed["bounds"][0][1][0] = -1.0

    failures = shared_bounds_parity_failures(shared, changed)

    assert any("sharedBounds.front.bounds:" in failure for failure in failures)


def test_missing_shared_frame_metadata_fails_closed() -> None:
    _, _, shared, saved_shared = _historical_metrics()
    changed = deepcopy(saved_shared)
    del changed["frame"]

    assert shared_bounds_parity_failures(shared, changed) == (
        "sharedBounds.frame: missing required metadata",
    )


def test_fixed_frame_mismatch_reports_the_exact_field() -> None:
    failures = fixed_frame_parity_failures(
        {view: {"truePositives": 1, "falsePositives": 2, "falseNegatives": 3} for view in BOUNDS},
        0.25,
        {
            "meanIou": 0.25,
            "views": [
                {
                    "view": view,
                    "truePositives": 1,
                    "falsePositives": 2,
                    "falseNegatives": 4,
                    "iou": 0.1,
                }
                for view in BOUNDS
            ],
        },
    )

    assert any("fixedFrame.front.falseNegatives:" in failure for failure in failures)


def test_identical_placements_produce_identical_masks() -> None:
    placements = (_placement(0, 0, 0),)
    masks = render_masks_in_bounds(SOURCE_VERTICES, SOURCE_FACES, placements, BOUNDS)

    result = compare_mask_triplets(masks, masks, BOUNDS)

    assert all(item["exactly_identical"] is True for item in result.values())
    assert all(item["xor_pixels"] == 0 for item in result.values())


def test_different_arrangements_can_have_identical_three_view_silhouettes() -> None:
    control = tuple(
        _placement(x, y, z)
        for x in range(2)
        for y in range(2)
        for z in range(2)
        if (x + y + z) % 2 == 0
    )
    experiment = tuple(
        _placement(x, y, z)
        for x in range(2)
        for y in range(2)
        for z in range(2)
        if (x + y + z) % 2 == 1
    )
    control_masks = render_masks_in_bounds(SOURCE_VERTICES, SOURCE_FACES, control, BOUNDS)
    experiment_masks = render_masks_in_bounds(SOURCE_VERTICES, SOURCE_FACES, experiment, BOUNDS)

    result = compare_mask_triplets(control_masks, experiment_masks, BOUNDS)

    assert placement_comparison(control, experiment)["identicalPlacementMultiset"] is False
    assert all(item["exactly_identical"] is True for item in result.values())


def test_different_masks_can_have_equal_tp_fp_fn() -> None:
    source = _mask(0, 1)
    control = _mask(0, 2)
    experiment = _mask(1, 2)
    control_masks, experiment_masks = _triplets(source, control, experiment)

    result = compare_mask_triplets(control_masks, experiment_masks, BOUNDS)

    assert all(item["xor_pixels"] == 2 for item in result.values())
    assert all(item["exactly_identical"] is False for item in result.values())


def test_xor_accounting_hashes_and_exact_equality_agree() -> None:
    source = _mask(0)
    control_masks, experiment_masks = _triplets(source, _mask(0, 1), _mask(0, 2))

    result = compare_mask_triplets(control_masks, experiment_masks, BOUNDS)

    assert all(
        item["control_only_pixels"] + item["experiment_only_pixels"] == item["xor_pixels"]
        for item in result.values()
    )
    assert all(item["control_sha256"] != item["experiment_sha256"] for item in result.values())


def test_source_masks_incompatible_shared_frame_are_rejected() -> None:
    control_masks, experiment_masks = _triplets(_mask(0), _mask(0), _mask(0))
    experiment_masks = {view: (_mask(1), lego) for view, (_, lego) in experiment_masks.items()}

    with pytest.raises(AuditError, match="source masks differ"):
        compare_mask_triplets(control_masks, experiment_masks, BOUNDS)


def test_mismatched_frame_metadata_is_rejected() -> None:
    masks, duplicate = _triplets(_mask(0), _mask(0), _mask(0))

    with pytest.raises(AuditError, match="invalid projection bounds"):
        compare_mask_triplets(masks, duplicate, {**BOUNDS, "front": (1.0, 0.0, 0.0, 1.0)})


def test_native_and_shared_frames_are_not_silently_conflated() -> None:
    control = (_placement(0, 0, 0),)
    experiment = (_placement(0, 0, 1),)

    result = native_comparison_metadata(SOURCE_VERTICES, SOURCE_FACES, control, experiment)

    assert result["boundsIdentical"] is False
    assert result["pixelComparison"] == "not-performed-different-native-bounds"


def test_candidate_union_ceiling_counts_coverage_uncoverable_and_locked_false_positives() -> None:
    source = {("front", 0, 0), ("front", 1, 0), ("front", 2, 0)}
    locked = {("front", 0, 0), ("front", 9, 0)}
    candidates = ({("front", 1, 0), ("front", 2, 0)}, {("front", 1, 0)})

    result = candidate_coverage_ceiling(
        source, locked, candidates, {view: 0.5 for view in BOUNDS}, BOUNDS
    )
    front = result["views"]["front"]

    assert front["sourcePixelsCoverableByCandidateOrLockedUnion"] == 3
    assert front["sourcePixelsNotCoverable"] == 0
    assert front["lockedOnlyFalsePositivePixels"] == 1
    assert front["optimisticIouUpperBound"] == 0.75


def test_candidate_union_does_not_double_count_overlapping_pixels() -> None:
    pixel = ("front", 0, 0)

    result = candidate_coverage_ceiling(
        {pixel}, (), ({pixel}, {pixel}), {view: 0.0 for view in BOUNDS}, BOUNDS
    )

    assert result["views"]["front"]["truePositiveUpperBound"] == 1


def test_candidate_ceiling_uses_the_declared_empty_mask_convention() -> None:
    result = candidate_coverage_ceiling((), (), (), {view: 0.0 for view in BOUNDS}, BOUNDS)

    assert result["views"]["front"]["optimisticIouUpperBound"] == 1.0
    assert "denominator is zero" in result["emptyMaskConvention"]


def test_candidate_ceiling_preserves_fixed_projection_frame_provenance() -> None:
    result = candidate_coverage_ceiling((), (), (), {view: 0.0 for view in BOUNDS}, BOUNDS)

    assert result["views"]["front"]["frame"] == {
        "bounds": [0.0, 2.0, 0.0, 2.0],
        "rasterWidth": 128,
        "rasterHeight": 128,
        "projection": "XZ",
    }


def test_candidate_preflight_count_mismatch_fails_closed() -> None:
    failures = candidate_preflight_failures(1, (), (_placement(0, 0, 0),))

    assert any("Candidate count mismatch" in failure for failure in failures)
    assert any(
        "absent from the reconstructed eligible candidate set" in failure for failure in failures
    )


def test_stage_a_parity_failure_blocks_stage_b() -> None:
    assert stage_b_allowed({"passed": True}, {"passed": False}) is False


def test_relaxed_ceiling_is_not_lower_than_an_eligible_observed_selection() -> None:
    source = {("front", 0, 0), ("front", 1, 0)}
    result = candidate_coverage_ceiling(
        source,
        (),
        ({("front", 0, 0)}, {("front", 1, 0)}),
        {"front": 0.5, "side": 0.0, "top": 0.0},
        BOUNDS,
    )

    assert result["views"]["front"]["optimisticIouUpperBound"] >= 0.5


def test_preprocessing_does_not_invoke_a_cp_sat_solve(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.conversion.surface_grid_v4 as surface_grid_v4

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("Stage B preprocessing must not call solve_surface_grid_v4.")

    monkeypatch.setattr(surface_grid_v4, "solve_surface_grid_v4", fail_if_called)

    preprocessing = reconstruct_m13b_preprocessing(
        glb_bytes(trimesh.creation.box()), core.GridSize(2, 2, 3), core.Axis.Y
    )

    assert preprocessing.target_cells


def test_ready_combined_preflight_allows_eligible_wedges_for_no_wedge_audit() -> None:
    preprocessing = M13bPreprocessing(
        [],
        [],
        frozenset(core.GridPosition(x, y, 0) for x in range(5) for y in range(5)),
        frozenset(),
        frozenset(),
        (),
    )

    preflight = m13b_no_wedge_candidate_preflight(preprocessing, ())

    assert preflight.status == "READY"
    assert preflight.eligible_wedge_count > 0
    assert preflight.candidate_rasters is not None


def test_candidate_limit_exhaustion_returns_diagnostics_without_a_ceiling() -> None:
    target = frozenset(
        core.GridPosition(x, y, z) for x in range(10) for y in range(10) for z in range(10)
    )
    preprocessing = M13bPreprocessing([], [], target, frozenset(), frozenset(), ())

    preflight = m13b_no_wedge_candidate_preflight(preprocessing, ())

    assert preflight.status == "CANDIDATE_LIMIT_EXHAUSTED"
    assert preflight.combined_candidate_count > 4_000
    assert preflight.candidate_rasters is None
