from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = REPOSITORY_ROOT / "lego_catalogue" / "parts.json"
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "build_lego_catalogue.py"
ASSET_DIRECTORY = REPOSITORY_ROOT / "backend" / "app" / "conversion" / "part_geometry_assets"
GENERATED_PATH = (
    REPOSITORY_ROOT / "backend" / "app" / "conversion" / "generated_part_catalogue.json"
)


def _source_records() -> list[dict[str, object]]:
    return cast(list[dict[str, object]], json.loads(SOURCE_PATH.read_text(encoding="utf-8")))


def _run_builder(source_path: Path, output_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--source",
            str(source_path),
            "--output",
            str(output_path),
            "--asset-directory",
            str(ASSET_DIRECTORY),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def _write_source(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


def test_source_catalogue_builds_to_the_checked_in_runtime_catalogue(tmp_path: Path) -> None:
    output_path = tmp_path / "generated.json"

    result = _run_builder(SOURCE_PATH, output_path)

    assert result.returncode == 0, result.stderr
    assert output_path.read_bytes() == GENERATED_PATH.read_bytes()


def test_catalogue_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    first = _run_builder(SOURCE_PATH, first_output)
    second = _run_builder(SOURCE_PATH, second_output)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first_output.read_bytes() == second_output.read_bytes()


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (
            lambda records: records.append(dict(records[0])),
            "Duplicate canonical partId: 3001.",
        ),
        (
            lambda records: records[1].__setitem__("fitterOrder", 0),
            "Duplicate fitterOrder: 0.",
        ),
        (
            lambda records: records[0].__setitem__("widthStuds", 0),
            "widthStuds must be a positive integer.",
        ),
        (
            lambda records: records[0].__setitem__("geometryAsset", "missing"),
            "geometry asset missing.json does not exist.",
        ),
        (
            lambda records: records[0].update({"verifiedColorIds": ["ldraw:999"]}),
            "Part 3001: verifiedColorIds references unknown colors: ldraw:999.",
        ),
        (
            lambda records: records[0].update({"verifiedColorIds": ["ldraw:4", "ldraw:4"]}),
            "Part 3001: verifiedColorIds must not contain duplicates.",
        ),
        (
            lambda records: records[0].update({"verifiedColorIds": []}),
            "Fitter-enabled part 3001 has no verified color IDs.",
        ),
        (
            lambda records: records[-1].__setitem__("slopeProfile", "unknown"),
            "Part 4286: slope_33 parts must use rise_33_3.",
        ),
    ],
)
def test_invalid_catalogue_source_fails_with_a_useful_message(
    tmp_path: Path,
    change: Callable[[list[dict[str, object]]], None],
    error: str,
) -> None:
    source_path = tmp_path / "parts.json"
    records = _source_records()
    change(records)
    _write_source(source_path, records)

    result = _run_builder(source_path, tmp_path / "generated.json")

    assert result.returncode != 0
    assert error in result.stderr
