from __future__ import annotations

import pytest

from app.conversion.part_coordinates import (
    LDrawSourceFrame,
    PartLocalFrame,
    is_standard_stud_grid_position,
    ldraw_source_frame,
    ldraw_to_part_local,
    part_local_to_ldraw,
    rotate_part_local,
    standard_stud_grid_coordinate,
)

BRICK_3001_SOURCE = ldraw_source_frame("3001")
WEDGE_SOURCE = ldraw_source_frame("41770")
BRICK_3001_PLACEMENT = PartLocalFrame(4, 2, 3)
WEDGE_PLACEMENT = PartLocalFrame(4, 2, 1)


def test_3001_calibration_maps_its_20_ldu_stud_pitch_and_8_ldu_plate_height() -> None:
    assert ldraw_to_part_local((-30.0, 0.0, -10.0), BRICK_3001_SOURCE) == (0.5, 0.5, 3.0)
    assert ldraw_to_part_local((30.0, 0.0, 10.0), BRICK_3001_SOURCE) == (3.5, 1.5, 3.0)
    assert ldraw_to_part_local((-40.0, 24.0, -20.0), BRICK_3001_SOURCE) == (0.0, 0.0, 0.0)


def test_transform_round_trips_without_implicit_rounding() -> None:
    source = (7.25, -3.5, 11.75)
    local = ldraw_to_part_local(source, BRICK_3001_SOURCE)
    assert part_local_to_ldraw(local, BRICK_3001_SOURCE) == pytest.approx(source)


def test_off_center_source_frame_uses_its_explicit_anchor_without_snapping() -> None:
    source_frame = LDrawSourceFrame("example", "example", "z", (2.5, 0.5, 3.0))

    assert ldraw_to_part_local((0.0, 0.0, 0.0), source_frame) == (2.5, 0.5, 3.0)
    assert ldraw_to_part_local((0.0, 20.0, -30.0), source_frame) == (1.0, 0.5, 0.5)
    assert part_local_to_ldraw((1.125, 0.5, 0.75), source_frame) == (-0.0, 18.0, -27.5)


@pytest.mark.parametrize(
    "part_id",
    (
        "3001",
        "3002",
        "3003",
        "3010",
        "3020",
        "3021",
        "3022",
        "3023",
        "4286",
        "15068",
        "41769",
        "41770",
    ),
)
def test_each_checked_in_source_frame_round_trips_continuous_coordinates(part_id: str) -> None:
    source = (7.25, -3.5, 11.75)
    source_frame = ldraw_source_frame(part_id)

    assert part_local_to_ldraw(
        ldraw_to_part_local(source, source_frame), source_frame
    ) == pytest.approx(source)


def test_source_frame_lookup_is_deterministic_and_keeps_4286_off_center() -> None:
    assert ldraw_source_frame("4286") is ldraw_source_frame("4286")
    assert ldraw_source_frame("4286").ldraw_origin_in_part_local == (2.5, 0.5, 3.0)
    with pytest.raises(ValueError, match="No verified"):
        ldraw_source_frame("unknown")


@pytest.mark.parametrize(
    ("orientation", "expected"),
    [
        (0, (0.5, 0.5, 1.0)),
        (90, (0.5, 3.5, 1.0)),
        (180, (3.5, 1.5, 1.0)),
        (270, (1.5, 0.5, 1.0)),
    ],
)
def test_all_placement_rotations_match_the_established_footprint_convention(
    orientation: int, expected: tuple[float, float, float]
) -> None:
    assert rotate_part_local((0.5, 0.5, 1.0), WEDGE_PLACEMENT, orientation) == expected


def test_standard_stud_grid_is_specific_to_rectangular_brick_plate_mechanics() -> None:
    assert standard_stud_grid_coordinate((0.5000001, 1.5, 3.0)) is not None
    assert is_standard_stud_grid_position((0.5, 1.5, 3.0))
    assert not is_standard_stud_grid_position((1.0, 1.5, 3.0))
    assert not is_standard_stud_grid_position((0.5, 1.5, 3.125))


def test_wedge_visual_stud_groups_map_without_reflection() -> None:
    # 41770 has its four visual studs at LDraw x=-10 and z=-30..30.
    assert tuple(
        ldraw_to_part_local((-10.0, 0.0, z), WEDGE_SOURCE) for z in (-30.0, -10.0, 10.0, 30.0)
    ) == ((0.5, 0.5, 1.0), (1.5, 0.5, 1.0), (2.5, 0.5, 1.0), (3.5, 0.5, 1.0))
    # 41769 is the authoritative x reflection and lands in the other row.
    assert tuple(
        ldraw_to_part_local((10.0, 0.0, z), ldraw_source_frame("41769"))
        for z in (-30.0, -10.0, 10.0, 30.0)
    ) == ((0.5, 1.5, 1.0), (1.5, 1.5, 1.0), (2.5, 1.5, 1.0), (3.5, 1.5, 1.0))


def test_source_backed_stud_coordinates_remain_valid_outside_standard_grid() -> None:
    # 41770a directly includes the shared subpart. Its stud4 reference has this
    # source origin; 41769a mirrors the subpart in LDraw x and y.
    assert ldraw_to_part_local((0.0, 4.0, 20.0), WEDGE_SOURCE) == (3.0, 1.0, 0.5)
    assert ldraw_to_part_local((0.0, -4.0, 20.0), WEDGE_SOURCE) == (3.0, 1.0, 1.5)
    assert not is_standard_stud_grid_position((3.0, 1.0, 0.5))
    assert not is_standard_stud_grid_position((3.0, 1.0, 1.5))

    # The shared subpart's tube/lip references remain visual features with no
    # receiving-connector classification.
    assert ldraw_to_part_local((0.0, 8.0, -20.0), WEDGE_SOURCE) == (1.0, 1.0, 0.0)
    assert ldraw_to_part_local((0.0, 8.0, 0.0), WEDGE_SOURCE) == (2.0, 1.0, 0.0)


def test_15068_source_backed_stud_coordinates_are_preserved_without_snapping() -> None:
    curved_slope = ldraw_source_frame("15068")
    upper_stud = ldraw_to_part_local((0.0, -12.0, 10.0), curved_slope)
    lower_stud = ldraw_to_part_local((0.0, -4.0, -10.0), curved_slope)
    assert upper_stud == (1.0, 1.5, 3.5)
    assert lower_stud == (1.0, 0.5, 2.5)
    assert not is_standard_stud_grid_position(upper_stud)
    assert not is_standard_stud_grid_position(lower_stud)


def test_rotation_preserves_an_arbitrary_continuous_canonical_coordinate() -> None:
    point = (1.0, 0.5, 2.5)
    assert rotate_part_local(point, BRICK_3001_PLACEMENT, 90) == (0.5, 3.0, 2.5)
    assert rotate_part_local(point, BRICK_3001_PLACEMENT, 180) == (3.0, 1.5, 2.5)


def test_placement_rotation_does_not_depend_on_ldraw_source_anchor() -> None:
    point = (2.5, 0.5, 3.0)

    assert rotate_part_local(point, PartLocalFrame(3, 1, 3), 180) == (0.5, 0.5, 3.0)
