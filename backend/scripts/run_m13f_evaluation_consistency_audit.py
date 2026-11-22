"""Run the no-solver M13F-B5 Duck metric and witness consistency audit."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m13c_silhouette_equivalence_audit import AuditError
from app.conversion.m13e_duck_mean_iou_guided import linearized_mean_iou_objective
from app.conversion.m13f_evaluation_consistency_audit import (
    connectivity_recommendation,
    frozen_semantics,
    frozen_source_pixel_counts,
)
from app.conversion.real_world_benchmark import load_manifest
from scripts.run_m13f_duck_coarse_budget_frontier import prepare_frontier
from scripts.run_m13f_duck_minimum_violation_audit import _verify_solver_witness

SCHEMA_VERSION = "m13f-evaluation-consistency-audit-v1"
FIFTY_PERCENT_POLICY = "source-occupancy-ge-50-percent"
RELAXED_POLICY = "fully-relaxed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        help="Optional full corpus manifest used only for non-Duck benchmark discovery.",
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--b4-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run_audit(
        args.manifest,
        args.summary,
        args.b4_summary,
        corpus_manifest_path=args.corpus_manifest,
    )
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(text, end="")
    else:
        if args.output.exists():
            parser.error("Refusing to overwrite an existing audit output.")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


def run_audit(
    manifest_path: Path,
    summary_path: Path,
    b4_summary_path: Path,
    *,
    corpus_manifest_path: Path | None = None,
) -> dict[str, object]:
    """Reconstruct B4 evidence without constructing or solving a CP-SAT model."""
    prepared = prepare_frontier(manifest_path, summary_path)
    summary = _load_summary(b4_summary_path)
    arms = _arms_by_policy(summary)
    fifty = _verify_arm(prepared, arms[FIFTY_PERCENT_POLICY], FIFTY_PERCENT_POLICY)
    relaxed = _verify_arm(prepared, arms[RELAXED_POLICY], RELAXED_POLICY)
    hashes_match = _mask_hashes(fifty) == _mask_hashes(relaxed)
    if not hashes_match:
        raise AuditError("The recorded 50% and fully relaxed fixed-frame masks differ.")
    benchmarks = _discover_benchmarks(corpus_manifest_path or manifest_path)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "privateOptimizationPerformed": False,
        "frozenSilhouetteV1Audit": {
            "semantics": frozen_semantics(),
            "conclusion": (
                "Assembly-dependent source foreground counts are intended legacy semantics, not "
                "a fixed-frame evaluator defect. They make frozen silhouette-v1 unsuitable as "
                "the controlled primary metric across different assemblies."
            ),
            "primaryControlledMetric": "fixed-frame exact TP/FP/FN and Fraction mean IoU",
            "secondaryDiagnosticMetric": "frozen silhouette-v1, reported with native bounds",
        },
        "duck50PercentWitness": fifty,
        "duckFullyRelaxedWitness": relaxed,
        "silhouetteEquivalentFixedFrameMasks": hashes_match,
        "crossObject": benchmarks,
        "connectivityRecommendation": connectivity_recommendation(),
    }


def _load_summary(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError("M13F-B4 summary could not be read.") from error
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion")
        != "m13f-duck-occupancy-coverage-ablation-v1"
    ):
        raise AuditError("Input is not an M13F-B4 occupancy-coverage summary.")
    return value


def _arms_by_policy(summary: dict[str, object]) -> dict[str, dict[str, object]]:
    values = summary.get("arms")
    if not isinstance(values, list):
        raise AuditError("M13F-B4 arms are missing.")
    arms: dict[str, dict[str, object]] = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("policy"), str):
            raise AuditError("M13F-B4 arm is malformed.")
        arms[value["policy"]] = value
    if FIFTY_PERCENT_POLICY not in arms or RELAXED_POLICY not in arms:
        raise AuditError("M13F-B4 lacks the 50% or fully relaxed arm.")
    return arms


def _verify_arm(prepared: object, arm: dict[str, object], policy: str) -> dict[str, object]:
    witness = arm.get("witness")
    if not isinstance(witness, dict):
        raise AuditError(f"M13F-B4 {policy} witness is missing.")
    values = witness.get("selectedCandidateIndices")
    if not isinstance(values, list) or not all(isinstance(value, int) for value in values):
        raise AuditError(f"M13F-B4 {policy} selected candidates are malformed.")
    selected = tuple(cast(int, value) for value in values)
    objective = linearized_mean_iou_objective(prepared.source_counts, prepared.control_views)
    verified = _verify_solver_witness(prepared, selected, objective)
    placements = tuple(prepared.locked) + tuple(
        prepared.candidate_preflight.candidates[index].placement for index in selected
    )
    source_counts = frozen_source_pixel_counts(
        prepared.preprocessing.source_vertices,
        prepared.preprocessing.faces,
        placements,
    )
    return {
        "policy": policy,
        "partCount": verified["partCount"],
        "connectedComponentCount": verified["connectedComponentCount"],
        "isolatedPartIndices": verified["isolatedPartIndices"],
        "mechanical": verified["mechanical"],
        "surrogateObjectiveValue": verified["surrogateObjectiveValue"],
        "fixedFrameMeanIouExact": verified["fixedFrameMeanIouExact"],
        "independentMaskParity": verified["independentMaskParity"],
        "originalHistoricalUnmetCount": verified["unmetRequirementCount"],
        "frozenSilhouetteV1SourceForegroundPixels": source_counts,
        "placementIds": [stable_placement_id(item) for item in placements],
    }


def _mask_hashes(verified: dict[str, object]) -> dict[str, str]:
    parity = cast(dict[str, object], verified["independentMaskParity"])
    views = cast(dict[str, dict[str, object]], parity["views"])
    return {view: cast(str, views[view]["actualSha256"]) for view in ("front", "side", "top")}


def _discover_benchmarks(manifest_path: Path) -> dict[str, object]:
    cases = load_manifest(manifest_path).cases
    available = [
        {"caseId": case.case_id, "characteristics": list(case.characteristics)}
        for case in cases
        if case.case_id != "duck"
    ]
    return {
        "availableNonDuckCases": available,
        "predeclaredPolicy": "source occupancy >= 50%",
        "status": "OPT_IN_INTERFACE_REQUIRED",
        "reason": (
            "The repository has Mansion and realistic-man sources, but no matched M13F policy "
            "summaries/candidate provenance for three-policy comparison. No substitute results "
            "were fabricated or solved automatically."
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
