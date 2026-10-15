"""Run silhouette-residual opportunity analysis without changing a conversion output."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.conversion import core  # noqa: E402
from app.conversion.fidelity import render_silhouette_masks  # noqa: E402
from app.conversion.part_family_opportunities import (  # noqa: E402
    OpportunityFamily,
    analyze_part_family_opportunities,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target-parts", type=int, required=True)
    parser.add_argument("--up-axis", choices=("x", "y", "z"), default="y")
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args()

    source = arguments.source.read_bytes()
    settings = core.ConversionSettings(
        target_parts=arguments.target_parts,
        up_axis=core.Axis(arguments.up_axis),
        algorithm_version=core.SURFACE_GRID_V4,
    )
    model = core.convert_glb(source, settings)
    mesh = core._load_mesh(source)
    vertices = [(float(vertex[0]), float(vertex[1]), float(vertex[2])) for vertex in mesh.vertices]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in mesh.faces]
    normalized = core._normalize_vertices(vertices, settings.up_axis)
    masks = render_silhouette_masks(
        core._scale_vertices_to_grid(normalized, model.metadata.grid_size),
        faces,
        core._placement_boxes(model.placements),
        slope_vertices=core._slope_vertices(model.placements),
    )
    report = analyze_part_family_opportunities(masks)
    family_counts = Counter(placement.brick_type.family for placement in model.placements)
    payload = {
        "targetParts": arguments.target_parts,
        "fidelity": asdict(model.metadata.fidelity),
        "placementFamilies": dict(sorted(family_counts.items())),
        "views": [asdict(view) for view in report.views],
        "opportunityEvidence": [
            {**asdict(item), "family": item.family.value} for item in report.evidence
        ],
        "familyResidualPixels": {
            family.value: sum(
                item.residual_pixels for item in report.evidence if item.family == family
            )
            for family in OpportunityFamily
        },
    }
    if arguments.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    fidelity = payload["fidelity"]
    print(
        f"targetParts={arguments.target_parts} meanIoU={fidelity['mean_iou']:.6f} "
        f"front={fidelity['front_iou']:.6f} side={fidelity['side_iou']:.6f} "
        f"top={fidelity['top_iou']:.6f}"
    )
    print(f"placement families: {payload['placementFamilies']}")
    for view in report.views:
        print(
            f"{view.view}: fn={view.false_negative_pixels} fp={view.false_positive_pixels} "
            f"disagreement={view.disagreement_pixels} boundary={view.boundary_disagreement_pixels}"
        )
    print("opportunity residual pixels:")
    for family, pixels in payload["familyResidualPixels"].items():
        if pixels:
            print(f"  {family}: {pixels}")


if __name__ == "__main__":
    main()
