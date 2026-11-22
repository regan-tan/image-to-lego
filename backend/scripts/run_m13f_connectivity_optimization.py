"""Run the isolated M13F-B7 connectivity-constrained reconstruction study.

The command is opt-in and writes only its ignored output directory.  It never
changes conversion behaviour, historical artifacts, or the candidate universe.
"""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ortools.sat.python import cp_model

from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13e_duck_iou_dominance import (
    IoUDominanceModel,
    IoUDominanceResult,
    solve_built_iou_dominance_model,
)
from app.conversion.m13e_duck_iou_incidence_compression import (
    build_compressed_iou_dominance_model,
    model_proto_sha256,
)
from app.conversion.m13e_duck_mean_iou_guided import (
    LinearizedMeanIouObjective,
    linearized_mean_iou_objective,
    surrogate_value,
)
from app.conversion.m13f_connectivity_optimization import (
    ConnectivityGraph,
    ContactGraphAudit,
    add_exact_mask_constraints,
    add_selectable_root_variables,
    add_separator_cut,
    add_single_component_constraint,
    audit_contact_graph_subset,
    mechanical_connectivity_graph,
    selected_graph_component_count,
    selected_graph_components,
    separator_cuts,
)
from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement
from app.conversion.m13f_duck_occupancy_coverage_ablation import (
    occupancy_requirements,
    requirements_for_policy,
)
from scripts.run_m13f_cross_object_validation import (
    DETERMINISTIC_TIME_LIMIT_SECONDS,
    POLICIES,
    PreparedCase,
    _coarse_region,
    _verify_witness,
    prepare_case,
)

SCHEMA_VERSION = "m13f-b7-2-connectivity-cut-generation-v1"
CHECKPOINT_FILENAME = "PRIVATE_UNVALIDATED_CHECKPOINT.json"
MANSION_PINNED_SURROGATE = 162246440
MAX_CONNECTIVITY_EDGES = 100_000
CUT_GENERATION_MAX_ITERATIONS = 40
CUT_GENERATION_TOTAL_DETERMINISTIC_SECONDS = 120.0
CONTACT_GRAPH_AUDIT_SUBSET_SIZE = 64


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--m13b-summary", type=Path, required=True)
    parser.add_argument("--b6-summary", type=Path, required=True)
    parser.add_argument("--case", choices=("mansion", "duck", "realistic-man"), default="mansion")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--connectivity-formulation", choices=("cuts", "flow"), default="cuts")
    parser.add_argument("--cut-max-iterations", type=int, default=CUT_GENERATION_MAX_ITERATIONS)
    parser.add_argument(
        "--cut-total-deterministic-seconds",
        type=float,
        default=CUT_GENERATION_TOTAL_DETERMINISTIC_SECONDS,
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/m13f-connectivity-cut-generation")
    )
    args = parser.parse_args()
    if args.cut_max_iterations <= 0 or args.cut_total_deterministic_seconds <= 0:
        parser.error("Cut iteration and deterministic-time budgets must be positive.")
    if args.output_dir.exists() and not (args.preflight or args.resume):
        parser.error("Refusing to overwrite an existing private experiment directory.")
    prepared = prepare_case(args.manifest, args.case, args.m13b_summary)
    b6_selected = _b6_selection(args.b6_summary)
    payload = run_experiment(
        prepared,
        b6_selected,
        preflight_only=args.preflight,
        output_dir=args.output_dir,
        resume=args.resume,
        formulation=args.connectivity_formulation,
        cut_max_iterations=args.cut_max_iterations,
        cut_total_deterministic_seconds=args.cut_total_deterministic_seconds,
    )
    if args.preflight:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _write_json_atomically(args.output_dir / "summary.json", payload)
    return 0 if payload["status"] == "PASS" else 1


def run_experiment(
    prepared: PreparedCase,
    b6_selected: tuple[int, ...],
    *,
    preflight_only: bool,
    output_dir: Path | None = None,
    resume: bool = False,
    formulation: str = "cuts",
    cut_max_iterations: int = CUT_GENERATION_MAX_ITERATIONS,
    cut_total_deterministic_seconds: float = CUT_GENERATION_TOTAL_DETERMINISTIC_SECONDS,
) -> dict[str, object]:
    """Audit the B6 witness, then run B7 stages only on an explicit opt-in."""
    _validate_selection(prepared, b6_selected)
    graph = mechanical_connectivity_graph(
        [candidate.placement for candidate in prepared.candidates], prepared.locked
    )
    audit = _contact_audit(prepared, graph)
    if (
        not audit.matches
        or audit.required_positive_pairs_found != audit.required_positive_pair_count
    ):
        raise ValueError(
            "Indexed contact graph does not match the naive matcher on the audit subset."
        )
    base = _preflight(
        prepared,
        b6_selected,
        graph,
        audit,
        cut_max_iterations,
        cut_total_deterministic_seconds,
    )
    if preflight_only:
        return {**base, "status": "PASS", "privateOptimizationPerformed": False}
    if formulation == "flow" and len(graph.edges) > MAX_CONNECTIVITY_EDGES:
        return {
            **base,
            "status": "BLOCKED",
            "privateOptimizationPerformed": False,
            "reason": "Complete mechanical graph exceeds the explicit flow model-size limit.",
        }
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    pinned_surrogate = surrogate_value(_views_for_selection(prepared, b6_selected), objective)
    if prepared.case_id == "mansion" and pinned_surrogate != MANSION_PINNED_SURROGATE:
        raise ValueError("B6 Mansion witness does not have the required pinned surrogate score.")
    required = _fifty_percent_requirements(prepared)
    checkpoint = _load_checkpoint(prepared, b6_selected, output_dir, resume)
    stages = checkpoint
    if "exactMaskFeasibility" not in stages:
        stages["exactMaskFeasibility"] = _solve_stage(
            prepared,
            graph,
            required,
            objective,
            b6_selected,
            pinned_surrogate,
            "exact-feasibility",
            formulation,
            cut_max_iterations,
            cut_total_deterministic_seconds,
        )
        _save_checkpoint(prepared, b6_selected, output_dir, stages)
    exact = stages["exactMaskFeasibility"]
    if (
        isinstance(exact, dict)
        and exact.get("status") in {"FEASIBLE", "OPTIMAL"}
        and "exactMaskMinimumParts" not in stages
    ):
        stages["exactMaskMinimumParts"] = _solve_stage(
            prepared,
            graph,
            required,
            objective,
            b6_selected,
            pinned_surrogate,
            "exact-minimum-parts",
            formulation,
            cut_max_iterations,
            cut_total_deterministic_seconds,
        )
        _save_checkpoint(prepared, b6_selected, output_dir, stages)
    if _proven_infeasible(exact) and "pinnedSurrogate" not in stages:
        stages["pinnedSurrogate"] = _solve_stage(
            prepared,
            graph,
            required,
            objective,
            b6_selected,
            pinned_surrogate,
            "pinned",
            formulation,
            cut_max_iterations,
            cut_total_deterministic_seconds,
        )
        _save_checkpoint(prepared, b6_selected, output_dir, stages)
    pinned = stages.get("pinnedSurrogate")
    if pinned is not None and _proven_infeasible(pinned) and "tradeoff" not in stages:
        stages["tradeoff"] = _solve_stage(
            prepared,
            graph,
            required,
            objective,
            b6_selected,
            pinned_surrogate,
            "tradeoff",
            formulation,
            cut_max_iterations,
            cut_total_deterministic_seconds,
        )
        _save_checkpoint(prepared, b6_selected, output_dir, stages)
    return {
        **base,
        "status": "PASS",
        "privateOptimizationPerformed": True,
        "stages": stages,
        "limitations": [
            "INFEASIBLE is reported only for CP-SAT INFEASIBLE, never for UNKNOWN.",
            "A surrogate optimum is not a fixed-frame IoU optimum.",
            "Mechanical connectivity is independently reconstructed after every witness.",
        ],
    }


def _preflight(
    prepared: PreparedCase,
    selected: tuple[int, ...],
    graph: ConnectivityGraph,
    audit: ContactGraphAudit,
    cut_max_iterations: int,
    cut_total_deterministic_seconds: float,
) -> dict[str, object]:
    witness = _verify_witness(
        prepared,
        selected,
        linearized_mean_iou_objective(prepared.source_counts, prepared.control_views),
        _fifty_percent_requirements(prepared),
        _views_for_selection(prepared, selected),
    )
    component_count = selected_graph_component_count(graph, selected)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": prepared.case_id,
        "sourceSha256": sha256(prepared.source).hexdigest(),
        "candidateUniverse": {
            "count": len(prepared.candidates),
            "baseModelFingerprint": prepared.base_fingerprint,
            "orderedCandidateIdsSha256": sha256(
                "\n".join(
                    stable_placement_id(item.placement) for item in prepared.candidates
                ).encode()
            ).hexdigest(),
            "lockedPlacementIds": [stable_placement_id(item) for item in prepared.locked],
        },
        "connectivitySemantics": {
            "edgeDefinition": (
                "exact matching vertical stud-system connectors after world transform; "
                "overlapping placements excluded"
            ),
            "edgeCount": len(graph.edges),
            "enumeration": asdict(graph.metrics),
            "naiveSubsetAudit": asdict(audit),
            "b6WitnessComponentCount": component_count,
            "b6WitnessIndependentMechanical": witness["mechanical"],
            "indexedEnumerationExpected": (
                "candidate_pair_comparisons counts pairs sharing a transformed connector "
                "coordinate; with zero overlap and incompatibility rejections, each compared "
                "pair is an exact compatible contact."
            ),
        },
        "b6Witness": {
            "selectedCandidateIndices": list(selected),
            "partCount": witness["partCount"],
            "surrogateObjectiveValue": witness["surrogateObjectiveValue"],
            "fixedFrameMeanIouExact": witness["fixedFrameMeanIouExact"],
            "projectionHashes": _projection_hashes(_mask(prepared, selected)),
        },
        "modelSafeguards": {
            "maximumCompleteMechanicalEdges": MAX_CONNECTIVITY_EDGES,
            "flowReadiness": {
                "ready": len(graph.edges) <= MAX_CONNECTIVITY_EDGES,
                "blocker": None
                if len(graph.edges) <= MAX_CONNECTIVITY_EDGES
                else "Complete graph exceeds the flow formulation edge limit.",
                "expectedDirectedFlowVariables": 2 * len(graph.edges),
            },
            "cutGenerationReadiness": {
                "ready": True,
                "completeFlowVariablesAvoided": 2 * len(graph.edges),
                "maximumIterations": cut_max_iterations,
                "totalDeterministicSeconds": cut_total_deterministic_seconds,
            },
            "flow": (
                "sparse directed single-commodity flow; one unit demanded by each selected "
                "candidate and non-root locked placement"
            ),
            "solver": {
                "randomSeed": 0,
                "workers": 1,
                "deterministicTimeSeconds": DETERMINISTIC_TIME_LIMIT_SECONDS,
            },
        },
    }


def _contact_audit(prepared: PreparedCase, graph: ConnectivityGraph) -> ContactGraphAudit:
    """Build a small deterministic audit that necessarily exercises real contacts.

    The old positional prefix often contained no mating placements, so matching
    two empty enumerations did not validate the positive contact path.
    """
    all_placements = tuple(candidate.placement for candidate in prepared.candidates) + tuple(
        prepared.locked
    )
    endpoint_ids = {
        endpoint
        for edge in graph.edges[: max(1, CONTACT_GRAPH_AUDIT_SUBSET_SIZE // 4)]
        for endpoint in (edge.first_candidate_index, edge.second_candidate_index)
    }
    selected_ids = sorted(endpoint_ids)
    for index in range(len(all_placements)):
        if len(selected_ids) >= CONTACT_GRAPH_AUDIT_SUBSET_SIZE - 1:
            break
        if index not in endpoint_ids:
            selected_ids.append(index)
    subset = [all_placements[index] for index in selected_ids]
    local_index = {global_index: index for index, global_index in enumerate(selected_ids)}
    positive_pairs = tuple(
        (local_index[edge.first_candidate_index], local_index[edge.second_candidate_index])
        for edge in graph.edges
        if edge.first_candidate_index in local_index and edge.second_candidate_index in local_index
    )
    graph_pairs = {
        (edge.first_candidate_index, edge.second_candidate_index) for edge in graph.edges
    }
    negative_pair = next(
        (
            (first, second)
            for first, first_global in enumerate(selected_ids)
            for second, second_global in enumerate(selected_ids[first + 1 :], start=first + 1)
            if tuple(sorted((first_global, second_global))) not in graph_pairs
        ),
        None,
    )
    # A duplicated known placement is an intentional, deterministic overlap
    # control for the matcher; it is not a candidate-universe change.
    subset.append(subset[0])
    overlap_pair = (0, len(subset) - 1)
    return audit_contact_graph_subset(
        subset,
        required_positive_pairs=positive_pairs,
        required_negative_pairs=() if negative_pair is None else (negative_pair,),
        required_overlapping_pairs=(overlap_pair,),
    )


def _solve_stage(
    prepared: PreparedCase,
    graph: ConnectivityGraph,
    required: tuple[CoarseRequirement, ...],
    objective: LinearizedMeanIouObjective,
    b6_selected: tuple[int, ...],
    pinned_surrogate: int,
    stage: str,
    formulation: str,
    cut_max_iterations: int,
    cut_total_deterministic_seconds: float,
) -> dict[str, object]:
    built, _compression = build_compressed_iou_dominance_model(
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
        candidate_ids = requirement.candidate_ids
        built.model.add(sum(built.selected[index] for index in candidate_ids) >= 1)
    connectivity: dict[str, object]
    selectable_roots: tuple[cp_model.IntVar, ...] = ()
    if formulation == "flow":
        encoding = add_single_component_constraint(built.model, built.selected, graph)
        connectivity = {"formulation": "flow", "encoding": asdict(encoding)}
    else:
        selectable_roots = add_selectable_root_variables(built.model, built.selected, graph)
        connectivity = {
            "formulation": "iterative-separator-cuts",
            "selectableRootVariableCount": len(selectable_roots),
            "maximumIterations": cut_max_iterations,
            "totalDeterministicSeconds": cut_total_deterministic_seconds,
        }
    target_mask = _mask(prepared, b6_selected)
    exact_constraints = 0
    if stage in {"exact-feasibility", "exact-minimum-parts"}:
        exact_constraints = add_exact_mask_constraints(
            built.model,
            built.selected,
            prepared.candidate_rasters,
            prepared.locked_pixels,
            target_mask,
        )
        if stage == "exact-minimum-parts":
            built.model.minimize(sum(built.selected))
    elif stage == "pinned":
        _pin_surrogate(built.model, built, objective, pinned_surrogate)
        built.model.minimize(sum(built.selected))
    else:
        _maximize_surrogate(built.model, built, objective)
    if formulation == "flow":
        result, solver = solve_built_iou_dominance_model(
            built, deterministic_time_seconds=DETERMINISTIC_TIME_LIMIT_SECONDS
        )
        cut_diagnostics: dict[str, object] = {"iterationCount": 0, "cutCount": 0}
    else:
        result, solver, cut_diagnostics = _solve_with_separator_cuts(
            built,
            graph,
            selectable_roots,
            max_iterations=cut_max_iterations,
            total_deterministic_seconds=cut_total_deterministic_seconds,
        )
    model_hash = model_proto_sha256(built.model)
    has_connected_witness = result.status in {"OPTIMAL", "FEASIBLE"} and (
        selected_graph_component_count(graph, result.selected_ids) == 1
    )
    reported_solver_status = (
        result.status if result.status == "INFEASIBLE" or has_connected_witness else "UNKNOWN"
    )
    payload: dict[str, object] = {
        "status": _stage_status(reported_solver_status),
        "solver": asdict(result),
        "solverModelProtoSha256": model_hash,
        "connectivity": connectivity,
        "cutGeneration": cut_diagnostics,
        "exactMaskConstraintCount": exact_constraints,
        "solverObjectiveValue": solver.objective_value
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
        "solverBestObjectiveBound": solver.best_objective_bound
        if result.status in {"OPTIMAL", "FEASIBLE"}
        else None,
    }
    if has_connected_witness:
        witness = _verify_witness(prepared, result.selected_ids, objective, required, result.views)
        actual_mask = _mask(prepared, result.selected_ids)
        payload["witness"] = {
            **witness,
            "componentCountFromExactGraph": selected_graph_component_count(
                graph, result.selected_ids
            ),
            "fixedMaskXorByView": _mask_xor(target_mask, actual_mask),
            "targetMaskExactlyPreserved": actual_mask == target_mask
            if stage in {"exact-feasibility", "exact-minimum-parts"}
            else None,
        }
    return payload


def _solve_with_separator_cuts(
    built: IoUDominanceModel,
    graph: ConnectivityGraph,
    selectable_roots: tuple[cp_model.IntVar, ...],
    *,
    max_iterations: int = CUT_GENERATION_MAX_ITERATIONS,
    total_deterministic_seconds: float = CUT_GENERATION_TOTAL_DETERMINISTIC_SECONDS,
) -> tuple[IoUDominanceResult, cp_model.CpSolver, dict[str, object]]:
    """Solve a relaxed master, adding only cuts required by its disconnected incumbents."""
    consumed = 0.0
    cut_count = 0
    added_cut_identifiers: set[str] = set()
    iterations: list[dict[str, object]] = []
    initial_constraint_count = len(built.model.proto.constraints)
    fixed_root = graph.candidate_count if graph.locked_count else None
    last_result: IoUDominanceResult | None = None
    last_solver: cp_model.CpSolver | None = None
    termination = "ITERATION_LIMIT"
    for iteration in range(1, max_iterations + 1):
        remaining = total_deterministic_seconds - consumed
        if remaining <= 0:
            termination = "DETERMINISTIC_TIME_LIMIT"
            break
        result, solver = solve_built_iou_dominance_model(
            built,
            deterministic_time_seconds=min(DETERMINISTIC_TIME_LIMIT_SECONDS, remaining),
        )
        last_result, last_solver = result, solver
        consumed += result.deterministic_time_consumed or result.deterministic_time_seconds
        iteration_diagnostic: dict[str, object] = {
            "iteration": iteration,
            "solverStatus": result.status,
            "solverObjectiveValue": solver.objective_value
            if result.status in {"OPTIMAL", "FEASIBLE"}
            else None,
            "solverBestObjectiveBound": solver.best_objective_bound
            if result.status in {"OPTIMAL", "FEASIBLE"}
            else None,
            "selectedCandidateCount": len(result.selected_ids),
            "deterministicSecondsConsumed": result.deterministic_time_consumed
            or result.deterministic_time_seconds,
            "allPreviouslyGeneratedCutsPresent": len(built.model.proto.constraints)
            == initial_constraint_count + cut_count,
        }
        if result.status not in {"OPTIMAL", "FEASIBLE"}:
            iterations.append(iteration_diagnostic)
            return (
                result,
                solver,
                {
                    "iterationCount": iteration,
                    "cutCount": cut_count,
                    "totalDeterministicSecondsConsumed": consumed,
                    "termination": result.status,
                    "iterations": iterations,
                },
            )
        root = fixed_root
        if root is None:
            root = next(
                index
                for index, variable in enumerate(selectable_roots)
                if solver.boolean_value(variable)
            )
        components = selected_graph_components(graph, result.selected_ids)
        disconnected = [component for component in components if root not in component]
        iteration_diagnostic["componentCount"] = len(components)
        iteration_diagnostic["componentSizes"] = [len(component) for component in components]
        if not disconnected:
            iteration_diagnostic.update(
                {"newCutsGenerated": 0, "duplicateCutsDetected": 0, "cutIdentifiers": []}
            )
            iterations.append(iteration_diagnostic)
            return (
                result,
                solver,
                {
                    "iterationCount": iteration,
                    "cutCount": cut_count,
                    "totalDeterministicSecondsConsumed": consumed,
                    "termination": "CONNECTED_WITNESS",
                    "iterations": iterations,
                },
            )
        added_this_iteration = 0
        duplicates = 0
        cut_identifiers: list[str] = []
        all_proposed_cuts_violated = True
        for component in disconnected:
            for cut in separator_cuts(graph, component):
                identifier = cut.canonical_identifier
                cut_identifiers.append(identifier)
                representative_selected = (
                    cut.representative_candidate_index is None
                    or cut.representative_candidate_index in result.selected_ids
                )
                boundary_selected = any(
                    index in result.selected_ids for index in cut.boundary_candidate_indices
                )
                violated = representative_selected and not boundary_selected
                all_proposed_cuts_violated = all_proposed_cuts_violated and violated
                if identifier in added_cut_identifiers:
                    duplicates += 1
                    continue
                if not violated:
                    raise AssertionError("A separator cut must be violated by its source witness.")
                add_separator_cut(
                    built.model,
                    built.selected,
                    cut,
                    fixed_root_node=fixed_root,
                    selectable_roots=selectable_roots,
                )
                added_cut_identifiers.add(identifier)
                cut_count += 1
                added_this_iteration += 1
        iteration_diagnostic.update(
            {
                "newCutsGenerated": added_this_iteration,
                "duplicateCutsDetected": duplicates,
                "cutIdentifiers": cut_identifiers,
                "everyProposedCutViolatedByWitness": all_proposed_cuts_violated,
            }
        )
        iterations.append(iteration_diagnostic)
        if not added_this_iteration:
            termination = "NO_NEW_VIOLATED_CUT"
            break
    if last_result is None or last_solver is None:
        raise AssertionError("Cut generation did not attempt a solve.")
    return (
        last_result,
        last_solver,
        {
            "iterationCount": len(iterations),
            "cutCount": cut_count,
            "totalDeterministicSecondsConsumed": consumed,
            "termination": termination,
            "connectivityProven": False,
            "iterations": iterations,
        },
    )


def _maximize_surrogate(
    model: cp_model.CpModel,
    built: IoUDominanceModel,
    objective: LinearizedMeanIouObjective,
) -> None:
    model.maximize(_surrogate_expression(built, objective))


def _pin_surrogate(
    model: cp_model.CpModel,
    built: IoUDominanceModel,
    objective: LinearizedMeanIouObjective,
    value: int,
) -> None:
    model.add(_surrogate_expression(built, objective) == value)


def _surrogate_expression(
    built: IoUDominanceModel, objective: LinearizedMeanIouObjective
) -> cp_model.LinearExpr:
    true_positives = built.true_positives
    false_positives = built.false_positives
    return cp_model.LinearExpr.Sum(
        [
            objective.true_positive_coefficients[view] * true_positives[view]
            + objective.false_positive_coefficients[view] * false_positives[view]
            for view in ("front", "side", "top")
        ]
    )


def _fifty_percent_requirements(prepared: PreparedCase) -> tuple[CoarseRequirement, ...]:
    from app.conversion.m13c_silhouette_equivalence_audit import m13b_fixed_frame_bounds

    bounds = m13b_fixed_frame_bounds(
        prepared.preprocessing.source_vertices, prepared.preprocessing.target_cells
    )
    records = occupancy_requirements(
        prepared.requirements, prepared.source_pixels, lambda pixel: _coarse_region(pixel, bounds)
    )
    policy = next(policy for policy in POLICIES if policy.name == "source-occupancy-ge-50-percent")
    return tuple(requirements_for_policy(policy, records))


def _views_for_selection(
    prepared: PreparedCase, selected: tuple[int, ...]
) -> dict[str, dict[str, int]]:
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    # The verifier compares this argument to an independently rendered result; use a one-model
    # solve-free calculation from the exact candidate raster union only for the preflight call.
    pixels = _mask(prepared, selected)
    views = {
        view: {
            "truePositives": sum(
                pixel[0] == view and pixel in prepared.source_pixels for pixel in pixels
            ),
            "falsePositives": sum(
                pixel[0] == view and pixel not in prepared.source_pixels for pixel in pixels
            ),
            "falseNegatives": sum(pixel[0] == view for pixel in prepared.source_pixels - pixels),
        }
        for view in ("front", "side", "top")
    }
    if surrogate_value(views, objective) is None:  # pragma: no cover - keeps the objective explicit
        raise AssertionError("Unreachable")
    return views


def _mask(prepared: PreparedCase, selected: tuple[int, ...]) -> frozenset[tuple[str, int, int]]:
    return frozenset(prepared.locked_pixels).union(
        *(prepared.candidate_rasters[index] for index in selected)
    )


def _mask_xor(
    expected: frozenset[tuple[str, int, int]], actual: frozenset[tuple[str, int, int]]
) -> dict[str, int]:
    return {
        view: sum(pixel[0] == view for pixel in expected ^ actual)
        for view in ("front", "side", "top")
    }


def _projection_hashes(mask: frozenset[tuple[str, int, int]]) -> dict[str, str]:
    return {
        view: sha256(
            "\n".join(
                f"{x}:{y}" for _, x, y in sorted(pixel for pixel in mask if pixel[0] == view)
            ).encode()
        ).hexdigest()
        for view in ("front", "side", "top")
    }


def _b6_selection(path: Path) -> tuple[int, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    arms = payload.get("arms") if isinstance(payload, dict) else None
    if not isinstance(arms, list):
        raise ValueError("B6 summary must contain policy arms.")
    for arm in arms:
        if isinstance(arm, dict) and arm.get("policy") == "source-occupancy-ge-50-percent":
            witness = arm.get("witness")
            selected = (
                witness.get("selectedCandidateIndices") if isinstance(witness, dict) else None
            )
            if isinstance(selected, list) and all(isinstance(item, int) for item in selected):
                return tuple(selected)
    raise ValueError("B6 50% policy witness is absent or malformed.")


def _validate_selection(prepared: PreparedCase, selected: tuple[int, ...]) -> None:
    if len(set(selected)) != len(selected) or any(
        index < 0 or index >= len(prepared.candidates) for index in selected
    ):
        raise ValueError(
            "B6 selected candidate indices are invalid for the reconstructed universe."
        )


def _stage_status(status: str) -> str:
    if status == "INFEASIBLE":
        return "PROVEN_INFEASIBLE"
    if status == "OPTIMAL":
        return "OPTIMAL"
    if status == "FEASIBLE":
        return "FEASIBLE"
    return "UNKNOWN"


def _proven_infeasible(stage: object) -> bool:
    return isinstance(stage, dict) and stage.get("status") == "PROVEN_INFEASIBLE"


def _checkpoint_provenance(prepared: PreparedCase, selected: tuple[int, ...]) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "caseId": prepared.case_id,
        "sourceSha256": sha256(prepared.source).hexdigest(),
        "b6Selected": list(selected),
    }


def _load_checkpoint(
    prepared: PreparedCase, selected: tuple[int, ...], output_dir: Path | None, resume: bool
) -> dict[str, object]:
    if output_dir is None or not resume:
        return {}
    path = output_dir / CHECKPOINT_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("provenance") != _checkpoint_provenance(
        prepared, selected
    ):
        raise ValueError("Checkpoint provenance does not match the current B7 inputs.")
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        raise ValueError("Checkpoint stages are malformed.")
    return stages


def _save_checkpoint(
    prepared: PreparedCase,
    selected: tuple[int, ...],
    output_dir: Path | None,
    stages: dict[str, object],
) -> None:
    if output_dir is not None:
        _write_json_atomically(
            output_dir / CHECKPOINT_FILENAME,
            {
                "checkpointState": "INCOMPLETE_UNVALIDATED",
                "provenance": _checkpoint_provenance(prepared, selected),
                "stages": stages,
            },
        )


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(payload, indent=2, sort_keys=True))
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
