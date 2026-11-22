# M13E-B3 — Exact Duck per-view IoU dominance feasibility

M13E-B3 is implemented as an opt-in, offline, Duck-only CP-SAT satisfaction
experiment. It has not been run by this change. It does not change production
conversion, the catalogue, source data, frozen `silhouette-v1`, or accepted
M13B/M13E results.

The pinned Control has source SHA-256
`77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e`, a
`5 x 7 x 12` grid, 1,449 rectangular candidates, three locked nonrectangular
placements, a 60-part cap, disabled wedge `41769a`, and 128-by-128 fixed-frame
rasters. It independently verifies source foreground counts of 7,895 / 7,075 /
7,255 and Control TP/FP counts of 7,803/3,940; 6,558/4,002; and 7,227/5,793
before searching.

For each view `v`, the model uses integer counts only:

```text
D_v = (S_v + FP_control_v) * TP_v - TP_control_v * (S_v + FP_v)
D_front >= 0
D_side >= 0
D_top >= 0
D_front + D_side + D_top >= 1
```

This is exact cross multiplication of fixed-frame IoU. There is no objective,
and no floating point tolerance or rounded IoU is used to determine feasibility.
Unlike B1/B2, B3 deliberately adds neither per-view TP floors nor FP caps. The
existing historical candidate identity/order, occupancy exclusion, verified and
locked support, mandatory coverage, locked geometry, protected-space handling,
disabled wedge, and part limit remain hard constraints.

Before the strict model is built, the runner fixes all rectangular candidate
variables to the saved Control selection in a separate feasibility model without
the strict sum condition. It validates source/candidate/locked identity,
independent fixed-frame metrics, zero-XOR masks, mechanics, and `D_v = 0` in all
views. Any failure is `MODEL_PARITY_FAILED`; strict infeasibility is never used
to question Control feasibility.

The strict model uses one worker, seed 0, and a 30-second deterministic budget.
`OPTIMAL` or `FEASIBLE` means a verified dominating witness was found, not an
IoU optimum. `INFEASIBLE` means `PROVEN_NO_PER_VIEW_DOMINANCE` in this exact
candidate model; `UNKNOWN` is `INCONCLUSIVE`. Every returned witness is
independently re-rendered, checked for zero-XOR parity, recomputed for exact
`D_v`, assessed with frozen `silhouette-v1`, and mechanically validated. Frozen
improvement is reported only when the independent frozen mean actually improves.

Run the private experiment explicitly from Windows CMD:

```cmd
cd backend
uv run python scripts\run_m13e_duck_iou_dominance.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-iou-dominance
```

It writes ignored `summary.json` and `duck-iou-dominance.json` files in the
specified output directory. No private optimization was run while implementing
or validating this experiment.
