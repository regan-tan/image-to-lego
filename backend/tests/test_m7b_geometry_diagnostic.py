import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.conversion import benchmark, core
from app.conversion.real_world_benchmark import ManifestError
from scripts.diagnose_m7b_geometry import run_diagnostic


def _manifest(path: Path, source_name: str, source_hash: str) -> Path:
    manifest = {
        "schemaVersion": "real-world-glb-manifest-v1",
        "corpusStatus": "available",
        "corpusNote": "Synthetic diagnostic test fixture",
        "cases": [
            {
                "id": "box",
                "path": source_name,
                "sha256": source_hash,
                "provenance": "synthetic test fixture",
                "usageRestrictions": "test only",
                "characteristics": ["axis-aligned"],
                "upAxis": "y",
                "targetParts": 4,
            }
        ],
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_runner_writes_deterministic_counts_for_a_sha_pinned_fixture(tmp_path: Path) -> None:
    source = benchmark.glb_bytes(benchmark.synthetic_cases()[0].mesh)
    source_path = tmp_path / "box.glb"
    source_path.write_bytes(source)
    manifest_path = _manifest(
        tmp_path / "manifest.json", source_path.name, sha256(source).hexdigest()
    )
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    run_diagnostic(manifest_path, first_output, target_parts=4, max_parts=16)
    run_diagnostic(manifest_path, second_output, target_parts=4, max_parts=16)

    assert first_output.read_bytes() == second_output.read_bytes()
    result = json.loads(first_output.read_text(encoding="utf-8"))["cases"]["box"]
    counts = result["cellCounts"]
    assert result["sourceSha256"] == sha256(source).hexdigest()
    assert counts["sourceSurface"] > 0
    assert counts["projectionHullCandidate"] >= counts["v3RectangularExterior"]
    assert counts["finalOccupied"] > 0
    assert all(
        values["falsePositivePixels"] >= 0 and values["falseNegativePixels"] >= 0
        for values in result["finalProjectionDeltaFromSourceSurface"].values()
    )


def test_runner_rejects_a_manifest_hash_mismatch(tmp_path: Path) -> None:
    source_path = tmp_path / "box.glb"
    source_path.write_bytes(benchmark.glb_bytes(benchmark.synthetic_cases()[0].mesh))
    manifest_path = _manifest(tmp_path / "manifest.json", source_path.name, "0" * 64)

    with pytest.raises(ManifestError, match="SHA-256 mismatch"):
        run_diagnostic(manifest_path, tmp_path / "output.json", target_parts=4, max_parts=16)


def test_runner_rejects_settings_that_do_not_match_the_manifest(tmp_path: Path) -> None:
    source = benchmark.glb_bytes(benchmark.synthetic_cases()[0].mesh)
    source_path = tmp_path / "box.glb"
    source_path.write_bytes(source)
    manifest_path = _manifest(
        tmp_path / "manifest.json", source_path.name, sha256(source).hexdigest()
    )

    with pytest.raises(ValueError, match="requested target parts"):
        run_diagnostic(manifest_path, tmp_path / "output.json", target_parts=5, max_parts=16)


def test_runner_reports_an_invalid_hashed_glb_as_a_conversion_failure(tmp_path: Path) -> None:
    source = b"not a GLB"
    source_path = tmp_path / "invalid.glb"
    source_path.write_bytes(source)
    manifest_path = _manifest(
        tmp_path / "manifest.json", source_path.name, sha256(source).hexdigest()
    )

    with pytest.raises(core.ConversionError, match="readable GLB mesh"):
        run_diagnostic(manifest_path, tmp_path / "output.json", target_parts=4, max_parts=16)
