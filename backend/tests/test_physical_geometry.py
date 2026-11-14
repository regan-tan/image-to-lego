from __future__ import annotations

from app.conversion import core, surface_grid_v4
from app.conversion.core import BrickPlacement, GridPosition
from app.conversion.part_catalogue import PART_BY_ID
from app.conversion.physical_geometry import (
    SUBDIVISIONS_PER_PLATE,
    SUBDIVISIONS_PER_STUD,
    colliding_placement_pairs,
    local_physical_geometry,
    physical_microcells,
    placements_overlap,
)


def _placement(
    part_id: str, x: int = 0, y: int = 0, z: int = 0, rotation: int = 0
) -> BrickPlacement:
    return BrickPlacement(PART_BY_ID[part_id], GridPosition(x, y, z), rotation)


def test_wedge_body_is_not_its_rectangular_bounds_and_handedness_is_distinct() -> None:
    right = local_physical_geometry(PART_BY_ID["41769"])
    left = local_physical_geometry(PART_BY_ID["41770"])
    full_bounds = 4 * 2 * SUBDIVISIONS_PER_STUD**2 * SUBDIVISIONS_PER_PLATE

    assert len(right.occupied_local_microcells) < full_bounds
    assert right.occupied_local_microcells != left.occupied_local_microcells


def test_rotations_preserve_body_volume_for_an_asymmetric_wedge() -> None:
    volumes = {
        len(physical_microcells(_placement("41769", rotation=orientation)))
        for orientation in (0, 90, 180, 270)
    }

    assert len(volumes) == 1


def test_curved_slope_proxy_is_not_a_rectangular_prism() -> None:
    curved = local_physical_geometry(PART_BY_ID["15068"])
    full_bounds = 2 * 2 * 2 * SUBDIVISIONS_PER_STUD**2 * SUBDIVISIONS_PER_PLATE

    assert 0 < len(curved.occupied_local_microcells) < full_bounds


def test_adjacent_contact_is_allowed_but_interior_penetration_is_rejected() -> None:
    first = _placement("3020")
    adjacent = _placement("3020", x=4)
    overlapping = _placement("3020", x=3)

    assert not placements_overlap(first, adjacent)
    assert placements_overlap(first, overlapping)


def test_supported_non_rectangular_pair_collision_is_detected() -> None:
    right = _placement("41769")
    left = _placement("41770")

    assert colliding_placement_pairs((right, left)) == ((0, 1),)


def test_physical_geometry_fingerprint_is_cached_and_deterministic() -> None:
    first = local_physical_geometry(PART_BY_ID["4286"])
    second = local_physical_geometry(PART_BY_ID["4286"])

    assert first is second
    assert len(first.fingerprint) == 64
    assert first.fingerprint == second.fingerprint


def test_4286_body_collision_not_represented_by_its_coarse_source_profile() -> None:
    slope = _placement("4286", y=5, z=4)
    plate = _placement("3710", y=2, z=5, rotation=90)
    candidate = surface_grid_v4._Candidate(plate, core._placement_cells(plate))

    assert core._placement_source_cells(slope).isdisjoint(core._placement_source_cells(plate))
    assert physical_microcells(slope) & physical_microcells(plate) == {
        (3, 20, 20),
        (3, 21, 20),
        (3, 22, 20),
        (3, 23, 20),
    }
    assert placements_overlap(slope, plate)
    assert surface_grid_v4._exclude_locked_body_collisions((candidate,), (slope,)) == ()
