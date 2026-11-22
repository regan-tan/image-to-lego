"""Run the opt-in M13E-B4 Duck cross-view fixed-frame mean-IoU pilot."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.m13c_silhouette_equivalence_audit import AuditError  # noqa: E402
from app.conversion.m13e_duck_cross_view_tradeoff import (  # noqa: E402
    TRADEOFF_BUDGETS,
    arm_thresholds,
)
from app.conversion.real_world_benchmark import BenchmarkCase, load_manifest  # noqa: E402
from scripts.run_m13e_duck_hint import _load_duck_summary  # noqa: E402
from scripts.run_m13e_duck_iou_dominance import run_duck_iou_dominance  # noqa: E402

TARGET_VIEWS: Final = ("front", "side", "top")
SCHEMA_VERSION: Final = "m13e-duck-cross-view-tradeoff-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("../artifacts/m13e-duck-cross-view-tradeoff")
    )
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("The output directory already exists; refusing to overwrite prior results.")
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B4 accepts a manifest containing only the pinned Duck case.")
    payload = run_duck_cross_view_tradeoff(cases["duck"], _load_duck_summary(args.summary))
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for arm in payload["records"]:
        target = arm["targetView"]
        budget = arm["lossBudgetBasisPoints"]
        (args.output_dir / f"duck-{target}-loss-{budget}.json").write_text(
            json.dumps(arm, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if payload["summary"]["status"] != "MODEL_PARITY_FAILED" else 1


def run_duck_cross_view_tradeoff(
    case: BenchmarkCase, record: dict[str, object]
) -> dict[str, object]:
    """Run the nine predeclared satisfaction arms with fresh compressed models."""
    if not isinstance(case, BenchmarkCase):
        raise AuditError("M13E-B4 requires a Duck benchmark case.")
    records: list[dict[str, object]] = []
    for target_view in TARGET_VIEWS:
        for loss_budget in TRADEOFF_BUDGETS:
            thresholds = arm_thresholds(target_view, loss_budget)
            arm = run_duck_iou_dominance(
                case,
                record,
                compressed=True,
                iou_change_basis_points=thresholds,
            )["record"]
            arm["targetView"] = target_view
            arm["lossBudgetBasisPoints"] = loss_budget
            arm["classification"] = _classification(arm)
            records.append(arm)
    return {
        "summary": {
            "schemaVersion": SCHEMA_VERSION,
            "status": _summary_status(records),
            "scope": (
                "This finite nine-arm satisfaction sweep is a sufficient, not exhaustive, "
                "test for fixed-frame mean-IoU improvement. It has no maximization objective."
            ),
            "arms": records,
            "table": [
                {
                    "targetView": arm["targetView"],
                    "lossBudgetBasisPoints": arm["lossBudgetBasisPoints"],
                    "status": arm["status"],
                    "classification": arm["classification"],
                }
                for arm in records
            ],
        },
        "records": records,
    }


def _classification(arm: dict[str, object]) -> str:
    status = arm.get("status")
    existing = arm.get("classification")
    if status == "INFEASIBLE":
        return "PROVEN_INFEASIBLE_WITHIN_TESTED_ARM"
    if status in {"OPTIMAL", "FEASIBLE"} and existing in {
        "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT",
        "VERIFIED_FROZEN_MEAN_IMPROVEMENT",
    }:
        return str(existing)
    if status == "MODEL_PARITY_FAILED":
        return "MODEL_PARITY_FAILED"
    if status == "RESULT_VERIFICATION_FAILED":
        return "RESULT_VERIFICATION_FAILED"
    return "INCONCLUSIVE"


def _summary_status(records: list[dict[str, object]]) -> str:
    statuses = {str(record.get("classification")) for record in records}
    if "MODEL_PARITY_FAILED" in statuses:
        return "MODEL_PARITY_FAILED"
    if "RESULT_VERIFICATION_FAILED" in statuses:
        return "RESULT_VERIFICATION_FAILED"
    if "VERIFIED_FROZEN_MEAN_IMPROVEMENT" in statuses:
        return "VERIFIED_FROZEN_MEAN_IMPROVEMENT"
    if "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT" in statuses:
        return "VERIFIED_FIXED_FRAME_MEAN_IMPROVEMENT"
    return "INCONCLUSIVE"


if __name__ == "__main__":
    raise SystemExit(main())
