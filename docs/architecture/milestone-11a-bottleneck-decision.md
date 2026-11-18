# Milestone 11A: LEGO Reconstruction Bottleneck and Engineering Direction Assessment

Status: completed assessment. This is documentation only. It changes no V4--V7
converter path, catalogue eligibility, metric, API, worker, private artifact, or
resource limit.

## Executive conclusion

**Recommendation: C - neither candidate reduction nor a new geometry family is
ready for an engineering experiment.**

The immediate, bounded milestone is an **offline candidate-space proof audit**,
not a pruning implementation: establish whether the present V6 candidate model
contains any mechanically exact duplicate decision variables. If it does not,
as the current enumeration strongly indicates, record the zero result and do
not build a reduction experiment around heuristic dominance. This is the only
small next step that can answer a concrete uncertainty without changing the
feasible set, mechanical contract, or frozen evaluation.

This is deliberately a NO-GO for a fidelity-improving implementation today.
It is more defensible than calling a potentially lossy heuristic "safe" merely
to bring Duck's 1.5x candidate count below 4,000. M9B independently blocks the
geometry direction: every inactive non-rectangular family lacks the verified
connector/receiver and support contract required to make an assembled-model
claim.

The central observation is not a causal proof that scale or richer geometry
cannot improve recognizability. It is that the current evidence does not admit
either as a valid, bounded next experiment:

- Duck and Mansion cannot enter the 1.5x experiment at 6,019 and 11,066
  reachable candidates. Those are real larger LEGO lattices, not extra sampling.
- The only completed 1.5x pilot (Realistic man) fell from 0.452924 to 0.439103
  scale-normalized mean IoU and worsened from two to three components. Its
  60-to-120 cap change also confounds scale with part budget.
- The inactive wedges and curved slope have visual/collision proxies, but no
  verified mechanical metadata. A proxy is not a support, contact, insertion,
  or export contract.

Accordingly, do not implement an optimiser, a scale option, candidate pruning,
or a geometry family as M11A follow-up work.

## Evidence from M7B through M10B

| Milestone | Observation | What it supports | What it does not establish |
| --- | --- | --- | --- |
| M7B | Frozen baseline mean IoU was Duck 0.591700, Mansion 0.600598, and Realistic man 0.421959. Neither 2x source evidence nor cap 60 versus 30 produced a decision-level gain. | More evidence or placement budget at a fixed lattice is not a demonstrated remedy. | Larger physical lattices cannot help. |
| M8A | A source-aware tie-break changed assemblies and source-cell retention, but improved frozen mean IoU by at least 0.01 on none of the three sources. | Packing tie-breaks are not the demonstrated main bottleneck. | No catalogue-feasible arrangement can be better. |
| M8B | Coarse axis-aligned surface representation retained large false-positive regions before packing; V6 did not calculate a catalogue-constrained source-mesh optimum. | Quantisation/vocabulary are plausible limiting stages. | A continuous or richer LEGO representation has no benefit. |
| M8C/M8D | M8C's bounded `TP - FP` surrogate did not improve frozen evaluation. M8D found its hard model excluded the Duck/Mansion V6 baselines because locked-slope coverage was modeled differently. | Objective and feasible-set alignment are necessary for interpretable optimisation results. | A bounded incumbent is a global geometric optimum. |
| M9A | Correcting only fixed locked-slope source-profile coverage made all three V6 baselines feasible under the experimental model. Duck's frozen change was +0.003549; Mansion and Realistic man were unchanged. | The corrected experiment is mechanically gated and baseline-feasible. | Material, general fidelity improvement or global optimality. |
| M9B | `41769`/`41770` and `15068` were rejected before experiment because all are mechanically unevaluated. | Catalogue geometry cannot be admitted from visual/proxy data alone. | Richer authentic parts are useless. |
| M10A/M10B | 1.5x grids are genuine larger objects. Duck and Mansion exceeded the 4,000-candidate limit; Realistic man alone completed. | Candidate growth is the immediate experimental bottleneck. | Raising a limit or pruning candidates is safe. |

M10B's Realistic-man pilot returned `OPTIMAL` coverage stages but `FEASIBLE`
tie-break stages with nonzero gaps. It is therefore not a global complete
solver or geometric optimum. Its zero collision, unsupported-placement, and
protected-space counts are necessary safety evidence only; the extra component
and isolated placement prevent calling the pilot an overall mechanical gain.

## Code-grounded candidate-space diagnosis

### Current construction path

The M10B preflight and V6 fixed-grid path use the same relevant construction:

1. `fixed_grid_experiment._source_occupancy_for_evidence()` creates surface
   evidence. `core._place_supported_slopes()` locks eligible `4286` slopes.
2. `projection_hull_target()` in
   `backend/app/conversion/surface_grid_v4.py` creates the projection-hull
   target and required front/side/top witness pixels. V5 protected empty space
   is passed in before candidate enumeration; non-watertight real sources have
   no proven protected cells.
3. `_enumerate_candidates()` creates one rectangular candidate for each
   target origin, fitter-enabled rectangular part, and legal orientation. A
   square part has only orientation zero; a non-square part has 0 and 90.
   Each candidate must have all its lattice cells inside the target.
4. `_exclude_locked_body_collisions()` removes a candidate that overlaps a
   locked slope's physical body proxy. `_support_reachable_candidates()` then
   keeps only candidates with a possible direct-support chain to the target
   base.
5. `_build_model()` creates one selection Boolean per retained candidate,
   occupancy variables for target cells, coverage variables for witness rays,
   exact cell non-overlap, direct support contacts, and the part cap. The
   post-solve locked-support repair and `_validate_placements()` retain final
   support, collision, cap, and buildability checks.

`physical_scale_experiment.preflight_fixed_grid()` executes steps 1--4 without
CP-SAT and reports the retained count. Thus M10B's 6,019 and 11,066 are not a
render/reporting figure: they are the number of proposed CP-SAT selection
variables after locked-body collision and support-reachability filtering.

Candidate count grows because a larger physical grid has more target origins
and the same rectangular vocabulary/orientation choices is tested at each
origin. The larger points contain 1,440, 1,080, and 864 lattice cells versus
420, 336, and 270 at baseline. Hull topology, locked slopes, and support
filtering change density, so this is not a simple cubic extrapolation, but it
is genuine decision-space growth.

### Candidate-reduction audit

| Technique | Present state and decision-space effect | Feasible-set/certificate assessment | Mechanical and fidelity risk |
| --- | --- | --- | --- |
| Exact duplicate placement removal | Not implemented as a separate pass, but enumeration is already canonical: one origin, part ID, and normalized legal orientation produces one candidate. No duplicated rectangular dimensions occur in the active catalogue. | Safe only when part ID, orientation, occupied cells, body proxy, and mechanical connector transform are identical. A stable signature equality check supplies a direct certificate. | None if all signature fields match; expected current reduction is zero. |
| Geometric equivalence by occupied cells or projected pixels | Not present. Pixel-equivalence grouping exists only in M8C's raster **objective** variables; it does not merge candidate selection variables. | Equal pixels, or even equal cells, is insufficient unless all support producer/receiver, locked-body collision, repair, and export semantics also match. Equal silhouette is not an equivalence proof. | High: physically distinct placements can block, support, connect, or repair differently. |
| Dominance by silhouette/coverage score or part count | Not present. | No valid certificate in this model. A lower-scoring candidate may be the only supporter, avoid a collision, preserve a locked slope, or enable a different non-overlapping combination. | High risk of excluding a high-fidelity or mechanically valid assembly. |
| Source-aware eligibility pruning | M8A adds an offline objective only; it does not narrow V6 candidate eligibility. | Source-cell membership is not a hard feasibility rule. The projection hull intentionally preserves depth ambiguity and M8A did not show a general gain. | High risk of removing a required witness/support arrangement. |
| Existing pixel-equivalence groups | M8C exactly groups pixels with the same selecting-candidate set and source membership. It reduces raster-objective Booleans only. | Exact for that fixed-frame union objective, not for V6 candidate selection, collision, support, or frozen dynamic-frame IoU. | No assembly effect today; no help for M10B's selection-variable ceiling. |
| Forward support reachability | Already implemented before CP-SAT. | It removes candidates with no possible direct-support chain in the current target. It is a feasibility-preserving eligibility filter under the current vertical-support model. | Already accounted for in M10B counts; cannot be claimed again as new reduction. |
| Reverse support/coverage relevance | Not implemented. | A proof would require retaining every candidate that can cover any variable witness, every transitive supporter of such a candidate, every transitive supporter of a locked receiver, and every candidate reachable by the locked-support repair. The current repair can replace selected local candidates, so a partial backward traversal is not a certificate. | Medium to high unless the repair closure and all contact relations are modeled exactly; likely limited reduction because hull target cells themselves project to required witnesses. |
| Lazy/staged/hierarchical generation | Not implemented. | It changes search construction, not merely a reporting count. Exactness would require a complete separation/oracle procedure and proof that omitted candidates cannot improve the declared objective or restore feasibility. | Medium to high; a heuristic stage can exclude high-fidelity alternatives. |

The one candidate technique worth checking is therefore **exact full-signature
duplicate detection**, solely because it has a crisp correctness certificate.
It is not approved as an implementation-based solution: the source audit
predicts zero duplicates in the current active catalogue. A zero result is a
useful answer because it rules out presenting deduplication as the explanation
for the 1.5x bottleneck.

This distinction matters:

- Removing full-signature duplicates retains the full feasible set after a
  deterministic representative mapping. It preserves every declared objective
  only if the signature includes every constraint- and export-observable
  property.
- Removing dominated or "same silhouette" candidates does **not** retain the
  full feasible set. At best it might preserve an optimum under a newly stated
  objective and a proof that ignores no support, collision, locked-slope,
  protected-space, connectivity, repair, or export interaction. No such proof
  exists here.

## Mechanical geometry capability diagnosis

The active fitter has seven brick families, seven plate families, and verified
`4286` slope geometry. `4286` is already active and so is not an expansion.

| Unavailable family | Authentic identity/geometry evidence | Missing capability that blocks admission | Isolated fixture valid now? |
| --- | --- | --- | --- |
| `41769`/`41770` wedge plates | Canonical identities, LDraw IDs, discrete XY footprint, four rotations, and sampled body proxy. | Verified underside receivers, top studs, mating/support contact rules, all orientation transforms, and a physical/export contract. `stud-connectivity-v1` marks them `UNEVALUATED`. | No. A footprint fixture would prove only silhouette/fit, while falsely implying support safety. |
| `15068` curved slope | Canonical identity, LDraw ID, and a quarter-cylinder collision proxy. | The proxy is explicitly non-authoritative for the hollow moulding; connector/receiver, contact, orientation, support, and export behavior are absent. | No. There is no mechanically honest fixture to run. |

`physical_geometry.py` is intentionally separate from mechanical metadata.
`resolve_part_mechanical_metadata()` returns metadata only for rectangular
brick/plate families and curated `4286`; it returns `None` for all three
inactive shapes. This is the correct fail-closed behavior. A geometry
expansion could be reconsidered only after authoritative part body and
connector evidence is curated, transformed, collision-checked against current
parts, independently support-tested, and exported in every allowed
orientation. Until then, a synthetic fixture must not be constructed.

## Direction comparison

| Criterion | A. Candidate reduction | B. Verified new geometry | C. Evidence-gap closure (recommended) |
| --- | --- | --- | --- |
| Likelihood of near-term frozen-fidelity gain | Low: reduction enables an experiment but does not add representation. | Potentially high hypothesis; unmeasured. | None directly; prevents an invalid claim. |
| Existing evidence | M10B proves capacity pressure, but not redundant candidates. | M9B proves all available inactive families are mechanically incomplete. | Strong, directly code- and report-grounded. |
| Correctness risk | High for dominance/heuristics; negligible only for exact duplicates. | High until physical contracts exist. | Low. |
| Mechanical safety risk | Must preserve collision, support, protected space, locks, repair, and connectivity semantics. | Cannot be assessed for unavailable parts. | None; no placement behavior changes. |
| Effort / runtime | Small audit; a valid nontrivial reducer is moderate-to-high and may not reduce enough. | High evidence and implementation effort before an A/B run. | Small, bounded documentation/test-audit work. |
| Reuse across V4--V7 | A proven canonicalization could be shared; heuristic pruning should not be. | A fully verified family could be reusable, after separate approval. | Reusable decision record; no production coupling. |
| One bounded meaningful answer | Yes only for the duplicate audit; it may truthfully answer "zero." | No; authoritative mechanics are missing. | Yes: it records whether any safe reduction exists. |

## Exact bounded next-milestone plan

### Scope and seam

Create no new solver or catalogue code for M11A. The only implementation seam
to inspect is the tuple returned by `_enumerate_candidates()` after
`_exclude_locked_body_collisions()` and `_support_reachable_candidates()` in
`surface_grid_v4.py`, as exercised by
`physical_scale_experiment.preflight_fixed_grid()`.

If, and only if, a later approved follow-up is requested, add an offline-only
audit function next to `physical_scale_experiment.py`. It must emit a stable
signature for every retained candidate containing:

- canonical part ID, origin, and orientation;
- occupied lattice cells and physical-body microcells;
- transformed male and receiver connector coordinates;
- variable witness-pixel incidence;
- locked-body collision result; and
- support producer/consumer contact incidence.

Only two candidates with identical complete signatures may share a
representative. The audit must prove the mapping is bijective between each
removed candidate and its retained representative for every listed property.
The fixed part identity requirement intentionally makes current duplicates
unlikely; substituting different part IDs is an export/BOM change and is not
equivalence.

Expected changed files for that future audit are limited to:

- `backend/app/conversion/physical_scale_experiment.py`;
- `backend/tests/test_m10b_physical_scale_experiment.py`; and
- an M11B results document under `docs/testing/`.

This M11A change adds only this decision document.

### Required synthetic verification before any reducer exists

1. A deliberately duplicated synthetic candidate pair must collapse to one
   representative and preserve every signature field.
2. Synthetic pairs differing only in a support contact, locked-slope body
   collision, occupied cell, connector transform, part ID, or orientation must
   remain separate.
3. On a small fixture, solve the unreduced and reduced models and assert the
   same feasibility, selected reconstructed placement set after representative
   expansion, coverage, cap, collision, direct-support, buildability, and
   connectivity diagnostics.
4. The existing locked-support repair fixture must demonstrate that the audit
   does not merge or drop repair-distinct candidates.

No synthetic geometry-family fixture is authorized while its mechanical
metadata remains absent.

### Private-corpus method and limits

Do not read the private corpus for M11A. The audit first requires only checked
in synthetic fixtures. If it finds a nonzero, formally certified reduction,
an explicitly approved M11B may use the existing SHA-256-pinned corpus and
the M10B Duck-first protocol. It must retain the 4,000 reachable-candidate
ceiling **before and after** reporting canonicalization, one solver worker,
seed zero, existing deterministic stage budgets, the 180-second point limit,
and Surface Metric V2's 30-second observation limit. No source bytes, paths,
placements, meshes, or artifacts may be committed.

M11B must compare a full model with the canonicalized model on the same Duck
1.5x input before any corpus metric comparison. Candidate count is reported
before and after, but only actual CP-SAT selection-variable count is used for
the ceiling. Frozen `silhouette-v1`, scale-normalized geometry, and Surface V2
remain unchanged and independently reported.

### GO / NO-GO and rollback

**GO to M11B only when all of the following hold:**

1. The exact signature proof and all synthetic tests pass.
2. The audit shows a nonzero reduction on the proposed Duck 1.5x preflight.
3. Full versus canonicalized Duck solves have exact expanded-placement and
   safety parity on two deterministic runs, except wall time.
4. The canonicalized Duck point is at or below 4,000 actual selection
   variables without increasing any resource limit or weakening a safeguard.

**NO-GO** if the audit finds zero duplicates, a signature mismatch, any
full-versus-reduced parity failure, a candidate limit failure, no incumbent,
timeout, collision, unsupported placement, protected-space violation, cap
violation, or connectivity regression. A NO-GO leaves V4--V7 unchanged and
does not license a dominance heuristic or a geometry expansion.

Rollback for a future audit is deletion of its offline-only helper, test, and
ignored measurement output. It must have no production imports, migrations,
API flags, catalogue `fitterEnabled` changes, or persisted artifacts; therefore
rollback cannot affect an existing conversion or user model.

## Reproducibility and final safety constraints

All future work in this direction must retain current verified catalogue
eligibility/orientations, target construction, watertight-only protected-space
handling, locked-slope body exclusion, direct support, final collision and
buildability gates, hard cap, connectivity reporting, seed zero, and one
solver worker. It must report candidate counts at every filtering stage,
catalogue and connector fingerprints, solver status/objective/bound/gap,
runtime, and a versioned aggregate schema.

Collision-free, direct-support-evaluated, and connected are separate claims;
none proves clutch force, stability, insertion accessibility, or consumer
buildability. No M11 result may present a lower count, an improved solver
surrogate, or an available visual proxy as evidence of those stronger claims.
