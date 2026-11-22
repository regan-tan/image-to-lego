# M13E-B5 — Mean-IoU-Guided Duck witness search

M13E-B5 is a separate, opt-in, offline-only Duck search. It uses the verified
compressed B3 representation: pinned Duck source, the original ordered 1,449
rectangular candidates, three locked placements, historical occupancy/support/
protected-space/coarse-coverage constraints, disabled wedge `41769a`, and the
60-part cap. It does not add a connectivity constraint. It retains the
historical raster semantics and independently evaluates frozen `silhouette-v1`.

It deliberately removes all B3 per-view IoU-dominance constraints, B4 target
gain/loss thresholds, and M13D TP/FP envelopes. The historical Control is
forced through the compressed and uncompressed models before searching, and its
independent raster XOR must be zero. The Control remains feasible.

For a view `v`, with `d0_v = S_v + FP0_v`, the maximised surrogate is the
variable portion of:

```text
J = sum((TP_v - TP0_v) / d0_v - TP0_v * (FP_v - FP0_v) / d0_v²)
```

The constants are omitted. Reference coefficients are exact Python
`Fraction`s, multiplied by `100,000,000`, then rounded to the nearest integer;
an exact half rounds away from zero. The baseline Duck coefficients are:

| View | TP coefficient | FP coefficient |
| --- | ---: | ---: |
| front | `8450` | `-5571` |
| side | `9028` | `-5345` |
| top | `7664` | `-4245` |

The implementation records exact fractions, per-coefficient quantisation error
(at most one half integer unit), and a conservative absolute objective bound
using the 128-by-128 raster limit before adding the CP-SAT objective. It rejects
any bound outside signed int64. It uses a fresh model and solver, seed 0, one
worker, and a 30 deterministic-second limit. No hint is installed.

Every returned incumbent is reconstructed and independently checked for source,
candidate, and placement provenance; full-resolution raster parity; exact
TP/FP/FN; rational per-view and mean IoUs; frozen evaluator result; collisions,
support, protected spaces, part cap, and connectivity. The output records all
placement IDs and their SHA-256 hash.

The surrogate is a first-order approximation, not the mean-IoU objective. An
`OPTIMAL` response proves only surrogate optimality. A synthetic regression
test demonstrates that the surrogate can rise while exact mean IoU falls.
Failure to find an exact mean-IoU improvement therefore proves nothing about
whether one exists. Frozen `silhouette-v1` may disagree with fixed-frame IoU,
and connectivity remains only a reported mechanical property.

No private optimization was run while implementing this pilot. Run it explicitly
from Windows CMD:

```cmd
cd backend
uv run python scripts\run_m13e_duck_mean_iou_guided.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-mean-iou-guided
```

The ignored output directory is refused if it already exists.
