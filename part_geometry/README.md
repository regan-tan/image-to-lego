# LDraw-derived part geometry

`backend/app/conversion/part_geometry_assets/` holds the small, generated visual
meshes used by both the backend loader and frontend viewer. This directory keeps
their provenance and minimal LDraw source evidence. Fitting and `silhouette-v1`
deliberately continue to use their simple grid occupancy and slope prism representations.

## Pinned source and attribution

- Source: official [LDraw.org Parts Library complete archive](https://library.ldraw.org/library/updates/complete.zip), core update **2026-04**, downloaded 2026-10-11.
- Archive SHA-256: `425f67cd40bf4d19e7c7949af7d517a906a3c27499c1de4d5336c08274d1b7ad`.
- License: source files declare [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The generated JSON is a derived, normalized representation.
- Attribution: LDraw.org Parts Library; root files credit James Jessiman (`3001.dat`, `4286.dat`) and Chris Böhnke / KnightOfTarenta (`s/4286s01.dat`).

| Part | LDraw source | Source SHA-256 | Generated asset SHA-256 |
| --- | --- | --- | --- |
| 3001 | `parts/3001.dat` | `70968cb5e4baa92dc6a1939aca7526b8566a17dbea49da9b91182aa864e412c4` | `544927f8d87678a76411b00a30b50a154463f0e926e774a7a72faf5d6f38238b` |
| 4286 | `parts/4286.dat` | `ce0b8fe0d83dd527625b773a26725ec927d462bc4216a8f3912fc72862016539` | `57e23c4b794d5c89e0edb5ac4ee5f966c061db2e666cc90be4be7ae0ab6848f7` |

## Regeneration

Given an extracted official `ldraw` directory, run from `backend/`:

```powershell
uv run python ../scripts/import_ldraw_geometry.py <ldraw-directory> ../backend/app/conversion/part_geometry_assets
```

The importer supports the type 1 references, type 3 triangles, type 4 quads,
and `BFC INVERTNEXT` needed by these source hierarchies. It converts LDraw units
once into local application units: 20 LDU = one horizontal stud and 8 LDU = one
vertical plate. Each asset's configured long LDraw axis becomes local `x`; the
other horizontal axis becomes local `y`, LDraw `y` (down) becomes local `z` (up),
and the resulting bounds are translated to start at `(0, 0, 0)`.

`ldraw_source/` contains only the files used by these two part hierarchies, so
the generated assets can be recreated without downloading the full library.

To add a part, add its source file and long-axis entry to `PARTS`, generate its
JSON, record its hashes here, and add its `geometry_asset`/`ldraw_id` metadata to
the catalogue. No viewer-specific renderer is required.
