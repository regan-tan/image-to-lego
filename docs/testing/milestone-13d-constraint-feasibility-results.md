# M13D — Constraint Feasibility Results

M13D is an offline diagnostic experiment. It does not change production conversion,
historical M13B controls, source models, or benchmark results. Its fixed-frame
objective is a constrained TP/FP question, not a fidelity-improvement claim.

The accepted Stage B evidence is
`artifacts/m13d-stage-b-fp-fixed/summary.json`. The earlier
`artifacts/m13d-stage-b` output is preserved only as diagnostic evidence and is
not used below.

## Verification of the accepted record

The final JSON was checked against the saved single-case M13B controls
(`m13b-duck-final`, `m13b-mansion-pilot`, and `m13b-man-final`) and the M13D
record-validation utility. The source SHA-256 values and candidate counts agree:

| Case | Source SHA-256 | Candidates | Check |
| --- | --- | ---: | --- |
| Duck | `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e` | 1,449 | Stage A passed; Stage B returned `UNKNOWN` |
| Mansion | `d1a9618613f251d528eccc12f99460f9a64c39e83b8b9267e2c4a2b923919510` | 3,166 | Control membership recorded as verified |
| Realistic man | `0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce` | 1,043 | Control membership recorded as verified |

For Mansion and Realistic man, the saved Control TP/FP values equal the solver
and independently rendered result values. `validate_view_metrics` also accepts
both solved records: TP and FN account for each source foreground mask, every
metric is within the 128 x 128 raster range, and aggregate FP equals the sum of
the three extracted per-view FP counts. The saved mechanical validation is clean
apart from the reported two connected components.

The private manifest/source data needed to recreate candidates was intentionally
not rerun. The accepted runner had already failed closed on source hashing,
candidate count, preflight, reconstructed Control membership, Control fixed-frame
parity, and mask parity before each solve.

## Stage A — no-solver constraint audit

Stage A completed with `PASS` for all three cases. It reconstructed the no-wedge
M13B candidate model and fixed 128 x 128 frames, but deliberately did not create
or solve a CP-SAT model.

| Case | Candidates | Occupancy-exclusion pairs | Candidates with no conflict | Mandatory projection pixels (locked / candidate-covered) | Zero / single candidate alternatives |
| --- | ---: | ---: | ---: | ---: | ---: |
| Duck | 1,449 | 124,033 | 0 | 131 (33 / 98) | 0 / 0 |
| Mansion | 3,166 | 411,909 | 0 | 143 (13 / 130) | 0 / 0 |
| Realistic man | 1,043 | 51,056 | 0 | 122 (0 / 122) | 0 / 0 |

All cases had dense rectangular occupancy conflicts and no mandatory coarse
projection requirement with zero or exactly one candidate alternative. These are
structural observations, not feasibility proofs: 128px raster uniqueness does
not make a placement globally necessary, and an exclusive FP contribution does
not mean that its placement can legally be removed.

The reconstructed historical M13B rules were:

- pre-selection: protected-empty-space wedge eligibility, locked-body collision
  rejection, and support-reachability pruning;
- CP-SAT: rectangular occupancy mutual exclusion, wedge collision exclusions
  (inactive because `41769a` was disabled), direct verified candidate support,
  support for locked placements, mandatory coarse projection coverage, and the
  60-part cap; and
- post-solve only: completed-arrangement collision/support/protected-space/
  interface checks and global connected-component count.

In particular, connected-component count was not a solver hard constraint.

## Stage B — constrained fixed-frame FP minimization

Stage B rebuilt the same no-wedge candidate sets and historical M13B hard
constraints. It used a 30-second deterministic CP-SAT budget, one worker, and
random seed zero. Candidate raster coverage was represented once per pixel with
Boolean OR variables. Locked geometry was a constant contribution.

For each view, the model imposed:

```text
TP(view) >= Control TP(view)
FP(view) <= Control FP(view)
```

It then minimized `FP(front) + FP(side) + FP(top)`.

### Duck

| Status | Classification | Deterministic budget | Wall-clock runtime | Objective / bound | Incumbent |
| --- | --- | ---: | ---: | --- | --- |
| `UNKNOWN` | `INCONCLUSIVE` | 30.0 s | 116.7763714 s | none / none | none |

`UNKNOWN` is neither infeasibility nor proof that no FP-reducing solution
exists. No Stage B placement, per-view solved metrics, frozen silhouette result,
or mechanical result exists for Duck because no incumbent was returned.

### Mansion

| Measure | Front | Side | Top | Total / mean |
| --- | ---: | ---: | ---: | ---: |
| Control TP | 10,257 | 8,223 | 8,606 | — |
| Control FP | 3,859 | 6,245 | 7,778 | 17,882 |
| Result TP | 10,257 | 8,223 | 8,606 | — |
| Result FP | 3,859 | 6,245 | 7,778 | 17,882 |
| Result FN | 65 | 191 | 0 | — |
| Frozen silhouette-v1 TP | 9,830 | 8,030 | 8,290 | — |
| Frozen silhouette-v1 FP | 3,778 | 6,203 | 7,586 | — |
| Frozen silhouette-v1 FN | 73 | 78 | 0 | — |
| Frozen silhouette-v1 IoU | 0.718515 | 0.561107 | 0.522172 | 0.600598 |

The solver status was `OPTIMAL`; objective and best objective bound were both
17,882. It selected 22 parts, versus 24 Control parts, with total FP reduction
of 0. Post-solve diagnostics found no collision pairs, invalid interfaces,
isolated placements, protected-space violations, or unsupported placements;
the part cap was satisfied; wedge count was 0; and there were two connected
components (19 and 3 placements).

### Realistic man

| Measure | Front | Side | Top | Total / mean |
| --- | ---: | ---: | ---: | ---: |
| Control TP | 6,361 | 5,269 | 5,249 | — |
| Control FP | 8,343 | 6,141 | 7,960 | 22,444 |
| Result TP | 6,361 | 5,269 | 5,249 | — |
| Result FP | 8,343 | 6,141 | 7,960 | 22,444 |
| Result FN | 116 | 398 | 20 | — |
| Frozen silhouette-v1 TP | 6,103 | 5,079 | 5,038 | — |
| Frozen silhouette-v1 FP | 8,093 | 5,972 | 7,713 | — |
| Frozen silhouette-v1 FN | 121 | 354 | 27 | — |
| Frozen silhouette-v1 IoU | 0.426276 | 0.445331 | 0.394271 | 0.421959 |

The solver status was `OPTIMAL`; objective and best objective bound were both
22,444. It selected 21 parts, versus 18 Control parts, with total FP reduction
of 0. Post-solve diagnostics found no collision pairs, invalid interfaces,
isolated placements, protected-space violations, or unsupported placements;
the part cap was satisfied; wedge count was 0; and there were two connected
components (12 and 9 placements).

## Exact scope of the two optimality proofs

The Mansion and Realistic man results prove that, over the reconstructed
historical M13B candidate model and its stated hard constraints, no solution has
a lower **aggregate fixed-frame FP** while simultaneously satisfying every
per-view `TP >= Control TP` and `FP <= Control FP` condition. The reported
optimum equals the historical Control aggregate FP, so the classifications are
`PROVEN_UNCHANGED` for this restricted problem.

They do **not** prove globally optimal IoU, full connectivity, physical
buildability beyond the recorded diagnostics, or that no favorable TP/FP
trade-off exists. They also do not rule out a solution that loses some TP to
remove more FP, gains TP while accepting more FP, uses a different candidate
space, changes the frame/metric, or changes a historical hard constraint.

Frozen silhouette-v1 is reported as a separate evaluator result. It was not the
Stage B optimization objective or a solver constraint.

## Corrected implementation errors

Two errors invalidated the earlier Stage B reporting and were fixed before the
accepted run:

1. The final-record comparison used incompatible TP/FP/FN dictionary key shapes,
   preventing the intended strict comparison between solver counts and
   independently rendered counts. The corrected code normalizes the three
   per-view fields before comparing them and fails closed on disagreement.
2. Aggregate FP construction mutated an OR-Tools expression: repeated `+=`
   against the first per-view `SumArray` extended the stored front expression
   with side and top terms. That made reported front FP appear as aggregate FP.
   The corrected code retains independent per-view expressions and builds
   `total_fp` with `LinearExpr.Sum`.

The correction additionally validates integer/range accounting, TP+FN source
foreground parity, aggregate-FP parity, Control reference metrics, and
independent fixed-frame mask/render parity.

## Duck Control-hint follow-up (not implemented or run)

The Duck runner reconstructs the Control placements before it builds the solve.
It maps each rectangular Control placement through `stable_placement_id` to the
reconstructed candidate ID and fails closed if any is absent. Non-rectangular
Control placements are reconstructed as locked geometry. That is sufficient to
supply the historical Control assignment as a valid CP-SAT hint: set every
reconstructed rectangular Control candidate to 1 (and, for a complete candidate
assignment, every other candidate to 0) with `AddHint`; the coverage variables
are forced by those selections and may remain unhindered as auxiliary variables.
This changes neither the hard constraints nor the objective. It can, however,
change search order, so it must be evaluated as a separate experiment.

Run one Duck-only paired experiment, with the private input manifest and same
corrected runner revision:

| Arm | Change | Fixed conditions |
| --- | --- | --- |
| A | Existing no-hint model | candidate reconstruction, constraints, objective, seed 0, one worker, 30-second deterministic budget |
| B | Add the validated historical Control candidate assignment as a hint only | all Arm A conditions, including no constraint/objective/seed/budget changes |

For each arm, retain the same fail-closed prechecks and record status, objective,
bound, deterministic budget, wall time, incumbent availability, selected IDs,
per-view TP/FP/FN, independent mask parity, and mechanical diagnostics. Compare
only solver behavior and returned evidence; `UNKNOWN` remains inconclusive in
either arm. Do not replace the no-hint baseline with the hinted arm.

## Subsequent bounded TP/FP-frontier experiment (not implemented or run)

After the Duck hint comparison, use a separate, explicitly experimental frontier
study that preserves the historical M13B hard constraints and candidate space but
relaxes the Stage B per-view dominance restriction in bounded steps. A simple
design is to choose a small, predeclared grid of TP-loss allowances per view and
solve the same aggregate-FP minimization with:

```text
TP(view) >= Control TP(view) - allowance(view)
```

Keep the existing FP upper bounds for the first sweep; if a later second sweep
allows FP increases, declare those caps before running it. For every point,
record all per-view TP/FP/FN, aggregate FP, solver status/bound, deterministic
budget, parts, selected IDs, independent parity, and mechanical diagnostics.
Report nondominated points only after retaining the full raw grid. This would
measure bounded trade-offs; it would not establish global IoU optimality or
general conversion quality.
