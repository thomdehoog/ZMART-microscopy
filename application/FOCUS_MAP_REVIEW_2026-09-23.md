# Focus map review, 2026-09-23

A review of how the focus map is laid out, fitted and used, for 1 to 7 points. Nothing here is fixed yet.

## Verdict

The fitting maths is sound. The page's thin-plate spline (`parts/microscope/pretend-sample/surface.js`) gives
the same heights as the Python one (`steps/focus_strategy/focus_surface.py`, scipy `RBFInterpolator`, kernel
`thin_plate_spline`, smoothing 0.1, coordinates centred and scaled to order one), which is the design of May
(`aedbe7a8`, "focus: hybrid model selection + TPS for 4+ points"). Measured on 4, 5 and 7 points, including a
place outside the points: the two agree to 1e-15 µm.

What makes the map wrong is where the page puts the points: on a long area it lays them in one line, and a
map from points in a line knows nothing about the tilt across it.

## Model by point count

| Points | Model | Note |
| --- | --- | --- |
| 1, or all heights within 0.1 µm | constant | the mean height |
| 2, or any number in one line | plane | tilted along the line, flat across it |
| 3 not in a line | plane | exact through the three |
| 4 or more not in a line | thin-plate spline | smoothing 0.1 |

Points whose stack found no tissue are left out of the fit. Two points at the same place do not break it.

## Measured

A 10 × 5 mm area of 200 fields; the points laid by the page's own placement (`sharePoints`); a known sample
surface plus 0.5 µm of noise on each focus measurement; the map compared with the truth at every field,
mean of 200 trials. Tilted slide: 12 µm across x, 6 µm across y.

| Points | Model | Laid out as | Error, typical / worst |
| --- | --- | --- | --- |
| 1 | constant | centre | 3.9 / 8.8 µm |
| 2 | plane | a row | 1.8 / 3.5 µm |
| 3 | plane | **a row** | 1.8 / 3.3 µm |
| 4 | plane | **a row** | 1.8 / 3.3 µm |
| 5 | spline | spread | 0.45 / 1.0 µm |
| 6 | spline | spread | 0.42 / 1.0 µm |
| 7 | spline | spread | 0.39 / 0.9 µm |

The same 3 points as a triangle: 0.49 / 1.0 µm. The same 4 as a 2 × 2: 0.47 / 1.1 µm.

Spline against a plane through the same 5 to 7 points:

| Sample | Spline | Plane |
| --- | --- | --- |
| Tilted slide | 0.45 µm | 0.38 µm |
| Slide with a 3 µm bow | 1.05 µm | 1.36 µm |

The spline chases a little noise on a flat tilt and earns it back on a bow: neither overfitted nor
underfitted. The worst errors sit at the corners, outside the area the points span.

Where the page lays 1 to 7 points:

| Area | In one line |
| --- | --- |
| Square, 10 × 10 fields | never |
| Well, 6 × 6 fields | never |
| Long, 20 × 10 fields | 3 and 4 points |
| Strip, 30 × 3 fields | every count |

## Findings

1. **Points in a line.** `sharePoints` (`workflows/target_acquisition/shared/scanfields.js`) picks the row
   count that covers the ground most evenly. That answers "which point stands nearest every field", but a
   plane needs spread in both directions. On a long area 3 and 4 points buy nothing over 2.
2. **"Exact fit" is claimed where the map cannot know the tilt.** `focusFitWord` in `main.js` says it for 2
   points, or 3 in a line.
3. **The spline's "rms" is always near zero.** With 4 to 7 points the smoothing leaves no residual, so the
   label reads as confidence it has not earned. `looErrors` in `surface.js`, which predicts each point from
   the others, exists for exactly this but the page never calls it.
4. **Lost from May.** The May version named the in-a-row case a "line", and warned when positions lay outside
   the points' bounding box, whose heights are extrapolated. The page has neither.
5. **Stale header.** `surface.js` names the Python copy as the authority, at a path that no longer exists. The
   page uses only the JavaScript fit; the Python one serves the old notebook widgets.

## Recommended fix, in this order

1. Placement: from 3 points on, never lay them all in one line unless the area itself is a single row.
2. Labels: bring back "line" for points in a line; drop "exact fit" where the map cannot know the tilt; say
   the leave-one-out error for a spline rather than its near-zero residual.
3. Bring back the warning when positions lie outside the points.
4. Correct the header of `surface.js`.

Each change gets a test that pins the layouts and the error figures above.

## Still to learn from the rig

What looked off there: how many points, what shape of area, and whether the heights were wrong everywhere or
only at the edges. Three or four automatic points on a long area, or any on a strip, is explained by
finding 1.
