# Plan: the details after the first Run protocol (2026-09-28, evening)

Thom's list from trying the first build in the window, with how each is built. Builds on
`PLAN_AUTOMATION_2026-09-28.md` and `PROTOCOL_2026-09-28.md`.

## What the operator sees

1. **Focus map kept.** Run protocol measures the focus map only when none has been measured on
   this sample; otherwise it starts at the scan. (Built; to be re-walked.)
2. **Grey until reached.** While the protocol runs, the steps it has not reached yet are grey, the
   one in hand spins, the ones it finished are green. An interrupted run leaves the step in hand
   orange and the unreached ones grey, so the rail says exactly how far it got.
3. **Progress in Step 10.** A bar in the Run protocol box: "step 3 of 5 · Scan the overview ·
   field 4 of 9", the bar filled by steps done plus the fraction of the step in hand.
4. **No "Run again".** After a finished run Step 10 shows the result, not a press. Running the
   protocol again is: edit something (it goes orange below), confirm, Run protocol.
5. **At the end:** a small table under the result -- tiles scanned, objects found, objects gated,
   targets acquired, time taken -- and a short, tasteful confetti burst inside the box (a few
   dozen small pieces in the page's own colours, ~1.5 s, then still), with a small "again" press
   beside it. Respects the system's reduced-motion setting. A stopped run shows the table with
   "stopped at Scan the overview" and no confetti.
6. **Test tiles filled green**, the whole tile, as the plan's tiles are filled blue. A scanned
   test tile shows its pixels (the fill is under the picture); an unscanned one is solid green.
7. **Amber, not red-orange**, for the unconfirmed badge and the Confirm press: `#d97706` on
   light, `#f59e0b` on dark.
8. **Shift-select in Step 5.** Shift-drag a rectangle on the picture: every tile inside turns
   green (Shift-drag over green tiles turns them off again -- the drag sets them all to the
   opposite of the first tile pressed). Shift-click adds or removes one. Plain click toggles one,
   as now. A plain drag still pans.

9. **Target Z offset.** Its own white box in Step 9, under "Target focussing settings": one
   number, "Z offset" in µm, added on top of whatever height a target would be taken at -- the
   focus map's height, or the peak of its own focussing stack when target focussing is on. A
   setting, carried in the protocol; editing it is an edit of Step 9.

## How it is built

- (2) `runProtocol` takes the reached-so-far steps out of `done` before the walk
  (`state.done.delete` for each protocol step not yet reached, `stale` too) and each step's
  `finish()` puts its own back, as it does now. `renderRail` needs nothing. The step results
  themselves are not cleared: the cells and pictures stay on the canvas until the step in hand
  replaces them, which is what the operator watches.
- (3) `state.protocol` gains `{ at, of, within: { done, of } }`; the sequence sets `at`/`of`
  (skipped steps excluded), the scan/detect/targets `onProgress` handlers set `within` when the
  protocol is running. `protocolMount` draws a `progressBox` (the one the scan and the gallery
  use) and the sequence re-renders it through `renderActionBar`.
- (4) `renderStepAction`: for `mode: "protocol"` after `done`, no press; the box shows the result.
- (5) `runProtocol` records `startedAt` and, at the end, `state.protocol.summary = { tiles,
  objects, gated, targets, seconds, ended }` from `state.scanned.plan.length`, `cells.size`,
  `gated.size`, `acquired.length`. `protocolMount` draws the table and, on `ended === "finished"`,
  a small `<canvas>` with `confetti.js` (new, `framework/window/confetti.js`, ~60 lines: pieces
  with position, velocity, spin, colour from `--accent`, `--good`, `--warn-ink`, `--mark-selected`;
  `requestAnimationFrame` until every piece has fallen out of the box) and an "again" press.
  Reduced motion: the table only.
- (6) `scan_the_overview/layers.js`: the `testTiles` layer moves back below `"picture"` in
  `THE_STACK` and fills (`--good`, alpha 0.35) with a 2 px edge; the hover outline stays above.
  The walk's grey check already compares grey against colour.
- (7) `style.css`: a `--confirm-ink` token, light `#d97706` / dark `#f59e0b`, used by
  `.step.stale .step-n` and `button.run.confirm`; `--warn-ink` stays what it was for warnings.
- (8) `shared/stage.js`: on the scan step, a drag with Shift held is claimed as a marquee (the
  focus step's marquee drawing reused: `focusMarqueeTo` is step 4's; a small `tileMarquee` of the
  same shape lives with the scan layer), tiles whose centre falls inside are set together;
  Shift-click toggles one without the marquee. `ctx.testTilesChanged` as now.
- (9) `state.targetZOffsetUm` (default 0), a `sideGroup("Target Z offset")` in
  `acquire_targets/gallery.js` after the focussing box with a number input; `positionFor` in the
  targets branch adds it to `z` when there is a surface, and the bridge's target run adds it to
  the peak when it drives to one (`_target_landed`/the page's loop passes `z_offset_um`);
  `protocolFrom`/`applyProtocol` carry it; `stateEdited("acquire")` on change.
- Tests: `steps.test.js` unchanged; a unit test for the marquee's tile picking (pure: tiles in a
  rectangle) in `scan_the_overview/test-tiles.test.js`; `walk.spec.js`: during Run protocol assert
  the unreached steps carry no `done`, the progress line reads "step … of …", the finished box has
  the table and no `.step-run` press, and the focus map was not re-measured (the bridge's focus
  ledger count unchanged); a Shift-drag over two tiles turns both green.

## What we might have missed

- **Named protocols.** The Step 1 list shows date and run hash. A name typed at the end of the
  run (a box in Step 10 with "Save as") would make the list readable. Open: yes or no.
- **After Run protocol, the test tiles stay green** (the protocol carries them). Fine for the next
  sample; on this one the next hand scan would take only those tiles again. Say if a finished
  protocol run should clear them.
- **Interrupt mid-detection** leaves the objects found so far; the gate step after it is not
  reached (grey). Consistent with 2.
- **Run protocol on a run where the target job was never imported** stops at Target scan area
  with its reason ("record the target settings first") -- the press is greyed before that only
  by orange steps, not by missing settings. Should Step 10's press also wait on every step's own
  readiness, so it cannot start a run that will stop at step 8? I recommend yes: one more line in
  `ready`.
- **The Leica**: the protocol run drives the same calls the presses do; per-target job switching
  is still the open rig check.
