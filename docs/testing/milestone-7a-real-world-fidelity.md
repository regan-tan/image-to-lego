# Milestone 7A: real-world 3D-to-LEGO fidelity benchmark

## Status

The evaluation harness is implemented and the historical synthetic benchmark is
unchanged. No approved, non-private real-world GLB corpus is currently present
in this repository, so no real-world ranking or V8 recommendation is justified
yet. This is an explicit corpus limitation, not a zero-result claim.

The checked-in manifest is
[`real-world-glb-benchmark-manifest.json`](real-world-glb-benchmark-manifest.json).
It intentionally has `corpusStatus: unavailable` and no invented source
results. The existing synthetic suite remains useful for harness regression,
but it is not a substitute for representative reconstructed models.

## Metric audit

| Measurement | Existing version | Establishes | Does not establish |
| --- | --- | --- | --- |
| Front/side/top IoU | `silhouette-v1` | Orthographic projection overlap | Depth, hidden geometry, exterior union, buildability |
| Mean IoU | `silhouette-v1` | Mean of the three fixed projections | A volumetric fidelity score |
| Symmetric surface distance, directions, P95 | `placement-surface-proxy-v1` | Bounded nearest-distance proxy in physical mm | Exact boolean-union distance or mould accuracy |
| Opening fill | current top-view diagnostic | Coverage of enclosed top-projection void pixels | General 3D hole preservation |
| Buildability | `stud-connectivity-v1` | Supported-connector connectivity, isolated and unsupported evaluated placements | Stability, insertion feasibility, collision-free construction |
| Collision pairs | physical microcell proxy | Intersecting supported body-proxy cells | Exact physical interference or assembly safety |

Source vertices receive the same up-axis normalization, origin normalization,
and selected-grid scaling as `convert_glb()`. Output dimensions are reported in
mm using 8 mm/stud and 3.2 mm/plate. This alignment makes a single run coherent,
but it does not hold physical scale fixed across algorithms or targets.

The runner marks an algorithm pair `matched-scale` only when its case, target,
hard cap, up axis, and output physical dimensions all match. Every other pair
is `scale-confounded`; absolute Chamfer and P95 values must not be used to rank
those records. Post-hoc scaling of an output is not treated as an equivalent
fixed-scale LEGO build. Volumetric IoU remains intentionally uncomputed.

## Adding an approved corpus

Do not commit private uploads or binary models without explicit approval. Keep
approved local GLBs beside a copied manifest (for example under an untracked
`artifacts/approved-glbs/` directory), calculate SHA-256, and include one entry
per source with its stable `id`, relative `.glb` `path`, lowercase `sha256`,
`provenance`, `usageRestrictions`, `characteristics`, `upAxis`, and
`targetParts`. The runner rejects path traversal, duplicate IDs, malformed
hashes, missing sources, and byte changes.

Use six to ten approved sources covering curved organic shape, diagonal vehicle,
architectural opening, thin feature, multicolour/textured source, and imperfect
or non-watertight reconstruction. Prefer the application's reconstruction
outputs where their owner has approved their use. Record licensing and source
restrictions in the manifest rather than assuming them.

## Run locally (Windows CMD)

From the repository root:

```cmd
cd backend
uv run python scripts\benchmark_real_world_fidelity.py --manifest ..\docs\testing\real-world-glb-benchmark-manifest.json --output-dir ..\artifacts\real-world-lego-benchmark
uv run python scripts\benchmark_conversion_fidelity.py --suite synthetic --full --algorithm surface-grid-v4 --output-dir ..\artifacts\lego-fidelity-benchmark-v4
uv run ruff check .
uv run mypy app
uv run pytest -q
```

For a populated manifest, the real-world runner invokes `convert_glb()` once
for V4, V6, and V7 per case. V6 and V7 share its fixed `--max-parts` hard cap
(default 120). V4 does not support that hard cap, so its `targetParts` request
is limited to 300 before source bytes are read or any conversion begins. This
is deliberately the highest completed V4 request in the frozen benchmark;
the 600-part full suite was not feasible. `targetParts` remains requested
detail, not a hard output-part cap. The preflight reports rejected settings as
clear stderr text followed by JSON diagnostics; it does not guarantee a strict
wall-clock timeout, because source complexity still affects conversion cost.
Failed conversions and SHA/missing-source failures are written as records and
remain in per-algorithm totals. A converter-raised `TimeoutError` is retained
with a `timeout` status rather than being dropped. It emits `summary.json` plus
source masks, LEGO masks, and controlled front/side/top overlays for each
successful run. These images are diagnostic silhouette evidence, not arbitrary
rendered or AI-generated imagery.

When a future full test-suite run is needed, collect `pytest --durations` data
alongside the result so an unexpected runtime change is evidence-based.

## Failure taxonomy and next step

Classify observations as coarse-grid/lost detail, curved-or-sloped loss,
missing-or-filled opening, depth error despite silhouettes, part-count anomaly,
mechanical disconnectivity, colour/texture loss, uncertain topology, scale
mismatch, or solver failure/timeout. Records are evidence; a suspected cause
must remain a hypothesis unless the measurement isolates it.

Until the corpus is populated, the only evidence-backed next step is to collect
the approved corpus and run the comparison. A V8 algorithm or catalogue change
would be premature: it cannot yet be ranked by affected cases, fidelity gain,
mechanical verification work, runtime/memory cost, or regression risk.
