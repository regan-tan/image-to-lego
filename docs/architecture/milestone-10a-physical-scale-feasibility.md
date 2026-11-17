# Milestone 10A: Physical Scale, Resolution and Architecture Feasibility Audit

Status: design and diagnostic assessment only. No production converter, API, worker, catalogue, metric, or private artifact was changed.

## Executive summary

**Qualified GO for a small offline M10B preflight and experiment; NO-GO for a production scale setting or an unbounded 2x corpus run.** The existing offline `convert_fixed_grid()` seam can make a genuinely larger LEGO reconstruction with existing verified parts: it receives an explicit `GridSize`, so each added horizontal unit remains 8 mm per stud and each vertical unit remains 3.2 mm per plate. More grid positions are therefore real additional representational capacity.

The ordinary V4--V7 interface has no physical-scale setting. It selects a normalized voxel grid from `target_parts`, maps every source axis independently to that integer grid, and reports dimensions from emitted placements. With `max_parts`, V5--V7 deliberately replace the grid request with at most one quarter of the cap. Increasing `maxParts` is therefore neither a direct scale control nor a dependable resolution increase.

M7B found no decision-relevant fidelity improvement from more source evidence or a higher cap at a *fixed* lattice. That is not a test of a larger lattice. M9B stopped because no inactive geometry family had verified mechanics; it is not evidence that richer verified geometry could not help.

The likely practical constraint is CP-SAT candidate/model growth, not the 250,000-cell guard. Mansion already has 3,166 reachable candidates at its baseline grid, while V7 rejects vocabularies over 2,000 candidates. A 1.5x explicit-grid comparison is the smallest useful next point. A 2x point is valid in principle but must be admitted only after 1.5x passes predeclared preflight, solver, and mechanical gates.

## Established baseline and prior evidence

| Source | Grid (studs x studs x plates) | Nominal envelope | Mean silhouette-v1 IoU | Parts | Components |
| --- | ---: | ---: | ---: | ---: | ---: |
| Duck | `5x7x12` | `40x56x38.4 mm` | 0.591700 | 29 | 1 |
| Mansion | `7x4x12` | `56x32x38.4 mm` | 0.600598 | 27 | 6 |
| Realistic man | `3x5x18` | `24x40x57.6 mm` | 0.421959 | 22 | 2 |

These are fixed-lattice 1x/cap-60 records, not source-world measurements. Source meshes are normalized independently by axis.

- M7B fixed-grid controls found no mean-IoU improvement of 0.01 or more from cap 60 versus 30 or 2x source evidence. All points had zero collisions and zero unsupported evaluated placements.
- M8A--M8D did not establish a meaningful frozen-metric gain from source-aware/catalogue/objective changes; M8D found an historical feasible-set mismatch for Duck and Mansion.
- M9A showed all three V6 baselines feasible in its corrected offline model while retaining cap, collision, support, and protected-space checks. It did not prove global geometric optimality.
- M9B found no inactive non-rectangular part family eligible for mechanical admission. It did not test a new family.

## Current architecture and exact references

| Stage | Finding | Code reference |
| --- | --- | --- |
| GLB loading | `trimesh` loads scene geometry and rejects unreadable, empty, non-triangle, non-finite, over-16 MiB, or over-100,000-triangle input. | [`core.py`](../../backend/app/conversion/core.py#L951-L975) |
| Alignment | `_normalize_vertices()` maps the requested up axis then translates minima to zero. Y-up maps `(x,y,z)` to `(x,-z,y)`. | [`core.py`](../../backend/app/conversion/core.py#L1159-L1188) |
| Grid selection | V3 tries budget-factor grids, voxelizes/greedily packs them, and selects the packed-part-count-nearest grid. | [`core.py`](../../backend/app/conversion/core.py#L878-L915) |
| Grid scaling | `_scale_vertices_to_grid()` independently maps X/Y/Z to `[0,w-1]`, `[0,d-1]`, `[0,h-1]`. | [`core.py`](../../backend/app/conversion/core.py#L1352-L1363) |
| Surface evidence | Scaled triangles are voxelized at pitch 1.0. Watertight meshes alone get a conservative interior flood-fill result. | [`core.py`](../../backend/app/conversion/core.py#L1218-L1242), [`core.py`](../../backend/app/conversion/core.py#L1245-L1290) |
| Grid formula | Dimensions are derived from physical-unit proportions and separately rounded cube-root-scaled cell budget. | [`core.py`](../../backend/app/conversion/core.py#L1191-L1215) |
| Slopes | Eligible 4286 slopes are locked from top-surface evidence before rectangular packing. | [`core.py`](../../backend/app/conversion/core.py#L1462-L1554) |
| Hull | V4 builds front/side/top projection witnesses and retains cells satisfying all three. | [`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L287-L313) |
| Candidates | Every target-cell origin is tested with each verified rectangular part/orientation, then support reachability prunes candidates. | [`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L326-L394) |
| CP-SAT | Stage one maximizes witness coverage; stage two minimizes parts/source-aware cost with occupancy non-overlap and direct support. | [`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L166-L232), [`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L397-L455) |
| Reliable V5 | Protects proven exterior only for watertight meshes, excludes locked-body collisions, uses a cap, repairs support, and rechecks support/collisions. | [`core.py`](../../backend/app/conversion/core.py#L489-L542) |
| V6 refinement | Tests at most 64 local 4286 candidates and rejects any unsafe/fidelity-regressing proposal. | [`core.py`](../../backend/app/conversion/core.py#L67-L78), [`core.py`](../../backend/app/conversion/core.py#L683-L802) |
| V7 | Starts from V6 and retains V6 unless complete-model connectivity strictly improves without fidelity regression. | [`connectivity_experiment.py`](../../backend/app/conversion/connectivity_experiment.py#L509-L738), [`connectivity_experiment.py`](../../backend/app/conversion/connectivity_experiment.py#L741-L806) |
| Dimensions | Output size is the maximum emitted placement extent at 8 mm/stud and 3.2 mm/plate, not the source mesh dimensions. | [`core.py`](../../backend/app/conversion/core.py#L1653-L1671) |

Production dispatch is intentionally untouched: `convert_glb()` routes only V3--V7 ([`core.py`](../../backend/app/conversion/core.py#L229-L248)). The diagnostic fixed-grid module explicitly is not imported by API, workers, or dispatch ([`fixed_grid_experiment.py`](../../backend/app/conversion/fixed_grid_experiment.py#L1-L4)). This is the correct M10B implementation seam.

## Physical scale mechanics

For an explicit grid `(w,d,h)`, the nominal physical envelope is:

```text
width = w * 8.0 mm; depth = d * 8.0 mm; height = h * 3.2 mm
```

The source's original absolute units do not control output size. A mesh made twice as wide in input coordinates normalizes to the same grid geometry for identical settings. `_scale_vertices_to_grid()` is anisotropic normalization, not world-scale preservation.

The final `ModelDimensions` can be smaller than the nominal grid envelope because it takes the maximum occupied placement extent. M10B must report both the selected grid/nominal envelope and final dimensions.

`target_parts` is a grid-selection preference, not a physical dimension. V3 computes:

```text
scale = (cell_budget / proportion_volume) ** (1 / 3)
axis = max(2, round(axis_proportion * scale))
```

Thus integer rounding introduces small aspect distortion. V5--V7 additionally apply the intentional hard-cap coarsening rule:

```text
grid_target_parts = min(target_parts, max(1, max_parts // 4))
```

([`core.py`](../../backend/app/conversion/core.py#L448-L462)). A higher cap at a fixed grid only relaxes selected-placement count; it adds no stud or plate position.

## 1x, 1.5x, and 2x planning scenarios

The following are **estimated grids, not measured converter outputs**. They use the existing offline runner's per-axis `round()` rule (`run_m7b_fixed_grid_experiment.py:63-70`). Python ties to even, so `5 * 1.5 = 7.5` becomes 8 and `7 * 1.5 = 10.5` becomes 10.

| Source | 1x grid / envelope | 1.5x estimated grid / envelope | Realized 1.5x factors (w,d,h) | 2x estimated grid / envelope |
| --- | --- | --- | --- | --- |
| Duck | `5x7x12` / `40x56x38.4 mm` | `8x10x18` / `64x80x57.6 mm` | `1.60, 1.43, 1.50` | `10x14x24` / `80x112x76.8 mm` |
| Mansion | `7x4x12` / `56x32x38.4 mm` | `10x6x18` / `80x48x57.6 mm` | `1.43, 1.50, 1.50` | `14x8x24` / `112x64x76.8 mm` |
| Realistic man | `3x5x18` / `24x40x57.6 mm` | `4x8x27` / `32x64x86.4 mm` | `1.33, 1.60, 1.50` | `6x10x36` / `48x80x115.2 mm` |

| Source | Baseline cells | 1.5x cells / multiplier | 2x cells / multiplier |
| --- | ---: | ---: | ---: |
| Duck | 420 | 1,440 / 3.43x | 3,360 / 8.00x |
| Mansion | 336 | 1,080 / 3.21x | 2,688 / 8.00x |
| Realistic man | 270 | 864 / 3.20x | 2,160 / 8.00x |

All estimates are below the 250,000-cell guard, but raw cell count is not the primary solver cost. A larger grid offers more physical degrees of freedom; it does not establish that the current vocabulary/objective will use them faithfully.

## Resource constraints

### Hard and configurable limits

- Input, triangle, target-part, max-part, and grid guards are 16 MiB, 100,000, 10,000, 10,000, and 250,000 respectively ([`core.py`](../../backend/app/conversion/core.py#L51-L63), [`core.py`](../../backend/app/conversion/core.py#L918-L948)).
- The fixed-grid seam enforces the same input/grid/part bounds and supports only 1x/2x source evidence ([`fixed_grid_experiment.py`](../../backend/app/conversion/fixed_grid_experiment.py#L150-L173)).
- V4 uses one solver worker/seed zero; stage one gets 20 deterministic units (40 at `target_parts >= 600`), and stage two/repair each get 7.25 ([`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L21-L34), [`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L258-L261), [`surface_grid_v4.py`](../../backend/app/conversion/surface_grid_v4.py#L1271-L1288)).
- Reliable repair has a 2,000-candidate bound; V6 local refinement has a 64-candidate bound.
- V7 limits candidate vocabulary and modeled connection pairs to 2,000, with a five-unit budget ([`connectivity_experiment.py`](../../backend/app/conversion/connectivity_experiment.py#L59-L68), [`connectivity_experiment.py`](../../backend/app/conversion/connectivity_experiment.py#L596-L610)).

Every candidate produces a selection variable; each target cell produces occupancy state; each witness and support contact adds variables/constraints. Candidate enumeration is origin x eligible rectangular part x orientation, before CP-SAT.

Existing reachable counts are Duck 1,449, Mansion 3,166, and Realistic man 1,043. If candidate density were unchanged, 1.5x raw-grid multipliers suggest approximately 4,968, 10,168, and 3,338 candidates. These are not runtime predictions: hull shape, pruning, slopes, and topology make density nonlinear. They are enough to require a measured preflight. At 2x, the unsupported density-only estimate is about eight times baseline work.

M8C's 4,000-candidate, 49,152-raw-pixel, 20-unit, one-worker, 180-second experimental ceiling is a conservative M10B preflight ceiling, not evidence that V5/V6 can solve every 4,000-candidate case.

## Mechanical reliability implications

Larger models can describe thinner contours and gradual profiles, but can also create more disconnected islands, unsupported spans, overhangs, contacts, assembly steps, and mass/footprint risks. Collision-free is not connected; connected is not stable.

The current collision proxy answers only whether modeled bodies overlap. `stud-connectivity-v1` establishes curated vertical connector relations and direct support for evaluated non-base placements. It does not prove clutch force, lateral bracing, centre of mass, global rigidity, hand access, or a practical assembly sequence. This is material because Mansion already has six components and Realistic man two. M9A reduced Mansion to three but retained Realistic man at two.

The following safety constraints must not be weakened: verified catalogue eligibility/orientations; hard cap; watertight-source protected-space rule; body collision checks; evaluated support/repair; and component/connectivity reporting. The three private sources are non-watertight, so zero protected cells means unknown source interior/exterior, not permission to fill apparent voids.

## Minimal M10B experiment

Use `convert_fixed_grid()` only. It accepts explicit grids, preserves V5 checks, offers V6 refinement, and is isolated from production. Add only an offline runner, aggregate schema, and focused tests; do not change V4--V7, `convert_glb()`, APIs, workers, frontend, catalogue eligibility, or frozen metrics.

Use the SHA-256-pinned private corpus via the existing manifest pattern. Store only hashes and aggregate records under ignored `artifacts/m10b-physical-scale/`; do not commit source bytes, paths, placements, or generated artifacts.

1. Re-run 1x controls: frozen grids, Y-up, 1x evidence, `solverTargetParts=24`, cap 60, V6 shape-aware path, same catalogue/colour policy, seed, workers, and solver limits. Require parity before larger points.
2. Preflight all three 1.5x grids. Record target cells, witnesses, candidates, support contacts, model-build time, and termination reason before interpreting a solver result.
3. Fully solve only preflight-passing 1.5x points. A candidate/time/no-incumbent failure is an honest `infeasible_under_budget` result; do not silently coarsen or raise a limit.
4. Attempt 2x only where the same source completes two deterministic 1.5x runs within every gate. It is exploratory, not a required three-source point.

For every point record source hash; requested/realized scale; grid; nominal/final dimensions; part count/cap; source/protected/hull/final cells; candidates/witnesses/contacts/repair/refinement counts; stage statuses/objectives/bounds/deterministic and wall time; collisions/protected violations/unsupported count; component/ratio/isolation; and insertion diagnostics when available.

Keep frozen `silhouette-v1`, but label cross-scale findings as cross-scale because its dynamic padded bounds and raster resolution can confound scale. Retain Surface Metric V2 with existing unavailable semantics and alignment data. Report absolute V2 plus a separately labelled normalized distance (for example, divide by source-aligned nominal-grid diagonal); do not alter historical V1/V2. A common-frame normalized silhouette is complementary analysis only, never a replacement for frozen evaluation.

### Proposed hypotheses and stop budgets

| Category | M10B rule |
| --- | --- |
| Candidate preflight | Start at the documented 4,000-candidate experimental ceiling. Record overage; do not raise it mid-experiment. |
| Solver | Preserve current V4 budgets, seed zero, and one worker. No usable incumbent fails the point. |
| Time | At most 180 seconds per source/scale/variant; stop safely and report timeout. |
| Progression | A 2x source point requires two successful identical 1.5x runs. |
| Mechanical | Zero collisions, protected-space violations, unsupported evaluated placements, and cap violations. |
| Connectivity | No automatic exception for component increase, more isolated parts, or reduced largest-component ratio. |
| Fidelity hypothesis | At least two completed 1.5x sources improve frozen mean IoU by >=0.01, none regresses >0.005, and available paired Surface V2 remains within established shape-aware tolerances. |
| Reproducibility | Non-timing records match exactly across two identical runs. |

The 4,000-candidate bound may reject Duck/Mansion at 1.5x under the density-only estimate, while potentially admitting Realistic man. That result would constrain the present architecture; it would not prove that larger LEGO models cannot help.

## Alternatives rejected

| Alternative | Reason |
| --- | --- |
| Raise `maxParts` only | Adds no physical grid position; V5--V7 may coarsen grid selection through the quarter-cap rule. |
| Increase source evidence | M7B already tested this at fixed lattices; it does not enlarge the object. |
| Scale input coordinates | Normalization removes absolute source scale. |
| Post-scale completed placements | Breaks genuine LEGO dimensions/connectors. |
| Relax collision/support/protected checks | Invalidates the mechanical comparison. |
| Add inactive wedges/curves | M9B found their mechanical contracts unevaluated. |
| Raise candidate/solver limits first | Makes cost unbounded before any evidence of a benefit. |
| Add a production scale option | Premature public/cost/reliability change before experiment evidence. |

## GO/NO-GO decision

**GO, conditionally, for the bounded offline M10B fixed-grid experiment.** A valid physical-scale method, isolated implementation seam, genuine units, deterministic solver configuration, private-input controls, and safety gates already exist.

**NO-GO for a production setting, an unbounded 2x run, or any individual point exceeding declared preflight/time/no-incumbent limits.** V7 is unsuitable as the large-scale primary path under its 2,000-candidate bound; M10B should use V6 fixed-lattice packing and report connectivity.

Remaining uncertainty is empirical: actual candidate counts, solver/memory behaviour, final part counts, metrics, and mechanics at larger grids have not been measured. The 1.5x rounded grids are not isotropic exact 1.5x objects. Open source meshes prevent proof of intended negative space, and existing mechanical checks do not certify a stable consumer build.

The answer to the central question is therefore: **larger, more expressive genuine LEGO lattices are technically available with the verified catalogue, but meaningful recognizability improvement within current solver and mechanical budgets is unproven and requires this bounded M10B test.**
