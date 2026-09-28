# Plan: running a settled protocol without presses (2026-09-28)

Branch `codex/operator-named-views-simulator`. Thom's ask, in his words, is the authority; the
"How it is built" part is the proposal and is open to review.

## What the operator sees

**Two colours on the rail.** A step's point is green when its settings have been confirmed for
this sample, orange when they were set once but not confirmed since something before them
changed. Grey stays grey (not done yet). There is no fourth colour.

**One rule for orange.** Redoing a step — editing its settings or running it again — makes it
green and turns every step after it orange, since they were made from what it was before. Change the tile set in
Define scan area and Focus strategy through Acquire targets go orange; touch the carrier and
Define scan area goes orange as well. The step you edited stays green: you just settled it.

**Confirm settings.** A orange step shows a orange press "Confirm settings" at the right of
its box. Pressing it turns the point green and changes nothing else. Running the step again
(Run focus map, Scan the overview, …) also counts as confirming it, since a fresh result was made
with the settings as they are.

**Step 10 — Run protocol.** A tenth step on the rail, reachable like any other once the
steps before it are done. Its box holds one press "Accept all current settings", which turns
every orange step green at once for the operator who has looked and agrees, and the step's own
press, "Run protocol". That press is greyed while any step is orange and says which:
"confirm Focus strategy, Discover targets first". When 1–9 are all green it runs Focus strategy
through Acquire targets in order, exactly as pressing each step's press would, on the whole scan
area, with no stop between steps. While it runs, the press reads "Interrupt" as today;
interrupting stops after the field in hand and ends the whole run; the interrupted step is
orange (Thom, 2026-09-28: it did part of its work, and asks to be confirmed or run again) and
everything after it is untouched. No pause, no resume. Nothing new goes in the toolbar.

**Following the run.** While Run protocol works, the rail and the page move with it: the step
being run is the active one, its box is on screen with its progress (the scan's tiles landing,
the detection's counts, the gallery filling) exactly as when it is pressed by hand, and every
press and setting in it is greyed out. The canvas stays alive and the operator's: the
overview fills as tiles land, masks and acquired pairs appear, panning, zooming, channels and
the acquisition eyes all work, the view follows the stage as it does today and a hand on the
canvas takes over. Only the step's settings and presses are greyed; Interrupt is live. When the
step finishes the run moves to the next one.

**The protocol.** Every run writes its settings — carrier, scan area, focus strategy and preset,
overview job, detection settings, gates, target scan area, target job, target focussing — to one
file in the experiment folder, `protocol.json`, when Step 10 finishes. No images, no results.

**Loading one.** Under the Connect box a second box, "Protocol", with two choices: *New
protocol* (today's behaviour) and *Existing protocol*, with the list of protocol files found
under the output root, newest first. Choosing one fills every step's settings. Connect is
green; Define carrier through Run protocol are orange (Thom, 2026-09-28: the carrier's corners in
the file are last mount's stage readings, so it is re-snapped on this sample, and the scan area
sits on the carrier). Each of 2–9 is confirmed or run on this sample before the run may go.

**The test subset, in Step 5.** Scan the overview shows the scan area's tiles in blue. Clicking a
tile turns it green; a press "Select N random" (N typed beside it) picks N tiles by systematic
uniform random sampling along the Z-curve the page already orders tiles by. The scan runs on the
green tiles only, and steps 6–9 work on what was scanned: detection, gating, the target scan
area and the target acquisition all see the subset. That is the rehearsal of the protocol on this
sample. With no tile green the scan takes the whole area, as today.

**Step 10 runs everything.** Run protocol takes the whole scan area, every tile, from Focus
strategy onward, including the tiles that were tested; the press says only "Run protocol".

**An existing protocol** carries last time's test tiles; they come up green in Step 5 and can be
changed before the step is confirmed.

**The second run, as Thom walked it (2026-09-28).** Mount the sample, Connect, pick the protocol:
1 green, 2–10 orange; re-snap the carrier, confirm the area. Measure the coarse focus map on this sample, by hand in Step 4 or as the
first act of Run protocol. Then either test the subset again in Step 5 and look at what 6, 7, 8
and 9 make of it, or press Accept all current settings; Run protocol acquires.

**To confirm with Thom.** The protocol list is read from the output root, which the page knows
only after connecting: so the order in Step 1 is connect, then choose the protocol.

## How it is built (rewritten 2026-09-28 after two reviews)

Reviews: `PLAN_AUTOMATION_2026-09-28_REVIEW.md` (Claude subagent, 20 findings) and
`C:\Users\t.de\PLAN_AUTOMATION_2026-09-28_REVIEW_FOR_FABLE.md` (Codex, 10 findings). Both are input,
not direction; every claim this section rests on was checked against the code on 2026-09-28:
`runStep` returns nothing (main.js:674-685), detection empties `gates`/`gated` (846-858), the
rail click calls `carrierSettled`/`scanfieldsSettled` (541-543), gate and lever edits do
`done.delete("select")` (1547, 1778), the bridge numbers fields by their place in the list sent
(bridge.py:1529-1530) and the page reads them through `state.plan[field]` (main.js:1525), and
`_start_scan` deletes the stores of tiles it was not sent (bridge.py:1450-1454).

The page keeps one `state` object in `framework/window/main.js` and every step's settings are
already fields on it. The work is: one mark for "not confirmed", one hook every edit goes
through, results that remember the geometry they were made with, a run that can be awaited, and
a settings-only file.

1. **`state.stale`, a `Set` beside `state.done`.** Green = done and not stale; orange = done and
   stale; grey = not done. The seven places that add to `done` today stay as they are. In
   `style.css`, `.step.stale .step-n` uses the existing `--warn-ink` token, both themes. Two pure
   functions in `framework/rules/steps.js`, unit-tested: `editedAt(steps, done, stale, id)` gives
   the stale set with every done step after `id` added; `staleSteps(steps, done, stale)` gives
   the stale ids in rail order. `blockedBecause` keeps its signature; Step 10's `ready` calls
   `staleSteps` on the state it is handed.

2. **One hook, `stateEdited(stepId)`,** owned by the shell: applies `editedAt`, keeps the edited
   step green, re-renders. Called from the edit callbacks and from nowhere else; never from
   `carrierSettled`, `scanfieldsSettled`, `focusSettled` or the rail click, which are navigation.
   Call sites: carrier `onChange` and the anchor `snap`/`suggest`/`forget`; the carrier layer's
   drag; scanfields `onChange`; preset `changed`/`activated` for all four slots; every focus-point
   edit in `focus-map.js` (place, delete, lay, nudge, clear, drag, `perField`/`perCarrier`,
   metric); the detection settings in `detection.js`; the gate commit; `setRule` for the placing
   levers; the target-focus toggle; the test-tile edits. The two `done.delete("select")` paths
   (gate commit, `setRule`) become `stateEdited("gate")` / `stateEdited("select")`: gates and
   levers are definitions that survive, so the step is stale, not undone. `confirm(id)` is
   `stale.delete(id)`. `finish()` deletes its step from `stale` and calls `stateEdited` for it,
   except inside Step 10's sequence, where nothing is staled.

3. **Results keep the geometry they were captured with.** New `state.scanned = { plan: [the
   tiles as sent], fields: [plan index of each] }`, set when a scan lands, `null` before.
   Everything that today reads a result through `state.plan[field]` reads
   `state.scanned.plan[field]` instead: `fieldLabels`, `tilesetOfField`, the gallery's
   `state.plan[cell.field]`, the discover_targets and scan_the_overview layers, the progress
   notes' `plan.length`, `tryOn` and the detection panel's Tile arrows. The bridge's field index
   (place in the sent list) is then the page's field index too, with no map to carry around.
   Editing the scan area after a scan changes `state.plan` and stales 5-10 while the pictures on
   screen stay where they were taken; that is what lets `scanfieldsLocked` and `focusLocked` go.
   Hand presses are NOT blocked by an orange step above them (the subagent proposed it, Codex
   objected; the pictures no longer lie, and a scan after Forget on the focus map drives at the
   standing height and says so in its summary, as today).

4. **The subset is the same mechanism.** The scan sends the green tiles' positions and
   `state.scanned` records which plan tiles they were; Step 10 sends the whole plan. The bridge
   needs nothing for indexing. Its deleting the stores of tiles it was not sent stays: the
   overview is the latest scan, whole or subset. "Select N random" is
   `sursDraw(state.plan.map((t, i) => ({ id: i, x: t.x, y: t.y })), n)`; the tile click reuses
   the stage's frame hit-test. Test tiles are plan indices stored with the plan's tile count;
   a plan change clears them.

5. **`runStep` returns a promise** resolving `{ outcome: "finished" | "stopped" | "failed",
   failed?: n }`; each branch's terminal `finish` / `stoppedShort` / `itFailed` resolves it, the
   `setTimeout` fall-through too. Detection's finish with failed fields resolves `finished` with
   the count so Step 10 can say so and go on.

6. **Step 10 is a channel step,** `steps/run_protocol/step.js` (`id: "protocol"`, `title` and
   `btn` "Run protocol", `mode: "protocol"`, `channel: { id, label, mount }` as the framework
   already allows), appended in `the-run.js`; `steps.test.js`'s step-list assertion updated. Its
   box holds "Accept all current settings" (`stale.clear()`) and the run. The run sets
   `state.protocol = { running: true, interrupted: false }`, then for focus, scan, detect, gate,
   select, targets in turn: `activeIdx` to the step, `await runStep(...)`, stop on anything but
   `finished` or on the latch. `gate` is not a press: the sequence sets
   `gated = cellsInAllGates(cells, gates)` (gating.js, already imported and unused in main.js)
   and marks `gate` done. Gates on `pca_`/`umap_` columns cannot be reapplied (Thom,
   2026-09-28: the axes are fitted to the population at hand, UMAP is random per run), so the
   "Complex feature dimensions" box in Step 7 is greyed out (ticks and Compute disabled, a
   "not available yet" line), its columns never reach the axis pickers, and the protocol carries
   no such gate. The bridge routes and the population workflow stay as they are. Interrupt is
   protocol-owned: while the protocol runs, every active step's box shows one Interrupt press
   that latches `interrupted` and forwards to the running operation's brake when there is one
   (scan, detect, targets, focus); a step without a brake ends at its next look at the latch. An
   interrupted step is added to `done` and to `stale` in `stoppedShort` (orange); a failed step
   stays as it was; the steps after are untouched.
   Finishing writes the protocol.

7. **Busy guard.** `state.busy()` = a step running or the protocol running. Every mutation
   handler checks it, the canvas editors included (the focus trace's pointer handler, carrier
   drag, focus-point placement, tile clicks); viewing never does. The focus panel's own Rerun /
   Run new points go through `runStep(indexOfStep("focus"))` so they count as running the step.

8. **The protocol file,** `framework/window/protocol.js`. `protocolFrom(state)` gives
   `{ version: 1, session: { microscope, api, configuration }, carrier, anchors: [{x, y}],
   fields, overviewPreset, focusPreset, focus: { strategy, metric, points: [{x, y}], perField,
   perCarrier, zFixed }, detect: settings only, gates (measured features only; a gate on a `pca_`/`umap_` axis is not carried), placing,
   targetType, targetFocusOn, targetFocus, testTiles: { tiles, of } }`; recordings as `{ changeable, frameUm }` from
   `withRecording`. No `gated`, no measured heights, no test results, no UI fields, no `Set`s.
   `applyProtocol(state, json)` rebuilds derived state (`newFocus()` then the points,
   `newDetect()` then the settings, `gates` with `gated` empty) and is tested as a real JSON
   write and read into a fresh `state`. A protocol from another instrument is refused by
   `session`. Bridge: `POST /api/protocol` writes `protocol.json` into the experiment folder;
   `GET /api/protocols` lists `*/protocol.json` under the connected session's output root
   (`get_info()["output_root"]`, cached at connect), newest first, each with its folder hash,
   mtime and the JSON inline. No third route.

9. **The Protocol box** sits under the Connected card in `session-card.js`, so it appears after
   Connect and applies on choice: *New protocol* / *Existing protocol* with the list. Choosing
   one calls `applyProtocol`, sets `done` and `stale` for 2-10, and refreshes every mounted
   control.

10. **Tests, first.** `steps.test.js`: `editedAt`, `staleSteps`, the tenth step in the list.
    `protocol.test.js`: JSON write and read into a fresh state. `runStep` outcomes in a unit
    test. `operator-page.spec.js` gains one walk on the mock: hand run with three test tiles,
    change the tile set, 5-10 orange, Accept all, Run protocol, the rail follows, the canvas
    answers a pan mid-run, `protocol.json` written; reconnect, choose it, 1 green, 2-10
    orange, the test tiles green in Step 5.

Not in this change: pause/resume (dropped), protocol files outside the output root, keeping a
full scan's pictures through a later subset test.

## Decided by Thom, 2026-09-28

- After loading a protocol: 1 green, 2–10 orange. Re-snap the carrier on this sample.
- An interrupted step is orange.
- Gates on PCA or UMAP axes are not automatable. The "Complex feature dimensions" box (PCA and
  UMAP ticks, Compute) is greyed out for now, with "not available yet" on it; the code stays.
- A subset test after a full scan drops the full scan's pictures, as any new scan does today;
  Step 10 rescans everything. (Not raised as a problem; noted.)

## Review prompt (Codex, before building)

You are reviewing a plan before it is built, on branch `codex/operator-named-views-simulator` of
this repository. Read `application/PLAN_AUTOMATION_2026-09-28.md` in full first. Its "What the
operator sees" part records the operator's decisions from a walk-through on 2026-09-28 and is not
under review; the "How it is built" part is the proposal and is.

Context: the operator page is one shell, `application/framework/window/main.js`, holding one
`state` object (fields at ~225–300, `resetRun` ~471, `renderRail` ~512, `runStep` and its
`finish()` ~600–1130, `setSlot` ~1248, `carrierSettled` ~1256, `focusLocked` ~1332, the gate
commit ~1541, `scanfieldsLocked` ~2009, `scanfieldsSettled` ~2359). Steps are descriptors in
`application/workflows/target_acquisition/steps/*/step.js`, composed in `the-run.js`; the pure
rules (numbering, reachability, `ready`) are in `application/framework/rules/steps.js`. The
Connect box is `steps/connect/session-card.js`. The scan's page side is
`steps/scan_the_overview/{step.js,live-bridge.js,layers.js}`; `sursDraw` is in
`steps/refine_targets/gating.js`. The bridge is `application/framework/bridge.py`
(`_scan_worker` ~996, `/api/scan` ~2003 and ~2069, targets discover ~1521); it persists images
and records under the experiment folder and today nothing of the page's settings. The line
numbers are from 2026-09-28 and may drift.

Questions: (1) Does removing `scanfieldsLocked` / `focusLocked` in favour of the orange mark
leave any result on screen that lies about the settings it was made with? Name the path. (2) Is
`state.confirmed` beside `state.done` the smallest clean representation, or should `done` become
a map of `{done, confirmed}`? (3) Are there settings written to `state` outside the listed call
sites, so `editedAt` would miss an edit? List them. (4) Is `protocolFrom(state)` complete: any
setting a step reads that is not in the list? (5) Anything about Step 10 as a sequence of
today's `runStep` calls that would not survive the stop path or a failure mid-sequence?
(6) Is anything in "How it is built" wrong about the code as it is today — a function, field or
route that does not exist or does not do what the plan says? (7) Does the operator-facing part
contain a contradiction or a gap an implementer would have to guess at? (8) What is the
smallest clean design that still satisfies the operator-facing part; is any proposed mechanism
more than needed?

Report findings only, ranked by severity, each with file:line evidence and a one-line proposed
fix. No praise, no summary of the plan. Do not edit any file.
