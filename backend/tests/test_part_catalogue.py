from app.conversion.colors import PART_COLOR_AVAILABILITY
from app.conversion.part_catalogue import ALL_PARTS, FITTER_PARTS, LEGO_PART_CATALOGUE, PART_BY_ID
from app.conversion.part_geometry import load_part_geometry


def test_all_parts_load_and_can_be_looked_up_by_canonical_id() -> None:
    assert len(ALL_PARTS) == 15
    assert PART_BY_ID["3001"].name == "Brick 2 x 4"
    assert PART_BY_ID["4286"].bricklink_id == "4286"


def test_fitter_catalogue_preserves_the_existing_explicit_order() -> None:
    signature = tuple(
        (
            part.part_id,
            part.family,
            part.width_studs,
            part.length_studs,
            part.height_plates,
            part.fitter_order,
        )
        for part in FITTER_PARTS
    )

    assert signature == (
        ("3001", "brick", 2, 4, 3, 0),
        ("3002", "brick", 2, 3, 3, 1),
        ("3003", "brick", 2, 2, 3, 2),
        ("3010", "brick", 1, 4, 3, 3),
        ("3622", "brick", 1, 3, 3, 4),
        ("3020", "plate", 2, 4, 1, 5),
        ("3021", "plate", 2, 3, 1, 6),
        ("3004", "brick", 1, 2, 3, 7),
        ("3022", "plate", 2, 2, 1, 8),
        ("3710", "plate", 1, 4, 1, 9),
        ("3005", "brick", 1, 1, 3, 10),
        ("3623", "plate", 1, 3, 1, 11),
        ("3023", "plate", 1, 2, 1, 12),
        ("3024", "plate", 1, 1, 1, 13),
        ("4286", "slope_33", 1, 3, 3, 14),
    )
    assert LEGO_PART_CATALOGUE == FITTER_PARTS


def test_geometry_references_and_color_availability_resolve_for_fitter_parts() -> None:
    assert load_part_geometry(PART_BY_ID["3001"].geometry_asset or "") is not None
    assert load_part_geometry(PART_BY_ID["4286"].geometry_asset or "") is not None
    assert all(PART_COLOR_AVAILABILITY[part.part_id] for part in FITTER_PARTS)


def test_slope_33_catalogue_profile_is_explicit() -> None:
    slope = PART_BY_ID["4286"]

    assert slope.family == "slope_33"
    assert slope.slope_profile == "rise_33_3"
    assert slope.catalogue_key == "slope_1x3"
