# Milestone 12A: Verified Nonrectangular Part Mechanics

## Decision

**GO for a controlled offline M12B experiment only.** The exact checked-in
`41769a` variant now has five independently located underside receivers that
are compatible with ordinary vertical studs. This is not production catalogue
admission: V4--V7 remain unchanged, and the evidence does not establish clutch
force, stability, insertion accessibility, or a general nonrectangular rule.

## Selected family and provenance

`41769a`, *Wing 2 x 4 Right without Chamfer*, is the exact selected variant.
The catalogue's `41769` record, geometry asset, and source-frame registry all
reference `41769a`; they do not reference `41769b`. The checked-in root has
the same title and its history records the 2026 rename. LDraw's May 2026
release separately lists `41769a` (without chamfer) and `41769b` (with
chamfer). The local geometry is therefore **not** silently treated as the
chamfered variant.

`15068` was the one alternative reviewed; its existing representation is an
explicitly non-authoritative quarter-cylinder proxy, so it remains excluded.
`41770` is the mirror wedge and is not included in this one-ID experiment.

The checked-in LDraw source [`part_geometry/ldraw_source/parts/41769a.dat`](../../part_geometry/ldraw_source/parts/41769a.dat)
identifies the part, its BrickLink keyword, and the referenced source tree. The
render asset [`backend/app/conversion/part_geometry_assets/41769.json`](../../backend/app/conversion/part_geometry_assets/41769.json)
pins that source as `parts/41769a.dat` with SHA-256
`0b069ab042f2cc8297a52e76b49a06e504cd4e9a51f02d6aea8c63f686c28ff8`.
The source's four `stud.dat` instances resolve to local coordinates
`(0.5, 1.5, 1)`, `(1.5, 1.5, 1)`, `(2.5, 1.5, 1)`, and `(3.5, 1.5, 1)`.

## Follow-up connection evidence

The inspection used four separate evidence classes.

| Source | What it establishes | What it does not establish |
| --- | --- | --- |
| Official LDraw `41769a.dat` and recursive `s/41770as01.dat` | Exact without-chamfer source tree, mirrored inheritance, `stud4`/partial-tube/lip geometry, and local coordinate transform. | Receiver locations or clutch force by primitive name alone. |
| LDCad Shadow Library commit `9b1131fb1991f8c0bfc072325e4e12f6271aba35` | Its inherited `s/41770as01.dat` metadata declares female `SNAP_CYL` holes. Its documented grid semantics expand the first record to four receivers. | Manufacturer certification, structural stability, or insertion feasibility. |
| Existing rectangular brick/plate mechanics | A standard male stud/receiver uses half-stud horizontal centres and mating bottom/top planes. | That every visible wedge recess is a receiver. |
| BrickLink and LDraw catalogue pages | `41769` identity, 4 x 2 nominal envelope, and the two LDraw variants. | A mechanical connection specification; photographs/catalogue art were not used as connection proof. |

The two LDCad records are `gender=F`, `caps=one`, `secs=R 6 4`. One has
`pos=-10 8 0` and `grid=1 C 4 0 20`; its grid expands to four holes. The other
has `pos=10 8 30`. `41769a` reflects the shared subpart in LDraw X. Applying
that source transform and the existing canonical source frame yields these
bottom-plane receivers in local stud/plate units:

`(0.5, 1.5, 0)`, `(1.5, 1.5, 0)`, `(2.5, 1.5, 0)`,
`(3.5, 1.5, 0)`, and `(3.5, 0.5, 0)`.

These coordinates are all standard stud centres. They are accepted solely as
a five-coordinate, `41769a`-specific `stud_receiver` contract with curated
provenance. The LDCad documentation defines female cylinders as holes and the
shape data used to calculate matching pairs; the official LDraw source provides
the corresponding inherited underside geometry. This is stronger than visual
bounding-box inference, but remains narrower than a claim of full physical
certification.

## Coordinates, dimensions, and orientations

Coordinates are application-local: `x` follows the four-stud length, `y` the
two-stud width, and `z` rises in plate units. World placement adds integer grid
coordinates after the established clockwise quarter-turn transform. A stud is
8 mm and a plate is 3.2 mm. The body envelope is one plate high; top-stud
connection coordinates are at `z = 1` plate.

Only 0, 90, 180, and 270 degrees are supported. Negative grid positions and
all other rotations are rejected. The exterior envelope footprint is the
checked-in nonrectangular polygon `(0,0) -> (4,0) -> (4,1) -> (0,2)`,
transformed using the existing wedge coordinate convention. It conservatively
contains the source mesh's chamfered details rather than claiming them as
occupied material.

## Collision implementation and limits

`m12a_wedge_mechanics.py` clips the transformed convex exterior polygons and
requires positive XY intersection area plus overlapping open Z intervals. Thus
touching faces are not collisions and the 4 x 2 bounding box is never used as
collision proof.

The occupied volume is a conservative exterior wedge prism. The hollow
underside remains occupied, so it may produce false positives but cannot admit
an intersection through an unverified cavity. Studs are handled only through
the explicit mating rule. This bounded representation has an XY boundary error
of zero relative to the recorded polygon, and a deliberate conservative error
equal to the unmodelled interior void; no configuration requiring that void is
accepted.

The continuous point fixture `(0.25, 1.99, 0.5)` is inside the rectangular
bounding box but outside the wedge, while `(3.5, 0.5, 0.5)` is inside the body.
Rotating the wedge 180 degrees changes the latter relation for `(3.5, 0.05,
0.5)`. Legal placements remain integral, so no sub-stud translation is exposed
to the experimental interface.

## Contacts, support, and connectivity

The four top studs are source-backed and match existing rectangular
brick/plate underside receivers exactly after transformation. A wedge at `z=0`
has ground support. A rectangular part directly above it is supported and
connected only when at least one source-backed top stud exactly matches a
verified receiver. A nearby plate without an exact match creates no edge.
`validate_assembly()` additionally rejects body collisions and every
rectangular part without such an edge, so a disconnected experimental assembly
cannot be accepted accidentally.

The wedge may now be directly supported above a rectangular brick or plate
only at one or more of those five receivers. Receiver coordinates transform
under all four existing quarter turns without rounding. A lower stud at any
other position creates neither support nor connectivity. Slopes and other
nonrectangular parts remain rejected. Collision, direct support, and
connectivity are intentionally separate; this does not certify clutch force,
lateral bracing, insertion motion, centre of mass, or full structural
stability.

## Fixtures and results

`backend/tests/test_m12a_wedge_mechanics.py` independently fixes expected
coordinates and known geometry relations rather than generating expected values
from the test subject. It covers all four orientations, nonrectangular
projection area, the bounding-box counterexample, a solid collision, rotation,
valid and invalid top-stud contacts, grounded and unsupported wedges,
disconnected assemblies, and invalid coordinates/orientations. The follow-up
adds an independently fixed 1 x 1 plate -> wedge attachment, non-receiver
rejection, harmless contact at the body boundary, and fixed receiver transform
fixtures for orientations 0 and 90. The existing mechanical connector
regressions remain included in the focused run.

Run from `backend`:

```cmd
.venv\Scripts\python.exe -m pytest tests/test_m12a_wedge_mechanics.py tests/test_mechanical_connectors.py tests/test_physical_geometry.py -q
.venv\Scripts\python.exe -m ruff check app/conversion/m12a_wedge_mechanics.py tests/test_m12a_wedge_mechanics.py
.venv\Scripts\python.exe -m mypy app/conversion/m12a_wedge_mechanics.py
.venv\Scripts\python.exe -m ruff format --check app/conversion/m12a_wedge_mechanics.py tests/test_m12a_wedge_mechanics.py
git diff --check
```

The focused suite completed successfully with 57 tests in 1.36 seconds in this
workspace. No external service, private source, production database, or paid
provider was contacted by the automated tests.

## Projection, export, and production isolation

`projection_polygon()` is deterministic and supplies the same transformed
exterior used by collision detection. Mechanical adjacency is deterministic by
placement index. No production export is produced: current export does not
represent this experimental part, so the module intentionally offers no route
to it.

New files are:

- `backend/app/conversion/m12a_wedge_mechanics.py`
- `backend/tests/test_m12a_wedge_mechanics.py`
- `docs/testing/milestone-12a-verified-part-mechanics-results.md`

The new module is not imported by `convert_glb()`, V4--V7, public catalogue
selection, API schemas, workers, frontend code, or export routing. The
catalogue's `fitterEnabled` flag remains unchanged.

## Remaining limitations

The contract applies only to `41769a`, not `41769b`, `41770`, or any family
rule. It accepts only vertical standard-stud contacts at the five listed
coordinates and continues to use a conservative body envelope. It does not
prove clutch force, physical stability, free insertion paths, exact mould-wall
clearance, or compatibility with slopes/nonrectangular parts.

M12B may use this part only in an offline, bounded experiment that preserves
these constraints. Production admission requires a separate reviewed decision,
broader collision/export evidence, and validation appropriate to the intended
claim.
