# LDraw-derived part geometry

`backend/app/conversion/part_geometry_assets/` holds the small, generated visual
meshes used by both the backend loader and frontend viewer. This directory keeps
their provenance and minimal LDraw source evidence. Fitting and `silhouette-v1`
deliberately continue to use their simple grid occupancy and slope prism representations.

## Pinned source and attribution

- Source: official [LDraw.org Parts Library complete archive](https://library.ldraw.org/library/updates/complete.zip), core update **2026-04**, downloaded 2026-10-11.
- Archive SHA-256: `425f67cd40bf4d19e7c7949af7d517a906a3c27499c1de4d5336c08274d1b7ad`.
- License: source files declare [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The generated JSON is a derived, normalized representation.
- Part `15068` was retrieved on 2026-10-16 from the official complete archive at core update **2026-09** (archive SHA-256 `f3e496d0ede69ca7942fa4aa198e661ee2d22723906101e2e339d8917a4dd5f2`); its root source SHA-256 is recorded below.
- Attribution: LDraw.org Parts Library; root files credit James Jessiman (`3001.dat`, `4286.dat`) and Chris Böhnke / KnightOfTarenta (`s/4286s01.dat`).

| Part | LDraw source | Source SHA-256 | Generated asset SHA-256 |
| --- | --- | --- | --- |
| 3001 | `parts/3001.dat` | `70968cb5e4baa92dc6a1939aca7526b8566a17dbea49da9b91182aa864e412c4` | `544927f8d87678a76411b00a30b50a154463f0e926e774a7a72faf5d6f38238b` |
| 4286 | `parts/4286.dat` | `ce0b8fe0d83dd527625b773a26725ec927d462bc4216a8f3912fc72862016539` | `57e23c4b794d5c89e0edb5ac4ee5f966c061db2e666cc90be4be7ae0ab6848f7` |
| 15068 | `parts/15068.dat` | `511c620c73d116a9564248a4adb0f564b90f12f1428a4a9276b4bae4f9bd7e4c` | `2d23f0315c53d994895ccdab55ed6542f6d20bfe800b614ec7e78fa454a3949a` |

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

## Part 15068 source foundation

`15068` is the official unprinted LDraw part
[Slope Brick Curved 2 x 2 x 0.667](https://library.ldraw.org/library/official/parts/15068.dat),
recorded as `parts/15068.dat` and imported with its complete required hierarchy in
`ldraw_source/`. The LDraw source declares CC BY 4.0 and an Official 2014-01 part update; its
subpart declares the Official 2022-04 update. The hierarchy was retrieved from the official
complete archive on 2026-10-16 and the imported root source SHA-256 is recorded above.

Known visual/source facts: the authoritative footprint is 2 by 2 studs; BrickLink records a
2 by 2 by 0.67-stud envelope, represented in this project as a two-plate height. The LDraw
subpart references `stud3` at LDraw `(0, -12, 10)` and `stud3a` at `(0, -4, -10)`; these are
visual primitive placements at distinct longitudinal positions. Their mechanical roles are not
specified by LDraw. Therefore, exact underside connection positions, mechanically valid top-stud
positions, and all connectivity semantics remain unresolved for `stud-connectivity-v1`.

For the next fitter milestone, the appropriate candidate research representation is an
orientation-aware, two-column directional height profile across the 2 by 2 footprint, with
provisional occupied heights of one then two plate cells repeated across the width. This is a
surface-fitting approximation inferred from the visual curve and the two-plate envelope, not
manufacturing CAD or a connector claim; it requires its own deterministic fit-geometry tests.

Part `15068` is source-foundation only. It is present in the catalogue and has a generated visual
asset, but is deliberately not fitter-enabled and is not used by `surface-grid-v4`, buildability,
instructions, or insertion analysis.
