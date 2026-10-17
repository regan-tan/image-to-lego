from __future__ import annotations

from pathlib import Path

import pytest

from app.conversion.ldraw_importer import import_part_geometry
from app.conversion.part_catalogue import ALL_PARTS
from app.conversion.part_geometry import ASSET_DIRECTORY, load_part_geometry

SOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / "part_geometry" / "ldraw_source"


@pytest.mark.parametrize(
    ("part_id", "source_file", "long_axis", "expected_bounds"),
    [
        ("3001", "3001.dat", "x", (4.0, 2.0, 3.5)),
        ("4286", "4286.dat", "z", (3.0, 1.0, 3.5)),
        ("15068", "15068.dat", "x", (2.0, 2.0, 2.000008)),
        ("41769", "41769a.dat", "z", (4.0, 2.0, 1.5)),
        ("41770", "41770a.dat", "z", (4.0, 2.0, 1.5)),
    ],
)
def test_real_part_geometry_is_valid_and_reproducible(
    part_id: str,
    source_file: str,
    long_axis: str,
    expected_bounds: tuple[float, float, float],
) -> None:
    loaded = load_part_geometry(part_id)
    generated = import_part_geometry(
        SOURCE_DIRECTORY,
        part_id=part_id,
        source_file=source_file,
        long_axis=long_axis,
    )

    assert loaded is not None
    assert len(loaded.positions) % 3 == 0
    assert len(loaded.indices) % 3 == 0
    assert all(index < len(loaded.positions) // 3 for index in loaded.indices)
    assert loaded.minimum == (0.0, 0.0, 0.0)
    assert loaded.maximum == expected_bounds
    assert generated.to_json_bytes() == (ASSET_DIRECTORY / f"{part_id}.json").read_bytes()


def test_catalogue_geometry_references_resolve() -> None:
    supported = {part.part_id: part for part in ALL_PARTS if part.geometry_asset is not None}

    assert set(supported) == {"3001", "4286", "15068", "41769", "41770"}
    for part_id, part in supported.items():
        assert load_part_geometry(part.geometry_asset) is not None
        if part_id in {"41769", "41770"}:
            assert part.geometry_asset == part_id
            assert part.ldraw_id == f"{part_id}a"
        else:
            assert part.geometry_asset == part.ldraw_id
