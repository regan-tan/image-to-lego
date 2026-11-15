# Milestone 7B: Scale-Controlled Fidelity Experiment Design

## Decision

Do **not** run or describe a LEGO-lattice resolution sweep as matched physical
scale.  With standard LEGO geometry, that comparison is infeasible: one lattice
cell is one 8 mm by 8 mm stud footprint and one 3.2 mm plate height.  Changing
an integer `GridSize(widthStuds, depthStuds, heightPlates)` normally changes the
physical envelope to `8w x 8d x 3.2h` mm.  Resizing a completed model would
alter real part geometry and is not a physical LEGO comparison.

The smallest defensible next experiment is an offline-only **fixed-lattice,
source-evidence-resolution by hard-cap factorial**.  It holds the lattice and
therefore its nominal physical envelope fixed for each source, while separately
varying (a) source evidence sampling before it is reduced to that lattice and
(b) the CP-SAT hard part cap.  It uses the existing V6 safety gates unchanged.
This isolates two likely causes of loss without pretending that a different
number of LEGO cells has the same physical size.

This document is a design only.  It does not change conversion behavior, API
settings, workers, or mechanical safeguards.

## Audit of the existing evidence

The prior investigation is [Milestone 7B geometric fidelity
investigation](milestone-7b-geometric-fidelity-investigation.md).  Its V6/V7
settings (`targetParts=24`, `maxParts=60`) derive an effective grid target of
`min(24, 60 // 4) = 15`.  That selection occurs before V3 chooses the grid.
Consequently, part cap, lattice dimensions, physical envelope, voxelization,
candidate count, and solver difficulty all change together.

The recorded envelopes make the confound concrete:

| Source | V4 lattice / envelope | V6/V7 lattice / envelope |
| --- | --- | --- |
| Duck | 5x8x12 / 40x64x38.4 mm | 5x7x12 / 40x56x38.4 mm |
| Mansion | 8x5x15 / 64x40x48.0 mm | 7x4x12 / 56x32x38.4 mm |
| Realistic man | 4x6x24 / 32x48x76.8 mm | 3x5x18 / 24x40x57.6 mm |

Thus, the observation that V4 has higher raster silhouette IoU cannot establish
that its packing algorithm or part count is better.  The only genuine
matched-lattice comparison already present is V6 versus V7, which returned the
same geometry for all three models.

The source-alignment path is coherent for one completed conversion, but it does
not remove this between-run confound.  It maps the declared up axis, translates
each source minimum to zero, then independently scales each source axis to
`gridDimension - 1`.  The benchmark repeats this same mapping before rendering
silhouettes and converting grid coordinates to mm.  It therefore measures a
source fitted to the selected LEGO lattice, not a source held at one absolute
world scale across lattices.  Independent axis scaling also means this is a
shape-normalized comparison, not an aspect-preserving physical reconstruction.

The processing stages are distinct:

1. **Source sampling / voxelization:** triangles are transformed into source
   surface cells after normalization and scaling to the selected grid.
2. **LEGO lattice and scale:** grid coordinates map to fixed real dimensions:
   8 mm in X/Y and 3.2 mm in Z.  The chosen integer dimensions define the
   nominal envelope.
3. **Packing and cap:** the projection hull creates a candidate witness volume;
   CP-SAT maximizes three orthographic projected pixels, then minimizes parts,
   subject to the cap and safety constraints.
4. **Candidate geometry:** hull-only cells and enumerated placements are not
   source truth and are not final geometry.
5. **Source-to-LEGO fidelity:** continuous source triangles must be compared
   with final part geometry, separately from grid-cell coverage.

The prior stage diagnostic is useful attribution evidence, not an end-to-end
fidelity score.  For example, its zero grid-projection false positives/negatives
shows CP-SAT preserved the *voxel representation* in those three views.  It
does not show that the voxel representation matches the original triangles,
that the projection hull preserves concavity, or that real silhouettes match.

## Feasibility assessment

### Genuine matched-envelope LEGO-lattice resolution sweep: infeasible

A lattice-resolution sweep means changing at least one of `w`, `d`, or `h`.
For an exact envelope `(W, D, H)`, physically valid values must satisfy
`W = 8w`, `D = 8d`, and `H = 3.2h` for integers `w`, `d`, and `h`.  The equations
have at most one integer solution per axis.  A second integer lattice with a
different resolution necessarily has a different envelope unless a part is
rescaled, non-standard sub-stud/sub-plate geometry is introduced, or the
comparison excludes some lattice space.  None is a controlled comparison of
standard LEGO models.

Padding a coarser grid, cropping a finer grid, or resizing output meshes does
not solve this.  Padding/cropping changes the usable candidate domain and
boundary conditions; mesh resizing changes brick dimensions.  Comparing final
occupied bounding boxes is also insufficient because source coverage and solver
decisions may leave lattice boundary cells unoccupied.

### Physically valid alternative: fixed lattice, varied evidence resolution

For each source, set one explicit source-aligned `GridSize` and use it for all
points.  The fixed nominal envelopes are the current capped V6 grids:

| Source | Fixed lattice | Nominal envelope |
| --- | ---: | ---: |
| Duck | 5x7x12 | 40x56x38.4 mm |
| Mansion | 7x4x12 | 56x32x38.4 mm |
| Realistic man | 3x5x18 | 24x40x57.6 mm |

These are separate per-source experiments, not a claim that the three sources
share a scale.  Within a source, every point has the same cell dimensions, part
catalogue, up axis, colour policy, slope locking, reachability pruning,
support repair, collision gate, and final physical units.

Define `sourceEvidenceResolution` as a diagnostic-only pre-packing sampling
factor, not a LEGO dimension.  `1` is the present one-cell-pitch surface
voxelization.  `2` samples the normalized mesh at half-cell pitch in every
axis, then deterministically reduces samples to the *same* fixed LEGO cells by
cell membership (a LEGO cell is occupied when any of its eight subcells is
surface-occupied).  Locked slopes, protected-empty logic, hull construction,
packing, and all final placements still operate in the fixed LEGO lattice.
The factor may change the evidence presented to fitting; it cannot claim a
finer physical LEGO model.

The reduction rule, boundary convention, and source-to-subcell transform must
be recorded as a new version (for example
`source-evidence-voxel-v1`).  It must use the same source normalization and
fixed lattice at every point.  No API/client setting may expose it.

## Fidelity attribution and measurements

Each record must retain the following levels.  Do not substitute one for
another.

| Level | Measure | Answers | Does not answer |
| --- | --- | --- | --- |
| Source evidence | source surface cells, subcell count, reduction-added cells | What evidence survived sampling? | Continuous mesh accuracy |
| Projection hull | hull-only cells and hull/source-cell ratio | How much candidate space was added by three-view ambiguity? | Which cells the solver selected or whether additions are erroneous volume |
| Packing | candidate count before/after protection and reachability, solver statuses/objectives, required/achieved grid pixels, final/source grid FP/FN | Did cap/solver preserve the selected grid evidence? | Triangle-level silhouette or depth fidelity |
| Final LEGO | part count, part families, dimensions, collision pairs, buildability outcome | Is the output bounded and mechanically screened? | Stability, insertion feasibility, or source similarity |
| Continuous fidelity | frozen silhouette-v1, overlays, surface-proxy metric | How final part geometry compares with source triangles | Volumetric truth, perceptual quality, mould-exact geometry |

For the grid-level comparison, calculate the final placement source-cell proxy
with the same fixed lattice and compare it both to the reduced source evidence
and to the projection hull.  Report front/side/top TP, FP, FN, and IoU in both
comparisons, clearly named `againstReducedSourceEvidence` and
`againstProjectionHull`.  The second reports packing retention; the first
reports grid evidence loss.  Neither is the original-mesh metric.

For original-mesh silhouette accuracy, preserve `silhouette-v1`: rasterize the
continuous aligned triangles and final LEGO primitive geometry with identical
per-view bounds at 128 pixels; record all three IoUs, mean IoU, and the masks/
overlays.  It must be evaluated after final packing, never inferred from source
cells.  At a fixed lattice, source and LEGO coordinates are already comparable
in fixed mm, so no post-hoc rescaling is permitted.

## Large-source continuous surface metric

`placement-surface-proxy-v1` is appropriately unavailable for mansion
(39,996 source faces) and realistic man (38,950): it refuses either surface
over 20,000 triangles before nearest-distance work.  Raising that limit would
change the safety contract and historic metric meaning.

Propose a separate, offline metric named
`placement-surface-proxy-v2-chunked`.  It is not comparable with v1 and must
appear beside, never replace, v1.

- Build source triangles and the existing final-placement primitive triangles;
  do not claim their union is a boolean-exact exterior.
- Take 2,048 deterministic, area-weighted low-discrepancy samples from each
  surface.  Area weighting reduces triangle tessellation bias; fixed sequences
  make repeat runs reproducible.
- Find point-to-triangle distances in chunks of at most 2,048 triangles and
  128 sample points.  Keep only each point's running nearest distance, so no
  all-pairs distance matrix is retained.
- Enforce explicit input bounds: at most 50,000 non-degenerate source
  triangles, 10,000 generated placement triangles, 2,048 samples per direction,
  and 128x2,048 work chunks.  Return `unavailable` with a specific reason for
  any bound, non-finite geometry, or calculation failure.  Do not retry or
  silently downsample.
- Report directional means, symmetric mean, P95 over both directions, source
  bounding-box diagonal in mm, and normalized symmetric mean.  Keep
  volumetric IoU `not_computed` for non-watertight/reconstruction sources.

Before it informs a decision, validate v2 determinism byte-for-byte on a small
fixture and show directional and symmetric agreement trends with v1 on the
under-20,000-triangle synthetic suite.  Exact equality is not expected because
the sampling/work implementation changes; unexplained rank reversal is a
blocker.  Metric evaluation gets a 30-second wall-clock observation budget per
completed conversion; a timeout is an unavailable result, not a zero score.

## Minimal experiment matrix

Use the SHA-pinned private duck, mansion, and realistic-man sources already
used by M7B.  Run V6 only: V7's connectivity search is a separate hypothesis,
and V4 cannot accept the same hard cap.  Each source has a fixed grid from the
table above, a fixed `targetParts=24`, `upAxis` from its manifest, the current
catalogue and solver seed, and no V6 shape-refinement change.

| Factor | Low | High | Purpose |
| --- | --- | --- | --- |
| Source evidence resolution | 1x (current cell-pitch evidence) | 2x subcell evidence reduced to fixed lattice | Is sampling loss material before packing? |
| Hard cap | 30 | 60 | Does the cap materially restrict a fixed-lattice packing? |

This is a 2x2 factorial: 4 runs/source, 12 conversions total.  It is the
smallest matrix that estimates both main effects and detects a cap/evidence
interaction.  Run each point once; the deterministic solver seed and one
worker make duplicate runs verification only, not independent samples.  The
existing 60-cap/1x point is a reproduction control.  A 30-cap point that
honestly fails an existing safety/solver condition remains a result; it is not
re-run with relaxed bounds or replaced with a nearby cap.

Budget the batch at 60 seconds observed conversion time plus 30 seconds metric
time per point, 18 minutes serial wall-clock including artifact writes.  Stop
the batch at that budget and record uncompleted points as `not_run_budget`;
do not increase solver work limits.  Expected baseline runtimes (about 17--29
seconds per V6 case) make this conservative.  Store output only under ignored
`artifacts/m7b-scale-controlled/`, with hashes/settings/counts and diagnostic
images; do not write private mesh bytes or paths to tracked files.

### Per-point acceptance criteria

A completed point is valid only when all of the following are recorded:

1. Input SHA, source characteristics, code revision, manifest up axis,
   explicit lattice and nominal mm envelope match the other three points for
   that source exactly.
2. Existing input/grid limits, protected-empty behavior, locked-slope body
   exclusion, reachability pruning, hard cap, support repair, buildability
   gate, and collision gate all pass unchanged.
3. `actualParts <= maxParts`; grid/evidence, hull, candidate, solver-stage,
   final-grid, silhouette-v1, and v2 status values are present.  An unavailable
   v2 value is explicit and excluded from numeric comparisons.
4. Source evidence and final-output dimensions are reported separately.  A
   final occupied bounding box may vary and is diagnostic only; it must not be
   reinterpreted as a changed lattice envelope.
5. The 60-cap/1x reproduction agrees with the existing stage diagnostic and
   V6 result in grid, parts, placements/final geometry hash, and
   silhouette-v1.  A disagreement blocks interpretation until explained.

Interpret a factor as decision-relevant only if it produces a consistent
direction in at least two of three sources, changes mean silhouette IoU by at
least 0.01 **and** v2 symmetric surface distance by at least 5% where v2 is
available, without a new collision or unsupported-placement failure.  These
are engineering triage thresholds, not statistical significance claims from
three inputs.  Report contrary per-view or directional metrics rather than
averaging them away.

## Confounders and exclusions

- All three sources are non-watertight, so protected-empty cells are correctly
  zero.  Do not call hull additions proven false fill or infer missing interiors.
- The projection hull has only three orthographic constraints; concavities and
  depth ambiguity remain distinct from sampling and cap effects.
- Current independent-axis normalization changes a source's world scale and
  aspect interpretation.  Hold it constant; this experiment does not evaluate
  physical size preservation.
- Fixed source order, hardware, solver version, one worker, catalogue revision,
  and colour policy are controls.  Runtime remains environment-dependent.
- Silhouette-v1 uses three views and 128-pixel rasters; it cannot establish
  hidden-surface, depth, texture, or perceptual fidelity.
- Buildability and collision diagnostics are necessary gates, not claims of
  structural stability, clutch force, or feasible assembly insertion.

## Ranked follow-on engineering changes

| Rank | Change | Expected fidelity benefit | Complexity | Mechanical-safety risk |
| ---: | --- | --- | --- | --- |
| 1 | Offline fixed-lattice/evidence/cap diagnostic seam and this 12-run matrix | High information value; identifies whether cap or sampling merits work | Low | Low; reuses gates |
| 2 | Versioned chunked surface metric v2 | High observability for 39--40k-triangle sources | Moderate | Low; metric only |
| 3 | If 2x evidence helps, improve source-evidence reduction at fixed lattice | Potentially moderate silhouette/surface gain | Moderate | Low-to-moderate; retain gates |
| 4 | If 60 cap helps, tune packing objective/candidate selection at fixed lattice | Potentially moderate | Moderate | Moderate; all safety regressions required |
| 5 | Conservative visible-opening evidence experiment | Potentially high on architectural holes | Moderate | High; open-mesh topology is uncertain |
| 6 | Add mechanically calibrated part families | Potentially high on curves/roofs | High | High; every part needs geometry/connector evidence |

Do not pursue a finer physical LEGO lattice or V8 until the matrix identifies a
specific bottleneck.  Increasing solver limits, adding unverified shapes, or
post-scaling models would add cost or weaken the controlled comparison without
answering the causal question.

## Recommended next implementation

Implement only an **offline diagnostic runner** with an explicit, validated
fixed `GridSize`, `sourceEvidenceResolution` of 1 or 2, separate `maxParts`,
and a fixed solver `targetParts`.  It must not be callable through
`convert_glb`, API schemas, workers, or persisted production conversion
settings.  Version its output (for example `m7b-scale-controlled-v1`) and add
focused deterministic tests for fixed-envelope invariance, 1x reproduction,
2x reduction determinism, cap enforcement, and honest unavailable/timeout
records.  Its measurable acceptance criteria are the five per-point criteria
above plus successful completion of the declared 12-point matrix within the
batch budget.  This is the smallest change that can tell the team whether to
invest in source evidence, packing, or neither while preserving physical LEGO
dimensions and all existing safeguards.
