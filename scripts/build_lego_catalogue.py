"""Validate the checked-in LEGO catalogue source and write the runtime JSON file."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Never, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_PATH = REPOSITORY_ROOT / "lego_catalogue" / "parts.json"
DEFAULT_OUTPUT_PATH = REPOSITORY_ROOT / "backend" / "app" / "conversion" / "generated_part_catalogue.json"
DEFAULT_ASSET_DIRECTORY = REPOSITORY_ROOT / "backend" / "app" / "conversion" / "part_geometry_assets"
SLOPE_33_FAMILY = "slope_33"
SLOPE_33_PROFILE = "rise_33_3"
SLOPE_33_LENGTH_STUDS = 3
SLOPE_33_HEIGHT_PLATES = 3

class CatalogueValidationError(ValueError):
    """The human-maintained catalogue source is not safe to generate."""


def _load_color_catalogue() -> Mapping[str, object]:
    """Load only static color data without importing the converter and its mesh dependencies."""
    colors_path = REPOSITORY_ROOT / "backend" / "app" / "conversion" / "colors.py"
    spec = importlib.util.spec_from_file_location("lego_catalogue_colors", colors_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the verified color catalogue.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(Mapping[str, object], module.COLORS_BY_ID)


COLORS_BY_ID = _load_color_catalogue()


def _error(message: str) -> Never:
    raise CatalogueValidationError(message)


def _required_string(record: Mapping[str, object], field: str, part_id: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        _error(f"Part {part_id}: {field} must be a non-empty string.")
    return value


def _optional_string(record: Mapping[str, object], field: str, part_id: str) -> str | None:
    if field not in record:
        return None
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        _error(f"Part {part_id}: {field} must be a non-empty string when provided.")
    return value


def _positive_integer(record: Mapping[str, object], field: str, part_id: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _error(f"Part {part_id}: {field} must be a positive integer.")
    return value


def _verified_color_ids(record: Mapping[str, object], part_id: str) -> list[str]:
    value = record.get("verifiedColorIds")
    if not isinstance(value, list) or not all(isinstance(color_id, str) for color_id in value):
        _error(f"Part {part_id}: verifiedColorIds must be an array of canonical color IDs.")
    color_ids = cast(list[str], value)
    if len(color_ids) != len(set(color_ids)):
        _error(f"Part {part_id}: verifiedColorIds must not contain duplicates.")
    unknown_colors = set(color_ids) - set(COLORS_BY_ID)
    if unknown_colors:
        _error(
            f"Part {part_id}: verifiedColorIds references unknown colors: "
            + ", ".join(sorted(unknown_colors))
            + "."
        )
    return color_ids


def _read_records(source_path: Path) -> list[Mapping[str, object]]:
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except OSError as error:
        _error(f"Could not read catalogue source {source_path}: {error}")
    except json.JSONDecodeError as error:
        _error(f"Catalogue source {source_path} is not valid JSON: {error.msg}")
    if not isinstance(payload, list):
        _error("Catalogue source must be a JSON array of part records.")
    records: list[Mapping[str, object]] = []
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            _error(f"Catalogue record {index} must be an object.")
        records.append(cast(Mapping[str, object], record))
    return records


def validate_records(
    records: Sequence[Mapping[str, object]],
    *,
    asset_directory: Path,
) -> list[dict[str, object]]:
    """Validate records and return their stable runtime representation."""
    normalized: list[dict[str, object]] = []
    part_ids: set[str] = set()
    ldraw_ids: set[str] = set()
    fitter_orders: set[int] = set()

    for record in records:
        part_id = _required_string(record, "partId", "<unknown>")
        if part_id in part_ids:
            _error(f"Duplicate canonical partId: {part_id}.")
        part_ids.add(part_id)

        name = _required_string(record, "name", part_id)
        family = _required_string(record, "family", part_id)
        shape = _required_string(record, "shape", part_id)
        width_studs = _positive_integer(record, "widthStuds", part_id)
        length_studs = _positive_integer(record, "lengthStuds", part_id)
        height_plates = _positive_integer(record, "heightPlates", part_id)
        slope_profile = _optional_string(record, "slopeProfile", part_id)
        ldraw_id = _optional_string(record, "ldrawId", part_id)
        bricklink_id = _optional_string(record, "bricklinkId", part_id)
        geometry_asset = _optional_string(record, "geometryAsset", part_id)
        verified_color_ids = _verified_color_ids(record, part_id)

        if ldraw_id is not None:
            if ldraw_id in ldraw_ids:
                _error(f"Duplicate ldrawId: {ldraw_id}.")
            ldraw_ids.add(ldraw_id)
        if geometry_asset is not None and not (asset_directory / f"{geometry_asset}.json").is_file():
            _error(f"Part {part_id}: geometry asset {geometry_asset}.json does not exist.")
        if family == SLOPE_33_FAMILY:
            if slope_profile != SLOPE_33_PROFILE:
                _error(f"Part {part_id}: slope_33 parts must use {SLOPE_33_PROFILE}.")
            if (
                length_studs != SLOPE_33_LENGTH_STUDS
                or height_plates != SLOPE_33_HEIGHT_PLATES
            ):
                _error(
                    f"Part {part_id}: {SLOPE_33_PROFILE} requires "
                    f"{SLOPE_33_LENGTH_STUDS} studs by {SLOPE_33_HEIGHT_PLATES} plates."
                )
        elif slope_profile is not None:
            _error(f"Part {part_id}: only slope families may define slopeProfile.")

        fitter_enabled = record.get("fitterEnabled")
        if not isinstance(fitter_enabled, bool):
            _error(f"Part {part_id}: fitterEnabled must be true or false.")
        fitter_order = record.get("fitterOrder")
        if fitter_enabled:
            if isinstance(fitter_order, bool) or not isinstance(fitter_order, int) or fitter_order < 0:
                _error(f"Part {part_id}: fitterOrder must be a non-negative integer when enabled.")
            if fitter_order in fitter_orders:
                _error(f"Duplicate fitterOrder: {fitter_order}.")
            fitter_orders.add(fitter_order)
            if not verified_color_ids:
                _error(f"Fitter-enabled part {part_id} has no verified color IDs.")
        elif fitter_order is not None:
            _error(f"Part {part_id}: disabled parts must not define fitterOrder.")

        normalized_record: dict[str, object] = {
            "partId": part_id,
            "name": name,
            "family": family,
            "shape": shape,
            "widthStuds": width_studs,
            "lengthStuds": length_studs,
            "heightPlates": height_plates,
            "slopeProfile": slope_profile,
            "ldrawId": ldraw_id,
            "bricklinkId": bricklink_id,
            "geometryAsset": geometry_asset,
            "verifiedColorIds": verified_color_ids,
            "fitterEnabled": fitter_enabled,
            "fitterOrder": fitter_order,
        }
        normalized.append(normalized_record)

    expected_orders = set(range(len(fitter_orders)))
    if fitter_orders != expected_orders:
        _error("Fitter orders must be contiguous, starting at 0.")

    return sorted(normalized, key=lambda record: cast(str, record["partId"]))


def build_catalogue(
    source_path: Path,
    output_path: Path,
    asset_directory: Path,
) -> bytes:
    records = _read_records(source_path)
    normalized = validate_records(records, asset_directory=asset_directory)
    content = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8", newline="\n")
    return content.encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--asset-directory", type=Path, default=DEFAULT_ASSET_DIRECTORY)
    arguments = parser.parse_args()
    try:
        build_catalogue(arguments.source, arguments.output, arguments.asset_directory)
    except CatalogueValidationError as error:
        print(f"Catalogue build failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
