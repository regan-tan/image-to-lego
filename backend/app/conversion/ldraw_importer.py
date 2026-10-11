"""Build-time importer for the small set of LDraw geometry assets we support."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from math import isfinite
from pathlib import Path

LDU_PER_STUD = 20.0
LDU_PER_PLATE = 8.0
MAX_REFERENCE_DEPTH = 64

Point = tuple[float, float, float]
Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


class LDrawImportError(ValueError):
    """An LDraw source file cannot be imported into a safe triangle mesh."""


@dataclass(frozen=True, slots=True)
class ImportedPartGeometry:
    part_id: str
    positions: tuple[float, ...]
    indices: tuple[int, ...]
    minimum: Point
    maximum: Point
    source_file: str
    source_sha256: str

    def to_json_bytes(self) -> bytes:
        payload = {
            "bounds": {"maximum": list(self.maximum), "minimum": list(self.minimum)},
            "indices": list(self.indices),
            "partId": self.part_id,
            "positions": list(self.positions),
            "source": {"file": self.source_file, "sha256": self.source_sha256},
        }
        return (dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


IDENTITY: Matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ORIGIN: Point = (0.0, 0.0, 0.0)


def import_part_geometry(
    library_root: Path,
    *,
    part_id: str,
    source_file: str,
    long_axis: str,
) -> ImportedPartGeometry:
    """Resolve one LDraw part and normalize it to the application's LEGO grid space."""
    if long_axis not in {"x", "z"}:
        raise LDrawImportError("The part's LDraw long axis must be x or z.")

    root = library_root.resolve()
    source_path = _resolve_reference(root, root / "parts" / source_file, source_file)
    triangles: list[tuple[Point, Point, Point]] = []
    _read_file(root, source_path, IDENTITY, ORIGIN, False, (), triangles)
    if not triangles:
        raise LDrawImportError(f"{source_file} does not contain any surface triangles.")

    points = [_normalize_point(point, long_axis) for triangle in triangles for point in triangle]
    minimum: Point = (
        min(point[0] for point in points),
        min(point[1] for point in points),
        min(point[2] for point in points),
    )
    maximum: Point = (
        max(point[0] for point in points),
        max(point[1] for point in points),
        max(point[2] for point in points),
    )
    normalized = [
        _rounded_point((point[0] - minimum[0], point[1] - minimum[1], point[2] - minimum[2]))
        for point in points
    ]
    if any(not isfinite(value) for point in normalized for value in point):
        raise LDrawImportError("LDraw geometry contains non-finite coordinates.")

    positions = tuple(value for point in normalized for value in point)
    indices = tuple(range(len(normalized)))
    return ImportedPartGeometry(
        part_id=part_id,
        positions=positions,
        indices=indices,
        minimum=(0.0, 0.0, 0.0),
        maximum=_rounded_point(
            (
                maximum[0] - minimum[0],
                maximum[1] - minimum[1],
                maximum[2] - minimum[2],
            )
        ),
        source_file=f"parts/{source_file.replace('\\', '/')}",
        source_sha256=sha256(source_path.read_bytes()).hexdigest(),
    )


def write_geometry_asset(geometry: ImportedPartGeometry, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(geometry.to_json_bytes())


def referenced_source_files(library_root: Path, source_file: str) -> tuple[Path, ...]:
    """Return the exact local LDraw files used by a part's reference hierarchy."""
    root = library_root.resolve()
    source_path = _resolve_reference(root, root / "parts" / source_file, source_file)
    visited: set[Path] = set()

    def visit(path: Path, ancestors: tuple[Path, ...]) -> None:
        resolved_path = path.resolve()
        if len(ancestors) >= MAX_REFERENCE_DEPTH:
            raise LDrawImportError(
                f"LDraw reference depth exceeds {MAX_REFERENCE_DEPTH}: {path.name}"
            )
        if resolved_path in ancestors:
            raise LDrawImportError(f"LDraw reference cycle detected at {path.name}")
        if resolved_path in visited:
            return
        try:
            lines = resolved_path.read_text(encoding="utf-8-sig").splitlines()
        except FileNotFoundError as error:
            raise LDrawImportError(f"Missing LDraw reference: {path}") from error
        visited.add(resolved_path)
        for line_number, line in enumerate(lines, start=1):
            fields = line.split()
            if fields and fields[0] == "1":
                _, _, reference = _parse_reference(fields, path, line_number)
                visit(
                    _resolve_reference(root, resolved_path.parent, reference),
                    (*ancestors, resolved_path),
                )

    visit(source_path, ())
    return tuple(sorted(visited, key=lambda path: path.relative_to(root).as_posix()))


def _read_file(
    library_root: Path,
    path: Path,
    matrix: Matrix,
    translation: Point,
    flip_winding: bool,
    ancestors: tuple[Path, ...],
    triangles: list[tuple[Point, Point, Point]],
) -> None:
    resolved_path = path.resolve()
    if len(ancestors) >= MAX_REFERENCE_DEPTH:
        raise LDrawImportError(f"LDraw reference depth exceeds {MAX_REFERENCE_DEPTH}: {path.name}")
    if resolved_path in ancestors:
        raise LDrawImportError(f"LDraw reference cycle detected at {path.name}")
    try:
        lines = resolved_path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError as error:
        raise LDrawImportError(f"Missing LDraw reference: {path}") from error

    invert_next = False
    next_ancestors = (*ancestors, resolved_path)
    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        if not fields:
            continue
        record_type = fields[0]
        if record_type == "0":
            invert_next = len(fields) >= 3 and fields[1:3] == ["BFC", "INVERTNEXT"]
            continue
        if record_type == "1":
            child_translation, child_matrix, reference = _parse_reference(fields, path, line_number)
            child_path = _resolve_reference(library_root, resolved_path.parent, reference)
            composed_translation = _add(translation, _apply(matrix, child_translation))
            composed_matrix = _multiply(matrix, child_matrix)
            child_flipped = flip_winding ^ (_determinant(child_matrix) < 0.0) ^ invert_next
            _read_file(
                library_root,
                child_path,
                composed_matrix,
                composed_translation,
                child_flipped,
                next_ancestors,
                triangles,
            )
            invert_next = False
            continue
        if record_type not in {"3", "4"}:
            continue
        points = _parse_surface(fields, path, line_number)
        world_points = tuple(_add(translation, _apply(matrix, point)) for point in points)
        if record_type == "3":
            _append_triangle(
                triangles, (world_points[0], world_points[1], world_points[2]), flip_winding
            )
        else:
            _append_triangle(
                triangles, (world_points[0], world_points[1], world_points[2]), flip_winding
            )
            _append_triangle(
                triangles, (world_points[0], world_points[2], world_points[3]), flip_winding
            )


def _parse_reference(
    fields: list[str], path: Path, line_number: int
) -> tuple[Point, Matrix, str]:
    if len(fields) < 15:
        raise LDrawImportError(f"Invalid type 1 record at {path.name}:{line_number}")
    values = _float_values(fields[2:14], path, line_number)
    return (
        (values[0], values[1], values[2]),
        (
            (values[3], values[4], values[5]),
            (values[6], values[7], values[8]),
            (values[9], values[10], values[11]),
        ),
        " ".join(fields[14:]),
    )


def _parse_surface(fields: list[str], path: Path, line_number: int) -> tuple[Point, ...]:
    point_count = 3 if fields[0] == "3" else 4
    if len(fields) != 2 + point_count * 3:
        raise LDrawImportError(f"Invalid type {fields[0]} record at {path.name}:{line_number}")
    values = _float_values(fields[2:], path, line_number)
    return tuple(
        (values[index], values[index + 1], values[index + 2])
        for index in range(0, len(values), 3)
    )


def _float_values(values: list[str], path: Path, line_number: int) -> list[float]:
    try:
        parsed = [float(value) for value in values]
    except ValueError as error:
        raise LDrawImportError(f"Invalid numeric value at {path.name}:{line_number}") from error
    if not all(isfinite(value) for value in parsed):
        raise LDrawImportError(f"Non-finite numeric value at {path.name}:{line_number}")
    return parsed


def _resolve_reference(library_root: Path, current_directory: Path, reference: str) -> Path:
    normalized = reference.replace("\\", "/")
    candidates = (
        current_directory / normalized,
        library_root / "parts" / normalized,
        library_root / "p" / normalized,
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(library_root) and resolved.is_file():
            return resolved
    raise LDrawImportError(f"Missing LDraw reference: {reference}")


def _append_triangle(
    triangles: list[tuple[Point, Point, Point]],
    points: tuple[Point, Point, Point],
    flip_winding: bool,
) -> None:
    triangles.append((points[0], points[2], points[1]) if flip_winding else points)


def _normalize_point(point: Point, long_axis: str) -> Point:
    """Map LDraw's x/right, y/down, z/depth coordinates into local stud/plate units."""
    if long_axis == "x":
        return (point[0] / LDU_PER_STUD, point[2] / LDU_PER_STUD, -point[1] / LDU_PER_PLATE)
    return (point[2] / LDU_PER_STUD, point[0] / LDU_PER_STUD, -point[1] / LDU_PER_PLATE)


def _rounded_point(point: Point) -> Point:
    return tuple(round(value, 6) for value in point)  # type: ignore[return-value]


def _apply(matrix: Matrix, point: Point) -> Point:
    return tuple(
        sum(matrix[row][column] * point[column] for column in range(3)) for row in range(3)
    )  # type: ignore[return-value]


def _add(first: Point, second: Point) -> Point:
    return (first[0] + second[0], first[1] + second[1], first[2] + second[2])


def _multiply(first: Matrix, second: Matrix) -> Matrix:
    return tuple(
        tuple(
            sum(first[row][index] * second[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _determinant(matrix: Matrix) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
