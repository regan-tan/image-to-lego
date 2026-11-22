"""Run or preflight the opt-in M13F source-occupancy coverage ablation."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13c_silhouette_equivalence_audit import AuditError, m13b_fixed_frame_bounds
from app.conversion.m13e_duck_control_hint_experiment import DUCK_MAX_PARTS
from app.conversion.m13e_duck_iou_dominance import solve_built_iou_dominance_model
from app.conversion.m13e_duck_iou_incidence_compression import model_proto_sha256
from app.conversion.m13e_duck_mean_iou_guided import (
    LinearizedMeanIouObjective,
    add_linearized_mean_iou_objective,
    linearized_mean_iou_objective,
)
from app.conversion.m13f_duck_coarse_budget_frontier import (
    CoarseRequirement,
    count_unmet_coarse_requirements,
)
from app.conversion.m13f_duck_occupancy_coverage_ablation import (
    POLICIES,
    CoveragePolicy,
    OccupancyRequirement,
    Pixel,
    occupancy_requirements,
    policy_definition,
    requirement_set_sha256,
    requirements_for_policy,
)
from app.conversion.m13f_minimum_violation_audit import independently_count_violations
from scripts.run_m13f_duck_coarse_budget_frontier import (
    DETERMINISTIC_TIME_LIMIT_SECONDS,
    FrontierPreflight,
    _build_arm_model,
    _fraction_text,
    _write_json_atomically,
    prepare_frontier,
)
from scripts.run_m13f_duck_minimum_violation_audit import (
    TARGET_SURROGATE_OBJECTIVE,
    _verify_solver_witness,
    _witnesses,
)

SCHEMA_VERSION = "m13f-duck-occupancy-coverage-ablation-v1"
CHECKPOINT_FILENAME = "PRIVATE_UNVALIDATED_CHECKPOINT.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--frontier-summary", type=Path, required=True)
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Validate inputs without creating a solver model.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/m13f-duck-occupancy-coverage-ablation"),
    )
    args = parser.parse_args()
    if args.output_dir.exists() and not (args.preflight or args.resume):
        parser.error("Refusing to overwrite an existing experiment output directory.")
    payload = run_ablation(
        args.manifest,
        args.summary,
        args.frontier_summary,
        preflight_only=args.preflight,
        checkpoint_dir=None if args.preflight else args.output_dir,
        resume=args.resume,
    )
    if not args.preflight:
        _write_json_atomically(args.output_dir / "summary.json", payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


def run_ablation(
    manifest_path: Path,
    summary_path: Path,
    frontier_path: Path,
    *,
    preflight_only: bool,
    checkpoint_dir: Path | None = None,
    resume: bool = False,
) -> dict[str, object]:
    """Validate the pinned case and, only when requested, solve one fresh model per policy."""
    prepared = prepare_frontier(manifest_path, summary_path)
    records = _occupancy_records(prepared)
    known = _verified_known_witness(prepared, frontier_path)
    policies = _policy_payloads(records)
    base = _preflight_payload(prepared, records, policies, known)
    if preflight_only:
        return {**base, "status": "PASS", "privateOptimizationPerformed": False}

    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    arms = _load_checkpoint(prepared, policies, checkpoint_dir, resume)
    completed = {cast(str, arm["policy"]) for arm in arms}
    for policy in POLICIES:
        if policy.name in completed:
            continue
        selected_requirements = requirements_for_policy(policy, records)
        arm = _solve_arm(prepared, objective, policy, selected_requirements)
        arms.append(arm)
        _write_checkpoint(prepared, policies, checkpoint_dir, arms)
    arms.sort(key=lambda arm: [p.name for p in POLICIES].index(cast(str, arm["policy"])))
    return {
        **base,
        "status": "PASS",
        "privateOptimizationPerformed": True,
        "arms": arms,
        "limitations": [
            "Thresholds are Duck-specific exploratory diagnostics, not a production policy.",
            "Identical surrogate scores do not establish identical IoU or connectivity.",
            "No policy result is a general-purpose source-occupancy validation.",
        ],
    }


def _occupancy_records(prepared: FrontierPreflight) -> tuple[OccupancyRequirement, ...]:
    assert prepared.candidate_preflight.source_pixels is not None
    bounds = m13b_fixed_frame_bounds(
        prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
    )
    from scripts.run_m13f_duck_minimum_violation_audit import _coarse_cell_region

    records = occupancy_requirements(
        prepared.requirements,
        prepared.candidate_preflight.source_pixels,
        lambda pixel: _coarse_cell_region(pixel, bounds),
    )
    if any(record.pixel_count == 0 for record in records):
        raise AuditError("A historical requirement rasterized to an empty fixed-frame region.")
    return records


def _policy_payloads(records: tuple[OccupancyRequirement, ...]) -> list[dict[str, object]]:
    return [
        {
            "policy": policy.name,
            "definition": policy_definition(policy),
            "requiredCellCount": len(selected := requirements_for_policy(policy, records)),
            "requiredCellSetSha256": requirement_set_sha256(selected),
            "requiredCells": [_cell(item) for item in selected],
        }
        for policy in POLICIES
    ]


def _verified_known_witness(prepared: FrontierPreflight, frontier_path: Path) -> dict[str, object]:
    try:
        frontier = json.loads(frontier_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError("M13F-B2 frontier summary could not be read.") from error
    if not isinstance(frontier, dict):
        raise AuditError("M13F-B2 frontier summary must be an object.")
    selected = _witnesses(frontier)[35]
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    verified = _verify_solver_witness(prepared, selected, objective)
    if verified["surrogateObjectiveValue"] != TARGET_SURROGATE_OBJECTIVE:
        raise AuditError("The connected K=35 witness has an unexpected surrogate score.")
    if verified["connectedComponentCount"] != 1 or verified["partCount"] != 33:
        raise AuditError("M13F-B2 K=35 is not the declared connected 33-part witness.")
    required_50 = requirements_for_policy(POLICIES[5], _occupancy_records(prepared))
    if independently_count_violations(required_50, selected):
        raise AuditError("The known K=35 witness does not satisfy the 50% policy.")
    return {
        "selectedCandidateIndices": list(selected),
        "partCount": verified["partCount"],
        "connectedComponentCount": verified["connectedComponentCount"],
        "surrogateObjectiveValue": verified["surrogateObjectiveValue"],
        "historicalUnmetRequirementCount": verified["unmetRequirementCount"],
        "satisfies50PercentPolicy": True,
        "surrogateOptimalityCertificate": (
            "The independently verified witness is feasible for the 50% policy and equals the "
            "established unrestricted surrogate optimum 152987135."
        ),
    }


def _preflight_payload(
    prepared: FrontierPreflight,
    records: tuple[OccupancyRequirement, ...],
    policies: list[dict[str, object]],
    known: dict[str, object],
) -> dict[str, object]:
    assert prepared.candidate_preflight.source_pixels is not None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "preflight": {
            "historicalRequirementCount": len(records),
            "sourceSha256": sha256(prepared.source).hexdigest(),
            "candidateCount": len(prepared.candidate_preflight.candidates),
            "candidateIdsSha256": sha256(
                "\n".join(
                    stable_placement_id(c.placement)
                    for c in prepared.candidate_preflight.candidates
                ).encode()
            ).hexdigest(),
            "baseModelFingerprint": prepared.base_fingerprint,
            "sourceProjectionHashes": _source_hashes(prepared.candidate_preflight.source_pixels),
            "occupancyEvidence": [_record(record) for record in records],
            "policies": policies,
            "knownConnectedK35Witness": known,
            "zeroForegroundExplanation": (
                "The historical requirements originate from occupied 3D grid-cell projections; "
                "their fixed-frame raster regions are compared to an independently rasterized "
                "source silhouette. Empty overlap is retained as evidence, not corrected."
            ),
        },
    }


def _solve_arm(
    prepared: FrontierPreflight,
    objective: LinearizedMeanIouObjective,
    policy: CoveragePolicy,
    requirements: tuple[CoarseRequirement, ...],
) -> dict[str, object]:
    if requirements:
        built, _, model_hash = _build_arm_model(  # type: ignore[no-untyped-call]
            0,
            prepared.candidate_preflight,
            prepared.preprocessing,
            prepared.locked,
            requirements,
            prepared.fixed_coverage,
            prepared.control_views,
            objective,
        )
    else:
        from app.conversion.m13e_duck_iou_incidence_compression import (
            build_compressed_iou_dominance_model,
        )

        built, _ = build_compressed_iou_dominance_model(
            candidates=prepared.candidate_preflight.candidates,
            candidate_rasters=prepared.candidate_preflight.candidate_rasters,
            source_pixels=prepared.candidate_preflight.source_pixels,
            locked_pixels=prepared.candidate_preflight.locked_pixels,
            required_pixels=prepared.preprocessing.required_pixels,
            locked_placements=prepared.locked,
            target_cells=prepared.preprocessing.target_cells,
            fixed_coverage_pixels=prepared.fixed_coverage,
            control_views=prepared.control_views,
            max_parts=DUCK_MAX_PARTS,
            require_strict_improvement=False,
            enforce_iou_constraints=False,
            enforce_mandatory_coverage=False,
        )
        add_linearized_mean_iou_objective(
            built.model, built.true_positives, built.false_positives, objective
        )
        model_hash = model_proto_sha256(built.model)
    result, solver = solve_built_iou_dominance_model(
        built, deterministic_time_seconds=DETERMINISTIC_TIME_LIMIT_SECONDS
    )
    arm: dict[str, object] = {
        "policy": policy.name,
        "solver": asdict(result),
        "solverModelProtoSha256": model_hash,
        "solverObjectiveValue": solver.objective_value
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "solverBestObjectiveBound": solver.best_objective_bound
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "surrogateOptimalityProven": result.status == "OPTIMAL",
    }
    if result.status in {"OPTIMAL", "FEASIBLE"}:
        witness = _verify_solver_witness(prepared, result.selected_ids, objective)
        historical_unmet = count_unmet_coarse_requirements(
            prepared.requirements, result.selected_ids
        )
        policy_unmet = count_unmet_coarse_requirements(requirements, result.selected_ids)
        witness["historicalAdmissibility"] = not bool(historical_unmet)
        witness["policySpecificAdmissibility"] = not bool(policy_unmet)
        witness["historicalUnmetRequirements"] = [_cell(item) for item in historical_unmet]
        witness["policyUnmetRequirements"] = [_cell(item) for item in policy_unmet]
        arm["witness"] = witness
    return arm


def _load_checkpoint(
    prepared: FrontierPreflight,
    policies: list[dict[str, object]],
    directory: Path | None,
    resume: bool,
) -> list[dict[str, object]]:
    if directory is None:
        return []
    path = directory / CHECKPOINT_FILENAME
    if not resume:
        _write_checkpoint(prepared, policies, directory, [])
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError("Cannot resume without a valid occupancy-ablation checkpoint.") from error
    expected = _checkpoint_provenance(prepared, policies)
    if not isinstance(payload, dict) or payload.get("provenance") != expected:
        raise AuditError("Checkpoint provenance does not match the current model configuration.")
    arms = payload.get("completedArms")
    if not isinstance(arms, list) or not all(isinstance(arm, dict) for arm in arms):
        raise AuditError("Checkpoint arms are malformed.")
    return cast(list[dict[str, object]], arms)


def _write_checkpoint(
    prepared: FrontierPreflight,
    policies: list[dict[str, object]],
    directory: Path | None,
    arms: list[dict[str, object]],
) -> None:
    if directory is not None:
        _write_json_atomically(
            directory / CHECKPOINT_FILENAME,
            {
                "checkpointState": "INCOMPLETE_UNVALIDATED",
                "provenance": _checkpoint_provenance(prepared, policies),
                "completedArms": arms,
            },
        )


def _checkpoint_provenance(
    prepared: FrontierPreflight, policies: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "baseModelFingerprint": prepared.base_fingerprint,
        "policies": policies,
        "solver": {
            "deterministicTimeSeconds": DETERMINISTIC_TIME_LIMIT_SECONDS,
            "randomSeed": 0,
            "workers": 1,
        },
    }


def _cell(requirement: CoarseRequirement) -> dict[str, object]:
    pixel = requirement.pixel
    return {"view": pixel[0], "coordinates": [pixel[1], pixel[2]]}


def _record(record: OccupancyRequirement) -> dict[str, object]:
    return {
        **_cell(record.requirement),
        "originalHistoricalMembership": True,
        "pixelCount": record.pixel_count,
        "sourceForegroundPixels": record.source_foreground_pixels,
        "sourceOccupancyFraction": _fraction_text(record.fraction),
    }


def _source_hashes(source: Collection[Pixel]) -> dict[str, str]:
    from app.conversion.m13f_duck_reconstruction_audit import projection_hashes

    return projection_hashes(source=source)["source"]


if __name__ == "__main__":
    raise SystemExit(main())
