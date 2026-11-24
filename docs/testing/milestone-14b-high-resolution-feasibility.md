# M14B — High-Resolution CP-SAT Feasibility Investigation

## Final status

**Completed with a negative practical scalability result for the current M14B.1 warm-start construction.**

This is an offline-only diagnostic. It does not change production conversion routing, the reliable
grid divisor, catalogue, constraints, solver budgets, APIs, workers, persistence, or benchmark
definitions. Private inputs and reports remain ignored under `backend/artifacts/`. M14A's exact
locked-body collision-filter optimization is preserved; it is not the cause of this result.

The native Windows seed-repaired run was manually interrupted after more than 20 minutes. Its
traceback located the interruption in recursive support closure:

```text
run_experiment()
  -> diagnose_and_construct_seed()
  -> _support_closed_selection()
  -> add(candidate_id)
  -> add(producer)
  -> add(producer)
  -> repeated recursive calls
  -> selected.clear()
  -> KeyboardInterrupt
```

The run did not reach either CP-SAT arm for the repaired seed. Therefore no completed hinted solver
result exists. This does not disprove warm-start optimization; it shows that the current recursive
procedure used to construct a complete valid hint is impractical on this workload.

## Baseline evidence

Experiment E requests `targetParts=300` and `maxParts=1200`, selecting the unchanged reliable
V5/V6 grid target `min(300, 1200 / RELIABLE_HARD_CAP_GRID_DIVISOR) = 300`. The pinned Y-up GLB
resolves to a `23 x 23 x 57` grid (30,153 cells).

Completed preflight measured 22,177 triangles, 3,137 source-occupancy cells, 7,971
projection-hull cells, 24 locked placements, 141,249 candidates before locked-body collision
filtering, 140,890 after it, and 140,401 after support reachability. M14A removes only 359
candidates for this input. The 140,401 retained selection variables remain the observed
high-scale problem; M14A removes repeated collision-filter geometry work, not CP-SAT or
warm-start-construction scaling.

The native unhinted 20-unit solve built 158,273 variables, 150,204 constraints, and 1,852 coverage
variables in 17.464 seconds. It used 20.002515 deterministic seconds and 67.766 wall-clock seconds
(744,082 branches, 88 conflicts, 20,012,638 propagations, and 538 LP iterations), returning
`UNKNOWN` without an incumbent. Its best bound of 1,852 is a bound, not a feasible objective.

## Outcomes that must not be conflated

| Investigation state | Observed result | What it establishes |
| --- | --- | --- |
| Original unhinted CP-SAT arm | Completed at the 20-unit deterministic budget with `UNKNOWN` and no incumbent. | The bounded unhinted search exhausted its budget; it does not prove infeasibility. |
| Original V3 seed mapping | Rejected by the warm-start gate as `baseline_candidate_removed_by_reliable_filters`. | Direct V3 placements were incompatible with the reliable retained candidate set. No hinted arm ran. |
| M14B.1 repaired seed construction | Native Windows run exceeded 20 minutes and was manually interrupted during recursive support-chain construction. | The current repair procedure is not practically scalable. This is not a CP-SAT result. |
| Hinted CP-SAT arm | No completed result exists. | No positive or negative conclusion can be made about solver behavior with a completed repaired hint. |

## Exact seed-construction behavior and bottleneck

`diagnose_and_construct_seed()` enumerates original candidate identities, maps each V3 rectangle to
the retained reliable set, and records an identity rejected during initial enumeration, locked-body
collision filtering, or support reachability. Before it builds any solver model, it passes the
compatible retained IDs to `_support_closed_selection()`.

That function creates direct-support metadata for every retained candidate. For each initial
candidate, in stable `(z, candidate ID)` order, its nested `add(candidate_id)` routine:

1. accepts an already selected candidate;
2. snapshots the complete `selected` ID set and `occupied` grid-cell set;
3. rejects cell overlap or a hard part-cap violation;
4. collects the sorted union of candidates that can produce any required direct-support contact;
5. recursively tries producers until one support chain succeeds; and
6. restores both snapshots after a failed producer branch and again when no producer works. On
   success it adds the candidate and occupies its cells.

Base-level candidates have no support contacts. A non-base candidate needs at least one selected
producer from its contact union, matching the stage-one model's existential direct-support rule,
not support under every footprint contact.

Support reachability proves only that a chain is possible in the global candidate graph. It does
not account for cells occupied by earlier seed choices or the part cap. The recursive routine may
therefore try and roll back alternate producer chains. With branch factors `b1, b2, ...`, failed
paths can require work proportional to their product; each branch also copies and restores sets
that grow with the partial seed. Geometry, ordering, overlap, and cap interactions determine the
actual cost, so this implementation has no useful polynomial runtime bound. The observed repeated
`add(producer)` calls and `selected.clear()` restoration are consistent with that backtracking
cost, not CP-SAT search.

## Why the 20-unit budget did not limit this run

`_solve_arm()` alone assigns `solver.parameters.max_deterministic_time = deterministic_time`, just
before `solver.solve(model.model)`. `run_experiment()` first calls
`diagnose_and_construct_seed()` and, if it returns a seed, performs fixed-assignment seed
validation before it creates the unhinted or hinted solve arms. Input preparation, candidate
indexing, recursive seed construction, fixed-seed validation, and model construction are outside
the solver parameter. Deterministic solver time is also a CP-SAT work measure, not a wall-clock
limit.

Thus the 20-unit budget bounded the completed unhinted solve but could not bound repaired
seed-construction runtime. No budget was increased, and M14B will not run another warm-start
experiment.

## Reproducibility and interruption state

The offline diagnostic remains at `backend/app/conversion/m14b_high_resolution_feasibility.py`; the
runner remains at `backend/scripts/run_m14b_high_resolution_feasibility.py`. Neither is imported by
production conversion paths.

After preflight, the runner now writes a durable `running_experiment` record. If Python receives
`KeyboardInterrupt`, it replaces that record with `interrupted`, includes the completed preflight
metadata, and exits with code 130. This is run-state recording only: it does not alter the seed
algorithm, solver budget, or conversion behavior. A process termination outside Python can still
prevent a final record.

Do not rerun this warm-start experiment automatically, increase budgets, or substitute an
unvalidated heuristic. No private model or generated artifact is committed with this report.

## Recommendation

Close M14B. The current recursive global support-chain seed construction is impractical at this
high-resolution workload, while the value of a completed CP-SAT warm start remains untested.

Investigate **scalable hierarchical or localized LEGO packing** as a separate future milestone.
It should define a bounded local or hierarchical construction strategy and validation criteria
before comparison with the current global stage-one model; it must not be treated as a minor M14B
patch.
