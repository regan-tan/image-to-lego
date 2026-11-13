"""Compare V4, V6, and V7 on SHA-pinned local GLBs named by a manifest."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.fidelity import render_silhouette_masks  # noqa: E402
from app.conversion.real_world_benchmark import (  # noqa: E402
    SUMMARY_SCHEMA_VERSION,
    BenchmarkCase,
    ManifestError,
    WorkloadError,
    aggregate_results,
    enrich_completed_record,
    load_manifest,
    validate_workloads,
    verify_case_source,
)

if TYPE_CHECKING:
    from PIL import Image

ALGORITHMS = (
    core.SURFACE_GRID_V4,
    core.SURFACE_GRID_V6_SHAPE_AWARE,
    core.SURFACE_GRID_V7_CONNECTIVITY_AWARE,
)
DEFAULT_HARD_PART_CAP = 120


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("../artifacts/real-world-lego-benchmark")
    )
    parser.add_argument("--max-parts", type=int, default=DEFAULT_HARD_PART_CAP)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        manifest = load_manifest(arguments.manifest)
        validate_workloads(manifest, arguments.max_parts)
    except ManifestError as error:
        print(error, file=sys.stderr)
        return 2
    except WorkloadError as error:
        print(str(error), file=sys.stderr)
        print(
            json.dumps(
                {
                    "schemaVersion": "real-world-lego-benchmark-diagnostics-v1",
                    "diagnostics": error.diagnostics,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    output = arguments.output_dir
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for case in manifest.cases:
        try:
            source = verify_case_source(case)
        except ManifestError as error:
            for algorithm in ALGORITHMS:
                records.append(_failed(case, algorithm, str(error)))
            continue
        for algorithm in ALGORITHMS:
            records.append(_run_case(case, source, algorithm, arguments.max_parts, output))
    summary = {
        "schemaVersion": SUMMARY_SCHEMA_VERSION,
        "manifest": {
            "path": str(manifest.path),
            "corpusStatus": manifest.corpus_status,
            "corpusNote": manifest.corpus_note,
        },
        "hardPartCap": arguments.max_parts,
        "records": records,
        "aggregation": aggregate_results(records),
        "limitations": [
            "Metrics are existing silhouette-v1 and placement-surface-proxy-v1 measurements.",
            "No volumetric IoU or physical-stability guarantee is claimed.",
            "Absolute surface distances are not compared across scale-confounded runs.",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(records)} records to {output}")
    return 0 if all(record["status"] == "completed" for record in records) else 1


def _run_case(
    case: BenchmarkCase, source: bytes, algorithm: str, max_parts: int, output: Path
) -> dict[str, object]:
    settings = core.ConversionSettings(
        target_parts=case.target_parts,
        up_axis=case.up_axis,
        algorithm_version=algorithm,
        max_parts=max_parts if algorithm != core.SURFACE_GRID_V4 else None,
    )
    started = time.perf_counter()
    try:
        model = core.convert_glb(source, settings)
        source_mesh, source_vertices, source_faces = benchmark.aligned_source_mesh(
            source, settings, model.metadata.grid_size
        )
        masks = render_silhouette_masks(
            source_vertices,
            source_faces,
            core._placement_boxes(model.placements),
            slope_vertices=core._slope_vertices(model.placements),
            wedge_vertices=core._wedge_vertices(model.placements),
        )
        record = benchmark.case_record(
            case_id=case.case_id,
            case_name=case.case_id,
            source=source,
            settings=settings,
            model=model,
            source_mesh=source_mesh,
            source_faces=source_faces,
            geometric=benchmark.evaluate_geometric_fidelity(
                source_vertices, source_faces, model.placements
            ),
            opening=benchmark.opening_void_diagnostic(masks),
            runtime_seconds=time.perf_counter() - started,
        )
        record = enrich_completed_record(record, case, model)
        _write_images(output / "cases" / case.case_id / algorithm, masks)
        return record
    except TimeoutError as error:
        record = _failed(case, algorithm, str(error))
        record["status"] = "timeout"
        return record
    except (core.ConversionError, ManifestError, OSError, ValueError) as error:
        return _failed(case, algorithm, str(error))


def _failed(case: BenchmarkCase, algorithm: str, reason: str) -> dict[str, object]:
    record = benchmark.failed_record(case.case_id, case.case_id, reason)
    record["algorithmVersion"] = algorithm
    record["sourceProvenance"] = {
        "path": str(case.source_path),
        "provenance": case.provenance,
        "usageRestrictions": case.usage_restrictions,
        "characteristics": list(case.characteristics),
    }
    return record


def _write_images(directory: Path, masks: dict[str, tuple[Image.Image, Image.Image]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for view, (source, output) in masks.items():
        source.save(directory / f"source_{view}.png", format="PNG")
        output.save(directory / f"lego_{view}.png", format="PNG")
        benchmark.make_overlay(source, output).save(directory / f"{view}_overlay.png", format="PNG")


if __name__ == "__main__":
    raise SystemExit(main())
