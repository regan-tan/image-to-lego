# Mechanical connector metadata

Status: implemented as a diagnostic metadata foundation. It does **not** alter
`stud-connectivity-v1`, fitting, vertical insertion, instructions, API, or the
frontend.

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
    Matcher -. future separately reviewed migration .-> Buildability[Production buildability]
```

Source evidence is never automatically promoted to mechanical truth.

## `vertical-stud-v1`

Each resolved connector has a canonical part-local coordinate, direction,
interface kind, and provenance. This version supports only vertical
stud-system connections:

- `male_stud`, direction `+Z`
- `stud_receiver`, direction `-Z`

The provenance vocabulary is `source_backed`, `trusted_family_rule`, and
`curated_verified`. In this milestone, both generated rectangular top studs
and underside receivers use `trusted_family_rule`: the top set is additionally
cross-checked against authoritative `stud.dat` source evidence where present.
The receiver set is explicitly not inferred from `stud3`/`stud4` counts.

The sole metadata source of truth is the trusted rectangular rule in
`backend/app/conversion/mechanical_connectors.py`: a part whose existing
catalogue semantics say `shape == rectangular` and family `brick` or `plate`
receives one top stud and one underside receiver at each catalogue footprint
cell. The runtime catalogue remains the input dimensions; `parts.json` does
not duplicate per-part connector arrays. This scales to ordinary rectangular
parts without a manually maintained connector list.

## Coordinates, transform, and matching

Part-local coordinates use the established lower-left footprint origin. A cell
`(x, y)` resolves at `(x + 0.5, y + 0.5)`: top studs are on the part height
plane and receivers are on the bottom plane. The existing 0/90/180/270 local
rotation transform is applied first, then `GridPosition(x, y, z)` is added.
Directions remain vertical under these rotations.

The pure matcher accepts only exact coordinate equality, opposite directions,
and the pair `male_stud` / `stud_receiver`. It deliberately has no bounding
box overlap, tolerance, clutch-force, stability, or insertion claim.

Validation rejects version mismatches, malformed/non-finite coordinates,
non-vertical directions, unsupported interface values, duplicate connectors,
and source-backed top-stud disagreement. Reports are deterministic and include
the metadata version, dimensions, counts, provenance, evidence agreement, and
ordered connector data.

## Non-trivial parts

41769, 41770, and 15068 remain mechanically `unevaluated`. Their LDraw source
evidence is preserved for diagnostics but does not create verified underside
receiver metadata. A future part-family workflow must first establish a
separate verified mechanical rule or curated verification, add deterministic
tests, and then make a separately reviewed production-buildability change.
