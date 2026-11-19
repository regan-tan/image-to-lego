# Milestone 12C: Controlled Offline Wedge Fidelity Experiment

## Status

**INCONCLUSIVE — the initial real-world Experiment B selections were rejected
by post-solve validation.** The three private, SHA-256-pinned cases completed
preflight below the 4,000 candidate cap, while Control A reproduced its frozen
IoUs (Duck `0.595249`, Mansion `0.600598`, Realistic man `0.421959`) with exact
evaluator parity. The initial B selections were never accepted or scored as
reconstructions.

| Model | Control candidates | Eligible wedges | Expanded | Solver status | Initial B result |
| --- | ---: | ---: | ---: | --- | --- |
| Duck | 1,449 | 512 | 1,961 | FEASIBLE | rejected post-solve |
| Mansion | 3,166 | 352 | 3,518 | FEASIBLE | rejected post-solve |
| Realistic man | 1,043 | 144 | 1,187 | FEASIBLE | rejected post-solve |

No post-correction private result is recorded in this document.

## Frozen domain and provenance

The experiment admits only `41769a` (*Wing 2 x 4 Right without Chamfer*) as
catalogue ID `41769`, with the M12A-pinned LDraw asset
`parts/41769a.dat` (SHA-256
`0b069ab042f2cc8297a52e76b49a06e504cd4e9a51f02d6aea8c63f686c28ff8`).
It supports quarter turns only, the four source-backed top studs, and the five
M12A receiver locations. `41769b`, `41770`, wedge-to-wedge contacts,
wedge-to-slope contacts, sideways/inverted attachment, stability, clutch, and
production export are excluded.

## Integration approach and compatibility limits

`surface_grid_v4` and the M8C/M9A solver remain unchanged. Their rectangular
cell candidates, cell collision model, footprint-overlap support and box-based
candidate raster are not valid wedge representations.

`m12c_wedge_fidelity_experiment.py` is a separate offline adapter. It preserves
the Control A candidate generator verbatim, then appends only wedges that fit
the fixed envelope, avoid protected cells and locked geometry, and do not touch
an unverified locked nonrectangular part. It uses M12A's analytic convex body
collision for every wedge/rectangle pair and exact connector matching for hard
CP-SAT support constraints. Wedge-to-wedge collision is forbidden rather than
being inferred. Mandatory source witnesses use only full unit cells proved to
be inside the wedge; the triangular remainder never satisfies a cell witness.

The TP-minus-FP objective and deterministic solver settings are unchanged.
Candidate masks use the real wedge projection: rectangular front/side prisms
and the M12A top polygon. The adapter deliberately does not run the M9A
post-solve repair, because changing a selected arrangement would make an
objective claim misleading.

## Initial failure diagnosis and correction

The initial failure was a solver-model defect, not a reason to relax the
validator. `_add_wedge_collisions()` considered a pair only when its *first*
candidate was a `WedgeCandidate`. Candidate construction appends wedges after
the unchanged rectangular candidates, so the solver omitted every
rectangle-before-wedge collision implication. M12A's analytic validator did
correctly detect those collisions after solving, which produced
`post_solve_validation_failed`.

The correction checks each pair whenever **either** candidate is a wedge and
adds the same analytic M12A collision hard constraint. It does not alter the
objective, candidate count, envelope, protected-space semantics, support
rules, or any production code. A focused regression forces an overlapping
rectangle followed by a wedge and proves CP-SAT returns `INFEASIBLE` before
post-solve validation.

The diagnostics now retain a rejected solver selection in ignored artifacts:
original status/objective/bound/gap, all part IDs and positions, wedges,
identity-labelled collision pairs, unsupported placements, invalid contacts,
protected-space violations, components/isolates, and the exact failed
predicates. These records distinguish solver feasibility, mechanical
acceptance, and availability for fidelity evaluation. Historical Control A is
also run through the same completed-assembly report; its known disconnected
Mansion and Realistic-man components are reported, not hidden or reclassified.

The frozen `silhouette-v1` evaluator was not changed. It already accepts
explicit wedge vertices; the existing evaluator-parity comparison is recorded
for each completed local run. If parity is false, historical frozen-IoU claims
are invalid and the case is inconclusive.

## Executed synthetic gates

Focused tests in `backend/tests/test_m12c_wedge_fidelity_experiment.py` use an
independently specified 4x2x1 wedge prism target. With one allowed part, the
offline solver selects `41769a`, while the unchanged rectangular catalogue is
still enumerated. Tests also verify:

- Control A candidate preservation.
- Conservative whole-cell coverage (no bounding-box witness for the diagonal).
- M12A analytic body collision and an exterior continuous-point counterexample.
- Rejection of an unsupported receiver contact.
- Candidate-limit termination before CP-SAT.
- The rectangle-before-wedge collision ordering defect.

The focused M12A/M12B/M12C command completed with **38 passing tests** in
this workspace. It contacted no private corpus, provider, cloud service, or
production system.

## Local private benchmark procedure

Approved private GLBs must stay outside Git. Create a private manifest with
the original `duck`, `mansion`, and `realistic-man` paths and SHA-256 values,
then run from the repository root:

```cmd
cd backend
.venv\Scripts\python.exe scripts\run_m12c_wedge_fidelity.py --manifest ..\docs\testing\real-world-glb-benchmark-manifest.private.json --output-dir ..\artifacts\m12c-wedge-fidelity
```

The runner writes only aggregate JSON under the ignored
`artifacts/m12c-wedge-fidelity/` directory. It records Control A and Experiment
B solver status, candidate/preflight counts and rejection reasons, bounds,
runtime, part/wedge count, three-view/mean frozen IoU, fixed-frame metrics,
parity, and the complete wedge-aware mechanical/connectivity report. A case
over 4,000 candidates is skipped before CP-SAT. No existing candidate is
dropped to make room for wedge candidates.

## Acceptance decision and next action

No result can meet the predeclared two-of-three `+0.01` mean-IoU threshold
until the corrected bounded experiment has produced mechanically accepted
arrangements. Therefore the decision remains **INCONCLUSIVE**, not GO or
NO-GO. The justified next action is one Duck-only rerun first, using the exact
command above plus `--case duck`, then reviewing the rejected-selection
diagnostics or accepted A/B record without changing scale, cap, objective,
metric, or solver limits.

## Locked-slope follow-up

The corrected collision-only Duck rerun still rejected its incumbent. Its
single failed predicate was an unsupported fixed `4286@3,0,8:90` slope; there
were zero collision/interface/protected-space findings. This was another
solver-model mismatch: M12C constrained support for selected candidates but
did not require support for elevated locked placements. The independent final
validator correctly checks all mechanically evaluated placements, including
locked `4286` slopes.

M12C now adds a hard constraint for every elevated locked placement with
verified receivers. It first accepts support from another verified locked
placement; otherwise it requires at least one selected candidate with an exact
verified stud-to-receiver relation. A missing supporter makes the model
infeasible. Wedges never qualify as slope supporters because wedge-to-slope
support has not been verified. This is an offline-only correction; V4--V7 and
the production catalogue remain unchanged.

The runner now records both the historical M9A Control A reference and a
separate matched no-wedge control using the same M12C hard constraints and
solver formulation as Experiment B. They must not be conflated: historical
M9A can repair locked support after its global solve, whereas matched control
enforces it during CP-SAT. The focused regressions cover a required selected
supporter, no legal supporter (infeasible), and support supplied by another
fixed slope. A Duck-only rerun is justified only after these checks pass.

## Accepted Duck rerun and objective audit

After the locked-slope correction, Duck produced a mechanically accepted,
time-limited `FEASIBLE` wedge arrangement: 28 parts, including one `41769a`,
one connected component, and zero detected collisions, unsupported placements,
invalid interfaces, or protected-space violations. Its frozen evaluator parity
was exact. The matched no-wedge control had two components. This is a
connectivity observation only; it does not establish that the wedge alone
caused the difference.

| Metric | Matched no-wedge | Wedge experiment |
| --- | ---: | ---: |
| Candidates | 1,449 | 1,961 (512 wedges) |
| Solver objective | 11,386,825 | 15,407,561 |
| Solver-implied TP−FP | 7,853 | 7,853 |
| Historical box/slope-only fixed-frame TP−FP | 7,853 | 7,827 |
| Fixed-frame IoU (historical helper) | 0.600334 | 0.597247 |
| Frozen mean IoU | 0.595249 | 0.592903 |
| Parts / wedges | 28 / 0 | 28 / 1 |
| Components | 2 | 1 |

The apparent wedge-objective discrepancy is a demonstrated reporting defect,
not a CP-SAT objective change. M12C uses the unchanged objective
`(TP - FP) * (candidate_count + 1) - selected_count`. Its candidate raster
includes analytic wedge pixels. The historical `fixed_frame_surrogate_score()`
accepts rectangular boxes and slopes only, so the prior runner omitted the
wedge from its independent fixed-frame mask and reported `7,827`. This helper
remains unchanged for historical comparability; it is not valid for
wedge-containing arrangements.

M12C now exposes a separate geometry-aware fixed-frame score using the same
source-plus-grid frame and candidate raster semantics as the solver, including
per-view TP/FP counts. The runner records it as `m12cFixedFrameScore` alongside
the preserved legacy value and `solverImpliedTpMinusFp`. A deterministic
wedge-prism regression proves that the selected arrangement's geometry-aware
score reconstructs the solver objective exactly. Because this correction
changes reported wedge metrics, Duck should be rerun before Mansion or
Realistic man. The prior accepted Duck result above remains evidence from the
earlier reporting revision and is not silently relabelled.

The frozen-IoU change remains negative (`-0.002346` mean; front `-0.016567`,
side `+0.009529`, top `0`). M12C is still **INCONCLUSIVE**: one accepted case
cannot meet the predeclared two-of-three improvement threshold, and no fidelity
improvement is claimed.

## Final real-world result and decision

**NO-GO for further 41769a fidelity promotion at the tested native 1x grids
and solver budget.** This is a bounded engineering decision, not proof that
nonrectangular geometry can never help: all six M12C solves were time-limited
`FEASIBLE` incumbents, not optimality proofs.

The final comparison uses the **matched no-wedge M12C control**, which has the
same locked-support hard constraints and objective as Experiment B. The older
`control` records remain the historical M9A reference; they preserve M9A's
post-solve locked-support repair and are not substituted for the matched
control. Every SHA-256 in the final records matches the original private
manifest: Duck `77093bb7325d2024bd60a4828510746d53f6b38ba8f9425f30d41cb43f11379e`,
Mansion `d1a9618613f251d528eccc12f99460f9a64c39e83b8b9267e2c4a2b923919510`,
and Realistic man `0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce`.

| Model | Control / wedge candidates | Matched / experiment mean IoU | Delta | Wedges | Components |
| --- | ---: | ---: | ---: | ---: | ---: |
| Duck | 1,449 / 1,961 | 0.595249 / 0.592903 | -0.002346 | 1 | 2 / 1 |
| Mansion | 3,166 / 3,518 | 0.600598 / 0.589479 | -0.011119 | 1 | 5 / 1 |
| Realistic man | 1,043 / 1,187 | 0.421959 / 0.421959 | 0.000000 | 0 | 2 / 3 |

All arrangements passed the offline mechanical gate: zero collision pairs,
unsupported placements, invalid interfaces, and protected-space violations;
each also had exact frozen evaluator parity. All had zero isolated placements
except the Mansion matched control, which had one. No claim of physical
stability, clutch force, insertion feasibility, or production export support
follows from these checks.

| Model / configuration | Status; objective / bound / gap | Runtime s; parts | Frozen front / side / top / mean IoU | Geometry-aware TP / FP / score |
| --- | --- | --- | --- | --- |
| Duck matched | FEASIBLE; 11,386,825 / 11,671,042 / 284,217 | 57.922073; 28 | 0.638589 / 0.619978 / 0.527180 / 0.595249 | 21,588 / 13,735 / 7,853 |
| Duck wedge | FEASIBLE; 15,407,561 / 15,546,886 / 139,325 | 99.850845; 28 | 0.622022 / 0.629507 / 0.527180 / 0.592903 | 21,588 / 13,735 / 7,853 |
| Mansion matched | FEASIBLE; 29,149,045 / 29,149,066 / 21 | 42.359804; 24 | 0.718515 / 0.561107 / 0.522172 / 0.600598 | 27,086 / 17,882 / 9,204 |
| Mansion wedge | FEASIBLE; 32,522,575 / 32,522,597 / 22 | 57.132636; 24 | 0.706820 / 0.539445 / 0.522172 / 0.589479 | 26,974 / 17,732 / 9,242 |
| Realistic man matched | FEASIBLE; -5,809,878 / -5,809,864 / 14 | 53.043081; 18 | 0.426276 / 0.445331 / 0.394271 / 0.421959 | 16,879 / 22,444 / -5,565 |
| Realistic man wedge-eligible | FEASIBLE; -6,611,242 / -6,611,223 / 19 | 61.706005; 22 | 0.426276 / 0.445331 / 0.394271 / 0.421959 | 16,879 / 22,444 / -5,565 |

Mansion demonstrates the intended surrogate/final-metric mismatch: its
geometry-aware TP-minus-FP score rose from `9,204` to `9,242`, while frozen
mean IoU fell by `0.011119`. Duck also regressed slightly, and the Realistic
man did not select a wedge while its connected components worsened from two to
three. Thus zero of three models reached the required `+0.01` mean-IoU gain,
Mansion exceeded the allowed `-0.01` regression, and Realistic man regressed
in connectivity.

The offline mechanical integration is successful: the exact `41769a` geometry
can be enumerated, collision-checked, connector-supported, solver-constrained,
and independently evaluated without changing production V4--V7. The fidelity
promotion is negative at this bounded setting. Production catalogue eligibility
remains disabled; exporter support and physical stability are still unverified.

The recommended next milestone is one small offline-only investigation of why
the fixed-frame TP-minus-FP surrogate and frozen silhouette IoU diverge, with
connectivity retained as a separately measured constraint. It is not
implemented by M12C.
