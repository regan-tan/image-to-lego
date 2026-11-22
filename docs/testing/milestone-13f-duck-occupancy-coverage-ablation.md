# M13F Duck source-occupancy coverage ablation

This is an opt-in, Duck-only diagnostic. It does not change production conversion behavior.

The historical 98-cell target is generated from occupied coarse 3D grid cells and then projected.
The ablation independently compares each projected unit-cell's pinned fixed-frame raster rectangle
with the fixed-frame source silhouette. A requirement can therefore be geometrically legitimate in
the 3D conservative envelope while its 2D source-raster rectangle contains no foreground pixels.
This study records that discrepancy; it never removes or relabels historical cells.

Policies are predeclared, inclusive, and use exact `Fraction` comparisons:

- `historical`: all 98 historical requirements.
- `nonempty-source-occupancy`: `sourceForegroundPixels > 0`.
- `source-occupancy-ge-{5,10,25,50}-percent`: `sourceForegroundPixels / pixelCount >= threshold`.
- `fully-relaxed`: no coarse requirements; reference only.

Every result contains each policy's ordered required-cell identity set and SHA-256, full source
occupancy evidence, the source/candidate provenance, and a solver-model SHA-256 per arm. Solves
use fresh CP-SAT models, seed 0, one worker, and the existing 30 deterministic-second limit. The
historical candidate order, locked slopes, objective, collision, support, protected-space, and part
cap constraints are unchanged.

No-solver preflight (the appropriate first command):

```powershell
cd backend
uv run python scripts/run_m13f_duck_occupancy_coverage_ablation.py `
  --manifest ..\artifacts\m7b-corpus\manifest-duck.json `
  --summary ..\artifacts\m13b-duck-final\summary.json `
  --frontier-summary ..\artifacts\m13f-duck-coarse-budget-frontier\summary.json `
  --preflight
```

The same command without `--preflight` runs the private experiment and writes resumable,
atomic checkpoints under `artifacts/m13f-duck-occupancy-coverage-ablation/`. Resume verifies the
preflight policy/provenance configuration before reusing a checkpoint.

The preflight also independently verifies the connected 33-part B2 K=35 witness, its score
`152987135`, and its feasibility under the 50% policy. That establishes an existence and
surrogate-optimality certificate for that policy, but does not assert that a fresh solve returned
the same assembly. Fixed-frame parity and mechanical validation are independently rerun for every
fresh solver witness.

Limitations: these thresholds were chosen from the Duck audit and are not tuned or validated as a
general-purpose policy. A shared surrogate score does not imply the same IoU, placement set, or
connectivity.
