# Milestone 14A — Exact physical collision-filter optimization

## Scope

This offline-only change optimizes the locked-placement body-collision filter in
`surface_grid_v4.py`. It does not alter conversion objectives, candidate
generation, ordering, solver budgets, part limits, physical geometry, support
checks, buildability checks, algorithm identifiers, or public/API contracts.
Historical conversion benchmark records are unchanged.

## Implementation and equivalence

The original filter retained a candidate placement `C` when every locked
placement `L` had no overlapping world-space physical microcell:

```text
for every L: microcells(C) ∩ microcells(L) = empty
```

`placements_overlap` has exactly this definition: it calculates the two
world-space `physical_microcells` sets and tests their intersection. There is
no pair-specific tolerance, collision state, or mutable geometry involved.
Therefore, for the local union `U = union(microcells(L))`, the original rule is
equivalent to:

```text
microcells(C) ∩ U = empty
```

M14A builds `U` once per filter invocation, calculates each candidate's
world-space cells once, and retains candidates through the same stable tuple
comprehension. The pre-existing empty-locked fast path returns the original
candidate tuple unchanged. The world-space union is a local set only; it is
not cached, so it cannot retain placements or grow memory across worker jobs.
The pre-existing cached data remains only the bounded per-part local geometry.

## Equivalence evidence

`backend/tests/test_surface_grid_v4.py` includes an explicit reference copy of
the former pairwise filter. It checks that the optimized output has identical
candidate identities and ordering for:

- empty locked placements and the unchanged fast-path identity;
- multiple locked placements, collisions, and face contact without overlap;
- translated rectangular placements; all supported orientations; 4286, wedge
  41769/41770, and curved-slope 15068 physical geometry; and
- twelve deterministic randomized mixed-placement cases.

It also monkeypatches `physical_microcells` to verify that a non-empty filter
call calculates every candidate and locked placement's world geometry exactly
once.

## Offline microbenchmark

The script below constructs only deterministic synthetic placements. It uses no
GLB, conversion routing, network, paid API, or production service. Before each
timed case it compares retained candidate identity and ordering with its local
pairwise reference implementation. Values are the median of three runs on the
local Windows development environment on 24 November 2026; they are evidence
of this hotspot only, not a worker throughput or SLA claim.

```powershell
cd backend
uv run python scripts/benchmark_locked_collision_filter.py --repetitions 3
```

| Candidates | Locked placements | Retained | Pairwise seconds | Union seconds | Speedup |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 48 | 6 | 48 | 0.289850 | 0.025783 | 11.24x |
| 96 | 12 | 96 | 1.077036 | 0.039487 | 27.28x |
| 144 | 18 | 144 | 2.251784 | 0.057256 | 39.33x |

The workloads intentionally keep candidate and locked bodies disjoint, forcing
the reference implementation to complete every pairwise comparison. This
isolates the repeated geometry construction that was observed in the manually
interrupted conversion. Actual conversion runtime also includes candidate
generation, CP-SAT, support repair, final validation, and model serialization,
so these microbenchmark speedups must not be interpreted as end-to-end speedup.

## Validation

From `backend/`, the focused offline checks completed:

```text
uv run ruff check app/conversion/surface_grid_v4.py \
  tests/test_surface_grid_v4.py scripts/benchmark_locked_collision_filter.py
uv run mypy app/conversion/surface_grid_v4.py scripts/benchmark_locked_collision_filter.py
uv run pytest -q tests/test_surface_grid_v4.py -k locked_body_collision
uv run pytest -q tests/test_physical_geometry.py
```

No timing-dependent unit-test assertion was added. The benchmark is an
explicit manual performance measurement rather than part of the normal test
suite.

## Remaining limitations

Physical microcells remain a deterministic sampled body proxy, not a complete
claim about mould-level collision, assembly insertion, or stability. The local
union can still be large for a large locked assembly, although it replaces the
former repeated world-space reconstruction and is discarded at the end of the
filter call. This change removes one identified hotspot; it does not establish
that a target-parts-300 conversion is feasible or resolve any other bottleneck.
