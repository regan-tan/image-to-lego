# Milestone 7B: Controlled Fidelity Experiment Results

## Outcome

The complete offline 2x2 fixed-lattice matrix completed for Duck, Mansion, and
Realistic man (12 primary runs). Raising source evidence from 1x to 2x did not
improve silhouette fidelity in any of the six paired comparisons. Raising the
hard cap from 30 to 60 also produced no silhouette gain of 0.01 or more. No
run had a physical collision or unsupported evaluated placement.

This is evidence against adopting 2x evidence sampling as a production
improvement at these lattices. It is not evidence that source sampling can
never help: the corpus is only three private examples, and the current metric
remains unavailable for seven large-mesh observations within its 30-second
observation budget.

## Controls and execution

The runner is deliberately offline-only:
`backend/scripts/run_m7b_controlled_fidelity_experiment.py` calls the
fixed-grid diagnostic seam, not `convert_glb()`, FastAPI, a worker, or a
frontend path. Its output schema is `m7b-controlled-fidelity-experiment-v1`.
All records, overlays, and per-point JSON are ignored under
`artifacts/m7b-controlled-fidelity-experiment/`; neither private source bytes
nor their paths are tracked.

| Source | SHA-256 | Fixed lattice / nominal envelope | Up axis |
| --- | --- | --- | --- |
| Duck | `77093bb…f11379e` | 5x7x12 / 40x56x38.4 mm | y |
| Mansion | `d1a96186…919510` | 7x4x12 / 56x32x38.4 mm | y |
| Realistic man | `0891024e…6088bce` | 3x5x18 / 24x40x57.6 mm | y |

Every point used V6 fixed-lattice diagnostic packing, `targetParts=24`, the
same catalogue, colour policy, seed/solver limits, reachability pruning,
locked-slope handling, support repair, protected-empty logic, buildability
gate, and physical collision gate. The factors were source evidence (`1x` or
`2x`, version `source-evidence-voxel-v1`) and the hard cap (`30` or `60`).
At 2x, subcells are voxelized then reduced by fixed-cell membership; no LEGO
lattice dimension or physical envelope changes.

The synthetic V6 smoke, deterministic 1x/2x factor tests, cap/safeguard tests,
invalid-setting tests, v2 deterministic test, timeout test, and a synthetic
v1/v2 rank-agreement test are included in `tests/test_fixed_grid_experiment.py`.
The measured primary work total was about 9.3 minutes excluding shell setup,
inside the 18-minute batch budget.

## Complete matrix

`Cells` records source evidence / projection-hull additions / final occupancy.
`v2` is symmetric mean surface distance in mm; lower is better. `—` is an
explicit unavailable metric, never a zero or a numeric comparison.

| Source | Evidence | Cap | Parts | Cells | Front / side / top / mean silhouette IoU | v2 | Runtime s | Components |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: |
| Duck | 1x | 30 | 26 | 165 / 45 / 149 | .638589 / .609331 / .527180 / .591700 | 2.770776 | 37.353 | 1 |
| Duck | 1x | 60 | 29 | 165 / 45 / 124 | .638589 / .609331 / .527180 / .591700 | 2.794217 | 26.570 | 1 |
| Duck | 2x | 30 | 22 | 183 / 43 / 135 | .601273 / .624814 / .527180 / .584422 | 3.200004 | 38.415 | 2 |
| Duck | 2x | 60 | 23 | 183 / 43 / 132 | .601273 / .618524 / .527180 / .582326 | 2.964855 | 32.423 | 3 |
| Mansion | 1x | 30 | 23 | 269 / 9 / 133 | .718515 / .561107 / .522172 / .600598 | — | 55.713 | 6 |
| Mansion | 1x | 60 | 27 | 269 / 9 / 130 | .718515 / .561107 / .522172 / .600598 | — | 62.445 | 6 |
| Mansion | 2x | 30 | 20 | 276 / 16 / 149 | .676466 / .569662 / .541193 / .595774 | — | 76.741 | 2 |
| Mansion | 2x | 60 | 32 | 276 / 16 / 164 | .689432 / .557519 / .522172 / .589708 | — | 59.662 | 3 |
| Realistic man | 1x | 30 | 17 | 137 / 19 / 117 | .426276 / .445331 / .394271 / .421959 | — | 52.131 | 2 |
| Realistic man | 1x | 60 | 22 | 137 / 19 / 120 | .426276 / .445331 / .394271 / .421959 | — | 48.146 | 2 |
| Realistic man | 2x | 30 | 20 | 148 / 28 / 131 | .414585 / .437615 / .364333 / .405511 | — | 53.911 | 2 |
| Realistic man | 2x | 60 | 19 | 148 / 28 / 119 | .414585 / .437615 / .364333 / .405511 | 3.299546 | 45.896 | 3 |

All twelve records report zero collisions and zero unsupported evaluated
placements. The three sources are non-watertight, therefore protected-empty
count is correctly zero for every point. All stage-one statuses were `OPTIMAL`
and stage-two statuses `FEASIBLE`; V6 reported no accepted shape refinement.

`placement-surface-proxy-v2-chunked` is separately versioned and does not
overwrite v1. It uses 2,048 deterministic area-weighted samples per direction,
128-point by 2,048-triangle chunks, 50,000 source-triangle and 10,000
placement-triangle bounds, and a 30-second observation budget. It was available
for Duck and the Realistic-man 2x/cap-60 point. Mansion and the other three
Realistic-man points explicitly timed out at that budget. The recovered
Realistic-man observation has symmetric mean 3.299546 mm, normalized symmetric
mean .050676, and P95 nearest-surface distance 11.623326 mm. It has no paired
available Realistic-man control, so it is retained as an observation but is
excluded from v2 factor-effect comparisons. This remains a measurement
limitation, not a converter fallback or a changed solver budget.

## Paired interpretation

Sampling effect (2x minus 1x mean IoU): Duck -0.007278 at cap 30 and -0.009374
at cap 60; Mansion -0.004824 and -0.010890; Realistic man -0.016448 and
-0.016448. Duck's available v2 distances also increased by +0.429228 mm and
+0.170638 mm. Thus, 2x evidence correlated with worse, not better, measured
fidelity in this matrix. The side-view Mansion 30-cap increase (+.008555) is a
contrary per-view result; it is smaller than the accompanying front-view loss
(-.042049), so it must not be hidden by the mean.

Cap effect (60 minus 30 mean IoU): Duck 1x +0.000000 and 2x -0.002096;
Mansion 1x +0.000000 and 2x -0.006066; Realistic man +0.000000 at both
evidence levels. Duck's v2 changed +0.023441 mm at 1x and -0.235149 mm at 2x.
These small and opposing changes do not establish a cap benefit. They are
consistent with different feasible CP-SAT solutions, not proof of a particular
packing mechanism. Realistic man's 2x/cap-60 v2 observation is now available,
but its 2x/cap-30 counterpart remains unavailable, so it does not establish a
cap effect.

The evidence-by-cap interaction (difference of the two cap effects) is
-0.002096 for Duck, -0.006066 for Mansion, and 0 for Realistic man. None meets
the design's 0.01 silhouette threshold. The full stage chain shows why the
claim remains limited: 2x changes retained source cells (Duck 165→183,
Mansion 269→276, Realistic man 137→148), but it also changes hull additions and
the feasible packing output. It cannot by itself identify whether sampling,
three-view hull ambiguity, or solver tie-breaking caused a particular final
placement difference.

No factor is decision-relevant under the predeclared rule: no effect has both a
consistent direction in at least two sources, a mean-IoU change of at least
0.01, and a comparable available v2 change of at least 5%, while retaining all
mechanical safeguards. These are correlations across three deterministic cases,
not statistical significance claims.

## Acceptance audit

The two evidence configurations are materially different for every source; the
unchanged IoU rows do **not** mean an equivalent intermediate representation.
For Duck, 1x/2x respectively retained 165/183 source cells, produced 188/220
hull targets, and produced 1,449/1,947 post-reachability candidates. Mansion
was 269/276, 271/292, and 3,166/3,556; Realistic man was 137/148, 156/176,
and 1,043/1,276. The 2x subcell counts were 731, 1,444, and 622, compared
with 1x counts of 165, 269, and 137. Placement geometry hashes differ for all
1x-versus-2x pairs. Where Realistic-man IoU stays at .421959 (1x caps) or
.405511 (2x caps), different capped placements have converged to the same
three-view raster score; the score is not proof of equivalent geometry.

For each source, all four records have exactly one source hash, up axis, fixed
lattice and nominal mm envelope, solver target 24, source characteristics, and
catalogue/solver path. Every actual part count is at or below its cap. Every
record has zero collision pairs and zero unsupported evaluated placements; all
use the same conservative non-watertight protected-empty outcome (zero), rather
than disabling that safeguard. Placement identities can still differ at a fixed
evidence level when only the cap changes; this is consistent with a different
feasible stage-two solution, not a factor-independence failure.

### Realistic-man v2 observation

The directional nearest-triangle pass from 2,048 final placement samples to the
38,950-source-triangle mesh is the bottleneck. With 128-point and
2,048-triangle chunks, it needs 16 point chunks times 20 triangle chunks (320
bounded point-to-triangle blocks), each evaluating exact point-to-triangle
distances. The recovered 2x/cap-60 observation completed within the unchanged
30-second wall-clock guard; it did not loosen triangle, sample, or memory
bounds. Its record reports 19 parts, three connected components, zero
collisions, and zero unsupported evaluated placements.

To rerun only that matrix point and its missing v2 observation locally on
Windows CMD, with the design's bounded 30-second metric timeout, run:

```cmd
cd /d C:\Users\Regan\Desktop\image-to-lego-reliability\backend
.venv\Scripts\python.exe scripts\run_m7b_controlled_fidelity_experiment.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m7b-controlled-fidelity-experiment --case realistic-man --source-evidence-resolution 2 --max-parts 60 --metric-timeout-seconds 30
```

The runner recomputes the deterministic placement because private placements
are intentionally not persisted, then observes only this selected point. A
selected rerun updates its per-point JSON without replacing a complete
`summary.json`; run the same command with `--summarize-existing` after all
durable records have been deliberately reviewed. If it again times out, retain
`unavailable` and exclude it from numeric v2 analysis.

## Limitations

- Three private, non-watertight reconstructions cannot establish statistical
  significance or volumetric fidelity.
- Silhouette-v1 has only three 128-pixel orthographic views; it does not assess
  hidden surfaces, texture, depth, stability, clutch force, or insertion.
- The hull additions are ambiguity introduced before packing, not proven false
  volume. Protected-empty zero means uncertainty was not overconstrained.
- Independent-axis normalization remains held constant but does not preserve
  original-world aspect/physical scale.
- Runtime is environment-dependent. Stage two is feasible, not an optimality
  proof, so placement hashes changing at fixed IoU are expected.
- v2 is unavailable for seven large-source observations; the one recovered
  Realistic-man measurement has no available paired control, so no v2
  cross-source conclusion is made.

## Recommendation

The smallest viable next production change is to make V6's default hard cap
**30 rather than 60**, while retaining 1x evidence sampling and every current
safeguard. This follows the observed absence of a 60-cap silhouette gain and
the lower part counts in every 30-cap row; it does not claim a fidelity
improvement. Acceptance criteria: on this SHA-pinned corpus at fixed grids,
30 must produce no collision or unsupported placement, stay within the cap,
and have mean silhouette IoU no more than 0.01 below its 60-cap control for
each source. Regression risks are a different feasible packing, fragmentation
(components changed in several rows), and a decline on sources unlike this
small corpus; retain the 60-cap explicit opt-in and re-run the matrix before
making it the API default.
