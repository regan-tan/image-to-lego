"""Run the bounded private M14B high-resolution CP-SAT investigation."""

from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core  # noqa: E402
from app.conversion.m14b_high_resolution_feasibility import (  # noqa: E402
    build_input,
    run_experiment,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--grid", type=int, nargs=3, metavar=("WIDTH", "DEPTH", "HEIGHT"), required=True
    )
    parser.add_argument("--max-parts", type=int, required=True)
    parser.add_argument("--effective-grid-target", type=int, default=300)
    parser.add_argument("--deterministic-time", type=float, default=40.0)
    parser.add_argument("--preflight-only", action="store_true")
    arguments = parser.parse_args()
    source = arguments.source.read_bytes()
    grid = core.GridSize(*arguments.grid)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(
            {
                "schemaVersion": "m14b-high-resolution-run-state-v1",
                "status": "preparing_input",
                "sourceSha256": sha256(source).hexdigest(),
                "grid": {
                    "widthStuds": grid.width_studs,
                    "depthStuds": grid.depth_studs,
                    "heightPlates": grid.height_plates,
                },
                "effectiveGridTarget": arguments.effective_grid_target,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        prepared = build_input(source, grid=grid, up_axis=core.Axis.Y)
    except Exception as error:
        _write_failure(arguments.output, error)
        print(f"Experiment failed: {error}", file=sys.stderr)
        return 2
    preflight = {
        "schemaVersion": "m14b-high-resolution-preflight-v1",
        "sourceSha256": sha256(source).hexdigest(),
        "grid": {
            "widthStuds": grid.width_studs,
            "depthStuds": grid.depth_studs,
            "heightPlates": grid.height_plates,
        },
        "effectiveGridTarget": arguments.effective_grid_target,
        "sourceTriangleCount": prepared.triangle_count,
        "sourceOccupancyCells": prepared.source_cells,
        "projectionHullCells": len(prepared.target_cells),
        "lockedPlacements": len(prepared.locked),
        "candidateCounts": {
            "beforeCollision": prepared.candidates_before_collision,
            "afterCollision": prepared.candidates_after_collision,
            "afterSupportReachability": len(prepared.candidates),
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    if arguments.preflight_only:
        arguments.output.write_text(
            json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(preflight, indent=2))
        return 0
    _write_running_experiment(arguments.output, preflight)
    try:
        result = run_experiment(
            prepared,
            max_parts=arguments.max_parts,
            effective_grid_target=arguments.effective_grid_target,
            deterministic_time=arguments.deterministic_time,
        )
    except KeyboardInterrupt:
        _write_interruption(arguments.output, preflight)
        print("Experiment interrupted.", file=sys.stderr)
        return 130
    except Exception as error:
        _write_failure(arguments.output, error, preflight=preflight)
        print(f"Experiment failed: {error}", file=sys.stderr)
        return 2
    result["sourceSha256"] = sha256(source).hexdigest()
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"unhinted": result["unhinted"], "hinted": result["hinted"] is not None},
            indent=2,
        )
    )
    return 0


def _write_failure(
    output_path: Path, error: Exception, *, preflight: dict[str, object] | None = None
) -> None:
    record: dict[str, object] = {
        "schemaVersion": "m14b-high-resolution-run-state-v1",
        "status": "failed",
        "errorType": type(error).__name__,
        "errorMessage": str(error),
    }
    if preflight is not None:
        record["preflight"] = preflight
    output_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_running_experiment(output_path: Path, preflight: dict[str, object]) -> None:
    output_path.write_text(
        json.dumps(
            {
                "schemaVersion": "m14b-high-resolution-run-state-v1",
                "status": "running_experiment",
                "preflight": preflight,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_interruption(output_path: Path, preflight: dict[str, object]) -> None:
    output_path.write_text(
        json.dumps(
            {
                "schemaVersion": "m14b-high-resolution-run-state-v1",
                "status": "interrupted",
                "preflight": preflight,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
