# Milestone 13C: Offline Silhouette Equivalence and Candidate-Space Audit

## Status

**M13C completed: Stage A PASS and Stage B PASS for Duck, Mansion, and Realistic man.**
M13C is an offline diagnostic only. It does not modify V4--V7, the frozen
`silhouette-v1` evaluator, the catalogue, API, workers, frontend, or exporters,
and it does not invoke a CP-SAT optimization solve.

The historical M12C and M13B NO-GO findings remain unchanged. Equal M13B
TP/FP/FN, proxy scores, and aggregate IoUs are not evidence that the Control
and IoU-proxy LEGO pixel masks are identical.

## Research question and hypotheses

M13C asks whether different mechanically accepted M13B assemblies create
identical three-view projected silhouettes, and whether the approved M13B
candidate space itself places a ceiling on fixed-frame source coverage.

The Stage A hypotheses are deliberately distinguishable:

1. Identical placement multisets produce identical masks.
2. Distinct placement multisets can produce identical projected masks.
3. Distinct masks can still have equal TP/FP/FN counts against one source.

Three-view equality is only projection equality. It does not establish full
3D geometry, connectivity, stability, clutch strength, or buildability equivalence.

## Frozen evidence and provenance

The runner accepts the SHA-pinned M7B manifest and exactly these completed,
private M13B summary files:

- `artifacts/m13b-duck-final/summary.json`
- `artifacts/m13b-mansion-pilot/summary.json`
- `artifacts/m13b-man-final/summary.json`

It verifies every source GLB against both the manifest hash and the M13B record
before loading its mesh. Ordered placement IDs encode part ID, integer position,
and orientation. Reconstruction resolves each part only through the authoritative
checked-in catalogue; an unknown part, malformed ID, source digest discrepancy,
unequal M13B shared bounds, or incompatible frame fails safely.

## Reconstruction and parity gate

For each arm, M13C reconstructs placements without solver calls and regenerates
the M13B aligned source transform plus fixed 1x target frame. It requires exact
integer parity for fixed-frame TP/FP/FN, ordered placement identity, and part
count. It also compares established rounded native `silhouette-v1` and saved
explicit shared-frame metrics.

Only if both arms pass does the runner compare A and B. A parity failure writes
diagnostics, marks Stage A `FAIL`, returns non-zero, and omits the cross-arm claim.

### Stage A parity correction

The first private Stage A attempt reconstructed all six M13B assemblies with
matching source hashes, placement IDs, part counts, and fixed-frame metrics,
but incorrectly failed frozen and shared metrics. The defect was a
whole-dictionary comparison between schemas with different presentation fields:
M13B frozen records include `source_equals_lego`, while M13C's former
reconstruction omitted it; M13B shared records include `frame` and `bounds`,
while M13C's former comparison omitted them.

M13C now normalizes only those known representations and strictly checks every
meaningful field. Frozen parity requires per-view TP/FP/FN, six-decimal IoU,
per-view equality flags, mean IoU, and aggregate equality. Shared parity
requires per-view TP/FP/FN and IoU, `shared-explicit` frame identity, and all
three full bounds. A failure records exact field-level expected-versus-actual
diagnostics; missing metadata still fails closed.

## Exact mask comparison

The shared comparison uses M13B's recorded source-plus-both-arrangements bounds
and frozen 128 by 128 semantics: front X--Z, side Y--Z, top X--Y, original
source triangles, and actual rectangular/slope geometry. M13B has no wedges.
Every view records source, Control, and experiment SHA-256; XOR; A-only/B-only
counts; intersection; union; Jaccard; exact equality; and bounds/resolution.
The source masks must be byte-identical in that shared frame.

The private output includes `summary.json` plus an explicit draft-2020-12
`schema.json` describing its required Stage A provenance, parity, placement,
mask, and optional candidate-ceiling fields.

Native-frame results are also recorded. They are compared pixel-by-pixel only
when independently computed native bounds are equal; otherwise the report says
no native cross-frame pixel comparison was performed.

Placement multiset comparison separately reports shared, A-only, B-only, and
part-count-difference values. This distinguishes identical placements and masks,
different placements but equal masks, and different masks with equal counts.

## Independent synthetic tests

The focused suite covers ordered reconstruction, malformed/unknown IDs, source
digest rejection, identical placements, distinct parity-complement arrangements
with equal three-view masks, distinct masks with equal TP/FP/FN, source-frame
rejection, invalid frame metadata, XOR accounting, hashes versus exact equality,
and native/shared frame separation.

## Candidate-space coverage ceiling

Stage B is opt-in through `--candidate-ceiling`; default Stage A behavior remains
unchanged. It reruns only deterministic preprocessing and the historical no-wedge
candidate preflight after both arms pass Stage A parity. It never calls
`convert_fixed_grid()` or `solve_surface_grid_v4()`.

The first Stage B attempt stopped before writing output because M13C incorrectly
treated any eligible experimental wedge as a failed no-wedge preflight. The
historical M13B arm correctly ignores wedges after the combined M12C preflight
reports `READY`. M13C now preserves that status rule and writes structured
`PRECHECK_FAILED` evidence—including raw, collision-filtered, support-reachable,
wedge, and combined counts—rather than raising before a summary is written.

After the parity gate, approved no-wedge candidate rasters may be audited
without solving. The runner rebuilds 1x source occupancy, initial slope cells,
protected-empty cells, projection-hull targets, and required projection pixels.
It then reconstructs final locked nonrectangular placements from M13B saved IDs,
applies M12C/M13B collision filtering and support-reachability, and rejects the
case if the candidate count differs from Duck 1,449, Mansion 3,166, or Realistic
man 1,043. For fixed-frame source pixels `S`, locked pixels `L`, and each
eligible candidate raster `C_i`:

```text
TP_upper = |S intersect (L union union(C_i))|
FP_lower = |L minus S|
IoU_upper = TP_upper / (|S| + FP_lower)
```

For an empty denominator, record 1.0 only when both masks are empty; otherwise
it is undefined. This is a relaxed coverage bound: it ignores collision, support,
protected-space, part-count, and all other simultaneous-feasibility constraints.
It is not a mechanically feasible optimum. Wedges remain disabled and actual
candidate rasters—not rectangular envelopes—are required.

## Final Stage A findings

Stage A establishes exact shared-frame A/B mask equality: all front, side, and
top XOR counts are zero. Duck changed from 28 to 27 parts, Mansion from 24 to
18, and Realistic man retained the same 18 placement IDs. All recorded arms had
zero reported collision, unsupported, invalid-interface, and protected-space
violations; components were Duck 2/2, Mansion 5/4, and Realistic man 2/2.

| Model | Control / IoU-proxy placements | Shared-frame XOR (front / side / top) | Stage A |
| --- | --- | --- | --- |
| Duck | Different, 28 / 27 parts | 0 / 0 / 0 | PASS |
| Mansion | Different, 24 / 18 parts | 0 / 0 / 0 | PASS |
| Realistic man | Identical, 18 / 18 parts | 0 / 0 / 0 | PASS |

Each source digest was verified against the private manifest and M13B record;
all six reconstructed arms passed placement, part-count, fixed-frame, frozen
silhouette-v1, and shared-bounds parity. This establishes equivalence only for
the tested 128 by 128 XZ/YZ/XY projections. It does not establish identical
three-dimensional arrangements, connectivity, physical stability, or clutch.

## Final Stage B findings

Historical rectangle candidate counts and Control membership were independently
verified: Duck 1,449, Mansion 3,166, and Realistic man 1,043. All combined
historical preflights were `READY`; Stage B is PASS for every case.

| Model | Candidates | Observed fixed-frame mean IoU | Relaxed mean IoU upper bound | TP saturated views |
| --- | ---: | ---: | ---: | --- |
| Duck | 1,449 | 0.601744 | 0.906524 | 0 / 3 |
| Mansion | 3,166 | 0.603171 | 0.970802 | 3 / 3 |
| Realistic man | 1,043 | 0.424073 | 0.969354 | 3 / 3 |

`S` is source foreground, `L∩S` is source pixels covered by locked geometry,
`C∩S` is source pixels covered by at least one eligible candidate, and
`TP_upper` is coverage by `L union C`. All values use M13B's fixed frame.

| Model / view | Observed TP / FP / FN | S | L∩S | C∩S | TP_upper | Uncovered S | FP_lower | IoU_upper | Absolute gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Duck front | 7803 / 3940 / 92 | 7895 | 548 | 7804 | 7804 | 91 | 529 | 0.926401 | 0.267085 |
| Duck side | 6558 / 4002 / 517 | 7075 | 389 | 6623 | 6623 | 452 | 79 | 0.925776 | 0.333738 |
| Duck top | 7227 / 5793 / 28 | 7255 | 1319 | 7228 | 7228 | 27 | 1078 | 0.867395 | 0.313517 |
| Mansion front | 10257 / 3859 / 65 | 10322 | 103 | 10257 | 10257 | 65 | 16 | 0.992165 | 0.268873 |
| Mansion side | 8223 / 6245 / 191 | 8414 | 294 | 8168 | 8223 | 191 | 283 | 0.945498 | 0.384546 |
| Mansion top | 8606 / 7778 / 0 | 8606 | 745 | 8606 | 8606 | 0 | 223 | 0.974742 | 0.449473 |
| Realistic man front | 6361 / 8343 / 116 | 6477 | 0 | 6361 | 6361 | 116 | 0 | 0.982090 | 0.552873 |
| Realistic man side | 5269 / 6141 / 398 | 5667 | 0 | 5269 | 5269 | 398 | 0 | 0.929769 | 0.483546 |
| Realistic man top | 5249 / 7960 / 20 | 5269 | 0 | 5249 | 5249 | 20 | 0 | 0.996204 | 0.599424 |

Duck retains representation TP headroom in every fixed view. Mansion and
Realistic man already achieve the relaxed maximum TP in all three views. For
those six saturated views, any IoU improvement must reduce FP, or trade TP for
a sufficiently larger FP reduction. This does **not** show that existing
constraints force the observed FP: the candidate union ignores simultaneous
selection and so cannot identify a mechanically achievable minimum FP.

The upper bound relaxes candidate mutual exclusion/collision, verified support,
mandatory-coverage interactions, connectivity, part-count limits, and other
simultaneous-feasibility constraints. It is not a constructible LEGO solution,
an optimum, or evidence that the solver can attain it. It separates
representation coverage from simultaneous feasibility, mechanical validity,
optimization quality, and unchanged frozen fidelity.

## Completed decision

**M13C is successfully completed as an offline diagnostic milestone.** The
evidence supports a GO only for designing a separate, bounded M13D experiment:
constraint-aware TP/FP trade-offs and minimum achievable FP under explicit
coverage requirements. It is not a GO for a production change, new part family,
or an optimizer promotion.

## Reproducibility

Run from the repository root in Windows CMD. The output path is ignored and must
remain private:

```cmd
cd backend && uv run python scripts\run_m13c_silhouette_audit.py --manifest ..\artifacts\m7b-corpus\manifest.json --summary ..\artifacts\m13b-duck-final\summary.json --summary ..\artifacts\m13b-mansion-pilot\summary.json --summary ..\artifacts\m13b-man-final\summary.json --output-dir ..\artifacts\m13c-silhouette-audit
```

Run the opt-in Stage B audit with the same inputs plus `--candidate-ceiling`:

```cmd
cd backend && uv run python scripts\run_m13c_silhouette_audit.py --candidate-ceiling --manifest ..\artifacts\m7b-corpus\manifest.json --summary ..\artifacts\m13b-duck-final\summary.json --summary ..\artifacts\m13b-mansion-pilot\summary.json --summary ..\artifacts\m13b-man-final\summary.json --output-dir ..\artifacts\m13c-stageb-ceiling
```

## Recommendation

Do not implement M13D in this milestone. Its design should state a bounded
coverage requirement, the permitted TP/FP trade-off, and the exact feasibility
constraints under test before any new optimization is run.
