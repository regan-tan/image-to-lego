# Milestone 11B: Mechanically Exact Candidate Duplicate Audit

Status: completed offline audit. **NO-GO** for exact candidate elimination.

This change adds no production V4--V7 behavior, CP-SAT pruning, geometry, API, worker, or `convert_glb()` routing change. It reuses M10B/V6 preflight enumeration and reports aggregate data only.

## Decision

The reachable rectangular candidates contain no projection, geometry, mechanical, or fully certified duplicate choices in the three pinned sources at either measured scale. Exact removal cannot reduce Duck from 6,019 or Mansion from 11,066 candidates to the 4,000-candidate gate. No heuristic, approximate geometry, new part family, higher solver limit, or production integration follows from this result.

## Exact duplicate definition

A reported `duplicates` count is candidates beyond one deterministic representative per matching group. The audit never removes candidates.

| Class | Exact signature | Removal status |
| --- | --- | --- |
| Projection-equivalent | Three-view discrete projection pixels derived from occupied cells | Diagnostic only; silhouette equality is not mechanical equivalence. |
| Geometry-equivalent | Cached immutable local physical microcell set, position, orientation, and dimensions | Diagnostic only; it omits catalogue/export identity and global interactions. |
| Mechanically-equivalent | Geometry plus transformed male/receiver connectors, direct-support producer/consumer contacts, and the locked-body result | Diagnostic only; matching local contacts is not a repair/global-constraint certificate. |
| Fully proven | Canonical part ID, origin, normalized orientation, export color fields, occupied cells, physical and mechanical signatures, and projection signature | Only removal certificate. |

No rounding or approximate matching is used. The immutable cached microcell set plus the established placement transform represents the exact current physical proxy without copying an expanded body for every candidate.

The final signature requires canonical part identity and placement identity. This conservatively preserves BOM/export semantics, every collision/non-overlap/support/coverage/cap coefficient, locked-support repair and connectivity interaction, the current coverage then unit-part-count objective, and the serialized placement. Matching a hash, body, projection, or contact subset alone is explicitly not a proof.

## Code-grounded proof obligations

`surface_grid_v4._enumerate_candidates()` creates one candidate per target origin, fitter-enabled rectangular part, and normalized legal orientation (square `0`; non-square `0` and `90`). `_exclude_locked_body_collisions()` and `_support_reachable_candidates()` run before the measured M10B count. `_build_model()` maps selected candidates to occupied cells, witness coverage, direct support, and a part cap. `_repair_locked_verified_support()` recomputes connector relations; final validation recomputes collision, support, protected-space, cap, and `stud-connectivity-v1`; the exporter serializes canonical placements.

The existing CP-SAT stages have no candidate-specific objective coefficient: they maximize coverage and then minimize the count of selected rectangular candidates. M8C pixel-equivalence groups compress only a raster objective, never candidate selection variables. M8D/M9A establish that locked-slope source coverage cannot be omitted. These facts are why the first three classes are diagnostic only.

## Synthetic correctness tests

`backend/tests/test_m11b_exact_duplicate_audit.py` proves a literal repeated candidate is recognized and that the classifier does not mark as removable candidates with:

- matching silhouette but a different physical body;
- matching body but different connector/contact contract;
- changed support eligibility or locked collision context;
- changed occupied-cell/mandatory-witness contribution;
- changed connector data relevant to repair/connectivity;
- distinct part identities/export representations.

There is no current differing per-candidate objective coefficient to synthesize; unit part-count and cell-derived coverage are covered by the full signature.

## Private-corpus measurements

The SHA-256-pinned private GLBs were available locally. Results are aggregate only; no paths, bytes, meshes, placements, or renders are recorded. Audit limits: 12,000 candidates, 180 seconds, and 256 MiB measured analysis memory. Peak memory covers the duplicate-analysis phase after the already-bounded V6 enumeration; runtime includes enumeration and analysis.

| Source / grid | Original candidates | Projection / geometry / mechanical duplicates | Fully removable | Reduction | Resulting variables | ≤4,000? | Runtime / peak memory |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Duck 1x | 1,449 | 0 / 0 / 0 | 0 | 0.0% | 1,449 | Yes | 33.615 s / 6.80 MiB |
| Duck 1.5x | 6,019 | 0 / 0 / 0 | 0 | 0.0% | 6,019 | No | 23.147 s / 17.54 MiB |
| Mansion 1x | 3,166 | 0 / 0 / 0 | 0 | 0.0% | 3,166 | Yes | 4.787 s / 8.96 MiB |
| Mansion 1.5x | 11,066 | 0 / 0 / 0 | 0 | 0.0% | 11,066 | No | 9.952 s / 33.93 MiB |
| Realistic man 1x | 1,043 | 0 / 0 / 0 | 0 | 0.0% | 1,043 | Yes | 1.192 s / 3.19 MiB |
| Realistic man 1.5x | 3,409 | 0 / 0 / 0 | 0 | 0.0% | 3,409 | Yes | 4.653 s / 8.91 MiB |

The 1.5x totals reproduce M10B: Duck 6,019, Mansion 11,066, and Realistic man 3,409. No CP-SAT optimization was run.

## Reproduce

Private aggregate JSON is in ignored `artifacts/m11b-exact-duplicate-audit/`. From `backend` in Windows CMD:

```cmd
uv run python scripts\run_m11b_exact_duplicate_audit.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m11b-exact-duplicate-audit\duck-15x --case duck --scale 1.5x
uv run python scripts\run_m11b_exact_duplicate_audit.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m11b-exact-duplicate-audit\mansion-15x --case mansion --scale 1.5x
uv run python scripts\run_m11b_exact_duplicate_audit.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m11b-exact-duplicate-audit\realistic-man-15x --case realistic-man --scale 1.5x
```

If the corpus is unavailable, use those exact commands and do not infer a result. The runner can run all cases/scales when `--case` and `--scale` are omitted.

## Limitation

This result applies only to the current verified rectangular V6 preflight catalogue, orientations, mechanics, repair, objective, exporter, and M10B grids. A change to any of those needs a new proof audit. Zero exact duplicates is not evidence that approximate, dominance, or source-aware pruning is safe.
