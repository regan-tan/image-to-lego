import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from app.conversion import benchmark, core
from app.conversion.opening_diagnostics import (
    placement_projected_opening_overlap,
    projected_opening_microcells,
)


def _matching_box() -> tuple[list[benchmark.Point3D], list[benchmark.Face], core.BrickPlacement]:
    brick = core.BRICK_CATALOGUE[0]
    placement = core.BrickPlacement(brick, core.GridPosition(0, 0, 0), 0)
    box = core._placement_boxes((placement,))[0]
    minimum_x, minimum_y, minimum_z, maximum_x, maximum_y, maximum_z = box
    vertices = [
        (minimum_x, minimum_y, minimum_z),
        (maximum_x, minimum_y, minimum_z),
        (maximum_x, maximum_y, minimum_z),
        (minimum_x, maximum_y, minimum_z),
        (minimum_x, minimum_y, maximum_z),
        (maximum_x, minimum_y, maximum_z),
        (maximum_x, maximum_y, maximum_z),
        (minimum_x, maximum_y, maximum_z),
    ]
    faces = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    return vertices, faces, placement


def test_synthetic_fixtures_are_stable_and_cover_expected_topology() -> None:
    cases = benchmark.synthetic_cases()

    assert tuple(case.case_id for case in cases) == (
        "box",
        "thin-wall",
        "sphere",
        "cylinder",
        "pyramid",
        "l-profile",
        "ring",
        "open-box",
    )
    assert all(case.default_target_parts > 0 for case in cases)
    assert next(case for case in cases if case.case_id == "ring").mesh.is_watertight
    assert not next(case for case in cases if case.case_id == "open-box").mesh.is_watertight
    assert benchmark.glb_bytes(cases[0].mesh) == benchmark.glb_bytes(cases[0].mesh)


def test_frozen_baseline_hashes_match_the_current_fixture_definitions() -> None:
    baseline_path = (
        Path(__file__).parents[2]
        / "docs"
        / "testing"
        / "baselines"
        / "surface-grid-v4-fidelity-baseline-v1.json"
    )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected_hashes = {
        case.case_id: sha256(benchmark.glb_bytes(case.mesh)).hexdigest()
        for case in benchmark.synthetic_cases()
    }

    assert baseline["fixtureVersion"] == benchmark.FIXTURE_VERSION
    assert baseline["evaluator"]["geometryMetricsVersion"] == benchmark.GEOMETRY_METRICS_VERSION
    assert {
        item["caseId"]: item["sourceSha256"] for item in baseline["fixtures"]
    } == expected_hashes
    assert baseline["converterSourceCommit"] == baseline["sourceCommit"]
    for run in baseline["runs"]:
        for result in run.get("results", []):
            if result["status"] == "completed":
                assert "gridDimensions" in result
                assert "sourceBoundingBoxDimensionsMm" in result
                assert "normalizedChamfer" in result
            if result["status"] == "completed_geometry_unavailable":
                assert result["symmetricChamferMm"] is None
                assert result["normalizedChamfer"] is None
                assert result["p95NearestSurfaceMm"] is None
                assert result["geometricReason"]


def test_identical_geometry_has_zero_symmetric_surface_error() -> None:
    vertices, faces, placement = _matching_box()

    metrics = benchmark.evaluate_geometric_fidelity(vertices, faces, (placement,), sample_count=96)

    assert metrics.status == "available"
    assert metrics.symmetric_chamfer_mm == pytest.approx(0.0, abs=1e-6)
    assert metrics.percentile_95_nearest_surface_mm == pytest.approx(0.0, abs=1e-6)


def test_source_alignment_uses_converter_normalization_and_grid_scaling() -> None:
    source = benchmark.glb_bytes(benchmark.synthetic_cases()[0].mesh)
    settings = core.ConversionSettings(target_parts=12, up_axis=core.Axis.Y)
    grid_size = core.GridSize(5, 4, 6)

    _, scaled, faces = benchmark.aligned_source_mesh(source, settings, grid_size)
    mesh = core._load_mesh(source)
    original = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    expected = core._scale_vertices_to_grid(
        core._normalize_vertices(original, core.Axis.Y), grid_size
    )

    assert scaled == expected
    assert len(faces) == len(mesh.faces)


def test_displaced_geometry_and_symmetric_metric_are_detectable_and_deterministic() -> None:
    vertices, faces, placement = _matching_box()
    shifted = core.BrickPlacement(placement.brick_type, core.GridPosition(1, 0, 0), 0)

    exact = benchmark.evaluate_geometric_fidelity(vertices, faces, (placement,), sample_count=96)
    displaced = benchmark.evaluate_geometric_fidelity(vertices, faces, (shifted,), sample_count=96)

    assert displaced.symmetric_chamfer_mm is not None
    assert exact.symmetric_chamfer_mm is not None
    assert displaced.symmetric_chamfer_mm > exact.symmetric_chamfer_mm
    assert displaced == benchmark.evaluate_geometric_fidelity(
        vertices, faces, (shifted,), sample_count=96
    )


def test_grid_coordinates_use_physical_stud_and_plate_scales() -> None:
    triangles = benchmark._grid_to_mm(
        benchmark._triangles_from_mesh([(0, 0, 0), (1, 1, 1), (0, 1, 0)], [(0, 1, 2)])
    )

    assert tuple(triangles[0, 1]) == (8.0, 8.0, 3.2)


def test_open_fixture_never_claims_a_trusted_safe_interior() -> None:
    open_case = next(case for case in benchmark.synthetic_cases() if case.case_id == "open-box")
    source = benchmark.glb_bytes(open_case.mesh)
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    normalized = core._normalize_vertices(vertices, core.Axis.Y)
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]

    occupancy = core._source_occupancy(normalized, faces, core.GridSize(6, 6, 6))

    assert not mesh.is_watertight
    assert occupancy.safe_interior_cells == frozenset()


def test_geometric_metric_rejects_unbounded_sample_requests() -> None:
    vertices, faces, placement = _matching_box()

    with pytest.raises(ValueError, match="sample_count"):
        benchmark.evaluate_geometric_fidelity(vertices, faces, (placement,), sample_count=0)


def test_non_finite_surface_calculation_is_not_reported_as_accuracy() -> None:
    _, faces, placement = _matching_box()
    vertices = [(0.0, 0.0, 0.0), (float("inf"), 0.0, 0.0), (0.0, 1.0, 0.0)]

    metrics = benchmark.evaluate_geometric_fidelity(vertices, faces[:1], (placement,))

    assert metrics.status == "unavailable"
    assert metrics.symmetric_chamfer_mm is None


def test_opening_diagnostic_distinguishes_preserved_and_filled_voids() -> None:
    source = Image.new("1", (8, 8))
    for y in range(1, 7):
        for x in range(1, 7):
            if not (3 <= x <= 4 and 3 <= y <= 4):
                source.putpixel((x, y), 1)
    preserved = source.copy()
    filled = source.copy()
    for y in range(3, 5):
        for x in range(3, 5):
            filled.putpixel((x, y), 1)
    blank = Image.new("1", source.size)

    preserved_result = benchmark.opening_void_diagnostic(
        {"front": (blank, blank), "side": (blank, blank), "top": (source, preserved)}
    )
    filled_result = benchmark.opening_void_diagnostic(
        {"front": (blank, blank), "side": (blank, blank), "top": (source, filled)}
    )

    assert preserved_result.filled_void_ratio == 0.0
    assert filled_result.filled_void_ratio == 1.0


def test_projected_opening_microcells_reject_a_rectangle_over_a_ring_aperture() -> None:
    ring = next(case for case in benchmark.synthetic_cases() if case.case_id == "ring")
    source = benchmark.glb_bytes(ring.mesh)
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    normalized = core._normalize_vertices(vertices, ring.up_axis)
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    grid_size = core.GridSize(8, 8, 6)
    opening = projected_opening_microcells(
        core._scale_vertices_to_grid(normalized, grid_size), faces, grid_size
    )
    plate = next(
        part
        for part in core.BRICK_CATALOGUE
        if part.shape == "rectangular"
        and part.length_studs == 1
        and part.width_studs == 1
        and part.height_plates == 1
    )

    assert opening
    assert placement_projected_opening_overlap(
        core.BrickPlacement(plate, core.GridPosition(3, 3, 0), 0), opening
    ) > 0
    assert placement_projected_opening_overlap(
        core.BrickPlacement(plate, core.GridPosition(0, 0, 0), 0), opening
    ) == 0


def test_overlay_uses_distinct_missing_and_extra_colors() -> None:
    source = Image.new("1", (2, 1))
    output = Image.new("1", (2, 1))
    source.putpixel((0, 0), 1)
    output.putpixel((1, 0), 1)

    overlay = benchmark.make_overlay(source, output)

    assert overlay.getpixel((0, 0)) == benchmark.MISSING_COLOR
    assert overlay.getpixel((1, 0)) == benchmark.EXTRA_COLOR


def test_cli_smoke_writes_schema_json_csv_and_png(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_conversion_fidelity.py"
    output = tmp_path / "benchmark"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--suite",
            "synthetic",
            "--case",
            "box",
            "--target-parts",
            "12",
            "--output-dir",
            str(output),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["schemaVersion"] == benchmark.BENCHMARK_SCHEMA_VERSION
    assert summary["cases"][0]["status"] == "completed"
    assert summary["cases"][0]["buildability"]["analysisVersion"] == "stud-connectivity-v1"
    assert (output / "summary.csv").is_file()
    assert (output / "cases" / "box" / "top_overlay.png").is_file()


def test_cli_v7_cylinder_reaches_the_real_connectivity_aware_conversion(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_conversion_fidelity.py"
    output = tmp_path / "benchmark"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--suite",
            "synthetic",
            "--case",
            "cylinder",
            "--algorithm",
            core.SURFACE_GRID_V7_CONNECTIVITY_AWARE,
            "--target-parts",
            "16",
            "--max-parts",
            "16",
            "--output-dir",
            str(output),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    record = summary["cases"][0]
    assert record["algorithmVersion"] == core.SURFACE_GRID_V7_CONNECTIVITY_AWARE
    assert record["buildability"] == {
        "analysisVersion": "stud-connectivity-v1",
        "connectedComponentCount": 1,
        "largestComponentFraction": 1.0,
        "isolatedPlacementCount": 0,
        "unsupportedPlacementCount": 0,
    }
    diagnostics = record["conversionDiagnostics"]
    assert diagnostics["connectivity_optimization_attempted"]
    assert diagnostics["connectivity_accepted"]


def test_cli_lists_supported_algorithms_and_rejects_unknown_algorithm(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_conversion_fidelity.py"
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    invalid_result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--suite",
            "synthetic",
            "--algorithm",
            "not-an-algorithm",
            "--output-dir",
            str(tmp_path / "invalid"),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert help_result.returncode == 0
    for algorithm in (
        core.SURFACE_GRID_V3,
        core.SURFACE_GRID_V4,
        core.SURFACE_GRID_V5_RELIABLE,
        core.SURFACE_GRID_V6_SHAPE_AWARE,
        core.SURFACE_GRID_V7_CONNECTIVITY_AWARE,
    ):
        assert algorithm in help_result.stdout
    assert invalid_result.returncode == 2
    assert "invalid choice" in invalid_result.stderr


def test_cli_records_invalid_glb_without_reporting_success(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "benchmark_conversion_fidelity.py"
    source = tmp_path / "invalid.glb"
    source.write_bytes(b"not a glb")
    output = tmp_path / "benchmark"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--source",
            str(source),
            "--target-parts",
            "12",
            "--output-dir",
            str(output),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result.returncode == 1
    assert summary["cases"][0]["status"] == "failed"
    assert "readable GLB" in summary["cases"][0]["failureReason"]
