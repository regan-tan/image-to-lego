"""Run the opt-in M13E-B5 Duck mean-IoU-guided witness search."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.real_world_benchmark import load_manifest  # noqa: E402
from scripts.run_m13e_duck_hint import _load_duck_summary  # noqa: E402
from scripts.run_m13e_duck_iou_dominance import run_duck_iou_dominance  # noqa: E402

SCHEMA_VERSION = "m13e-duck-mean-iou-guided-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("../artifacts/m13e-duck-mean-iou-guided")
    )
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("The output directory already exists; refusing to overwrite prior results.")
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B5 accepts a manifest containing only the pinned Duck case.")
    output = run_duck_iou_dominance(
        cases["duck"], _load_duck_summary(args.summary), compressed=True, mean_iou_guided=True
    )
    record = output["record"]
    summary = {
        "schemaVersion": SCHEMA_VERSION,
        "status": record["status"],
        "classification": record["classification"],
        "limitations": [
            "The first-order objective approximates mean IoU; it is not exact "
            "mean-IoU optimization.",
            "OPTIMAL means optimal only for the signed-integer surrogate.",
            "No exact mean-IoU improvement does not prove that none exists.",
            "Frozen silhouette-v1 may disagree with fixed-frame IoU.",
            "Connectivity is a separately reported mechanical property, not a hard constraint.",
        ],
        "record": record,
    }
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "duck-mean-iou-guided.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if record["status"] != "MODEL_PARITY_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
