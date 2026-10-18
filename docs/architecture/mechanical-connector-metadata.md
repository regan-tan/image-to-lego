# Mechanical connector metadata

Status: implemented. It backs production direct support-edge construction for
`stud-connectivity-v1`; it does **not** alter fitter, vertical insertion, API,
or the frontend.

## Why the model is hybrid

LDraw is authoritative for source geometry and provenance. It is not, by
itself, authoritative proof that a visual primitive is a complete mechanical
receiver. Calibration showed that `stud3` and `stud4` geometry does not
reproduce every ordinary brick/plate receiving footprint. The existing
rectangular brick/plate semantics are already trusted for those footprints.

The resulting lifecycle keeps the claims separate:

```mermaid
flowchart LR
    LDraw[Authoritative LDraw] --> Evidence[Connector evidence]
    Evidence --> Verified[Verified mechanical metadata]
    Verified --> Matcher[Generic connector matcher]
    Matcher --> Buildability[Production stud-connectivity-v1 buildability]
```

Source evidence is never automatically promoted to mechanical truth.

## `vertical-stud-v1`

Each resolved connector has a canonical part-local coordinate, direction,
interface kind, and provenance. This version supports only vertical
stud-system connections:

- `male_stud`, direction `+Z`
- `stud_receiver`, direction `-Z`

The provenance vocabulary is `source_backed`, `trusted_family_rule`, and
`curated_verified`. Generated rectangular top studs and underside receivers
use `trusted_family_rule`; the top set is additionally cross-checked against
authoritative `stud.dat` source evidence where present. The receiver set is
explicitly not inferred from `stud3`/`stud4` counts.

The runtime metadata source of truth is
`backend/app/conversion/mechanical_connectors.py`: a part whose existing
catalogue semantics say `shape == rectangular` and family `brick` or `plate`
receives one top stud and one underside receiver at each catalogue footprint
cell. The runtime catalogue remains the input dimensions; `parts.json` does
not duplicate per-part connector arrays. A small explicit declaration in the
same module may record a separately reviewed non-rectangular part; it does not
create a family rule.

## Coordinates, transform, and matching

Part-local coordinates use the established lower-left footprint origin. A cell
`(x, y)` resolves at `(x + 0.5, y + 0.5)`: top studs are on the part height
plane and receivers are on the bottom plane. The existing 0/90/180/270 local
rotation transform is applied first, then `GridPosition(x, y, z)` is added.
Directions remain vertical under these rotations.

The pure matcher accepts only exact coordinate equality, opposite directions,
and the pair `male_stud` / `stud_receiver`. It deliberately has no bounding
box overlap, tolerance, clutch-force, stability, or insertion claim.

Production support detection resolves only `verified` metadata, transforms the
lower placement's `male_stud +Z` and upper placement's `stud_receiver -Z` to
world coordinates, then uses this matcher. Ground support remains the existing
minimum-placement-z rule and does not require a connector below the model.

Validation rejects version mismatches, malformed/non-finite coordinates,
non-vertical directions, unsupported interface values, duplicate connectors,
and source-backed top-stud disagreement. Reports are deterministic and include
the metadata version, dimensions, counts, provenance, evidence agreement, and
ordered connector data.

## Curated part 4286

4286 (Slope Brick 33 3 x 1) is the one curated non-rectangular part in this
metadata version. Its source hierarchy is `parts/4286.dat` ->
`parts/s/4286s01.dat` -> `p/stud.dat`, which has one upward source-backed
male stud at raw LDraw `(0,0,0)` and canonical `(2.5,0.5,3)`. No additional
upward `stud.dat` reference appears in that hierarchy.

Its three underside receivers are a project-owned `curated_verified` decision
at canonical `(0.5,0.5,0)`, `(1.5,0.5,0)`, and `(2.5,0.5,0)`, all directed
`-Z`. The decision combines the corrected explicit source frame, the official
underside cavity/body geometry, the calibrated ordinary 1-wide brick/plate
receiver pitch and bottom plane, and external corroboration from the LDCad
Shadow Library at `RolandMelkert/LDCadShadowLibrary`
`9b1131fb1991f8c0bfc072325e4e12f6271aba35`, `parts/4286.dat`. That external
community metadata is not vendored, runtime data, or manufacturer truth. LDraw
geometry supports the placement and absence of any other receiver position in
the 3 x 1 footprint, but does not by itself prove clutch force.

4286 is therefore `verified` for `stud-connectivity-v1` support only. It is
still unevaluated by `vertical-insertion-v1`: that analysis deliberately uses
only conservative rectangular fit geometry, and connectors are not collision
geometry.

## Other non-trivial parts

41769, 41770, and 15068 remain mechanically `unevaluated`. Their LDraw source
evidence is preserved for diagnostics but does not create verified underside
receiver metadata. A future part-family workflow must first establish a
separate verified mechanical rule or curated verification, add deterministic
tests, and then make a separately reviewed production-buildability change.
