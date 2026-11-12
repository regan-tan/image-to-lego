# Milestone 5: connectivity-aware LEGO optimization

## Decision

**Superseded by the final Gate A evaluation below.** The historical sections record
the preliminary box-control work; they are retained for traceability. The decisive
evaluation reached Gate A PASS without changing production conversion behavior.

## Starting architecture and insertion point

`solve_surface_grid_v4` enumerates rectangular candidates, removes candidates without a possible
direct-support chain, solves projection coverage, then minimizes part count. V5 adds the hard cap,
protected source-empty cells, and support repair; V6 makes bounded 4286 substitutions after that
result. The completed assembly is finally checked by `analyze_buildability`.

The experimental insertion point is therefore after the established best projection coverage is
known and before the part-count tie-breaker. It must operate on the same protected, support-safe
candidate vocabulary and must re-evaluate the complete assembly after support repair. This is not
yet wired into production because the source-conversion evidence gate is incomplete.

## Root cause and connector index

The prior experiment walked every unordered candidate pair. It transformed the second placement's
connector metadata repeatedly inside that nested loop, then silently returned the first 2,000
matching pairs. That mixed enumeration cost with objective size and made the 2,000 limit report an
incomplete mechanical graph.

The experiment now transforms each candidate's verified connector metadata once. It indexes exact
world-coordinate male studs and underside receivers, joins only matching coordinates, applies the
existing `matching_vertical_connectors` compatibility rule, rejects physical body overlap, and
deduplicates candidate pairs. Coordinates are exact transformed half-stud/plate values; no floating
point rounding is applied. Pair records are sorted by candidate index and multiple stud contacts
remain one graph edge.

`exhaustive_verified_connection_pairs` remains a small-fixture oracle. Tests compare its complete
edge records with the indexed implementation across multiple studs, rotations, height mismatch,
overlap, frozen support, unevaluated parts, empty connector sets, duplicate coordinates, and stable
ordering.

## Supported graph and formulation

Only `stud-connectivity-v1` vertical matches count. Candidate pairs use
`resolve_part_mechanical_metadata`, `transform_connector_to_world`, and
`matching_vertical_connectors`; they exclude overlapping bodies and mechanically unevaluated parts
(including 41769, 41770, and 15068). A pair with several matching studs is one graph edge and
reports its separate stud-contact count.

For candidate selection variables `x_i`, each legal pair has `e_ij` constrained exactly as:

```text
e_ij <= x_i
e_ij <= x_j
e_ij >= x_i + x_j - 1
```

The harness preserves supplied coverage groups and a hard part cap, then maximizes `sum(e_ij)`.
It uses a sparse 2,000-edge *objective* ceiling, deterministic one-worker CP-SAT, seed zero, and a
5.0 deterministic-time budget. The full verified graph remains available to direct-support
constraints. When it exceeds the objective ceiling, the experiment reserves one deterministic
incident edge for each connected candidate, then fills remaining capacity in stable contact-count
and candidate-index order. This does not remove candidates, coverage groups, support options, or
legal placements; it only omits rewards for some mechanically legal edges. The known three-part
bridge retains all of its objective edges. This score is only a search proxy: final acceptance is based on
`analyze_buildability` components, largest-component fraction, isolated placements, and
unsupported placements.

The result records both total eligible pairs and modeled objective pairs. Omitted edges are not
called invalid, and the final selected assembly is always evaluated on the complete graph.

## Feasibility fixture results

| Fixture | Baseline components | Proposed components | Largest fraction before/after | Verified edges before/after | Mean IoU before/after | Accepted? |
| --- | ---: | ---: | --- | --- | --- | --- |
| Equal-coverage vertical bridge | 2 | 1 | 0.667 / 1.000 | 0 / 2 | n/a (placement fixture) | Mechanism only |

The bridge fixture has two equal-coverage choices at the same three-part cap. The objective picks
a lower plate, an aligned bridge plate, and an upper plate rather than an isolated grounded plate.
The completed evaluator reports one component and two verified graph edges. A 2x4 pair also shows
that eight stud contacts remain one selected graph edge. Negative checks exclude overlap, incorrect
height, and unevaluated wedge parts.

## Phase 2 source-mesh adapter

`run_source_mesh_experiment` now derives an offline candidate vocabulary from an actual GLB using
the same source hash, axis, V5 hard-cap grid rule, V3-derived rectangular exterior, V5 protected
empty cells, locked 4286 placements, rectangular catalogue, and projection rays as V5/V6. It first
runs the V6 baseline on the identical bytes, then evaluates the complete proposed assembly including
the frozen placements with the existing buildability evaluator. It also checks the hard cap,
physical body collisions, protected cells, and the canonical silhouette metric.

The adapter deliberately does not call V5 support repair after its selection. A source experiment
with a missing incumbent is evidence of a bounded experimental limitation, not a reason to return
or label V6 as an experimental success. Frozen 4286 placements remain in the final proposal and can
supply a verified direct support path; the proposed solver cannot replace or remove them.

## GLB experiment measurements

The following is an actual local run on the deterministic synthetic-box GLB. It uses the same
normalization, source hash, protected cells, catalogue, direct-support rules, and final evaluator as
the V5/V6 path. This smoke-scale run uses `targetParts=maxParts=12`; it is not a substitute for the
required 100-part ring benchmark.

| Fixture | Candidate count | Naive comparisons | Indexed lookups | True eligible edges | Modeled edges | Pair-build time | Model-build time | Solver time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Synthetic box (12-part smoke run) | 480 | 114,960 | 1,280 | 11,760 | 2,000 | 0.368 s | 0.826 s | 9.382 s |

The total run was 11.981 s. It produced a feasible incumbent, but the final assembly's mean
silhouette IoU was lower than the matched V6 baseline, so the run is explicitly rejected with
`fidelity_regression`. It is not counted as connectivity evidence. The true graph is much larger
than the modeled objective, demonstrating that model size—not the indexed lookup—is now the limiting
factor for this fixture.

Thin-wall, L-profile, and the required 100-part fixed 8x8x6 ring comparison have not yet been run
to completion in this environment. No result is claimed for them. The smallest justified next
experiment is to use the current bounded objective on the 100-part box, then thin-wall and L-profile,
recording final fidelity and buildability for each before attempting the ring.

## Phase 4 fidelity diagnosis and bounded edge audit

The original 12-part synthetic-box smoke comparison was rejected for a precise
reason: it was not part-count matched. V6 completed with **3** placements
(`3001 x2`, `4286 x1`), while the experimental model could select all **12**
allowed placements (`3710 x2`, `3023 x4`, `3001 x2`, `3024 x3`, `3623 x1`).
The edge objective rewarded this dense alternative; it did not preserve the
completed V6 arrangement. The proposal remained one connected component, as
was V6, so it supplied no final connectivity improvement either.

The experiment now has a hard `selected_part_limit` and source comparisons set
it to the completed V6 part count. `maxParts` remains a separate hard ceiling.
This prevents the objective from manufacturing a higher local edge score by
adding small parts. A proposal that cannot preserve coverage at that matched
count is reported as a bounded-search limitation, rather than silently given
an allowance.

The source adapter and V6 use identical GLB bytes, Y-up normalization, the
same `4 x 2 x 9` grid for the smoke box, physical scale (`32.0 x 16.0 x 28.8`
mm), protected source-empty cells, rectangular catalogue, and frozen 4286
slope handling. They do **not** use the same final search vocabulary: V6 may
retain post-solve support-repair and shape-aware placements, whereas the
experiment reconstructs its candidates from the earlier V3 exterior and locks
only its inferred slopes. This is an explicit representability limitation.

| Predicate | V6 | Original proposal | Requirement | Result |
| --- | ---: | ---: | --- | --- |
| Mean silhouette IoU | 0.548659 | 0.501554 | no regression | fail |
| Components | 1 | 1 | improve count or largest fraction | fail |
| Largest-component fraction | 1.000000 | 1.000000 | improve if count unchanged | fail |
| Isolated placements | 0 | 0 | no increase | pass |
| Unsupported placements | 0 | 0 | no increase | pass |
| Physical collisions | 0 | 0 | zero | pass |
| Protected-space violations | 0 | 0 | zero | pass |

The source SHA was
`4fb014994c535fd9f88e01b0aec5984a00989c1efab691d71eaae0a12c1d0489`.
The baseline front/side/top IoUs were `0.722924 / 0.540084 / 0.382968`; the
matched-cap current proposal measured `0.670194 / 0.451499 / 0.382968`.
The bounded canonical surface proxy also regressed from symmetric Chamfer
`2.312662 mm`, normalized Chamfer `0.064256`, and P95 `8.000000 mm` to
`2.616072 mm`, `0.072687`, and `8.002733 mm`. It was rejected on the canonical
measured fidelity and the lack of final graph gain, not on its CP-SAT objective
value.

The 2,000 current objective edges were highly concentrated: 1,820 are in the
lowest height bucket; spatial buckets contain 1,636, 184, 150, and 30 edges.
All 480 candidates participate, but low candidate indexes receive many more
incidences than later indexes. This is deterministic-order bias, not evidence
that omitted pairs are mechanically invalid. Frozen placements are used for
direct support and are not objective-edge endpoints. This particular baseline
has one component, so it has no potential cross-component bridge pairs.

Three deterministic objective policies are now available while retaining the
same 2,000-edge cap: `current` (the existing per-candidate reservation plus
stable fill), `spatially-balanced` (round-robin coarse source/height buckets),
and `baseline-component-aware` (cross-component verified opportunities first,
then spatial balance). Component labels are assigned only for exact baseline
placements; the code deliberately does not invent labels from proximity. Tests
exercise deterministic spatial selection, cross-component preference, frozen
support, and the matched selected-part cap. The policies change objective
rewards only; they never make a placement feasible or mechanically verified.

The matched-cap control run confirms that changing objective edges alone is not
enough to repair the vocabulary mismatch:

| Strategy | Solver status | Final parts | Final mean IoU | Final components | Result |
| --- | --- | ---: | ---: | ---: | --- |
| current | OPTIMAL | 3 | 0.501554 | 1 | fidelity regression |
| spatially-balanced | UNKNOWN | 0 | not measured | 0 | no incumbent in 5.0 deterministic seconds |
| baseline-component-aware | UNKNOWN | 0 | not measured | 0 | no incumbent in 5.0 deterministic seconds |

The latter two are solver-bound failures, not mechanical failures. The
component-aware control had no distinct baseline components to bridge. Matching
the final V6 vocabulary remains the next correctness prerequisite; it is not a
reason to relax fidelity or increase the part allowance. Gate A remains
**PARTIAL** and no production V7 integration is justified.

## Acceptance policy for a future Gate A source run

A candidate must retain the same source, hash, grid, physical LEGO scale, cap, protected-space
policy, collision check, and final support check as its V6 baseline. It must reduce component count
or increase largest-component fraction without increasing isolated or unsupported evaluated
placements, remain under the cap, and retain measured silhouette/Chamfer/P95 quality. Opening fill
must not worsen for sources with a measured opening. Only then may an opt-in V7 integration be
considered.

## Limitations and reproduction

Vertical stud connectivity does not establish stability, clutch force, side connections, torque
resistance, or insertion feasibility. The current work is deliberately a research prototype, not a
production algorithm.

From `backend`:

```powershell
uv run pytest -q tests/test_connectivity_experiment.py
uv run ruff check .
uv run mypy app
```

For a Windows CMD shell:

```cmd
cd backend
uv run ruff check .
uv run mypy app
uv run pytest -q tests/test_connectivity_experiment.py tests/test_buildability.py
```

A CPU-only 16 GB laptop can run the measured smoke case, but a full graph with 11,760 mechanical
edges is not suitable for an unbounded CP-SAT edge objective. The retained 2,000-variable objective
limit is therefore a model-size safeguard, not an enumeration truncation. The experiment remains
offline until a matched nontrivial GLB run improves the complete final graph without fidelity or
mechanical-safety regression.

## Phase 5: final-V6 baseline representability audit

The earlier adapter was **not** a fair V6 comparison. It rebuilt a V3-derived
rectangular vocabulary and froze only slopes inferred before V5 support repair
and V6 shape-aware refinement. A final repaired rectangle or 4286 substitution
could be absent, and coverage was defined from the earlier exterior rather
than the completed assembly. Sharing source-preparation helpers did not make
the search spaces equivalent.

The offline experiment now uses Option A, an exact representable search space.
It keeps source-derived candidates and adds every final V6 rectangular
placement by exact `(part ID, orientation, x, y, z)` geometry. Every final V6
non-rectangular placement, including 4286, is frozen. Coverage is projected
from all final V6 source cells, with frozen placements accounting for their
fixed pixels. Before solving, the actual final assembly is checked for
vocabulary, locked-placement, part-count, protected-space, collision,
direct-support and projection-coverage mismatches. Baseline rectangle indices
are CP-SAT hints only, not fixed decisions.

The strict setting uses the final V6 part count. An explicit optional
additional-part allowance uses `min(maxParts, baselineParts + allowance)` and
defaults to zero; it never bypasses `maxParts`.

### Controlled strict synthetic-box result

With `targetParts=maxParts=12`, the V6 box baseline is exactly feasible:
two selected rectangular incumbent candidates plus one frozen 4286 placement,
with no vocabulary, lock, coverage, support, collision, protected-space or
part-count mismatch. The source SHA is
`4fb014994c535fd9f88e01b0aec5984a00989c1efab691d71eaae0a12c1d0489`; grid
and scale remain `4 x 2 x 9` and `32.0 x 16.0 x 28.8 mm`.

| Fixture / mode | Parts | Components | Largest fraction | Graph edges | Mean IoU | Chamfer mm | P95 mm | Status / reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Box V6 final baseline | 3 | 1 | 1.000000 | 2 | 0.548659 | 2.312662 | 8.000000 | accepted baseline |
| Box strict offline proposal | 3 | 1 | 1.000000 | 2 | 0.548659 | 2.312662 | 8.000000 | rejected: no final connectivity improvement |
| Box offline proposal, +1 allowance | 4 | 1 | 1.000000 | 3 | 0.543402 | 2.320662 | 8.000000 | rejected: fidelity regression |

The proposal has no isolated or unsupported evaluated placements, collisions,
or protected-space violations. It used 480 candidates, 11,760 eligible pairs,
2,000 modeled pairs, 25,823 constraints, 0.75 s model-build time, 0.65 s
solver time and 3.30 s total runtime. The previously invalid 12-versus-three
part comparison is resolved, but an already connected box is not evidence of
an improvement. The bounded +1 control ran for 7.83 s. It did add one verified
edge, but its final component graph cannot improve beyond one component and
its mean IoU regressed, so extra edges were correctly not treated as success.

No structural-bridge GLB, L-profile, or 8x8x6 ring result is claimed here.
The required ring settings and its six-component / 0.538462 baseline remain
uncompleted bounded experiments.

### Gate A decision

**Superseded by the final evaluation below.**

## Final Gate A evaluation

### Decision

**Gate A: PASS.** The existing offline-only, bounded experiment produced a
reproducible accepted final-graph improvement for the nontrivial synthetic
cylinder GLB. No production V7 routing, API option, worker behavior, converter
behavior, vocabulary, objective function, or edge cap was changed. The
smallest appropriate Gate B proposal is one reviewed, opt-in experimental
conversion mode using the existing worker and unchanged final-model acceptance
gate; it remains separate from V6 until that production integration is reviewed.

The existing safeguards were retained: exact V6 representation, frozen
non-rectangular placements, protected-space and collision checks, direct
support constraints, a matched selected-part cap, final
`analyze_buildability` evaluation, and no more than 2,000 modeled objective
edges. CP-SAT uses one worker, seed zero, and a 5.0 deterministic-second
budget; wall times are environment-dependent.

### Canonical V6 baseline inventory

These baselines use each fixture's canonical target and maximum part count.
Physical dimensions use the fixed LEGO grid scale: 8 mm per stud and 3.2 mm
per plate. Edges are final verified graph edges from `analyze_buildability`.

| Fixture | Source SHA-256 | Grid (W x D x H) | Physical mm (W x D x H) | Parts | Components | Largest fraction | Isolated | Edges |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Box | `4fb014994c535fd9f88e01b0aec5984a00989c1efab691d71eaae0a12c1d0489` | 4 x 2 x 9 | 32 x 16 x 28.8 | 3 | 1 | 1.000000 | 0 | 2 |
| Thin wall | `119ea18d997d74b009da1b1e233f846d49bf94466f129a9e5fba35d733ebabcb` | 3 x 2 x 6 | 24 x 16 x 19.2 | 1 | 1 | 1.000000 | 1 | 0 |
| Sphere | `f48448cdcd9e24028c6b927429f1dc9e5caf83c8079c003279a201268dda5396` | 3 x 3 x 6 | 24 x 24 x 19.2 | 5 | 2 | 0.800000 | 1 | 3 |
| Cylinder | `d25f8e3e3c1d0fa604a3e312a60a8331a07b0da1cd537de1e2697d12a31f4ec6` | 3 x 3 x 6 | 24 x 24 x 19.2 | 4 | 2 | 0.500000 | 0 | 2 |
| Pyramid | `474a566b10c751933ed19161b013baeaf3bd24fec9339eb1db09612beabb679b` | 2 x 2 x 6 | 16 x 16 x 19.2 | 4 | 1 | 1.000000 | 0 | 3 |
| L-profile | `732c0dd93d9de28fd7ed1f4aa9b6cc2546f7b559a80da50320128e865f2280c8` | 4 x 2 x 12 | 32 x 16 x 38.4 | 6 | 1 | 1.000000 | 0 | 5 |
| Ring (canonical 16-part mode) | `04e6e0dcd0f70d5bdbf7ceb1605ca0de401ccc30389cb641af5289fce4a81fa6` | 3 x 3 x 6 | 24 x 24 x 19.2 | 3 | 2 | 0.666667 | 1 | 1 |
| Open box | `7a5648f3d8e311f1c3376c497405101ff9148a963565c490b2bfc216384833d1` | 2 x 2 x 6 | 16 x 16 x 19.2 | 2 | 1 | 1.000000 | 0 | 1 |

L-profile was not selected because V6 already returns one component. Ring and
cylinder were selected because their final V6 graphs are disconnected. Box is
only a connected control and is not connectivity evidence.

### Baseline feasibility and cylinder result

The adapter checks exact placements and vocabulary, frozen slopes, projection
coverage, source normalization, grid and scale, direct support, collision
compliance, protected space, and part count before solving. The selected
cylinder baseline passed this equivalence check and is exactly representable at
the strict four-part cap.

The small allowance is one placement and is bounded by
`min(maxParts, baselineParts + 1)`. `current` is the existing deterministic
strategy; `baseline-component-aware` is the existing component-aware strategy.
The graph in every row is the complete final graph from
`analyze_buildability`, never the CP-SAT objective graph.

| Mode / strategy | Solver status | Solver wall time | Total wall time | Eligible / modeled edges | Parts | Components | Largest size / fraction | Isolated | Verified edges | Unsupported | Collisions / protected violations | Front / side / top / mean IoU | Chamfer mm / P95 mm | Opening fill | Decision |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| V6 baseline | n/a | n/a | n/a | n/a | 4 | 2 | 2 / 0.500000 | 0 | 2 | 0 | 0 / 0 | 0.475267 / 0.475267 / 0.475267 / 0.475267 | 3.658397 / 9.343235 | n/a | feasible baseline |
| Strict / `current` | FEASIBLE | 10.354 s | 12.295 s | 7,260 / 2,000 | 4 | 1 | 4 / 1.000000 | 0 | 4 | 0 | 0 / 0 | 0.475267 / 0.475267 / 0.475267 / 0.475267 | 2.595771 / 8.519070 | n/a | **accepted** |
| Strict / `baseline-component-aware` | FEASIBLE | 7.577 s | 9.440 s | 7,260 / 2,000 | 4 | 1 | 4 / 1.000000 | 0 | 3 | 0 | 0 / 0 | 0.475267 / 0.475267 / 0.475267 / 0.475267 | not separately sampled | n/a | accepted by final graph and silhouette criteria |
| +1 / `current` | FEASIBLE | 11.384 s | 13.456 s | 7,260 / 2,000 | 5 | 1 | 5 / 1.000000 | 0 | 5 | 0 | 0 / 0 | 0.475267 / 0.475267 / 0.475267 / 0.475267 | not separately sampled | n/a | accepted mechanically; no additional fidelity gain |

The strict `current` result is the acceptance witness: it reduces components
from two to one, increases largest-component coverage from 0.5 to 1.0, does
not increase isolated or unsupported placements, and does not regress
silhouette. Its independently measured surface proxy improves in Chamfer and
P95. The component-aware strict run independently reaches one component.

### Required fixed-scale ring attempt

The requested ring baseline was reproduced at `targetParts=maxParts=100`.

| Fixture / mode | Source SHA-256 | Grid | Physical mm | Parts | Components | Largest size / fraction | Isolated | Verified edges | Unsupported | Front / side / top / mean IoU | Chamfer mm / P95 mm | Opening fill |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| V6 baseline | `04e6e0dcd0f70d5bdbf7ceb1605ca0de401ccc30389cb641af5289fce4a81fa6` | 8 x 8 x 6 | 64 x 64 x 19.2 | 26 | 6 | 14 / 0.538462 | 2 | 21 | 0 | 0.749708 / 0.727513 / 0.605411 / 0.694211 | 2.354005 / 6.767722 | 923 / 1,734 |

Two strict `current` calls were attempted with the unchanged 2,000-edge cap
and existing solver limit. Neither returned a solver status, incumbent, or
final model to the invoking process. This is a bounded-computation failure
before a result could be recorded, not a rejected candidate and not evidence
of an improvement. No allowance or additional strategy was run after the
repeated failure; that would repeat the same resource-bound attempt without a
complete-model comparison. The ring footprint, cap, fidelity thresholds,
vocabulary, and objective edge limit were not changed.

### Controls, validation, and recommendation

The 12-part box remains rejected as connectivity evidence because its V6
baseline has one component. The successful handcrafted bridge remains a
mechanism fixture only and is not GLB evidence. `stud-connectivity-v1` does
not prove whole-model stability, clutch force, torque resistance, side
connections, or general insertion feasibility.

Focused experiment tests, Ruff, and mypy were run after this final record was
prepared. Normal tests remain offline and do not call fal.ai, Supabase, or
Azure. For full Windows CMD validation:

```cmd
cd backend
uv run ruff check .
uv run mypy app
uv run pytest -q
```

At the end of Gate A, this branch was a diagnostics-only evidence PR. It had a
reproducible, accepted nontrivial GLB-derived improvement, but intentionally
did not yet add V7 routing. The Gate B record below adds the smallest reviewed,
opt-in experimental conversion mode using the existing worker and the same
final-model acceptance evidence; it does not redesign the objective or force
the ring benchmark.

## Gate B implementation record

`surface-grid-v7-connectivity-aware` is now an explicit, experimental
conversion identifier. `surface-grid-v4` remains the default. V7 requires an
explicit `maxParts`, runs V6 first, and uses the existing exact-V6 vocabulary,
frozen non-rectangular placements, indexed verified connector pairs, one-worker
CP-SAT configuration (seed zero, five deterministic seconds), and the existing
2,000 modeled-edge limit. Its selected-part limit is exactly the completed V6
part count: it never adds parts to buy connector edges.

The final candidate is accepted only after complete placement evaluation: no
unsupported evaluated parts, collisions, or protected-empty-space violations;
strictly better final graph connectivity; no silhouette IoU regression; and no
regression in symmetric or normalized Chamfer or P95 surface distance. Otherwise
V7 emits the unchanged V6 placements and marks the fallback reason in artifact
metadata. Connector edges are only `stud-connectivity-v1` verified mechanical
stud/receiver matches; they do not assert whole-model stability, clutch force,
or insertion feasibility.

The production entry-point reproduction used the synthetic-cylinder source
SHA-256 `d25f8e3e3c1d0fa604a3e312a60a8331a07b0da1cd537de1e2697d12a31f4ec6`,
Y-up, `targetParts=maxParts=16`, and grid `3 x 3 x 6` (24 x 24 x 19.2 mm).
V6 had four parts, two components, two edges, no isolated/unsupported parts,
and mean IoU 0.475267. V7 also had four parts, but one component, three final
verified edges, no isolated/unsupported parts, and the same mean IoU. The
measured V6/V7 Chamfer was 3.658397/2.595771 mm and P95 was
9.343235/8.519070 mm. The accepted production run used 350 candidates,
7,260 verified candidate pairs, and 2,000 modeled objective edges. Wall time
is environment-dependent (about 13 seconds in this Windows run).

The historical capped-100 cylinder IoU (0.773605) is not comparable to this
witness: it uses different target/cap and selected grid settings. The Gate B
witness uses the strict 16-part `3 x 3 x 6` configuration above.

V7 is carried through API request validation, the persisted algorithm field,
the existing conversion worker, benchmark settings, and serialized model
metadata. `connectivityAware` metadata records the vocabulary size, complete
verified-pair count, modeled objective-edge count, solver status/runtime,
acceptance, and exact fallback reason. The frontend remains unchanged, so the
experimental option is not promoted as a default UI choice.

Before the final benchmark audit below, the full matched eight-fixture
`targetParts=maxParts=100` V6/V7 comparison had not yet been run. No ring
improvement was claimed at that time. The final audit supersedes this interim
Gate B status.

### Benchmark CLI registration follow-up

The benchmark CLI originally had a separate V3–V6 `--algorithm` allowlist and
a separate hard-cap allowlist. V7 was therefore rejected by argument parsing
before it could reach `convert_glb`. Both lists now use the canonical core V7
identifier. A real CLI run of the synthetic cylinder with
`targetParts=maxParts=16` recorded `algorithmVersion` as
`surface-grid-v7-connectivity-aware`, `connectivity_accepted=true`, four parts,
one component, largest-component fraction 1.0, and zero isolated or unsupported
placements. The matched V6 CLI record had four parts, two components, and a
largest-component fraction of 0.5. Mean IoU was 0.475267 for both; CLI-measured
Chamfer/P95 improved from 3.658397/9.343235 mm to 2.667059/8.525568 mm.

## Final capped-100 benchmark audit

The matched `targetParts=100`, `maxParts=100` synthetic V6 and V7 benchmark
records were inspected case by case. Every V7 call used the same fixture bytes,
axis, requested cap, grid chosen by V6, metric versions, five deterministic
second CP-SAT limit, one worker, seed zero, and 2,000 modeled objective-edge
limit. Values below are `V6/V7`; `n/a` means the fixture has no enclosed
top-view opening.

| Case | Parts | Components | Largest fraction | Isolated | Unsupported | Front IoU | Side IoU | Top IoU | Mean IoU | Chamfer mm | P95 mm | Opening fill | V6/V7 runtime s | V7 decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Box | 63/63 | 6/6 | 0.476190/0.476190 | 2/2 | 0/0 | 0.831525/0.831525 | 0.700113/0.700113 | 0.670194/0.670194 | 0.733944/0.733944 | 2.605941/2.605941 | 8.000000/8.000000 | n/a | 22.728/358.257 | fallback: solver without incumbent |
| Thin wall | 34/34 | 6/6 | 0.411765/0.411765 | 2/2 | 0/0 | 0.753968/0.753968 | 0.730717/0.730717 | 0.775510/0.775510 | 0.753398/0.753398 | 2.046907/2.046907 | 6.400000/6.400000 | n/a | 15.309/289.642 | fallback: solver without incumbent |
| Sphere | 36/36 | 1/1 | 1.000000/1.000000 | 0/0 | 0/0 | 0.728280/0.728280 | 0.719282/0.719282 | 0.602441/0.602441 | 0.683334/0.683334 | 3.261158/3.261158 | 9.780095/9.780095 | n/a | 16.363/110.753 | fallback: no final connectivity improvement |
| Cylinder | 46/46 | 1/1 | 1.000000/1.000000 | 0/0 | 0/0 | 0.749385/0.749385 | 0.857143/0.857143 | 0.714286/0.714286 | 0.773605/0.773605 | 3.443516/3.443516 | 10.175712/10.175712 | n/a | 20.208/251.857 | fallback: solver without incumbent |
| Pyramid | 18/18 | 2/1 | 0.944444/1.000000 | 1/0 | 0/0 | 0.788978/0.795169 | 0.504799/0.504799 | 0.394586/0.394586 | 0.562788/0.564851 | 2.465798/2.354048 | 8.000000/8.000000 | n/a | 9.432/30.547 | **accepted** |
| L-profile | 47/47 | 2/2 | 0.893617/0.893617 | 0/0 | 0/0 | 0.696280/0.696280 | 0.718065/0.718065 | 0.658226/0.658226 | 0.690857/0.690857 | 2.330835/2.330835 | 7.650305/7.650305 | n/a | 16.614/169.814 | fallback: solver without incumbent |
| Ring | 26/26 | 6/6 | 0.538462/0.538462 | 2/2 | 0/0 | 0.749708/0.749708 | 0.727513/0.727513 | 0.605411/0.605411 | 0.694211/0.694211 | 2.354005/2.354005 | 6.767722/6.767722 | 0.532295/0.532295 | 12.408/53.336 | fallback: fidelity regression |
| Open box | 57/57 | 3/3 | 0.964912/0.964912 | 2/2 | 0/0 | 0.810658/0.810658 | 0.744331/0.744331 | 0.699798/0.699798 | 0.751596/0.751596 | 3.523285/3.523285 | 12.800000/12.800000 | n/a | 19.504/531.721 | fallback: solver without incumbent |

The benchmark record schema does not persist a final connection-edge count or a
protected-space-violation count. It does persist the final graph component,
largest-fraction, isolated, unsupported, and physical-collision values. Final
collision count is zero for every V7 output. The accepted V7 candidate is
rejected before emission if it has a protected-space violation; every fallback
emits V6's already validated placements. Thus the records do not establish a
new protected-space metric, but they do not indicate a safety failure.

### V7 work and fallback reasons

| Case | Candidate placements | Eligible / modeled pairs | Solver status / seconds | Accepted / reason |
| --- | ---: | ---: | --- | --- |
| Box | 7,308 | 742,224 / 2,000 | UNKNOWN / 14.435 | no / solver without incumbent |
| Thin wall | 6,830 | 691,500 / 2,000 | UNKNOWN / 14.628 | no / solver without incumbent |
| Sphere | 3,212 | 286,496 / 2,000 | FEASIBLE / 11.522 | no / no final connectivity improvement |
| Cylinder | 5,390 | 587,396 / 2,000 | UNKNOWN / 11.703 | no / solver without incumbent |
| Pyramid | 1,242 | 51,276 / 2,000 | FEASIBLE / 11.638 | yes |
| L-profile | 5,152 | 427,608 / 2,000 | UNKNOWN / 9.788 | no / solver without incumbent |
| Ring | 2,960 | 155,040 / 2,000 | FEASIBLE / 8.803 | no / fidelity regression |
| Open box | 8,652 | 999,888 / 2,000 | UNKNOWN / 20.059 | no / solver without incumbent |

`UNKNOWN` is an interrupted bounded solve with no incumbent; it is not proof
of infeasibility. In every such case the final V7 artifact is the validated V6
fallback. The ring was not improved: it reached a feasible candidate but the
fidelity gate rejected it.

### Pyramid acceptance and repeatability

Pyramid is a valid accepted refinement, not an objective-only result. It keeps
18 parts, reduces final components from two to one, increases the largest
component fraction from 0.944444 to 1.0, removes the one isolated placement,
keeps zero unsupported placements and collisions, improves mean IoU and
Chamfer, and leaves P95 unchanged. The complete candidate was evaluated after
selection by the same final support, collision, protected-space, fidelity, and
`analyze_buildability` gates as every other V7 candidate.

A second capped-100 pyramid run produced the same accepted final metrics
(18 parts, one component, mean IoU 0.564851, Chamfer 2.354048 mm, P95 8.0 mm)
with the same FEASIBLE solver status. The 16-part cylinder was also repeated:
both CLI runs recorded four parts, one component, mean IoU 0.475267, Chamfer
2.667059 mm, and P95 8.525568 mm. The earlier 2.595771 mm cylinder value came
from Gate A's `current` objective-edge strategy. Production V7 uses the
documented `baseline-component-aware` strategy; it produces a different valid
FEASIBLE incumbent, not a solver-settings or metric-version change. The repeat
establishes reproducibility for the production strategy in this environment,
but FEASIBLE status means deterministic final geometry should not be claimed
across OR-Tools/platform versions without further evidence.

### Practicality and release assessment

The 2,000-edge CP-SAT model is bounded, but indexed complete-pair enumeration
is not cheap at capped-100 scale: seven of eight fixtures fell back after
53–532 seconds total V7 runtime, compared with 12–23 seconds for V6. The
successful pyramid cost 30.547 seconds versus 9.432 seconds for V6. No memory
or explicit resource-limit error was recorded, but these multi-minute fallback
costs are not practical for a CPU-only 16 GB laptop production worker and
violate the requirement not to significantly slow models that do not benefit.

**Final assessment: C — not justified for production exposure yet.** The V7
acceptance gate correctly protects V6 output and the pyramid/cylinder evidence
shows the mechanism can help, but the measured capped-100 fallback overhead is
too high. Keep this as research evidence; before a production PR exposes V7,
the team needs a reviewed bounded-vocabulary/performance design and a new
benchmark record. This audit does not change solver budgets or relax any
mechanical, collision, protected-space, hard-cap, or fidelity safeguard.

## Milestone 5 performance engineering follow-up

### Original bottleneck and measured evidence

The earlier capped-100 audit is retained above without alteration: its V7
fallbacks took 53.336–531.721 seconds while V6 took 12.408–22.728 seconds.
The two-thousand-edge CP-SAT objective limit did not bound elapsed conversion
time. Before solving, V7 built a global vocabulary of 1,242–8,652 placements,
enumerated the complete verified graph (51,276–999,888 pairs), and constructed
support constraints from that full graph. In particular, direct-support model
construction scanned the complete pair list once for each candidate. Thus the
complete graph and model construction, rather than the reduced objective alone,
were responsible for the multi-minute cases. The old solver wall times of
8.803–20.059 seconds also demonstrate that deterministic solver time is not a
wall-clock bound.

### Implemented bounded-work policy

V7 now applies two decisions after producing the unchanged V6 baseline.

1. If the V6 final graph has one component, it skips V7 with
   `baseline_already_connected`. This is a correctness proof: V7 accepts only
   a strict reduction in final component count, so no possible candidate can be
   accepted under the existing policy.
2. For a disconnected baseline, V7 generates the exact existing vocabulary but
   skips connector indexing and CP-SAT if it exceeds the named
   `MAX_CONNECTIVITY_CANDIDATES` limit (2,000), reporting
   `candidate_limit_exceeded`. This is a resource policy, not a proof that an
   improvement is impossible. It preserves V6 exactly and deliberately leaves
   large-vocabulary improvements for a separately reviewed local-neighborhood
   design.

The artifact diagnostics now distinguish `attempted`, `eligibilityReason`, and
`fallbackReason`. A connected or limit-exceeded baseline records no solver
attempt, no verified candidate pairs, and no modeled objective edges. The
candidate ceiling is an algorithmic guard before the known expensive full graph
and model work; it does not promise a hard conversion wall-clock limit because
V6 and vocabulary generation remain synchronous, non-interruptible work.

### Current capped-100 V7 run

These are one Windows local run after the policy change. Fidelity and final
graph metrics equal V6 for every fallback; values below are final emitted V7
models. The historical V6 times above are retained as the previous audit, not
represented as same-process timing comparisons.

| Case | V7 seconds | Outcome | Components | Largest fraction | Isolated | Parts | Mean IoU | Chamfer / P95 mm | Candidate count | Solver status / seconds |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| Box | 29.243 | candidate-limit fallback | 6 | 0.476190 | 2 | 63 | 0.733944 | 2.605941 / 8.000000 | 7,308 | not run |
| Thin wall | 19.193 | candidate-limit fallback | 6 | 0.411765 | 2 | 34 | 0.753398 | 2.046907 / 6.400000 | 6,830 | not run |
| Sphere | 20.129 | already-connected skip | 1 | 1.000000 | 0 | 36 | 0.683334 | 3.261158 / 9.780095 | 0 | not run |
| Cylinder | 23.922 | already-connected skip | 1 | 1.000000 | 0 | 46 | 0.773605 | 3.443516 / 10.175712 | 0 | not run |
| Pyramid | 35.189 | **accepted** | 1 | 1.000000 | 0 | 18 | 0.564851 | 2.354048 / 8.000000 | 1,242 | FEASIBLE / 13.334 |
| L-profile | 23.342 | candidate-limit fallback | 2 | 0.893617 | 0 | 47 | 0.690857 | 2.330835 / 7.650305 | 5,152 | not run |
| Ring | 14.458 | candidate-limit fallback | 6 | 0.538462 | 2 | 26 | 0.694211 | 2.354005 / 6.767722 | 2,960 | not run |
| Open box | 22.781 | candidate-limit fallback | 3 | 0.964912 | 2 | 57 | 0.751596 | 3.523285 / 12.800000 | 8,652 | not run |

The accepted capped-100 pyramid remains the proven improvement: V6 had 18
parts and two components; V7 has 18 parts and one component, no unsupported
placements or collisions, higher mean IoU, lower Chamfer, and unchanged P95.
The strict 16-part cylinder regression also still passes: it emits four parts,
one component, no unsupported placements, and V7 diagnostics with an attempted
optimizer. The limit does not affect either witness (350 candidates for the
strict cylinder and 1,242 for the capped-100 pyramid).

### Decision

**A — performance gate passed for the exposed experimental V7 mode.** The
strictly sound connected-baseline skip and bounded candidate policy retain the
two useful improvements while eliminating the previous multi-minute fallback
work on the standard capped-100 suite. This is not a claim that V7 exhaustively
optimizes every disconnected large model. A future attempt to improve those
models needs a separate reviewed, local-neighborhood formulation with its own
mechanical and fidelity regression evidence.
