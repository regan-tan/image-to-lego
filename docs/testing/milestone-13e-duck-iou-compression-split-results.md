# M13E-B3.4 — Compressed exact Duck per-view IoU-dominance proof

M13E-B3.4 is an opt-in, offline-only completion of the three-arm exact B3
study. It does not change production conversion, candidate geometry, source
rasterization, the frozen evaluator, historical mechanical/coverage
constraints, or previous artifacts. No private experiment was run while
implementing this runner.

For every fixed-frame view, it retains the exact integer expression:

```text
D_v = (S_v + FP_control_v) * TP_v - TP_control_v * (S_v + FP_v)
```

The accepted B3.3 front-strict record in
`artifacts/m13e-duck-iou-compressed-fixed01/` is recorded as immutable
historical evidence and is not rerun. It proved the front arm `D_front >= 1`,
`D_side >= 0`, `D_top >= 0` infeasible using the compressed model (1,799
variables, 1,978 constraints; versus 34,990 and 35,169 for the original),
with zero raster XOR in its Control preflight. Its prior
`PROVEN_NO_PER_VIEW_DOMINANCE` label applies to that **front arm only** and is
not a combined three-view conclusion.

This runner builds fresh compressed CP-SAT models and solvers for the two
remaining, objective-free arms:

```text
side-strict: D_front >= 0, D_side >= 1, D_top >= 0
top-strict:  D_front >= 0, D_side >= 0, D_top >= 1
```

Both retain the pinned Duck SHA-256, 1,449 candidate identities and ordering,
three locked placements, candidate/source raster masks, historical hard
constraints, 60-part cap, wedge exclusion, seed 0, one worker, and a 30-second
deterministic-time budget. There are no TP floors, FP caps, Control hints,
connectivity constraints, or optimization objective.

Each fresh arm separately verifies source/candidate provenance, compressed
locked/source accounting, compressed-versus-uncompressed model parity data,
historical Control candidate selection, forced-Control feasibility, independent
full-resolution mask and mechanical checks, and the exact dominance expression.
A feasible witness is independently reconstructed and must pass exact TP/FP/FN,
dominance, raster, frozen `silhouette-v1`, mechanical, and connectivity checks.
`UNKNOWN` remains inconclusive. Any parity or witness-verification failure is
reported as `VALIDATION_FAILED`, never as a proof.

The combined result is `VERIFIED_PER_VIEW_DOMINANCE` if either fresh arm has a
verified witness, `PROVEN_NO_PER_VIEW_DOMINANCE` only if the referenced front
arm plus both fresh arms are `INFEASIBLE`, and `INCONCLUSIVE` if no witness
exists and an arm is `UNKNOWN`.

Run explicitly from Windows CMD:

```cmd
cd backend
uv run python scripts\run_m13e_duck_iou_compressed_split.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-iou-compressed-split
```

The command refuses to overwrite an existing output directory and writes
ignored `summary.json`, `duck-front-strict.json` (the historical reference),
`duck-side-strict.json`, and `duck-top-strict.json` there.
