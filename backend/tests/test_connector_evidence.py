from __future__ import annotations

from pathlib import Path
from typing import Any

from app.conversion.connector_evidence import (
    CanonicalDirection,
    ConnectorFeatureKind,
    CurrentMechanicsCompatibility,
    EvidenceStatus,
    classify_source_primitive,
    extract_connector_evidence,
)
from app.conversion.part_coordinates import PartLocalFrame

SOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / "part_geometry" / "ldraw_source"
BRICK_3001 = PartLocalFrame(4, 2, 3, "x")
WEDGE = PartLocalFrame(4, 2, 1, "z")
CURVED_SLOPE = PartLocalFrame(2, 2, 2, "x")

CALIBRATION_PARTS = (
    ("3001", "3001.dat", PartLocalFrame(4, 2, 3, "x"), "brick", 8, 3, 0),
    ("3002", "3002.dat", PartLocalFrame(3, 2, 3, "x"), "brick", 6, 2, 0),
    ("3003", "3003.dat", PartLocalFrame(2, 2, 3, "x"), "brick", 4, 1, 0),
    ("3010", "3010.dat", PartLocalFrame(4, 1, 3, "x"), "brick", 4, 0, 3),
    ("3020", "3020.dat", PartLocalFrame(4, 2, 1, "x"), "plate", 8, 3, 0),
    ("3021", "3021.dat", PartLocalFrame(3, 2, 1, "x"), "plate", 6, 2, 0),
    ("3022", "3022.dat", PartLocalFrame(2, 2, 1, "x"), "plate", 4, 1, 0),
    ("3023", "3023b.dat", PartLocalFrame(2, 1, 1, "x"), "plate", 2, 0, 1),
)


def write_ldraw_file(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def extract_fake(root: Path) -> tuple[Any, ...]:
    write_ldraw_file(root, "p/stud.dat", "0 Stud\n")
    return extract_connector_evidence(
        root,
        part_id="example",
        source_file="root.dat",
        frame=BRICK_3001,
        part_family="brick",
    )


def test_identity_parent_preserves_child_translation_and_male_stud_direction(
    tmp_path: Path,
) -> None:
    write_ldraw_file(tmp_path, "parts/root.dat", "1 16 7 4 11 1 0 0 0 1 0 0 0 1 stud.dat\n")

    evidence = extract_fake(tmp_path)[0]

    assert evidence.ldraw_coordinate == (7.0, 4.0, 11.0)
    assert evidence.direction == CanonicalDirection.POSITIVE_Z
    assert evidence.feature_kind == ConnectorFeatureKind.MALE_STUD


def test_x_reflection_transforms_child_translation_before_adding_parent_translation(
    tmp_path: Path,
) -> None:
    write_ldraw_file(
        tmp_path,
        "parts/root.dat",
        "1 16 10 0 0 -1 0 0 0 1 0 0 0 1 s/middle.dat\n",
    )
    write_ldraw_file(
        tmp_path,
        "parts/s/middle.dat",
        "1 16 3 4 11 1 0 0 0 1 0 0 0 1 stud.dat\n",
    )

    evidence = extract_fake(tmp_path)[0]

    assert evidence.ldraw_coordinate == (7.0, 4.0, 11.0)
    assert evidence.direction == CanonicalDirection.POSITIVE_Z


def test_rotation_parent_transforms_child_translation_and_direction(tmp_path: Path) -> None:
    write_ldraw_file(
        tmp_path,
        "parts/root.dat",
        "1 16 0 0 0 0 -1 0 1 0 0 0 0 1 stud.dat\n",
    )

    evidence = extract_fake(tmp_path)[0]

    assert evidence.ldraw_coordinate == (0.0, 0.0, 0.0)
    assert evidence.direction == CanonicalDirection.POSITIVE_X
    assert evidence.current_mechanics_compatibility == CurrentMechanicsCompatibility.INCOMPATIBLE


def test_nested_reflection_rotation_and_translation_are_composed_in_order(tmp_path: Path) -> None:
    write_ldraw_file(
        tmp_path,
        "parts/root.dat",
        "1 16 10 0 0 -1 0 0 0 1 0 0 0 1 s/middle.dat\n",
    )
    write_ldraw_file(
        tmp_path,
        "parts/s/middle.dat",
        "1 16 2 3 0 0 -1 0 1 0 0 0 0 1 s/leaf.dat\n",
    )
    write_ldraw_file(
        tmp_path,
        "parts/s/leaf.dat",
        "1 16 4 5 6 1 0 0 0 1 0 0 0 1 stud.dat\n",
    )

    evidence = extract_fake(tmp_path)[0]

    assert evidence.ldraw_coordinate == (13.0, 7.0, 6.0)
    assert evidence.canonical_coordinate == (2.65, 1.3, 2.125)
    assert evidence.direction == CanonicalDirection.NEGATIVE_X


def test_primitive_semantics_remain_distinct_and_partial_geometry_is_not_promoted() -> None:
    assert classify_source_primitive("p/stud.dat") == (
        ConnectorFeatureKind.MALE_STUD,
        EvidenceStatus.SOURCE_BACKED,
    )
    assert classify_source_primitive("p/stud4.dat") == (
        ConnectorFeatureKind.UNDERSIDE_RING_TUBE,
        EvidenceStatus.SOURCE_BACKED,
    )
    assert (
        classify_source_primitive("p/stud3.dat")[0]
        == ConnectorFeatureKind.UNDERSIDE_SMALL_STUD_TUBE
    )
    assert (
        classify_source_primitive("p/stud3a.dat")[0]
        == ConnectorFeatureKind.UNDERSIDE_SMALL_STUD_TUBE
    )
    assert (
        classify_source_primitive("p/1-4stud4.dat")[0]
        == ConnectorFeatureKind.PARTIAL_STUD_TUBE_GEOMETRY
    )
    assert classify_source_primitive("p/unrecognized-stud.dat") == (None, EvidenceStatus.UNRESOLVED)


def test_3001_extracts_eight_upward_male_studs_and_three_underside_rings() -> None:
    evidence = extract_connector_evidence(
        SOURCE_DIRECTORY,
        part_id="3001",
        source_file="3001.dat",
        frame=BRICK_3001,
        part_family="brick",
    )

    male_studs = [item for item in evidence if item.feature_kind == ConnectorFeatureKind.MALE_STUD]
    rings = [
        item for item in evidence if item.feature_kind == ConnectorFeatureKind.UNDERSIDE_RING_TUBE
    ]
    assert len(male_studs) == 8
    assert {item.canonical_coordinate for item in male_studs} == {
        (x, y, 3.0) for x in (0.5, 1.5, 2.5, 3.5) for y in (0.5, 1.5)
    }
    assert all(item.direction == CanonicalDirection.POSITIVE_Z for item in male_studs)
    assert all(
        item.current_mechanics_compatibility == CurrentMechanicsCompatibility.COMPATIBLE
        for item in male_studs
    )
    assert [item.canonical_coordinate for item in rings] == [
        (1.0, 1.0, 2.5),
        (2.0, 1.0, 2.5),
        (3.0, 1.0, 2.5),
    ]
    assert all(item.direction == CanonicalDirection.NEGATIVE_Z for item in rings)
    assert all(
        item.current_mechanics_compatibility == CurrentMechanicsCompatibility.UNEVALUATED
        for item in rings
    )


def test_calibration_parts_have_deterministic_source_backed_connector_evidence() -> None:
    for (
        part_id,
        source_file,
        frame,
        family,
        expected_male_studs,
        expected_rings,
        expected_small_tubes,
    ) in CALIBRATION_PARTS:
        first = extract_connector_evidence(
            SOURCE_DIRECTORY,
            part_id=part_id,
            source_file=source_file,
            frame=frame,
            part_family=family,
        )
        second = extract_connector_evidence(
            SOURCE_DIRECTORY,
            part_id=part_id,
            source_file=source_file,
            frame=frame,
            part_family=family,
        )

        male_studs = [item for item in first if item.feature_kind == ConnectorFeatureKind.MALE_STUD]
        rings = [
            item for item in first if item.feature_kind == ConnectorFeatureKind.UNDERSIDE_RING_TUBE
        ]
        small_tubes = [
            item
            for item in first
            if item.feature_kind == ConnectorFeatureKind.UNDERSIDE_SMALL_STUD_TUBE
        ]

        assert first == second
        assert len(male_studs) == expected_male_studs
        assert len(rings) == expected_rings
        assert len(small_tubes) == expected_small_tubes
        assert all(item.direction == CanonicalDirection.POSITIVE_Z for item in male_studs)
        assert all(
            item.direction == CanonicalDirection.NEGATIVE_Z for item in (*rings, *small_tubes)
        )
        assert all(item.on_standard_rectangular_stud_grid for item in male_studs)
        assert all(
            item.current_mechanics_compatibility == CurrentMechanicsCompatibility.COMPATIBLE
            for item in male_studs
        )

def test_wedge_reflection_keeps_stud4_at_the_same_vertical_level() -> None:
    left = extract_connector_evidence(
        SOURCE_DIRECTORY,
        part_id="41770",
        source_file="41770a.dat",
        frame=WEDGE,
        part_family="wedge_plate",
    )
    right = extract_connector_evidence(
        SOURCE_DIRECTORY,
        part_id="41769",
        source_file="41769a.dat",
        frame=WEDGE,
        part_family="wedge_plate",
    )
    left_ring = next(
        item for item in left if item.feature_kind == ConnectorFeatureKind.UNDERSIDE_RING_TUBE
    )
    right_ring = next(
        item for item in right if item.feature_kind == ConnectorFeatureKind.UNDERSIDE_RING_TUBE
    )

    assert left_ring.ldraw_coordinate == right_ring.ldraw_coordinate == (0.0, 4.0, 20.0)
    assert left_ring.canonical_coordinate == right_ring.canonical_coordinate == (3.0, 1.0, 0.5)
    assert left_ring.direction == right_ring.direction == CanonicalDirection.NEGATIVE_Z
    assert len([item for item in left if item.feature_kind == ConnectorFeatureKind.MALE_STUD]) == 4
    assert len([item for item in right if item.feature_kind == ConnectorFeatureKind.MALE_STUD]) == 4
    assert any(
        item.feature_kind == ConnectorFeatureKind.PARTIAL_STUD_TUBE_GEOMETRY for item in left
    )


def test_15068_small_underside_stud_tubes_are_not_top_studs() -> None:
    evidence = extract_connector_evidence(
        SOURCE_DIRECTORY,
        part_id="15068",
        source_file="15068.dat",
        frame=CURVED_SLOPE,
        part_family="curved_slope",
    )

    assert [(item.source_file, item.canonical_coordinate) for item in evidence] == [
        ("p/stud3a.dat", (1.0, 0.5, 2.5)),
        ("p/stud3.dat", (1.0, 1.5, 3.5)),
    ]
    assert all(
        item.feature_kind == ConnectorFeatureKind.UNDERSIDE_SMALL_STUD_TUBE for item in evidence
    )
    assert all(item.direction == CanonicalDirection.NEGATIVE_Z for item in evidence)
    assert all(
        item.current_mechanics_compatibility == CurrentMechanicsCompatibility.UNEVALUATED
        for item in evidence
    )


def test_output_is_deterministic() -> None:
    first = extract_connector_evidence(
        SOURCE_DIRECTORY,
        part_id="41770",
        source_file="41770a.dat",
        frame=WEDGE,
        part_family="wedge_plate",
    )
    second = extract_connector_evidence(
        SOURCE_DIRECTORY,
        part_id="41770",
        source_file="41770a.dat",
        frame=WEDGE,
        part_family="wedge_plate",
    )

    assert first == second
