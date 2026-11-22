# M13F — Duck reconstruction bottleneck audit

M13F is an offline, opt-in diagnostic only. It reconstructs the pinned Duck
source, historical locked placements, ordered rectangular candidate set, and
fixed-frame rasters without creating or solving a CP-SAT model. Its output is
ignored local evidence, never a production conversion artifact.

The audit verifies the source SHA-256, M13B configuration, locked placement
identities, candidate count/order fingerprint, Control membership, Control
fixed-frame TP/FP parity, and candidate-raster versus independent renderer
parity. It records per-view hashes for source, locked, candidate-union, Control,
and rendered-Control masks.

The report distinguishes pixels unavailable to all existing geometry from
pixels that are geometrically coverable but not selected by Control. Candidate
union figures deliberately relax simultaneous selection, occupancy, support,
coarse coverage, cap, and connectivity interactions. They are not a feasible
assembly claim or a causal explanation.

The prepared ablation matrix preserves an unchanged Control arm and the M13E-B5
quantized fixed-frame surrogate. Each diagnostic arm changes only one family:
part cap, mandatory coarse coverage, or support. Any arm relaxing support or
coarse coverage is labelled potentially mechanically invalid and must remain
separate from historically admissible results. For every incumbent, a future
opt-in runner must independently calculate exact fixed-frame and frozen
`silhouette-v1` IoUs. An optimal surrogate result would not prove exact mean
IoU optimality.

Run from Windows CMD (this performs no optimization):

```cmd
cd backend
uv run python scripts\run_m13f_duck_reconstruction_audit.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13f-duck-reconstruction-audit
```

No private optimization was performed while implementing M13F.
