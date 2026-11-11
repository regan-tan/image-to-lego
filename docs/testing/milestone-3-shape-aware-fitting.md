# Milestone 3: shape-aware fitting

## Status

This change adds an opt-in `surface-grid-v6-shape-aware` refinement after the
unchanged reliable v5 result. `surface-grid-v4` remains the default and v3,
v4, and v5 are unchanged.

## Geometry contract

`backend/app/conversion/physical_geometry.py` separates a part's body proxy
from its LDraw render mesh and connector data.  The converter coordinates are
unchanged: X/Y are studs, Z is plates, origins are lower footprint corners, and
rotations use the established 0/90/180/270-degree transform.

The physical body proxy is a deterministic centre-sampled occupancy grid at
four samples per stud in X/Y and four samples per plate in Z.  Adjacent samples
are contact, not penetration.  A collision is a shared body sample; connector
studs and receivers are excluded from this body volume because their mechanical
relationship is evaluated separately.  This is deliberately a bounded proxy,
not an assertion of exact mould geometry or volumetric IoU.

| Part | Top studs | Underside features | Verified receiver positions | Physical geometry | Production eligibility |
| --- | --- | --- | --- | --- | --- |
| Rectangular brick/plate families | Trusted family rule | Trusted family rule | Every footprint stud | Full box | Yes |
| 4286 slope | One source-observed top stud | LDraw visual evidence plus curated review | Three explicit positions: `(0.5, 0.5, 0)`, `(1.5, 0.5, 0)`, `(2.5, 0.5, 0)` | Reviewed 33-degree proxy | Yes |
| 41769 wedge | Four source-observed studs | Ring/partial-tube primitives observed | None | Mirrored polygonal plate proxy | No |
| 41770 wedge | Four source-observed studs | Ring/partial-tube primitives observed | None | Mirrored polygonal plate proxy | No |
| 15068 curved slope | No curated contract | Tube-like underside primitives observed | None | Quarter-cylinder approximation | No |

The LDraw observations for 41769, 41770, and 15068 are evidence of visual
geometry, not proof that a specific underside feature is a compatible vertical
stud receiver. Production eligibility needs a curated receiver coordinate set,
its permitted mating direction and stud type, an independently reviewed
connection configuration, and regression tests for every asserted interface.
No established family behaviour is inferred for these shapes.

The 15068 proxy is a documented fitting/collision approximation only.  Its
LDraw mesh is not treated as proof of a closed physical body, underside clutch,
or receiver geometry.

## V6 source-aware 4286 fitting

V6 starts with v5's unchanged hard cap, protected-empty-space semantics,
deterministic solver configuration, and support repair. It then generates
4286 placements only in the local neighborhoods of existing v5 rectangular
placements, across all legal rotations, and evaluates at most 64 candidates.
Existing non-rectangular placements are frozen, so a v3/v5 slope and its
repairs are not disturbed.

For each candidate, V6 removes only intersecting local rectangular body volume.
It rejects the replacement if it would touch protected source-empty cells,
overlap a frozen body, exceed the part cap, leave any final evaluated part
unsupported, or create a body collision. A candidate first needs a meaningful
cheap local silhouette gain: at least one mean-view pixel at the fixed
128-by-128 raster resolution (`1 / (3 * 128 * 128)`). Only those shortlisted
proposals run the frozen canonical `placement-surface-proxy-v1` measurement
(384 deterministic samples per surface). That guard permits at most the larger
of 0.05 mm or 1% symmetric-Chamfer drift and 0.1 mm P95 drift. These tolerances
cover bounded proxy/raster precision; they do not reward selecting a slope. A
candidate that fails either surface guard retains the incumbent v5-equivalent
model. The final model is checked again for body collisions and unsupported
evaluated placements.

This is intentionally a bounded local substitution, not a second global
CP-SAT solve. The canonical high-cost Chamfer benchmark remains a final
independent measurement, rather than a per-candidate objective.

41769, 41770, and 15068 remain mechanically unevaluated and are never emitted.
The compact diagnostics report candidate count, accepted-refinement count,
fallback reason when no candidate wins, and physical collision pair count.

## Validation and limitations

Focused tests cover 4286's verified connector contract and rotations, a
source-ramp fixture where the optimizer independently selects 4286, rejection
when it worsens source fit, support/cap/protected-space checks inherited from
v5, and physical collision behaviour. The controlled source-ramp fixture uses
the same 3-by-1-by-3 grid, source coordinates, and evaluator for both a
three-rectangle baseline and the V6 candidate. It has mean silhouette IoU
strictly higher after V6 selects one 4286; the selection is not hard-coded.
It is a unit-scale deterministic fitting demonstration, not a claim about the
eight-case benchmark.

Run locally from `backend`:

```powershell
uv run ruff check .
uv run mypy app
uv run pytest -q
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --full --algorithm surface-grid-v5-reliable --target-parts 100 --max-parts 100
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --full --algorithm surface-grid-v6-shape-aware --target-parts 100 --max-parts 100
```

The original eight-case benchmark remains required for a release-quality
comparison. Run the two commands above with the same target/grid and cap, then
record actual part count, selected 4286 count, front/side/top/mean IoU,
normalized and millimetre Chamfer, P95 error, validation outcomes, and runtime
for every case. Do not interpret an unchanged case as a regression: V6 retains
the v5 baseline when no legal source-aware candidate improves it.

### Controlled 4286 experiment

The deterministic unit fixture is a 3-by-1-by-3 33-degree triangular-prism
source. Both alternatives use that same grid, source coordinates, target count
of 3, physical scale (8 mm/stud and 3.2 mm/plate), silhouette evaluator, and
a three-part limit. V5 is represented by three adjacent 1-by-1 bricks; V6
considered both legal lengthwise 4286 rotations and selected the one at the
source location. The geometric metric used 256 samples per surface.

| Result | V5 rectangles | V6 selected 4286 |
| --- | ---: | ---: |
| Actual parts | 3 | 1 |
| 4286 count | 0 | 1 |
| Front / side / top IoU | 0.503968 / 1 / 1 | 1 / 1 / 1 |
| Mean IoU | 0.834656 | 1.0 |
| Normalized symmetric Chamfer | 0.038547 | 0 |
| Symmetric Chamfer (mm) | 1.043009 | 0 |
| P95 nearest surface (mm) | 5.516660 | 0 |
| Mechanical support | valid (grounded) | valid (grounded) |
| Body collision / protected space | none / compliant | none / compliant |

This is a deliberately small controlled positive case, not a claim that the
unmodified production v5 solver always produces three rectangles for a ramp.
It proves the new v6 selection path measures and accepts a verified slope only
when it improves agreement with the original source geometry.

## Final capped-100 fidelity audit

The final audit reran each synthetic case with `targetParts=100` and
`maxParts=100`. Individual case invocations were used because the local command
runner stops the aggregate job before it can write its final summary; all values
below come from the persisted per-case JSON records. Every v5/v6 pair has the
same source SHA-256, grid dimensions, `normalized-source-to-converter-grid-v1`
alignment, `silhouette-v1` raster setting, and `placement-surface-proxy-v1`
geometry metric. Grid units are 8 mm per X/Y stud and 3.2 mm per Z plate, so
these are controlled comparisons at the same physical scale.

`IoU`, `Chamfer`, and `P95` entries are v5 -> v6. `A/R` is accepted/rejected
4286-refinement candidates. All listed runs completed.

| Case (source SHA-256) | Grid (studs, studs, plates) | Parts | 4286 | Front / side / top / mean IoU | Symmetric Chamfer mm | P95 mm | Opening fill | Runtime s | A/R |
| --- | ---: | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: |
| box (`4fb014994c535fd9f88e01b0aec5984a00989c1efab691d71eaae0a12c1d0489`) | 9×4×15 | 64→63 | 0→1 | .825397/.700113/.670194/.731901 → .831525/.700113/.670194/.733944 | 2.628469→2.605941 | 8.008274→8.000000 | n/a | 21.277288→22.995009 | 1/63 |
| thin-wall (`119ea18d997d74b009da1b1e233f846d49bf94466f129a9e5fba35d733ebabcb`) | 11×7×6 | 34→34 | 0→1 | .753968/.714286/.775510/.747921 → .753968/.730717/.775510/.753398 | 2.062876→2.046907 | 6.4→6.4 | n/a | 15.109957→16.280586 | 1/63 |
| sphere (`f48448cdcd9e24028c6b927429f1dc9e5caf83c8079c003279a201268dda5396`) | 6×6×15 | 37→36 | 4→5 | .728280/.731012/.589220/.682837 → .728280/.719282/.602441/.683334 | 3.348598→3.261158 | 10.126494→9.780095 | n/a | 14.706998→16.045526 | 1/63 |
| cylinder (`d25f8e3e3c1d0fa604a3e312a60a8331a07b0da1cd537de1e2697d12a31f4ec6`) | 6×7×15 | 46→46 | 14→14 | unchanged: .749385/.857143/.714286/.773605 | unchanged: 3.443516 | unchanged: 10.175712 | n/a | 19.070904→20.518089 | 0/64 |
| pyramid (`474a566b10c751933ed19161b013baeaf3bd24fec9339eb1db09612beabb679b`) | 5×4×15 | 19→18 | 0→1 | .744331/.504799/.394586/.547905 → .788978/.504799/.394586/.562788 | 2.516603→2.465798 | 8.0→8.0 | n/a | 9.839260→10.314198 | 1/63 |
| l-profile (`732c0dd93d9de28fd7ed1f4aa9b6cc2546f7b559a80da50320128e865f2280c8`) | 8×4×21 | 47→47 | 0→0 | unchanged: .696280/.718065/.658226/.690857 | unchanged: 2.330835 | unchanged: 7.650305 | n/a | 17.777364→18.903335 | 0/64 |
| ring (`04e6e0dcd0f70d5bdbf7ceb1605ca0de401ccc30389cb641af5289fce4a81fa6`) | 8×8×6 | 26→26 | 0→1 | .727513/.727513/.602417/.685814 → .749708/.727513/.605411/.694211 | 2.342103→2.354005 | 6.901031→6.767722 | 923/1734 (53.2295%) → 923/1734 (53.2295%) | 12.771089→13.657609 | 1/63 |
| open-box (`7a5648f3d8e311f1c3376c497405101ff9148a963565c490b2bfc216384833d1`) | 8×5×15 | 57→57 | 0→0 | unchanged: .810658/.744331/.699798/.751596 | unchanged: 3.523285 | unchanged: 12.8 | n/a | 19.010315→21.123641 | 0/64 |

The part quantities are recorded in the benchmark JSON. Apart from 4286, v6
keeps the v5 palette and rectangular catalogue; each accepted substitution
removes only local rectangular parts. The box replacement removes one 3005 and
one 3023 and adds one 4286. The other 4286 deltas are thin-wall +1, sphere
4→5, pyramid +1, and ring +1; cylinder's 14 existing 4286 parts are unchanged.
No 41769, 41770, or 15068 is selected.

### Box regression investigation

The earlier v6 record accepted a 4286 substitution solely because mean IoU rose
from .731901 to .736076. Its symmetric Chamfer worsened from 2.628469 mm to
2.700512 mm (+2.74%) and P95 worsened from 8.008274 mm to 8.096295 mm. The
source hash, 9×4×15 grid, physical scale, alignment, and metric versions match,
so this was a real silhouette-versus-surface trade-off caused by the
silhouette-only acceptance rule—not a coordinate mismatch or a change to the
frozen metric. The combined policy rejects that proposal. It instead selects a
different legal substitution whose box result is .733944 mean IoU, 2.605941 mm
Chamfer, and 8.0 mm P95; it improves all reported fidelity measures.

### Opening, mechanical, and serialization evidence

Ring is the only source with an enclosed top-view opening. Its fill remains
923 of 1,734 pixels (53.2295%) in both versions: the mean-IoU increase does not
claim an opening-preservation improvement. All v6 cases stay at or below 100
parts. The persisted diagnostics show zero physical body-collision pairs; the
final converter also fails rather than serializes a model with any unsupported
evaluated placement, and records that count as zero after its final check.
Protected source-empty-cell counts are preserved by
the existing per-proposal protected-space check (box/thin-wall 0, sphere 204,
cylinder 112, pyramid 136, l-profile 224, ring 96, open-box 0). Serialization
is covered by the v6 regression test using the canonical model serializer.

The remaining limitation is unchanged: 41769, 41770, and 15068 have visual or
proxy evidence only and no reviewed receiver/mechanical contract, so production
fitting never emits them.
