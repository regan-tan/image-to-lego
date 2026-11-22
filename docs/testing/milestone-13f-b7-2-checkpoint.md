# M13F-B7.2 reconstruction checkpoint

Status: completed offline research checkpoint. This document records results
from ignored local artifacts; it does not add an experimental policy or
connectivity constraint to production conversion.

## Fixed-frame occupancy-policy result

The matched, exact fixed-frame comparison below uses each case's reconstructed
M13B candidate universe and the same fixed source masks. The `50%` arm requires
a historical coarse requirement only when at least half of its fixed-frame
source-raster rectangle is foreground. It is an experimental, source-specific
policy, not a general policy or production behaviour.

| Case | Historical mean IoU | 50% mean IoU | Change |
| --- | ---: | ---: | ---: |
| Duck | 0.601744 | 0.786905 | +0.185162 |
| Mansion | 0.603171 | 0.839882 | +0.236711 |
| Realistic man | 0.424073 | 0.654009 | +0.229936 |

These are matched fixed-frame silhouette results, not a physical-buildability
claim or proof of generalisation. The 50% threshold was derived from the Duck
occupancy audit and was then tested on the two available non-Duck cases. It
needs a larger, independently selected corpus before it could support a
general policy decision.

## B7.2 Mansion connectivity result

The B7.2 iterative exact separator-cut run preserved the selected B6 50%
witness's three projection masks exactly (`fixedMaskXorByView`: front 0, side
0, top 0). It found and independently checked a 30-piece, single-component
Mansion assembly with the same fixed-frame mean IoU, `0.839882`
(`69940546579/83274253920`) and preserved the B6 optimal surrogate score,
`162246440`. The run used three cut-generation iterations and seven valid
separator cuts.

This is an existence result only. The follow-up exact-mask part-minimisation
stage reached its deterministic time budget with an incumbent of 11 selected
candidate placements and lower bound 2; it is `UNKNOWN`. Consequently, the
minimum part count for a connected exact-silhouette Mansion assembly remains
unproven, and the 30-piece witness must not be described as minimal.

Exact mechanical contact connectivity and the completed-arrangement checks
were used for this research witness. They do not establish clutch strength,
structural stability, insertion order/clearance, support under gravity, or
other physical buildability. Results are also bounded by the fixed source,
candidate universe, rectangular-part catalogue, raster frame, and three-case
evaluation; they do not demonstrate generalisation to arbitrary images or
models.

## Reproduction and artifact custody

The committed runners, tests, and result notes are the reproducible method;
they deliberately write source-derived placement records, masks, checkpoints,
and summaries only beneath ignored `artifacts/`. The recorded B7.2 result is
in `artifacts/m13f-connectivity-cut-generation-b7-2-new/summary.json`; the
matched-policy results are in `artifacts/m13f-duck-occupancy-coverage-ablation/summary.json`
and `artifacts/m13f-cross-object-validation/{mansion,realistic-man}/summary.json`.

Before the workstation copy is removed, archive those complete ignored
directories (including `PRIVATE_UNVALIDATED_CHECKPOINT.json` files) to the
team's approved private, access-controlled research storage, together with a
SHA-256 manifest of the archive. Keep the archive outside Git and retain the
source/corpus access controls. The local artifacts are intentionally not
staged or committed.

To reproduce the B7.2 run with the same private inputs, run from `backend/`:

```cmd
uv run python scripts\run_m13f_connectivity_optimization.py --manifest ..\artifacts\m7b-corpus\manifest.json --m13b-summary ..\artifacts\m13b-mansion-pilot\summary.json --b6-summary ..\artifacts\m13f-cross-object-validation\mansion\summary.json --connectivity-formulation cuts --output-dir ..\artifacts\m13f-connectivity-cut-generation-b7-2-new
```

The command is intentionally opt-in and writes only ignored local artifacts.
