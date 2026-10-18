from __future__ import annotations

from pathlib import Path

import pytest

from app.conversion.ldraw_importer import (
    LDrawImportError,
    import_part_geometry,
    referenced_source_files,
)
from app.conversion.part_coordinates import LDrawSourceFrame, LongAxis


def source_frame(part_id: str, long_axis: LongAxis = "x") -> LDrawSourceFrame:
    return LDrawSourceFrame(part_id, part_id, long_axis, (0.0, 0.0, 0.0))


def write_ldraw_file(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_type_1_reference_composes_its_transform_and_normalizes_coordinates(tmp_path: Path) -> None:
    write_ldraw_file(
        tmp_path,
        "parts/example.dat",
        "1 16 20 8 0 2 0 0 0 1 0 0 0 1 child.dat\n",
    )
    write_ldraw_file(tmp_path, "parts/child.dat", "3 16 0 0 0 10 0 0 0 8 0\n")

    geometry = import_part_geometry(
        tmp_path, source_file="example.dat", source_frame=source_frame("example")
    )

    assert geometry.minimum == (0.0, 0.0, 0.0)
    assert geometry.maximum == (1.0, 0.0, 1.0)
    assert geometry.positions == (0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0)


def test_quad_records_are_triangulated_in_a_stable_order(tmp_path: Path) -> None:
    write_ldraw_file(
        tmp_path,
        "parts/quad.dat",
        "4 16 0 0 0 20 0 0 20 0 20 0 0 20\n",
    )

    geometry = import_part_geometry(
        tmp_path, source_file="quad.dat", source_frame=source_frame("quad")
    )

    assert geometry.indices == (0, 1, 2, 3, 4, 5)
    assert len(geometry.positions) == 18


def test_recursive_references_are_resolved_and_reported(tmp_path: Path) -> None:
    write_ldraw_file(tmp_path, "parts/root.dat", "1 16 0 0 0 1 0 0 0 1 0 0 0 1 s\\middle.dat\n")
    write_ldraw_file(tmp_path, "parts/s/middle.dat", "1 16 0 0 0 1 0 0 0 1 0 0 0 1 leaf.dat\n")
    write_ldraw_file(tmp_path, "parts/s/leaf.dat", "3 16 0 0 0 20 0 0 0 8 0\n")

    geometry = import_part_geometry(
        tmp_path, source_file="root.dat", source_frame=source_frame("root")
    )
    sources = referenced_source_files(tmp_path, "root.dat")

    assert len(geometry.indices) == 3
    assert [path.relative_to(tmp_path).as_posix() for path in sources] == [
        "parts/root.dat",
        "parts/s/leaf.dat",
        "parts/s/middle.dat",
    ]


def test_cycle_and_missing_reference_are_safe_errors(tmp_path: Path) -> None:
    write_ldraw_file(tmp_path, "parts/cycle.dat", "1 16 0 0 0 1 0 0 0 1 0 0 0 1 loop.dat\n")
    write_ldraw_file(tmp_path, "parts/loop.dat", "1 16 0 0 0 1 0 0 0 1 0 0 0 1 cycle.dat\n")
    write_ldraw_file(tmp_path, "parts/missing.dat", "1 16 0 0 0 1 0 0 0 1 0 0 0 1 absent.dat\n")

    with pytest.raises(LDrawImportError, match="cycle"):
        import_part_geometry(tmp_path, source_file="cycle.dat", source_frame=source_frame("cycle"))
    with pytest.raises(LDrawImportError, match="Missing"):
        import_part_geometry(
            tmp_path, source_file="missing.dat", source_frame=source_frame("missing")
        )


def test_imported_output_is_byte_stable(tmp_path: Path) -> None:
    write_ldraw_file(
        tmp_path,
        "parts/example.dat",
        "3 16 -20 8 -20 20 0 20 0 24 0\n",
    )

    first = import_part_geometry(
        tmp_path, source_file="example.dat", source_frame=source_frame("example")
    )
    second = import_part_geometry(
        tmp_path, source_file="example.dat", source_frame=source_frame("example")
    )

    assert first.to_json_bytes() == second.to_json_bytes()
