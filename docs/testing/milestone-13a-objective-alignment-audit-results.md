# Milestone 13A: Objective-to-Evaluation Alignment Audit

> **M13B erratum (2026-11-20):** The original one-view claim in the
> “Mathematical finding” section below was false. For fixed source foreground
> pixels `P`, `IoU = TP / (P + FP)`; increasing `TP-FP` does not by itself
> force IoU upward when both TP and FP decrease. With `P=100`, arrangement A
> `(TP, FP, FN) = (90, 50, 10)` has `TP-FP=40` and `IoU=.600000`, while B
> `(80, 39, 20)` has `TP-FP=41` and `IoU=80/139≈.575540`. The historical M13A
> measurements and conclusions are otherwise frozen. M13B adds a regression
> test and investigates per-view TP/FP trade-offs as well as unequal view
> weighting.

## Decision

**GO for a bounded M13B design experiment; NO-GO for a production change or a claim that a particular new objective improves fidelity.** M12C demonstrates a measurable mismatch: CP-SAT sums pixel-level `TP - FP` across views, while the official result equally averages three IoUs. The fixed solver frame and silhouette-v1's per-arrangement frame are another measurable source of disagreement. This does not attribute Mansion's pixel-level regression without private placement/mask records.

M12C's **NO-GO for 41769a fidelity promotion remains unchanged**. All six real solves were time-limited `FEASIBLE` incumbents, not optimality proofs.

## Audited paths and renderer contract

Reviewed `m12c_wedge_fidelity_experiment.py`, `catalogue_silhouette_experiment.py`, `evaluation_alignment.py`, `fidelity.py`, `surface_grid_v4.py`, the runner, and M12C results. The runner calls `benchmark.aligned_source_mesh` with the fixed grid/up-axis, then uses those same aligned source vertices and completed lattice placements for all measures. No alternative source-to-grid transform was introduced.

Every path uses front `(x,z)`, side `(y,z)`, top `(x,y)`, 128x128 pixels, `round`, clamping to `0..127`, and a flip of the second image axis. The M12C fixed frame starts at zero and ends at the larger source/grid maximum; it has no padding. It draws source triangles, boxes, slopes, and M12C's analytic 41769a body.

Frozen silhouette-v1 instead derives per-view extrema from source plus completed LEGO boxes, slope vertices, and wedge vertices. It adds 1% padding per span (at least `1e-9`) on both ends, then draws source triangle faces, box rectangles, all slope-prism faces, and each wedge's two end polygons. Selected geometry can therefore move source and LEGO pixels. `evaluation_alignment.py` independently repeats this contract; M12C records exact parity for each real assembly.

The CP-SAT objective is exactly `(TP - FP) * (candidate_count + 1) - selected_count`. The multiplier makes part count only a tie-break. It has no FN, union, IoU ratio, or equal-view weighting.

## Mathematical finding

For one unchanged-source view, `P = TP + FN` and `IoU = TP / (P + FP)`. See
the M13B erratum above: the original claim that a higher `TP-FP` cannot lower
this IoU was incorrect. A loss of TP can be smaller than a simultaneous loss
of FP while still lowering the ratio.

It can reverse the three-view result because the solver sums raw pixels while the evaluator weights each view equally after dividing by its own union. This independent, implementation-free counterexample proves the claim and view imbalance:

| Arrangement | Front `(TP,FP,FN)` | Side | Top | Sum TP-FP | Mean IoU |
| --- | --- | --- | --- | ---: | ---: |
| A | `(50,0,50)` | `(10,0,0)` | `(10,0,0)` | 70 | .833333 |
| B | `(61,0,39)` | `(0,0,10)` | `(10,0,0)` | 71 | .536667 |

The part-count tie-break cannot repair a non-tie primary-score trade.

## Frame isolation and synthetic gates

New offline-only `m13a_objective_alignment_audit.py` reports TP/FP/FN/IoU, mean IoU, summed TP-FP, and exact bounds. It supports native silhouette-v1 measurement and caller-supplied shared bounds; it does not modify conversion, solver, catalogue, or frozen evaluation.

| Metric | Frame | Use |
| --- | --- | --- |
| A | M12C fixed source-plus-grid | Existing solver TP-FP |
| B | Same fixed frame | Fixed-frame mean IoU |
| C | Native silhouette-v1 | Official result, own bounds |
| D | Native bounds | Diagnostic TP-FP from C masks |
| E | One source-plus-both-arrangements frame | Separates shape/mask change from re-framing |

`combined_native_bounds()` supplies E and must be reused unchanged for both assemblies. Tests independently specify the counterexample; prove native bounds change when LEGO extents change; prove an unchanged assembly is reproducible; use actual nonrectangular 41769a rather than its envelope; and prove fractional-coordinate explicit native bounds reproduce frozen masks. A changed extremum changes origin/scale, so rounding can move pixels despite similar world-space geometry.

## M12C evidence and Mansion attribution

| Model | Matched control IoU | Expanded IoU | Delta | Components |
| --- | ---: | ---: | ---: | --- |
| Duck | .595249 | .592903 | -.002346 | 2 -> 1 |
| Mansion | .600598 | .589479 | -.011119 | 5 -> 1 |
| Realistic man | .421959 | .421959 | .000000 | 2 -> 3 |

Mansion arithmetic is proven: TP `27086 -> 26974` (-112), FP `17882 -> 17732` (-150), and TP-FP `9204 -> 9242` (+38). Front remains `(10257,3859)`, side remains `(8223,6245)`, and top is `(8606,7778) -> (8494,7628)`. This cannot establish a mean-IoU gain because the aggregate lacks FN and uses another frame.

Frozen Mansion front/side IoUs fell `.718515 -> .706820` and `.561107 -> .539445`; top remained `.522172`. Equal fixed TP/FP totals do not prove equal masks. Aggregate JSON retains no placements, masks, fixed FNs, frozen bounds, or native TP/FP/FN; it cannot partition the loss between world-mask difference and reframing. Per-case parity only proves the two frozen implementations agree for that assembly.

Duck has equal geometry-aware fixed TP/FP/score (`21588/13735/7853`) but loses `.002346` frozen mean IoU. Realistic man selects no wedge, has equal fixed counts (`16879/22444/-5565`) and equal frozen IoU, yet worsens connectivity. These are observations, not wedge causality.

If private artifacts lack placements, do not rerun automatically. A bounded Mansion-only private rerun is:

```cmd
cd backend
.venv\Scripts\python.exe scripts\run_m12c_wedge_fidelity.py --manifest ..\docs\testing\real-world-glb-benchmark-manifest.private.json --output-dir ..\artifacts\m13a-objective-alignment --case mansion
```

Before interpretation, an opt-in trace must record placement IDs, A--E, bounds, and mask hashes/counts for both arrangements. No pixel attribution is claimed here.

## Connectivity, limits, and recommendation

M12C hard constraints cover collision avoidance, protected space, part cap, mandatory witnesses, and direct verified support (including elevated locked placements). V4/M12C has no all-selected reachability/component constraint; components are post-solve diagnostics. TP-FP therefore provides no global-connectivity guarantee. Direct support, collision avoidance, components, isolated parts, stability, and insertion feasibility are different claims. Mechanically accepted does not mean stable or fully connected.

No private rerun occurred and no private GLB/result changed. The smallest M13B is an offline predeclared comparison using identical candidates/geometry/budget: test an equal-view or fixed-frame-IoU-oriented objective, report native and shared frames, and retain connectivity separately. Do not change production behavior, catalogue, scale, constraints, or candidate limits.

## Validation

```cmd
cd backend
uv run pytest -q tests/test_m13a_objective_alignment_audit.py tests/test_m12c_wedge_fidelity_experiment.py tests/test_evaluation_alignment.py tests/test_catalogue_silhouette_experiment.py
uv run ruff check app/conversion/m13a_objective_alignment_audit.py tests/test_m13a_objective_alignment_audit.py
uv run ruff format --check app/conversion/m13a_objective_alignment_audit.py tests/test_m13a_objective_alignment_audit.py
uv run mypy app
cd ..
git diff --check
```
