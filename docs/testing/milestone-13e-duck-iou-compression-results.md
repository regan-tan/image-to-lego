# M13E-B3.3 — Exact pixel-incidence compression

This opt-in offline experiment preserves M13E-B3's candidate variables,
historical mechanical constraints, fixed-frame metrics, and exact IoU-dominance
constraints. It changes only the representation of candidate-driven raster
coverage. No private optimization was run while implementing this change.

For every fixed-frame pixel, locked geometry takes precedence over candidates.
The unique locked-pixel union is counted once per view, split exactly into
foreground TP and background FP constants. It remains constant even when one
or more candidate footprints overlap that pixel. For each non-locked raster
pixel with a non-empty candidate incidence set, the compressed model forms the
sorted tuple of candidate indices that cover it. It creates one Boolean OR for
each distinct non-empty tuple and accumulates separate foreground and
background weights for each view. Foreground pixels with no candidate incidence
remain fixed-zero coverage and therefore contribute to FN; they require no
Boolean. Signature ordering is lexicographic.

For any candidate assignment, locked pixels have coverage one in both models;
non-locked pixels with no candidate incidence have coverage zero in both; and
every remaining pixel has the OR of the same candidate variables in both. Each
incidence group collects only pixels sharing that OR. Multiplying the OR by its
exact per-view foreground/background weights therefore yields the same TP and
FP sums. Thus `FN = sourceForeground - TP` and every integer
cross-multiplied dominance expression are identical. The candidate variables
and every historical mechanical/coarse constraint are constructed unchanged.
This is a proof for arbitrary assignments; the tests additionally enumerate all
assignments in deterministic synthetic examples.

The private Duck run records its own result files and refuses to overwrite an
existing output directory. Its statistics must be obtained from the generated
models; no expected compression count is hard-coded here.

Run from Windows CMD:

```cmd
cd backend
uv run python scripts\run_m13e_duck_iou_compressed.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-iou-compressed-fixed01
```

The runner uses one worker, seed 0, no objective, no hint, and the retained
30-second deterministic-time budget. A future accepted witness must still pass
the independent raster, exact-count, dominance, frozen-silhouette, mechanical,
and connectivity checks already used by B3.
