# M13E-B1 - Duck constraint-preserving TP maximization

## Completed result

**M13E-B1 completed successfully.** The private results in
`artifacts/m13e-duck-tp-max/` contain two independently solved Duck arms. Both
are `OPTIMAL_WITH_UNCHANGED_TP`: the best incumbent and the proven bound are
both 21,588 aggregate fixed-frame true positives (TP). Therefore, under the
M13B/M13D restrictions reconstructed by this experiment, Duck cannot gain any
aggregate fixed-frame TP while retaining every per-view historical TP floor and
FP cap.

This is an offline experimental result only. It does not change production
conversion, the candidate catalogue, historical records, mechanics, source
models, or either renderer.

| Arm | Hint | Status | TP objective / bound | Deterministic seconds | Wall seconds | Parts | Components |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `duck-no-hint` | none | `OPTIMAL` | 21,588 / 21,588 | 29.92093107258792 | 143.8144934 | 43 | 2 |
| `duck-control-hint` | verified complete Control assignment | `OPTIMAL` | 21,588 / 21,588 | 29.90713841234758 | 146.3916816 | 28 | 2 |

The two arms use fresh models and solver instances. Their only intentional
difference is the `AddHint` assignment; it is guidance, never an equality
constraint. Both have model fingerprint
`ff4d4fba8aa10a62e8fc90c0bb590fbe985d35d2ae88885b203cf11b25798502`.
Their shared provenance records the pinned source SHA-256
`77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e`, grid
`5 x 7 x 12`, 1,449 candidates, 60-part cap, wedge `41769a` disabled,
OR-Tools `9.15.6755`, random seed 0, one worker, and a 30-second deterministic
budget. The pre-solve Control assignment validation passed in both records.

## Fixed-frame result and proof scope

| View | Historical TP | Result TP | Historical FP | Result FP | FN | Fixed-frame IoU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Front | 7,803 | 7,803 | 3,940 | 3,940 | 92 | 0.659316 |
| Side | 6,558 | 6,558 | 4,002 | 4,002 | 517 | 0.592038 |
| Top | 7,227 | 7,227 | 5,793 | 5,793 | 28 | 0.553878 |
| Total / mean | 21,588 | 21,588 | 13,735 | 13,735 | - | 0.601744 |

For selected rectangular candidates `x_i`, M13E-B1 constructs Boolean
fixed-frame union variables for the exact 128 x 128 candidate rasters. Locked
geometry is counted separately. In each view `v`, the model retains:

```text
TP_v >= Control_TP_v
FP_v <= Control_FP_v

maximize TP_front + TP_side + TP_top
```

It also retains the historical rectangular occupancy exclusion, verified
candidate and locked support, mandatory coarse projection coverage, locked
geometry, candidate ordering and vocabulary, disabled wedge, and 60-part cap.
The `OPTIMAL` status and equal objective/best bound prove that no feasible
assembly in **this fixed candidate model with these per-view dominance
constraints** exceeds 21,588 total TP. Since Control itself supplies 21,588
TP, there is no TP increase under the restrictions.

M13D and M13E-A already proved no aggregate FP reduction under the same strict
dominance restrictions. M13E-B1 adds the complementary result: no aggregate TP
increase is possible under them either.

This is not a global IoU-optimality proof. It does not search other grids,
candidates, geometries, part caps, mechanical models, scoring frames, or
relaxed per-view TP/FP budgets. Fixed-frame IoU is not frozen `silhouette-v1`
IoU, and equal TP/FP counts only establish equality for this restricted
fixed-frame objective/constraint set.

## Independent validation evidence

For each incumbent, the assembly was reconstructed from its saved placement
IDs, then checked independently of CP-SAT:

- Candidate-raster OR masks match the M12C fixed-frame renderer exactly:
  source masks match and front, side, and top each have XOR = 0.
- The independent metrics match the solver metrics and the TP objective is the
  extracted sum of the three TP counts.
- All per-view TP floors and FP caps hold exactly at their historical values.
- Mechanical validation passed: no collisions, unsupported placements,
  protected-space violations, invalid interfaces, or isolated placements;
  wedge count is zero and the part cap holds. Connectivity is a post-solve
  diagnostic only; each assembly has two connected components.

The no-hint placement-ID SHA-256 is
`e98ed612e5b0eb671ad95cab93b6527471e66c42ff048b36af0622021a9c5850`; the
Control-hint placement-ID SHA-256 is
`855305fda25062669f573fb59fac0dd24db3bc4c8e33697d3f7c54f87ec2f0c0`.

The unchanged frozen `silhouette-v1` evaluator also agrees across Control and
both returned assemblies:

| View | TP | FP | FN | IoU |
| --- | ---: | ---: | ---: | ---: |
| Front | 7,513 | 4,163 | 89 | 0.638589 |
| Side | 6,635 | 3,904 | 163 | 0.619978 |
| Top | 6,963 | 6,213 | 32 | 0.527180 |
| Mean | - | - | - | 0.595249 |

The fixed-frame and frozen mean-IoU changes from Control are both 0.0. This is
reported as equality, not as a fidelity improvement.

## M13E-B2 design: bounded Duck TP/FP trade-off pilot

M13E-B2 is an implemented, opt-in offline pilot; it has **not been run** by
this change. It starts with Duck only and preserves every historical M13B hard
constraint, the exact candidate ordering and 128 x 128 raster definitions,
locked geometry, mechanics, grid, 60-part cap, and frozen evaluator. Each
solve uses the existing 30-second deterministic budget, one worker, and random
seed 0.

For each uniform loss percentage `p`, let `S_v` be the fixed-frame source
foreground count in view `v`. Define the allowed loss as:

```text
allowance_v(p) = floor(S_v * p / 100)
TP_v >= Control_TP_v - allowance_v(p)
FP_v <= Control_FP_v
minimize FP_front + FP_side + FP_top
```

Using `floor` is intentional: it never grants more than the declared percentage
of any view's source foreground. The source counts are Front 7,895, Side 7,075,
and Top 7,255. The predeclared pilot matrix is:

| Uniform TP-loss percentage | Front allowance / TP floor | Side allowance / TP floor | Top allowance / TP floor |
| ---: | ---: | ---: | ---: |
| 0% | 0 / 7,803 | 0 / 6,558 | 0 / 7,227 |
| 0.5% | 39 / 7,764 | 35 / 6,523 | 36 / 7,191 |
| 1% | 78 / 7,725 | 70 / 6,488 | 72 / 7,155 |
| 2% | 157 / 7,646 | 141 / 6,417 | 145 / 7,082 |
| 5% | 394 / 7,409 | 353 / 6,205 | 362 / 6,865 |

The 0% row must reproduce the established strict-dominance baseline: aggregate
FP 13,735 and the historical per-view TP/FP values. A mismatch is a model-parity
failure, not a candidate improvement.

For every returned incumbent, B2 should save the solver status, objective and
best bound; independent TP/FP/FN per view; fixed-frame mean IoU; frozen
`silhouette-v1` mean IoU; explicit Control deltas; placement IDs and hash;
mechanical report and component count; and exact per-view mask-parity evidence.
Reduced aggregate FP alone is never proof of improved fidelity: the reported
fixed-frame and frozen mean IoUs must be evaluated directly.

`OPTIMAL` proves the stated FP minimum for that one allowance row. `FEASIBLE`
is only an incumbent, `UNKNOWN` is inconclusive, and `INFEASIBLE` after a
verified applicable baseline is a model-parity investigation. No outcome from
one row should be generalized to another row.

This five-row uniform sweep is a bounded pilot, not a complete Pareto frontier.
It can miss an improvement that needs a loss concentrated in one view. If the
pilot warrants extension, first predeclare a small asymmetric matrix around the
best uniform row, varying one view's allowance while holding the other two
fixed. Only if all FP-capped budgets are exhausted should a separate, explicitly
labelled experiment introduce bounded per-view FP increases; that experiment
must report the full TP/FP/IoU trade-off rather than treating its FP relaxation
as comparable to B2.

The runner uses the verified complete historical Control assignment as an
`AddHint` for every one of the five rows. The hint is guidance only, never a
forced selection, and there is no paired-hint arm in B2. It validates exact
integer basis-point allowances, source foreground counts, the historical
Control assignment, renderer/raster parity, and mechanics before each solve.
It writes ignored records to `artifacts/m13e-duck-tp-fp-frontier/` only when
explicitly invoked:

```cmd
cd backend
uv run python scripts\run_m13e_duck_tp_fp_frontier.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-tp-fp-frontier
```
