"""Run the opt-in M13F-B3 minimum coarse-violation and importance audit."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.catalogue_silhouette_experiment import _pixel
from app.conversion.evaluation_alignment import evaluate_completed_assembly, stable_placement_id
from app.conversion.fidelity import SILHOUETTE_RESOLUTION
from app.conversion.m12c_wedge_fidelity_experiment import (
    fixed_frame_score,
    validate_completed_arrangement,
)
from app.conversion.m13c_silhouette_equivalence_audit import AuditError, m13b_fixed_frame_bounds
from app.conversion.m13e_duck_cross_view_tradeoff import fixed_frame_mean_iou_fraction
from app.conversion.m13e_duck_iou_dominance import solve_built_iou_dominance_model
from app.conversion.m13e_duck_iou_incidence_compression import model_proto_sha256
from app.conversion.m13e_duck_mean_iou_guided import (
    LinearizedMeanIouObjective,
    linearized_mean_iou_objective,
    surrogate_value,
)
from app.conversion.m13f_duck_coarse_budget_frontier import (
    count_unmet_coarse_requirements,
)
from app.conversion.m13f_minimum_violation_audit import (
    add_exact_surrogate_target,
    add_minimum_violation_objective,
    exact_surrogate_matches,
    independently_count_violations,
    minimum_violation_conclusion,
)
from scripts.run_m13d_tp_fp_feasibility import _mask_parity
from scripts.run_m13f_duck_coarse_budget_frontier import (
    DETERMINISTIC_TIME_LIMIT_SECONDS,
    DUCK_MAX_PARTS,
    FrontierPreflight,
    _build_arm_model,
    _fraction_text,
    prepare_frontier,
)

TARGET_SURROGATE_OBJECTIVE = 152_987_135
SCHEMA_VERSION = "m13f-duck-minimum-violation-audit-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--frontier-summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/m13f-duck-minimum-violation-audit")
    )
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Refusing to overwrite an existing experiment output directory.")
    payload = run_audit(args.manifest, args.summary, args.frontier_summary)
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["status"] == "PASS" else 1


def run_audit(manifest_path: Path, summary_path: Path, frontier_path: Path) -> dict[str, object]:
    """Solve exactly one lexicographic model after validating B2's K=35 witness."""
    prepared = prepare_frontier(manifest_path, summary_path)
    frontier = _load_frontier(frontier_path)
    witnesses = _witnesses(frontier)
    k35 = witnesses[35]
    _verify_historical_witness(prepared, k35, expected_unmet=35)
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    built, violations, _ = _build_arm_model(
        98,
        prepared.candidate_preflight,
        prepared.preprocessing,
        prepared.locked,
        prepared.requirements,
        prepared.fixed_coverage,
        prepared.control_views,
        objective,
    )
    add_exact_surrogate_target(built, objective, TARGET_SURROGATE_OBJECTIVE)
    add_minimum_violation_objective(built.model, violations)
    model_hash = model_proto_sha256(built.model)
    result, solver = solve_built_iou_dominance_model(
        built, deterministic_time_seconds=DETERMINISTIC_TIME_LIMIT_SECONDS
    )
    solver_record: dict[str, object] = {
        "status": result.status,
        "deterministicTimeSeconds": DETERMINISTIC_TIME_LIMIT_SECONDS,
        "bestObjectiveBound": solver.best_objective_bound
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "objectiveValue": solver.objective_value
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "modelProtoSha256": model_hash,
        "baseModelProvenance": (
            "This hash identifies the full lexicographic model, not the shared base fingerprint."
        ),
    }
    witness: dict[str, object] | None = None
    if result.status in {"OPTIMAL", "FEASIBLE"}:
        witness = _verify_solver_witness(prepared, result.selected_ids, objective)
    status = "PASS" if result.status in {"OPTIMAL", "FEASIBLE"} else "INCONCLUSIVE"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "privateOptimizationPerformed": True,
        "targetSurrogateObjective": TARGET_SURROGATE_OBJECTIVE,
        "preflight": {"k35WitnessValid": True, "k35UnmetRequirementCount": 35},
        "solver": solver_record,
        "conclusion": minimum_violation_conclusion(result.status),
        "provenMinimumViolationCount": witness["unmetRequirementCount"]
        if result.status == "OPTIMAL" and witness is not None
        else None,
        "feasibleUpperBound": witness["unmetRequirementCount"] if witness is not None else 35,
        "rigorousLowerBound": solver.best_objective_bound
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "witness": witness,
        "requirementImportanceAudit": _importance_audit(prepared, witnesses),
        "recommendation": _recommendation(),
        "limitations": [
            "The B5 surrogate equality is not equality of fixed-frame or frozen mean IoU.",
            (
                "Requirement-level overlap is descriptive: overlapping false-positive pixels "
                "are not attributed to one requirement."
            ),
            "Observed omission association is not a controlled causal estimate.",
        ],
    }


def _load_frontier(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != "m13f-duck-coarse-budget-frontier-v1"
    ):
        raise AuditError("Frontier input is not an M13F-B2 summary.")
    return cast(dict[str, object], payload)


def _witnesses(frontier: dict[str, object]) -> dict[int, tuple[int, ...]]:
    arms = frontier.get("arms")
    if not isinstance(arms, list):
        raise AuditError("M13F-B2 arms must be a list.")
    result: dict[int, tuple[int, ...]] = {}
    for arm in arms:
        if not isinstance(arm, dict) or not isinstance(arm.get("budget"), int):
            raise AuditError("M13F-B2 arm is malformed.")
        details = arm.get("result")
        if isinstance(details, dict) and isinstance(details.get("selectedCandidateIndices"), list):
            ids = details["selectedCandidateIndices"]
            if not all(isinstance(item, int) and not isinstance(item, bool) for item in ids):
                raise AuditError("M13F-B2 selected candidate IDs must be integers.")
            result[arm["budget"]] = tuple(ids)
    if set(result) != {0, 1, 2, 5, 10, 20, 35}:
        raise AuditError("M13F-B2 requires all seven verified witness arms.")
    return result


def _verify_historical_witness(
    prepared: FrontierPreflight, selected: tuple[int, ...], *, expected_unmet: int
) -> None:
    actual = independently_count_violations(prepared.requirements, selected)
    if actual != expected_unmet:
        raise AuditError("Historical K=35 witness does not have the declared unmet count.")
    witness = _verify_solver_witness(
        prepared,
        selected,
        linearized_mean_iou_objective(prepared.source_counts, prepared.control_views),
    )
    if witness["surrogateObjectiveValue"] != TARGET_SURROGATE_OBJECTIVE:
        raise AuditError("Historical K=35 witness does not meet the pinned surrogate target.")


def _verify_solver_witness(
    prepared: FrontierPreflight,
    selected: tuple[int, ...],
    objective: LinearizedMeanIouObjective,
) -> dict[str, object]:
    assert prepared.candidate_preflight.source_pixels is not None
    assert prepared.candidate_preflight.locked_pixels is not None
    assert prepared.candidate_preflight.candidate_rasters is not None
    placements = (
        *prepared.locked,
        *(prepared.candidate_preflight.candidates[i].placement for i in selected),
    )
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
    bounds = m13b_fixed_frame_bounds(
        prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
    )
    parity = _mask_parity(
        prepared.preprocessing.source_vertices,
        prepared.preprocessing.faces,
        placements,
        prepared.preprocessing.target_cells,
        prepared.candidate_preflight.source_pixels,
        prepared.candidate_preflight.locked_pixels,
        [prepared.candidate_preflight.candidate_rasters[i] for i in selected],
        bounds,
    )
    mechanical = validate_completed_arrangement(
        placements, prepared.preprocessing.protected_empty_cells, DUCK_MAX_PARTS
    )
    unmet = count_unmet_coarse_requirements(prepared.requirements, selected)
    if not parity["passed"] or not mechanical.is_valid:
        raise AuditError("Independent solver-witness verification failed.")
    return {
        "selectedCandidateIndices": list(selected),
        "placementIds": [stable_placement_id(item) for item in placements],
        "views": views,
        "surrogateObjectiveValue": surrogate_value(views, objective),
        "surrogateTargetEquality": exact_surrogate_matches(
            views, objective, TARGET_SURROGATE_OBJECTIVE
        ),
        "fixedFrameMeanIouExact": _fraction_text(fixed_frame_mean_iou_fraction(views)),
        "frozenSilhouetteV1": asdict(
            evaluate_completed_assembly(
                prepared.preprocessing.source_vertices, prepared.preprocessing.faces, placements
            )
        ),
        "mechanical": asdict(mechanical),
        "partCount": len(placements),
        "connectedComponentCount": len(mechanical.connected_components),
        "isolatedPartIndices": [
            component[0] for component in mechanical.connected_components if len(component) == 1
        ],
        "independentMaskParity": parity,
        "unmetRequirementCount": len(unmet),
        "unmetRequirements": [
            {"view": item.pixel[0], "coordinates": [item.pixel[1], item.pixel[2]]} for item in unmet
        ],
    }


def _importance_audit(
    prepared: FrontierPreflight, witnesses: dict[int, tuple[int, ...]]
) -> list[dict[str, object]]:
    source = prepared.candidate_preflight.source_pixels
    rasters = prepared.candidate_preflight.candidate_rasters
    assert source is not None
    assert rasters is not None
    bounds = m13b_fixed_frame_bounds(
        prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
    )
    records: list[dict[str, object]] = []
    for requirement in prepared.requirements:
        cell_region = _coarse_cell_region(requirement.pixel, bounds)
        incident_region = frozenset().union(*(rasters[i] for i in requirement.candidate_ids))
        incident_view_region = frozenset(
            pixel for pixel in incident_region if pixel[0] == requirement.pixel[0]
        )
        occupancy = len(cell_region & source)
        witness_status = {
            str(k): not bool(set(ids).isdisjoint(requirement.candidate_ids))
            for k, ids in witnesses.items()
        }
        witness_metrics = {
            str(k): _regional_metrics(
                source,
                cell_region,
                prepared.candidate_preflight.locked_pixels,
                rasters,
                ids,
            )
            for k, ids in witnesses.items()
        }
        records.append(
            {
                "view": requirement.pixel[0],
                "coordinates": [requirement.pixel[1], requirement.pixel[2]],
                "candidateIncidenceCount": len(requirement.candidate_ids),
                "fixedFrameCoarseCellRegion": {
                    "definition": "pinned fixed-frame rasterization of the unit coarse grid cell",
                    "pixelCount": len(cell_region),
                    "sourceForegroundPixels": occupancy,
                    "sourceOccupancyFraction": _fraction_text(Fraction(occupancy, len(cell_region)))
                    if cell_region
                    else None,
                },
                "incidentCandidateRasterOverlap": {
                    "definition": (
                        "union of incident candidates' fixed-frame footprints; "
                        "not an exclusive attribution"
                    ),
                    "pixelCount": len(incident_view_region),
                },
                "witnessSatisfied": witness_status,
                "historicalWitnessRegionalMetrics": witness_metrics,
                "unmetHighFidelityWitnessCount": sum(
                    not witness_status[str(k)] for k in (5, 10, 20, 35)
                ),
            }
        )
    return records


def _coarse_cell_region(
    requirement: tuple[str, int, int],
    bounds: dict[str, tuple[float, float, float, float]],
) -> frozenset[tuple[str, int, int]]:
    """Map a unit grid cell to the exact pinned fixed-frame pixel rectangle."""
    view, first, second = requirement
    axes = {"front": (0, 2), "side": (1, 2), "top": (0, 1)}[view]
    points = []
    for first_value in (first, first + 1):
        for second_value in (second, second + 1):
            coordinates = [0.0, 0.0, 0.0]
            coordinates[axes[0]] = float(first_value)
            coordinates[axes[1]] = float(second_value)
            point = (coordinates[0], coordinates[1], coordinates[2])
            points.append(_pixel(point, axes, bounds[view]))
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    return frozenset(
        (view, x, y)
        for x in range(min_x, max_x + 1)
        for y in range(min_y, max_y + 1)
        if 0 <= x < SILHOUETTE_RESOLUTION and 0 <= y < SILHOUETTE_RESOLUTION
    )


def _regional_metrics(
    source: frozenset[tuple[str, int, int]],
    region: frozenset[tuple[str, int, int]],
    locked: frozenset[tuple[str, int, int]] | None,
    rasters: tuple[frozenset[tuple[str, int, int]], ...],
    selected: tuple[int, ...],
) -> dict[str, int]:
    """Report region-local TP/FP/FN without assigning shared pixels to a requirement."""
    assert locked is not None
    output = frozenset(locked).union(*(rasters[index] for index in selected))
    regional_source = source & region
    regional_output = output & region
    return {
        "truePositives": len(regional_source & regional_output),
        "falsePositives": len(regional_output - regional_source),
        "falseNegatives": len(regional_source - regional_output),
    }


def _recommendation() -> dict[str, object]:
    return {
        "status": "FUTURE_POLICY_ONLY",
        "proposal": (
            "Use a controlled source-occupancy-aware coarse-coverage penalty or selectively "
            "mandatory cells after ablation."
        ),
        "verified": (
            "Exact violation counting and the target-score lexicographic encoding are verified "
            "by focused tests."
        ),
        "requiresControlledExperiment": (
            "Whether exceptions improve user-visible fidelity without harmful omission "
            "or spillover."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
