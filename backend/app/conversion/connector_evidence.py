"""Source-backed connector-feature diagnostics for LDraw part hierarchies.

The extractor reports source geometry, not certified mechanical connections.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from pathlib import Path

from app.conversion.part_coordinates import PartLocalFrame, Point3, is_standard_stud_grid_position

MAX_REFERENCE_DEPTH = 64
Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
IDENTITY: Matrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
ORIGIN: Point3 = (0.0, 0.0, 0.0)
PRIMITIVE_UP_AXIS: Point3 = (0.0, -1.0, 0.0)


class EvidenceStatus(StrEnum):
    SOURCE_BACKED = "source_backed"
    DERIVED = "derived"
    UNRESOLVED = "unresolved"


class ConnectorFeatureKind(StrEnum):
    MALE_STUD = "male_stud"
    UNDERSIDE_RING_TUBE = "underside_ring_tube"
    UNDERSIDE_SMALL_STUD_TUBE = "underside_small_stud_tube"
    PARTIAL_STUD_TUBE_GEOMETRY = "partial_stud_tube_geometry"


class CanonicalDirection(StrEnum):
    POSITIVE_X = "+X"
    NEGATIVE_X = "-X"
    POSITIVE_Y = "+Y"
    NEGATIVE_Y = "-Y"
    POSITIVE_Z = "+Z"
    NEGATIVE_Z = "-Z"


class CurrentMechanicsCompatibility(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNEVALUATED = "unevaluated"


@dataclass(frozen=True, slots=True)
class ConnectorEvidence:
    """One source primitive instance, including its fully transformed direction."""

    part_id: str
    source_file: str
    source_path: tuple[str, ...]
    ldraw_coordinate: Point3
    canonical_coordinate: Point3
    direction: CanonicalDirection
    feature_kind: ConnectorFeatureKind
    status: EvidenceStatus
    on_standard_rectangular_stud_grid: bool
    current_mechanics_compatibility: CurrentMechanicsCompatibility


class ConnectorEvidenceError(ValueError):
    """The LDraw hierarchy cannot safely be inspected for connector evidence."""


_PRIMITIVE_KINDS = {
    "stud.dat": ConnectorFeatureKind.MALE_STUD,
    "stud3.dat": ConnectorFeatureKind.UNDERSIDE_SMALL_STUD_TUBE,
    "stud3a.dat": ConnectorFeatureKind.UNDERSIDE_SMALL_STUD_TUBE,
    "stud4.dat": ConnectorFeatureKind.UNDERSIDE_RING_TUBE,
    "1-4stud4.dat": ConnectorFeatureKind.PARTIAL_STUD_TUBE_GEOMETRY,
    "1-8stud4.dat": ConnectorFeatureKind.PARTIAL_STUD_TUBE_GEOMETRY,
    "2-4stud4.dat": ConnectorFeatureKind.PARTIAL_STUD_TUBE_GEOMETRY,
    "3-16stud4.dat": ConnectorFeatureKind.PARTIAL_STUD_TUBE_GEOMETRY,
}


def classify_source_primitive(
    source_file: str,
) -> tuple[ConnectorFeatureKind | None, EvidenceStatus]:
    """Classify only explicitly known primitives; similar names stay unresolved."""
    feature_kind = _PRIMITIVE_KINDS.get(Path(source_file).name.lower())
    if feature_kind is None:
        return (None, EvidenceStatus.UNRESOLVED)
    return (feature_kind, EvidenceStatus.SOURCE_BACKED)


def extract_connector_evidence(
    library_root: Path,
    *,
    part_id: str,
    source_file: str,
    frame: PartLocalFrame,
    part_family: str,
) -> tuple[ConnectorEvidence, ...]:
    """Extract recognized connector geometry through the complete reference tree."""
    root = library_root.resolve()
    root_path = _resolve_reference(root, root / "parts" / source_file, source_file)
    evidence: list[ConnectorEvidence] = []

    def visit(
        path: Path,
        matrix: Matrix,
        translation: Point3,
        source_path: tuple[str, ...],
        ancestors: tuple[Path, ...],
    ) -> None:
        resolved_path = path.resolve()
        if len(ancestors) >= MAX_REFERENCE_DEPTH:
            raise ConnectorEvidenceError(
                f"LDraw reference depth exceeds {MAX_REFERENCE_DEPTH}: {path.name}"
            )
        if resolved_path in ancestors:
            raise ConnectorEvidenceError(f"LDraw reference cycle detected at {path.name}")
        try:
            lines = resolved_path.read_text(encoding="utf-8-sig").splitlines()
        except FileNotFoundError as error:
            raise ConnectorEvidenceError(f"Missing LDraw reference: {path}") from error

        for line_number, line in enumerate(lines, start=1):
            fields = line.split()
            if not fields or fields[0] != "1":
                continue
            child_translation, child_matrix, reference = _parse_reference(
                fields, resolved_path, line_number
            )
            child_path = _resolve_reference(root, resolved_path.parent, reference)
            composed_translation = _add(translation, _apply(matrix, child_translation))
            composed_matrix = _multiply(matrix, child_matrix)
            child_source = _relative_source(root, child_path)
            child_hierarchy = (*source_path, child_source)
            feature_kind, status = classify_source_primitive(child_source)
            if feature_kind is not None:
                canonical_coordinate = _ldraw_point_to_canonical(composed_translation, frame)
                direction = _ldraw_direction_to_canonical(
                    _apply(composed_matrix, PRIMITIVE_UP_AXIS), frame
                )
                on_grid = is_standard_stud_grid_position(canonical_coordinate)
                evidence.append(
                    ConnectorEvidence(
                        part_id=part_id,
                        source_file=child_source,
                        source_path=child_hierarchy,
                        ldraw_coordinate=composed_translation,
                        canonical_coordinate=canonical_coordinate,
                        direction=direction,
                        feature_kind=feature_kind,
                        status=status,
                        on_standard_rectangular_stud_grid=on_grid,
                        current_mechanics_compatibility=_mechanics_compatibility(
                            part_family, feature_kind, direction, on_grid
                        ),
                    )
                )
                continue
            visit(
                child_path,
                composed_matrix,
                composed_translation,
                child_hierarchy,
                (*ancestors, resolved_path),
            )

    visit(root_path, IDENTITY, ORIGIN, (_relative_source(root, root_path),), ())
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.canonical_coordinate,
                item.direction,
                item.source_file,
                item.source_path,
            ),
        )
    )


def _mechanics_compatibility(
    part_family: str,
    feature_kind: ConnectorFeatureKind,
    direction: CanonicalDirection,
    on_standard_rectangular_stud_grid: bool,
) -> CurrentMechanicsCompatibility:
    if feature_kind != ConnectorFeatureKind.MALE_STUD:
        return CurrentMechanicsCompatibility.UNEVALUATED
    if direction != CanonicalDirection.POSITIVE_Z or not on_standard_rectangular_stud_grid:
        return CurrentMechanicsCompatibility.INCOMPATIBLE
    if part_family in {"brick", "plate"}:
        return CurrentMechanicsCompatibility.COMPATIBLE
    return CurrentMechanicsCompatibility.UNEVALUATED


def _ldraw_point_to_canonical(point: Point3, frame: PartLocalFrame) -> Point3:
    ldraw_x, ldraw_y, ldraw_z = point
    if frame.ldraw_long_axis == "x":
        return (
            ldraw_x / 20.0 + frame.length_studs / 2,
            ldraw_z / 20.0 + frame.width_studs / 2,
            frame.height_plates - ldraw_y / 8.0,
        )
    return (
        ldraw_z / 20.0 + frame.length_studs / 2,
        ldraw_x / 20.0 + frame.width_studs / 2,
        frame.height_plates - ldraw_y / 8.0,
    )


def _ldraw_direction_to_canonical(vector: Point3, frame: PartLocalFrame) -> CanonicalDirection:
    ldraw_x, ldraw_y, ldraw_z = vector
    canonical = (
        ldraw_x if frame.ldraw_long_axis == "x" else ldraw_z,
        ldraw_z if frame.ldraw_long_axis == "x" else ldraw_x,
        -ldraw_y,
    )
    non_zero_axes = [index for index, value in enumerate(canonical) if value != 0.0]
    if len(non_zero_axes) != 1:
        raise ConnectorEvidenceError("Connector primitive direction is not axis-aligned.")
    axis = non_zero_axes[0]
    positive = canonical[axis] > 0.0
    return (
        (CanonicalDirection.POSITIVE_X if positive else CanonicalDirection.NEGATIVE_X)
        if axis == 0
        else (CanonicalDirection.POSITIVE_Y if positive else CanonicalDirection.NEGATIVE_Y)
        if axis == 1
        else (CanonicalDirection.POSITIVE_Z if positive else CanonicalDirection.NEGATIVE_Z)
    )


def _parse_reference(fields: list[str], path: Path, line_number: int) -> tuple[Point3, Matrix, str]:
    if len(fields) < 15:
        raise ConnectorEvidenceError(f"Invalid type 1 record at {path.name}:{line_number}")
    try:
        values = [float(value) for value in fields[2:14]]
    except ValueError as error:
        raise ConnectorEvidenceError(
            f"Invalid numeric value at {path.name}:{line_number}"
        ) from error
    if not all(isfinite(value) for value in values):
        raise ConnectorEvidenceError(f"Non-finite numeric value at {path.name}:{line_number}")
    return (
        (values[0], values[1], values[2]),
        (
            (values[3], values[4], values[5]),
            (values[6], values[7], values[8]),
            (values[9], values[10], values[11]),
        ),
        " ".join(fields[14:]),
    )


def _resolve_reference(library_root: Path, current_directory: Path, reference: str) -> Path:
    normalized = reference.replace("\\", "/")
    for candidate in (
        current_directory / normalized,
        library_root / "parts" / normalized,
        library_root / "p" / normalized,
    ):
        resolved = candidate.resolve()
        if resolved.is_relative_to(library_root) and resolved.is_file():
            return resolved
    raise ConnectorEvidenceError(f"Missing LDraw reference: {reference}")


def _relative_source(library_root: Path, path: Path) -> str:
    return path.relative_to(library_root).as_posix()


def _apply(matrix: Matrix, point: Point3) -> Point3:
    return tuple(
        sum(matrix[row][column] * point[column] for column in range(3)) for row in range(3)
    )  # type: ignore[return-value]


def _add(first: Point3, second: Point3) -> Point3:
    return (first[0] + second[0], first[1] + second[1], first[2] + second[2])


def _multiply(first: Matrix, second: Matrix) -> Matrix:
    return tuple(
        tuple(
            sum(first[row][index] * second[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]
