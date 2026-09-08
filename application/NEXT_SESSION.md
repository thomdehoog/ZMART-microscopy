# Next session

Written 2026-09-08 at the end of the day.

Branch `claude/smart-operator-workflow-review-ehw3c5`, worktree
`C:\ProgramData\MinicondaZMB\home\t.de\zmart-operator-review`. Last pushed
`854874c4` (2026-09-08). Launch: `npm run dev` in `application/`, then
`python zmart-interface.py` (bridge lives inside the window process, so
restarting the window restarts the backend). Notes in `application/`:
`BLACK_TILE.md`, `ABSOLUTE_Z_PLAN.md`, `FOCUS_INTERRUPT.md`.

**Done:** position stores are written in absolute stage z with a positive
spacing whichever way a focus stack was swept (`zarr_positions.py`
`_the_z_model`); the engine opens at the lowest plane; mock can sweep
top-down (`ZMART_MOCK_FOCUS_SWEEP=down`). Fixed the black overview tile.

**Pick up first — last tile stays thin.** In
`viz_studio/options/neuroglancer-under/viewer.js`,
`countFromTheCornerOfTheVoxelRatherThanItsMiddle` makes a flat source a
metre thick along its local `z'` (`A_FLAT_PICTURES_THICKNESS`). On the real
four-tile run, three sources thicken and the last-loaded one does not
(`isOnePlaneDeep` came back false for it in one pass; a later pass never
fixed it). Reproduce with a harness page under `application/` that calls
`openViewer` on one acquisition with 4 `sources` per channel (the four
`overview_K00_M000027_*` stores under `E:\Experiments\ZMART-microscopy\`,
z 30-32 um), served with a CORS `http.server`, and read
`viewer.layersForMeasurement()` source bounds (upper-lower on z ~2e6 when
thick). Suspects: `source.changed` never firing, or `correctedLoadStates`
marking the source before its extent is read.

**Then:**
- Driver stamps focus planes with z ~ -5800 um while the stage says ~7 um:
  two frames. Settle in `zmart_drivers/leica/.../navigator_expert`, not the
  writer. Until then a stack and a flat tile at the same place do not line
  up in z (picture still draws).
- Focus Interrupt cannot land on a one-point map (flag read only between
  points); plan in `FOCUS_INTERRUPT.md` is to make the page orchestrate
  point by point. Not started.
- Disconnect deliberately wipes display settings
  (`watching-the-run.js` `closePicture({ forgetVisibility: true })`); user
  wants them kept. One-flag change, not done.
- `the-operator-walk.spec.js` last assertion is a knife-edge (43 px vs 40),
  flaky either sweep direction, predates the change.
- Uncommitted on purpose: `framework/window/static/index.html` (built page)
  and `application/setup-pictures/`.
