# Milestone 7B: controlled fixed-grid fidelity experiment

## Scope

This is an offline diagnostic only. `fixed_grid_experiment.py` is not imported by
FastAPI, workers, or `convert_glb()`. It uses the existing V5 projection hull,
CP-SAT packing, support repair, protected-space, buildability, collision, and
hard-cap checks. It neither changes a requested grid/cap/solver target nor falls
back silently: invalid settings and infeasible solver outcomes are recorded as
failed records with their reason.

The private input files remain under ignored `artifacts/m7b-corpus/`; outputs
contain hashes and measurements only and are written to ignored
`artifacts/m7b-fixed-grid-experiment/`.

## Reproduction

From `backend/`, run each case separately so every output is durable even if a
later solver run is interrupted:

```powershell
uv run python scripts/run_m7b_fixed_grid_experiment.py `
  --manifest ..\artifacts\m7b-corpus\manifest.json `
  --output ..\artifacts\m7b-fixed-grid-experiment\duck-cap-40.json `
  --case duck --experiment hard-cap --solver-target-parts 24 `
  --fixed-grid duck=5x7x12 --cap 40
```

Repeat with the matrix below. The runner verifies every manifest hash before it
loads a mesh. The submitted matrix used source-aligned fixed grids: Duck
`5x7x12`, Mansion `7x4x12`, and Realistic man `3x5x18`. All dimensions are
`width studs x depth studs x height plates`.

| Experiment | Fixed solver target | Cap | Explicit grids |
| --- | ---: | ---: | --- |
| A: hard cap | 24 | 40, 60 | 5x7x12; 7x4x12; 3x5x18 |
| B: grid | 24 | 60 | baseline grids and 0.8 scale: 4x6x10; 6x3x10; 2x4x14 |

Hashes: Duck `77093bb…f11379e`; Mansion `d1a96186…919510`; Realistic man
`0891024e…6088bce`.

## Results

All completed runs had zero physical collisions, unsupported evaluated pieces,
and protected-space violations. All three sources are non-watertight, so the
conservative protected-empty count was zero.

| Case | Grid / envelope mm | Cap | Parts | Mean silhouette IoU | Hull additions | Final-only cells | Solver |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Duck | 5x7x12 / 40x56x38.4 | 40 | 25 | .585968 | 45 | 23 | OPTIMAL / FEASIBLE |
| Duck | 5x7x12 / 40x56x38.4 | 60 | 29 | .591700 | 45 | 17 | OPTIMAL / FEASIBLE |
| Mansion | 7x4x12 / 56x32x38.4 | 40 | 27 | .600598 | 9 | 1 | OPTIMAL / FEASIBLE |
| Mansion | 7x4x12 / 56x32x38.4 | 60 | 27 | .600598 | 9 | 1 | OPTIMAL / FEASIBLE |
| Realistic man | 3x5x18 / 24x40x57.6 | 40 | 23 | .421959 | 19 | 14 | OPTIMAL / FEASIBLE |
| Realistic man | 3x5x18 / 24x40x57.6 | 60 | 22 | .421959 | 19 | 11 | OPTIMAL / FEASIBLE |

The complete cap matrix below confirms the controls. Within each source pair,
the source hash, exact grid, physical envelope, up axis, solver target (24),
catalogue, projection-hull/packing path, and solver bounds are identical; only
`maxParts` differs. `Candidates` is the post-reachability solver candidate count.

| Case | SHA-256 | Cap | Parts | Solver | Candidates | Runtime s | Mean IoU | Collisions | Components | Constraint / fallback outcome |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Duck | `77093bb…f11379e` | 40 | 25 | OPTIMAL / FEASIBLE | 1,449 | 18.882 | .585968 | 0 | 1 | protected 0; unsupported 0; no fallback |
| Duck | `77093bb…f11379e` | 60 | 29 | OPTIMAL / FEASIBLE | 1,449 | 17.850 | .591700 | 0 | 1 | protected 0; unsupported 0; no fallback |
| Mansion | `d1a96186…919510` | 40 | 27 | OPTIMAL / FEASIBLE | 3,166 | 24.127 | .600598 | 0 | 6 | protected 0; unsupported 0; no fallback |
| Mansion | `d1a96186…919510` | 60 | 27 | OPTIMAL / FEASIBLE | 3,166 | 25.714 | .600598 | 0 | 6 | protected 0; unsupported 0; no fallback |
| Realistic man | `0891024e…6088bce` | 40 | 23 | OPTIMAL / FEASIBLE | 1,043 | 14.616 | .421959 | 0 | 1 | protected 0; unsupported 0; no fallback |
| Realistic man | `0891024e…6088bce` | 60 | 22 | OPTIMAL / FEASIBLE | 1,043 | 11.871 | .421959 | 0 | 2 | protected 0; unsupported 0; no fallback |

`protected 0` is expected: every source is non-watertight, so the production
conservative protected-empty classifier identifies no proven exterior cells.
It is not evidence that source-negative-space protection was disabled.

The coarser-grid runs are recorded as follows. Their physical envelopes differ,
so IoU changes are evidence of the complete resolution-and-scale change, not a
matched-scale distance comparison.

| Case | Grid / envelope mm | Parts | Mean silhouette IoU | Hull additions | Final-only |
| --- | --- | ---: | ---: | ---: | ---: |
| Duck | 4x6x10 / 32x48x32.0 | 15 | .541633 | 11 | 9 |
| Mansion | 6x3x10 / 48x24x32.0 | 10 | .546181 | 0 | 0 |
| Realistic man | 2x4x14 / 16x32x44.8 | 10 | .318762 | 1 | 1 |

Compared with their corresponding cap-60 baseline, the envelope changes are
Duck `40x56x38.4 -> 32x48x32.0` mm, Mansion
`56x32x38.4 -> 48x24x32.0` mm, and Realistic man
`24x40x57.6 -> 16x32x44.8` mm. The observed IoU differences are respectively
`-.050067`, `-.054417`, and `-.103197`. They are **not** causally isolated
resolution effects because each run also changes physical scale and solver
candidate space. No failed case occurred in the submitted matrix; the ignored
older `summary.json` was an aborted pre-fix attempt and is not evidence used by
this report.

Stage projection false positives/negatives are separately retained per view in
each JSON record. They compare source voxels to final voxels; silhouette IoU is
instead the frozen original-mesh metric, so the two must not be conflated.
Runtime and candidate counts are also retained per run (18.88/17.85 seconds for
Duck cap 40/60; environment-dependent runtime is not used for deterministic
comparison).

## Attribution and recommendation

At a fixed grid, raising the cap from 40 to 60 changed Duck IoU by +.005732 and
reduced final-only cells from 23 to 17. The output was not a small local edit:
only 7 placement signatures are shared between the two Duck models; 18
cap-40-only and 22 cap-60-only placements differ (part ID, grid position, and
orientation). The extra cap headroom permits a different feasible solution, but
both second stages are `FEASIBLE`, not an optimality proof. Therefore the data
supports an association with the changed feasible/tie-broken packing result, not
a claim that the cap alone caused the IoU improvement. Mansion and Realistic man
had unchanged silhouette IoU despite cap headroom; Realistic man's component
count changed from one to two, confirming that an unchanged IoU is not unchanged
geometry or connectivity.

The supported discrete attribution is source-surface occupancy -> projection
hull -> final cells. At baseline grids it is Duck `165 -> 188 -> 140`, Mansion
`269 -> 271 -> 130`, and Realistic man `137 -> 156 -> 120`. Thus hull expansion
is 45/9/19 cells before packing; final-only cells are 23/1/14 at cap 40 and
17/1/11 at cap 60. This quantifies representation-stage and packing-stage cell
differences, not continuous source-to-LEGO geometric error. The frozen
triangle-surface metric remains unavailable for Mansion and Realistic man due
to its triangle safety limit, while mesh silhouette IoU cannot isolate depth,
concavity, vocabulary, or physical-scale effects.

Projection-hull expansion already exists before packing (45 Duck, 9 Mansion, 19
Realistic man cells). Final-only cells show additional packing output beyond the
source surface, but do not prove a true-volume error for non-watertight source
meshes. The coarser grids materially lower IoU, especially the realistic man
(.421959 to .318762), though the changed envelope is a stated confounder.

The highest-priority next improvement is a **matched-envelope higher-resolution
diagnostic**: extend the fixed-grid runner with explicitly chosen grids that
preserve a physical envelope, then measure whether finer source occupancy helps
before changing solver objectives or part vocabulary. That directly resolves the
remaining grid-scale confounder without weakening safety rules.

## Focused safeguards

`tests/test_fixed_grid_experiment.py` proves fixed grids and solver targets do
not drift during cap sweeps, grid changes are reflected in output metadata, hard
caps/protected-space/collision checks remain active, invalid infeasible settings
fail explicitly, and repeated runs are deterministic apart from recorded runtime.

## Evidence-audit validation

All commands were run from `backend/` without real cloud/provider calls:

| Command | Outcome | Runtime |
| --- | --- | ---: |
| `python -m pytest -q tests/test_fixed_grid_experiment.py::test_cap_sweep_keeps_explicit_grid_and_solver_target_fixed ...test_grid_change_is_reflected... ...test_fixed_grid_output_preserves... --basetemp .pytest_tmp/m7b-fixed-grid-audit-first` | 3 passed | 26.88 s |
| `python -m pytest -q tests/test_fixed_grid_experiment.py::test_invalid_infeasible_setting_fails_explicitly ...test_repeated_fixed_grid_runs_are_deterministic --basetemp .pytest_tmp/m7b-fixed-grid-audit-last` | 2 passed | 13.61 s |
| `python -m pytest -q tests/test_conversion_benchmark.py --basetemp .pytest_tmp/m7b-evidence-audit` | 25 passed | 23.09 s |
| `python -m pytest -q tests/test_m7b_geometry_diagnostic.py --basetemp .pytest_tmp/m7b-geometry-audit` | 4 passed | 0.89 s |
| `uv run ruff check ...` | passed | — |
| `uv run mypy app/conversion/fixed_grid_experiment.py scripts/run_m7b_fixed_grid_experiment.py` | passed | — |
| `git diff --check` | passed | — |

The first benchmark invocation without `--basetemp` had 13 passing tests and 12
temporary-directory setup errors caused by the sandbox-owned system temp path;
the writable-base-temp rerun above is the recorded result.
