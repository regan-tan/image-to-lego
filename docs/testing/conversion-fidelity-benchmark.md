# Conversion fidelity benchmark

## Purpose

This offline benchmark freezes a reproducible baseline for the current
surface-grid-v4 GLB-to-LEGO converter. It does not improve the converter or
change its production JSON. Instead, it shows where a LEGO result differs from
the original source mesh so that a later algorithm can make a fair, evidence-
based comparison.

surface-grid-v4 optimizes a structurally valid rectangular placement solution
against a v3-derived projection hull. That is a useful construction objective,
but it is not a direct optimization of the original mesh's 3D surface. Even
perfect orthographic silhouettes can hide depth displacement, rounded-shape
faceting, unwanted volume, or an opening filled along the viewing direction.

## Run it

From `backend/`, run the small deterministic synthetic smoke suite:

```powershell
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --algorithm surface-grid-v4 --target-parts 100 --output-dir ../artifacts/lego-fidelity-benchmark
```

The command above deliberately defaults to the box and thin-wall cases so it is
practical on a normal developer laptop. Run every fixture manually with
`--full`, or select one or more exact fixtures with `--case`:

```powershell
uv run python scripts/benchmark_conversion_fidelity.py --suite synthetic --full --output-dir ../artifacts/lego-fidelity-benchmark-full
```

To inspect a local GLB without uploading it or contacting any external service:

```powershell
uv run python scripts/benchmark_conversion_fidelity.py --source path/to/model.glb --algorithm surface-grid-v4 --target-parts 300 --output-dir ../artifacts/lego-fidelity-benchmark
```

Use `--algorithm surface-grid-v3` to record a comparison with the preserved v3
path. A user-provided source requires `--target-parts`; synthetic fixtures have
documented defaults when that option is omitted. `--case` may be repeated.

The benchmark records an offline `openingDiagnostic` and a compact
`stud-connectivity-v1` buildability summary for every completed case. These
measurements do not affect conversion routing or algorithm selection; see the
[Milestone 4 investigation](milestone-4-advanced-part-fitting.md).

The command invokes the real `convert_glb()` entry point. It has no Azure,
database, queue, provider, authentication, GPU, or network dependency. Invalid
input, converter limits, and individual conversion failures are written as
failed case records; the command returns nonzero if any selected case fails.

## Fixtures

Fixtures are created at runtime with the existing `trimesh` dependency, not
stored as binary files. The version is `synthetic-fixtures-v1`; stable IDs are
`box`, `thin-wall`, `sphere`, `cylinder`, `pyramid`, `l-profile`, `ring`, and
`open-box`. They cover aligned volume, thin detail, smooth surfaces, a round
profile, sloped faces, a concave footprint, an explicit through-opening, and a
non-watertight robustness case. They use low/moderate complexity so that the
suite is practical on a developer laptop.

## Alignment and measurements

The benchmark loads the original source GLB, applies the converter's existing
up-axis conversion and origin normalization, then calls the same grid scaling
used by `convert_glb()`. It does **not** compare against the v3 result or the
v4 projection hull. All source/output metrics therefore use a shared grid.

`summary.json`, each `cases/<caseId>/metrics.json`, and `summary.csv` use the
separate, versioned `conversion-benchmark-v1` schema. Records include the
source SHA-256, fixture version where applicable, converter settings and
algorithm, grid dimensions, source triangle count and watertightness, part
counts, metric versions/settings, runtime, and failure reasons. JSON keys and
case order are stable; runtime is explicitly marked environment-dependent.

### Silhouette-v1

Front (XZ), side (YZ), and top (XY) binary IoU remain the existing
`silhouette-v1` calculations exactly. The record also contains their mean,
target/actual part count, count delta/error ratio, and false-positive or
false-negative information in the diagnostic images. Higher IoU is better.

### Placement-surface-proxy-v1

The new geometric measure samples source triangles area-proportionally using a
fixed low-discrepancy sequence. It samples rectangular LEGO placements as box
surfaces and supported slopes/wedges through the converter's existing shape
geometry rather than treating slopes as full bounding boxes. It computes:

- symmetric sampled surface Chamfer distance: the mean of source-to-LEGO and
  LEGO-to-source nearest-surface distances, in millimetres;
- 95th-percentile nearest-surface distance over both directed sample sets, in
  millimetres; and
- the symmetric distance divided by the source bounding-box diagonal, as a
  dimensionless comparison scale.

The conversion grid uses 8 mm in X/Y per stud and 3.2 mm in Z per plate before
Euclidean distance is calculated. This prevents a plate-height displacement
from being incorrectly treated as a stud-width displacement.

This is honestly named a **placement exterior-surface proxy**, not an exact
boolean union. Inter-brick faces can remain in the primitive surface set, so
partially occluded faces are not fully removed. It is bounded to 384 samples
per surface and 20,000 triangles per surface. A case outside those bounds
reports `unavailable` with a reason instead of a fictional score. It is
deterministic but not a substitute for a future exact CSG/exterior extraction
implementation.

Volumetric IoU is intentionally null with a `not_computed` reason. A common,
shape-faithful volume definition would require a reviewed resolution and
interior policy; bounding boxes would incorrectly make irregular objects look
accurate. Non-watertight source meshes are still converted and compared by
surface/silhouette metrics, but are never presented as having a trusted source
interior.

### Opening diagnostic

The `openingDiagnostic` is intentionally narrow: it finds source-enclosed,
empty pixels in the **top** silhouette and measures which are filled by LEGO.
That identifies a specific void region rather than labelling arbitrary exterior
space as an opening. It is a 2D projection diagnostic, so it reports
`not_applicable` when the source has no enclosed top-view void and does not
claim 3D hole preservation.

## Overlays and output

Every successful case writes `front_overlay.png`, `side_overlay.png`, and
`top_overlay.png` at the canonical silhouette resolution plus a fixed legend.
Green is correct overlap, magenta is source coverage missing from LEGO, and
orange is extra LEGO coverage. Source and LEGO masks share the same bounds in
each view because the existing `render_silhouette_masks()` function is used.

Results stay in the selected output directory (default
`../artifacts/lego-fidelity-benchmark`), which is gitignored. No source model
or output artifact is uploaded automatically.

## Comparing a future algorithm fairly

Compare only completed records that match source SHA-256, fixture version,
algorithm settings such as target parts/up axis, silhouette version, geometry
metric version, and sample count. Do not claim an improvement from runs with a
different source, scale, fixture, target budget, or metric definition. Runtime
can be reported separately, but should not be read as deterministic across
hardware or dependency versions.

### Cross-budget scale warning

The current converter chooses a new grid for each `targetParts` request. The
benchmark deliberately aligns the source to that selected grid, which means the
same original fixture obtains different physical bounding-box dimensions in
millimetres at different budgets. For example, the box source is 104.0 × 48.0
× 83.2 mm at target 100 and 192.0 × 88.0 × 150.4 mm at target 300.

Consequently, absolute Chamfer and p95 values in millimetres are valid within
one run but are **not** evidence of better or worse relative fidelity across
budgets. Use `normalizedChamfer` for cross-budget relative comparisons, while
still matching the fixture hash, evaluator version, and other settings. The
baseline records each run's grid dimensions and source bounding-box dimensions
so a comparison cannot silently mix scales.

When future work needs reliable volumetric scores, exact external-face removal,
or 3D opening preservation, add a reviewed metric version rather than changing
this frozen baseline's semantics. Likely next work is source-aware fitting for
curves/slopes and protected negative-space constraints, backed by the baseline
records produced here.

## Current baseline

The versioned v4 baseline record is
[`surface-grid-v4-fidelity-baseline-v1.json`](baselines/surface-grid-v4-fidelity-baseline-v1.json).
It freezes the source commit, fixture hashes, dependency version, conversion
settings, evaluator definition, and every completed accuracy result. It also
records explicit converter failures and environment-limited incomplete runs so
they cannot be mistaken for successful measurements.

One local v4 run at 12 target parts produced the following representative
smoke baseline (runtime is intentionally omitted because it is environment-dependent):

| Case | Actual parts | Mean IoU | Symmetric proxy Chamfer | Top-view void fill |
| --- | ---: | ---: | ---: | ---: |
| Box | 8 | 0.613169 | 2.577955 mm | not applicable |
| Thin wall | 12 | 0.662951 | 2.244281 mm | not applicable |
| Ring | 10 | 0.592571 | 2.260598 mm | 0.764665 |

The ring result demonstrates the value of the explicit void check: its
top-view silhouette IoU is only 0.441734 and about 76% of the source-enclosed
top-view opening is covered by output. Expected qualitative weaknesses are
coarse silhouettes for curved fixtures, lost thin detail, projection-hull
distortion of concave shapes, and filled openings. The benchmark is designed to
quantify rather than conceal those limitations.
