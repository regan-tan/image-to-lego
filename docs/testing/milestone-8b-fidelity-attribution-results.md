# Milestone 8B: Geometric Fidelity Bottleneck Attribution

## Decision

**C. Mixed or inconclusive.** The evidence rules out the narrow claim that an
unrestricted per-cell surface representation automatically provides a much
better three-view silhouette than V6. It does not prove the opposite: Stage B
is a bounded deterministic voxelisation surrogate, not a continuous-mesh or
catalogue optimiser. Existing M8A evidence also shows that a source-aware V6
tie-break changes geometry without improving the measured original-mesh
silhouettes. The dominant observed loss remains the coarse, axis-aligned
surface representation, but a defensible catalogue-constrained optimum has not
been computed.

## Method and controls

The offline-only runner is `backend/scripts/run_m8b_fidelity_attribution.py`.
It uses the M7B SHA-256-pinned private GLBs, and writes JSON plus overlays only
under ignored `artifacts/m8b-fidelity-attribution/`. It is not imported by
FastAPI, workers, the frontend, or `convert_glb()`.

All source geometry uses Y-up conversion, the fixed V6 source-aligned lattice,
the physical cell dimensions (8 mm x 8 mm x 3.2 mm), and frozen
`silhouette-v1` rasterization. V6 uses `targetParts=24`, `maxParts=60`, its
verified catalogue, deterministic solver settings, collision checks, and
buildability checks. Each case has a 180-second wall-clock recording budget;
all finished within it. Private bytes, paths, placements, and source meshes
are not output or committed.

Stage A is the original mesh reference, so by definition it scores 1.0 in each
view against itself. Stage B has one coherent 3D occupancy: V6-aligned source
surface voxelisation represented as independent 1x1x1 cells. It has no LEGO
part count and no claim of physical buildability or optimality. This is a
bounded surrogate, rather than a mathematical ceiling. A rectangular-cell
result also cannot bound slope-capable real LEGO geometry.

The projection-hull row renders the V6 mandatory witness volume as the same
independent cells. It is a controlled representation diagnostic—not an
optimisation—and isolates the visible effect of turning source cells into the
three-view hull. Stage C records the existing V6 catalogue feasible set:
catalogue and orientation eligibility, collision exclusion, reachability,
support repair, protected-empty handling, 60-part cap, and mandatory projection
coverage. It does **not** claim a new catalogue optimum, because this codebase
does not have a direct original-mesh silhouette objective over that exact
feasible set. Stage D is the actual V6 result.

## Results

All reconstructed sources were non-watertight. Thus, source surface cells are
not treated as reliable solid-volume ground truth, and three projections do not
establish depth or internal fidelity.

| Source (SHA-256 prefix) | Grid / envelope mm | A mean | B cells / mean | Hull cells / mean | D parts / mean | Runtime s |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Duck (`77093bb…f11379e`) | 5x7x12 / 40x56x38.4 | 1.000000 | 165 / .578348 | 188 / .569358 | 29 / .591700 | 17.288 |
| Mansion (`d1a961…919510`) | 7x4x12 / 56x32x38.4 | 1.000000 | 269 / .599402 | 271 / .599657 | 27 / .600598 | 28.547 |
| Realistic man (`0891024…6088bce`) | 3x5x18 / 24x40x57.6 | 1.000000 | 137 / .421959 | 156 / .421959 | 22 / .421959 | 15.536 |

| Source | Stage | Front / side / top IoU | Original-mesh FP (front/side/top) | Original-mesh FN (front/side/top) |
| --- | --- | --- | --- | --- |
| Duck | B cells | .610069 / .597794 / .527180 | 4713 / 4353 / 6213 | 89 / 132 / 32 |
| Duck | Hull cells | .610069 / .570825 / .527180 | 4713 / 4328 / 6213 | 89 / 447 / 32 |
| Duck | D V6 | .638589 / .609331 / .527180 | 4163 / 4091 / 6213 | 89 / 163 / 32 |
| Mansion | B cells | .718515 / .557519 / .522172 | 3778 / 6435 / 7586 | 73 / 0 / 0 |
| Mansion | Hull cells | .718515 / .558283 / .522172 | 3778 / 6030 / 7586 | 73 / 215 / 0 |
| Mansion | D V6 | .718515 / .561107 / .522172 | 3778 / 6203 / 7586 | 73 / 78 / 0 |
| Realistic man | B cells | .426276 / .445331 / .394271 | 8093 / 5972 / 7713 | 121 / 354 / 27 |
| Realistic man | Hull cells | .426276 / .445331 / .394271 | 8093 / 5972 / 7713 | 121 / 354 / 27 |
| Realistic man | D V6 | .426276 / .445331 / .394271 | 8093 / 5972 / 7713 | 121 / 354 / 27 |

The Stage C/D candidate counts were Duck 1733/1527/1449,
Mansion 3246/3174/3166, and Realistic man 1063/1063/1043
(before protection / after protection / after reachability). Each stage-one
solver status was `OPTIMAL`; each stage-two status was `FEASIBLE`. V6 exposes
no safe, comparable stage-two objective bound, so stage-two results are
bounded incumbents, never catalogue optimality proofs. All actual V6 outputs
had zero collision pairs and zero unsupported evaluated placements. Connected
components were 1, 6, and 2 respectively.

## Attribution and limits

1. **Source-to-lattice representation:** Stage B still has large persistent
   false-positive regions, especially in the top views. This shows substantial
   loss before part assembly. It is evidence about this surface-voxel surrogate,
   not an upper bound for all fixed-lattice representations.
2. **Mandatory projection hull:** Duck loses .008990 mean IoU between B and
   hull; Mansion gains .000255; Realistic man is unchanged. This controlled
   render isolates only the hull-cell representation, not its causal effect on
   a constrained catalogue optimisation.
3. **Catalogue geometry, cap, and mechanics:** Existing V6 is valid under
   these restrictions, but no direct source-mesh objective was solved over an
   ablated shared feasible set. Differences cannot be assigned causally.
4. **Remaining V6 optimisation gap:** Not measured. M8A demonstrates that
   source-aware lexicographic packing can change selected placements while
   retaining identical Mansion and Realistic-man silhouette masks, but it does
   not demonstrate a better feasible catalogue solution.

Unsuccessful/withheld experiment: a direct CP-SAT objective based on the
128x128 continuous raster masks would need to model unions of projected,
non-rectangular part geometry while preserving the current physical checks.
That is not present in V6 and was not introduced solely for this diagnostic;
substituting unrelated grid-projection coverage would not answer the research
question. No claim of a catalogue upper bound is made.

## Ranked next work

1. Add a bounded, offline-only **catalogue candidate silhouette objective** at
   fixed lattice/envelope, reporting incumbent, best bound, and every retained
   safeguard. This directly resolves the remaining optimisation-vs-representation
   question.
2. Evaluate a limited slope/curved-part candidate vocabulary in that same
   objective; rectangular cells cannot upper-bound these shapes.
3. Only after those controls, test a modest grid-resolution increase with
   fixed physical envelope and explicit candidate/memory budgets.
4. Do not promote M8A's source-aware packing term: it had no decision-relevant
   three-model improvement.

## Recommended production change

**Do not change production V6 yet.** First implement the offline catalogue
silhouette experiment above. Promotion requires, on all three pinned sources,
that the candidate solution passes the current collision/support gates and
finds a solution at least .01 higher mean `silhouette-v1` IoU than V6 on at
least two sources, while reporting a solver bound or clearly labelled bounded
feasible status. Without that evidence, the current data does not justify
weakening mechanical correctness or adding a new production optimiser.
