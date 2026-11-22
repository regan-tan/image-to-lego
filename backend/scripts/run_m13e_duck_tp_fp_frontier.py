"""Run the opt-in M13E-B2 Duck TP-loss/FP-reduction pilot with private inputs."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.m13c_silhouette_equivalence_audit import AuditError  # noqa: E402
from app.conversion.m13e_duck_tp_fp_frontier import (  # noqa: E402
    CONTROL_AGGREGATE_FP,
    CONTROL_VIEWS,
    SOURCE_FOREGROUND,
    classify_frontier_status,
    optimal_fp_is_nested,
    predeclared_rows,
    tp_floors,
    verified_frozen_improvement,
)
from app.conversion.real_world_benchmark import BenchmarkCase, load_manifest  # noqa: E402
from scripts.run_m13e_duck_hint import _load_duck_summary, run_duck_experiment  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/m13e-duck-tp-fp-frontier")
    )
    args = parser.parse_args()
    record = _load_duck_summary(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B2 accepts a manifest containing only the pinned Duck case.")
    result = run_frontier(cases["duck"], record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in result.items():
        (args.output_dir / f"{name}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if result["summary"]["status"] != "COMPLETE":
        raise AuditError("M13E-B2 did not complete its validation gates.")
    return 0


def run_frontier(case: BenchmarkCase, record: dict[str, object]) -> dict[str, dict[str, object]]:
    """Run exactly five fresh, Control-hinted models after shared fail-closed preflight."""
    rows = predeclared_rows()
    payloads: dict[str, dict[str, object]] = {}
    records: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        run = run_duck_experiment(
            case,
            record,
            objective_mode="min_fp",
            tp_loss_allowances=dict(row.allowances),
            arm_policies=((f"row-{index}", True),),
            expected_source_foreground=SOURCE_FOREGROUND,
        )
        row_record = run[f"row-{index}"]
        row_record["allowanceRow"] = {
            "label": row.label,
            "basisPoints": row.basis_points,
            "allowances": dict(row.allowances),
            "tpFloors": tp_floors(CONTROL_VIEWS, row.allowances),
            "hintPolicy": "verified complete historical Control assignment (guidance only)",
        }
        row_record["classification"] = classify_frontier_status(str(row_record["status"]))
        payloads[f"row-{index}"] = row_record
        records.append(row_record)
    zero = records[0]
    zero_regression = (
        zero.get("status") == "OPTIMAL"
        and isinstance(zero.get("solver"), dict)
        and zero["solver"].get("objective_value") != CONTROL_AGGREGATE_FP
    )
    status = "COMPLETE"
    if any(record.get("status") == "RESULT_VERIFICATION_FAILED" for record in records):
        status = "RESULT_VERIFICATION_FAILED"
    elif (
        any(record.get("status") in {"MODEL_PARITY_FAILED", "INFEASIBLE"} for record in records)
        or zero_regression
        or not optimal_fp_is_nested(records)
    ):
        status = "MODEL_PARITY_FAILED"
    summary: dict[str, object] = {
        "schemaVersion": "m13e-duck-tp-fp-frontier-v1",
        "status": status,
        "hintPolicy": "Control hint for every row; no paired-hint experiment.",
        "records": records,
        "comparison": [
            {
                "label": record["allowanceRow"]["label"],
                "status": record["status"],
                "aggregateFp": _aggregate_fp(record),
                "fixedFrameMeanIou": _result_field(record, "fixedFrameMeanIou"),
                "frozenMeanIouChangeFromControl": _result_field(
                    record, "frozenMeanIouChangeFromControl"
                ),
            }
            for record in records
        ],
        "optimalFpNested": optimal_fp_is_nested(records),
        "zeroAllowanceRegression": not zero_regression,
        "verifiedFrozenSilhouetteV1Improvement": verified_frozen_improvement(records),
        "limitation": "Minimum aggregate FP does not maximize IoU among equal-FP assemblies.",
    }
    return {"summary": summary, **payloads}


def _aggregate_fp(record: dict[str, object]) -> int | None:
    solver = record.get("solver")
    if not isinstance(solver, dict):
        return None
    objective = solver.get("objective_value")
    return objective if isinstance(objective, int) else None


def _result_field(record: dict[str, object], field: str) -> float | None:
    result = record.get("result")
    if not isinstance(result, dict):
        return None
    value = result.get(field)
    return float(value) if isinstance(value, int | float) else None


if __name__ == "__main__":
    raise SystemExit(main())
