"""Run the opt-in M13E-B3.4 compressed side- and top-strict Duck arms."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Final

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.m13c_silhouette_equivalence_audit import AuditError  # noqa: E402
from app.conversion.real_world_benchmark import BenchmarkCase, load_manifest  # noqa: E402
from scripts.run_m13e_duck_hint import _load_duck_summary  # noqa: E402
from scripts.run_m13e_duck_iou_dominance import run_duck_iou_dominance  # noqa: E402

SCHEMA_VERSION: Final = "m13e-duck-iou-compressed-split-v1"
FRESH_STRICT_VIEWS: Final = ("side", "top")
HISTORICAL_FRONT_STRICT: Final[dict[str, object]] = {
    "caseId": "duck",
    "strictView": "front",
    "status": "INFEASIBLE",
    "classification": "PROVEN_NO_FRONT_STRICT_DOMINANCE",
    "recordType": "HISTORICAL_REFERENCE",
    "scope": (
        "This accepted B3.3 result proves only that front-strict dominance is "
        "infeasible in the historical candidate model. Its prior "
        "PROVEN_NO_PER_VIEW_DOMINANCE label is not a three-arm proof."
    ),
    "provenance": {
        "artifactDirectory": "artifacts/m13e-duck-iou-compressed-fixed01",
        "sourceSha256": "77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e",
        "candidateCount": 1449,
        "compressedVariables": 1799,
        "compressedConstraints": 1978,
        "originalVariables": 34990,
        "originalConstraints": 35169,
        "compressedCoverageVariables": 350,
        "deterministicTimeBudgetSeconds": 30.0,
        "deterministicTimeSeconds": 0.3060623,
        "wallTimeSeconds": 3.3663583,
        "randomSeed": 0,
        "solverWorkers": 1,
        "controlPreflightRasterXor": 0,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../artifacts/m13e-duck-iou-compressed-split"),
    )
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("The output directory already exists; refusing to overwrite prior results.")
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B3.4 accepts a manifest containing only the pinned Duck case.")
    payload = run_duck_iou_compressed_split(cases["duck"], _load_duck_summary(args.summary))
    summary = payload["summary"]
    records = payload["records"]
    if (
        not isinstance(summary, dict)
        or not isinstance(records, list)
        or any(not isinstance(arm, dict) for arm in records)
    ):
        raise AssertionError("M13E-B3.4 produced invalid arm records.")
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for arm in records:
        strict_view = arm["strictView"]
        (args.output_dir / f"duck-{strict_view}-strict.json").write_text(
            json.dumps(arm, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if summary.get("status") != "VALIDATION_FAILED" else 1


def run_duck_iou_compressed_split(
    case: BenchmarkCase, record: dict[str, object]
) -> dict[str, object]:
    """Run fresh compressed side/top arms and aggregate them with B3.3 front evidence."""
    if not isinstance(case, BenchmarkCase):
        raise AuditError("M13E-B3.4 requires a Duck benchmark case.")
    records: list[dict[str, object]] = [deepcopy(HISTORICAL_FRONT_STRICT)]
    for strict_view in FRESH_STRICT_VIEWS:
        arm = run_duck_iou_dominance(case, record, strict_view=strict_view, compressed=True)[
            "record"
        ]
        arm["classification"] = _arm_classification(
            strict_view, arm["status"], arm["classification"]
        )
        records.append(arm)
    return {
        "summary": {
            "schemaVersion": SCHEMA_VERSION,
            "status": _combined_status(records),
            "classification": _combined_classification(records),
            "frontStrictEvidence": "REFERENCED_B3_3_RESULT_NOT_RERUN",
            "aggregateBudgetNote": (
                "B3.4 runs two fresh 30-second deterministic-time arms. The accepted "
                "front-strict B3.3 result is referenced without rerunning it."
            ),
            "records": records,
        },
        "records": records,
    }


def _combined_status(records: Sequence[object]) -> str:
    statuses = _statuses(records)
    if _has_validation_failure(statuses):
        return "VALIDATION_FAILED"
    if any(status in {"OPTIMAL", "FEASIBLE"} for status in statuses):
        return "WITNESS_FOUND"
    if statuses == ["INFEASIBLE", "INFEASIBLE", "INFEASIBLE"]:
        return "INFEASIBLE"
    return "INCONCLUSIVE"


def _arm_classification(strict_view: str, status: object, original: object) -> object:
    if status == "INFEASIBLE":
        return f"PROVEN_NO_{strict_view.upper()}_STRICT_DOMINANCE"
    return original


def _combined_classification(records: Sequence[object]) -> str:
    return {
        "VALIDATION_FAILED": "VALIDATION_FAILED",
        "WITNESS_FOUND": "VERIFIED_PER_VIEW_DOMINANCE",
        "INFEASIBLE": "PROVEN_NO_PER_VIEW_DOMINANCE",
        "INCONCLUSIVE": "INCONCLUSIVE",
    }[_combined_status(records)]


def _statuses(records: Sequence[object]) -> list[str]:
    expected_views = ("front", *FRESH_STRICT_VIEWS)
    if len(records) != len(expected_views):
        return ["VALIDATION_FAILED"]
    statuses: list[str] = []
    for expected_view, arm in zip(expected_views, records, strict=True):
        if not isinstance(arm, dict):
            return ["VALIDATION_FAILED"]
        if arm.get("strictView") != expected_view or not isinstance(arm.get("status"), str):
            return ["VALIDATION_FAILED"]
        statuses.append(arm["status"])
    return statuses


def _has_validation_failure(statuses: list[str]) -> bool:
    return any(status.endswith("_FAILED") for status in statuses)


if __name__ == "__main__":
    raise SystemExit(main())
