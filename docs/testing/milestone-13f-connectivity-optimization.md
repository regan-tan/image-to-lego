# M13F-B7.2 connectivity-constrained reconstruction

This is an isolated, opt-in research experiment. It does not modify production
conversion, historical B6 artifacts, or the source/candidate universe.

## What is checked

The study reconstructs the selected B6 50%-occupancy witness and enumerates its
candidate-contact graph with the existing calibrated mechanical semantics: exact
world-space matching vertical stud/receiver connectors, with overlapping parts
excluded. It does not infer connections from bounding boxes or proximity.

Small graphs retain the sparse single-commodity-flow formulation. Mansion's
253,666 exact contact edges would create 507,332 directed flow variables before
the original model, so the default is exact iterative separator-cut generation.
After each relaxed CP-SAT solve, every selected component not containing the
root receives complete-boundary cuts. For a fixed root and component `S`, the
runner adds `sum(x_v for v in N(S)) >= x_u` for every selected optional vertex
`u` in `S`. Any connected selected assembly containing `u` must cross from `S`
to a selected outside boundary vertex, so each cut cannot remove a connected
solution. When there is no locked root, a selected root variable inside `S` is
an additional valid way to satisfy the cut.

The runner records every solver iteration: status, objective/bound, selected
count, component sizes, deterministic time, canonical cut identifiers, duplicate
cuts, whether proposed cuts are violated by the source witness, and whether all
previous cuts remain in the next model. If it receives a disconnected witness
but has no new violated valid cut, it terminates as `NO_NEW_VIOLATED_CUT`; it
does not misreport the configured iteration limit. Budgets are configurable with
`--cut-max-iterations` and `--cut-total-deterministic-seconds`.

The output independently recomputes components using the complete exact graph
and runs the existing completed-arrangement validator. The preflight also
compares the indexed connector matcher with the naive exact matcher on a bounded
candidate subset. It does not change contact semantics to reduce graph size.

The first stage pins every fixed-frame projection mask exactly to the B6 witness
and searches only for connected feasibility (no part objective). Only after it
independently verifies a connected witness does a second exact-mask stage
minimize selected parts. The first witness is never called part-minimal.
It groups pixels by their exact candidate-incidence signature, avoiding repeated
equivalent OR constraints. If that is proven infeasible, the second stage pins
Mansion's B6 surrogate score (`162246440`) while allowing masks to differ. Only
if that is proven infeasible does the final stage maximize the existing B5
quantized surrogate under connectivity. `UNKNOWN` and time-limited results are
not described as infeasible.

## Commands

Run the no-solver preflight first (Windows CMD):

```cmd
cd backend
uv run python scripts\run_m13f_connectivity_optimization.py --manifest ..\artifacts\m7b-corpus\manifest.json --m13b-summary ..\artifacts\m13b-mansion-pilot\summary.json --b6-summary ..\artifacts\m13f-cross-object-validation\mansion\summary.json --preflight
```

The same command without `--preflight` runs the cut-generation formulation and
writes atomically resumable private results to
`artifacts/m13f-connectivity-cut-generation/`; add `--resume` to reuse a
checkpoint only after source and selected-witness provenance match. Use
`--connectivity-formulation flow` only for a bounded graph; Mansion correctly
reports it as not solver-ready rather than increasing or truncating its edge set.

```cmd
cd backend
uv run python scripts\run_m13f_connectivity_optimization.py --manifest ..\artifacts\m7b-corpus\manifest.json --m13b-summary ..\artifacts\m13b-mansion-pilot\summary.json --b6-summary ..\artifacts\m13f-cross-object-validation\mansion\summary.json --connectivity-formulation cuts --output-dir ..\artifacts\m13f-connectivity-cut-generation-b7-2-new
```

The final summary separates exact-mask preservation (`fixedMaskXorByView` all
zero), pinned-surrogate preservation, and the connectivity/fidelity trade-off.
It includes fixed-frame IoU, TP/FP/FN, parts, historical coverage checks, model
fingerprints, graph/model sizes, solver status/bounds, and independent witness
validation for each feasible stage.
