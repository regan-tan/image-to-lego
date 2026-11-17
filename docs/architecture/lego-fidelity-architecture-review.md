# LEGO Geometric Fidelity Architecture Review

Status: design/investigation assessment only. This document proposes no production converter, API, worker, catalogue, or deployment change.

## Executive summary

The most promising next milestone is an **offline-only, evaluation-aligned catalogue-geometry experiment**. It should first make the experimental candidate set demonstrably V6-feasible, then compare a small, mechanically verified non-rectangular vocabulary against V6 at fixed lattices and envelopes. The solver may use a clearly labelled fixed-frame surrogate, but promotion must be judged by frozen completed-assembly `silhouette-v1` and `placement-surface-proxy-v2-chunked`, never by that surrogate.

This is the smallest credible way to learn whether real LEGO geometry can make reconstructions more recognizable. It combines the representation opportunity with the M8C/M8D controls. It is not a proposal to promote another packing optimizer.

Do not make larger output models the next production change. A larger grid is a larger physical model with standard LEGO, but the current evidence has not isolated its benefit from grid selection, candidate growth, and solver behaviour. Raising only a part cap on a fixed lattice cannot add physical spatial resolution. M7B found no decision-relevant gain from cap 30 to 60 at fixed lattices.

**Fact** denotes code or experiment evidence. **Hypothesis** denotes an engineering prediction, not a conclusion from the three-model corpus.

## Evidence and implementation reviewed

This review covered V4--V7 in `backend/app/conversion/core.py`, V4 CP-SAT packing in `surface_grid_v4.py`, collision/support machinery, the fixed-grid seam, M8C/M8D modules, and M7B--M8D reports.

| Area | Code-grounded finding | Consequence |
| --- | --- | --- |
| V3/V4 | V3 voxelizes a normalized surface, locks eligible 4286 slopes, and greedily packs cells. V4 forms a three-view projection-hull target; CP-SAT maximizes projected witnesses then minimizes parts. | It does not optimize source distance, concavity, or recognition. |
| V5/V6 | V5 adds a hard cap, protected empty space, locked-slope body exclusion, reachability pruning, support repair, and final collision/support gates. V6 tries at most 64 local 4286 substitutions. | V6 is the appropriate guarded baseline, not a global shape optimiser. |
| V7 | V7 starts with V6 and accepts only a strict complete-model connectivity improvement; its experiment is bounded at 2,000 candidates/modelled edges. | It is not a general fidelity solution. |
| Normalization | `_normalize_vertices` maps up axis and translates minima to zero. `_scale_vertices_to_grid` independently scales X/Y/Z to the selected integer grid. | It is source-aligned, but does not preserve world scale or aspect across grids. |
| Lattice | `GridSize(w,d,h)` maps to `8w x 8d x 3.2h` mm. | Different integer grids normally have different physical envelopes. |
| Active vocabulary | Fifteen fitter-enabled parts: seven bricks, seven plates, and only 4286 (3 x 1 33-degree slope). CP-SAT candidates are rectangular; 4286 is locked/local refinement geometry. | Curves, diagonal facets, limbs, and fine roof profiles are underrepresented. |
| Other shapes | 41769/41770 wedges and 15068 curved slope have visual/proxy evidence but are mechanically unevaluated and fitter-disabled. | A render mesh/catalogue row alone must never make a part selectable. |
| Empty space | V5 protects face-connected exterior cells only for watertight sources. All three real meshes are non-watertight, so their protected-empty counts are correctly zero. | Apparent holes are uncertain topology, not permission to fill all empty voxels. |
| Mechanics | Final V5/V6 gates reject body-proxy collisions and unsupported evaluated placements. `stud-connectivity-v1` is vertical support; insertion analysis is rectangular-only. | Passing gates is necessary, not a proof of clutch force, stability, hand access, or full buildability. |
| Evaluation | `silhouette-v1` is 128-pixel, three-view, completed-assembly rendering. Surface V2 is bounded and can honestly be unavailable. | Frozen metrics are acceptance measurements, not mechanical proof. |

### What M7B--M8D establish

- **Fact:** At M7B fixed lattices, 2x source evidence did not yield a decision-relevant gain; cap 60 did not improve mean silhouette by 0.01 or more over cap 30. Every result passed collision and evaluated-support gates.
- **Fact:** M8B found substantial loss before final packing in the coarse source-surface lattice. It did not calculate a catalogue-constrained optimum.
- **Fact:** M8C did not improve frozen evaluation: Duck fell from .591700 to .578348; Mansion and Realistic man were unchanged. Its solutions were bounded `FEASIBLE` incumbents of a surrogate.
- **Fact:** M8D proved the M8C hard model cannot select V6's rectangle baseline for Duck or Mansion, although completed V6 builds pass physical gates. Realistic man is feasible.
- **Fact:** M8D proved exact completed-assembly renderer parity with frozen `silhouette-v1`. Candidate-level equivalence remains unavailable because frozen bounds depend on selected geometry.
- **Not established:** global grid optimality; that larger physical models cannot help; that richer geometry cannot help; or that no catalogue-feasible build can beat V6.

## A. Larger physical LEGO reconstructions

### What genuinely makes a model larger

With unchanged LEGO dimensions, increase one or more selected `GridSize` dimensions. A grid `(w,d,h)` is physically `8w x 8d x 3.2h` mm. There is no second finer integer grid for the same exact envelope. The public path does this only indirectly: a higher `targetParts` lets V3's grid search select a larger cell budget and potentially a larger envelope. There is no explicit physical-size setting.

For V5/V6/V7, when `maxParts` is supplied:

    gridTargetParts = min(targetParts, max(1, maxParts // 4))

The quarter-cap rule is a documented candidate/solver safeguard. For desired V3 grid-search target `P`, `targetParts >= P` and `maxParts >= 4P` are needed to avoid that intentional coarsening. This is not a claim that every model needs four times as many parts.

Increasing `maxParts` on an explicit fixed lattice relaxes selected-placement count only. It cannot make another stud/plate of feature detail or enlarge the model. M7B demonstrated this distinction.

| Dimension | Assessment |
| --- | --- |
| Fidelity opportunity | **Hypothesis: medium--high.** More physical cells can represent detail, but no controlled larger-lattice result exists. |
| Complexity | Moderate offline; higher in product because settings express part preference/cap, not physical size. |
| Runtime/memory | High risk: the grid limit is 250,000 cells, but candidates and CP-SAT constraints grow quickly. V7 caps at 2,000 candidates; M8C at 4,000. Existing deterministic stage budgets may produce no incumbent. |
| Mechanical risk | Existing gates apply, but slender detail can increase fragmentation, unsupported parts, and insertion uncertainty. |
| Compatibility | V4 can indirectly select larger grids. V5/V6 cap coarsening can counteract a request; changing it is a production reliability choice. |
| Falsification | At predeclared larger grids, compare V6 with current V6 and report actual envelopes, not "matched scale." If fewer than two sources gain .01 silhouette without worse available Surface V2 or gate failure, do not add a scale option. |

Direction A is real capacity, not budget inflation, but is not next: its benefit and cost remain unisolated.

## B. Richer geometry representation

The active fitter is rectangular packing plus 4286. Boxes approximate curved bodies, and a 3 x 1 33-degree ramp cannot express arbitrary roof pitch, wedge facets, or smooth limbs. Candidate enumeration remains rectangular even where rendering/collision code knows another shape.

4286 is a controlled positive proof that shape can matter: its source-ramp fixture improved mean silhouette .834656 to 1.0 under the defined support/collision checks. It does not transfer automatically: M7B rejected all 64 local V6 candidates on every real mesh. That only rejects the current local policy, not slopes globally.

| Shape class | State | Opportunity and prerequisite |
| --- | --- | --- |
| More rectangular sizes | Existing 1x1 through 2x4 brick/plate footprints. | Mostly efficiency/connectivity, not a new boundary shape class. |
| 4286 slope | Enabled, four rotations, physical proxy, verified support; only locked/local placement. | An aligned global candidate experiment can test it fairly. |
| 41769/41770 wedge plates | Geometry/proxy evidence; mechanically unevaluated and disabled. | **Hypothesis:** roof/diagonal benefit. First establish receivers, mating rules, transforms, collision shape, and fixtures. |
| 15068 curved slope | Quarter-cylinder proxy; mechanically unevaluated and disabled. | **Hypothesis:** curvature/limb benefit, but highest mechanical uncertainty. Do not select it first without a reviewed contract. |

Do not admit all shapes at once. Test at most one newly verified family. If none can be verified, the aligned 4286-only experiment still resolves the modelling prerequisite without widening production eligibility.

| Dimension | Assessment |
| --- | --- |
| Fidelity opportunity | **Hypothesis: high** for curved/tapered/faceted silhouettes; no real-corpus positive result yet. |
| Complexity | Moderate for 4286; high for a new family because connectors, collision geometry, orientations, and tests are required. |
| Runtime/memory | Legal origins/orientations multiply candidates. Bound per-family and total candidates before building CP-SAT. |
| Mechanical risk | High unless each emitted shape has verified support metadata and physical proxy. Insertion remains partial. |
| Compatibility | Keep vocabulary offline and fitter-disabled until it wins the benchmark; V4--V7 output remains unchanged. |
| Falsification | Same grids/envelopes/caps, current V6 versus exactly one verified family. No consistent gain on two sources, or any gate failure, is no-go. |

## C. Improved geometric optimization

M8C does not prove optimisation lacks value. It proves an optimizer cannot be judged by a different score over a different feasible set. A defensible follow-up requires:

1. **One coverage contract.** Choose V6 best-effort achieved coverage or M8C hard witnesses. Rebuild V6 under that exact model and assert baseline feasibility before comparison.
2. **One geometry contract.** Candidate masks, locked slopes, repair, and completed assemblies must use identical orientation-aware geometry.
3. **Surrogate separation.** Dynamic `silhouette-v1` bounds cannot be precomputed before selection. A fixed frame is acceptable only as a versioned surrogate. Optimize exact fixed-frame IoU (or a bounded procedure selecting it), not merely `TP - FP`; retain frozen evaluation independently.
4. **Repair is feasibility.** Encode repair, or prohibit post-solve mutation for both compared candidates and use repair only as a final rejection gate. Never score a pre-repair build as delivered.
5. **Honest bounded reporting.** Capture candidate/group counts, status, incumbent/bound, runtime, cap, and exact baseline-feasibility status. Solver bounds apply only to the declared surrogate.

| Dimension | Assessment |
| --- | --- |
| Opportunity | Indirect but necessary. **Fact:** M8C cannot rank frozen IoU reliably; alignment determines whether candidate selection leaves quality on the table. |
| Complexity | Moderate--high because dynamic frozen bounds are selection-dependent. |
| Runtime/memory | Pixel-union CP-SAT is costly: M8C bounded 49,152 raw pixels, 4,000 candidates, 20 deterministic units. |
| Mechanical risk | Low if V6's verified feasible set/final gates are retained; high if coverage/support is weakened. |
| Falsification | If aligned current-vocabulary solving cannot beat V6 on frozen metrics for two sources, do not build another production optimizer. Redirect to scale or verified geometry. |

## Comparison and decision

| Direction | Opportunity | Current blocker | Decision |
| --- | --- | --- | --- |
| A. Larger physical models | Real extra cells/millimetres | Benefit unisolated; grid/cap/runtime coupled | Defer. |
| B. Richer geometry | Direct representation of curves/facets | Most shapes lack mechanics | Test offline, one verified family at a time. |
| C. Alignment | Makes future tests interpretable | M8C differs from V6/frozen evaluation | Required foundation. |

## Recommended milestone: M9 evaluation-aligned catalogue geometry experiment

This is one offline milestone, not a product feature. It performs C only as needed to get a defensible answer to B.

### Exact scope

1. Add an offline-only M9 module/runner accepting only the pinned local manifest, M7B grids, 1x evidence, `solverTargetParts=24`, and `maxParts=60`.
2. Rebuild V6 and the experimental candidate set through one shared construction path. Fix V6 rectangular selections in the same model; Duck, Mansion, and Realistic man must all be feasible before any comparison.
3. Use a single coverage contract. Recommended: V6's best-effort achieved projection coverage, recorded exactly, rather than M8C hard witnesses.
4. Add a versioned, selection-independent fixed-frame raster helper for solver scoring. It must use exact fixed-frame IoU (not `TP - FP`). Frozen `silhouette-v1` remains the independent result evaluator.
5. Run an aligned-current-vocabulary solve and, only after mechanics review, a solve with one new family. Preferred initial family is wedge plates for roof facets only after verified receiver/collision/orientation tests exist. If unavailable, M9 is 4286-only and the new family is deferred.
6. Include support repair in the shared feasible construction, or disable it symmetrically and use it only as a final rejection gate. No pre-repair scoring versus post-repair evaluation.

### Minimal code changes

- An offline module/script alongside M8C; never imported by `convert_glb`, API, workers, or frontend.
- A narrowly named shared experimental candidate/coverage builder extracted from V5/V6 steps, with an exact V6 baseline-feasibility assertion. Do not replace the production V4 solver.
- Fixed-frame helper plus synthetic objective/ranking/parity tests. Do not alter frozen `silhouette-v1` or Surface V2.
- Only if a new family is admitted: curated mechanical metadata, physical proxy/orientation code, and family-specific tests. Keep `fitterEnabled: false`.
- Ignored M9 artifacts and testing documentation only. No API version, conversion setting, schema, queue, or worker change.

### Controlled benchmark

| Control | Requirement |
| --- | --- |
| Corpus | Duck, Mansion, Realistic man; verify SHA-256 before every point. Never persist source bytes, paths, private placements, or URLs. |
| Matched physical scale | Fixed M7B grids: Duck 5x7x12 / 40x56x38.4 mm; Mansion 7x4x12 / 56x32x38.4 mm; Realistic man 3x5x18 / 24x40x57.6 mm. Matched within a source only. |
| Baseline | Reconstructed V6, 1x evidence, target 24/cap 60, same colour policy, seed, workers. Assert exact M9-model feasibility. |
| Variants | V6 passthrough control; aligned current vocabulary; one verified expanded family. |
| Evaluation | Frozen `silhouette-v1`; frozen `placement-surface-proxy-v2-chunked` at existing limits. Preserve unavailable as unavailable. Record FP/FN and renderer parity without private geometry. |
| Gates | Zero collisions, protected-space violations, unsupported evaluated placements, and cap violations; exact candidate membership; report components and insertion analysis. Do not call these full physical certification. |
| Reproducibility | Seed 0, one worker, named deterministic budgets, versioned schema, source hash, grid/envelope, catalogue/connector fingerprints, candidate/group count, status/incumbent/bound. Two runs must match except timing. |

### Budgets and production safeguards

Start at M8C's proven ceiling: 4,000 candidates, 49,152 raw pixels, one solver worker, 20 deterministic solver-time units per primary solve, and 180 seconds end-to-end per source/variant. Retain Surface V2's existing 30-second observation budget. Candidate-limit, no-incumbent, over-budget, or baseline-infeasible outcomes are recorded failures; do not relax limits or silently fall back.

Write only ignored `artifacts/m9-.../` output. There is no API entry point. Production catalogue eligibility and V4--V7 dispatch are untouched. Deleting the offline module/script is a complete rollback.

### GO / NO-GO

**GO to a narrow production design review only when all conditions hold:**

1. All reconstructed V6 baselines are feasible in the exact M9 model, and the passthrough has frozen-metric parity.
2. The expanded verified vocabulary improves frozen mean `silhouette-v1` by at least .01 on at least two sources, with no source worse by more than .005.
3. For every available paired Surface V2 result, mean and P95 do not regress beyond current shape-aware tolerances: max(.05 mm, 1%) mean and .1 mm P95. Unavailable is not improvement evidence.
4. Every output passes collision, protected-space, cap, evaluated support, exact-candidate, and reproducibility gates. A component-count increase requires explicit review; no automatic exception.
5. All points stay inside stated budgets on two deterministic runs.

**NO-GO:** keep V4--V7 unchanged if baseline feasibility differs, a shape lacks a verified contract, a gate fails, the improvement rule fails, ranking disagreement lacks a documented cause, or budgets are exceeded. The next investigation is then a modest larger-physical-lattice study using this aligned harness, not another unconstrained packing objective.

## Production safety conclusion

Keep production unchanged. Its bounded grids/candidates, cap, watertight-only empty-space protection, collision proxy, and verified vertical support are more valuable than speculative fidelity. M9 creates the evidence to decide whether one mechanically verified geometry family belongs in production or physical scale is the next controlled capacity study.
