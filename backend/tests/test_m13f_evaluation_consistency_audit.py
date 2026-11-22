from PIL import Image

from app.conversion import core, m13f_evaluation_consistency_audit
from app.conversion.m13f_evaluation_consistency_audit import frozen_source_pixel_counts
from app.conversion.part_catalogue import PART_BY_ID


def test_frozen_source_pixel_counts_counts_filled_binary_pixels(monkeypatch) -> None:
    source = Image.new("1", (2, 2))
    source.putdata((0, 1, 1, 0))
    output = Image.new("1", (2, 2))
    masks = {view: (source, output) for view in ("front", "side", "top")}
    monkeypatch.setattr(
        m13f_evaluation_consistency_audit,
        "render_silhouette_masks",
        lambda *_args, **_kwargs: masks,
    )

    assert frozen_source_pixel_counts((), (), ()) == {"front": 2, "side": 2, "top": 2}


def test_frozen_source_raster_is_assembly_bound_dependent() -> None:
    source = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    faces = ((0, 1, 2),)
    nearby = (core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(0, 0, 0), 0),)
    distant = (core.BrickPlacement(PART_BY_ID["3024"], core.GridPosition(20, 0, 0), 0),)

    assert frozen_source_pixel_counts(source, faces, nearby) != frozen_source_pixel_counts(
        source, faces, distant
    )
