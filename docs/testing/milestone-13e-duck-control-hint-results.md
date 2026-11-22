# M13E — Duck CP-SAT Control-hint Results

## Status

**M13E-A completed successfully.** This offline paired experiment does not
change production conversion, M13D evidence, candidate generation, historical
Duck Control, evaluators, or hard constraints.

Both arms proved the same restricted aggregate fixed-frame false-positive (FP)
optimum. The no-hint arm also reached `OPTIMAL`; this experiment therefore does
**not** establish that the Control hint was necessary or reliably faster.

Private outputs remain in ignored `artifacts/m13e-duck-control-hint/`:
`summary.json`, `duck-no-hint.json`, and `duck-control-hint.json`.

## Controlled design

M13E-A asks whether a complete historical Duck Control `AddHint` changes the
M13D Stage B fixed-frame FP-minimization result.

| Arm | Solver difference | Mathematical model |
| --- | --- | --- |
| `duck-no-hint` | No solution hint | Reconstructed M13D Stage B model |
| `duck-control-hint` | Each Control rectangular candidate hinted to 1; all others hinted to 0 | Identical reconstructed M13D Stage B model |

The hint is guidance, not an equality constraint. A pre-solve gate separately
fixes the Control assignment to verify it satisfies the reconstructed hard
constraints. Both arms used the same 1,449 candidates, locked geometry,
coverage, collision/support/protected-space constraints, per-view M13D
dominance conditions, 60-part cap, candidate order, objective, one worker,
random seed 0, and 30-second deterministic-time budget.

The shared model fingerprint is
`990c2ecc17be40be1b9a5f02672e424481e546184742ad60c51993d64572de0d`.
Saved provenance records the pinned source SHA-256
`77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e`,
the `5 × 7 × 12` grid, wedge `41769a` disabled, OR-Tools `9.15.6755`, and a
passed Control-assignment gate.

## Verified solver results

| Arm | Status | Classification | Aggregate FP objective / best bound | Deterministic time | Wall-clock runtime | Parts | Components |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| No hint | `OPTIMAL` | `PROVEN_UNCHANGED` | 13,735 / 13,735 | 29.94760076388667 s | 147.7620133 s | 40 | 2 |
| Control hint | `OPTIMAL` | `PROVEN_UNCHANGED` | 13,735 / 13,735 | 29.634664530043292 s | 143.2982915 s | 28 | 2 |

The hinted arm used 0.312936233843378 fewer deterministic seconds and
4.4637218 fewer wall-clock seconds in this one pair. That is descriptive only,
not evidence of a reliable speed advantage.

Both arms returned the same three fixed-frame masks and counts:

| View | TP | FP | FN | Fixed-frame IoU |
| --- | ---: | ---: | ---: | ---: |
| Front | 7,803 | 3,940 | 92 | 0.659316 |
| Side | 6,558 | 4,002 | 517 | 0.592038 |
| Top | 7,227 | 5,793 | 28 | 0.553878 |
| Mean | — | 13,735 | — | 0.601744 |

Their frozen `silhouette-v1` results are also identical:

| View | TP | FP | FN | IoU |
| --- | ---: | ---: | ---: | ---: |
| Front | 7,513 | 4,163 | 89 | 0.638589 |
| Side | 6,635 | 3,904 | 163 | 0.619978 |
| Top | 6,963 | 6,213 | 32 | 0.527180 |
| Mean | — | — | — | 0.595249 |

The 40-part no-hint assembly and 28-part hinted assembly are different
three-dimensional arrangements with identical three-view fixed-frame masks and
frozen mean IoU. This part-count difference alone is not a fidelity difference.

## Independent saved-record verification

The saved `summary.json` is `COMPLETE`; its two arm records exactly match their
per-arm files. Without rerunning optimization, both records were reconstructed
and checked using the M13C/M13D reference utilities:

- M13D `validate_view_metrics` accepted every integer TP/FP/FN accounting and
  aggregate FP; each saved objective and best bound is 13,735.
- M13C placement reconstruction and the frozen evaluator reproduced every saved
  `silhouette-v1` view metric and mean IoU.
- The independent M12C/M13D fixed-frame raster comparison reproduced all masks:
  source masks match and each front/side/top XOR, expected-only, and actual-only
  count is zero; saved hashes match on both sides of every comparison.
- Mechanical validation accepted both assemblies: no collisions, invalid
  interfaces, isolated placements, protected-space violations, or unsupported
  placements; the 60-part cap is satisfied and wedge count is zero.

Both assemblies have two connected components. Global connectivity therefore
remains unresolved; M13E-A does not establish connectivity, stability, clutch,
insertion feasibility, or comprehensive buildability.

## What is proved, and what is not

Duck now joins Mansion and Realistic man in having a restricted FP-minimization
optimality proof: in each reconstructed historical M13B candidate model and its
hard constraints, no solution has lower aggregate fixed-frame FP while retaining
every `TP_view >= Control_TP_view` and `FP_view <= Control_FP_view` condition.
For Duck, both M13E-A arms prove the optimum equals the Control aggregate FP,
with zero FP improvement.

This is not a proof of globally optimal IoU. It does not optimize native frozen
`silhouette-v1`, prove an optimum outside the historical candidate set, prove
connectivity, or rule out greater TP coverage at the same FP caps. Frozen
metrics are independent evaluation evidence, not solver objectives or
constraints.

## Next research question: Duck TP coverage

M13C's relaxed candidate-union audit found Duck coverage headroom in all fixed
views. The next question is therefore:

> Under the original historical M13B hard constraints, can Duck increase
> true-positive coverage while preserving `FP_view <= Control_FP_view` and
> `TP_view >= Control_TP_view` in every view?

M13E-A cannot answer it: after minimizing FP to the Control value, its objective
does not prefer extra TP among equal-FP solutions. The 40-part no-hint result
also confirms that alternate feasible arrangements exist despite equal masks and
objective.

## Recommended bounded TP-maximization experiment

Do not modify or rerun M13E-A. Run one separate, offline-only Duck experiment
with the original M13B candidate set, raster definitions, locked geometry, hard
constraints, per-view FP caps, per-view TP floors, 60-part limit, seed, and
30-second deterministic-time budget unchanged. Change only the objective:

```text
maximize TP_front + TP_side + TP_top
```

Keep, for each view:

```text
FP_view <= Control_FP_view
TP_view >= Control_TP_view
```

Use one worker and seed 0. Record solver status, objective/best bound,
deterministic and wall time, selected IDs, parts, every view's TP/FP/FN,
independent fixed-frame mask parity, frozen `silhouette-v1`, and mechanical
diagnostics. Treat `UNKNOWN` as inconclusive and independently validate any
incumbent raster and mechanics before reporting it.

Maximizing total TP is not generally equivalent to maximizing mean IoU because
view IoU denominators include source foreground and FP. But a strictly higher TP
in at least one view, no TP regression in any view, and no FP increase in any
view guarantees a strictly higher mean fixed-frame IoU.

Only after this TP-maximization result should bounded TP/FP trade-off experiments
be designed. They should predeclare small per-view FP allowances or TP floors,
retain the full raw grid, and report a nondominated frontier; they remain
separate from historical benchmarks and production conversion.

## Reproducibility

The private paired runner is opt-in and was not invoked during saved-record
verification:

```cmd
cd backend
uv run python scripts\run_m13e_duck_hint.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-control-hint
```
