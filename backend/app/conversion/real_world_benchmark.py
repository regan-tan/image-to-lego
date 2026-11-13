"""Manifest-driven, offline V4/V6/V7 fidelity comparison support.

This module deliberately reuses the frozen benchmark evaluators.  It does not
change converter settings, conversion behaviour, or historical metric versions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final

from app.conversion import core
from app.conversion.buildability import analyze_buildability
from app.conversion.physical_geometry import colliding_placement_pairs

MANIFEST_SCHEMA_VERSION: Final = "real-world-glb-manifest-v1"
SUMMARY_SCHEMA_VERSION: Final = "real-world-lego-benchmark-v1"
CASE_ID_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# The frozen V4 benchmark completed at 100 and 300 target parts. Its 600-part
# full suite was not feasible, so this runner stops at the highest completed
# evidence-backed request. This is a workload guardrail, not an output cap.
MAX_V4_BENCHMARK_TARGET_PARTS: Final = 300


class ManifestError(ValueError):
    """A real-world benchmark manifest is unsafe or incomplete."""


class WorkloadError(ValueError):
    """A benchmark workload would exceed this runner's safe operating envelope."""

    def __init__(self, diagnostics: list[dict[str, object]]) -> None:
        super().__init__("Benchmark workload validation failed.")
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    source_path: Path
    source_sha256: str
    provenance: str
    usage_restrictions: str
    characteristics: tuple[str, ...]
    up_axis: core.Axis
    target_parts: int


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    path: Path
    corpus_status: str
    corpus_note: str
    cases: tuple[BenchmarkCase, ...]


def load_manifest(path: Path) -> BenchmarkManifest:
    """Load a strict manifest without reading any source model bytes."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"Manifest is not readable JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ManifestError("Manifest root must be an object.")
    if payload.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"Manifest schemaVersion must be {MANIFEST_SCHEMA_VERSION!r}.")
    corpus_status = payload.get("corpusStatus")
    corpus_note = payload.get("corpusNote")
    raw_cases = payload.get("cases")
    if corpus_status not in {"available", "unavailable"}:
        raise ManifestError("Manifest corpusStatus must be 'available' or 'unavailable'.")
    if not isinstance(corpus_note, str) or not corpus_note.strip():
        raise ManifestError("Manifest corpusNote must be a non-empty string.")
    if not isinstance(raw_cases, list):
        raise ManifestError("Manifest cases must be a list.")
    if corpus_status == "available" and not raw_cases:
        raise ManifestError("An available corpus must contain at least one case.")
    cases = tuple(_parse_case(item, path.parent) for item in raw_cases)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ManifestError("Manifest case IDs must be unique.")
    return BenchmarkManifest(path, corpus_status, corpus_note, cases)


def verify_case_source(case: BenchmarkCase) -> bytes:
    """Read a declared local GLB and reject changed or missing source bytes."""
    try:
        source = case.source_path.read_bytes()
    except OSError as error:
        raise ManifestError(f"Source is not readable: {case.source_path}: {error}") from error
    actual = sha256(source).hexdigest()
    if actual != case.source_sha256:
        raise ManifestError(
            f"Source SHA-256 mismatch for {case.case_id}: "
            f"expected {case.source_sha256}, got {actual}."
        )
    return source


def validate_workloads(manifest: BenchmarkManifest, max_parts: int) -> None:
    """Reject unsafe effective requests before reading or converting source files.

    V6 and V7 retain their runner hard cap. V4 has no converter hard cap, so
    its requested detail is bounded here. This does not guarantee wall-clock
    duration; source complexity still affects conversion cost.
    """
    diagnostics: list[dict[str, object]] = []
    if not 0 < max_parts <= core.MAX_TARGET_PARTS:
        diagnostics.append(
            {
                "code": "invalid_hard_part_cap",
                "maxParts": max_parts,
                "maximum": core.MAX_TARGET_PARTS,
                "message": "maxParts must be within converter limits.",
            }
        )
    for case in manifest.cases:
        if case.target_parts > MAX_V4_BENCHMARK_TARGET_PARTS:
            diagnostics.append(
                {
                    "code": "v4_target_parts_exceeds_benchmark_limit",
                    "caseId": case.case_id,
                    "algorithmVersion": core.SURFACE_GRID_V4,
                    "targetParts": case.target_parts,
                    "maximumTargetParts": MAX_V4_BENCHMARK_TARGET_PARTS,
                    "message": (
                        "V4 targetParts exceeds this benchmark runner's safe "
                        "workload limit; targetParts is requested detail, not a hard part cap."
                    ),
                }
            )
        for algorithm in (
            core.SURFACE_GRID_V6_SHAPE_AWARE,
            core.SURFACE_GRID_V7_CONNECTIVITY_AWARE,
        ):
            diagnostics.append(
                {
                    "code": "effective_capped_workload",
                    "caseId": case.case_id,
                    "algorithmVersion": algorithm,
                    "targetParts": case.target_parts,
                    "maxParts": max_parts,
                    "effectiveGridTargetParts": min(
                        case.target_parts,
                        max(1, max_parts // core.RELIABLE_HARD_CAP_GRID_DIVISOR),
                    ),
                }
            )
    errors = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic["code"] != "effective_capped_workload"
    ]
    if errors:
        raise WorkloadError(errors)


def scale_comparison(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Classify algorithm pairs without treating different envelopes as controlled.

    Equal target/max settings are necessary but insufficient: current algorithms
    choose their own grid, so physical output dimensions must also agree.
    """
    completed = [record for record in records if record.get("status") == "completed"]
    comparisons: list[dict[str, object]] = []
    for index, first in enumerate(completed):
        for second in completed[index + 1 :]:
            if first["caseId"] != second["caseId"]:
                continue
            first_settings = first["converterSettings"]
            second_settings = second["converterSettings"]
            first_dimensions = first["physicalDimensions"]
            second_dimensions = second["physicalDimensions"]
            assert isinstance(first_settings, dict) and isinstance(second_settings, dict)
            assert isinstance(first_dimensions, dict) and isinstance(second_dimensions, dict)
            same_settings = (
                first_settings["targetParts"] == second_settings["targetParts"]
                and first_settings["maxParts"] == second_settings["maxParts"]
                and first["upAxis"] == second["upAxis"]
            )
            same_envelope = first_dimensions["outputMm"] == second_dimensions["outputMm"]
            comparisons.append(
                {
                    "caseId": first["caseId"],
                    "algorithms": [first["algorithmVersion"], second["algorithmVersion"]],
                    "status": "matched-scale"
                    if same_settings and same_envelope
                    else "scale-confounded",
                    "reason": None
                    if same_settings and same_envelope
                    else "converter settings or physical output dimensions differ",
                }
            )
    return comparisons


def aggregate_results(records: list[dict[str, object]]) -> dict[str, object]:
    """Keep failed records in the denominator and provide a compact machine summary."""
    by_algorithm: dict[str, dict[str, int]] = {}
    for record in records:
        algorithm = str(record.get("algorithmVersion", "not-run"))
        summary = by_algorithm.setdefault(algorithm, {"total": 0, "completed": 0, "failed": 0})
        summary["total"] += 1
        summary["completed" if record.get("status") == "completed" else "failed"] += 1
    return {
        "caseCount": len(records),
        "algorithms": by_algorithm,
        "comparisons": scale_comparison(records),
    }


def enrich_completed_record(
    record: dict[str, object], case: BenchmarkCase, model: core.LegoModel
) -> dict[str, object]:
    """Add Milestone 7A observations while preserving benchmark-v1 fields."""
    source = record["source"]
    assert isinstance(source, dict)
    buildability = analyze_buildability(model.placements)
    physical_collisions = colliding_placement_pairs(model.placements)
    topology_warnings: list[str] = []
    if not source["watertight"]:
        topology_warnings.append("source_not_watertight")
    record["sourceProvenance"] = {
        "path": str(case.source_path),
        "provenance": case.provenance,
        "usageRestrictions": case.usage_restrictions,
        "characteristics": list(case.characteristics),
    }
    record["physicalDimensions"] = {
        "outputMm": {
            "width": model.dimensions.width_mm,
            "depth": model.dimensions.depth_mm,
            "height": model.dimensions.height_mm,
        },
        "sourceAlignedMm": _source_dimensions_mm(model.metadata.grid_size),
    }
    record["sourceTopologyWarnings"] = topology_warnings
    existing_buildability = record["buildability"]
    assert isinstance(existing_buildability, dict)
    record["buildability"] = {
        **existing_buildability,
        "mechanicallyUnevaluatedPlacementCount": buildability.unevaluated_placement_count,
        "physicalCollisionPairCount": len(physical_collisions),
        "physicalCollisionPairs": [list(pair) for pair in physical_collisions],
        "limitations": (
            "Connectivity and collision proxies do not prove assembly stability or exterior union."
        ),
    }
    record["scaleValidity"] = "pending-comparison"
    return record


def _parse_case(value: object, manifest_directory: Path) -> BenchmarkCase:
    if not isinstance(value, dict):
        raise ManifestError("Each manifest case must be an object.")
    required = (
        "id",
        "path",
        "sha256",
        "provenance",
        "usageRestrictions",
        "characteristics",
        "upAxis",
        "targetParts",
    )
    if any(key not in value for key in required):
        raise ManifestError(
            "Each manifest case needs id, path, sha256, provenance, usageRestrictions, "
            "characteristics, upAxis, and targetParts."
        )
    case_id = value["id"]
    source_path = value["path"]
    source_sha256 = value["sha256"]
    characteristics = value["characteristics"]
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise ManifestError("Case id must be lowercase letters, digits, and hyphens.")
    if not isinstance(source_path, str) or not source_path.endswith(".glb"):
        raise ManifestError(f"Case {case_id} path must name a .glb file.")
    resolved = (manifest_directory / source_path).resolve()
    if manifest_directory.resolve() not in resolved.parents:
        raise ManifestError(f"Case {case_id} path must remain under the manifest directory.")
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ManifestError(f"Case {case_id} sha256 must be lowercase hexadecimal.")
    if not isinstance(characteristics, list) or not all(
        isinstance(item, str) for item in characteristics
    ):
        raise ManifestError(f"Case {case_id} characteristics must be a list of strings.")
    if not isinstance(value["provenance"], str) or not isinstance(value["usageRestrictions"], str):
        raise ManifestError(f"Case {case_id} provenance and usageRestrictions must be strings.")
    if (
        not isinstance(value["targetParts"], int)
        or not 0 < value["targetParts"] <= core.MAX_TARGET_PARTS
    ):
        raise ManifestError(f"Case {case_id} targetParts is outside converter limits.")
    try:
        axis = core.Axis(value["upAxis"])
    except ValueError as error:
        raise ManifestError(f"Case {case_id} has an invalid upAxis.") from error
    return BenchmarkCase(
        case_id,
        resolved,
        source_sha256,
        value["provenance"],
        value["usageRestrictions"],
        tuple(characteristics),
        axis,
        value["targetParts"],
    )


def _source_dimensions_mm(grid: core.GridSize) -> dict[str, float]:
    return {
        "width": grid.width_studs * core.STUD_WIDTH_MM,
        "depth": grid.depth_studs * core.STUD_WIDTH_MM,
        "height": grid.height_plates * core.PLATE_HEIGHT_MM,
    }
