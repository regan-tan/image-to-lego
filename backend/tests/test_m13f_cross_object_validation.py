from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.conversion.m13c_silhouette_equivalence_audit import AuditError
from app.conversion.m13f_duck_coarse_budget_frontier import CoarseRequirement
from app.conversion.m13f_duck_occupancy_coverage_ablation import (
    CoveragePolicy,
    occupancy_requirements,
    requirements_for_policy,
)
from scripts.run_m13f_cross_object_validation import CASE_IDS, prepare_case

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts/m7b-corpus/manifest.json"
SUMMARY_NAMES = {"mansion": "m13b-mansion-pilot", "realistic-man": "m13b-man-final"}


def test_exact_half_threshold_is_inclusive() -> None:
    requirement = CoarseRequirement(("front", 0, 0), (0,), False)
    records = occupancy_requirements(
        (requirement,), {("front", 0, 0)}, lambda _: {("front", 0, 0), ("front", 1, 0)}
    )
    assert requirements_for_policy(
        CoveragePolicy("source-occupancy-ge-50-percent", Fraction(1, 2)), records
    ) == (requirement,)


def _summary_path(root: Path, case_id: str) -> Path:
    return root / "artifacts" / SUMMARY_NAMES[case_id] / "summary.json"


def _required_private_artifact_paths(root: Path) -> tuple[Path, ...]:
    return (root / "artifacts/m7b-corpus/manifest.json",) + tuple(
        _summary_path(root, case_id) for case_id in CASE_IDS
    )


def _run_real_artifact_preflight(root: Path, prepare: object = prepare_case) -> None:
    missing = [path for path in _required_private_artifact_paths(root) if not path.is_file()]
    if missing:
        pytest.skip(
            "requires ignored private M7B corpus manifest and M13B non-Duck summaries; "
            "they are unavailable in this environment"
        )
    for case_id in CASE_IDS:
        assert callable(prepare)
        prepared = prepare(
            root / "artifacts/m7b-corpus/manifest.json", case_id, _summary_path(root, case_id)
        )
        assert prepared.case_id == case_id
        assert prepared.candidates
        assert prepared.requirements


def test_real_artifact_preflight_reconstructs_each_non_duck_case() -> None:
    _run_real_artifact_preflight(ROOT)


def test_real_artifact_preflight_skips_when_private_inputs_are_unavailable(
    tmp_path: Path,
) -> None:
    with pytest.raises(pytest.skip.Exception, match="requires ignored private M7B corpus"):
        _run_real_artifact_preflight(tmp_path)


def test_real_artifact_preflight_runs_when_required_inputs_exist(tmp_path: Path) -> None:
    for path in _required_private_artifact_paths(tmp_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    calls: list[tuple[Path, str, Path]] = []

    def prepare(manifest: Path, case_id: str, summary: Path) -> SimpleNamespace:
        calls.append((manifest, case_id, summary))
        return SimpleNamespace(case_id=case_id, candidates=(object(),), requirements=(object(),))

    _run_real_artifact_preflight(tmp_path, prepare)

    assert [case_id for _, case_id, _ in calls] == list(CASE_IDS)


def test_real_artifact_preflight_propagates_reconstruction_errors_when_inputs_exist(
    tmp_path: Path,
) -> None:
    for path in _required_private_artifact_paths(tmp_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    def prepare(_: Path, __: str, ___: Path) -> SimpleNamespace:
        raise AuditError("reconstruction mismatch")

    with pytest.raises(AuditError, match="reconstruction mismatch"):
        _run_real_artifact_preflight(tmp_path, prepare)
