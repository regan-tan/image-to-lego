# Milestone 9A: Experimental Feasibility Results

## Decision

**GO for M9B offline evaluation.** The SHA-256-pinned private Duck, Mansion, and Realistic man corpus has now been run successfully. M9A establishes baseline feasibility, not meaningful production-fidelity improvement or global geometric optimality.

Ignored output, including private placement IDs, is written under `artifacts/m9a-experimental-feasibility/`. `summary.json` was checked against all three case files and contains exactly their records.

```powershell
Set-Location backend
uv run python scripts/run_m9a_experimental_feasibility.py `
  --manifest ..\docs\testing\real-world-glb-benchmark-manifest.json `
  --output-dir ..\artifacts\m9a-experimental-feasibility
```

The committed manifest remains a non-private placeholder. Reproducing this run requires the approved private manifest and pinned GLBs; the placeholder correctly rejects a different corpus.

## Controls

The runner accepts exactly `duck`, `mansion`, and `realistic-man`, verifies each manifest SHA-256 before processing, and holds these controls:

| Case | Fixed grid | Physical envelope (mm) |
| --- | --- | --- |
| Duck | 5 x 7 x 12 | 40 x 56 x 38.4 |
| Mansion | 7 x 4 x 12 | 56 x 32 x 38.4 |
| Realistic man | 3 x 5 x 18 | 24 x 40 x 57.6 |

All runs use Y-up from the pinned manifest, source evidence `1x`, `targetParts=24`, `maxParts=60`, the existing verified catalogue/orientations, and existing deterministic CP-SAT settings. No production route, worker, API, frontend, `convert_glb()` dispatch, frozen historical metric, or LEGO dimension changed.

## Corrected hard-coverage contract

M8D fixed every V6 rectangular selection in M8C's model and found Duck and Mansion infeasible because M8C required rectangles alone to satisfy every projection witness. That model excluded fixed locked slopes from the witness equalities despite their being present in the completed arrangement.

M9A changes only the offline experimental model. It computes `fixed_coverage_pixels` from each existing locked non-rectangular placement's `_placement_source_cells` profile, intersects that set with required witnesses, and asks selectable rectangles to cover only the remainder. It does **not** treat all source occupancy, a slope bounding box, source mesh pixels, or arbitrary locked geometry as coverage. A fixed witness is accepted only when an already locked slope source-profile cell projects to it.

Collision exclusion against locked bodies, direct support/reachability, cell occupancy, part cap, candidate eligibility, protected space, and final mechanical checks remain active. `verify_baseline_feasibility` preserves M8D's historical behavior by default; only M9A supplies the explicit fixed witness set. Historical M8C/M8D records and frozen metrics are not rewritten.

## Baseline gate results

All baseline records have no missing placement IDs or mandatory witnesses, physical projection coverage, a satisfied 60-part cap, zero collisions, zero unsupported placements, and zero protected-space violations.

M8D's unchanged rectangle-only fixed-selection result is the before control:

| Source | SHA-256 | M8D rectangle-only status | M8D missing witnesses |
| --- | --- | --- | ---: |
| Duck | `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e` | INFEASIBLE | 10 |
| Mansion | `d1a9618613f251d528eccc12f99460f9a64c39e83b8b9267e2c4a2b923919510` | INFEASIBLE | 2 |
| Realistic man | `0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce` | OPTIMAL | 0 |

| Source | SHA-256 | Fixed selection | Locked / remaining / required witnesses | Candidates | Collisions | Unsupported | Protected violations | Cap | Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Duck | `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e` | OPTIMAL | 33 / 98 / 131 | 1,449 | 0 | 0 | 0 | satisfied | FEASIBLE |
| Mansion | `d1a9618613f251d528eccc12f99460f9a64c39e83b8b9267e2c4a2b923919510` | OPTIMAL | 12 / 130 / 142 | 3,166 | 0 | 0 | 0 | satisfied | FEASIBLE |
| Realistic man | `0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce` | OPTIMAL | 0 / 122 / 122 | 1,043 | 0 | 0 | 0 | satisfied | FEASIBLE |

The later fixed-frame silhouette optimization returned `FEASIBLE` incumbents, not global `OPTIMAL` proofs: Duck used 448 pixel-equivalence groups and ran 28.066 seconds (objective/bound `11,386,827/11,386,843`); Mansion used 577 groups and ran 25.149 seconds (`29,149,048/29,149,066`); Realistic man used 540 groups and ran 21.442 seconds (`-5,809,877/-5,809,864`). Its objective is historical fixed-frame `TP - FP` with a part-count tie-break. Fixed-selection `OPTIMAL` proves the recorded baseline selection satisfies the corrected constraints; it does not prove global geometric optimality.

## Evaluation alignment

| Quantity | Meaning | Use |
| --- | --- | --- |
| Frozen `silhouette-v1` | Completed assembly in dynamic padded bounds derived from source plus final LEGO geometry | Acceptance measurement |
| Fixed-frame IoU | Exact union IoU in M8C's selection-independent source-plus-grid frame | Bounded reporting surrogate |
| `TP - FP` | M8C's historical fixed-frame objective; its encoded objective also has a part-count tie-break | Historical optimizer score only |
| Final measured IoU | `TP / (source pixels + FP)` under frozen `silhouette-v1` | Reported final result |

`TP - FP` is not IoU. The retained M8D counterexample has sparse TP=20/FP=0 versus complete TP=30/FP=11 against 30 source pixels: sparse wins `TP-FP` (20 versus 19), complete wins IoU (20/30 versus 30/41). M8D also recorded Mansion raw-surrogate improvement of 92 with unchanged frozen IoU.

The M9A artifact calculates both fixed-frame scores and exact frozen completed-assembly TP/FP/FN/IoU, then repeats the M8D independent renderer-parity check. A global evaluation-aligned objective is not implemented: frozen bounds depend on selected geometry. Fixed-frame IoU is practical as a bounded surrogate calculation, but encoding its global ratio/union objective would be a new global optimization system outside M9A scope.

| Model | Frozen silhouette-v1 baseline | Frozen silhouette-v1 M9A | Change | Fixed-frame baseline | Fixed-frame M9A | Change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Duck | .591700 | .595249 | +.003549 | .578949 | .600334 | +.021385 |
| Mansion | .600598 | .600598 | .000000 | .596190 | .598930 | +.002740 |
| Realistic man | .421959 | .421959 | .000000 | .423489 | .423489 | .000000 |

For Duck, front and top frozen masks are unchanged. The side false-positive count falls from 4,091 to 3,904, raising side IoU from .609331 to .619978; averaging that one-view improvement across three views gives only .003549. Fixed-frame IoU instead uses one selection-independent source-plus-grid envelope, while frozen `silhouette-v1` derives padded bounds from each completed assembly. Therefore the fixed-frame gain of .021385 cannot be equated with the frozen-result gain.

All six completed arrangements have exact frozen-evaluator parity: front, side, and top source and LEGO masks, TP/FP/FN counts, and IoUs match the independent diagnostic renderer. That proves evaluator implementation parity, not optimizer-objective alignment.

## Focused validation

The synthetic M9A regression locks one verified 4286 slope and requires a witness supplied by its source profile. The historical rectangle-only selection is `INFEASIBLE`; the corrected selection is `FEASIBLE`; an unrelated witness remains `INFEASIBLE`. This proves the correction does not turn arbitrary source occupancy into coverage.

Completed-assembly evaluator parity remains tested for ordinary boxes and slope prisms. The baseline runner independently checks collision pairs, evaluated support, protected-space violations, connected components, and the 60-part cap.

| Model | Parts baseline -> M9A | Connected components baseline -> M9A | Collision pairs | Unsupported | Protected-space violations |
| --- | ---: | ---: | ---: | ---: | ---: |
| Duck | 29 -> 28 | 1 -> 1 | 0 | 0 | 0 |
| Mansion | 27 -> 21 | 6 -> 3 | 0 | 0 | 0 |
| Realistic man | 22 -> 17 | 2 -> 2 | 0 | 0 | 0 |

These are experimentally safe placements under the existing collision, evaluated direct-support, protected-space, cap, and component diagnostics. They are not fully connected LEGO builds: Mansion still has three components, and the diagnostics do not establish stability, clutch force, centre of mass, insertion accessibility, or official-build quality.

The M9A helper and runner are offline-only and are not imported by production conversion routing. Their private placement IDs remain only in ignored `artifacts/` output. The review found no new geometry family, unchanged production V4-V7 behavior, retained physical safeguards, and no private-artifact inclusion.

## Remaining limitations and next action

- M9A establishes feasibility, not global geometric optimality or meaningful production-fidelity improvement.
- The private corpus must remain available to reproduce the experiment; this document records hashes and non-sensitive aggregate results only.
- The M9A optimizer retains M8C's `TP - FP` objective. Fixed-frame IoU is measured, not globally optimized.
- Frozen dynamic bounds remain a final completed-arrangement evaluator, not a preselection candidate objective.
- Existing mechanics establish collision, direct-support, protected-space, cap, and connectivity conditions; they are not complete physical-build certification.

The recorded baseline gate is complete: all three fixed selections are feasible with `OPTIMAL` fixed-selection proofs, every recorded mechanical gate passes, and evaluator parity is exact. M9B remains an offline evaluation follow-up; it is not implemented by M9A.
