# Milestone 2: Conversion Correctness and Reliability

## Scope and compatibility

`surface-grid-v5-reliable` is an explicit, opt-in conversion algorithm. The
production default remains `surface-grid-v4`, and the frozen
`surface-grid-v4-fidelity-baseline-v1.json` has not been changed. Existing
`targetParts` continues to mean preferred detail, not an output cap.

The opt-in path accepts `maxParts` through the conversion API, persists it in
the existing `conversion_runs.settings` JSON object, and passes it to the
worker. It is rejected for v3 and v4 requests so an older algorithm cannot
appear to honour a limit it does not enforce. The canonical `lego-model.json`
layout is unchanged; its algorithm version identifies the reliable output.

## v4 root causes

* v4 chose its grid from `targetParts`, but neither CP-SAT stage constrained
  total placement count. Local support repair could add parts after packing.
* Its projection hull admits any cell consistent with three silhouette rays.
  Those cells need not be source surface or source interior, so through-holes
  can be filled.
* The global support approximation is intentionally simpler than the verified
  connector analysis. Repair selected smallest direct supporters and had a
  target-independent local allowance, so some otherwise useful local choices
  were unavailable.

## Reliable-path behaviour

The reliable mode reuses v4's catalogue, CP-SAT formulation, and mechanical
connector evaluator. It adds the following bounded constraints:

* `maxParts`, when supplied, includes locked slopes, initial selected
  rectangles, support-repair replacements, and final assembly validation.
  A request whose locked placements already exceed the limit fails explicitly.
  Infeasible or solver-without-incumbent outcomes fail; they are never emitted
  as partial successful models.
* For watertight input, voxel surface cells and flood-fill-proven interior
  cells are permitted. All other cells are protected empty space and are
  removed from the projection-hull candidate volume. The final model is
  checked again against that protected set. Non-watertight meshes impose no
  protected-empty constraint because they cannot prove a closed solid.
* Reliable repair includes all direct supporter alternatives in its local
  closure and has a named, capped candidate budget of 2,000. It uses the hard
  remaining part allowance as well as its local repair allowance. Final
  `analyze_buildability` remains the success gate.
* A cap-aware grid uses a baseline target no higher than one quarter of
  `maxParts`. This deliberately
  prevents a high-resolution v4 hull from consuming the solver's bounded
  search before it can find any cap-respecting incumbent. It is a conservative
  resolution choice, not a claim that detail improves monotonically.

The current buildability result means direct stud connectivity only. It does
not claim collision-free assembly sequencing, stability, insertion
feasibility, or real-world physical strength beyond the existing analyses.

## Phase B diagnostic instrumentation

The offline benchmark record now includes `conversionDiagnostics` for completed
v5 runs. It records the requested cap, selected grid cell classification
(surface, allowed interior, protected empty, and unknown), watertightness,
candidate counts before and after protected-space filtering and after
reachability pruning, locked placement count, both CP-SAT statuses/incumbent
availability, and local repair candidate and selected-placement counts. The
canonical production `lego-model.json` contract is intentionally unchanged.

Reliable support repair also deterministically prunes optional broad-neighbourhood
candidates before CP-SAT variable construction, while retaining mutable
baseline placements and direct/anchored mechanical supporters. If those required
candidates alone exceed the configured bound, the failure is reported as
`candidate_limit_exhausted`; it is not mislabeled as solver infeasibility.
An `UNKNOWN` first-stage solver result is likewise reported as
`reason=limit_exhausted`, distinct from proven `INFEASIBLE`.

## Phase F measured comparison

The frozen v4 record remains the historical reference at
[`surface-grid-v4-fidelity-baseline-v1.json`](baselines/surface-grid-v4-fidelity-baseline-v1.json).
The v5 capped matrix below was run locally on 11 November 2026 with
`targetParts=100`, `maxParts=100`, and `surface-grid-v5-reliable`; records are
in `artifacts/m2-phase-f-v5-capped-100`. Every completed v5 row passed the
final `stud-connectivity-v1` validation. `O/F` means stage one was `OPTIMAL`
and stage two produced a `FEASIBLE` incumbent. Candidate counts are after
reachability pruning. Physical dimensions are the aligned source-grid span in
millimetres, derived from `(grid axis - 1) * unit` (8 mm/stud and 3.2
mm/plate), not an assertion that the assembled model has identical bounds.

| Shape | Status / actual-requested parts | Normalized Chamfer | Mean IoU | Void fill | Grid; aligned span (mm) | Solver effort; runtime |
|---|---:|---:|---:|---:|---|---|
| Box | completed / 64-100 | 0.032162 | 0.731901 | n/a | 9×4×15; 64×24×44.8 | 7,308; O/F; 21.315 s |
| Thin wall | completed / 34-100 | 0.021793 | 0.747921 | n/a | 11×7×6; 80×48×16 | 6,830; O/F; 15.355 s |
| Sphere | completed / 37-100 | 0.046405 | 0.682837 | n/a | 6×6×15; 40×40×44.8 | 3,212; O/F; 15.373 s |
| Cylinder | completed / 46-100 | 0.044789 | 0.773605 | n/a | 6×7×15; 40×48×44.8 | 5,390; O/F; 19.203 s |
| Pyramid | completed / 19-100 | 0.041902 | 0.547905 | n/a | 5×4×15; 32×24×44.8 | 1,242; O/F; 9.377 s |
| L-profile | completed / 47-100 | 0.026378 | 0.690857 | n/a | 8×4×21; 56×24×64 | 5,152; O/F; 19.817 s |
| Ring | completed / 26-100 | 0.028988 | 0.685814 | 53.2295% | 8×8×6; 56×56×16 | 2,960; O/F; 15.229 s |
| Open box | completed / 57-100 | 0.044865 | 0.751596 | n/a | 8×5×15; 56×32×44.8 | 8,652; O/F; 23.927 s |

The uncapped matrix reuses successful current-revision artifacts for unchanged
cases and adds the corrected sphere record at
`artifacts/m2-phase-f-v5-uncapped-sphere`. Its requested target remains 100,
but it has no part cap; comparisons with capped rows are therefore not
controlled fidelity comparisons. All rows passed final mechanical validation
and have `O/F` solver stages.

| Shape | Status / actual-requested parts | Normalized Chamfer | Mean IoU | Void fill | Grid; aligned span (mm) | Candidates; runtime |
|---|---:|---:|---:|---:|---|---|
| Box | completed / 341-100 | 0.032431 | 0.836923 | n/a | 14×7×27; 104×48×83.2 | 46,436; 32.959 s |
| Thin wall | completed / 298-100 | 0.010403 | 0.817272 | n/a | 23×14×6; 176×104×16 | 33,570; 23.308 s |
| Sphere | completed / 292-100 | 0.035489 | 0.794589 | n/a | 10×10×24; 72×72×73.6 | 18,419; 32.490 s |
| Cylinder | completed / 425-100 | 0.029143 | 0.876011 | n/a | 12×14×30; 88×104×92.8 | 68,010; 51.571 s |
| Pyramid | completed / 157-100 | 0.026044 | 0.746171 | n/a | 11×8×27; 80×56×83.2 | 11,299; 16.986 s |
| L-profile | completed / 462-100 | 0.018658 | 0.838745 | n/a | 16×8×39; 120×56×121.6 | 51,128; 36.349 s |
| Ring | completed / 349-100 | 0.017471 | 0.801390 | 35.8031% | 16×16×9; 120×120×25.6 | 25,472; 20.596 s |
| Open box | completed / 444-100 | 0.045664 | 0.871840 | n/a | 16×11×27; 120×80×83.2 | 90,740; 48.080 s |

### Open-box diagnosis and correction

The failed saved capped run was a solver-limit result, not a proof of
infeasibility. Its artifact shows the uncapped-scale 16×11×27 candidate
volume (90,740 candidates), which could not yield an incumbent within the
fixed deterministic stage-one budget. The then-current half-detail capped grid
still had 20,842 candidates at 10×7×18 and also returned `UNKNOWN`.

The cap-aware grid now uses a named divisor of four. The resulting 8×5×15
open-box model has 8,652 reachable candidates, finds an optimal stage-one
incumbent, emits 57 parts under the 100-part cap, and passes the final
collision, protected-space, and mechanical checks. This is a bounded
candidate-space reduction, not a timeout increase or an `UNKNOWN` relabel.
`test_reliable_capped_open_box_produces_a_mechanically_valid_incumbent`
protects that regression.

### Ring opening result

The protected-empty-space implementation works as a constraint but has not
improved the top-view ring score. Direct diagnostics found 96 protected cells
at capped resolution and 648 uncapped; final placement intersections were
zero in both cases. Candidate counts before and after protected-space filtering
were also identical (2,960 capped and 25,472 uncapped), so the projection hull
did not offer any candidate that crossed the protected cells.

Against frozen v4, uncapped v5 at target 100 remains exactly 35.8031% opening
fill (v4 target 100: 35.8031%). Capped v5 is worse at 53.2295%; the frozen v4
target-300 reference is 26.8843%, at a different scale and actual 464-part
output. The residual fill is therefore coarse voxel/raster boundary aliasing,
not a protected-cell or final-intersection failure. No geometric or mechanical
constraint was weakened, and no correction was added without an evidence-based
representation change.

### Acceptance status

Met: hard cap enforcement, capped open-box solver reliability, bounded solver
effort, persisted diagnostics, complete current v5 100-target matrix, and
final mechanical validation for every reported output. Unresolved: capped
fidelity is intentionally lower because the cap-aware grid changes physical
scale, and the ring opening metric has not improved. This is ready for code
review as a reliability correction, but not as acceptance of an opening-fidelity
improvement.

## Running comparisons

From `backend/`:

```powershell
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --full --algorithm surface-grid-v4 --target-parts 100 --output-dir C:\tmp\v4-100
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --full --algorithm surface-grid-v5-reliable --target-parts 100 --max-parts 100 --output-dir C:\tmp\v5-100
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --case ring --algorithm surface-grid-v5-reliable --target-parts 300 --max-parts 300 --output-dir C:\tmp\v5-ring-300
```

Compare only matching fixture hashes and evaluator versions. Keep v4 failures
in the denominator, make unavailable metrics explicit, and retain the
generated JSON/CSV beside the comparison rather than replacing the frozen
baseline.

## Remaining work

A finer opening-preserving representation or metric-backed boundary treatment
would need a separate reviewed design: it must retain the hard part cap,
mechanical validation, and bounded solver model. A target-300 v5 matrix has
not been re-established and must not be inferred from these target-100 runs.

## Final regression validation (11 November 2026)

### Connectivity compatibility correction

The two full-suite failures came from changing the shared
`_safe_interior_cells()` flood fill from its historical 26-neighbour topology
to face-only traversal. A central empty cell connected to a boundary voxel by
an edge or corner was then incorrectly returned as enclosed. This changed the
legacy contract exercised by `test_empty_space_connected_to_exterior_is_not_safe`.

`_safe_interior_cells()` again uses 26-neighbour traversal, so v3/v4 source
occupancy and the frozen v4 baseline retain their established behavior.

V5 protection is intentionally separate in `_v5_protected_empty_cells()`:

* face-reachable empty voxels are protected and cannot be occupied;
* edge- or corner-only paths are left unconstrained rather than asserted to be
  either source interior or protected exterior; and
* non-watertight inputs still receive no protected-empty constraint.

This is the narrowest safe distinction. Face-only protection prevents v5 from
rejecting the sampled sphere and pyramid interiors; treating diagonal-only
topology as protected regressed the capped sphere. Treating it as confirmed
interior could instead fill a thin diagonal opening. The ambiguity is therefore
represented as neither classification, not silently promoted to protected
volume.

The added v5 regression test covers face, edge, and corner paths: a face path
protects the central voxel, while edge/corner-only paths do not. The existing
legacy face/edge/corner tests remain unchanged and pass.

### Fresh artifacts from the corrected revision

The following capped results were generated after the correction, with
`surface-grid-v5-reliable`, `targetParts=100`, and `maxParts=100`. Each
completed conversion passed the converter's final direct-stud mechanical gate;
every actual part count is at or below the requested hard maximum.

| Shape | Status; actual parts | Grid | Mean IoU | Normalized Chamfer | Runtime (s) |
|---|---:|---|---:|---:|---:|
| Box | completed; 64 | 9x4x15 | 0.731901 | 0.032162 | 21.753157 |
| Thin wall | completed; 34 | 11x7x6 | 0.747921 | 0.021793 | 15.517136 |
| Sphere | completed; 37 | 6x6x15 | 0.682837 | 0.046405 | 16.143651 |
| Cylinder | completed; 46 | 6x7x15 | 0.773605 | 0.044789 | 19.618799 |
| Pyramid | completed; 19 | 5x4x15 | 0.547905 | 0.041902 | 10.203835 |
| L-profile | completed; 47 | 8x4x21 | 0.690857 | 0.026378 | 17.780737 |
| Ring | completed; 26 | 8x8x6 | 0.685814 | 0.028988 | 13.222059 |
| Open box | completed; 57 | 8x5x15 | 0.751596 | 0.044865 | 18.736514 |

Fresh uncapped results (`targetParts=100`) were also collected for the
required sphere, pyramid, and ring cases. They remain mechanically gated;
there is no hard maximum in this comparison.

| Shape | Status; actual parts | Grid | Mean IoU | Normalized Chamfer | Runtime (s) |
|---|---:|---|---:|---:|---:|
| Sphere | completed; 292 | 10x10x24 | 0.794589 | 0.035489 | 30.709115 |
| Pyramid | completed; 157 | 11x8x27 | 0.746171 | 0.026044 | 17.256113 |
| Ring | completed; 349 | 16x16x9 | 0.801390 | 0.017471 | 19.286123 |

The latest fresh uncapped cylinder run completed in 51.571488 seconds and
wrote its record under `artifacts/m2-final-v5-uncapped-cylinder`. It produced
425 parts with mean IoU 0.876011 and normalized Chamfer 0.029143; the
conversion diagnostics report `OPTIMAL` first-stage and `FEASIBLE` second-stage
solver results. The prior foreground timeout did not produce an artifact and
is not used for this comparison.

Fresh artifact directories are under `artifacts/m2-final-v5-*`; each record
contains its settings, fixture version/hash, grid, diagnostics, metrics, and
runtime.

### Ring provenance and protection audit

The fresh capped ring record reports 26 parts on a 8x8x6 grid, 53.2295%
opening fill, 96 protected empty cells, and 2,960 candidates both before and
after protection. The fresh uncapped record reports 349 parts on a 16x16x9
grid, 35.8031% opening fill, 648 protected empty cells, and 25,472 candidates
before and after protection. The earlier 48.07% capped figure consequently
does not describe this corrected-revision run; the 53.2295% figure does.

Zero candidates were removed because the v3-derived projection-hull target
already excluded every protected cell in these ring grids. Final
protected-space validation remains enforced, but zero intersections only shows
that the constraint was not active for those candidates; it does not establish
good opening fidelity. The residual opening fill is consistent with coarse
voxel/raster boundary aliasing. A higher-resolution, source-aware treatment is
a separate design problem and has not been added here.

### Cap-aware grid assessment and checks

The `maxParts / 4` grid target completed all eight capped synthetic fixtures
above, including the formerly solver-limited open box. It preserves the hard
cap and bounds the candidate space, but it intentionally reduces detail at
small budgets; it is not a fidelity guarantee. No parameter search or grid
selection rewrite was performed.

Focused topology tests passed: `7 passed in 3.90s`. Ruff passed (`All checks
passed!`) and mypy passed (`Success: no issues found in 81 source files`). The
connectivity regression tests passed (`3 passed`); the combined converter and
v4 solver tests passed (`104 passed`); and the complete backend suite passed
with `502 passed, 32 skipped, 0 failed` in 665.59 seconds.

The 32 skips are understood and unrelated to this feature: 31 optional local
PostgreSQL integration tests require `TEST_DATABASE_URL`, and one optional
local dog-model regression requires the untracked `dog-model.glb` fixture.
Neither skip condition was introduced or changed by the Milestone 2 files.
Milestone 2 is ready for code review and PR preparation, with the documented
ring-fidelity and physical-scale limitations retained.

### Working tree at validation end

Modified files:

* `backend/app/api/v1/conversions.py`
* `backend/app/conversion/benchmark.py`
* `backend/app/conversion/core.py`
* `backend/app/conversion/surface_grid_v4.py`
* `backend/app/domain/jobs.py`
* `backend/app/repositories/conversion.py`
* `backend/app/repositories/sqlalchemy_conversion.py`
* `backend/app/services/conversion.py`
* `backend/app/workers/conversion_worker.py`
* `backend/scripts/benchmark_conversion_fidelity.py`
* `backend/tests/test_conversions.py`
* `backend/tests/test_surface_grid_v4.py`

Untracked file:

* `docs/testing/milestone-2-conversion-reliability.md`
