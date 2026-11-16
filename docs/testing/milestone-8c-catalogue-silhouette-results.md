# Milestone 8C: Catalogue-Constrained Silhouette Optimization

## Decision

**NO-GO for this M8C implementation.** The three SHA-256-pinned private GLBs completed in the offline runner, but none improved frozen `silhouette-v1`; Duck regressed by .013352, beyond the .01 acceptance limit. The experiment is merge-ready only as an offline-only negative-result diagnostic. It must not be promoted to V4–V7 or exposed through the API, workers, or frontend.

This is not proof that a global catalogue-constrained optimum cannot improve these sources. All solves were bounded `FEASIBLE` incumbents, not `OPTIMAL`, and the implemented objective is a surrogate.

## Formulation and feasible set

`backend/app/conversion/catalogue_silhouette_experiment.py` reuses the fixed V6 lattice candidate enumeration, verified rectangular catalogue parts and orientations, cell non-overlap, direct support, required projection coverage, locked supported slopes, V6 local support repair, physical collision exclusion, protected-empty target construction, and the 60-part cap. It is only called by `backend/scripts/run_m8c_catalogue_silhouette.py`.

For each candidate, its actual rectangular part body is rasterized in a 128x128 orthographic view. Locked V6 slopes are fixed geometry. The CP-SAT objective maximizes `true-positive projected pixels - false-positive projected pixels`; false negatives are a fixed source-pixel total minus true positives. Pixel union is modeled with `AddMaxEquality`, so overlap is never counted twice. A deterministic lower-priority part-count term breaks ties.

Pixels with identical selecting-candidate sets and source membership are grouped into one weighted Boolean. This is exact for the fixed-envelope union objective: it does not round, change orientation, or double-count overlap. The model is bounded to 49,152 raw pixels across three views, 4,000 eligible candidates, and 20 deterministic solver-time units. Single worker and seed zero preserve deterministic settings.

It is not the frozen evaluator. `silhouette-v1` derives raster bounds from the source **and final selected LEGO geometry**, with padding. M8C needs candidate masks before selection, so it uses a fixed source-plus-grid envelope and no evaluator padding. Its fixed-slope drawing path also differs from `silhouette-v1`'s prism-face rasterization, and V6 local support repair can change a solver incumbent after objective evaluation. These are confirmed implementation differences. They explain why a higher M8C score does not imply higher frozen IoU; the saved aggregates cannot apportion Duck's regression among the bounds difference, slope drawing, and repair.

With a fixed source mask size `S`, IoU is `TP / (S + FP)`. Maximizing `TP - FP` is not generally equivalent: candidates may exchange TP and FP at different ratios. The part-count tie-break is also outside IoU. Thus M8C remains a surrogate even if it had matched raster masks.

## Candidate and constraint audit

The runner records candidates after V6 collision and support-reachability filtering. Required projection pixels are hard equalities, so an optimizer may alter an outline only where multiple candidates satisfy the same witnesses. Physical collision and unsupported-placement counts, connected components, protected-space violations, part count, V2, and frozen false-positive/false-negative counts are recorded for both variants.

## Real-world results

| Source / hash prefix | Grid | V6 mean | M8C mean | Delta | Parts V6→M8C | Components V6→M8C |
| --- | --- | ---: | ---: | ---: | --- | --- |
| Duck `77093bb…f11379e` | 5x7x12 | .591700 | .578348 | -.013352 | 29→29 | 1→2 |
| Mansion `d1a961…919510` | 7x4x12 | .600598 | .600598 | .000000 | 27→26 | 6→3 |
| Realistic man `089102…6088bce` | 3x5x18 | .421959 | .421959 | .000000 | 22→17 | 2→2 |

| Source | Variant | Front IoU / FP / FN | Side IoU / FP / FN | Top IoU / FP / FN |
| --- | --- | --- | --- | --- |
| Duck | V6 | .638589 / 4163 / 89 | .609331 / 4091 / 163 | .527180 / 6213 / 32 |
| Duck | M8C | .610069 / 4713 / 89 | .597794 / 4353 / 132 | .527180 / 6213 / 32 |
| Mansion | V6 / M8C | .718515 / 3778 / 73 | .561107 / 6203 / 78 | .522172 / 7586 / 0 |
| Realistic man | V6 / M8C | .426276 / 8093 / 121 | .445331 / 5972 / 354 | .394271 / 7713 / 27 |

Duck has +550 front FP with unchanged FN, +262 side FP and -31 side FN, and no top change. Mansion and Realistic man prove that genuine placement/connectivity changes can retain identical silhouettes; silhouette agreement is not a connectivity or assembly-quality proof.

| Source | Candidates / groups | Solver status / objective / bound / gap | Runtime s | Collisions / unsupported / protected |
| --- | ---: | --- | ---: | --- |
| Duck | 1449 / 448 | FEASIBLE / 8449124 / 8449143 / 19 | 24.881 | 0 / 0 / 0 |
| Mansion | 3166 / 577 | FEASIBLE / 29149044 / 29149066 / 22 | 26.974 | 0 / 0 / 0 |
| Realistic man | 1043 / 540 | FEASIBLE / -5809877 / -5809864 / 13 | 22.874 | 0 / 0 / 0 |

No run used fallback. Bounds and gaps apply only to the surrogate objective, never to frozen IoU or a global catalogue optimum.

## Surface V2 and audit limit

| Source | V6 symmetric mean mm | M8C symmetric mean mm | Status |
| --- | ---: | ---: | --- |
| Duck | 2.794217 | 2.910649 | available |
| Mansion | 2.517792 | unavailable | M8C observation timed out |
| Realistic man | 3.122435 | 3.169818 | available |

Duck and Realistic man regress under available V2 observations. Mansion M8C's timeout is not evidence of equality or improvement. All source meshes are non-watertight; projections and V2 do not establish volume, stability, insertion feasibility, or global physical buildability.

The saved records intentionally omit private placement geometry and candidate IDs, while the checked-in manifest has no private sources. Consequently the completed artifacts cannot retrospectively establish whether the exact V6 placement set is feasible in the rebuilt M8C model or calculate its surrogate objective. The baseline may differ because V6 shape-aware refinement, M8C locked non-rectangular placements, candidate filtering, required coverage, and local repair are not a proven identical feasible set. This is a bounded uncertainty, not evidence of a solver fault.

## Synthetic correctness control

`backend/tests/test_catalogue_silhouette_experiment.py` creates two feasible positions under a one-part cap, verifies a safe candidate-limit fallback, and explicitly proves that the selection-independent objective raster differs from `silhouette-v1` for the same geometry because their bounds differ. Existing V6 tests cover retained collision, support, and protected-space gates.

## Running the private comparison

With approved local GLBs and a complete pinned manifest, run:

```powershell
Set-Location backend
uv run python scripts/run_m8c_catalogue_silhouette.py --manifest ..\docs\testing\real-world-glb-benchmark-manifest.json --output-dir ..\artifacts\m8c-catalogue-silhouette
```

Artifacts are gitignored and contain only derived measurement records. The completed run fails promotion: no gain on two sources, Duck regresses beyond .01, and Duck connectivity worsens. Merge the negative-result diagnostic, but do not tune scoring weights or increase solver limits blindly. The next justified direction is a separate representation study that defines a selection-independent metric frame shared by optimization and evaluation (or an exact treatment of the existing dynamic frame), then tests a richer fixed-lattice vocabulary with an explicit baseline-feasibility audit. Continued optimization of this representation is not justified by M8C.
