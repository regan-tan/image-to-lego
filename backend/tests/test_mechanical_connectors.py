from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.conversion.buildability import directly_supports
from app.conversion.connector_evidence import (
    CanonicalDirection,
    ConnectorEvidence,
    ConnectorFeatureKind,
    CurrentMechanicsCompatibility,
    EvidenceStatus,
    extract_connector_evidence,
)
from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.mechanical_connectors import (
    VERTICAL_STUD_METADATA_VERSION,
    MechanicalConnector,
    MechanicalConnectorValidationError,
    MechanicalEvaluationStatus,
    MechanicalInterfaceKind,
    MechanicalProvenance,
    PartMechanicalMetadata,
    WorldMechanicalConnector,
    matching_vertical_connectors,
    mechanical_connector_report,
    mechanical_evaluation_status,
    resolve_part_mechanical_metadata,
    transform_connector_to_world,
    validate_part_mechanical_metadata,
    validate_source_backed_top_studs,
)
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.part_coordinates import PartLocalFrame

SOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / "part_geometry" / "ldraw_source"
CALIBRATION_IDS = ("3001", "3002", "3003", "3010", "3020", "3021", "3022", "3023")


def _world_connectors(placement: BrickPlacement) -> tuple[WorldMechanicalConnector, ...]:
    metadata = resolve_part_mechanical_metadata(placement.brick_type)
    assert metadata is not None
    return tuple(
        transform_connector_to_world(
            connector,
            placement.brick_type,
            placement.position,
            placement.orientation_degrees,
        )
        for connector in metadata.connectors
    )


def _matches(lower: BrickPlacement, upper: BrickPlacement) -> int:
    return len(matching_vertical_connectors(_world_connectors(lower), _world_connectors(upper)))


@pytest.mark.parametrize(
    ("part_id", "expected_count"),
    (
        ("3001", 8),
        ("3002", 6),
        ("3003", 4),
        ("3010", 4),
        ("3020", 8),
        ("3021", 6),
        ("3022", 4),
        ("3023", 2),
    ),
)
def test_calibration_parts_resolve_trusted_rectangular_connector_sets(
    part_id: str, expected_count: int
) -> None:
    metadata = resolve_part_mechanical_metadata(PART_BY_ID[part_id])

    assert metadata is not None
    assert metadata.version == VERTICAL_STUD_METADATA_VERSION
    assert len(metadata.connectors) == expected_count * 2
    assert (
        sum(c.interface_kind == MechanicalInterfaceKind.MALE_STUD for c in metadata.connectors)
        == expected_count
    )
    assert (
        sum(c.interface_kind == MechanicalInterfaceKind.STUD_RECEIVER for c in metadata.connectors)
        == expected_count
    )
    assert {c.provenance for c in metadata.connectors} == {MechanicalProvenance.TRUSTED_FAMILY_RULE}


def test_calibration_top_studs_exactly_agree_with_authoritative_source_evidence() -> None:
    for part_id in CALIBRATION_IDS:
        part = PART_BY_ID[part_id]
        metadata = resolve_part_mechanical_metadata(part)
        assert metadata is not None
        evidence = extract_connector_evidence(
            SOURCE_DIRECTORY,
            part_id=part.part_id,
            source_file=f"{part.ldraw_id}.dat",
            frame=PartLocalFrame(part.length_studs, part.width_studs, part.height_plates, "x"),
            part_family=part.family,
        )
        validate_source_backed_top_studs(metadata, evidence)
        report = mechanical_connector_report(part, metadata, evidence)
        assert report["sourceEvidenceAgreement"] is True


def test_source_evidence_disagreement_fails_validation() -> None:
    metadata = resolve_part_mechanical_metadata(PART_BY_ID["3001"])
    assert metadata is not None
    disagreeing = ConnectorEvidence(
        "3001",
        "p/stud.dat",
        ("parts/3001.dat", "p/stud.dat"),
        (0.0, 0.0, 0.0),
        (0.25, 0.5, 3.0),
        CanonicalDirection.POSITIVE_Z,
        ConnectorFeatureKind.MALE_STUD,
        EvidenceStatus.SOURCE_BACKED,
        False,
        CurrentMechanicsCompatibility.INCOMPATIBLE,
    )

    with pytest.raises(MechanicalConnectorValidationError, match="disagrees"):
        validate_source_backed_top_studs(metadata, (disagreeing,))


@pytest.mark.parametrize("orientation", (0, 90, 180, 270))
def test_world_transform_uses_existing_non_square_orientation_convention(orientation: int) -> None:
    part = PART_BY_ID["3010"]
    metadata = resolve_part_mechanical_metadata(part)
    assert metadata is not None
    stud = metadata.connectors[0]

    world = transform_connector_to_world(stud, part, GridPosition(10, 20, 30), orientation)

    expected_local = {0: (0.5, 0.5), 90: (0.5, 3.5), 180: (3.5, 0.5), 270: (0.5, 0.5)}[orientation]
    assert world.coordinate[:2] == (10 + expected_local[0], 20 + expected_local[1])
    assert world.coordinate[2] == 33.0
    assert world.direction == CanonicalDirection.POSITIVE_Z


def test_matcher_requires_exact_coordinate_opposite_direction_and_complementary_kinds() -> None:
    male = WorldMechanicalConnector(
        (1.5, 0.5, 3.0),
        CanonicalDirection.POSITIVE_Z,
        MechanicalInterfaceKind.MALE_STUD,
        MechanicalProvenance.TRUSTED_FAMILY_RULE,
    )
    receiver = WorldMechanicalConnector(
        (1.5, 0.5, 3.0),
        CanonicalDirection.NEGATIVE_Z,
        MechanicalInterfaceKind.STUD_RECEIVER,
        MechanicalProvenance.TRUSTED_FAMILY_RULE,
    )
    wrong_plane = WorldMechanicalConnector(
        (1.5, 0.5, 2.0),
        CanonicalDirection.NEGATIVE_Z,
        MechanicalInterfaceKind.STUD_RECEIVER,
        MechanicalProvenance.TRUSTED_FAMILY_RULE,
    )
    wrong_kind = WorldMechanicalConnector(
        (1.5, 0.5, 3.0),
        CanonicalDirection.NEGATIVE_Z,
        MechanicalInterfaceKind.MALE_STUD,
        MechanicalProvenance.TRUSTED_FAMILY_RULE,
    )

    assert len(matching_vertical_connectors((male,), (receiver,))) == 1
    assert matching_vertical_connectors((male,), (wrong_plane, wrong_kind)) == ()
    receiver_to_receiver = WorldMechanicalConnector(
        receiver.coordinate,
        CanonicalDirection.NEGATIVE_Z,
        MechanicalInterfaceKind.STUD_RECEIVER,
        MechanicalProvenance.TRUSTED_FAMILY_RULE,
    )
    assert matching_vertical_connectors((receiver,), (receiver_to_receiver,)) == ()


@pytest.mark.parametrize(
    "lower,upper",
    (
        (
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0),
            BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 3), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3020"], GridPosition(0, 0, 0), 0),
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 1), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0),
            BrickPlacement(PART_BY_ID["3004"], GridPosition(3, 0, 3), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0),
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 3), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0),
            BrickPlacement(PART_BY_ID["3004"], GridPosition(4, 0, 3), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3001"], GridPosition(0, 0, 0), 0),
            BrickPlacement(PART_BY_ID["3004"], GridPosition(0, 0, 2), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3010"], GridPosition(0, 0, 0), 90),
            BrickPlacement(PART_BY_ID["3004"], GridPosition(0, 2, 3), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3010"], GridPosition(0, 0, 0), 180),
            BrickPlacement(PART_BY_ID["3004"], GridPosition(2, 0, 3), 0),
        ),
        (
            BrickPlacement(PART_BY_ID["3010"], GridPosition(0, 0, 0), 270),
            BrickPlacement(PART_BY_ID["3004"], GridPosition(0, 0, 3), 0),
        ),
    ),
)
def test_generic_matcher_exactly_matches_stud_connectivity_v1_for_rectangular_cases(
    lower: BrickPlacement, upper: BrickPlacement
) -> None:
    assert bool(_matches(lower, upper)) == directly_supports(lower, upper)


def test_metadata_validation_and_serialization_are_deterministic() -> None:
    metadata = resolve_part_mechanical_metadata(PART_BY_ID["3001"])
    assert metadata is not None
    validate_part_mechanical_metadata(metadata)
    assert json.dumps(
        mechanical_connector_report(PART_BY_ID["3001"], metadata, ()), sort_keys=True
    ) == json.dumps(mechanical_connector_report(PART_BY_ID["3001"], metadata, ()), sort_keys=True)
    duplicate = PartMechanicalMetadata(
        "3001", VERTICAL_STUD_METADATA_VERSION, (metadata.connectors[0], metadata.connectors[0])
    )
    with pytest.raises(MechanicalConnectorValidationError, match="Duplicate"):
        validate_part_mechanical_metadata(duplicate)
    invalid_direction = MechanicalConnector(
        (0.5, 0.5, 3.0),
        CanonicalDirection.POSITIVE_X,
        MechanicalInterfaceKind.MALE_STUD,
        MechanicalProvenance.CURATED_VERIFIED,
    )
    with pytest.raises(MechanicalConnectorValidationError, match="direction"):
        validate_part_mechanical_metadata(
            PartMechanicalMetadata("x", VERTICAL_STUD_METADATA_VERSION, (invalid_direction,))
        )
    unsupported = MechanicalConnector(
        (0.5, 0.5, 3.0),
        CanonicalDirection.POSITIVE_Z,
        cast(MechanicalInterfaceKind, "pin"),
        MechanicalProvenance.CURATED_VERIFIED,
    )
    with pytest.raises(MechanicalConnectorValidationError, match="Unsupported"):
        validate_part_mechanical_metadata(
            PartMechanicalMetadata("x", VERTICAL_STUD_METADATA_VERSION, (unsupported,))
        )
    malformed = MechanicalConnector(
        cast(Any, (float("nan"), 0.5, 3.0)),
        CanonicalDirection.POSITIVE_Z,
        MechanicalInterfaceKind.MALE_STUD,
        MechanicalProvenance.CURATED_VERIFIED,
    )
    with pytest.raises(MechanicalConnectorValidationError, match="malformed"):
        validate_part_mechanical_metadata(
            PartMechanicalMetadata("x", VERTICAL_STUD_METADATA_VERSION, (malformed,))
        )
    with pytest.raises(MechanicalConnectorValidationError, match="version"):
        validate_part_mechanical_metadata(
            PartMechanicalMetadata("x", "vertical-stud-v0", (metadata.connectors[0],))
        )


@pytest.mark.parametrize("part_id", ("41769", "41770", "15068"))
def test_non_trivial_parts_remain_unevaluated_despite_source_evidence(part_id: str) -> None:
    part = PART_BY_ID[part_id]

    assert mechanical_evaluation_status(part) == MechanicalEvaluationStatus.UNEVALUATED
    assert resolve_part_mechanical_metadata(part) is None
