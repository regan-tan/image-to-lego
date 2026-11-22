"""Run the opt-in M13E-B3.3 incidence-compressed front-strict Duck solve."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("../artifacts/m13e-duck-iou-compressed")
    )
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("The output directory is non-empty; refusing to overwrite prior results.")
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B3.3 accepts a manifest containing only the pinned Duck case.")
    output = run_duck_iou_dominance(
        cases["duck"], _load_duck_summary(args.summary), strict_view="front", compressed=True
    )
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "summary.json").write_text(
        json.dumps(output["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "duck-front-strict.json").write_text(
        json.dumps(output["record"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if output["summary"]["status"] != "MODEL_PARITY_FAILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
