"""Run the opt-in, matched M13F 50%-occupancy validation for one non-Duck case.

This is deliberately an offline research tool.  It reconstructs the historical
M13B inputs from the SHA-pinned corpus and never changes production conversion.
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core
from app.conversion.evaluation_alignment import evaluate_completed_assembly, stable_placement_id
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage
from app.conversion.m12c_wedge_fidelity_experiment import (
    fixed_frame_score,
    validate_completed_arrangement,
)
from app.conversion.m13c_silhouette_equivalence_audit import (
    AuditError,
    M13bPreprocessing,
    m13b_fixed_frame_bounds,
    m13b_no_wedge_candidate_preflight,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
)
from app.conversion.m13d_tp_fp_feasibility_experiment import validate_view_metrics
from app.conversion.m13e_duck_cross_view_tradeoff import fixed_frame_mean_iou_fraction
from app.conversion.m13e_duck_iou_dominance import (
    model_fingerprint,
    solve_built_iou_dominance_model,
)
from app.conversion.m13e_duck_iou_incidence_compression import (
    build_compressed_iou_dominance_model,
    model_proto_sha256,
)
from app.conversion.m13e_duck_mean_iou_guided import (
    LinearizedMeanIouObjective,
    add_linearized_mean_iou_objective,
    linearized_mean_iou_objective,
    surrogate_value,
)
from app.conversion.m13f_duck_coarse_budget_frontier import (
    CoarseRequirement,
    count_unmet_coarse_requirements,
    historical_coarse_requirements,
)
from app.conversion.m13f_duck_occupancy_coverage_ablation import (
    CoveragePolicy,
    occupancy_requirements,
    requirement_set_sha256,
    requirements_for_policy,
)
from app.conversion.real_world_benchmark import load_manifest, verify_case_source
from app.conversion.surface_grid_v4 import _Candidate
from scripts.run_m13d_tp_fp_feasibility import _mask_parity, _source_foreground_by_view

CASE_IDS = ("mansion", "realistic-man")
SUMMARY_NAMES = {"mansion": "m13b-mansion-pilot", "realistic-man": "m13b-man-final"}
POLICIES = (
    CoveragePolicy("historical", Fraction(0)),
    CoveragePolicy("source-occupancy-ge-50-percent", Fraction(1, 2)),
    CoveragePolicy("fully-relaxed", None),
)
SCHEMA_VERSION = "m13f-cross-object-validation-v1"
CHECKPOINT_FILENAME = "PRIVATE_UNVALIDATED_CHECKPOINT.json"
DETERMINISTIC_TIME_LIMIT_SECONDS = 30.0


@dataclass(frozen=True)
class PreparedCase:
    case_id: str
    source: bytes
    grid: core.GridSize
    max_parts: int
    preprocessing: M13bPreprocessing
    candidates: tuple[_Candidate, ...]
    candidate_rasters: tuple[frozenset[tuple[str, int, int]], ...]
    source_pixels: frozenset[tuple[str, int, int]]
    locked_pixels: frozenset[tuple[str, int, int]]
    locked: tuple[core.BrickPlacement, ...]
    requirements: tuple[CoarseRequirement, ...]
    fixed_coverage: frozenset[tuple[str, int, int]]
    control_views: dict[str, dict[str, int]]
    source_counts: dict[str, int]
    base_fingerprint: str


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--case", choices=CASE_IDS, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--m13b-summary",
        type=Path,
        help="Override the matching private M13B summary for the selected case.",
    )
    args = parser.parse_args()
    summary = args.m13b_summary or _default_summary(args.manifest, args.case)
    try:
        prepared = prepare_case(args.manifest, args.case, summary)
        payload = preflight_payload(prepared)
        if args.preflight:
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.output_dir.exists() and not args.resume:
            parser.error("Refusing to overwrite an existing private experiment directory.")
        payload = solve_case(prepared, args.output_dir, args.resume)
        write_json_atomically(args.output_dir / "summary.json", payload)
        return 0
    except (AuditError, OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps({"schemaVersion": SCHEMA_VERSION, "status": "BLOCKED", "reason": str(error)})
        )
        return 1


def _default_summary(manifest: Path, case_id: str) -> Path:
    return manifest.parent.parent / SUMMARY_NAMES[case_id] / "summary.json"


def prepare_case(manifest_path: Path, case_id: str, summary_path: Path) -> PreparedCase:
    """Rebuild the actual historical no-wedge candidate universe without solving."""
    cases = {case.case_id: case for case in load_manifest(manifest_path).cases}
    if case_id not in cases or case_id not in CASE_IDS:
        raise AuditError("The selected case is not a supported non-Duck validation case.")
    record = _record(summary_path, case_id)
    config = _mapping(record.get("configuration"), "configuration")
    if config.get("wedge41769aEnabled") is not False or config.get("sourceEvidenceResolution") != 1:
        raise AuditError("M13F requires the M13B no-wedge, resolution-one configuration.")
    grid_data = _mapping(config.get("grid"), "configuration.grid")
    grid = core.GridSize(**{key: _integer(grid_data.get(key), key) for key in grid_data})
    max_parts = _integer(config.get("maxParts"), "configuration.maxParts")
    source = verify_case_source(cases[case_id])
    if sha256(source).hexdigest() != record.get("sourceSha256"):
        raise AuditError("The manifest source SHA-256 does not match the M13B record.")
    preprocessing = reconstruct_m13b_preprocessing(source, grid, cases[case_id].up_axis)
    control = reconstruct_placements(
        _strings(
            _mapping(record.get("control"), "control").get("placementIds"), "control.placementIds"
        )
    )
    locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
    expected_locked = tuple(
        stable_placement_id(item) for item in preprocessing.initial_locked_slope_placements
    )
    if tuple(stable_placement_id(item) for item in locked) != expected_locked:
        raise AuditError("Historical locked placements do not match reconstructed preprocessing.")
    candidate_preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
    if candidate_preflight.status != "READY" or any(
        value is None
        for value in (
            candidate_preflight.candidate_rasters,
            candidate_preflight.source_pixels,
            candidate_preflight.locked_pixels,
        )
    ):
        raise AuditError(
            "The general no-wedge candidate generator did not produce complete rasters."
        )
    assert candidate_preflight.candidate_rasters is not None
    assert candidate_preflight.source_pixels is not None
    assert candidate_preflight.locked_pixels is not None
    if config.get("candidateCount") != len(candidate_preflight.candidates):
        raise AuditError("Reconstructed candidate count differs from the M13B record.")
    candidate_ids = {stable_placement_id(item.placement) for item in candidate_preflight.candidates}
    if any(
        stable_placement_id(item) not in candidate_ids
        for item in control
        if item.brick_type.shape == "rectangular"
    ):
        raise AuditError(
            "A historical rectangular placement is absent from the candidate universe."
        )
    source_pixels = frozenset(candidate_preflight.source_pixels)
    locked_pixels = frozenset(candidate_preflight.locked_pixels)
    source_counts = _source_foreground_by_view(source_pixels)
    saved_views = _views(_mapping(record["control"], "control"))
    rendered = fixed_frame_score(
        preprocessing.source_vertices, preprocessing.faces, control, preprocessing.target_cells
    )
    actual_views = {
        item.view: {
            "truePositives": item.true_positives,
            "falsePositives": item.false_positives,
            "falseNegatives": source_counts[item.view] - item.true_positives,
        }
        for item in rendered.views
    }
    if actual_views != saved_views:
        raise AuditError("Historical fixed-frame control metrics do not reproduce exactly.")
    fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels
    requirements = historical_coarse_requirements(
        candidates=candidate_preflight.candidates,
        required_pixels=preprocessing.required_pixels,
        fixed_coverage_pixels=fixed_coverage,
    )
    candidate_rasters = tuple(candidate_preflight.candidate_rasters)
    return PreparedCase(
        case_id,
        source,
        grid,
        max_parts,
        preprocessing,
        tuple(candidate_preflight.candidates),
        candidate_rasters,
        source_pixels,
        locked_pixels,
        locked,
        requirements,
        fixed_coverage,
        {
            view: {
                "truePositives": values["truePositives"],
                "falsePositives": values["falsePositives"],
            }
            for view, values in saved_views.items()
        },
        source_counts,
        model_fingerprint(
            candidate_ids=[
                stable_placement_id(item.placement) for item in candidate_preflight.candidates
            ],
            locked_ids=[stable_placement_id(item) for item in locked],
            required_pixels=preprocessing.required_pixels,
            fixed_coverage_pixels=fixed_coverage,
            control_views={
                view: {
                    "truePositives": values["truePositives"],
                    "falsePositives": values["falsePositives"],
                }
                for view, values in saved_views.items()
            },
            mean_iou_guided=True,
        ),
    )


def preflight_payload(prepared: PreparedCase) -> dict[str, object]:
    bounds = m13b_fixed_frame_bounds(
        prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
    )
    records = occupancy_requirements(
        prepared.requirements, prepared.source_pixels, lambda pixel: _coarse_region(pixel, bounds)
    )
    policies = [
        {
            "name": policy.name,
            "mandatoryRequirementCount": len(requirements_for_policy(policy, records)),
            "mandatoryRequirementSetSha256": requirement_set_sha256(
                requirements_for_policy(policy, records)
            ),
        }
        for policy in POLICIES
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "privateOptimizationPerformed": False,
        "caseId": prepared.case_id,
        "sourceSha256": sha256(prepared.source).hexdigest(),
        "geometry": {
            "grid": asdict(prepared.grid),
            "upAxis": "y",
            "coordinateFrame": "M13B normalized source, scaled into grid coordinates",
            "scaledSourceBounds": _bounds(prepared.preprocessing.source_vertices),
            "sourceRepresentation": "SHA-pinned GLB",
        },
        "candidateUniverse": {
            "status": "PASS",
            "count": len(prepared.candidates),
            "orderedCandidateIdsSha256": _candidate_hash(prepared),
        },
        "constraints": {
            "maxParts": prepared.max_parts,
            "lockedPlacementIds": [stable_placement_id(item) for item in prepared.locked],
            "historicalCoarseRequirementCount": len(prepared.requirements),
            "vocabulary": "M13B rectangular catalogue; wedge 41769a disabled",
        },
        "fixedFrame": {
            "status": "PASS",
            "bounds": {view: list(value) for view, value in bounds.items()},
            "sourceProjectionHashes": _source_hashes(prepared.source_pixels),
        },
        "surrogate": {
            "status": "PASS",
            "definition": "B5 quantized first-order mean-IoU surrogate",
            "baseModelFingerprint": prepared.base_fingerprint,
        },
        "occupancyPolicy": {
            "status": "PASS",
            "threshold": "1/2",
            "computedFrom": "reconstructed source GLB fixed-frame raster, not benchmark labels",
            "policies": policies,
        },
        "blockers": [],
    }


def solve_case(prepared: PreparedCase, output_dir: Path, resume: bool) -> dict[str, object]:
    preflight = preflight_payload(prepared)
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    records = occupancy_requirements(
        prepared.requirements,
        prepared.source_pixels,
        lambda pixel: _coarse_region(
            pixel,
            m13b_fixed_frame_bounds(
                prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
            ),
        ),
    )
    expected = _checkpoint_provenance(prepared, preflight, objective)
    arms = _load_checkpoint(output_dir, expected) if resume else []
    completed = {arm["policy"] for arm in arms}
    for policy in POLICIES:
        if policy.name in completed:
            continue
        required = requirements_for_policy(policy, records)
        arms.append(_solve_arm(prepared, objective, policy, required))
        write_json_atomically(
            output_dir / CHECKPOINT_FILENAME,
            {
                "checkpointState": "INCOMPLETE_UNVALIDATED",
                "provenance": expected,
                "completedArms": arms,
            },
        )
    if {arm["policy"] for arm in arms} != {policy.name for policy in POLICIES}:
        raise AuditError("Checkpoint has duplicate or incomplete policy arms.")
    return {
        **preflight,
        "privateOptimizationPerformed": True,
        "arms": arms,
        "limitations": [
            "This is a two-case validation, not statistical generalization.",
            "Surrogate optimality does not prove fixed-frame IoU optimality.",
            (
                "Connectivity diagnostics do not prove physical strength or "
                "build sequence feasibility."
            ),
        ],
    }


def _solve_arm(
    prepared: PreparedCase,
    objective: LinearizedMeanIouObjective,
    policy: CoveragePolicy,
    required: tuple[CoarseRequirement, ...],
) -> dict[str, object]:
    built, _ = build_compressed_iou_dominance_model(
        candidates=prepared.candidates,
        candidate_rasters=prepared.candidate_rasters,
        source_pixels=prepared.source_pixels,
        locked_pixels=prepared.locked_pixels,
        required_pixels=prepared.preprocessing.required_pixels,
        locked_placements=prepared.locked,
        target_cells=prepared.preprocessing.target_cells,
        fixed_coverage_pixels=prepared.fixed_coverage,
        control_views=prepared.control_views,
        max_parts=prepared.max_parts,
        require_strict_improvement=False,
        enforce_iou_constraints=False,
        enforce_mandatory_coverage=False,
    )
    for requirement in required:
        built.model.add(sum(built.selected[index] for index in requirement.candidate_ids) >= 1)
    add_linearized_mean_iou_objective(
        built.model, built.true_positives, built.false_positives, objective
    )
    model_hash = model_proto_sha256(built.model)
    result, solver = solve_built_iou_dominance_model(
        built, deterministic_time_seconds=DETERMINISTIC_TIME_LIMIT_SECONDS
    )
    arm: dict[str, object] = {
        "policy": policy.name,
        "mandatoryRequirementCount": len(required),
        "solver": asdict(result),
        "solverModelProtoSha256": model_hash,
        "solverObjectiveValue": solver.objective_value
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "solverBestObjectiveBound": solver.best_objective_bound
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
    }
    if result.status in {"OPTIMAL", "FEASIBLE"}:
        arm["witness"] = _verify_witness(
            prepared, result.selected_ids, objective, required, result.views
        )
    return arm


def _verify_witness(
    prepared: PreparedCase,
    selected: tuple[int, ...],
    objective: LinearizedMeanIouObjective,
    required: tuple[CoarseRequirement, ...],
    solver_views: object,
) -> dict[str, object]:
    placements = (*prepared.locked, *(prepared.candidates[index].placement for index in selected))
    fixed = fixed_frame_score(
        prepared.preprocessing.source_vertices,
        prepared.preprocessing.faces,
        placements,
        prepared.preprocessing.target_cells,
    )
    views = {
        item.view: {
            "truePositives": item.true_positives,
            "falsePositives": item.false_positives,
            "falseNegatives": prepared.source_counts[item.view] - item.true_positives,
        }
        for item in fixed.views
    }
    validate_view_metrics(views, prepared.source_counts)
    parity = _mask_parity(
        prepared.preprocessing.source_vertices,
        prepared.preprocessing.faces,
        placements,
        prepared.preprocessing.target_cells,
        prepared.source_pixels,
        prepared.locked_pixels,
        [prepared.candidate_rasters[index] for index in selected],
        m13b_fixed_frame_bounds(
            prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
        ),
    )
    mechanical = validate_completed_arrangement(
        placements, prepared.preprocessing.protected_empty_cells, prepared.max_parts
    )
    if views != solver_views or not parity["passed"] or not mechanical.is_valid:
        raise AuditError("Independent witness reconstruction failed.")
    unmet_historical = count_unmet_coarse_requirements(prepared.requirements, selected)
    unmet_policy = count_unmet_coarse_requirements(required, selected)
    return {
        "selectedCandidateIndices": list(selected),
        "selectedCandidateIds": [
            stable_placement_id(prepared.candidates[index].placement) for index in selected
        ],
        "partCount": len(placements),
        "connectedComponentCount": len(mechanical.connected_components),
        "mechanical": asdict(mechanical),
        "historicalUnmetRequirementCount": len(unmet_historical),
        "policyUnmetRequirementCount": len(unmet_policy),
        "views": views,
        "fixedFrameMeanIouExact": _fraction_text(fixed_frame_mean_iou_fraction(views)),
        "surrogateObjectiveValue": surrogate_value(views, objective),
        "independentMaskParity": parity,
        "frozenSilhouetteV1": asdict(
            evaluate_completed_assembly(
                prepared.preprocessing.source_vertices, prepared.preprocessing.faces, placements
            )
        ),
    }


def _coarse_region(
    pixel: tuple[str, int, int], bounds: dict[str, tuple[float, float, float, float]]
) -> frozenset[tuple[str, int, int]]:
    from scripts.run_m13f_duck_minimum_violation_audit import _coarse_cell_region

    return frozenset(_coarse_cell_region(pixel, bounds))


def _record(path: Path, case_id: str) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise AuditError("M13B summary does not contain records.")
    matches = [item for item in records if isinstance(item, dict) and item.get("caseId") == case_id]
    if len(matches) != 1:
        raise AuditError("M13B summary must contain exactly one matching case record.")
    return matches[0]


def _views(control: dict[str, object]) -> dict[str, dict[str, int]]:
    fixed = _mapping(control.get("fixedFrame"), "control.fixedFrame")
    values = fixed.get("views")
    if not isinstance(values, list):
        raise AuditError("control.fixedFrame.views must be a list.")
    parsed: dict[str, dict[str, int]] = {}
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("view"), str):
            raise AuditError("control fixed-frame metrics are incomplete.")
        view = item["view"]
        metrics = {
            name: _integer(item.get(name), f"control.fixedFrame.{view}.{name}")
            for name in ("truePositives", "falsePositives", "falseNegatives")
        }
        if view in parsed:
            raise AuditError("control fixed-frame metrics duplicate a view.")
        parsed[view] = metrics
    if set(parsed) != {"front", "side", "top"}:
        raise AuditError("control fixed-frame metrics are incomplete.")
    return parsed


def _candidate_hash(prepared: PreparedCase) -> str:
    return sha256(
        "\n".join(stable_placement_id(item.placement) for item in prepared.candidates).encode()
    ).hexdigest()


def _source_hashes(pixels: frozenset[tuple[str, int, int]]) -> dict[str, str]:
    return {
        view: sha256(
            "\n".join(
                f"{x}:{y}" for _, x, y in sorted(pixel for pixel in pixels if pixel[0] == view)
            ).encode()
        ).hexdigest()
        for view in ("front", "side", "top")
    }


def _bounds(vertices: list[tuple[float, float, float]]) -> dict[str, list[float]]:
    return {
        axis: [min(vertex[index] for vertex in vertices), max(vertex[index] for vertex in vertices)]
        for index, axis in enumerate(("x", "y", "z"))
    }


def _checkpoint_provenance(
    prepared: PreparedCase,
    preflight: dict[str, object],
    objective: LinearizedMeanIouObjective,
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": prepared.case_id,
        "sourceSha256": preflight["sourceSha256"],
        "baseModelFingerprint": prepared.base_fingerprint,
        "candidateIdsSha256": _candidate_hash(prepared),
        "policies": [policy.name for policy in POLICIES],
        "solver": {
            "deterministicTimeSeconds": DETERMINISTIC_TIME_LIMIT_SECONDS,
            "randomSeed": 0,
            "workers": 1,
        },
        "objective": {
            "scale": objective.scale,
            "truePositiveCoefficients": dict(objective.true_positive_coefficients),
            "falsePositiveCoefficients": dict(objective.false_positive_coefficients),
        },
    }


def _load_checkpoint(output_dir: Path, expected: dict[str, object]) -> list[dict[str, object]]:
    try:
        payload = json.loads((output_dir / CHECKPOINT_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError("Cannot resume without a valid matching checkpoint.") from error
    if (
        not isinstance(payload, dict)
        or payload.get("checkpointState") != "INCOMPLETE_UNVALIDATED"
        or payload.get("provenance") != expected
    ):
        raise AuditError("Checkpoint provenance does not match this case and model configuration.")
    arms = payload.get("completedArms")
    if not isinstance(arms, list) or not all(
        isinstance(arm, dict) and isinstance(arm.get("policy"), str) for arm in arms
    ):
        raise AuditError("Checkpoint arms are malformed.")
    return arms


def write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} must be an object.")
    return value


def _strings(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError(f"{name} must be a list of strings.")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuditError(f"{name} must be an integer.")
    return value


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


if __name__ == "__main__":
    raise SystemExit(main())
