"""Run the offline conversion-fidelity benchmark against synthetic or local GLB input."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import benchmark, core  # noqa: E402
from app.conversion.fidelity import render_silhouette_masks  # noqa: E402

DEFAULT_OUTPUT_DIRECTORY = Path("../artifacts/lego-fidelity-benchmark")
CSV_COLUMNS = (
    "caseId",
    "status",
    "algorithmVersion",
    "upAxis",
    "sourceSha256",
    "targetParts",
    "actualParts",
    "partCountDelta",
    "partCountErrorRatio",
    "frontIou",
    "sideIou",
    "topIou",
    "meanIou",
    "symmetricChamferMm",
    "p95NearestSurfaceMm",
    "normalizedSymmetricChamfer",
    "openingFilledVoidRatio",
    "runtimeSeconds",
    "failureReason",
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--suite", choices=("synthetic",))
    source_group.add_argument("--source", type=Path)
    parser.add_argument(
        "--algorithm",
        choices=(
            core.SURFACE_GRID_V3,
            core.SURFACE_GRID_V4,
            core.SURFACE_GRID_V5_RELIABLE,
            core.SURFACE_GRID_V6_SHAPE_AWARE,
        ),
        default=core.SURFACE_GRID_V4,
    )
    parser.add_argument("--target-parts", type=int)
    parser.add_argument("--max-parts", type=int)
    parser.add_argument(
        "--up-axis", choices=tuple(axis.value for axis in core.Axis), default=core.Axis.Y.value
    )
    parser.add_argument(
        "--case",
        dest="case_ids",
        action="append",
        help="Synthetic case ID; repeat to select several cases.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run all synthetic cases instead of the small default smoke suite.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.target_parts is not None:
        _validate_target_parts(arguments.target_parts)
    if arguments.max_parts is not None:
        _validate_target_parts(arguments.max_parts)
    if arguments.max_parts is not None and arguments.algorithm not in {
        core.SURFACE_GRID_V5_RELIABLE,
        core.SURFACE_GRID_V6_SHAPE_AWARE,
    }:
        raise SystemExit(
            "--max-parts requires --algorithm surface-grid-v5-reliable or "
            "surface-grid-v6-shape-aware."
        )
    if arguments.source is not None:
        if not arguments.source.is_file():
            print("Source path must name a readable GLB file.", file=sys.stderr)
            return 2
        cases: tuple[tuple[str, str, benchmark.SyntheticCase | None, bytes, core.Axis], ...] = (
            (
                arguments.source.stem,
                arguments.source.name,
                None,
                arguments.source.read_bytes(),
                core.Axis(arguments.up_axis),
            ),
        )
    else:
        selected = _select_synthetic_cases(arguments.case_ids, full=arguments.full)
        if selected is None:
            return 2
        cases = tuple(
            (case.case_id, case.name, case, benchmark.glb_bytes(case.mesh), case.up_axis)
            for case in selected
        )

    output_directory = arguments.output_dir
    output_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for case_id, case_name, synthetic, source, default_axis in cases:
        target_parts = arguments.target_parts or (
            synthetic.default_target_parts if synthetic else None
        )
        if target_parts is None:
            print(
                "--target-parts is required when benchmarking a user-provided source.",
                file=sys.stderr,
            )
            return 2
        settings = core.ConversionSettings(
            target_parts=target_parts,
            up_axis=default_axis if synthetic else core.Axis(arguments.up_axis),
            algorithm_version=arguments.algorithm,
            max_parts=arguments.max_parts,
        )
        record = _run_case(case_id, case_name, synthetic, source, settings, output_directory)
        records.append(record)
        _print_case_summary(record)

    _write_summary(output_directory, records)
    failed = [record for record in records if record["status"] != "completed"]
    print(f"Wrote {len(records)} benchmark record(s) to {output_directory}")
    return 1 if failed else 0


def _select_synthetic_cases(
    case_ids: list[str] | None, *, full: bool
) -> tuple[benchmark.SyntheticCase, ...] | None:
    cases = benchmark.synthetic_cases()
    available = {case.case_id: case for case in cases}
    if not case_ids:
        smoke_ids = {"box", "thin-wall"}
        return cases if full else tuple(case for case in cases if case.case_id in smoke_ids)
    unknown = sorted(set(case_ids) - set(available))
    if unknown:
        print(f"Unknown synthetic case ID(s): {', '.join(unknown)}", file=sys.stderr)
        return None
    return tuple(case for case in cases if case.case_id in case_ids)


def _validate_target_parts(target_parts: int) -> None:
    if target_parts <= 0 or target_parts > core.MAX_TARGET_PARTS:
        raise SystemExit(f"--target-parts must be between 1 and {core.MAX_TARGET_PARTS}.")


def _run_case(
    case_id: str,
    case_name: str,
    synthetic: benchmark.SyntheticCase | None,
    source: bytes,
    settings: core.ConversionSettings,
    output_directory: Path,
) -> dict[str, object]:
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
        geometry = benchmark.evaluate_geometric_fidelity(
            source_vertices, source_faces, model.placements
        )
        opening = benchmark.opening_void_diagnostic(masks)
        record = benchmark.case_record(
            case_id=case_id,
            case_name=case_name,
            source=source,
            settings=settings,
            model=model,
            source_mesh=source_mesh,
            source_faces=source_faces,
            geometric=geometry,
            opening=opening,
            runtime_seconds=time.perf_counter() - started,
            expected_characteristic=synthetic.expected_characteristic if synthetic else None,
        )
        _write_case_artifacts(output_directory / "cases" / case_id, record, masks)
        return record
    except (core.ConversionError, OSError, ValueError) as error:
        record = benchmark.failed_record(case_id, case_name, str(error))
        _write_case_artifacts(output_directory / "cases" / case_id, record, None)
        return record


def _write_case_artifacts(
    case_directory: Path,
    record: dict[str, object],
    masks: dict[str, tuple[Image.Image, Image.Image]] | None,
) -> None:
    case_directory.mkdir(parents=True, exist_ok=True)
    _write_json(case_directory / "metrics.json", record)
    if masks is None:
        return
    for view, (source, output) in masks.items():
        benchmark.make_overlay(source, output).save(
            case_directory / f"{view}_overlay.png", format="PNG"
        )


def _write_summary(output_directory: Path, records: Iterable[dict[str, object]]) -> None:
    record_list = list(records)
    _write_json(
        output_directory / "summary.json",
        {"schemaVersion": benchmark.BENCHMARK_SCHEMA_VERSION, "cases": record_list},
    )
    with (output_directory / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(_csv_row(record) for record in record_list)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )


def _csv_row(record: dict[str, object]) -> dict[str, object]:
    if record["status"] != "completed":
        return {
            "caseId": record["caseId"],
            "status": "failed",
            "failureReason": record["failureReason"],
        }
    silhouette = record["silhouette"]
    parts = record["parts"]
    geometry = record["geometric"]
    opening = record["openingDiagnostic"]
    runtime = record["runtime"]
    assert isinstance(silhouette, dict) and isinstance(parts, dict)
    assert isinstance(geometry, dict) and isinstance(opening, dict) and isinstance(runtime, dict)
    return {
        "caseId": record["caseId"],
        "status": "completed",
        "algorithmVersion": record["algorithmVersion"],
        "upAxis": record["upAxis"],
        "sourceSha256": record["sourceSha256"],
        "targetParts": parts["target"],
        "actualParts": parts["actual"],
        "partCountDelta": parts["delta"],
        "partCountErrorRatio": parts["errorRatio"],
        "frontIou": silhouette["front_iou"],
        "sideIou": silhouette["side_iou"],
        "topIou": silhouette["top_iou"],
        "meanIou": silhouette["mean_iou"],
        "symmetricChamferMm": geometry["symmetric_chamfer_mm"],
        "p95NearestSurfaceMm": geometry["percentile_95_nearest_surface_mm"],
        "normalizedSymmetricChamfer": geometry["normalized_symmetric_chamfer"],
        "openingFilledVoidRatio": opening["filled_void_ratio"],
        "runtimeSeconds": runtime["seconds"],
    }


def _print_case_summary(record: dict[str, object]) -> None:
    if record["status"] != "completed":
        print(f"{record['caseId']}: FAILED: {record['failureReason']}")
        return
    silhouette = record["silhouette"]
    geometric = record["geometric"]
    assert isinstance(silhouette, dict) and isinstance(geometric, dict)
    print(
        f"{record['caseId']}: mean IoU={silhouette['mean_iou']:.6f} "
        f"chamfer mm={geometric['symmetric_chamfer_mm']}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
