# M13E-B3.2 - Duck front-strict CP-SAT bottleneck diagnostic

M13E-B3.2 is an offline diagnostic of the existing M13E-B3.1 front-strict
model. It does not modify production conversion, candidate geometry, the
historical B3/B3.1 mathematics, source masks, or accepted artifacts.

## Confirmed run finding

The private front-strict diagnostic completed the existing forced-Control
parity gates, constructed the exact B3.1 front arm, and returned `UNKNOWN`.
It did **not** prove that strict per-view dominance is infeasible.

The captured CP-SAT evidence reports:

- 34,990 Boolean variables: 1,449 candidate-selection variables and 33,541
  pixel-coverage variables.
- 33,541 `kLinMax` coverage constraints containing 4,212,899 expressions.
- SAT presolve initially expanded to about 4.28 million clauses.
- A presolved model with 23,804 variables, 32,126 constraints, and 2,292,966
  terms.
- `Stopped after presolve`, followed by final status `UNKNOWN`.
- 30.4999 seconds deterministic time and 156.582 seconds wall-clock time.
- No search branches and no incumbent.

Therefore, presolve/model processing consumed the run budget before CP-SAT
search began. This is a bottleneck finding, not an infeasibility result and not
evidence that the strict-dominance problem has no solution.

## Artifact capture behavior

The runner writes `solver.log` and `solver-response.txt` before deriving model
metadata. It captures the log in the solver response and disables CP-SAT's log
stdout output, so the complete saved log is not echoed to the console. If an
optional later step, including the model fingerprint export, fails, those raw
files remain and the runner writes `diagnostic-artifact-failure.json` when
possible, reports `Diagnostic artifact failure` on stderr, and returns exit
code 2. This is intentionally distinct from the solver's own status.

The fingerprint is SHA-256 over an OR-Tools 9.15 `CpModel.export_to_file()`
binary `.pb` export. The temporary export directory is removed after hashing.

## Exact candidate-incidence compression proposal

Do not change B3/B3.1 until this reformulation receives separate review and
regression coverage. The following is an exact proposed representation for the
coverage portion of the model.

For every non-locked raster pixel `p`, let `I(p)` be the ordered set of
candidate indices whose raster contains `p`. The current model creates:

```text
c_p = OR(x_i for i in I(p))
```

where `x_i` is the candidate-selection Boolean. Partition pixels by identical
`I(p)`, regardless of their location or view, and create one Boolean per
nonempty incidence set:

```text
y_I = OR(x_i for i in I)
```

For each group, retain integer weights by `(view, source-mask membership)`:
`n_tp[view, I]` is the number of foreground pixels and `n_fp[view, I]` the
number of background pixels. Replace the per-pixel sums with:

```text
TP_view = locked_foreground[view] + sum(n_tp[view, I] * y_I for I)
FP_view = locked_background[view] + sum(n_fp[view, I] * y_I for I)
FN_view = source_foreground[view] - TP_view
```

This is exact for every possible candidate-selection assignment: each pixel in
a group has precisely the same Boolean formula, so `c_p = y_I`; grouping only
collects equal terms in the TP/FP sums. It does not depend on a particular
solver incumbent or on feasibility of the assignment.

Locked-geometry pixels have constant coverage one and remain in the existing
`locked_foreground` / `locked_background` constants. Pixels with empty
candidate incidence have constant coverage zero: foreground pixels remain in
the fixed source total and therefore contribute to FN, while background pixels
contribute zero FP. `fixed_coverage_pixels` still affects the existing
mandatory-coverage constraint exactly as today; it does not alter the TP/FP
formula or justify changing any other B3 hard constraint. Source-mask
membership is preserved only as the TP versus FP weight, never discarded.

## Pinned-Duck estimate without solving

Using the pinned Duck candidate rasters and no CP-SAT optimization, the 33,541
candidate-touchable, non-locked pixels form 350 distinct candidate-incidence
sets. Replacing only the coverage representation would therefore remove 33,191
coverage Booleans and 33,191 `kLinMax` constraints (98.96% of each). The whole
unpresolved model would fall from 34,990 to about 1,799 variables and from
35,169 to about 1,978 constraints, before any solver presolve.

The current `kLinMax` formulas contain 4,212,899 candidate references. One
formula per incidence group would contain 63,091 references: 4,149,808 fewer
(98.50%). The largest one group represents 468 pixels. The inspection also
found 3,942 locked-geometry output pixels and 570 source pixels with constant
zero candidate coverage; neither needs a coverage Boolean. These are static
raster counts, not an optimization result or a runtime-performance claim.

## Rerun command

Run explicitly from Windows CMD, choosing an empty output directory so prior
diagnostic artifacts are never overwritten:

```cmd
cd backend
uv run python scripts\run_m13e_duck_solver_bottleneck.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --output-dir ..\artifacts\m13e-duck-solver-bottleneck
```
