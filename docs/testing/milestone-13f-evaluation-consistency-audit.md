# M13F-B5 evaluation consistency audit

Frozen silhouette-v1 is a legacy diagnostic, not a controlled cross-assembly metric. Its renderer
forms padded projection bounds from the source geometry **and the evaluated assembly**, then renders
both masks at 128 by 128 pixels. Different assemblies therefore change scale and rasterization of
the same source, including its foreground-pixel count. This is intended historical semantics, not a
fixed-frame implementation bug; it must not be reinterpreted or changed retroactively.

Future controlled policy experiments should use fixed-frame exact TP/FP/FN, identical source masks,
identical frame bounds, and exact mean-IoU arithmetic as their primary measure. Continue reporting
frozen silhouette-v1 only as a native-frame diagnostic, with its framing semantics noted.

The B5 no-solver audit reconstructs the B4 50% and fully relaxed witnesses, reruns independent
fixed-frame parity and mechanical checks, compares their three fixed-frame mask hashes, and records
frozen source-pixel counts derived from each witness's native bounds. It does not alter B4 artifacts
or invoke CP-SAT.

The repository has two legally usable private-local non-Duck sources in the corpus: `mansion`
(architectural) and `realistic-man` (complex figure). It has no matched M13F candidate provenance
and three-policy result summaries for either, so no cross-object result is claimed. The predeclared
generalization policy remains source occupancy >= 50%; a future opt-in matched experiment must
reconstruct each object's own candidate universe and requirements before solving.

Connectivity remains a secondary selection criterion, not a hard production constraint in this
milestone: among silhouette-equivalent mechanically valid assemblies, prefer fewer components and
then fewer parts. Graph connectivity does not prove structural stability or insertion feasibility.

Run from Windows CMD:

```cmd
cd backend
uv run python scripts\run_m13f_evaluation_consistency_audit.py ^
  --manifest ..\artifacts\m7b-corpus\manifest-duck.json ^
  --corpus-manifest ..\artifacts\m7b-corpus\manifest.json ^
  --summary ..\artifacts\m13b-duck-final\summary.json ^
  --b4-summary ..\artifacts\m13f-duck-occupancy-coverage-ablation\summary.json
```

Add `--output ..\artifacts\m13f-evaluation-consistency-audit\summary.json` to serialize a
read-only audit report. No private optimization is performed by this command.
