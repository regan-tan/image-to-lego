"""Run the opt-in M13E-B1 Duck TP-maximization experiment with private inputs."""
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
from scripts.run_m13e_duck_hint import _load_duck_summary, run_duck_experiment  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/m13e-duck-tp-max"))
    args = parser.parse_args()
    record = _load_duck_summary(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B1 accepts a manifest containing only the pinned Duck case.")
    result = run_duck_experiment(cases["duck"], record, objective_mode="max_tp")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in result.items():
        filename = "summary.json" if name == "summary" else f"{name}.json"
        (args.output_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if result["summary"]["status"] != "COMPLETE":
        raise AuditError("M13E-B1 did not complete its validation gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
