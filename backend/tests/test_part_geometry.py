from __future__ import annotations

from pathlib import Path

import pytest

from app.conversion.ldraw_importer import import_part_geometry
from app.conversion.part_catalogue import ALL_PARTS
from app.conversion.part_coordinates import ldraw_source_frame
from app.conversion.part_geometry import ASSET_DIRECTORY, load_part_geometry

SOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / "part_geometry" / "ldraw_source"


@pytest.mark.parametrize(
    ("part_id", "source_file", "expected_bounds"),
    [
        ("3001", "3001.dat", (4.0, 2.0, 3.5)),
        ("4286", "4286.dat", (3.0, 1.0, 3.5)),
        ("15068", "15068.dat", (2.0, 2.0, 2.000008)),
        ("41769", "41769a.dat", (4.0, 2.0, 1.5)),
        ("41770", "41770a.dat", (4.0, 2.0, 1.5)),
    ],
)
def test_real_part_geometry_is_valid_and_reproducible(
    part_id: str,
    source_file: str,
    expected_bounds: tuple[float, float, float],
) -> None:
    loaded = load_part_geometry(part_id)
    generated = import_part_geometry(
        SOURCE_DIRECTORY,
        source_file=source_file,
        source_frame=ldraw_source_frame(part_id),
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


def test_4286_source_anchor_agrees_with_its_visual_asset_horizontal_frame() -> None:
    geometry = load_part_geometry("4286")

    assert geometry is not None
    visual_x_coordinates = geometry.positions[::3]
    # The asset is rebased from raw LDraw z=-50.  The explicit source anchor
    # maps those body landmarks into the same 0..3 catalogue-length frame.
    assert {0.0, 1.0, 2.5, 3.0}.issubset(set(visual_x_coordinates))
