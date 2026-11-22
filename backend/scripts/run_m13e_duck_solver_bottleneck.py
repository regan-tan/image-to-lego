"""Run the opt-in M13E-B3.2 front-strict CP-SAT bottleneck diagnostic."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from ortools.sat.python import cp_model

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion.m13c_silhouette_equivalence_audit import AuditError  # noqa: E402
from app.conversion.m13d_tp_fp_feasibility_experiment import (  # noqa: E402
    DEFAULT_DETERMINISTIC_TIME_SECONDS,
)
from app.conversion.m13e_duck_iou_dominance import (  # noqa: E402
    IoUDominanceModel,
    IoUDominanceResult,
    solve_built_iou_dominance_model,
)
from app.conversion.real_world_benchmark import load_manifest  # noqa: E402
from scripts.run_m13e_duck_hint import _load_duck_summary  # noqa: E402
from scripts.run_m13e_duck_iou_dominance import run_duck_iou_dominance  # noqa: E402

OUTPUT_DIRECTORY = Path("../artifacts/m13e-duck-solver-bottleneck")
STRICT_VIEW = "front"


@dataclass(slots=True)
class DiagnosticCapture:
    """Raw evidence from the one instrumented strict solve."""

    model: IoUDominanceModel | None = None
    result: IoUDominanceResult | None = None
    solver_log: str = ""
    solver_response: str = ""
    response_log_supported: bool = False


class DiagnosticArtifactError(RuntimeError):
    """Raised when optional diagnostic metadata cannot be saved after raw evidence."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIRECTORY)
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("The output directory is non-empty; refusing to overwrite prior diagnostics.")

    record = _load_duck_summary(args.summary)
    cases = {case.case_id: case for case in load_manifest(args.manifest).cases}
    if set(cases) != {"duck"}:
        parser.error("M13E-B3.2 accepts a manifest containing only the pinned Duck case.")

    capture = DiagnosticCapture()
    output = run_duck_iou_dominance(
        cases["duck"],
        record,
        strict_view=STRICT_VIEW,
        strict_solver_callback=_instrumented_front_strict_solver(capture),
    )
    if output["summary"]["status"] == "MODEL_PARITY_FAILED":
        raise AuditError("M13E-B3.2 did not complete the existing B3.1 validation gates.")
    if capture.model is None or capture.result is None:
        raise AuditError("The front-strict solver was not invoked after the validation gates.")
    if capture.result.variable_count != len(capture.model.model.proto.variables) or (
        capture.result.constraint_count != len(capture.model.model.proto.constraints)
    ):
        raise AuditError("Instrumented model counts differ from the solved front-strict model.")

    try:
        _write_diagnostic_artifacts(args.output_dir, output["record"], capture)
    except DiagnosticArtifactError as error:
        print(f"Diagnostic artifact failure: {error}", file=sys.stderr)
        return 2
    return 0


def _instrumented_front_strict_solver(
    capture: DiagnosticCapture,
) -> Callable[[IoUDominanceModel, float], tuple[IoUDominanceResult, cp_model.CpSolver]]:
    def solve(
        model: IoUDominanceModel, deterministic_time_seconds: float
    ) -> tuple[IoUDominanceResult, cp_model.CpSolver]:
        if deterministic_time_seconds != DEFAULT_DETERMINISTIC_TIME_SECONDS:
            raise AuditError("M13E-B3.2 must retain B3.1's 30-second deterministic-time budget.")
        result, solver = solve_built_iou_dominance_model(
            model,
            deterministic_time_seconds=deterministic_time_seconds,
            log_search_progress=True,
            log_to_response=True,
            log_to_stdout=False,
        )
        capture.model = model
        capture.result = result
        capture.response_log_supported = hasattr(solver.parameters, "log_to_response")
        capture.solver_log = str(getattr(solver.response_proto, "solve_log", ""))
        capture.solver_response = str(solver.response_proto)
        return result, solver

    return solve


def _write_diagnostic_artifacts(
    output_dir: Path, record: object, capture: DiagnosticCapture
) -> None:
    assert capture.model is not None and capture.result is not None
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_raw_solver_evidence(output_dir, capture)

    try:
        _write_diagnostic_metadata(output_dir, record, capture)
    except Exception as error:
        _write_artifact_failure(output_dir, error)
        raise DiagnosticArtifactError(
            "raw solver evidence was saved, but later diagnostic metadata could not be written"
        ) from error


def _write_raw_solver_evidence(output_dir: Path, capture: DiagnosticCapture) -> None:
    """Persist the CP-SAT output before deriving optional metadata from the model."""
    (output_dir / "solver.log").write_text(capture.solver_log, encoding="utf-8")
    (output_dir / "solver-response.txt").write_text(
        capture.solver_response + "\n", encoding="utf-8"
    )


def _write_diagnostic_metadata(
    output_dir: Path, record: object, capture: DiagnosticCapture
) -> None:
    """Save derived diagnostics only after raw CP-SAT evidence is durable."""
    assert capture.model is not None and capture.result is not None
    model = capture.model.model
    model_fingerprint = _model_proto_sha256(model)
    component_counts = {
        name: asdict(count) for name, count in capture.model.component_counts.items()
    }
    evidence = _search_stage_evidence(capture.solver_log, capture.result.response_statistics)
    (output_dir / "model-stats.txt").write_text(model.model_stats() + "\n", encoding="utf-8")
    (output_dir / "model-components.json").write_text(
        json.dumps(
            {
                "modelProtoSha256": model_fingerprint,
                "variables": len(model.proto.variables),
                "constraints": len(model.proto.constraints),
                "components": component_counts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "presolve-search-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "duck-front-strict.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "diagnostic-summary.json").write_text(
        json.dumps(
            {
                "schemaVersion": "m13e-duck-solver-bottleneck-v1",
                "strictView": STRICT_VIEW,
                "responseLogCaptureSupported": capture.response_log_supported,
                "solverResult": asdict(capture.result),
                "modelProtoSha256": model_fingerprint,
                "stageEvidence": evidence,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_artifact_failure(output_dir: Path, error: Exception) -> None:
    """Leave a concise failure record without replacing the already-saved solver output."""
    with suppress(OSError):
        (output_dir / "diagnostic-artifact-failure.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "m13e-duck-solver-bottleneck-v1",
                    "status": "DIAGNOSTIC_ARTIFACT_FAILURE",
                    "rawSolverEvidence": ["solver.log", "solver-response.txt"],
                    "errorType": type(error).__name__,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _search_stage_evidence(solver_log: str, response_statistics: str | None) -> dict[str, object]:
    """Report only stages whose standard CP-SAT log markers actually appear."""
    log = solver_log.lower()
    markers = {
        "initialModel": "initial satisfaction model" in log or "initial optimization model" in log,
        "presolveStarted": "starting presolve" in log,
        "presolvedModel": "presolved satisfaction model" in log
        or "presolved optimization model" in log,
        "searchStarted": "starting search" in log,
        "searchProgress": "#1" in log or "#bound" in log,
        "stoppedAfterPresolve": "stopped after presolve" in log,
        "responseSummary": "cpsolverresponse summary" in log or bool(response_statistics),
    }
    if markers["searchStarted"] or markers["searchProgress"]:
        terminal_stage = "search"
    elif markers["presolveStarted"] or markers["presolvedModel"]:
        terminal_stage = "presolve"
    elif markers["initialModel"]:
        terminal_stage = "model_processing"
    else:
        terminal_stage = "unobserved"
    if markers["stoppedAfterPresolve"] and not markers["searchStarted"]:
        budget_attribution = {
            "determination": "PRESOLVE_MODEL_PROCESSING_CONSUMED_BUDGET",
            "reason": (
                "CP-SAT explicitly stopped after presolve and never logged search, so presolve "
                "or model processing consumed the available deterministic-time budget."
            ),
        }
    else:
        budget_attribution = {
            "determination": "NOT_ATTRIBUTABLE_FROM_STANDARD_LOG_ALONE",
            "reason": (
                "The standard CP-SAT response reports total deterministic time, but does not "
                "provide a per-stage deterministic-time breakdown. The last confirmed stage "
                "shows progress reached, not which stage consumed the whole budget."
            ),
        }
    return {
        "confirmedMarkers": markers,
        "lastConfirmedStage": terminal_stage,
        "budgetAttribution": budget_attribution,
        "hypotheses": [
            "An explicit 'Stopped after presolve' marker without search attributes the budget "
            "to presolve or model processing; merely missing a search marker does not.",
            "If search is confirmed, search was reached, but presolve and search time cannot "
            "be apportioned without additional solver instrumentation.",
        ],
    }


def _model_proto_sha256(model: cp_model.CpModel) -> str:
    """Hash an OR-Tools 9.15 binary export of the exact constructed model."""
    with TemporaryDirectory(prefix="m13e-cp-model-") as temporary_directory:
        export_path = Path(temporary_directory) / "model.pb"
        if not model.export_to_file(str(export_path)):
            raise OSError("OR-Tools did not export the CP-SAT model.")
        return sha256(export_path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
