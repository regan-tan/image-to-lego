from __future__ import annotations

from pathlib import Path

import pytest

from app.conversion.ldraw_importer import import_part_geometry, referenced_source_files
from app.conversion.part_coordinates import ldraw_source_frame

SOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / "part_geometry" / "ldraw_source"


@pytest.mark.parametrize(
    ("part_id", "source_file", "expected_root", "expected_bounds"),
    (
        ("3001", "3001.dat", "parts/3001.dat", (4.0, 2.0, 3.5)),
        ("3002", "3002.dat", "parts/3002.dat", (3.0, 2.0, 3.5)),
        ("3003", "3003.dat", "parts/3003.dat", (2.0, 2.0, 3.5)),
        ("3010", "3010.dat", "parts/3010.dat", (4.0, 1.0, 3.5)),
        ("3020", "3020.dat", "parts/3020.dat", (4.0, 2.0, 1.5)),
        ("3021", "3021.dat", "parts/3021.dat", (3.0, 2.0, 1.5)),
        ("3022", "3022.dat", "parts/3022.dat", (2.0, 2.0, 1.5)),
        ("3023", "3023b.dat", "parts/3023b.dat", (2.0, 1.0, 1.5)),
    ),
)
def test_calibration_root_hierarchies_are_complete_and_deterministic(
    part_id: str,
    source_file: str,
    expected_root: str,
    expected_bounds: tuple[float, float, float],
) -> None:
    first = referenced_source_files(SOURCE_DIRECTORY, source_file)
    second = referenced_source_files(SOURCE_DIRECTORY, source_file)

    assert first == second
    assert expected_root in {path.relative_to(SOURCE_DIRECTORY).as_posix() for path in first}
    assert all(path.is_file() for path in first)
    assert (
        import_part_geometry(
            SOURCE_DIRECTORY,
            source_file=source_file,
            source_frame=ldraw_source_frame(part_id),
        ).maximum
        == expected_bounds
    )


def test_coordinate_documentation_uses_the_tested_41769_ring_coordinate() -> None:
    document = (
        Path(__file__).resolve().parents[2] / "docs" / "architecture" / "part-coordinate-system.md"
    ).read_text(encoding="utf-8")

    expected_statement = (
        "Both 41770 and 41769\nresolve that full ring/tube at canonical `(3, 1, 0.5)`"
    )
    assert expected_statement in document
