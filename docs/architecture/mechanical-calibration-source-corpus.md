# Mechanical calibration source corpus

This is a source and diagnostic calibration record. It does not change the
fitter, `stud-connectivity-v1`, buildability, insertion, instructions, or any
part's production mechanical eligibility.

## Authoritative source set

The checked-in files are the minimum official LDraw dependency closure for the
ordinary calibration roots below. Existing primitives and subfiles are reused.
No unofficial or alternate variants were required.

| Catalogue ID | Official LDraw root | Classification | New root/subfiles | Existing shared dependencies |
| --- | --- | --- | --- | --- |
| 3001 | `3001` | official part | none (anchor) | existing source closure |
| 3002 | `3002` | official part | `parts/3002.dat`, `parts/s/3002s01.dat` | `stud.dat`, `stud4.dat`, `box5.dat` and their existing primitives |
| 3003 | `3003` | official part | `parts/3003.dat`, `parts/s/3003s01.dat`, `parts/s/3003s02.dat` | `stud.dat`, `stud4.dat`, `stug-2x2.dat`, `box3u2p.dat`, `box5.dat` and existing primitives |
| 3010 | `3010` | official part | `parts/3010.dat`, `parts/s/3010s01.dat`, `stug3-1x3.dat`, `box4t.dat` | `stug-1x4.dat`, `stud.dat`, `stud3.dat`, `box5.dat` and existing primitives |
| 3020 | `3020` | official part | `parts/3020.dat` | `stud.dat`, `stud4.dat`, `box5.dat` and existing primitives |
| 3021 | `3021` | official part | `parts/3021.dat` | `stud.dat`, `stud4.dat`, `box5.dat` and existing primitives |
| 3022 | `3022` | official part | `parts/3022.dat` | `stud.dat`, `stud4.dat`, `box5.dat` and existing primitives |
| 3023 | `3023b` | official part; `3023.dat` is an official moved-to alias | `parts/3023b.dat`, `parts/s/3023bs01.dat`, `stug-1x2.dat` | `stud.dat`, `stud3.dat`, `box4t.dat`, `box5.dat` and existing primitives |

## Connector evidence

All listed male studs are source-backed, canonical `+Z`, and on the standard
rectangular grid. All listed underside features are source-backed, canonical
`-Z`, and remain mechanically unevaluated.

| Part | Male studs | Full `stud4` rings | Small `stud3` tubes | Partial tubes / unresolved connector geometry |
| --- | --- | --- | --- | --- |
| 3001 | 8 at every `0.5`-centered 4 x 2 grid position, `z=3` | `(1,1,2.5)`, `(2,1,2.5)`, `(3,1,2.5)` | none | none recognized |
| 3002 | 6 at every 3 x 2 grid position, `z=3` | `(1,1,2.5)`, `(2,1,2.5)` | none | none recognized |
| 3003 | 4 at every 2 x 2 grid position, `z=3` | `(1,1,2.5)` | none | none recognized |
| 3010 | 4 at every 4 x 1 grid position, `z=3` | none | `(1,0.5,2.5)`, `(2,0.5,2.5)`, `(3,0.5,2.5)` | none recognized |
| 3020 | 8 at every 4 x 2 grid position, `z=1` | `(1,1,0.5)`, `(2,1,0.5)`, `(3,1,0.5)` | none | none recognized |
| 3021 | 6 at every 3 x 2 grid position, `z=1` | `(1,1,0.5)`, `(2,1,0.5)` | none | none recognized |
| 3022 | 4 at every 2 x 2 grid position, `z=1` | `(1,1,0.5)` | none | none recognized |
| 3023 | 2 at every 2 x 1 grid position, `z=1` | none | `(1,0.5,0.5)` | none recognized |

The generic extractor reported no partial `stud4` geometry for any ordinary
calibration root. Its output is deterministic and preserves the continuous
canonical coordinates above; no values are snapped.

## Comparison with current rectangular mechanics

Current rectangular mechanics treats the complete catalogue footprint as
receiving-capable: the expected receiver positions are the same half-centred
horizontal positions as the part's top-stud grid, on the underside plane. The
source full-ring/small-tube centers are interior structural features instead:
they are not at those half-centred positions and have `z=H-0.5`.

| Part | Expected receivers | Direct full-ring/small-tube matches | Misses | False positions |
| --- | ---: | ---: | ---: | ---: |
| 3001 | 8 | 0 | 8 | 3 |
| 3002 | 6 | 0 | 6 | 2 |
| 3003 | 4 | 0 | 4 | 1 |
| 3010 | 4 | 0 | 4 | 3 |
| 3020 | 8 | 0 | 8 | 3 |
| 3021 | 6 | 0 | 6 | 2 |
| 3022 | 4 | 0 | 4 | 1 |
| 3023 | 2 | 0 | 2 | 1 |

The exact mismatches are the full-ring/small-tube coordinates in the preceding
table: every expected receiver is missed, and every reported underside feature
is a false position under a direct-coordinate rule. Projecting the observed
top male-stud grid vertically to the underside reproduces the expected counts
for all eight parts, but it proves only top-stud geometry and does not prove a
receiving interface. It is therefore not a source-derived receiver rule.

## Pattern and decision

Two-wide bricks and plates share interior `stud4` rings; one-wide bricks and
plates share interior `stud3` tubes. The pattern is systematic across heights,
but it describes internal source structures, not the full rectangular
receiving footprint. Side/end walls and these features do not uniquely encode
all receiver positions.

**Decision: B. Hybrid.** LDraw remains valuable provenance and can automate
source evidence, but verified per-part connector metadata is required before
non-trivial vertical receiver mechanics can rely on it. A smallest future-only
shape is:

```yaml
mechanicalConnectors:
  topMaleStuds:
    - coordinate: [x, y, z]
      direction: +Z
      interfaceKind: stud
      evidence: verified
  undersideReceivers:
    - coordinate: [x, y, z]
      direction: -Z
      interfaceKind: stud_receiver
      evidence: verified
```

This is documentation only: no catalogue schema migration or wedge metadata is
introduced.

## Wedge and curved-slope diagnostics

41769 and 41770 both retain one full `stud4` feature at canonical `(3,1,0.5)`;
their partial tube/lip geometry does not resemble a complete calibrated
receiver footprint. 15068 has small underside tubes at `(1,0.5,2.5)` and
`(1,1.5,3.5)`, likewise not a calibrated rectangular receiver pattern. They
remain diagnostic and mechanically unevaluated.
