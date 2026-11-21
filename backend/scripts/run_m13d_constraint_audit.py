"""Run M13D Stage A against completed private M13B summaries; never solves CP-SAT."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core  # noqa: E402
from app.conversion.m12c_wedge_fidelity_experiment import _placement_pixels_many  # noqa: E402
from app.conversion.m13c_silhouette_equivalence_audit import (  # noqa: E402
    AuditError,
    candidate_preflight_failures,
    m13b_fixed_frame_bounds,
    m13b_no_wedge_candidate_preflight,
    parity_record,
    reconstruct_m13b_preprocessing,
    reconstruct_placements,
    verify_source_sha256,
)
from app.conversion.m13d_tp_fp_feasibility_audit import (  # noqa: E402
    assembly_error_attribution,
    candidate_conflicts,
    candidate_pixel_accounting,
    coverage_alternatives,
    mandatory_coverage_pressure,
)
from app.conversion.real_world_benchmark import (  # noqa: E402
    BenchmarkCase,
    load_manifest,
    verify_case_source,
)

CASE_IDS = ("duck", "mansion", "realistic-man")
EXPECTED_CANDIDATES = {"duck": 1449, "mansion": 3166, "realistic-man": 1043}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if len(args.summary) != len(CASE_IDS):
        parser.error("Pass exactly three M13B summaries.")
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    summaries = _load_summaries(args.summary)
    if set(cases) != set(CASE_IDS) or set(summaries) != set(CASE_IDS):
        raise AuditError("M13D requires exactly the three SHA-pinned M13B cases and summaries.")
    records = [_audit_case(cases[case_id], summaries[case_id]) for case_id in CASE_IDS]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": "m13d-constraint-aware-tp-fp-audit-v1",
        "stageA": "PASS"
        if all(record["status"] == "PASS" for record in records)
        else "PRECHECK_FAILED",
        "solverInvocation": "none",
        "records": records,
        "stageBRecommendation": {
            "hypothesis": (
                "A constrained solve can test whether the historical TP counts can be retained "
                "while lowering fixed-frame FP."
            ),
            "acceptanceCriteria": (
                "Report only a feasible incumbent, a proven optimum, a rigorous infeasibility "
                "proof, or TIMEOUT/UNKNOWN separately; preserve historical constraints and a "
                "bounded deterministic budget."
            ),
        },
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if payload["stageA"] == "PASS" else 1


def _audit_case(case: BenchmarkCase, record: Mapping[str, object]) -> dict[str, object]:
    case_id = case.case_id
    try:
        source = verify_case_source(case)
        configuration = _mapping(record.get("configuration"), "configuration")
        grid_value = _mapping(configuration.get("grid"), "configuration.grid")
        grid = core.GridSize(
            _integer(grid_value.get("width_studs")),
            _integer(grid_value.get("depth_studs")),
            _integer(grid_value.get("height_plates")),
        )
        failures = []
        if verify_source_sha256(source, record.get("sourceSha256")) != sha256(source).hexdigest():
            failures.append("source hash verification failed")
        if (
            configuration.get("wedge41769aEnabled") is not False
            or configuration.get("sourceEvidenceResolution") != 1
        ):
            failures.append("historical no-wedge or source-evidence configuration mismatch")
        if configuration.get("candidateCount") != EXPECTED_CANDIDATES[case_id]:
            failures.append("saved historical candidate count mismatch")
        control = reconstruct_placements(
            _strings(_mapping(record.get("control"), "control").get("placementIds"))
        )
        experiment = reconstruct_placements(
            _strings(_mapping(record.get("iouProxy"), "iouProxy").get("placementIds"))
        )
        locked = tuple(item for item in control if item.brick_type.shape != "rectangular")
        if locked != tuple(item for item in experiment if item.brick_type.shape != "rectangular"):
            failures.append("control and experiment locked placements differ")
        preprocessing = reconstruct_m13b_preprocessing(source, grid, case.up_axis)
        preflight = m13b_no_wedge_candidate_preflight(preprocessing, locked)
        failures.extend(
            candidate_preflight_failures(
                EXPECTED_CANDIDATES[case_id], preflight.candidates, control
            )
        )
        if (
            preflight.status != "READY"
            or preflight.candidate_rasters is None
            or preflight.source_pixels is None
            or preflight.locked_pixels is None
        ):
            failures.append("candidate preflight was not READY")
        bounds = m13b_fixed_frame_bounds(preprocessing.source_vertices, preprocessing.target_cells)
        control_saved = _mapping(record.get("control"), "control")
        experiment_saved = _mapping(record.get("iouProxy"), "iouProxy")
        shared_bounds = _shared_bounds(control_saved, experiment_saved)
        control_parity = parity_record(
            preprocessing.source_vertices,
            preprocessing.faces,
            control,
            preprocessing.target_cells,
            control_saved,
            shared_bounds,
        )
        experiment_parity = parity_record(
            preprocessing.source_vertices,
            preprocessing.faces,
            experiment,
            preprocessing.target_cells,
            experiment_saved,
            shared_bounds,
        )
        if not control_parity["passed"] or not experiment_parity["passed"]:
            failures.append("fixed-frame reconstruction parity mismatch")
        if failures:
            return {"caseId": case_id, "status": "PRECHECK_FAILED", "diagnostics": failures}
        assert (
            preflight.candidate_rasters is not None
            and preflight.source_pixels is not None
            and preflight.locked_pixels is not None
        )
        candidate_by_placement = {
            item.placement: raster
            for item, raster in zip(preflight.candidates, preflight.candidate_rasters, strict=True)
        }
        locked_rasters = tuple(_placement_pixels_many((placement,), bounds) for placement in locked)
        return {
            "caseId": case_id,
            "status": "PASS",
            "provenance": {
                "sourceSha256": sha256(source).hexdigest(),
                "candidateCount": len(preflight.candidates),
                "fixedFrame": {view: list(value) for view, value in bounds.items()},
            },
            "historicalConstraints": _historical_constraints(),
            "candidateGeometry": candidate_pixel_accounting(
                preflight.candidates,
                preflight.candidate_rasters,
                preflight.source_pixels,
                preflight.locked_pixels,
            ),
            "coverageAlternatives": coverage_alternatives(
                preflight.source_pixels, preflight.locked_pixels, preflight.candidate_rasters
            ),
            "candidateConflicts": candidate_conflicts(preflight.candidates, locked),
            "mandatoryCoverage": mandatory_coverage_pressure(
                preprocessing.required_pixels, preflight.candidates, locked
            ),
            "assemblies": {
                "control": assembly_error_attribution(
                    control,
                    _selected_rasters(control, locked, candidate_by_placement, locked_rasters),
                    preflight.source_pixels,
                ),
                "iouProxy": assembly_error_attribution(
                    experiment,
                    _selected_rasters(experiment, locked, candidate_by_placement, locked_rasters),
                    preflight.source_pixels,
                ),
            },
            "limitations": [
                "No CP-SAT model was created or solved.",
                "Pairwise conflicts and possible support do not prove global feasibility.",
                "The global connected-component count was checked after solving, not enforced "
                "as a CP-SAT constraint.",
            ],
        }
    except (AuditError, OSError, ValueError, KeyError) as error:
        return {"caseId": case_id, "status": "PRECHECK_FAILED", "diagnostics": [str(error)]}


def _selected_rasters(
    placements: tuple[core.BrickPlacement, ...],
    locked: tuple[core.BrickPlacement, ...],
    candidate_by_placement: Mapping[core.BrickPlacement, frozenset[tuple[str, int, int]]],
    locked_rasters: tuple[frozenset[tuple[str, int, int]], ...],
) -> tuple[frozenset[tuple[str, int, int]], ...]:
    locked_map = dict(zip(locked, locked_rasters, strict=True))
    return tuple(
        locked_map[item] if item in locked_map else candidate_by_placement[item]
        for item in placements
    )


def _historical_constraints() -> dict[str, object]:
    return {
        "enforcedByCpSat": [
            "rectangular candidate occupancy mutual exclusion",
            "pairwise wedge collision exclusions (inactive because 41769a was disabled)",
            "candidate direct verified support",
            "support required for locked placements",
            "mandatory coarse projection coverage",
            "maximum part count",
        ],
        "enforcedBeforeCandidateSelection": [
            "protected-empty-space wedge eligibility",
            "candidate rejection for locked-body collision",
            "support-reachability pruning",
        ],
        "postSolveValidationOnly": [
            "global connected-component count",
            "completed-arrangement collision, support, protected-space, and interface validation",
        ],
    }


def _shared_bounds(
    control: Mapping[str, object], experiment: Mapping[str, object]
) -> dict[str, tuple[float, float, float, float]]:
    def parse(record: Mapping[str, object]) -> dict[str, tuple[float, float, float, float]]:
        values = _mapping(record.get("sharedBounds"), "sharedBounds").get("bounds")
        if not isinstance(values, list):
            raise AuditError("shared bounds must be a list.")
        result: dict[str, tuple[float, float, float, float]] = {}
        for item in values:
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str):
                raise AuditError("shared bounds entry is invalid.")
            numbers = item[1]
            if not isinstance(numbers, list) or len(numbers) != 4:
                raise AuditError("shared bounds must have four values.")
            result[item[0]] = cast(
                tuple[float, float, float, float], tuple(float(value) for value in numbers)
            )
        return result

    left, right = parse(control), parse(experiment)
    if left != right:
        raise AuditError("control and experiment shared bounds differ.")
    return left


def _load_summaries(paths: list[Path]) -> dict[str, dict[str, object]]:
    result = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records")
        if (
            payload.get("schemaVersion") != "m13b-iou-proxy-v1"
            or not isinstance(records, list)
            or len(records) != 1
        ):
            raise AuditError(f"{path} is not a single-record M13B summary.")
        item = _mapping(records[0], str(path))
        result[cast(str, item["caseId"])] = item
    return result


def _mapping(value: object, name: str = "value") -> dict[str, object]:
    if not isinstance(value, dict):
        raise AuditError(f"{name} must be an object.")
    return cast(dict[str, object], value)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AuditError("placement IDs must be a list of strings.")
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int):
        raise AuditError("grid dimensions must be integers.")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
