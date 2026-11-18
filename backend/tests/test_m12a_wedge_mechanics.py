from __future__ import annotations

import pytest

from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.m12a_wedge_mechanics import (
    ExperimentalPlacementError,
    contains_body_point,
    has_ground_support,
    is_supported,
    mechanical_adjacency,
    physical_collision,
    projection_polygon,
    underside_receiver_coordinates,
    validate_assembly,
    validate_placement,
)
from app.conversion.part_catalogue import PART_BY_ID


def _placement(part_id: str, x: int, y: int, z: int, orientation: int = 0) -> BrickPlacement:
    return BrickPlacement(PART_BY_ID[part_id], GridPosition(x, y, z), orientation)


@pytest.mark.parametrize("orientation", (0, 90, 180, 270))
def test_wedge_has_deterministic_nonrectangular_projection_in_every_allowed_orientation(
    orientation: int,
) -> None:
    wedge = _placement("41769", 10, 20, 0, orientation)

    polygon = projection_polygon(wedge)

    assert len(polygon) == 4
    assert polygon == projection_polygon(wedge)
    twice_area = abs(
        sum(
            x1 * y2 - y1 * x2
            for (x1, y1), (x2, y2) in zip(polygon, (*polygon[1:], polygon[0]), strict=True)
        )
    )
    assert twice_area == 12.0


def test_wedge_collision_is_not_its_rectangular_bounding_box() -> None:
    wedge = _placement("41769", 0, 0, 0)

    # Both points are inside the 4x2 bounding box; only one is in the wedge body.
    assert not contains_body_point(wedge, (0.25, 1.99, 0.5))
    assert contains_body_point(wedge, (3.5, 0.5, 0.5))
    assert physical_collision(wedge, _placement("3024", 3, 0, 0))


def test_rotation_changes_the_continuous_body_relationship() -> None:
    world_point = (3.5, 0.05, 0.5)

    assert contains_body_point(_placement("41769", 0, 0, 0, 0), world_point)
    assert not contains_body_point(_placement("41769", 0, 0, 0, 180), world_point)


def test_source_backed_top_studs_support_a_rectangular_plate() -> None:
    wedge = _placement("41769", 0, 0, 0)
    upper_plate = _placement("3024", 0, 1, 1)

    assert has_ground_support(wedge)
    assert is_supported(wedge, upper_plate)
    assert not physical_collision(wedge, upper_plate)
    assert mechanical_adjacency((wedge, upper_plate))[0].stud_count == 1
    assert validate_assembly((wedge, upper_plate))[0].stud_count == 1


def test_nonmatching_contact_does_not_create_a_mechanical_edge() -> None:
    wedge = _placement("41769", 0, 0, 0)
    unmatched_plate = _placement("3024", 0, 0, 1)

    assert not is_supported(wedge, unmatched_plate)
    assert mechanical_adjacency((wedge, unmatched_plate)) == ()


def test_wedge_underside_and_unsupported_configuration_are_rejected() -> None:
    base_plate = _placement("3024", 0, 0, 0)
    floating_wedge = _placement("41769", 0, 0, 1)

    assert not is_supported(base_plate, floating_wedge)
    assert not has_ground_support(floating_wedge)


def test_wedge_can_attach_to_a_known_rectangular_plate_at_a_verified_receiver() -> None:
    base_plate = _placement("3024", 0, 1, 0)
    wedge = _placement("41769", 0, 0, 1)

    assert is_supported(base_plate, wedge)
    assert not physical_collision(base_plate, wedge)
    assert validate_assembly((base_plate, wedge))[0].stud_count == 1


@pytest.mark.parametrize(
    ("orientation", "expected"),
    (
        (0, ((0.5, 1.5, 1.0), (1.5, 1.5, 1.0), (2.5, 1.5, 1.0), (3.5, 0.5, 1.0), (3.5, 1.5, 1.0))),
        (90, ((1.5, 3.5, 1.0), (1.5, 2.5, 1.0), (1.5, 1.5, 1.0), (0.5, 0.5, 1.0), (1.5, 0.5, 1.0))),
        (
            180,
            ((3.5, 0.5, 1.0), (2.5, 0.5, 1.0), (1.5, 0.5, 1.0), (0.5, 1.5, 1.0), (0.5, 0.5, 1.0)),
        ),
        (
            270,
            ((0.5, 0.5, 1.0), (0.5, 1.5, 1.0), (0.5, 2.5, 1.0), (1.5, 3.5, 1.0), (0.5, 3.5, 1.0)),
        ),
    ),
)
def test_underside_receiver_transform_uses_independently_fixed_coordinates(
    orientation: int, expected: tuple[tuple[float, float, float], ...]
) -> None:
    wedge = _placement("41769", 0, 0, 1, orientation)

    assert underside_receiver_coordinates(wedge) == expected


def test_illegal_orientation_and_negative_grid_coordinate_are_rejected() -> None:
    with pytest.raises(ExperimentalPlacementError):
        validate_placement(_placement("41769", 0, 0, 0, 45))
    with pytest.raises(ExperimentalPlacementError):
        validate_placement(_placement("41769", -1, 0, 0))


def test_disconnected_experimental_assembly_has_no_adjacency() -> None:
    wedge = _placement("41769", 0, 0, 0)
    disconnected_plate = _placement("3024", 8, 8, 1)

    assert mechanical_adjacency((wedge, disconnected_plate)) == ()
    with pytest.raises(ExperimentalPlacementError, match="lacks verified"):
        validate_assembly((wedge, disconnected_plate))
