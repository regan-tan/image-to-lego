# Milestone 4: opening and connectivity diagnostics

## Final decision

This document preserves an experimental feasibility investigation. The V7
opening-optimization route was removed: it did not demonstrate an acceptable
improvement at the established 8x8x6 physical scale. `surface-grid-v4` remains
the production default; V3 through V6 are unchanged. The retained opening and
connectivity work is offline benchmark diagnostic infrastructure only, and does
not alter conversion routing or claim that the converter fixes the ring opening.

The V7 hard-protection and soft-overlap descriptions below are historical
experiments, not available production algorithms.

## Historical Phase 3: connectivity-aware opening optimization

### Matched ring evidence

The controlled source SHA is
`04e6e0dcd0f70d5bdbf7ceb1605ca0de401ccc30389cb641af5289fce4a81fa6`, at
`targetParts=100`, `maxParts=100`, Y-up, 8x8x6 grid, the existing 128-pixel
silhouette evaluator, and the same physical scale.

| Strategy | Parts | Opening fill | Mean / top IoU | Components / largest fraction | Isolated / unsupported | Result |
| --- | ---: | --- | --- | --- | --- | --- |
| V6 incumbent | 26 | 923/1,734 | .694211 / .605411 | 6 / .538462 | 2 / 0 | final baseline |
| Historical hard exclusion | 19 | 9/1,734 | .693125 / .624349 | 7 / .263158 | 1 / 0 | rejected: fragmented graph |
| Central-mask diagnostic | 26 | 923/1,734 | .685814 / .602417 | 6 / .576923 | 3 / 0 | rejected: no opening gain, IoU regression |
| Soft overlap preference | 32 | 923/1,734 | .685814 / .602417 | 7 / .250000 | 0 / 0 | rejected: no opening gain, fidelity and graph regression |

The V6 baseline also has Chamfer 2.354005 mm and P95 6.767722 mm. The soft
candidate has Chamfer 2.144844 mm and P95 6.520934 mm, but those improvements
cannot compensate for no opening reduction, the IoU regression, or the worse
component graph. All alternatives respected the hard cap, physical body proxy,
and protected 3D source-empty space.

### Connector graph interpretation

`stud-connectivity-v1` uses only exact vertical top-stud/underside-receiver
matches for mechanically verified rectangular pieces. V6's six components are
genuine separate direct-stud subassemblies from the ring's sampled elevated
strips; it is not a claimed single assembly. Its largest 14-piece group lies in
the connected south/east run, and two placements have no verified neighbour.
The historic hard candidate removes aperture-adjacent base rectangles that
served as the only vertical support path for upper strips, yielding seven groups
with a five-piece maximum. The soft candidate likewise has seven groups with a
maximum of eight. Ground contact and body adjacency are not substituted for a
connector; no side-clutch interface is inferred.

Within this 8x8 target volume, a legal bridge would need to lie outside the
source-confirmed 3D empty cells while matching receiver/stud coordinates on
both sides. The available rectangle vocabulary supplies no such bridge without
covering the aperture or replacing supported source structure. One to three
microcell erosions retain the same nine LEGO-cell footprints; four erase
effective protection. The central-mask diagnostic confirms that relaxing the
mask restores the baseline aperture fill rather than producing an intermediate
solution.

Final acceptance additionally compares largest-component fraction and isolated
placements, alongside the original strict component count and absolute-largest
component checks. This strengthens rather than replaces the existing policy.
The final V7 ring output therefore remains the V6 model and serializes its
unchanged final metrics; metadata retains the rejected candidate diagnostics.

## Milestone 4 feasibility investigation

This is a bounded investigation, not an exhaustive proof. It uses the original
watertight synthetic ring (SHA-256
`04e6e0dcd0f70d5bdbf7ceb1605ca0de401ccc30389cb641af5289fce4a81fa6`),
Y-up, the existing verified rectangular/4286 catalogue, `silhouette-v1` at
128 pixels, `placement-surface-proxy-v1`, 8 mm horizontal studs, and 3.2 mm
plate height. No benchmark arrangement was copied into production conversion.

### Connected-ring feasibility

The following are the bounded arrangements actually evaluated. “Protected” is
the number of V5 protected-source-empty-space violations, not the number of
protected cells. A zero does not claim overall structural stability or
buildability beyond `stud-connectivity-v1`.

| Arrangement | Grid | Parts | Opening fill | Front / side / top / mean IoU | Chamfer / P95 mm | Components / largest fraction | Isolated / unsupported | Collisions / protected |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| V6 incumbent | 8x8x6 | 26 | 923/1,734 (53.2295%) | .749708 / .727513 / .605411 / .694211 | 2.354005 / 6.767722 | 6 / .538462 | 2 / 0 | 0 / 0 |
| Historical hard-exclusion candidate | 8x8x6 | 19 | 9/1,734 (.5190%) | .727513 / .727513 / .624349 / .693125 | 2.362569 / 7.501439 | 7 / .263158 | 1 / 0 | 0 / 0 |
| Current soft-overlap candidate | 8x8x6 | 32 | 923/1,734 (53.2295%) | .727513 / .727513 / .602417 / .685814 | 2.144844 / 6.520934 | 7 / .250000 | 0 / 0 | 0 / 0 |

The historic 19-part candidate demonstrates that low projected fill is
representable by the current catalogue. It is not a valid improved connected
ring: compared with V6 it adds a component and reduces the largest verified
component from 14 placements to five. The current soft candidate provides no
opening improvement and also regresses the connector graph. Therefore no
valid arrangement with substantially lower fill than V6 was found in the
bounded 8x8 search. This is not an impossibility claim: no complete
fixed-grid enumeration with a correctly specified connectivity condition was
performed.

The result points to two concrete limits in the current path:

- Candidate generation admits only rectangular placements in the V5 target
  volume (plus already locked 4286 slopes). The other advanced parts remain
  ineligible because their underside receiver contracts are unverified.
- CP-SAT maximizes projection coverage, then minimizes the configured
  secondary cost and part count. Its support-reachability filter and repair
  pass prevent unsupported placements, but neither encodes connector edges,
  component count, nor largest-component size. The completed graph is only
  assessed after selection. V6 additionally examines at most 64 local 4286
  substitutions, so it does not search an expanded ring vocabulary globally.

### Resolution probes and physical-scale limitation

The converter can select larger grids only by changing `targetParts`; when a
hard cap is supplied, V5/V6 deliberately select the grid from
`min(targetParts, maxParts / 4)`. Actual output count remains an outcome of
the coverage solve, not a promise. The bounded probes below use the same
evaluator settings and standard LEGO cell dimensions. They show what the
currently supported selector produces, including all required diagnostics.

| Requested target / cap | Selected grid | Actual parts | Opening fill | Front / side / top / mean IoU | Chamfer / P95 mm | Components / largest fraction | Isolated / unsupported | Collisions / protected |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| 100 / 100 | 8x8x6 | 26 | 923/1,734 (53.2295%) | .749708 / .727513 / .605411 / .694211 | 2.354005 / 6.767722 | 6 / .538462 | 2 / 0 | 0 / 0 |
| 144 / 144 | 9x9x6 | 37 | 1,071/1,778 (60.2362%) | .740741 / .753701 / .594029 / .696157 | 2.218340 / 6.675394 | 7 / .378378 | 3 / 0 | 0 / 0 |
| 200 / 200 | 13x13x6 | 65 | 756/1,943 (38.9089%) | .767196 / .767196 / .693312 / .742568 | 2.464869 / 6.420413 | 18 / .292308 | 7 / 0 | 0 / 0 |
| 150 / no cap | 19x19x9 | 401 | 617/2,036 (30.3045%) | .839506 / .839506 / .760614 / .813209 | 3.338663 / 9.600000 | 14 / .950125 | 9 / 0 | 0 / 0 |

These probes are **not** a controlled fixed-physical-dimensions resolution
study. The existing selector normalizes the source to the chosen grid before
the 8 mm/3.2 mm conversion. Consequently the aligned source diagonal changes
from 80.796 mm at 8x8x6 to 136.704 mm at 13x13x6 and 205.250 mm at 19x19x9.
Rescaling either output to hide that difference would make a stud nonstandard
and would violate the established physical scale. The 13x13 and 19x19 values
therefore demonstrate a discretization/size trade-off, not that higher
resolution solves the original fixed-size ring. They cannot support an
algorithmic improvement claim.

Within that limitation, coarse sampling is plausibly one contributor: 13x13
reduces fill and improves silhouette agreement, while 19x19 has a much larger
verified component fraction. It is not the sole demonstrated cause of the
conflict, because the 13x13 result is more fragmented than V6 and the 9x9
result is worse on fill. A fixed-footprint study is required before changing
production grid selection.

### Smallest connectivity-aware construction change

The smallest credible CP-SAT experiment is not a global connectivity solver.
For each pair of candidate rectangles with a verified matching vertical
stud/receiver interface, introduce a Boolean “selected connection” variable
linked to both placement variables. After projection coverage is fixed, use
the number of selected verified connections as a bounded secondary objective
or an acceptance threshold before part count. This would reward retaining
support bridges during selection. It still would not prove one component,
stability, side clutch, or insertion feasibility, so the existing final
analysis remains necessary. No such change is implemented because the
fixed-size feasibility evidence does not yet justify adding solver complexity.

### V7 retention review

| Current V7 element | Assessment | Impact of retaining it |
| --- | --- | --- |
| Candidate-versus-final assessment | Reusable diagnostic | Makes a rejected experimental candidate auditable without misrepresenting the returned V6 model. |
| Source-derived opening mask and overlap measurement | Reusable offline diagnostic | Locates and quantifies the failure; it is not evidence that an opening constraint improves output. |
| `stud-connectivity-v1` analysis | Reusable safety diagnostic | Correctly rejects graph regressions, but remains a limited vertical-connection analysis. |
| Soft opening preference | Experimental and not currently beneficial | It produced no accepted ring improvement; do not add another penalty variation. |
| V7 routing and fallback | Safe containment for the experiment | It keeps the opt-in route deterministic and returns V6 when acceptance fails; retaining it does not improve production geometry. |

The failed V7 production routing, solver preference, API selection, worker
serialization, CLI selection, and experimental runtime tests were removed.
The retained implementation is the offline benchmark record's compact
`stud-connectivity-v1` component, largest-fraction, isolation, and
unsupported-placement summary, plus source-projection opening diagnostics.
These measurements do not change production conversion output.

### Conclusion and next milestone

**Recommendation: D — stop the current opening-optimization approach.** No
viable improvement has been demonstrated at the established 8x8x6 physical
scale, and the larger-grid results confound resolution with model footprint.
Candidate generation and the optimizer remain possible contributors, but the
current evidence does not warrant another V7 penalty, a global connectivity
solver, or enabling mechanically unverified parts.

The next milestone should be **connectivity-aware LEGO optimization**, preceded
by a fixed-footprint offline feasibility harness. It must preserve the baseline
ring's physical dimensions while comparing candidate discretizations with
standard LEGO dimensions explicitly accounted for. Do not promote a resolution
or connectivity solver change to production without evidence of lower opening
fill while retaining fidelity and the baseline connectivity measures.

**Final Phase 3 decision - D. No viable current improvement:** at the
established grid/physical scale and verified vocabulary, no candidate improves
the opening while preserving the baseline's direct-stud graph and fidelity.

## Status

V7 was removed after this investigation. The production default remains
`surface-grid-v4`; V3 through V6 are unchanged. This document retains the
historical evidence only; current benchmark diagnostics do not run a candidate
solver or select an opening-preservation algorithm.

## Architecture assessment

V5 supplies the safe hard-cap, protected-empty-cell, CP-SAT, and support-repair baseline. V6 adds
a bounded 4286 replacement pass with physical-body and source-fidelity checks. The observed ring
failure was not a V5 protected-cell violation: a rectangular candidate can respect every coarse
3D protected cell yet cover a sub-stud portion of the top-view aperture. This is a projection and
resolution mismatch, not evidence that the existing 3D protection is broken.

V7 derives a separate four-by-four-per-stud XY mask only for a watertight source. It rasterizes the
source's projected triangles, flood-fills exterior empty samples with four-neighbour connectivity,
and treats only the remaining enclosed samples as an opening. The current experiment measures a
candidate's overlap with those samples as a bounded secondary preference; it does not remove the
candidate before CP-SAT. The rule does not claim that a general 2D void is empty at every Z level,
and it is disabled for non-watertight sources.

V7 compares that candidate with the unchanged V6 result. It retains the candidate only when it
frees at least one canonical opening pixel, does not reduce top IoU, loses at most 0.002 mean IoU
(0.2 percentage points), adds at most 1% Chamfer, and adds at most 1.0 mm P95 error (less than a
single 3.2 mm plate). It must also not increase the existing evaluator's direct-stud connected
component count or reduce its largest component. Otherwise V7 returns the verified V6 baseline.
The extra conversion is bounded; it replaces neither the solver's deterministic work limits nor the
final support/collision checks.

## Mechanical evidence matrix

| Part | Geometry | Verified top interface | Verified underside interface | Fitter eligible | Reason |
| --- | --- | --- | --- | --- | --- |
| 4286 | Reviewed slope proxy and render asset | Source-backed, curated metadata | Three curated receivers | Yes | Existing V6 contract |
| 41769 | Mirrored polygonal plate proxy and render asset | Four source-observed studs | No | No | LDraw rings/tubes do not prove receiver compatibility |
| 41770 | Mirrored polygonal plate proxy and render asset | Four source-observed studs | No | No | LDraw rings/tubes do not prove receiver compatibility |
| 15068 | Quarter-cylinder fitting proxy and render asset | No curated contract | No | No | Tube-like visual features are not a receiver contract |

The source provenance is the checked-in LDraw hierarchy parsed by `connector_evidence.py`; no new
connector metadata has been asserted from that visual source. As a result V7's serialized
diagnostics explicitly list all three advanced IDs as excluded, and no production conversion emits
them.

## Controlled ring result

Matched local runs used `targetParts=100`, `maxParts=100`, the same source hash
`04e6e0dcd0f70d5bdbf7ceb1605ca0de401ccc30389cb641af5289fce4a81fa6`, 8x8x6 grid, and the
unchanged `silhouette-v1` and `placement-surface-proxy-v1` evaluators.

| Case | V6 mean IoU | V7 mean IoU | V6 Chamfer mm | V7 Chamfer mm | V6/V7 opening fill | V7 parts |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| Ring | 0.694211 | 0.694211 | 2.354005 | 2.354005 | 923/1,734 (53.2295%) -> 923/1,734 (53.2295%) | 26 |

The initial projected-opening candidate produced 9/1,734 filled opening pixels and top IoU
0.624349, but it reduced the 26-part V6 assembly to 19 parts. The evaluator then found seven
direct-stud connected components with largest size five, compared with V6's six components and
largest size fourteen. Although both had zero unsupported placements and zero body collisions, this
is a material connectivity regression. V7 now rejects that candidate and returns the V6 result.
Its metadata records the rejected candidate's 120 opening microcells and 680 filtered candidates,
but marks final projected-opening protection disabled so it never claims protection that the
returned model does not satisfy.

### Exact candidate acceptance audit

The 9/1,734 result is reproducible as the complete V5-derived, opening-aware proposed model, not
as a stale metric or a different fixture. It uses the same ring hash, Y-up conversion, 8x8x6 grid,
8 mm/3.2 mm physical scale, `silhouette-v1` 128-pixel raster, and
`placement-surface-proxy-v1` evaluator as the V6 incumbent and final V7 record.

The V6 incumbent has 26 parts: `3002x1, 3005x3, 3010x2, 3020x2, 3021x1, 3022x1, 3023x4,
3024x1, 3622x3, 3623x3, 3710x4, 4286x1`. The proposed 19-part opening candidate has
`3001x2, 3002x1, 3005x4, 3010x3, 3020x1, 3021x1, 3023x3, 3622x1, 3623x2, 3710x1`.

| Acceptance predicate | Candidate | Incumbent | Threshold | Result |
| --- | --- | --- | --- | --- |
| Source-confirmed projected opening | true | n/a | true | Pass |
| Matching conversion grid | 8x8x6 | 8x8x6 | exact match | Pass |
| Opening fill | 9 | 923 | reduce by at least 1 pixel | Pass |
| Top IoU | .624349 | .605411 | >= incumbent | Pass |
| Mean IoU | .693125 | .694211 | >= .692211 | Pass |
| Unsupported evaluated placements | 0 | 0 | <= incumbent | Pass |
| Evaluated component count | 7 | 6 | <= incumbent | **Fail** |
| Largest evaluated component | 5 | 14 | >= incumbent | **Fail** |
| Protected source-empty space | true | n/a | true | Pass |
| Physical body collisions | true | n/a | true | Pass |
| Hard part cap | 19 | n/a | <= 100 | Pass |
| Surface measurement | available | available | both available | Pass |
| Symmetric Chamfer mm | 2.362569 | 2.354005 | <= 2.377545 | Pass |
| P95 mm | 7.501439 | 6.767722 | <= 7.767722 | Pass |

The final V7 diagnostic now stores every check and names only the actual failures:
`evaluated_component_count, largest_evaluated_component`. The final artifact separately records
that an opening candidate was attempted but not accepted; its opening ratio and part quantities
remain those of the V6 fallback.

The full eight-case V6-versus-V7 benchmark was run after this correction. Every case, including the
ring, has identical final V6/V7 geometry and metrics because V7 has no safely accepted candidate.
V7's additional V6 comparison falls back unchanged for a source without an applicable opening or
when the bounded quality policy does not accept the opening-aware candidate.

### Rejected ring-candidate mask audit

The audit uses the same canonical 128x128 top source mask and projection bounds for V6 and the
opening-aware candidate. The source foreground has 7,596 pixels in both runs.

| Output | LEGO foreground | True positive | False positive | False negative | Intersection | Union | Opening filled | Top IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| V6 baseline | 11,807 | 7,317 | 4,490 | 279 | 7,317 | 12,086 | 923/1,734 (53.2295%) | 0.605411 |
| Rejected opening candidate | 10,816 | 7,077 | 3,739 | 519 | 7,077 | 11,335 | 9/1,734 (0.5190%) | 0.624349 |

The candidate removes 1,216 V6 foreground pixels and adds 225. Of the removed pixels, 914 are
false positives in the source-confirmed opening, but 302 are legitimate source-overlap pixels;
only 62 true-positive pixels are added elsewhere. The union therefore falls by 751 pixels while
the intersection falls by 240, which explains the modest IoU increase despite the large aperture
change. The local artifact
`artifacts/m4-v7-capped100-full/cases/ring/v6_to_rejected_opening_candidate_top_difference.png`
shows the removed region in magenta and additions in blue. This proves that the candidate removed
some legitimate ring structure as well as aperture fill; the connectivity guard correctly rejects it.

Successive one-, two-, and three-microcell erosions left the same nine LEGO-cell footprints under
protection and produced the same rejected 19-part candidate. A fourth erosion reduced protection to
one LEGO cell but filtered zero candidates, restoring the filled aperture. This establishes a
current grid-vocabulary limitation rather than evidence that the 680 original rejections are all
spurious. No narrower source-derived mask produced a safe final improvement, so V7 keeps V6.

The returned V6/V7 ring model is nonempty (26 parts), has zero unsupported evaluated placements,
zero body-proxy collision pairs, zero V5 protected-empty-space violations, and serializes as the
canonical JSON format using only verified part/color pairs. It remains a visible surrounding ring,
but its existing `stud-connectivity-v1` report has six direct-stud components, largest size 14, and
two isolated placements. That analysis does not prove global connectivity, stability, clutch
strength, collision-free assembly motion, or a single physically stable build. V7 does not present
that incomplete baseline diagnostic as full mechanical validation.

### Eight-case final comparison

All runs used the same fixture version, source hash per row, selected grid, Y-up axis, 100 target
parts, 100 maximum parts, alignment, 128-pixel silhouette raster, and
`placement-surface-proxy-v1` geometry metric. V7 equals V6 in every final value below; runtime is
environment-dependent.

| Case | Grid | Parts | Front / side / top IoU | Mean IoU | Chamfer mm | Normalized Chamfer | P95 mm | Opening fill | V6 / V7 runtime s |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| Box | 9x4x15 | 63 | .831525/.700113/.670194 | .733944 | 2.605941 | .031887 | 8.000000 | n/a | 23.156960 / 22.589698 |
| Thin wall | 11x7x6 | 34 | .753968/.730717/.775510 | .753398 | 2.046907 | .021624 | 6.400000 | n/a | 16.295747 / 15.782519 |
| Sphere | 6x6x15 | 36 | .728280/.719282/.602441 | .683334 | 3.261158 | .045194 | 9.780095 | n/a | 15.523227 / 15.332277 |
| Cylinder | 6x7x15 | 46 | .749385/.857143/.714286 | .773605 | 3.443516 | .044789 | 10.175712 | n/a | 19.389702 / 19.191192 |
| Pyramid | 5x4x15 | 18 | .788978/.504799/.394586 | .562788 | 2.465798 | .041057 | 8.000000 | n/a | 9.499439 / 9.463007 |
| L-profile | 8x4x21 | 47 | .696280/.718065/.658226 | .690857 | 2.330835 | .026378 | 7.650305 | n/a | 17.805014 / 17.717816 |
| Ring | 8x8x6 | 26 | .749708/.727513/.605411 | .694211 | 2.354005 | .029135 | 6.767722 | .532295 | 12.103253 / 29.948004 |
| Open box | 8x5x15 | 57 | .810658/.744331/.699798 | .751596 | 3.523285 | .044865 | 12.800000 | n/a | 19.064108 / 18.632334 |

## Reproduction

From `backend`:

```powershell
uv run ruff check .
uv run mypy app
uv run pytest -q --tb=short
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --case ring --algorithm surface-grid-v6-shape-aware --target-parts 100 --max-parts 100 --output-dir ../artifacts/m4-v6-capped100
```

The generated artifacts are local and gitignored. The historical V7 comparison
command is intentionally not reproducible through the production CLI because
that algorithm was removed.

## Validation status

The historical V6/V7 comparison was run fixture by fixture because the aggregate
command exceeded that environment's reporting window. Its outputs are evidence
for the removal decision, not current validation of a production algorithm. The
retained benchmark and diagnostics tests should be run with the commands above.
Ruff and mypy passed during the historical investigation. A complete `uv run pytest -q --tb=short` was attempted; it
reached 26% in this environment without a terminal result, so it is not reported as passing.

Run locally from Windows CMD or PowerShell:

```cmd
cd backend
uv run pytest -q --tb=short
```

## Remaining blockers

Wedge 41769/41770 and curved slope 15068 require independently reviewed, exact underside receiver
coordinates, permitted mating direction, and regression-tested mechanical contracts. Their current
render meshes, physical proxies, and LDraw primitive observations are useful geometry evidence but
are insufficient for production eligibility. Curved-slope output also remains blocked until the
canonical fidelity evaluator and frontend use a reviewed curved exterior surface representation.

## Final assessment

**V7 has a specific fidelity and structural issue requiring correction before it can claim an
opening-preservation improvement.** The unsafe candidate is now rejected and V7 safely preserves
V6 output, but no structurally acceptable opening-aware candidate has been demonstrated. The
advanced-part milestone remains partially complete because 41769, 41770, and 15068 are still
mechanically unverified.
