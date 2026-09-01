# Smart Viewer-inspired panel UX evidence

This directory is the separate Package H visual record. The reference capture
runs the production Smart Viewer 0.2 frontend and API from commit `9ff10b0`.
The Operator captures use the real Viewer's `/api/measure` result while an
isolated engine-adapter fixture makes requested and observed group/channel state
deterministic and lets the test compare every source matrix before and after UI
actions.

This evidence proves the histogram and panel presentation/state gates. It does
not pretend that the fixture is kidney-pixel or physical-coordinate evidence.
Those gates remain covered by the accepted real-mock records in
`../2026-09-01-smart-viewer-step-five/`, including 0/3/6/9, whole-plate,
overview-only, and kidney close-up.

The reference page's `/.zarray` 404 is explicitly allowed: it is the expected
format probe before the Zarr v2 group is opened. No other failed request,
browser exception, or console error was accepted.
