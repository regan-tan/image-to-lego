# M13E-B3.1 — Duck split IoU-dominance feasibility

M13E-B3.1 is an opt-in, offline Duck-only diagnostic following B3's
inconclusive private strict-dominance search. It does not modify conversion,
candidate geometry, frozen metrics, accepted benchmarks, or existing artifacts.
It has not been run by this implementation change.

For each fixed-frame view, B3 defines the exact integer expression:

```text
D_v = (S_v + FP_control_v) * TP_v - TP_control_v * (S_v + FP_v)
```

B3.1 runs three fresh, 30-second deterministic-time satisfaction models:

```text
front-strict: D_front >= 1, D_side >= 0, D_top >= 0
side-strict:  D_front >= 0, D_side >= 1, D_top >= 0
top-strict:   D_front >= 0, D_side >= 0, D_top >= 1
```

This is an exact disjunction of B3's `D_v >= 0` and
`D_front + D_side + D_top >= 1`: for integer values, a nonnegative sum of at
least one has at least one component at least one. Each arm is objective-free,
uses a fresh solver with seed 0 and one worker, and preserves the B3 candidate
set, locked geometry, hard physical/coverage constraints, raster definitions,
disabled wedge, and 60-part cap. B3.1 intentionally has no M13D/B2 TP floors or
FP caps, and no Control hint.

Each arm repeats B3's complete forced-Control preflight and independently
validates any witness through renderer parity, exact integer dominance values,
frozen `silhouette-v1`, mechanical diagnostics, placement/candidate hashes, and
component count. Solver records retain raw status, deterministic/wall time,
response statistics, and model variable/constraint counts without inferring why
an `UNKNOWN` result occurred.

A valid witness from any arm proves original B3 feasibility. Only three
`INFEASIBLE` arms prove no B3-dominating witness in the historical model. An
`UNKNOWN` arm without a witness is inconclusive. A model-parity or verification
failure is not scientific proof. The three-arm study has three times the
per-arm deterministic budget of B3, so wall-clock comparisons are not equivalent
and no speed claim is made.

Run explicitly from Windows CMD:

```cmd
cd backend
uv run python scripts\run_m13e_duck_iou_dominance_split.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-iou-dominance-split
```

The runner writes ignored `summary.json` plus `duck-front-strict.json`,
`duck-side-strict.json`, and `duck-top-strict.json`. No private optimization was
run while implementing or testing B3.1.
