# Milestone 10B: Controlled Physical Scale Experiment

Status: completed preflight and bounded Duck control; **NO-GO for expanded evaluation under the
predeclared candidate limit.** This is an offline diagnostic only. It does not change V4--V7,
`convert_glb()`, APIs, workers, or private artifact handling.

## Method

The experiment uses the existing `convert_fixed_grid()` seam with the verified catalogue and
unchanged V5/V6 collision, protected-space, and direct-support checks. Each horizontal lattice unit
is 8 mm and each vertical lattice unit is 3.2 mm. The larger configuration therefore creates actual
additional LEGO positions; it is not extra sampling inside the same output envelope.

`backend/scripts/run_m10b_physical_scale_experiment.py` performs preflight before invoking CP-SAT.
Its candidate ceiling is 4,000, solver target is 24, baseline cap is 60, larger-grid cap is 120,
solver seed is zero, and one solver worker is retained. A point is also marked infeasible if it
exceeds 180 seconds. The 120-part cap is intentional and is reported as a scale-and-budget
confounder; no result claims that their effects are isolated.

The runner writes aggregate JSON only under ignored `artifacts/m10b-physical-scale/`. It verifies
the three original private GLBs against their pinned SHA-256 values and does not record paths,
source bytes, placements, or generated meshes.

## Gate A preflight

The following are measured preflight counts, not density extrapolations. Candidate counts are after
the ordinary fixed-grid support-reachability pruning. All sources are non-watertight, so zero
protected cells means unknown interior/exterior rather than permission to fill apparent voids.

| Source | SHA-256 | 1x grid -> 1.5x grid | Larger nominal envelope | Achieved factors (W/D/H) | Candidate count | Decision |
| --- | --- | --- | --- | --- | ---: | --- |
| Duck | `77093bb…11379e` | `5x7x12` -> `8x10x18` | `64x80x57.6 mm` | `1.60 / 1.43 / 1.50` | 6,019 | Rejected: candidate limit |
| Mansion | `d1a9618…919510` | `7x4x12` -> `10x6x18` | `80x48x57.6 mm` | `1.43 / 1.50 / 1.50` | 11,066 | Rejected: candidate limit |
| Realistic man | `0891024…6088bce` | `3x5x18` -> `4x8x27` | `32x64x86.4 mm` | `1.33 / 1.60 / 1.50` | 3,409 | Accepted by preflight, but Gate C not reached |

The larger lattices have 1,440, 1,080, and 864 cells respectively, versus 420, 336, and 270 at
1x. Thus every planned larger point is physically larger and has more genuine lattice capacity.

Duck measured 538 target cells, 263 required projection pixels, 4 locked slopes, and candidate
family counts of 2,536 brick / 3,483 plate. Mansion measured 758 target cells, 293 pixels, no
locked slopes, and 5,120 brick / 5,946 plate candidates. Realistic man measured 406 target cells,
245 pixels, one locked slope, and 1,471 brick / 1,938 plate candidates. No oversized preflight
point was sent to CP-SAT.

## Gate B Duck control

The Duck 1x control completed in 19.68 seconds at `5x7x12`, cap 60. It emitted 29 parts and its
actual final size was `40x56x38.4 mm`; these equal the intended 1x envelope. It had 1,449 reachable
candidates, stage-one `OPTIMAL`, stage-two `FEASIBLE`, zero collision pairs, zero unsupported
evaluated placements, zero protected-space violations, one connected component, a 1.0 largest-
component ratio, and zero isolated placements.

Its frozen silhouette-v1 result was front 0.638589, side 0.609331, top 0.527180, mean 0.591700.
Surface Metric V2 was available: 2.794217 mm symmetric mean (0.041347 normalized by its aligned
source diagonal). The frozen silhouette values remain supporting diagnostics only: their dynamic
padded bounds make a cross-scale comparison confounded.

Duck's `8x10x18` point was not run because its measured 6,019 candidates exceed the declared 4,000
ceiling. This is a legitimate resource-gate failure, not a solver failure. Consequently there is no
valid Duck larger-scale fidelity delta, no repeat, and no Gate C corpus run. Mansion and Realistic
man were skipped after Gate B rather than using the individually admitted Realistic-man preflight to
bypass the declared progression rule.

## Cross-scale geometry evaluator

`scale_normalized_geometry.py` adds `scale-normalized-geometry-v1` without changing
silhouette-v1 or Surface V2. It translates source geometry to its minimum and uniformly normalizes
it by its largest extent. LEGO boxes retain the real stud/plate dimensions and are normalized by
the largest nominal output-envelope extent. Front, side, and top masks use one shared 3D frame;
individual silhouettes are never separately fitted. It records per-view IoU plus original-source
false-positive and false-negative pixel counts. Surface V2 remains separately reported with its
existing available/unavailable/timeout semantics.

No normalized cross-scale delta is reported because Duck's larger point was correctly rejected before
conversion. Focused synthetic tests prove that uniformly scaling a matching shape does not change
this metric. The predeclared engineering signal for a future completed pilot remains a +0.01
normalized mean-IoU change, not a statistical claim.

## Conclusion and next step

**NO-GO for expanded 1.5x evaluation with the current fixed-grid V6 candidate budget.** Duck and
Mansion fail preflight before optimization, so the study cannot establish a safe, bounded fidelity
gain. A successful Duck control alone is not production evidence, and no safety requirement was
relaxed.

The next engineering step is a reviewed, offline-only candidate-space reduction study that preserves
the verified catalogue, collision/support/protected-space semantics, and the 4,000-candidate ceiling.
It should demonstrate a deterministic Duck 1.5x point before another corpus run; it must not simply
raise the limit or add a production scale setting.

## Separately labelled Realistic-man 1.5x exploratory pilot

This is one prospective, offline-only experiment with schema
`m10b-realistic-man-scale-pilot-v1`. It is expressly separate from the original M10B
Duck-first protocol and does **not** alter its preflight decision: Duck (6,019 candidates) and
Mansion (11,066) remain NO-GO under the 4,000-candidate ceiling. The explicit
`--realistic-man-pilot` mode is the only permitted per-case exception; ordinary M10B selections
still require Duck.

The private SHA-pinned Realistic-man GLB (`0891024...6088bce`) was available for this run. Both
points used the same verified catalogue, Y-up alignment, original GLB, fixed-grid V6
shape-aware conversion, collision/protected-space/support checks, seed zero, and one solver
worker. The existing solver limits were retained: 20 deterministic units for stage one, 7.25 for
stage two and each bounded local repair, 180 seconds per point, a 30-second Surface V2 observation
limit, and the 4,000-candidate preflight limit. No pruning or physical constraint was disabled.

| Measure | 1x control | 1.5x pilot | Change / interpretation |
| --- | ---: | ---: | --- |
| Grid (W x D x H) | `3x5x18` | `4x8x27` | Actual factors `1.33x / 1.60x / 1.50x` |
| Nominal / final dimensions | `24x40x57.6` / `24x40x57.6 mm` | `32x64x86.4` / `32x64x86.4 mm` | Genuine larger LEGO lattice |
| Candidate count (before / protected / reachable) | 1,063 / 1,063 / 1,043 | 3,632 / 3,518 / 3,409 | Larger point admitted below 4,000 |
| Part budget / actual parts | 60 / 22 | 120 / 52 | **Joint scale-and-budget intervention**; effects are not isolated |
| Solver status | `OPTIMAL` / `FEASIBLE` | `OPTIMAL` / `FEASIBLE` | Both completed |
| Runtime | 14.153828 s | 41.069409 s | Original recorded values; both below 180 s |
| Scale-normalized silhouette mean IoU | 0.452924 | 0.439103 | -0.013821; no normalized fidelity improvement |
| Frozen silhouette-v1 mean IoU | 0.421959 | 0.524551 | +0.102592 diagnostic only; dynamic padded bounds confound cross-scale use |
| Surface Metric V2 | unavailable: 30 s observation timeout | unavailable: 30 s observation timeout | No millimetre-distance comparison claimed |
| Collision / unsupported / protected violations | 0 / 0 / 0 | 0 / 0 / 0 | Mechanical safety checks passed |
| Components / largest component / isolated placements | 2 / 18 (0.8182) / 0 | 3 / 43 (0.8269) / 1 | Connectivity was not preserved overall: components and isolation worsened, despite a slightly higher largest-component ratio |

The 1.5x solver therefore **produced a feasible time-limited result** within the configured
computational budgets and maintained the evaluated collision, support, and protected-space
requirements. It did **not** demonstrate higher scale-normalized geometric fidelity, and it did not
preserve connectivity. The frozen silhouette-v1 rise is retained only as a separately labelled
diagnostic; Surface V2 is also
retained separately with its honest timeout/unavailable status. Neither supports a claim of physical
geometric improvement.

This is the first valid completed real-world 1x-versus-larger reconstruction comparison at fixed
real-brick dimensions in this project, but it is a single, confounded exploratory result rather
than production-scale evidence. The aggregate JSON is kept only under the ignored
`artifacts/m10b-realistic-man-pilot/` directory; it contains no paths, GLBs, placements, or meshes.

### Final audit: source, metric, solver, and safety evidence

The original pilot aggregate records the full Realistic-man source SHA-256 as
`0891024ef635f797e83f6c99569714e12fad9c23722e69140c3b1720e6088bce` for **both** points. Its
preflight and point records confirm these exact budgets and physical envelopes:

| Configuration | Grid / nominal and final dimensions | Part cap / actual parts | Candidates before / protected / reachable |
| --- | --- | ---: | ---: |
| 1x | `3x5x18` / `24x40x57.6 mm` | 60 / 22 | 1,063 / 1,063 / 1,043 |
| 1.5x | `4x8x27` / `32x64x86.4 mm` | 120 / 52 | 3,632 / 3,518 / 3,409 |

The 1.5x point is a **joint scale-and-budget intervention**. It cannot attribute its results to
physical scale independently of the 60-to-120 part-cap increase.

Both normalized silhouettes have status `available` and metric version
`scale-normalized-geometry-v1`. They use the same SHA-pinned GLB, Y-up source alignment, one shared
3D frame for all views, and the same 256-pixel front (XZ), side (YZ), and top (XY) projection
semantics. The evaluator translates each source to its minimum and uniformly divides by its largest
extent; LEGO geometry retains real brick dimensions and is uniformly divided by the largest nominal
output-envelope extent. It never independently fits individual views. The exact means are
`0.452924` and `0.439103`, a `-0.013821` change. The synthetic regression test confirms invariance
when an otherwise identical source is uniformly scaled.

The original pilot aggregate predated detailed solver audit fields. A deterministic rerun with the
same source, grid, caps, seed zero, one worker, and constraints is stored only in ignored
`artifacts/m10b-realistic-man-pilot-audit/summary.json`. It reproduced the reported part counts,
normalized silhouettes, and mechanical outcomes (wall-clock runtime varied, as expected). It records
the following CP-SAT results. Limits are deterministic work units, not wall-clock seconds.

| Configuration | Stage | Status | Objective / best bound | Absolute gap | Deterministic limit | Interpretation |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 1x | Coverage maximize | `OPTIMAL` | 122 / 122 | 0 | 20.0 | Proven optimal for stage one |
| 1x | Tie-break minimize | `FEASIBLE` | 22 / 4 | 18 | 7.25 | Incumbent only; not proven optimal |
| 1.5x | Coverage maximize | `OPTIMAL` | 236 / 236 | 0 | 20.0 | Proven optimal for stage one |
| 1.5x | Tie-break minimize | `FEASIBLE` | 51 / 0 | 51 | 7.25 | Incumbent only; not proven optimal |

The 1.5x final model has one locked slope in addition to the 51 rectangular stage-two selections,
which is why its 52 final parts do not equal that stage's objective. A stage-one `OPTIMAL` result
does not make the complete shape-aware conversion, its local repair/refinement steps, or its
geometric reconstruction globally optimal.

All recorded evaluated mechanical checks remain zero at both points: physical collision pairs,
unsupported evaluated placements, and protected-space violations. Connectivity worsened from two
components / 18-part largest component / no isolated placements to three components / 43-part
largest component / **one isolated placement**. Surface Metric V2 is `unavailable` at both points
because the independent 30-second observation limit was exceeded; no surface-distance conclusion is
drawn.

## Final conclusion and recommended direction

**Final decision: NO-GO for further broad physical-scale expansion under the current experimental
architecture.** The original Duck/Mansion preflight decision remains unchanged: their 1.5x points
were rejected at 6,019 and 11,066 candidates respectively, above the declared 4,000-candidate
ceiling. The separately labelled Realistic-man pilot is not a protocol replacement or a Gate C
corpus result. It safely produced a larger model, but its normalized fidelity fell and its
connectivity worsened.

This is not evidence that physically larger LEGO reconstructions can never improve fidelity, nor
does any solver record establish a global geometric optimum. The next engineering direction is a
reviewed offline candidate-space reduction study that preserves the verified catalogue and all
collision, support, and protected-space semantics while remaining under the 4,000-candidate ceiling.
It should first produce a deterministic Duck 1.5x point before any broader corpus evaluation. Do
not add a production scale setting or increase the candidate ceiling as a substitute for that study.

## Reproduce locally

From `backend` in Windows CMD:

```cmd
uv run python scripts\run_m10b_physical_scale_experiment.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m10b-physical-scale --preflight-only
uv run python scripts\run_m10b_physical_scale_experiment.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m10b-physical-scale
```

For the separately labelled Realistic-man pilot, from `backend` in Windows CMD:

```cmd
uv run python scripts\run_m10b_physical_scale_experiment.py --manifest ..\artifacts\m7b-corpus\manifest.json --output-dir ..\artifacts\m10b-realistic-man-pilot --realistic-man-pilot
```

The private corpus must remain in the ignored artifact directory. Do not commit any GLB or generated
artifact.
