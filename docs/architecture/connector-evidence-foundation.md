# Connector evidence foundation

Connector evidence is a deterministic source-diagnostic layer between LDraw
geometry and any later mechanical analysis. It records the primitive instance,
full nested source path, continuous canonical location, transformed canonical
direction, feature kind, evidence status, and current mechanics compatibility.
It does not change fitting, buildability, support graphs, insertion,
instructions, public APIs, or the frontend.

## Source primitive semantics and direction

An LDraw primitive name is not a universal connector type. The extractor only
classifies the explicit checked-in primitives below and derives their direction
from the complete composed type-1 transform. A primitive's local outward axis
is LDraw `-Y`; after all parent translations, rotations, and reflections it is
reported as one of canonical `+X`, `-X`, `+Y`, `-Y`, `+Z`, or `-Z`.

| Primitive | Evidence kind | Current interpretation |
| --- | --- | --- |
| `stud.dat` | `male_stud` | Regular male-stud geometry; it is an upward top stud only when its transformed direction is `+Z`. A later SNOT source may rotate it sideways. |
| `stud4.dat` | `underside_ring_tube` | Full ring/open stud-tube geometry, retained as strong underside source evidence, not top-stud evidence. |
| `stud3.dat`, `stud3a.dat` | `underside_small_stud_tube` | Distinct small/solid underside geometry. It is not promoted automatically to a receiving connector. |
| `1-4stud4.dat`, `1-8stud4.dat`, `2-4stud4.dat`, `3-16stud4.dat` | `partial_stud_tube_geometry` | Partial source geometry only, never a complete receiving connector. |
| `stug-1x4.dat` | traversal group | Its nested `stud.dat` children carry the actual male-stud evidence. |

Source-backed geometry does not prove clutch force, tolerances, receiving
semantics, insertion feasibility, support, stability, or any other mechanical
property.

## Transform handling

For every nested LDraw reference, the extractor composes the child affine
transform with its parent: `translation = parent_translation +
parent_matrix * child_translation`; `matrix = parent_matrix * child_matrix`.
Only then does it convert the continuous point and direction through that
part's explicit `LDrawSourceFrame` to the canonical part-local frame. The
source anchor is independent from application placement rotation. No coordinate
is snapped to the rectangular stud grid.

The standard rectangular grid remains only a narrow diagnostic. Current
`stud-connectivity-v1` is potentially compatible solely with an upward
`male_stud` at a grid position on a rectangular brick/plate. Ring and small
underside evidence remain `unevaluated`; sideways or off-grid male studs are
`incompatible`; grid-aligned wedge studs remain `unevaluated` because production
mechanics deliberately does not evaluate wedges.

## Calibration diagnostics

`3001` yields eight upward `male_stud` records at `(0.5..3.5, 0.5..1.5, 3)`
with `+Z` direction. It also yields three `underside_ring_tube` records at
`(1, 1, 2.5)`, `(2, 1, 2.5)`, and `(3, 1, 2.5)`, each with `-Z` direction.
Those ring records are deliberately not reported as top studs.

For the wedge subpart, `41770a` references `s/41770as01.dat` with identity
orientation. `41769a` uses only an LDraw-X reflection. Its nested `stud4.dat`
reference has child translation `(0, 4, 20)` and child matrix
`diag(-1, -1, 1)`. The two composed results are:

| Part | Composed matrix | LDraw point | Canonical point | Direction |
| --- | --- | --- | --- | --- |
| 41770 | `diag(-1, -1, 1)` | `(0, 4, 20)` | `(3, 1, 0.5)` | `-Z` |
| 41769 | `diag(1, -1, 1)` | `(0, 4, 20)` | `(3, 1, 0.5)` | `-Z` |

Thus the previously documented `41769` point at canonical `z=1.5` was an
incorrect expectation, not an affine-composition bug. The X reflection does
not alter LDraw Y, so both full ring/tube features share the same vertical
level. The regular nested `stud.dat` rows remain at `(0.5..3.5, 0.5, 1)` for
41770 and `(0.5..3.5, 1.5, 1)` for 41769, each directed `+Z` and mechanically
unevaluated. The wedge's partial stud4/tube/lip primitives are recorded as
partial source geometry only.

`15068` yields `stud3a.dat` at `(1, 0.5, 2.5)` and `stud3.dat` at
`(1, 1.5, 3.5)`, both directed `-Z`. They are conservative
`underside_small_stud_tube` evidence, not ordinary top studs and not assumed
receivers.

## Batch generation

The extractor takes a library root, root source file, and explicit canonical
frame. It has no database or converter dependency, so the existing catalogue
and geometry generation pipeline can apply it deterministically once each
source record supplies authoritative long-axis metadata. This branch neither
batch-processes the catalogue nor persists evidence.
