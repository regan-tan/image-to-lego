# Milestone 9B: Verified LEGO Geometry Family Evaluation

## Decision

**NO-GO at the geometry-family selection gate.** No inactive geometry family in
the checked-in catalogue can satisfy M9B's required mechanical-verification
contract. Per the milestone hard stop, no M9B candidate expansion, synthetic
fixture, private-GLB run, or artifact output was created. This is a selection
NO-GO, not a conclusion that richer LEGO geometry cannot improve fidelity.

M9A remains the applicable baseline evidence: the Duck, Mansion, and Realistic
man V6 baselines are feasible in its corrected fixed-coverage model and have
frozen mean silhouette-v1 IoUs of .591700, .600598, and .421959 respectively.
Its optimized records are .595249, .600598, and .421959. Those figures do not
test a newly admitted part family.

## Selection audit

The active fitter catalogue contains seven brick families, seven plate families,
and the verified `4286` 33-degree 3 x 1 slope. `4286` is already selectable, so
it cannot be M9B's required *new* family. The only inactive non-rectangular
catalogue entries are the following candidates.

| Candidate | Opportunity | Catalogue/source evidence | Placement and projection evidence | Selection result |
| --- | --- | --- | --- | --- |
| `41769` / `41770` wedge plates | Diagonal top contours and roof profiles | Canonical identities, LDraw source IDs (`41769a`/`41770a`), manufactured-colour snapshot, and a discrete XY footprint are checked in. | 0/90/180/270-degree footprint rotations and sampled body proxies exist. The module explicitly limits itself to fit/silhouette geometry and makes no underside, clutch, or mechanical-support claim. | Rejected: no verified connector/receiver or support/contact contract; buildability marks both unevaluated. |
| `15068` curved slope | Organic curved silhouettes and narrow rounded features | Canonical identity, LDraw source ID `15068`, and manufactured-colour snapshot are checked in. | A quarter-cylinder sampled proxy exists, but its implementation explicitly calls it conservative and not an authoritative solid model of the hollow moulding. | Rejected: no verified connector/receiver or support/contact contract; buildability marks it unevaluated. |
| Additional slope family | Sloped surfaces and architectural roofs | No other inactive, supported slope family is present in the checked-in catalogue. | Not applicable. | Rejected: there is no repository-backed candidate to admit. |

The audit intentionally did not invent a part ID, mould dimensions, connector
layout, rotation behavior, or export mapping. The catalogue's `fitterEnabled`
flags remain `false` for `15068`, `41769`, and `41770`; changing one merely for
the experiment would contradict the evidence recorded above.

## Why no candidate is mechanically verifiable today

The existing collision representation is useful evidence, but is insufficient
for M9B admission:

- `physical_geometry.py` contains non-rectangular sampled collision proxies for
  wedges and a quarter-cylinder proxy for `15068`; the latter is explicitly not
  an authoritative physical solid.
- `wedge_41769_41770.py` explicitly limits its footprint implementation to fit
  and silhouette geometry and disclaims underside, clutch, and support claims.
- `stud-connectivity-v1` includes only parts with curated verified mechanical
  metadata. The focused connector regression asserts that `41769`, `41770`,
  and `15068` have status `UNEVALUATED` and no resolvable mechanical metadata.
  Consequently their support, contact, connectivity, and insertion eligibility
  cannot be checked to the same standard as selectable brick and plate parts.
- The local wedge refinement is an opt-in historical experiment, not a verified
  general candidate family. Its own tests preserve that a wedge cannot satisfy
  the rectangular support constraint.

The project geometry uses the established lattice units of 8 mm per stud and
3.2 mm per plate. That preserves nominal placement scale, but it cannot fill in
the missing interface and mould-contract evidence required for a physically
accepted result.

## M9A controls retained, but not executed as M9B

No M9B experiment ran. If a family later passes this gate, its A/B harness must
reuse M9A's corrected locked-slope source-profile coverage, required source
projection witnesses, protected-space rules, collision exclusions, evaluated
support constraints, 60-part cap, fixed grids, one-times source evidence,
`targetParts=24`, and deterministic bounded solver settings. Control A must
remain the existing fitter vocabulary and Experiment B may differ only by the
newly verified family.

M9A already demonstrated all three V6 baseline feasibility checks under that
corrected model. M9B did not rerun those private-source checks because no
eligible Experiment B exists; doing so would add private-artifact processing
without addressing the selection failure.

## Synthetic and real-world results

Not run. A synthetic geometric-benefit fixture would require actual verified
body geometry plus valid support/contact behavior for every introduced
orientation. Building one from the present wedge footprint or curved-slope
proxy would falsely imply mechanical correctness. The three SHA-256-pinned
private GLBs were therefore not read, and no output was written to
`artifacts/m9b-geometry-family-evaluation/`.

There are consequently no M9B candidate counts, solver status, placement IDs,
geometry hashes, per-view IoUs, Surface Metric V2 values, collision counts, or
connectivity comparisons to report. This absence is intentional and must not
be treated as zero or as an A/B tie.

## Attribution, limitations, and next direction

There can be no fidelity attribution without a mechanically valid Experiment B.
The existing wedge/curved proxies demonstrate possible *geometric* opportunity,
not safe placement or causal fidelity benefit. The fixed-frame/frozen-IoU
disagreement recorded by M9A remains relevant to any future experiment: a
surrogate improvement must not be reported as frozen silhouette-v1 improvement.

The recommended next engineering direction is a narrowly scoped mechanics
evidence task for one candidate family before any optimization work: record an
authoritative body and connector/receiver contract, explicitly enumerate valid
orientations, validate collisions against existing brick/plate/slope geometry,
and add independent support/contact/export tests. Only if that task produces a
curated verified contract should the offline-only M9B A/B harness and synthetic
fixture be implemented. Otherwise, retain production V4--V7 unchanged and
consider the separately controlled larger-physical-lattice direction.

## Production isolation and validation

No production converter, `convert_glb()` path, API, worker, frontend, catalogue
entry, generated catalogue, or test behavior was modified. No external service
or private artifact was accessed. `artifacts/` is already gitignored.

Focused offline catalogue, physical-geometry, mechanical-connector,
evaluation-alignment, and wedge-refinement tests passed; Ruff and targeted mypy
also passed. `git diff --check` passed. The existing formatter check reports
pre-existing formatting changes in four inspected Python files; they were not
reformatted because M9B made no code change to them.
