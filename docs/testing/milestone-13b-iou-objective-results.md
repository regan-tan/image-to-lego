# Milestone 13B: Controlled Offline IoU-Aware Objective Experiment

## Final decision

**M13B: NO-GO for promoting this fixed-reference IoU-aware linear objective as
a fidelity improvement under the tested native 1x grids and solver budget.**

The predeclared strict GO required at least two of three models to improve
frozen mean IoU by at least `.01`, with no loss greater than `.01`, no
connectivity regression, no new mechanical violation, and unchanged resource
limits and eligible candidates. All three paired outcomes have a frozen-mean
IoU delta of exactly `0.000000`. Therefore zero models improved, zero reached
the `+.01` threshold, and no model had a measured fidelity regression. The
mechanical checks passed and no pair had a connectivity regression.

This is a completed, evidence-backed negative fidelity experiment, not an
unresolved implementation failure. It does not enable the objective in
production. These bounded `FEASIBLE` outcomes do not prove that another
objective, a larger solver budget, or a different candidate space could not
improve fidelity.

## Scope and preserved M13A correction

M13B is offline only. It does not alter production V4-V7 converter behavior,
API, workers, frontend, exporter, frozen evaluator, or catalogue behavior.
Both arms keep wedge `41769a` disabled and use the same native 1x source
evidence, fixed grid, locked geometry, candidates, constraints, seed, workers,
and deterministic solver budget. Only the primary solver score differs.

The M13A mathematical erratum remains in force. A higher raw `TP-FP` does not
necessarily raise one-view IoU: with `P=100`, `(TP, FP, FN)` changing from
`(90, 50, 10)` to `(80, 39, 20)` raises `TP-FP` from `40` to `41`, while IoU
falls from `.600000` to `80/139 ~= .575540`. For fixed `P` and reference IoU
`r`, this comparison remains exact:

```text
IoU_new > r
TP_new / (P + FP_new) > r
TP_new - r * FP_new > r * P
```

The proxy maximises the deterministically rounded, fixed-reference form
`sum(TP / D_ref - TP_ref * FP / D_ref^2)`, with scale `1,000,000` and integer
half-up rounding. The selected-part term remains a secondary tie-break.

## Recorded inputs and reference weights

The completed private evidence was read directly from:

- `artifacts/m13b-duck-final/summary.json`
- `artifacts/m13b-mansion-pilot/summary.json`
- `artifacts/m13b-man-final/summary.json`

The `sourceSha256` in each record matches the SHA-256 computed from its local
M7B corpus GLB. All three summaries use schema `m13b-iou-proxy-v1`, coefficient
scale `1,000,000`, and integer half-up rounding.

| Model | Pinned SHA-256 | Grid (W x D x H) | Candidates | Total recorded runtime (s) |
| --- | --- | --- | ---: | ---: |
| Duck | `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e` | 5 x 7 x 12 | 1,449 | 255.1892342 |
| Mansion | `d1a9618613f251d528eccc12f99460f9a64c39e83b8b9267e2c4a2b923919510` | 7 x 4 x 12 | 3,166 | 26,492.2378561 |
| Realistic man | `0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce` | 3 x 5 x 18 | 1,043 | 196.2797596 |

Reference entries are `TP_ref / FP_ref / source foreground P`; objective
weights are `TP weight / FP weight` for front, side, top respectively.

| Model | Reference TP / FP / P (front; side; top) | Reference weights (front; side; top) |
| --- | --- | --- |
| Duck | `7803/3940/7895; 6558/4002/7075; 7227/5793/7255` | `84/56; 90/53; 77/42` |
| Mansion | `10257/3859/10322; 8223/6245/8414; 8606/7778/8606` | `71/51; 68/38; 61/32` |
| Realistic man | `6361/8343/6477; 5269/6141/5667; 5249/7960/5269` | `67/29; 85/38; 76/30` |

Each preflight reported `READY` with its control candidate count equal to the
recorded candidate count. All cases used `maxParts=60`, `targetParts=24`,
`upAxis=y`, and `wedge41769aEnabled=false`.

## Solver and assembly evidence

`objective / bound / gap` is reported separately for each arm because their
objective magnitudes are not comparable. Every run returned `FEASIBLE`, never
`OPTIMAL`.

| Model | Arm | Status | Runtime (s) | Objective / bound / gap | IoU-proxy | Raw TP-FP | Parts | Components |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| Duck | Control | FEASIBLE | 65.6042692 | `11386825 / 11671042 / 284217` | 1126099 | 7853 | 28 | 2 |
| Duck | IoU-proxy | FEASIBLE | 71.9830803 | `1632843526 / 1665478692 / 32635166` | 1126099 | 7853 | 27 | 2 |
| Mansion | Control | FEASIBLE | 45.2821729 | `29149045 / 29149066 / 21` | 1129362 | 9204 | 24 | 5 |
| Mansion | IoU-proxy | FEASIBLE | 21.6950875 | `3576689437 / 3576689452 / 15` | 1129362 | 9204 | 18 | 4 |
| Realistic man | Control | FEASIBLE | 60.5665173 | `-5809878 / -5809864 / 14` | 558871 | -5565 | 18 | 2 |
| Realistic man | IoU-proxy | FEASIBLE | 63.0519719 | `583461306 / 583461320 / 14` | 558871 | -5565 | 18 | 2 |

All six records report zero collisions, unsupported placements, invalid
interfaces, and protected-space violations. The observed part-count changes
are Duck `28 -> 27`, Mansion `24 -> 18`, and Realistic man `18 -> 18`.
Connected components are Duck `2 -> 2`, Mansion `5 -> 4`, and Realistic man
`2 -> 2`. These reductions are observations only: this experiment does not
establish that the IoU-aware proxy caused the part-count reductions.

## Fidelity evidence

Within each model, the two arms have equal aggregate scores. Their recorded
fixed-frame TP/FP/FN, fixed-frame mean IoU, frozen silhouette-v1 mean IoU, and
shared-explicit-bounds metrics are exactly equal. Exact evaluator parity is
`true` for every arm and every front/side/top comparison, with zero source and
LEGO mask differences between the compared evaluator paths.

Equal counts and exact within-arm evaluator parity do **not** prove that the
Control and IoU-proxy arms have pixel-identical masks. The recorded evidence
does not include a direct cross-arm raster-mask XOR, so M13B makes no such
claim.

| Model | Fixed frame TP / FP / FN (front; side; top) | Fixed mean IoU | Frozen mean IoU, Control -> IoU-proxy | Shared-bounds IoU (front; side; top) |
| --- | --- | ---: | --- | --- |
| Duck | `7803/3940/92; 6558/4002/517; 7227/5793/28` | 0.6017437112 | `0.595249 -> 0.595249` (`+0.000000`) | `0.638589; 0.619978; 0.527180` |
| Mansion | `10257/3859/65; 8223/6245/191; 8606/7778/0` | 0.6031708663 | `0.600598 -> 0.600598` (`+0.000000`) | `0.718515; 0.561107; 0.522172` |
| Realistic man | `6361/8343/116; 5269/6141/398; 5249/7960/20` | 0.4240733252 | `0.421959 -> 0.421959` (`+0.000000`) | `0.426276; 0.445331; 0.394271` |

The shared bounds were explicitly fixed per model and view:

| Model | Front bounds | Side bounds | Top bounds |
| --- | --- | --- | --- |
| Duck | `[-0.05, 5.05, -0.12, 12.12]` | `[-0.07, 7.07, -0.12, 12.12]` | `[-0.05, 5.05, -0.07, 7.07]` |
| Mansion | `[-0.07, 7.07, -0.12, 12.12]` | `[-0.04, 4.04, -0.12, 12.12]` | `[-0.07, 7.07, -0.04, 4.04]` |
| Realistic man | `[-0.03, 3.03, -0.18, 18.18]` | `[-0.05, 5.05, -0.18, 18.18]` | `[-0.03, 3.03, -0.05, 5.05]` |

For each row, the shared-bounds TP/FP/FN are also the frozen silhouette-v1
counts: Duck `7513/4163/89; 6635/3904/163; 6963/6213/32`; Mansion
`9830/3778/73; 8030/6203/78; 8290/7586/0`; Realistic man
`6103/8093/121; 5079/5972/354; 5038/7713/27`. The corresponding frozen
per-view IoUs are the shared-bounds values in the preceding table.

## Interpretation and next research recommendation

The fidelity hypothesis was unsuccessful under this fixed reference, native 1x
grid, candidate set, and deterministic solver budget. That conclusion is
separate from the observed lower selected-part counts, which require their own
causal experiment before attribution.

The next small milestone should remain offline only and investigate silhouette
equivalence and feasible-set limitations. Useful measurements are:

- Exact Control-versus-IoU-proxy raster-mask XOR per view.
- The number of distinct silhouettes produced by different mechanically valid
  arrangements.
- Whether materially different part layouts share identical projected masks.
- Whether mandatory source coverage and locked geometry dominate silhouettes.
- Whether the existing candidate catalogue and grid resolution leave room for
  better IoU.

Do not implement that follow-up as part of M13B.

## Local validation

The implementation and documentation diff was audited before finalization. The
changed files are listed in the final change audit; no commit, push, merge, or
deployment is part of this milestone. Run the focused checks from `backend`:

```cmd
uv run pytest -q tests/test_m13b_iou_objective_experiment.py tests/test_m13a_objective_alignment_audit.py tests/test_m12c_wedge_fidelity_experiment.py tests/test_evaluation_alignment.py tests/test_catalogue_silhouette_experiment.py
uv run ruff check app/conversion/m12c_wedge_fidelity_experiment.py app/conversion/m13b_iou_objective_experiment.py tests/test_m12c_wedge_fidelity_experiment.py tests/test_m13a_objective_alignment_audit.py tests/test_m13b_iou_objective_experiment.py
uv run ruff format --check app/conversion/m12c_wedge_fidelity_experiment.py app/conversion/m13b_iou_objective_experiment.py tests/test_m12c_wedge_fidelity_experiment.py tests/test_m13a_objective_alignment_audit.py tests/test_m13b_iou_objective_experiment.py
uv run mypy app
```

Run `git diff --check` from the repository root. The complete backend regression
suite, in Windows CMD, is:

```cmd
cd backend && uv run pytest -q
```
