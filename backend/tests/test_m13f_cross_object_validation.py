from fractions import Fraction
from pathlib import Path

from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement
from app.conversion.m13f_duck_occupancy_coverage_ablation import (
    CoveragePolicy,
    occupancy_requirements,
    requirements_for_policy,
)
from scripts.run_m13f_cross_object_validation import CASE_IDS, prepare_case

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts/m7b-corpus/manifest.json"


def test_exact_half_threshold_is_inclusive() -> None:
    requirement = CoarseRequirement(("front", 0, 0), (0,), False)
    records = occupancy_requirements(
        (requirement,), {("front", 0, 0)}, lambda _: {("front", 0, 0), ("front", 1, 0)}
    )
    assert requirements_for_policy(
        CoveragePolicy("source-occupancy-ge-50-percent", Fraction(1, 2)), records
    ) == (requirement,)


def test_real_artifact_preflight_reconstructs_each_non_duck_case() -> None:
    for case_id in CASE_IDS:
        summary = (
            ROOT
            / "artifacts"
            / ("m13b-mansion-pilot" if case_id == "mansion" else "m13b-man-final")
            / "summary.json"
        )
        prepared = prepare_case(MANIFEST, case_id, summary)
        assert prepared.case_id == case_id
        assert prepared.candidates
        assert prepared.requirements
