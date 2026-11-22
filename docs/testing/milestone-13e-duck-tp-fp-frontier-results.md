# M13E-B2 — Duck TP/FP Frontier Results and B3 Design

## Final B2 result

M13E-B2 is complete as an offline, Duck-only diagnostic. The five saved records in `artifacts/m13e-duck-tp-fp-frontier/` were read and validated; no optimization was rerun. All rows use the pinned Duck source SHA-256 `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e`, 1,449 candidates, the `5 x 7 x 12` grid, locked geometry, wedge `41769a` disabled, a 60-part cap, seed 0, one worker, and a 30-second deterministic budget. The historical Control assignment validation and independent Control mask parity passed for every row.

The B2 objective was aggregate fixed-frame FP minimisation under `TP_v >= Control_TP_v - allowance_v` and `FP_v <= Control_FP_v`. It is not an IoU objective. Consequently, FP reduction is not evidence of an IoU improvement.

Source foreground counts are front/side/top = `7,895 / 7,075 / 7,255`. Control fixed-frame TP/FP/FN is `7,803/3,940/92; 6,558/4,002/517; 7,227/5,793/28`; its aggregate FP is 13,735, fixed-frame mean IoU is 0.601744, and frozen `silhouette-v1` mean IoU is 0.595249.

| TP-loss row | Allowance (F/S/T) | TP floor (F/S/T) | Solver status / classification | Objective / bound | Fixed-frame TP/FP/FN (F; S; T) | Aggregate TP / FP (reduction) | Fixed mean IoU (delta) | Frozen mean IoU (delta) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0% | `0 / 0 / 0` | `7,803 / 6,558 / 7,227` | `FEASIBLE` / verified incumbent | `13,735 / 13,110` | `7,803/3,940/92; 6,558/4,002/517; 7,227/5,793/28` | `21,588 / 13,735 (0)` | `0.601744 (0.000000)` | `0.595249 (0.000000)` |
| 0.5% | `39 / 35 / 36` | `7,764 / 6,523 / 7,191` | `OPTIMAL` | `13,735 / 13,735` | `7,803/3,940/92; 6,558/4,002/517; 7,227/5,793/28` | `21,588 / 13,735 (0)` | `0.601744 (0.000000)` | `0.595249 (0.000000)` |
| 1% | `78 / 70 / 72` | `7,725 / 6,488 / 7,155` | `OPTIMAL` | `13,721 / 13,721` | `7,803/3,940/92; 6,558/4,002/517; 7,164/5,779/91` | `21,525 / 13,721 (14)` | `0.600331 (-0.001413)` | `0.595249 (0.000000)` |
| 2% | `157 / 141 / 145` | `7,646 / 6,417 / 7,082` | `OPTIMAL` | `13,580 / 13,580` | `7,694/3,877/201; 6,460/3,924/615; 7,164/5,779/91` | `21,318 / 13,580 (155)` | `0.596850 (-0.004894)` | `0.594228 (-0.001021)` |
| 5% | `394 / 353 / 362` | `7,409 / 6,205 / 6,865` | `UNKNOWN` / inconclusive | none / none | none (no returned incumbent) | none | none | none |

The actual deterministic-time consumption / wall-clock seconds was respectively `30.00699431544456 / 157.7346404`, `19.85986620490222 / 110.9922155`, `21.789090623974356 / 104.4128416`, `22.20052222878812 / 108.6888717`, and `30.088256280001925 / 141.8718477`.

Every returned incumbent has independent fixed-frame mask/metric parity: source masks match and each view has zero XOR, expected-only pixels, and actual-only pixels. Their frozen `silhouette-v1` values are:

| Row | Frozen front TP/FP/FN, IoU | Frozen side TP/FP/FN, IoU | Frozen top TP/FP/FN, IoU |
| --- | --- | --- | --- |
| 0% | `7,513/4,163/89`, `0.638589` | `6,635/3,904/163`, `0.619978` | `6,963/6,213/32`, `0.527180` |
| 0.5% | `7,513/4,163/89`, `0.638589` | `6,635/3,904/163`, `0.619978` | `6,963/6,213/32`, `0.527180` |
| 1% | `7,513/4,163/89`, `0.638589` | `6,635/3,904/163`, `0.619978` | `6,963/6,213/32`, `0.527180` |
| 2% | `7,513/4,163/89`, `0.638589` | `6,580/3,868/218`, `0.616914` | `6,963/6,213/32`, `0.527180` |
| 5% | no incumbent | no incumbent | no incumbent |

| Row | Parts / connected components | Placement-ID SHA-256 | Mechanical diagnostics |
| --- | --- | --- | --- |
| 0% | `28 / 2` (sizes 3, 25) | `855305fda25062669f573fb59fac0dd24db3bc4c8e33697d3f7c54f87ec2f0c0` | no collisions, invalid interfaces, isolated placements, protected-space violations, or unsupported placements; part cap satisfied; 0 wedges |
| 0.5% | `28 / 2` (sizes 3, 25) | `855305fda25062669f573fb59fac0dd24db3bc4c8e33697d3f7c54f87ec2f0c0` | no collisions, invalid interfaces, isolated placements, protected-space violations, or unsupported placements; part cap satisfied; 0 wedges |
| 1% | `34 / 1` (size 34) | `c86aac500ee266db7bd3984d4ba99a5aa305eb3300c3398c17c4cca56069f58e` | no collisions, invalid interfaces, isolated placements, protected-space violations, or unsupported placements; part cap satisfied; 0 wedges |
| 2% | `34 / 2` (sizes 3, 31) | `ec9c3e225dc5ed9f4a82ea51a21825309e224e7d37b3faea3702064f6b02609c` | no collisions, invalid interfaces, isolated placements, protected-space violations, or unsupported placements; part cap satisfied; 0 wedges |
| 5% | no incumbent | none | no post-solve diagnostics exist |

The 1% solution is therefore the only returned B2 candidate with one connected component. The `UNKNOWN` result at 5% is neither an infeasibility proof nor a candidate result. The 1% and 2% aggregate-FP improvements did not produce a verified frozen silhouette-v1 improvement; the 2% result regressed from 0.595249 to 0.594228. The saved summary's `verifiedFrozenSilhouetteV1Improvement` is `false`.

## M13E-B3 — exact fixed-frame IoU-dominance feasibility pilot

B3 should be a new offline Duck-only feasibility experiment, not a production converter change and not a replacement for the accepted M13B or B2 records. It will reconstruct the historical M13B model exactly: same pinned source, candidate order and vocabulary, locked geometry, 128-by-128 fixed-frame raster definition, source masks, mandatory coverage, non-overlap/support/protected-space hard constraints, disabled wedge, and 60-part cap. It will retain one worker, seed 0, and the 30-second deterministic budget. It intentionally removes the B2 per-view FP caps and TP floors.

For each view `v`, let `S_v` be its exact source-foreground count, and let `TP_control_v` and `FP_control_v` be the historical fixed-frame Control counts. Build the existing Boolean union raster variables once, derive integer linear `TP_v` and `FP_v`, and impose exactly:

```text
D_v = (S_v + FP_control_v) * TP_v
      - TP_control_v * (S_v + FP_v)

D_front >= 0
D_side  >= 0
D_top   >= 0
D_front + D_side + D_top >= 1
```

These are integer linear CP-SAT expressions: all coefficients are recorded integers, and no floating point, rounded coefficient, or threshold relaxation is permitted. Since `IoU_v = TP_v / (S_v + FP_v)` and all denominators are positive, `D_v >= 0` is exactly `IoU_v >= IoU_control_v`; the final sum is at least one, so at least one view is strictly better. Thus a witness dominates the Control per-view fixed-frame IoU, rather than merely improving aggregate FP.

Before adding the strict-sum constraint, B3 must separately build the identical historical hard-constraint model, fix every rectangular selection variable to the verified Control assignment, and solve it as a feasibility check. It must also reproduce the Control's exact fixed-frame mask/metrics. Failure here is a model-parity failure, not evidence about IoU dominance. The strict B3 model then removes those selection fixings and adds only the four exact `D` constraints above; no Control hint is needed for the strict search.

The result schema should retain source/model fingerprints, candidate count and ordering fingerprint, Control assignment hash, solver configuration, status, selected IDs, all exact `D_v` values, fixed-frame TP/FP/FN and per-view IoU, and the Control comparison. For every witness, require independent renderer mask/metric parity (including per-view XOR/expected-only/actual-only counts), unchanged frozen `silhouette-v1` evaluation and deltas, placement-ID hash, and the full mechanical diagnostic report. The frozen evaluator is evidence only; it is not a CP-SAT constraint or objective.

This is a pure feasibility question. `OPTIMAL` or `FEASIBLE` with a returned assignment means only that a fixed-frame IoU-dominating witness was found; neither label means globally IoU-optimal. `INFEASIBLE` proves no such witness exists within the reconstructed M13B candidate model and preserved hard constraints. `UNKNOWN` without a witness is inconclusive. A returned incumbent must never be inferred from a bound or a hint.

B3's scope is deliberately narrower than mean-IoU optimisation: an `INFEASIBLE` result would not rule out a higher mean IoU that improves two views enough to offset a regression in the third.

## Follow-up for mean-IoU trade-offs

After B3, run a separate offline Pareto-frontier study rather than weakening its dominance definition. Hold the same historical model fixed, choose a finite, predeclared grid of exact integer TP/FP envelopes for the two views allowed to trade off, and at each cell solve a deterministic lexicographic linear objective for the remaining view (maximize TP, then minimize FP). Independently calculate each returned vector's three rational IoUs and mean using integer numerator/denominator arithmetic, then compare it to the Control mean by cross multiplication with arbitrary-precision Python integers. This permits an explicitly recorded view to worsen while avoiding floating-point acceptance decisions. It investigates the trade-off frontier; it should not be presented as a global mean-IoU proof unless the bounded grid is exhaustively justified and completed.

## Local validation

Focused offline checks completed successfully:

```text
uv run pytest -q tests/test_m13e_duck_tp_fp_frontier.py \
  tests/test_m13e_duck_control_hint_experiment.py \
  tests/test_m13e_duck_tp_max_experiment.py \
  tests/test_m13d_tp_fp_feasibility_experiment.py \
  tests/test_m13b_iou_objective_experiment.py \
  tests/test_m13c_silhouette_equivalence_audit.py
# 56 passed

uv run ruff check [the corresponding experiment modules and tests]
uv run ruff format --check [the corresponding experiment modules and tests]
uv run mypy app
# all passed
```

No private optimization was run, and no production conversion code, accepted historical record, commit, remote branch, or deployment was changed.
