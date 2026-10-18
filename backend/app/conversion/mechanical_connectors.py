"""Verified vertical stud-system metadata, separate from production buildability.

The calibrated rectangular brick and plate family uses a trusted family rule.
Part 4286 is the sole reviewed, curated exception. LDraw connector evidence
remains source evidence and is never promoted automatically.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType

from app.conversion.connector_evidence import (
    CanonicalDirection,
    ConnectorEvidence,
    ConnectorFeatureKind,
)
from app.conversion.core import GridPosition
from app.conversion.part_catalogue import LegoPart
from app.conversion.part_coordinates import PartLocalFrame, Point3, rotate_part_local

VERTICAL_STUD_METADATA_VERSION = "vertical-stud-v1"
_VERTICAL_DIRECTIONS = frozenset({CanonicalDirection.POSITIVE_Z, CanonicalDirection.NEGATIVE_Z})
_RECTANGULAR_FAMILIES = frozenset({"brick", "plate"})


class MechanicalInterfaceKind(StrEnum):
    MALE_STUD = "male_stud"
    STUD_RECEIVER = "stud_receiver"


class MechanicalProvenance(StrEnum):
    SOURCE_BACKED = "source_backed"
    TRUSTED_FAMILY_RULE = "trusted_family_rule"
    CURATED_VERIFIED = "curated_verified"


class MechanicalEvaluationStatus(StrEnum):
    VERIFIED = "verified"
    UNEVALUATED = "unevaluated"


@dataclass(frozen=True, slots=True)
class MechanicalConnector:
    """One verified part-local vertical connector."""

    coordinate: Point3
    direction: CanonicalDirection
    interface_kind: MechanicalInterfaceKind
    provenance: MechanicalProvenance


@dataclass(frozen=True, slots=True)
class PartMechanicalMetadata:
    """The resolved vertical-stud contract for one part."""

    part_id: str
    version: str
    connectors: tuple[MechanicalConnector, ...]


@dataclass(frozen=True, slots=True)
class WorldMechanicalConnector:
    """A verified connector after applying an existing placement transform."""

    coordinate: Point3
    direction: CanonicalDirection
    interface_kind: MechanicalInterfaceKind
    provenance: MechanicalProvenance


class MechanicalConnectorValidationError(ValueError):
    """The narrow vertical-stud metadata contract is invalid."""


_CURATED_CONNECTORS_BY_PART_ID = MappingProxyType(
    {
        "4286": (
            MechanicalConnector(
                (2.5, 0.5, 3.0),
                CanonicalDirection.POSITIVE_Z,
                MechanicalInterfaceKind.MALE_STUD,
                MechanicalProvenance.SOURCE_BACKED,
            ),
            MechanicalConnector(
                (0.5, 0.5, 0.0),
                CanonicalDirection.NEGATIVE_Z,
                MechanicalInterfaceKind.STUD_RECEIVER,
                MechanicalProvenance.CURATED_VERIFIED,
            ),
            MechanicalConnector(
                (1.5, 0.5, 0.0),
                CanonicalDirection.NEGATIVE_Z,
                MechanicalInterfaceKind.STUD_RECEIVER,
                MechanicalProvenance.CURATED_VERIFIED,
            ),
            MechanicalConnector(
                (2.5, 0.5, 0.0),
                CanonicalDirection.NEGATIVE_Z,
                MechanicalInterfaceKind.STUD_RECEIVER,
                MechanicalProvenance.CURATED_VERIFIED,
            ),
        )
    }
)


def mechanical_evaluation_status(part: LegoPart) -> MechanicalEvaluationStatus:
    """Report whether this milestone has verified vertical connector metadata."""
    if part.part_id in _CURATED_CONNECTORS_BY_PART_ID:
        return MechanicalEvaluationStatus.VERIFIED
    if part.shape == "rectangular" and part.family in _RECTANGULAR_FAMILIES:
        return MechanicalEvaluationStatus.VERIFIED
    return MechanicalEvaluationStatus.UNEVALUATED


def resolve_part_mechanical_metadata(part: LegoPart) -> PartMechanicalMetadata | None:
    """Resolve trusted rectangular or explicitly curated connector metadata.

    The catalogue dimensions generate rectangular coordinates. Curated entries
    are explicit; this resolver never inspects LDraw evidence, so source
    geometry cannot accidentally become mechanically verified metadata.
    """
    curated_connectors = _CURATED_CONNECTORS_BY_PART_ID.get(part.part_id)
    if curated_connectors is not None:
        metadata = PartMechanicalMetadata(
            part.part_id,
            VERTICAL_STUD_METADATA_VERSION,
            curated_connectors,
        )
        validate_part_mechanical_metadata(metadata)
        return metadata

    if mechanical_evaluation_status(part) != MechanicalEvaluationStatus.VERIFIED:
        return None

    top = tuple(
        MechanicalConnector(
            (x + 0.5, y + 0.5, float(part.height_plates)),
            CanonicalDirection.POSITIVE_Z,
            MechanicalInterfaceKind.MALE_STUD,
            MechanicalProvenance.TRUSTED_FAMILY_RULE,
        )
        for x in range(part.length_studs)
        for y in range(part.width_studs)
    )
    underside = tuple(
        MechanicalConnector(
            (x + 0.5, y + 0.5, 0.0),
            CanonicalDirection.NEGATIVE_Z,
            MechanicalInterfaceKind.STUD_RECEIVER,
            MechanicalProvenance.TRUSTED_FAMILY_RULE,
        )
        for x in range(part.length_studs)
        for y in range(part.width_studs)
    )
    metadata = PartMechanicalMetadata(part.part_id, VERTICAL_STUD_METADATA_VERSION, top + underside)
    validate_part_mechanical_metadata(metadata)
    return metadata


def validate_source_backed_top_studs(
    metadata: PartMechanicalMetadata,
    evidence: Iterable[ConnectorEvidence],
) -> None:
    """Require exact agreement with any supplied authoritative top-stud evidence."""
    expected = {
        connector.coordinate
        for connector in metadata.connectors
        if connector.interface_kind == MechanicalInterfaceKind.MALE_STUD
    }
    observed = {
        item.canonical_coordinate
        for item in evidence
        if item.feature_kind == ConnectorFeatureKind.MALE_STUD
        and item.direction == CanonicalDirection.POSITIVE_Z
    }
    if observed and observed != expected:
        raise MechanicalConnectorValidationError(
            "Source-backed top-stud evidence disagrees with verified mechanical metadata."
        )


def mechanical_connector_report(
    part: LegoPart,
    metadata: PartMechanicalMetadata,
    evidence: Iterable[ConnectorEvidence],
) -> dict[str, object]:
    """Return a deterministic, JSON-ready calibration report for one part."""
    validate_source_backed_top_studs(metadata, evidence)
    connectors = tuple(
        sorted(
            metadata.connectors,
            key=lambda connector: (
                connector.coordinate,
                connector.interface_kind,
                connector.direction,
            ),
        )
    )
    return {
        "partId": part.part_id,
        "footprint": [part.length_studs, part.width_studs],
        "heightPlates": part.height_plates,
        "topMaleConnectorCount": sum(
            connector.interface_kind == MechanicalInterfaceKind.MALE_STUD
            for connector in connectors
        ),
        "undersideReceiverCount": sum(
            connector.interface_kind == MechanicalInterfaceKind.STUD_RECEIVER
            for connector in connectors
        ),
        "topProvenance": next(
            connector.provenance.value
            for connector in connectors
            if connector.interface_kind == MechanicalInterfaceKind.MALE_STUD
        ),
        "receiverProvenance": next(
            connector.provenance.value
            for connector in connectors
            if connector.interface_kind == MechanicalInterfaceKind.STUD_RECEIVER
        ),
        "sourceEvidenceAgreement": True,
        "connectors": [
            {
                "coordinate": list(connector.coordinate),
                "direction": connector.direction.value,
                "interfaceKind": connector.interface_kind.value,
                "provenance": connector.provenance.value,
            }
            for connector in connectors
        ],
        "metadataVersion": metadata.version,
    }


def transform_connector_to_world(
    connector: MechanicalConnector,
    part: LegoPart,
    position: GridPosition,
    orientation_degrees: int,
) -> WorldMechanicalConnector:
    """Apply the established part-local placement transform without rounding."""
    local = rotate_part_local(
        connector.coordinate,
        PartLocalFrame(
            part.length_studs,
            part.width_studs,
            part.height_plates,
        ),
        orientation_degrees,
    )
    x, y, z = local
    return WorldMechanicalConnector(
        (x + position.x, y + position.y, z + position.z),
        connector.direction,
        connector.interface_kind,
        connector.provenance,
    )


def matching_vertical_connectors(
    first: Iterable[WorldMechanicalConnector],
    second: Iterable[WorldMechanicalConnector],
) -> tuple[tuple[WorldMechanicalConnector, WorldMechanicalConnector], ...]:
    """Return exact, compatible vertical stud-system connector pairs."""
    matches = [(left, right) for left in first for right in second if _compatible(left, right)]
    return tuple(
        sorted(
            matches,
            key=lambda pair: (
                pair[0].coordinate,
                pair[0].interface_kind,
                pair[1].interface_kind,
            ),
        )
    )


def validate_part_mechanical_metadata(
    metadata: PartMechanicalMetadata,
    *,
    expected_version: str = VERTICAL_STUD_METADATA_VERSION,
) -> None:
    """Validate the compact vertical-stud metadata contract."""
    if metadata.version != expected_version:
        raise MechanicalConnectorValidationError("Mechanical connector metadata version mismatch.")
    seen: set[tuple[Point3, MechanicalInterfaceKind, CanonicalDirection]] = set()
    for connector in metadata.connectors:
        if not isinstance(connector.interface_kind, MechanicalInterfaceKind):
            raise MechanicalConnectorValidationError("Unsupported mechanical interface kind.")
        if connector.direction not in _VERTICAL_DIRECTIONS:
            raise MechanicalConnectorValidationError(
                "Mechanical connector direction must be +Z or -Z."
            )
        if (
            not isinstance(connector.coordinate, tuple)
            or len(connector.coordinate) != 3
            or not all(
                isinstance(value, int | float) and isfinite(value) for value in connector.coordinate
            )
        ):
            raise MechanicalConnectorValidationError(
                "Mechanical connector coordinate is malformed."
            )
        key = (connector.coordinate, connector.interface_kind, connector.direction)
        if key in seen:
            raise MechanicalConnectorValidationError("Duplicate mechanical connector.")
        seen.add(key)


def _compatible(left: WorldMechanicalConnector, right: WorldMechanicalConnector) -> bool:
    return (
        left.coordinate == right.coordinate
        and left.direction != right.direction
        and {left.interface_kind, right.interface_kind}
        == {MechanicalInterfaceKind.MALE_STUD, MechanicalInterfaceKind.STUD_RECEIVER}
    )
