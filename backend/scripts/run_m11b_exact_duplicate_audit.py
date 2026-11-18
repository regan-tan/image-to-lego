"""Run the bounded, aggregate-only M11B exact-candidate duplicate audit.

The runner reuses V6 preflight enumeration and never builds or changes a
CP-SAT model. It writes only source hashes, aggregate counts, and resource
measurements beneath an ignored artifacts directory.
"""

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
from app.conversion.physical_scale_experiment import (  # noqa: E402
    EXACT_DUPLICATE_AUDIT_MAX_CANDIDATES,
    EXACT_DUPLICATE_AUDIT_MAX_PEAK_MEMORY_BYTES,
    EXACT_DUPLICATE_AUDIT_MAX_RUNTIME_SECONDS,
    EXACT_DUPLICATE_AUDIT_VERSION,
    audit_fixed_grid_candidate_duplicates,
    scaled_grid,
)
from app.conversion.real_world_benchmark import load_manifest, verify_case_source  # noqa: E402

BASELINE_GRIDS = {
    "duck": core.GridSize(5, 7, 12),
    "mansion": core.GridSize(7, 4, 12),
    "realistic-man": core.GridSize(3, 5, 18),
}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=tuple(BASELINE_GRIDS))
    parser.add_argument("--scale", action="append", choices=("1x", "1.5x"))
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        summary = run_audit(
            arguments.manifest,
            arguments.output_dir,
            selected_case_ids=tuple(arguments.case) if arguments.case else None,
            selected_scales=tuple(arguments.scale) if arguments.scale else None,
        )
    except (OSError, ValueError, core.ConversionError) as error:
        print(f"Audit validation failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": summary["status"], "records": len(summary["records"])}, indent=2))
    return 0


def run_audit(
    manifest_path: Path,
    output_dir: Path,
    *,
    selected_case_ids: tuple[str, ...] | None = None,
    selected_scales: tuple[str, ...] | None = None,
) -> dict[str, object]:
    manifest = load_manifest(manifest_path)
    cases = {case.case_id: case for case in manifest.cases}
    if set(cases) != set(BASELINE_GRIDS):
        raise ValueError("M11B requires the SHA-pinned Duck, Mansion, and Realistic-man manifest.")
    if manifest.corpus_status != "available":
        raise ValueError("M11B source corpus is unavailable; no measurements were run.")
    selected_cases = selected_case_ids or tuple(BASELINE_GRIDS)
    if not set(selected_cases).issubset(cases):
        raise ValueError("M11B selected an unknown corpus case.")
    scales = selected_scales or ("1x", "1.5x")
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for case_id in selected_cases:
        baseline_grid = BASELINE_GRIDS[case_id]
        case = cases[case_id]
        source = verify_case_source(case)
        grids = {"1x": baseline_grid, "1.5x": scaled_grid(baseline_grid, 1.5)}
        for label in scales:
            grid = grids[label]
            result = audit_fixed_grid_candidate_duplicates(source, grid=grid, up_axis=case.up_axis)
            record = result.record()
            record.update(
                {
                    "caseId": case_id,
                    "scale": label,
                    "grid": {
                        "widthStuds": grid.width_studs,
                        "depthStuds": grid.depth_studs,
                        "heightPlates": grid.height_plates,
                    },
                    "sourceSha256": sha256(source).hexdigest(),
                    "reachesFourThousandCandidateLimit": result.reduced_candidate_count <= 4_000,
                }
            )
            records.append(record)
    summary: dict[str, object] = {
        "schemaVersion": EXACT_DUPLICATE_AUDIT_VERSION,
        "status": "completed",
        "limits": {
            "maxCandidates": EXACT_DUPLICATE_AUDIT_MAX_CANDIDATES,
            "maxRuntimeSeconds": EXACT_DUPLICATE_AUDIT_MAX_RUNTIME_SECONDS,
            "maxPeakMemoryBytes": EXACT_DUPLICATE_AUDIT_MAX_PEAK_MEMORY_BYTES,
        },
        "proof": {
            "fullyProvenClass": "identical canonical placement and all derived signatures",
            "projectionGeometryMechanicalClasses": "diagnostic only; not removal certificates",
        },
        "records": records,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
