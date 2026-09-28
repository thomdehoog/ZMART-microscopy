# Review of PLAN_AUTOMATION_2026-09-28 (Claude subagent, 2026-09-28)

Findings only, ranked. Line numbers are of the branch on 2026-09-28.

## Critical

1. **Step 10 cannot run detect → gate → select as a sequence of today's `runStep` calls.**
   `main.js:854-856` — `runStep(detect)` sets `state.gates = []; state.gated = new Set()`. Step 7
   (`gate`) has no press; it is done only via `setGates` (main.js:1538-1550), the gating panel's
   commit. Step 8's `ready` then fails with "nothing gated yet". Also `gated` is a set of cell ids
   minted anew per detection (`fieldFound` main.js:108) — meaningless in a file.
   Fix: the protocol stores `gates` (the polygons), not `gated`; Step 10 re-derives
   `gated = cellsInAllGates(cells, gates)` (gating.js:64, imported at main.js:23, unused) after
   detect and marks `gate` done itself. Gates on PCA/UMAP columns need `computePlot` first
   (main.js:1557-1568): the sequence must run it or the plan must exclude such gates.

2. **`runStep` returns nothing to await.** main.js:674 — every branch returns undefined before
   `finish`/`stoppedShort`/`itFailed` (757, 828, 845, 915, 1058); the fall-through is a
   `setTimeout` (1120). Nothing tells a caller finished / stopped / failed.
   Fix: `runStep` returns a promise resolving `{finished|stopped|failed}`; Step 10 awaits and
   stops on anything but `finished`. As written the stop path ends nothing.

3. **A subset scan breaks every by-index link between plan and results.** The bridge indexes
   fields by position in the SENT list (bridge.py:1530, 1554); the page by position in
   `state.plan` (`fieldLabels[i]` main.js:813, `tilesetOfField` 1526, gallery 1612,
   discover_targets/layers.js:216/273/349, scan_the_overview/layers.js:23, progress notes 691,
   762, 783-786, 1091). With only green tiles sent, bridge field 3 is plan tile k≠3: wrong
   pictures, wrong tileset ceiling, wrong lit frames, "5 / 40 tiles".
   Also `_replace_the_acquisition` (bridge.py:1451-1454) deletes the stores of every tile not in
   the new run — a subset scan after a full scan destroys the full scan's pictures on disk.
   Fix: send `planned: state.plan` (live.js:385-387, bridge.py:1458 accept it) plus a
   `position_index` per sent position, or hold `scannedFields: number[]` on the page and
   translate `field` through it everywhere it is used.

4. **Hooking `editedAt` into `carrierSettled`/`scanfieldsSettled`/`focusSettled` oranges later
   steps on a mere click.** main.js:543-544 — clicking the rail entry for Step 2/3 calls the
   settle functions; 1383-1388 `showTheRest` calls `focusSettled()` on every mount; 2241/2246 on
   preset changed/activated.
   Fix: call `editedAt` only from the edit callbacks — carrier `onChange` (2180), anchors
   `snap`/`suggest`/`forget` (2113, 2131, 2143), scanfields `onChange` (2277), preset
   `changed`/`activated` (2232, 2244) — never from the settle functions.

## High

5. **Settings written to `state` outside the listed call sites.** Focus points placed/deleted/
   laid/nudged/cleared/dragged in focus-map.js (686, 955, 1692-1708, 1679-1687, 1640-1650,
   1713-1728, main.js:2684), `perField`/`perCarrier` (1653-1665); the focus panel's own Rerun /
   Run-new presses (1737, 1774) bypass `runStep`/`finish` — a fresh measurement there would not
   count as confirming. Detection settings written directly by detection.js:103, 452, 488, 519.
   Anchors by focus-map.js:705 and define_carrier/layers.js:80. `targetType` via
   `selectionMount.changed` (1782), `targetFocus` via gallery `changed` (1632). `setRule` (1773)
   already does `done.delete("select")` — invalidates rather than stales.
   Fix: one `stateEdited(stepId)` hook the panels' `changed` callbacks call, not an enumeration.

6. **`focus.applied` is a result but decides behaviour; removing `focusLocked` lets Forget reset
   it and the next scan images at the wrong heights.** main.js:1311-1320 → `surface: null` →
   `surfaceZAt` (768, 933) answers null → drives at the standing height (bridge.py:1028-1036).
   Nothing greys a hand press of Step 9 after editing Step 4.
   Fix: `blockedBecause` for scan/targets returns "confirm Focus strategy first" when a prior
   step is stale — the same rule Step 10 uses — or the locks' bug (comment 1996-2008) returns.

7. **`scanfieldsLocked` removal: editing the plan after a scan makes `state.plan` disagree with
   the pictures on disk.** Same by-index dependency as 3; moving/deleting a tileset renumbers
   later tiles; Step 9 stays reachable (`isReachable` reads only `done`, steps.js:60).
   Fix: snapshot the scanned plan (`state.scannedPlan`) and read results through it, or keep the
   lock for deleting/moving and lift it for adding. The plan must choose.

8. **Interrupt is not offered on Step 10.** main.js:604-609 picks the brake by the active step's
   `mode`; `mode: "protocol"` has none → "working…", disabled (636-639).
   Fix: `brake.protocol = () => brakeFor(state.runningSub)`; `state.running` = the sub-step id
   plus a `state.protocolRunning` boolean.

9. **The focus panel's own runs set `run.running = true`, not an id** (focus-map.js:1740,
   1788) and never mark done/confirmed. Fix: route them through `runStep(indexOfStep("focus"))`
   or a shared `focusRan()`.

## Medium

10. **Interrupt semantics contradict the orange definition.** `stoppedShort` (1125-1133) does
    not add to `done`; an interrupted step stays grey or as it was; "leaves that step orange" is
    a third meaning. Detection interrupted has already wiped gates (854).
    Fix: interrupted = not done (grey), drop the orange claim; or add done+stale in
    `stoppedShort` and say so.

11. **"Touch the carrier and Define scan area goes orange as well" vs the one rule.** `snap`
    (2143-2177) shifts cells and focus points, so 8-9 are stale too. Fix: delete the sentence.

12. **Existing protocol: Define carrier green "from the file" trusts last mount's registration.**
    `anchors[i].stage` (2159-2160) is this mounting's stage reading. Fix: load carrier shape and
    anchor positions, drop the stage snaps, make Step 2 orange — or say the file carries the
    registration and the operator re-snaps if the sample moved.

13. **`ready: ({ stale })` — `blockedBecause` is handed `state` (main.js:557); no `stale`, no
    `titles`.** Fix: `staleSteps(steps, done, stale)` in `rules/steps.js`; titles from `steps()`.

14. **"Z-curve the page already orders tiles by" is false.** `plan()` is row-major per field
    (scanfield-editor.js:233-288); the Z-curve exists only inside `sursDraw` (gating.js:103-118),
    which returns `c.id`s; plan tiles have no `id`. Fix:
    `sursDraw(state.plan.map((t, i) => ({ id: i, x: t.x, y: t.y })), n)`.

15. **`protocolFrom` completeness.** Missing: `focus.metric`, `focus.points` (x, y only),
    `perField`/`perCarrier`, `focus.zFixed`/`strategy`; `focusMaps` keyed by per-session
    recording id (only the active map is portable); `detect` must be picked (`tile`, `hovered`,
    `tested`, `tried`, mask UI fields are not settings); `placing` (307) is the target scan area's
    levers; `gates` not `gated`; `session.microscope/api/configuration` so a protocol from another
    instrument is refused; each recording's `changeable` + `frameUm` (recordings.js
    `withRecording`). `testTiles` are plan indices — store with the plan's tile count as a check.

16. **Protocol file listing.** `_output_root` is None for drivers that find their own root
    (bridge.py:504-508); the root is known inside `_connect` (540). `GET /api/protocols` must
    read `_session.get_info()["output_root"]` or cache it at connect. "Connect, then choose"
    contradicts item 5's "on Connect with an existing one chosen". The folder is
    `target-acquisition_<hash6>` (496-502, output.py:67-72) — no experiment name; list by mtime
    and hash. Fix: the Protocol box appears under the Connected card (session-card.js:177-188),
    applies on choose, not on connect.

17. **Step 10's box/press placement.** `renderStepAction` needs `.${s.id}-action` or
    `foot-${shown}` (580); `sideWidget` needs a `SIDE_WIDGETS` entry or `s.channel` (1804-1810);
    `steps.test.js:311` asserts the step list. Fix: give the step a `channel: {id, label, mount}`
    as the framework allows (1798-1803); update that test.

## Low

18. `--warn-ink` already exists (style.css:27, 88); no new token.
19. `state.locked` (684) is set and never read — not one of "the locks".
20. Detection `tryOn` (1483-1498) and the panel's Tile arrows (detection.js:488) cycle over
    `plan.length`; under a subset scan the test tile must be a scanned one.

## Q2 / Q8 — representation and the smallest design

Store the INVERSE: `state.stale: Set`, not `state.confirmed`. Every existing `done.add` site
(1071, 1256, 1321, 1544, 1879, 1990, 2359) would otherwise need a paired `confirmed.add`, and a
missed one renders orange forever; with `stale` nothing existing changes: `editedAt` adds later
done ids to `stale`, `confirm(id)` and `finish()` delete from it, protocol load adds 4–10.
`renderRail` adds class `stale` when `done && stale.has`.

More than needed: `state.runningAll` (sub-step id in `running` + one boolean suffices);
`GET /api/protocol?path=` (the list can carry the JSON inline); a second tile hit-test in
`scan_the_overview/layers.js` (frames layer + hit-testing exist in stage.js:987-1043).

Smallest design: `state.stale` + `editedAt`/`staleSteps` in `rules/steps.js`; one
`stateEdited(stepId)` hook called by the panels' existing `changed` callbacks; `runStep`
returning a promise; Step 10 as a `channel` step whose run is
`for (id of [...]) if ((await runStep(idx(id))).outcome !== "finished") break;` with `gate`
re-derived from stored `gates`; scan sends all plan positions with `planned`, subset via a
`scannedFields` map; protocol = `{version, session, carrier, anchors(xy), fields,
overviewPreset, focusPreset, focus:{metric, points(xy), perField, perCarrier}, detect(picked),
gates, placing, targetType, targetFocusOn, targetFocus, testTiles}`.
