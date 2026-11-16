# Milestone 8D: Evaluation Alignment and Baseline Feasibility

## Decision

**B — Feasible-set mismatch, confirmed for Duck and Mansion.** Duck and Mansion
have confirmed experimental-model mismatches; Realistic man is feasible. Completed
assembly evaluator parity is confirmed. Candidate-level exact parity remains
inherently unavailable because frozen bounds depend on the completed selection,
not because a completed-assembly check is unresolved. No fidelity improvement
is claimed.

| Source | SHA-256 | Candidates | Missing candidates | Mandatory coverage | Feasibility |
| --- | --- | ---: | ---: | --- | --- |
| Duck | `77093bb…f11379e` | 1,449 | 0 | fails | **INFEASIBLE** |
| Mansion | `d1a961…919510` | 3,166 | 0 | fails | **INFEASIBLE** |
| Realistic man | `089102…6088bce` | 1,043 | 0 | passes | **FEASIBLE** |

All three V6 builds have zero collision pairs, unsupported evaluated placements,
protected-space violations, and part-cap violations. Duck therefore is not a
physically invalid build.

The earlier three-witness result and the later feasible result were both
independent coverage calculations, not a proof against M8C's actual model.
The later calculation added locked slope source-profile cells, so it correctly
reported physical projection coverage but accidentally treated those cells as
CP-SAT coverage. M8C does not do that: its `_build_model` coverage variables
are built only from rectangular candidates in `target`; locked placements are
collision/support inputs and post-solve repair inputs, not fixed coverage.

M8D now fixes every baseline rectangular candidate to its V6 value in M8C's
unchanged hard model, adds the original coverage equalities and part cap, and
solves that fixed selection. The resulting classification is authoritative for
the experimental model:

| Source | Fixed M8C selection status | Missing model witnesses |
| --- | --- | --- |
| Duck | INFEASIBLE | `front(1,10)`, `front(1,11)`, `front(3,10)`, `front(3,11)`, `side(0,8)`, `side(5,4)`, `side(5,6)`, `side(5,7)`, `top(0,5)`, `top(1,0)` |
| Mansion | INFEASIBLE | `side(0,7)`, `side(0,8)` |
| Realistic man | OPTIMAL | none |

This proves a candidate/locked-placement modeling discrepancy, not a physical
invalidity and not an accidentally weakened M8C constraint. The feasibility
record now exposes both `physical_projection_coverage_satisfied` and the fixed
M8C selection status so they cannot be conflated.

## Contract audit

| Concern | M8C objective | Frozen `silhouette-v1` |
| --- | --- | --- |
| Coordinates | Already Y-up normalized and scaled into the fixed V6 grid by the runner. | Receives that same completed-assembly grid coordinate system. |
| Views | Front `(x,z)`, side `(y,z)`, top `(x,y)`; second axis flipped for image Y-down. | Same projections and Y flip. |
| Bounds | One selection-independent `[0, max(source, grid)]` frame per view; no padding. | Bounds enclose source plus final selected boxes/slopes/wedges, then add 1% of each span (minimum `1e-9`). |
| Resolution and rounding | 128²; `round(value * 127)`, clamped. | Same resolution, rounding, and clamping. |
| Geometry | Individual rectangular candidate bodies; locked slopes use end polygons only. | Final assembled rectangular boxes, every slope-prism face, and wedge end polygons. |
| Objective | Fixed-frame union `TP - FP`, with a part-count tie-break. | Dynamic-frame IoU `TP / (source pixels + FP)`. |
| Post-solve mutation | V6 locked-support repair may change the selected incumbent. | Scores the repaired final assembly. |

The source is normalized through `core._normalize_vertices` and scaled via
`core._scale_vertices_to_grid` before both experiments. Ordinary bricks use
their orientation-adjusted rectangular dimensions. Slopes are locked M8C
geometry and have a triangular-prism rendering contract in the evaluator.

The two scores may rank two assemblies oppositely. Dynamic final-geometry
bounds change the source raster when selected output changes; M8C cannot do
that before candidate selection. Even with a common frame, maximizing `TP-FP`
is not equivalent to maximizing `TP/(S+FP)`, and M8C's part tie-break is not
part of IoU. Its simplified locked-slope raster and post-solve repair add two
more possible divergences.

## Exact completed-assembly parity

The earlier `masks_match` field compared the **source mask with the LEGO mask**.
It was a fidelity indicator, not evaluator parity; the field is now named
`source_equals_lego`. Its historical false values are expected at IoU below one.

`compare_frozen_evaluator_parity` now uses a separate diagnostic raster pass and
compares it with the unchanged frozen renderer. It records source and LEGO mask
difference counts, TP/FP/FN equality, IoU equality, and an exact-pixel result.
For Duck V6/M8C, Mansion V6/M8C, and Realistic man V6/M8C, every view had zero
source-mask differences and zero LEGO-mask differences; TP, FP, FN, and IoU
all matched; all six exact-pixel checks passed.

This confirms completed-assembly evaluator parity, including dynamic bounds. It
cannot produce selection-independent candidate masks equivalent to the frozen
metric, because those bounds depend on the final selected geometry.

Focused tests cover ordinary-brick and slope-prism rendering, stable grid
coordinates, deterministic V6 reconstruction on a synthetic GLB, exact
candidate part/position/orientation membership, protected-space and part-cap
violations, and a missing-placement result. Existing M8C tests retain the
explicit regression that its fixed objective frame differs from
`silhouette-v1`.

## V6 baseline feasibility procedure

The runner rebuilds V6 with the M8C controls: Y-up, source evidence `1x`,
target 24, cap 60, fixed grids Duck `5x7x12`, Mansion `7x4x12`, Realistic man
`3x5x18`, and the verified catalogue. It writes only private, gitignored
placement IDs under `artifacts/m8d-evaluation-alignment/`.

For each rectangular baseline part it requires an exact rebuilt M8C candidate
match: canonical part ID, lattice position, and orientation. Non-rectangular
V6 parts become the M8C locked set. It then checks mandatory projection
coverage, protected space, cap, physical collisions, evaluated support, and
candidate membership. A failure is reported as `INFEASIBLE` with stable missing
IDs or the failed guard; it is not labeled a physical defect unless collision
or support actually fails.

Run only with the approved private manifest and GLBs:

```powershell
Set-Location backend
uv run python scripts/run_m8d_evaluation_alignment.py `
  --manifest ..\docs\testing\real-world-glb-benchmark-manifest.json `
  --output-dir ..\artifacts\m8d-evaluation-alignment
```

## M8D objective and ranking comparison

| Source | Raw M8C surrogate V6 -> M8C | Solver encoded objective | Frozen IoU V6 -> M8C |
| --- | ---: | ---: | --- |
| Duck | 6868 -> 5827 | 8,449,124 | .591700 -> .578348 |
| Mansion | 9112 -> 9204 | 29,149,044 | .600598 -> .600598 |
| Realistic man | -5565 -> -5565 | -5,809,877 | .421959 -> .421959 |

Raw values are recomputed fixed-frame `TP - FP` scores and are comparable only
within one source/frame. The solver's encoded objective is different: it
multiplies the union score by a candidate-derived part weight and subtracts the
selected part count as a tie-break. It must not be compared directly to either
raw scores or IoU.

Mansion's raw surrogate improves by 92 while frozen IoU is unchanged because
the two final arrangements have identical frozen masks and TP/FP/FN in each
view, while their fixed-frame candidate-body coverage differs. Realistic man
also has changed placements with unchanged frozen silhouettes. The bounded
M8C incumbents are not global surrogate or IoU optima.

## Recommendation

Reconcile the experimental feasible set before another optimization attempt:
choose either V6's best-effort projection coverage or M8C's hard witnesses,
then compare only baselines feasible under that decision. Keep fixed-frame
scores explicitly labeled as surrogates. Do not add a pixel-level global CP-SAT
model or promote M8C/M8D code to production.

## Validation

Focused pytest, Ruff, targeted mypy, and `git diff --check` passed for this
change. The completed local validation passed 52 pytest tests, Ruff, and mypy
across 90 source files. No external service was contacted.
