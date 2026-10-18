from app.conversion.part_catalogue import ALL_PARTS, FITTER_PARTS, LEGO_PART_CATALOGUE, PART_BY_ID
from app.conversion.part_geometry import load_part_geometry


def test_all_parts_load_and_can_be_looked_up_by_canonical_id() -> None:
    assert len(ALL_PARTS) == 18
    assert PART_BY_ID["3001"].name == "Brick 2 x 4"
    assert PART_BY_ID["4286"].bricklink_id == "4286"
    assert PART_BY_ID["15068"].name == "Slope Brick Curved 2 x 2 x 0.667"
    assert PART_BY_ID["15068"].family == "curved_slope"
    assert PART_BY_ID["15068"].dimensions.height_plates == 2
    assert not PART_BY_ID["15068"].fitter_enabled
    assert PART_BY_ID["41769"].name == "Wedge, Plate 4 x 2 Right"
    assert PART_BY_ID["41770"].name == "Wedge, Plate 4 x 2 Left"


def test_15068_external_ids_are_explicit() -> None:
    slope = PART_BY_ID["15068"]

    assert slope.ldraw_id == "15068"
    assert slope.bricklink_id == "15068"
    assert slope.supports_color_id("ldraw:0")
    assert not slope.supports_color_id("ldraw:999")


def test_calibration_parts_use_their_authoritative_ldraw_roots() -> None:
    assert {part_id: PART_BY_ID[part_id].ldraw_id for part_id in (
        "3001", "3002", "3003", "3010", "3020", "3021", "3022", "3023"
    )} == {
        "3001": "3001",
        "3002": "3002",
        "3003": "3003",
        "3010": "3010",
        "3020": "3020",
        "3021": "3021",
        "3022": "3022",
        "3023": "3023b",
    }


def test_wedge_plate_external_ids_keep_catalogue_and_visual_identities_distinct() -> None:
    right = PART_BY_ID["41769"]
    left = PART_BY_ID["41770"]

    assert (right.part_id, right.bricklink_id, right.ldraw_id, right.geometry_asset) == (
        "41769",
        "41769",
        "41769a",
        "41769",
    )
    assert (left.part_id, left.bricklink_id, left.ldraw_id, left.geometry_asset) == (
        "41770",
        "41770",
        "41770a",
        "41770",
    )
    assert right.shape == "wedge_plate_4x2_right"
    assert left.shape == "wedge_plate_4x2_left"
    assert right.shape != left.shape
    assert right.verified_color_ids == left.verified_color_ids
    assert right.supports_color_id("ldraw:0")
    assert not right.supports_color_id("ldraw:308")
    assert not left.supports_color_id("ldraw:999")
    assert not right.fitter_enabled
    assert not left.fitter_enabled


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


def test_geometry_references_and_verified_colors_resolve_for_fitter_parts() -> None:
    assert load_part_geometry(PART_BY_ID["3001"].geometry_asset or "") is not None
    assert load_part_geometry(PART_BY_ID["4286"].geometry_asset or "") is not None
    assert all(part.verified_color_ids for part in FITTER_PARTS)


def test_wedge_plate_visual_assets_resolve_without_enabling_the_fitter() -> None:
    for part_id in ("41769", "41770"):
        part = PART_BY_ID[part_id]
        assert load_part_geometry(part.geometry_asset or "") is not None
        assert not part.fitter_enabled


def test_slope_33_catalogue_profile_is_explicit() -> None:
    slope = PART_BY_ID["4286"]

    assert slope.family == "slope_33"
    assert slope.slope_profile == "rise_33_3"
    assert slope.catalogue_key == "slope_1x3"
