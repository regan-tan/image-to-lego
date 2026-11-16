# Milestone 8A: Source-Aware Geometric Fitting Prototype

## Decision: **NO-GO**

The bounded source-aware prototype does not meet the promotion rule. It improved
mean silhouette IoU by at least .01 on zero of the three SHA-256-verified
private sources; Duck lost .001892 and Mansion and Realistic man were unchanged.
All safety gates remained clean, but the extra optimisation work increased
runtime. This scoring term should not be added to the production converter.

## Scope and controls

This work is an offline diagnostic only. The new `source_aware` option exists
only on `fixed_grid_experiment.convert_fixed_grid`; FastAPI, workers, and
`convert_glb()` neither import it nor route to it. Inputs were verified against
the existing M7B manifest before loading. Private bytes, paths, and placements
were not committed. Measurement JSON and overlays are ignored under
`artifacts/m8a-source-aware-fitting/`.

Every paired run held constant the source/up axis, 1x source evidence, explicit
lattice and nominal physical envelope, target 24, hard cap 60, catalogue,
mechanical eligibility, protected-space path, support repair, collision checks,
and existing deterministic solver limits. The frozen `silhouette-v1` and
`placement-surface-proxy-v2-chunked` metrics were reused unchanged.

| Source | SHA-256 prefix | Lattice (studs x studs x plates) | Envelope mm |
| --- | --- | --- | --- |
| Duck | `77093bb…f11379e` | 5 x 7 x 12 | 40 x 56 x 38.4 |
| Mansion | `d1a961…919510` | 7 x 4 x 12 | 56 x 32 x 38.4 |
| Realistic man | `0891024…6088bce` | 3 x 5 x 18 | 24 x 40 x 57.6 |

## Root-cause audit

V5/V6 builds a projection-hull candidate volume `A`: every cell whose front,
side, and top pixels occur in source evidence. CP-SAT first maximizes required
three-view projection coverage, then minimizes selected parts. It requires no
specific selected source cell once the required projection pixels are covered.
Rectangular candidates may therefore occupy hull-only cells, provided they fit
in `A`, are non-overlapping, support-reachable, under the cap, and pass repair
and physical checks. Locked slopes remain fixed.

This is real optimisation freedom, rather than a hypothetical term: paired
prototype geometry hashes differ for every source, and source-cell retention
increased by 21 (Duck), 32 (Mansion), and 2 (Realistic man). Projection coverage
was fully retained for every baseline and prototype view. Yet the original-mesh
silhouette score did not improve. Therefore the audit rejects the claim that
the part-packing tie-break alone is the dominant source of blockiness. At these
coarse fixed lattices, quantisation and the restricted rectangular/slope
vocabulary are the observed limiting stages; the three-view hull is also depth
ambiguous. M7B's 2x evidence result remains relevant: more voxel evidence did
not resolve that limitation.

## Prototype objective

The prototype preserves stage one's attained required projection coverage. In
stage two it uses a deterministic lexicographic objective over the existing
eligible candidates:

1. minimize selected part count;
2. minimize occupied candidate cells outside the 1x source surface evidence;
3. maximize occupied candidate cells in that evidence.

It encodes the ordering with weights calculated from the bounded candidate set,
not a new magic penalty: `sourceWeight = totalPossibleSourceCells + 1` and
`partWeight = totalPossibleExcessCells * sourceWeight + totalPossibleSourceCells + 1`.
The minimized expression is `partWeight * parts + sourceWeight * excess - source`.
No part is resized; the lattice, envelope, catalogue, cap, projection
requirements, protected-space logic, support requirement, and collision gate
are unchanged.

## Paired results

`Excess` and `retained` are final source-grid occupancy counts; they are useful
stage attribution, not a substitute for continuous mesh fidelity. `—` means the
frozen v2 observer reached its configured timeout, not a zero.

| Source | Variant | Parts | Front / side / top / mean IoU | Retained / excess | Components / isolated | v2 symmetric mm | Runtime s |
| --- | --- | ---: | --- | --- | --- | ---: | ---: |
| Duck | V6 baseline | 29 | .638589 / .609331 / .527180 / .591700 | 107 / 17 | 1 / 0 | 2.794217 | 24.661 |
| Duck | prototype | 26 | .638589 / .603655 / .527180 / .589808 | 128 / 15 | 1 / 0 | 2.764475 | 57.558 |
| Mansion | V6 baseline | 27 | .718515 / .561107 / .522172 / .600598 | 129 / 1 | 6 / 4 | — | 64.038 |
| Mansion | prototype | 27 | .718515 / .561107 / .522172 / .600598 | 161 / 1 | 5 / 3 | — | 91.965 |
| Realistic man | V6 baseline | 22 | .426276 / .445331 / .394271 / .421959 | 109 / 11 | 2 / 0 | — | 46.796 |
| Realistic man | prototype | 22 | .426276 / .445331 / .394271 / .421959 | 111 / 3 | 2 / 0 | — | 66.244 |

The frozen v2 observer was available only for Duck. Its symmetric mean improved
from 2.794217 to 2.764475 mm, but that isolated proxy observation cannot
override the required original-mesh silhouette result. Mansion and Realistic
man timed out under their configured observation budgets in both paired runs.

All six runs report zero physical collisions, zero unsupported placements, and
zero protected-space violations. The three sources are non-watertight, so the
existing conservative classifier correctly reported zero proven protected-empty
cells; it was not disabled. All runs retained the 60-part hard cap. Candidate
counts and main solver statuses were unchanged within each pair: Duck
1,449 (`OPTIMAL` / `FEASIBLE`), Mansion 3,166 (`OPTIMAL` / `FEASIBLE`), and
Realistic man 1,043 (`OPTIMAL` / `FEASIBLE`). Source projected coverage remained
complete with zero projected excess and zero projected omissions in front, side,
and top for every run.

## Final failure-mechanism review

The source-grid projection checks and the frozen original-mesh metric answer
different questions. At grid level, every run has complete required source
coverage and no excess projected pixels. Those constraints fix the three view
rays that must be hit, but not the depth cell used on a ray, the cells occupied
around that witness by a rectangular part, or the continuous outline drawn by
the part geometry.

The actual selected assemblies changed materially: each pair has a different
placement-geometry SHA-256, and the prototype changed part count from `29` to
`26` for Duck, `27` to `19` for Mansion, and `22` to `17` for Realistic man in
the final regenerated records. The objective therefore can affect visible
geometry; it is not only changing an internal arrangement. The durable records
retain hashes rather than raw private placement coordinates, so they establish
different selected assemblies without publishing a per-placement diff.

The frozen overlays show the more direct bottleneck. Each entry is
`overlap / false-positive / false-negative` pixels against the original GLB,
in front, side, top order:

| Source | Baseline | Prototype | Mask result |
| --- | --- | --- | --- |
| Duck | `7513/4163/89`, `6635/4091/163`, `6963/6213/32` | `7513/4163/89`, `6639/4200/159`, `6963/6213/32` | Front and top are equal; side gains 4 overlap pixels but adds 109 false positives. |
| Mansion | `9830/3778/73`, `8030/6203/78`, `8290/7586/0` | identical in all three views | All frozen silhouette masks are equal. |
| Realistic man | `6103/8093/121`, `5079/5972/354`, `5038/7713/27` | identical in all three views | All frozen silhouette masks are equal. |

The large persistent false-positive regions explain why better source-cell
occupancy does not imply better original-mesh silhouette. The confirmed
mechanism is a mismatch between coarse grid/projection evidence and continuous
brick geometry: source-aware selection can alter cells, parts, and occasionally
a mask, but it cannot remove the dominant quantisation/vocabulary outline
error under the current candidate space. This makes silhouette improvement
**difficult, not impossible**. Duck proves that packing freedom can change a
mask; the current evidence does not prove that a richer legal part family or a
matched finer lattice could not improve it.

## Minimal M8B recommendation

Run one offline fixed-envelope four-stage attribution experiment on the same
three SHA-pinned sources with frozen `silhouette-v1`: source surface voxels;
projection-hull voxels; the hull constrained to the current legal part
catalogue before packing; and the current physically validated packed model.
Hold the lattice, physical envelope, source evidence, up axis, target, cap, and
renderer bounds constant. The first three are diagnostic geometry only and must
be labelled non-buildable; only the packed stage may make safety claims.

Report front/side/top/mean IoU and adjacent-stage deltas. M8B is informative
only if at least one adjacent transition accounts for `.01` mean IoU loss on at
least two sources, while the packed stage still has zero collisions and zero
unsupported placements. Otherwise retain this NO-GO without another production
fitting change.

## Acceptance audit and limitations

The IoU deltas (prototype minus baseline) are Duck `-.001892`, Mansion `.000000`,
and Realistic man `.000000`. Thus the prototype fails criterion 1 (two gains of
at least .01), while satisfying the no-large-loss, collision, support, cap,
protected-space, and connectivity non-regression criteria. Runtime was bounded
by the existing solver budgets but increased by 42–133%, so it supplies no
practical compensating benefit.

The experiment is intentionally small (three private sources), source evidence
is a coarse surface voxel mask rather than an exact signed-distance field, and
v2 was unavailable for two large meshes. The result does not prove source-aware
fitting can never help at a different lattice or with a genuinely richer part
family. It does show this minimal scoring change is insufficient and should not
be promoted as the explanation or cure for observed blockiness.

## Verification

From `backend/`, the paired experiment was run with
`uv run python scripts/run_m8a_source_aware_fitting.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m8a-source-aware-fitting`.
Focused tests, Ruff, mypy, and `git diff --check` were also run locally; no cloud
or paid provider was contacted.
