"""Run the opt-in M13F Duck false-positive and coarse-coverage experiment."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Collection, Sequence
from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core
from app.conversion.evaluation_alignment import stable_placement_id
from app.conversion.m9a_experimental_feasibility import locked_source_profile_coverage
from app.conversion.m12c_wedge_fidelity_experiment import validate_completed_arrangement
from app.conversion.m13c_silhouette_equivalence_audit import (
    candidate_preflight_failures,
    m13b_no_wedge_candidate_preflight,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
)
from app.conversion.m13e_duck_control_hint_experiment import (
    DUCK_CANDIDATE_COUNT,
    DUCK_GRID,
    DUCK_MAX_PARTS,
    control_candidate_indices,
)
from app.conversion.m13f_duck_fp_coarse_ablation import (
    attribute_control_false_positives,
    coarse_coverage_satisfied,
    support_preprocessing_caveat,
)
from app.conversion.m13f_duck_reconstruction_audit import projection_hashes
from app.conversion.real_world_benchmark import load_manifest, verify_case_source
from app.conversion.surface_grid_v4 import _Candidate
from scripts.run_m13e_duck_hint import _load_duck_summary
from scripts.run_m13e_duck_iou_dominance import run_duck_iou_dominance

SCHEMA_VERSION = "m13f-duck-fp-coarse-ablation-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/m13f-duck-fp-coarse-ablation")
    )
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Refusing to overwrite an existing experiment output directory.")
    payload = run_experiment(args.manifest, args.summary)
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["status"] != "RESULT_VERIFICATION_FAILED" else 1


def run_experiment(manifest_path: Path, summary_path: Path) -> dict[str, object]:
    """Run exactly the historical and mandatory-coarse-relaxed B5 solver arms."""
    record = _load_duck_summary(summary_path)
    cases = {case.case_id: case for case in load_manifest(manifest_path).cases}
    if set(cases) != {"duck"}:
        raise ValueError("M13F requires a manifest containing only the pinned Duck case.")
    case = cases["duck"]
    source = verify_case_source(case)
    control = reconstruct_placements(record["control"]["placementIds"])
    preprocessing = reconstruct_m13b_preprocessing(source, core.GridSize(**DUCK_GRID), case.up_axis)
    locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
    preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
    failures = candidate_preflight_failures(DUCK_CANDIDATE_COUNT, preflight.candidates, control)
    if (
        failures
        or preflight.candidate_rasters is None
        or preflight.source_pixels is None
        or preflight.locked_pixels is None
    ):
        raise ValueError("; ".join(failures) or "M13F candidate reconstruction failed.")
    selected = control_candidate_indices(
        preflight.candidates,
        [stable_placement_id(item) for item in control if item.brick_type.shape == "rectangular"],
    )
    fixed_coverage = locked_source_profile_coverage(locked) & preprocessing.required_pixels

    def historically_valid(candidate_ids: tuple[int, ...]) -> bool:
        placements = (*locked, *(preflight.candidates[index].placement for index in candidate_ids))
        return (
            validate_completed_arrangement(
                placements, preprocessing.protected_empty_cells, DUCK_MAX_PARTS
            ).is_valid
            and coarse_coverage_satisfied(
                candidates=preflight.candidates,
                selected_ids=candidate_ids,
                required_pixels=preprocessing.required_pixels,
                fixed_coverage_pixels=fixed_coverage,
            )["satisfied"]
        )

    attribution = attribute_control_false_positives(
        candidates=preflight.candidates,
        candidate_rasters=preflight.candidate_rasters,
        selected_ids=selected,
        source_pixels=preflight.source_pixels,
        locked_pixels=preflight.locked_pixels,
        historical_valid=historically_valid,
    )
    selected_pixels = frozenset(
        pixel for index in selected for pixel in preflight.candidate_rasters[index]
    )
    arms = {
        "historicalControl": run_duck_iou_dominance(
            case, record, compressed=True, mean_iou_guided=True
        )["record"],
        "coarseCoverageRelaxed": run_duck_iou_dominance(
            case,
            record,
            compressed=True,
            mean_iou_guided=True,
            enforce_mandatory_coverage=False,
        )["record"],
    }
    for name, arm in arms.items():
        _label_coarse_status(
            arm, preflight.candidates, preprocessing.required_pixels, fixed_coverage, name
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "privateOptimizationPerformed": True,
        "provenance": {
            "sourceSha256": sha256(source).hexdigest(),
            "candidateCount": len(preflight.candidates),
            "candidateIdsSha256": sha256(
                "\n".join(
                    stable_placement_id(item.placement) for item in preflight.candidates
                ).encode()
            ).hexdigest(),
            "projectionHashes": projection_hashes(
                source=preflight.source_pixels,
                locked=preflight.locked_pixels,
                selectedCandidates=selected_pixels,
                control=frozenset(preflight.locked_pixels) | selected_pixels,
            ),
        },
        "errorAttribution": attribution,
        "arms": arms,
        "supportPreprocessingCaveat": support_preprocessing_caveat(),
        "limitations": [
            (
                "Single-candidate removals hold all other selections fixed and do not establish "
                "simultaneous removability."
            ),
            (
                "The relaxed arm is historically inadmissible when it violates mandatory coarse "
                "coverage."
            ),
            (
                "Surrogate improvement does not prove an exact fixed-frame or frozen "
                "silhouette-v1 mean-IoU improvement."
            ),
        ],
    }


def _label_coarse_status(
    arm: dict[str, object],
    candidates: Sequence[_Candidate],
    required_pixels: Collection[tuple[str, int, int]],
    fixed_coverage: Collection[tuple[str, int, int]],
    name: str,
) -> None:
    result = arm.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("selectedCandidateIndices"), list):
        return
    coarse = coarse_coverage_satisfied(
        candidates=candidates,
        selected_ids=result["selectedCandidateIndices"],
        required_pixels=required_pixels,
        fixed_coverage_pixels=fixed_coverage,
    )
    result["mandatoryCoarseCoverage"] = coarse
    if name == "coarseCoverageRelaxed" and not coarse["satisfied"]:
        result["historicalAdmissibility"] = "HISTORICALLY_INADMISSIBLE_COARSE_COVERAGE_VIOLATED"
    else:
        result["historicalAdmissibility"] = "SATISFIES_HISTORICAL_COARSE_COVERAGE"


if __name__ == "__main__":
    raise SystemExit(main())
