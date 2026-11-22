# M13F-B3 — Minimum coarse-violation certificate and importance audit

This opt-in offline study fixes the M13E-B5 Duck surrogate score at `152987135`,
then minimizes the exact 98 historical coarse-coverage violation indicators. It
does not change production conversion behavior or any accepted M13F-B1/B2 artifact.

The runner refuses to overwrite output, requires the historical M13B summary and
the fully verified B2 seven-arm summary, and independently validates the K=35
witness before constructing CP-SAT. Its deterministic limit is 30 seconds, seed
0, and one worker through the shared M13 solver configuration.

From the repository root, the explicit Windows CMD opt-in command is:

```cmd
cd backend && uv run python scripts\run_m13f_duck_minimum_violation_audit.py --manifest ..\artifacts\m7b-corpus\manifest-duck.json --summary ..\artifacts\m13b-duck-final\summary.json --frontier-summary ..\artifacts\m13f-duck-coarse-budget-frontier\summary.json --output-dir ..\artifacts\m13f-duck-minimum-violation-audit
```

`OPTIMAL` proves the minimum. `FEASIBLE` reports only the incumbent upper bound
and CP-SAT lower bound; `UNKNOWN` makes no minimality claim. Every feasible new
witness is independently reconstructed, checked for fixed-frame raster parity,
TP/FP/FN, exact mean IoU, frozen silhouette-v1, mechanical validity, component
count, isolated parts, and unmet requirement identifiers.

The audit reports a requirement's incident-candidate raster union and its local
metrics for the Control and B2 witnesses. This deliberately is not exclusive
pixel attribution: shared false-positive pixels must not be blamed on one
requirement, and observed omission is descriptive rather than causal evidence.
Any source-occupancy-aware exception policy remains a future controlled
experiment, not an implemented production behavior.
