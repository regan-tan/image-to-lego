# Canonical LEGO part-local coordinates

This document defines the one coordinate transform used when an authoritative
LDraw source location must be compared with application placement coordinates.
It is a source/diagnostic foundation only: it does not add mechanical connector
semantics or change fitting, buildability, or rendering behaviour.

## Current coordinate-system map

| System | Axes, units, origin, and current behaviour |
| --- | --- |
| LDraw source | `x` right, `y` down, `z` depth; LDraw units (LDU). A stud pitch is 20 LDU and a plate is 8 LDU. The location of LDraw `(0,0,0)` in application-local space is part-specific and verified explicitly. |
| Generated geometry assets | The importer maps either `(x,z,-y)` or `(z,x,-y)`, divides horizontal coordinates by 20 and vertical by 8, then rebases every mesh to its geometry minimum. Its per-part source axis makes the catalogue length the asset x axis. This is visual-mesh normalization, not connector data or source-frame truth. |
| Catalogue | `lengthStuds`, `widthStuds`, and `heightPlates` describe the intended placement footprint and body height.  The catalogue does not describe visual protrusions such as studs. |
| Fitter and world placement | `GridPosition(x,y,z)` uses integer lower-left footprint cells and bottom plate planes. `x` is length, `y` width/depth, `z` plate height.  A placement's orientation is 0/90/180/270. |
| Frontend | Placement `x` renders to Three.js x, placement `y` to Three.js z, and plate `z` to Three.js y.  Generated asset vertices use the existing normalized asset orientation. |
| Silhouettes | Front is XZ, side is YZ, top is XY in the application grid. |
| `stud-connectivity-v1` | Uses overlapping integer `(x,y)` footprint cells and integer plate `z`; it evaluates only rectangular bricks/plates. |
| Staged wedges | Its polygon coordinates are lower-left footprint corners in the same XY placement plane, but are experimental silhouette/fit data only.  They do not provide connector locations. |

All transforms here are right-handed after mapping: canonical `x` cross `y`
points upward along canonical `z`.  The LDraw y-axis reversal is therefore a
required axis sign change, not an optional reflection.

## Canonical application-local frame

For part dimensions `(L, W, H)`, the local origin `(0, 0, 0)` is the lower-left
corner of its catalogue footprint on the bottom plate plane. `x` runs along
catalogue length (0..L), `y` along catalogue width (0..W), and `z` is upward in
plate units. A normal stud center is at `(n + 0.5, m + 0.5, H)`.

`PartLocalFrame` holds only catalogue dimensions and therefore only placement
rotation semantics. `LDrawSourceFrame` separately holds a part ID, LDraw ID,
axis mapping, and `ldraw_origin_in_part_local`. For an LDraw point
`(lx, ly, lz)` and source anchor `(ox, oy, oz)`, the transform is:

- LDraw-x long axis: `(ox + lx / 20, oy + lz / 20, oz - ly / 8)`;
- LDraw-z long axis: `(ox + lz / 20, oy + lx / 20, oz - ly / 8)`.

The inverse subtracts that same anchor before scaling and permuting. No source
coordinate is snapped. The one checked-in registry is the authoritative source
for the axis and anchor used by connector evidence and visual-asset generation.
Generated asset coordinates must not be treated as canonical connector
coordinates: their final mesh-minimum rebase includes studs and other geometry
rather than the catalogue body planes.

## Orientation and standard rectangular stud grid

The orientation transform is the existing placement convention. At 90 degrees
it maps `(x, y)` to `(y, L - x)`, so 90 is clockwise when viewed from positive
canonical z. 180 maps to `(L - x, W - y)` and 270 maps to `(W - y, x)`.

Continuous transformed locations are never rounded. Their source-derived
stud-pitch/plate-height values remain valid canonical coordinates, including
values such as `3.0`, `1.5`, `2.5`, and `3.5`.

`standard_rectangular_stud_grid` is a deliberately narrow current-mechanics
concept: ordinary rectangular brick/plate stud centers have half-integer
horizontal coordinates and integer vertical plate planes. The sole comparison
tolerance is `1e-6`, covering deterministic decimal LDraw values. It never
snaps a coordinate. A point outside this grid is not thereby invalid or an
unknown connector; it is only outside the current rectangular-grid predicate.

Connector evidence and mechanics are assessed in this order:

1. LDraw source coordinates;
2. continuous canonical application-local coordinates;
3. source-backed connector geometry, such as an explicit LDraw stud primitive;
4. connector-type-specific compatibility; and
5. the current fitter's rectangular-grid mechanical support.

A **source-backed connector location** is established by authoritative source
geometry. A **current-mechanics-compatible connector** is a source-backed
location that the current mechanical representation can evaluate. These are
separate claims: source-backed studs outside the standard rectangular grid are
known locations but mechanically unsupported/unresolved in this milestone.
This document does not posit a universal connector lattice for future studs,
SNOT connections, clips, bars, pins, axles, or other interfaces.

## Checked-in calibration and diagnostics

3001 is the centred reference: its source anchor is `(2, 1, 3)`. LDraw
`(-30, 0, -10)` maps to canonical `(0.5, 0.5, 3)`, while `(-40, 24, -20)`
maps to `(0, 0, 0)`. The visual stud centers therefore land on the expected
lattice.

4286 contrasts with that reference. Its official source body spans LDraw
`z=-50..10`, while its 3 x 1 catalogue footprint is canonical `x=0..3`.
The explicit anchor `(2.5, 0.5, 3)` follows those body end planes: raw
`z=-50` maps to canonical `x=0`, raw `z=10` maps to `x=3`, and the source's
top-stud origin `(0,0,0)` maps to `(2.5,0.5,3)`. The raw underside `stud3a`
placement `(0,20,-30)` maps to `(1,0.5,0.5)`. This matches the generated
asset's rebased horizontal landmarks at x `0`, `1`, `2.5`, and `3`, but the
mesh rebase is corroborating visual evidence only, not how the anchor is
defined.

The following source-frame registry entries are calibrated from the checked-in
official roots, catalogue footprint/body planes, and explicit source features:

| Part | Catalogue `(L,W,H)` | LDraw ID / axis | LDraw origin in canonical space | Source-backed check |
| --- | --- | --- | --- | --- |
| 3001 | `(4,2,3)` | `3001` / x | `(2,1,3)` | eight top studs, including `(-30,0,-10)` -> `(0.5,0.5,3)` |
| 3002 | `(3,2,3)` | `3002` / x | `(1.5,1,3)` | six top studs on the rectangular grid |
| 3003 | `(2,2,3)` | `3003` / x | `(1,1,3)` | four top studs on the rectangular grid |
| 3010 | `(4,1,3)` | `3010` / x | `(2,0.5,3)` | four top studs on the rectangular grid |
| 3020 | `(4,2,1)` | `3020` / x | `(2,1,1)` | eight top studs on the rectangular grid |
| 3021 | `(3,2,1)` | `3021` / x | `(1.5,1,1)` | six top studs on the rectangular grid |
| 3022 | `(2,2,1)` | `3022` / x | `(1,1,1)` | four top studs on the rectangular grid |
| 3023 | `(2,1,1)` | `3023b` / x | `(1,0.5,1)` | two top studs on the rectangular grid |
| 4286 | `(3,1,3)` | `4286` / z | `(2.5,0.5,3)` | top stud and body end planes above |
| 15068 | `(2,2,2)` | `15068` / x | `(1,1,2)` | `stud3a` / `stud3` retain `(1,0.5,2.5)` / `(1,1.5,3.5)` |
| 41769 | `(4,2,1)` | `41769a` / z | `(2,1,1)` | mirrored four-stud row and shared `stud4` |
| 41770 | `(4,2,1)` | `41770a` / z | `(2,1,1)` | four-stud row and shared `stud4` |

External corroboration was inspected in the LDCad Shadow Library,
`RolandMelkert/LDCadShadowLibrary` revision
`9b1131fb1991f8c0bfc072325e4e12f6271aba35`, `parts/4286.dat`. Its three
female snap positions `(0,24,0)`, `(0,24,-20)`, and `(0,24,-40)` map through
the corrected frame to `(2.5,0.5,0)`, `(1.5,0.5,0)`, and `(0.5,0.5,0)`.
That community-maintained metadata is corroboration only: it is neither
vendored nor a runtime input nor manufacturer mechanical truth.

For 41770, the authoritative `stug-1x4` instance contains explicit `stud.dat`
references that map to `(0.5..3.5, 0.5, 1)`; 41769's mirrored source maps to
`(0.5..3.5, 1.5, 1)`. These are source-backed top-stud locations and are on the
standard rectangular stud grid, so the current fitter can represent them.

The shared `s\\41770as01.dat` subpart explicitly references `stud4.dat` at
`(0, 4, 20)` with transform `(-1,0,0; 0,-1,0; 0,0,1)`. Both 41770 and 41769
resolve that full ring/tube at canonical `(3, 1, 0.5)`. Thus the previous
41769 diagnostic at `(3, 1, 1.5)` was not the center of this explicit source
primitive. The primitive is genuine source-backed stud geometry, but its
continuous location is not on the standard rectangular stud grid, so it is not
currently mechanically evaluated.

The shared subpart's end tube/lip reference around `(0, 8, -20)` maps to
`(1, 1, 0)` and its centre tube/lip around `(0, 8, 0)` maps to `(2, 1, 0)`;
both remain source visual features with receiving mechanical meaning unresolved.
The authoritative sources are mirrored in LDraw x, so the staged wedge labels
are consistent: there is no production naming or geometry correction in this
change.

For 15068, `s\\15068s01.dat` explicitly references `stud3.dat` at
`(0, -12, 10)` and `stud3a.dat` at `(0, -4, -10)`. They map to `(1, 1.5, 3.5)`
and `(1, 0.5, 2.5)` using the current catalogue dimensions. These are
source-backed stud locations, even though neither is on the standard grid and
the current fitter cannot evaluate its nonstandard vertical placement.

Known limitations: LDraw primitive names and meshes are visual modelling data;
they cannot by themselves establish clutch, receiving-tube, insertion, support,
or stability semantics. Future mechanical work must separately validate those
claims before enabling a part family.
