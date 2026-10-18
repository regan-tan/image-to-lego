# Canonical LEGO part-local coordinates

This document defines the one coordinate transform used when an authoritative
LDraw source location must be compared with application placement coordinates.
It is a source/diagnostic foundation only: it does not add mechanical connector
semantics or change fitting, buildability, or rendering behaviour.

## Current coordinate-system map

| System | Axes, units, origin, and current behaviour |
| --- | --- |
| LDraw source | `x` right, `y` down, `z` depth; LDraw units (LDU); part-local origin is conventionally horizontally centred at the top surface.  A stud pitch is 20 LDU and a plate is 8 LDU. |
| Generated geometry assets | The importer maps either `(x,z,-y)` or `(z,x,-y)`, divides horizontal coordinates by 20 and vertical by 8, then rebases every mesh to its geometry minimum.  Its per-part `long_axis` makes the catalogue length the asset x axis.  This is visual-mesh normalization, not connector data. |
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

For an LDraw point `(lx, ly, lz)`, the transform is:

- parts whose authoritative long axis is LDraw x: `(lx / 20 + L / 2, lz / 20 + W / 2, H - ly / 8)`;
- parts whose authoritative long axis is LDraw z: `(lz / 20 + L / 2, lx / 20 + W / 2, H - ly / 8)`.

The required long-axis choice is explicit per part, matching the existing
visual importer: 3001 and 15068 use x; 4286, 41769, and 41770 use z. This is
also why generated visual asset coordinates must not be treated as canonical
connector coordinates: their final mesh-minimum rebase includes studs and other
geometry rather than the catalogue body planes.

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

3001 confirms the scale and origin: LDraw `(-30, 0, -10)` maps to canonical
`(0.5, 0.5, 3)`, while `(-40, 24, -20)` maps to `(0, 0, 0)`. The visual stud
centers therefore land on the expected lattice.

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
