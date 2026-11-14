# Milestone 7B: Real-World Geometric Fidelity Investigation

Status: investigation complete. No production converter behavior was changed.

## Executive findings

### Confirmed facts

- All three private corpus meshes are non-watertight. V5/V6 therefore deliberately
  produce zero protected-empty cells; this is conservative behavior, not a failed flood fill.
- With `targetParts=24`, `maxParts=60`, V6/V7 derive an effective grid target of
  `min(24, 60 // 4) = 15`. Their envelopes differ from V4 in every case, so V4 versus
  V6/V7 comparisons and raw millimetre distances are scale-confounded.
- At the V6 grid, final V6 cells have zero false-positive and zero false-negative
  projected cells against the source voxel surface in front, side, and top. The final
  CP-SAT selection preserves its voxel-projection representation.
- The projection hull adds non-source-surface candidate cells before packing: 45/188
  (23.9%) duck, 9/271 (3.3%) mansion, and 19/156 (12.2%) realistic man.
- V6 accepted 0/64 shape-refinement candidates for every model. V7 returns V6 in all
  cases: duck is connected, mansion exceeds 2,000 candidates, and realistic man has
  no verified final connectivity improvement.
- The two unavailable v1 surface metrics are genuine safety-limit outcomes: mansion
  has 39,996 faces and realistic man 38,950, both above the 20,000-triangle limit.

### Supported hypotheses

- The capped grids (5x7x12, 7x4x12, 3x5x18) and box-and-one-slope vocabulary are
  plausible material representation limits for fine/curved features. Their relative
  contribution has not been controlled against the hard part cap.
- Projection-hull depth ambiguity can cause volume-filled-looking regions. Its
  pre-packing candidate cells prove the mechanism exists, but not its exact visual
  contribution at a fixed physical scale.
- V7 did not change final geometry in these runs because it retained V6. This establishes
  no observed V7 improvement here, not that connectivity can never improve geometry.

### Unknowns

- Open reconstructed meshes do not reveal trustworthy intended interior volume or
  distinguish every apparent hole from reconstruction noise.
- Current public settings cannot hold grid/envelope fixed while varying the part cap;
  they cannot causally separate resolution from cap. Post-hoc resizing is not equivalent
  LEGO geometry.
- Silhouette metrics omit depth/concavity; v1 surface distance is unavailable for two cases.

## Reproduction

Sources remain private local artifacts and are not included here.

| Field | Value |
| --- | --- |
| Code revision | `f8c2714e01fe6b8311b0c836d8745849bb023d71` |
| Duck SHA-256 | `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e` |
| Mansion SHA-256 | `d1a9618613f251d528eccc12f99460f9a64c39e83b8b9267e2c4a2b923919510` |
| Realistic-man SHA-256 | `0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce` |
| Settings | `targetParts=24`, `maxParts=60` (V6/V7), `upAxis=y` |
| Baseline | ignored local `artifacts/m7b-three-models-fixed/summary.json` |
| New output | ignored local `artifacts/m7b-investigation/stage-attribution-v1.json` |

From `backend/`:

```powershell
uv run python scripts/diagnose_m7b_geometry.py `
  --manifest ..\artifacts\m7b-corpus\manifest.json `
  --output ..\artifacts\m7b-investigation\stage-attribution-v1.json `
  --target-parts 24 --max-parts 60
```

The runner verifies hashes, records only counts/hashes/settings, and changes no production
behavior. It intentionally excludes runtime so repeated JSON output is byte-stable; timing is
environment-dependent and belongs in the separate benchmark record.

## Quantitative baseline

`unavailable` is not zero; v1 declined the calculation.

| Model / algorithm | Grid | Envelope mm | Parts | IoU | Components | Collisions | Surface metric | Runtime s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Duck V4 | 5x8x12 | 40x64x38.4 | 26 | .6054 | 1 | 5 | 2.768 mm chamfer | 11.86 |
| Duck V6/V7 | 5x7x12 | 40x56x38.4 | 29 | .5917 | 1 | 0 | 2.749 mm chamfer | 17.80 / 18.12 |
| Mansion V4 | 8x5x15 | 64x40x48.0 | 50 | .6382 | 4 | 0 | unavailable | 20.19 |
| Mansion V6/V7 | 7x4x12 | 56x32x38.4 | 27 | .6006 | 6 | 0 | unavailable | 29.26 / 33.79 |
| Realistic man V4 | 4x6x24 | 32x48x76.8 | 39 | .4778 | 3 | 0 | unavailable | 25.22 |
| Realistic man V6/V7 | 3x5x18 | 24x40x57.6 | 22 | .4220 | 2 | 0 | unavailable | 17.12 / 36.45 |

V4 duck collisions are historical frozen-baseline evidence; V5/V6 prevent them without altering V4.

## Actual pipeline audit

1. `_load_mesh` loads GLB through `trimesh.Scene.to_geometry`; it rejects invalid,
   non-triangle, over-16-MiB, and over-100,000-face input.
2. `_normalize_vertices` maps the requested up axis and translates minima to zero.
   `_scale_vertices_to_grid` independently fits each axis to the chosen integer grid:
   this is anisotropic normalization, not preserved source-world scale.
3. V3 voxelizes the scaled triangle surface at pitch 1.0, selects a grid from budget
   factors, locks eligible 4286 slopes, then greedily packs remaining surface cells.
4. V4 builds a three-orthographic-projection hull from V3 cells and uses CP-SAT to
   maximize required projected pixels then minimize parts. It does not optimize source
   distance, concavity, volume, or perspective appearance.
5. V5/V6 lower the V3 grid target under a cap, protect exterior empty cells only for
   watertight meshes, reject locked-slope collisions, enforce the cap, and repair support.
   V6 tries at most 64 local 4286 replacements and retains only fully safe fidelity gains.
6. V7 starts from V6; it accepts only a complete-model, strict component improvement
   with no available geometric-metric regression. Otherwise it returns V6.
7. `silhouette-v1` rasterizes continuous source triangles and LEGO primitives at 128px.
   `placement-surface-proxy-v1` samples 384 points per surface and uses nearest triangles.

### Capped V6 stage attribution

| Model | Grid cells | Source occupied | Eligible rectangular target | Hull additions | Final occupied | Final-only | Projected FP / FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Duck | 420 | 165 | 188 | 45 | 124 | 17 | 0 / 0 in each view |
| Mansion | 336 | 269 | 271 | 9 | 130 | 1 | 0 / 0 in each view |
| Realistic man | 270 | 137 | 156 | 19 | 120 | 11 | 0 / 0 in each view |

`Eligible rectangular target` is the projection-hull candidate volume after locked-slope exclusion;
`Hull additions` is candidate-space expansion beyond source surface cells. `Final-only` is actual
final-model occupancy beyond those source surface cells, but neither metric proves overfilling of
the unobservable true volume of an open mesh. Projected FP/FN are available only in the source-voxel
grid representation, not as continuous-triangle or perspective measures. They establish that CP-SAT
preserved this grid projection; they do not isolate the cause of triangle-raster IoU loss. Reachable
candidates were 1,449, 3,166, and 1,043. Protected cells were zero; all 64 V6 shape candidates
were rejected in every model.

## Scale, topology, and metrics

V4 target 24 and capped V6/V7 effective target 15 produce different grids/envelopes. Only V6
versus V7 is a matched-scale comparison, and their equal geometry is a valid no-improvement result.
A controlled study needs the smallest new seam: a diagnostic-only runner accepting validated explicit
`GridSize` plus separate `maxParts`, while retaining all safety gates. It should test fixed-grid/
varied-cap and fixed-cap/varied-grid matrices, reporting grid/envelope, solver status, runtime,
cells, parts, candidates, and silhouette. Do not rescale completed models.

### Subsequent controlled-experiment seam specification

The later investigation-only seam must normalize each source once with the existing up-axis mapping,
then use an explicitly supplied source-aligned `GridSize` for voxelization and all subsequent V5
steps. Its physical envelope is therefore exactly `widthStuds * 8 mm`, `depthStuds * 8 mm`, and
`heightPlates * 3.2 mm`; no completed geometry is resized. `maxParts` is passed only to the existing
CP-SAT part-limit and repair-limit checks. A separately fixed `solverTargetParts` controls the existing
deterministic solver-budget selection and must be held constant in a cap sweep.

The runner must be offline-only and must not be accepted by API settings, workers, or the production
`convert_glb` dispatch. It must retain input limits, `MAX_GRID_CELLS`, protected-empty calculation,
locked-slope body exclusion, reachability pruning, V5 repair, hard cap, buildability, and physical
collision checks. It uses the frozen `silhouette-v1` and existing benchmark schemas unchanged, adding
a new diagnostic record version rather than changing historic metrics. The declared matrix must have
small prevalidated grids and caps, emit no private bytes/paths, and fail a point honestly when existing
solver/candidate bounds prevent a result.

For open meshes `_v5_protected_empty_cells` returns early by design: it must not declare uncertain
interior/exterior topology. Zero protections can contribute to filling, but no current evidence makes
any particular void safe to protect. A future negative-space experiment needs conservative,
projection-visible opening evidence and fixture regressions; it must not infer all unoccupied cells
as holes.

V1 rejects a surface if either triangle set exceeds 20,000 before nearest-distance work. Do not raise
that limit or rename v1. Add a separately versioned `placement-surface-proxy-v2-chunked` evaluator:
fixed deterministic area-weighted samples, bounded triangle chunks, explicit sample/chunk/work limits,
and persisted unavailable reasons. Chunking bounds memory; area weighting reduces tessellation bias;
fixed sampling is reproducible. V2 is not comparable with historical v1 records and must be stored
alongside them.

## Connectivity versus geometry

| Model | V7 result | Evidence |
| --- | --- | --- |
| Duck | V6 retained | Baseline already has one component. |
| Mansion | V6 retained | 3,173 candidates exceeds the 2,000 candidate bound. |
| Realistic man | V6 retained | 1,043 candidates, 32,922 verified pairs, 2,000 modeled edges, feasible in 10.50 s; no final component improvement. |

Increasing V7 limits would increase bounded-model work. The current evidence does not show it would
improve fidelity, so it is not recommended before the controlled grid/cap experiment.

## Failure taxonomy and ranked options

| Category | Evidence across corpus |
| --- | --- |
| Source topology | All non-watertight; zero safe protected-empty cells. |
| Quantization | Observed coarse grids; a material contribution is plausible but unisolated. |
| Projection-hull ambiguity | 45, 9, and 19 candidate-space additions before packing; visual contribution unisolated. |
| Solver objective | Optimizes three projected pixels, not 3-D distance/concavity. |
| Vocabulary | Rectangles plus 4286; all 64 local substitutions rejected. |
| Benchmark limits | Scale confounds all V4-V6/V7 pairs; v1 unavailable for two sources. |

| Rank | Improvement | Benefit and measurement | Complexity / risk |
| ---: | --- | --- | --- |
| 1 | Fixed-grid/cap diagnostic seam | Separates resolution from cap with fixed-envelope records. | Small, diagnostic-only, low risk. |
| 2 | Chunked surface metric v2 | Measures large meshes; verify determinism and v1 agreement below 20k. | Moderate, low risk if separately versioned. |
| 3 | Conservative visible-opening experiment | Measure false-fill reduction and fixture regressions. | Moderate, high topology risk. |
| 4 | Higher fixed-grid evaluation | Establishes whether detail changes real-source fidelity. | Moderate solver-cost risk. |
| 5 | More mechanically verified shapes | Potentially improves curves/roofs after evidence. | High calibration/safety risk. |

## Recommendation

Implement **only the diagnostic fixed-grid versus hard-cap experiment seam** next. It answers the
blocked causal question without changing API defaults, mechanics, or production output.

Acceptance criteria:

1. Explicit `GridSize` is accepted only by an offline diagnostic runner.
2. The three hash-pinned local models run a small fixed-grid/varied-cap and fixed-cap/varied-grid matrix.
3. Records include source hash, grid/envelope, cap, parts, candidates, solver statuses, runtime,
   stage cells, and silhouette metrics.
4. Protected-space, support, collision, and hard-cap checks remain unchanged.
5. Focused deterministic tests pass and outputs remain under ignored `artifacts/`.

## Validation

Executed locally:

```powershell
Set-Location backend
uv run python scripts/diagnose_m7b_geometry.py ...
python -m pytest -q tests/test_conversion_benchmark.py --basetemp .pytest_tmp/m7b-benchmark-only
```

The diagnostic completed and wrote the ignored JSON. The benchmark-focused test file passed
25 tests in 24.62 s. An attempted broader V4/connectivity run exceeded this environment's
30-second command window after emitting 51 passing-progress dots, so it is not recorded as a pass.
Initial lint/format reported two line/format issues in the new script; those were fixed. Final Ruff
check and format check passed. The investigation runner's synthetic tests cover deterministic output,
manifest hash rejection, manifest/settings mismatch, and malformed GLB failure. Final focused
validation: the benchmark and diagnostic test files passed 29 tests in 27.91 s; Ruff check/format check passed; `mypy
scripts/diagnose_m7b_geometry.py` passed; and `git diff --check` passed.
