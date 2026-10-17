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
| 41769 | `parts/41769a.dat` | `0b069ab042f2cc8297a52e76b49a06e504cd4e9a51f02d6aea8c63f686c28ff8` | `a0e9fad37353af27f0e33b67db62a205f6ba4c6e4410089987ce576596e707cc` |
| 41770 | `parts/41770a.dat` | `59648c2ca07a51d82fdc9aabf4edb65f4942760dc9df3b64946d13fd82b0303d` | `5f11777e9edc341498c0b523afe131d192e6afcfe3f63716a560a1fd1100b1ac` |

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

## Parts 41769 and 41770 source foundation

BrickLink identifies `41769` as **Wedge, Plate 4 x 2 Right** and `41770` as the distinct
**Left** paired part. Both have a 4 by 2 stud envelope. The one-plate catalogue height describes
the plate body; the generated visual meshes have a 1.5-plate z bound because they include studs.

The current official LDraw library (retrieved 2026-10-17) makes the visual-source decision
explicit rather than relying on matching number strings:

| Catalogue identity | BrickLink ID | Official LDraw compatibility file | Canonical visual source | Separate visual variant |
| --- | --- | --- | --- | --- |
| Right wedge | `41769` | `parts/41769.dat` redirects to `41769a.dat` | `parts/41769a.dat`, without chamfer | `parts/41769b.dat`, with chamfer |
| Left wedge | `41770` | `parts/41770.dat` redirects to `41770a.dat` | `parts/41770a.dat`, without chamfer | `parts/41770b.dat`, with chamfer |

The selected roots, their shared `parts/s/41770as01.dat` subpart, `p/stug-1x4.dat`, and every
recursively referenced primitive are checked in under `ldraw_source/`. The root and subpart files
declare official LDraw update **2026-05** and CC BY 4.0; they were retrieved from the official
LDraw library source endpoints, which are the source used by the current complete archive. The
hash table above pins the selected roots and generated assets. The `b` files are documented but
not imported because they are a distinct chamfered visual variant, not the compatibility target.

The normal importer maps the LDraw long axis `z` to the application's local `x` axis. It generates
one asset per catalogue identity (`41769.json`, `41770.json`) from its explicit `a` variant; no
hand-authored wedge mesh is used.

### Mirror, fit, and mechanical research

`41769` and `41770` are a mirrored pair, not two rotations of one catalogue identity. A 90-degree
rotation is available to each future placement, and 180 degrees preserves the same handedness; no
rotation produces the opposite handedness. A future candidate must therefore retain both the
catalogue ID and its rotation instead of collapsing this pair into one part.

The next opt-in fitting experiment should model each part as a one-plate-high 4 by 2 bounding
rectangle plus an orientation-aware, handed polygon or fractional-coverage footprint. An integer
set of occupied stud cells alone is **not sufficient**: the authoritative visual outline uses a
diagonal that cuts through boundary cells, so treating it as all eight cells loses the wedge
advantage and choosing a smaller cell subset changes the shape. This is research only; no fit
geometry, candidate generation, CP-SAT constraint, buildability, insertion, or instructions use
these parts today.

Mechanical facts are intentionally separated from visual facts:

- **KNOWN:** each LDraw root places the `stug-1x4` primitive (a row of four `stud.dat` references)
  and the shared body source includes one `stud4.dat` reference. The shared source also explicitly
  models an end stud tube/lip and a centre stud tube/lip. Its plate body spans the one-plate
  envelope and its rendered geometry shows ordinary top studs and underside detail.
- **UNRESOLVED:** those visual primitives are not an authoritative mechanical-connectivity
  contract. Exact production-mould underside contact areas, legal clutch/connectivity states,
  strength/stability, insertion feasibility, and whether every apparent recess is a usable
  connector remain unverified. Ordinary vertical attachment is visually plausible but is not
  activated or claimed by `stud-connectivity-v1`.

Both parts are source foundation only: `fitterEnabled` remains false, so production conversion
output and fitter inventory are unchanged.

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
