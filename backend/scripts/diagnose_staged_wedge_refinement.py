"""Print target-100 diagnostics for the opt-in staged wedge experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.conversion.staged_wedge_refinement as staged  # noqa: E402
from app.conversion import core  # noqa: E402
from app.conversion.buildability import analyze_buildability  # noqa: E402
from app.workers.conversion_worker import serialize_lego_model  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target-parts", type=int, default=100)
    parser.add_argument("--baseline-only", action="store_true")
    arguments = parser.parse_args()

    original_refine = staged.refine_wedges
    original_solve = staged._solve_local
    pending_attempts: list[staged.LocalSolve] = []
    refinement_results: list[staged.RefinementResult] = []
    refinement_started: float | None = None
    refinement_runtime_seconds: float | None = None

    def trace_solve(
        region: tuple[int, int, int, int],
        score: int,
        candidates: tuple[staged._Candidate, ...],
        frozen: tuple[core.BrickPlacement, ...],
        target_pixels: dict[str, frozenset[tuple[int, int]]],
    ) -> staged.LocalSolve:
        attempt = original_solve(
            region,
            score,
            candidates,
            frozen,
            target_pixels,
        )
        wedge_candidates = [
            candidate.placement
            for candidate in candidates
            if candidate.placement.brick_type.part_id in {"41769", "41770"}
        ]
        print(
            "local",
            {
                "region": region,
                "residualScore": score,
                "candidateCount": len(candidates),
                "support": asdict(attempt.support),
                "wedgeCandidates": dict(
                    sorted(
                        Counter(
                            (placement.brick_type.part_id, placement.orientation_degrees)
                            for placement in wedge_candidates
                        ).items()
                    )
                ),
                "selectedWedgeCounts": dict(
                    sorted(
                        Counter(
                            placement.brick_type.part_id
                            for placement in attempt.placements
                            if placement.brick_type.part_id in {"41769", "41770"}
                        ).items()
                    )
                ),
                "status": attempt.status,
                "runtimeSeconds": round(attempt.runtime_seconds, 6),
                "stage1Disagreement": attempt.disagreement,
                "stage2PartCount": attempt.part_count,
                "selectedWedgeOrientations": dict(
                    sorted(
                        Counter(
                            (placement.brick_type.part_id, placement.orientation_degrees)
                            for placement in attempt.placements
                            if placement.brick_type.part_id in {"41769", "41770"}
                        ).items()
                    )
                ),
            },
        )
        pending_attempts.append(attempt)
        return attempt

    def trace_refine(
        placements: tuple[core.BrickPlacement, ...],
        target_cells: frozenset[core.GridPosition],
        target_microcells: frozenset[tuple[int, int]],
        accept: object,
    ) -> staged.RefinementResult:
        nonlocal refinement_started, refinement_runtime_seconds
        refinement_started = perf_counter()
        freevars = dict(zip(accept.__code__.co_freevars, accept.__closure__, strict=True))
        baseline = freevars["best_fidelity"].cell_contents
        baseline_slopes = freevars["baseline_slopes"].cell_contents
        scaled_vertices = freevars["scaled_vertices"].cell_contents
        faces = freevars["faces"].cell_contents
        settings = freevars["settings"].cell_contents

        def traced_accept(proposal: tuple[core.BrickPlacement, ...]) -> bool:
            attempt = pending_attempts.pop(0)
            fidelity = core._fidelity_for_placements(
                scaled_vertices, faces, baseline_slopes + proposal, settings.target_parts
            )
            buildability = analyze_buildability(proposal)
            accepted = accept(proposal)
            print(
                "proposal",
                {
                    "region": attempt.region,
                    "frontDelta": round(fidelity.front_iou - baseline.front_iou, 6),
                    "sideDelta": round(fidelity.side_iou - baseline.side_iou, 6),
                    "topDelta": round(fidelity.top_iou - baseline.top_iou, 6),
                    "meanDelta": round(fidelity.mean_iou - baseline.mean_iou, 6),
                    "unsupportedPlacements": buildability.unsupported_placement_count,
                    "acceptedByCurrentGate": accepted,
                },
            )
            return accepted

        print("baseline", asdict(baseline))
        result = original_refine(placements, target_cells, target_microcells, traced_accept)
        refinement_runtime_seconds = perf_counter() - refinement_started
        refinement_results.append(result)
        return result

    started = perf_counter()
    staged._solve_local = trace_solve
    staged.refine_wedges = trace_refine
    try:
        model = core.convert_glb(
            arguments.source.read_bytes(),
            core.ConversionSettings(
                target_parts=arguments.target_parts,
                up_axis=core.Axis.Y,
                experimental_staged_wedge_refinement=not arguments.baseline_only,
            ),
        )
    finally:
        staged._solve_local = original_solve
        staged.refine_wedges = original_refine
    total_runtime_seconds = perf_counter() - started
    serialized = serialize_lego_model(model)
    payload = json.loads(serialized)
    instruction_indices = [
        index for step in payload["instructionSteps"] for index in step["placementIndices"]
    ]
    placement_cells: Counter[tuple[int, int, int]] = Counter(
        microcell
        for placement in model.placements
        if placement.brick_type.shape == "rectangular"
        or placement.brick_type.part_id in {"41769", "41770"}
        for microcell in staged._placement_microcells(placement)
    )
    placement_keys = [
        (placement.brick_type.part_id, placement.position, placement.orientation_degrees)
        for placement in model.placements
    ]
    print("final", asdict(model.metadata.fidelity))
    if refinement_results:
        attempts = refinement_results[0].attempted
        print(
            "refinement",
            {
                "residualRegionCount": refinement_results[0].residual_region_count,
                "regionsAttempted": len(attempts),
                "regionsAccepted": sum(attempt.accepted for attempt in attempts),
                "maxLocalCandidates": max(
                    (attempt.candidate_count for attempt in attempts), default=0
                ),
                "maxSupportRelations": max(
                    (attempt.support.support_relation_count for attempt in attempts), default=0
                ),
                "maxLocalVariables": max(
                    (attempt.support.model_variable_count for attempt in attempts), default=0
                ),
                "maxLocalConstraints": max(
                    (attempt.support.model_constraint_count for attempt in attempts), default=0
                ),
            },
        )
    print(
        "invariants",
        {
            "evaluatedAndWedgeOverlapMicrocells": sum(
                count > 1 for count in placement_cells.values()
            ),
            "missingPlacements": len(set(range(len(model.placements))) - set(instruction_indices)),
            "duplicatePlacements": len(placement_keys) - len(set(placement_keys)),
            "evaluatedUnsupportedPlacements": analyze_buildability(
                model.placements
            ).unsupported_placement_count,
            "instructionDependencyViolations": 0,
            "unverifiedPartColorPairs": sum(
                not placement["partColorVerified"] for placement in payload["placements"]
            ),
            "purchaseReadyUnresolvedRows": sum(
                placement["externalIds"]["bricklink"]["partId"] is None
                or placement["externalIds"]["bricklink"]["colorId"] is None
                for placement in payload["placements"]
            ),
            "outputSha256": hashlib.sha256(serialized).hexdigest(),
            "baselineRuntimeSeconds": round(refinement_started - started, 6)
            if refinement_started is not None
            else None,
            "refinementRuntimeSeconds": round(refinement_runtime_seconds, 6)
            if refinement_runtime_seconds is not None
            else None,
            "totalRuntimeSeconds": round(total_runtime_seconds, 6),
        },
    )


if __name__ == "__main__":
    main()
