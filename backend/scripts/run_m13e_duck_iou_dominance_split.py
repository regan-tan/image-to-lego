"""Run the opt-in M13E-B3.1 Duck split exact-IoU-dominance experiment."""
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
from app.conversion.real_world_benchmark import load_manifest  # noqa: E402
from scripts.run_m13e_duck_hint import _load_duck_summary  # noqa: E402
from scripts.run_m13e_duck_iou_dominance import run_duck_iou_dominance  # noqa: E402

STRICT_VIEWS = ("front", "side", "top")
SCHEMA_VERSION = "m13e-duck-iou-dominance-split-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/m13e-duck-iou-dominance-split")
    )
    args = parser.parse_args()
    record = _load_duck_summary(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B3.1 accepts a manifest containing only the pinned Duck case.")
    payload = run_duck_iou_dominance_split(cases["duck"], record)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for arm in payload["records"]:
        strict_view = arm["strictView"]
        (args.output_dir / f"duck-{strict_view}-strict.json").write_text(
            json.dumps(arm, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0 if payload["summary"]["status"] != "MODEL_PARITY_FAILED" else 1


def run_duck_iou_dominance_split(case: object, record: dict[str, object]) -> dict[str, object]:
    """Run three fresh B3 models whose disjunction is exactly the B3 strict condition."""
    from app.conversion.real_world_benchmark import BenchmarkCase

    if not isinstance(case, BenchmarkCase):
        raise AuditError("M13E-B3.1 requires a Duck benchmark case.")
    records = [
        run_duck_iou_dominance(case, record, strict_view=strict_view)["record"]
        for strict_view in STRICT_VIEWS
    ]
    return {
        "summary": {
            "schemaVersion": SCHEMA_VERSION,
            "status": _combined_status(records),
            "classification": _combined_classification(records),
            "aggregateBudgetNote": (
                "Three independent 30-second deterministic-time arms have a larger aggregate "
                "budget than one B3 solve; wall-clock times are not directly comparable."
            ),
            "records": records,
        },
        "records": records,
    }


def _combined_status(records: list[object]) -> str:
    statuses = _statuses(records)
    if "MODEL_PARITY_FAILED" in statuses:
        return "MODEL_PARITY_FAILED"
    if any(status in {"OPTIMAL", "FEASIBLE"} for status in statuses):
        return "WITNESS_FOUND"
    if all(status == "INFEASIBLE" for status in statuses):
        return "INFEASIBLE"
    return "INCONCLUSIVE"


def _combined_classification(records: list[object]) -> str:
    status = _combined_status(records)
    return {
        "WITNESS_FOUND": "VERIFIED_DOMINATING_WITNESS",
        "INFEASIBLE": "PROVEN_NO_PER_VIEW_DOMINANCE",
        "MODEL_PARITY_FAILED": "MODEL_PARITY_FAILED",
        "INCONCLUSIVE": "INCONCLUSIVE",
    }[status]


def _statuses(records: list[object]) -> list[str]:
    statuses: list[str] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("status"), str):
            return ["MODEL_PARITY_FAILED"]
        statuses.append(record["status"])
    return statuses


if __name__ == "__main__":
    raise SystemExit(main())
