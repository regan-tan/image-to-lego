"""Independent synthetic assembly checks for the M12A 41769a experiment."""

from __future__ import annotations

import pytest

from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.m12a_wedge_mechanics import physical_collision
from app.conversion.m12b_wedge_assembly_validation import validate_synthetic_assembly
from app.conversion.part_catalogue import PART_BY_ID


def _placement(part_id: str, x: int, y: int, z: int, orientation: int = 0) -> BrickPlacement:
    return BrickPlacement(PART_BY_ID[part_id], GridPosition(x, y, z), orientation)


def test_single_receiver_and_multiple_receiver_assemblies_are_valid() -> None:
    one_receiver = (_placement("3024", 0, 1, 0), _placement("41769", 0, 0, 1))
    five_receivers = (_placement("3020", 0, 0, 0), _placement("41769", 0, 0, 1))

    one_report = validate_synthetic_assembly(one_receiver)
    five_report = validate_synthetic_assembly(five_receivers)

    assert one_report.is_valid
    assert one_report.connection_edges[0].stud_count == 1
    assert five_report.is_valid
    assert five_report.connection_edges[0].stud_count == 5
    assert five_report.connected_components == ((0, 1),)
    assert five_report.unsupported_placement_indices == ()


def test_three_part_wedge_brick_plate_assembly_is_one_supported_component() -> None:
    report = validate_synthetic_assembly(
        (
            _placement("3001", 0, 0, 0),
            _placement("41769", 0, 0, 3),
            _placement("3024", 0, 1, 4),
        )
    )

    assert report.is_valid
    assert tuple(edge.stud_count for edge in report.connection_edges) == (5, 1)
    assert report.connected_components == ((0, 1, 2),)
    assert report.part_counts == (("3001", 1), ("3024", 1), ("41769", 1))
    assert report.projection_consistent
    assert report.export_representable is None


@pytest.mark.parametrize("orientation", (0, 90, 180, 270))
def test_all_source_backed_quarter_turns_support_the_wedge(orientation: int) -> None:
    report = validate_synthetic_assembly(
        (_placement("3020", 0, 0, 0, orientation), _placement("41769", 0, 0, 1, orientation))
    )

    assert report.is_valid
    assert report.connection_edges[0].stud_count == 5


@pytest.mark.parametrize(
    ("placements", "expected_field"),
    (
        ((_placement("3024", 0, 0, 0), _placement("41769", 0, 0, 1)), "invalid_interface_pairs"),
        ((_placement("3024", 1, 0, 0), _placement("41769", 0, 0, 1)), "invalid_interface_pairs"),
        ((_placement("41769", 0, 0, 0), _placement("3024", 3, 0, 0)), "collision_pairs"),
        ((_placement("41769", 0, 0, 0), _placement("3024", 0, 0, 1)), "invalid_interface_pairs"),
        ((_placement("41769", 0, 0, 1),), "unsupported_placement_indices"),
        ((_placement("3024", 0, 0, 0), _placement("3024", 4, 0, 0)), "connected_components"),
        ((_placement("41769", 0, 0, 0), _placement("3024", 8, 8, 0)), "isolated_placement_indices"),
        ((_placement("41769", 0, 0, 0), _placement("4286", 0, 0, 1)), "invalid_placement_indices"),
        ((_placement("41770", 0, 0, 0),), "invalid_placement_indices"),
    ),
)
def test_invalid_fixture_groups_are_rejected(
    placements: tuple[BrickPlacement, ...], expected_field: str
) -> None:
    report = validate_synthetic_assembly(placements)

    assert not report.is_valid
    assert getattr(report, expected_field)


def test_unsupported_orientation_is_classified_without_expanding_the_domain() -> None:
    report = validate_synthetic_assembly((_placement("41769", 0, 0, 0, 45),))

    assert not report.is_valid
    assert report.invalid_placement_indices == (0,)


def test_geometric_edge_cases_use_the_wedge_polygon_not_a_bounding_box() -> None:
    wedge = _placement("41769", 0, 0, 0)
    bounding_box_only_contact = _placement("3024", 4, 1, 0)
    body_intersection = _placement("3024", 3, 0, 0)
    rotated_wedge = _placement("41769", 0, 0, 0, 90)

    assert not physical_collision(wedge, bounding_box_only_contact)
    assert physical_collision(wedge, body_intersection)
    assert not physical_collision(rotated_wedge, body_intersection)
    assert validate_synthetic_assembly((wedge, bounding_box_only_contact)).projection_consistent
