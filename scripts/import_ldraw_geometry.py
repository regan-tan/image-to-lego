"""Generate checked-in part geometry assets from an official local LDraw library."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from shutil import copyfile
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.conversion.ldraw_importer import (
    import_part_geometry,
    referenced_source_files,
    write_geometry_asset,
)

PARTS = (
    ("3001", "3001.dat", "x"),
    ("4286", "4286.dat", "z"),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library_root", type=Path, help="Path to the extracted ldraw directory.")
    parser.add_argument("output_directory", type=Path, help="Directory for generated JSON assets.")
    parser.add_argument(
        "--source-evidence-directory",
        type=Path,
        help="Optional directory for the exact LDraw source files used by the generated assets.",
    )
    arguments = parser.parse_args()
    library_root = arguments.library_root.resolve()

    started = perf_counter()
    for part_id, source_file, long_axis in PARTS:
        geometry = import_part_geometry(
            library_root,
            part_id=part_id,
            source_file=source_file,
            long_axis=long_axis,
        )
        write_geometry_asset(geometry, arguments.output_directory / f"{part_id}.json")
        if arguments.source_evidence_directory is not None:
            for source_path in referenced_source_files(library_root, source_file):
                destination = arguments.source_evidence_directory / source_path.relative_to(
                    library_root
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                copyfile(source_path, destination)
    print(f"Generated {len(PARTS)} assets in {perf_counter() - started:.3f}s.")


if __name__ == "__main__":
    main()
