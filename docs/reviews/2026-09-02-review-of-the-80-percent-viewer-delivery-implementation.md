# Review of the 80% viewer-delivery implementation

**Date:** 2026-09-02.

**What was reviewed, as code:**

- ZMART-microscopy, branch `claude/viewer-delivery-to-100`, commit `ae40fb58`
  ("finish the compatibility half: M2 handshake, embedded waiting state, I1"),
  whose parent `b79fb46e` is Codex's correction of the 50% checkpoint.
- ZMART Viewer, branch `claude/viewer-delivery-to-100`, commit `02cf88d`
  ("name the display-window promises, and tell a declared window from a
  measured one"), whose parent `2b4338e` is Codex's correction; `9ff10b0` is
  the released 0.2.0.

**Read alongside:** `docs/design/viewer-delivery-implementation-plan-80-percent.md`,
the previous review (`docs/reviews/2026-09-01-review-of-the-50-percent-viewer-delivery-implementation.md`,
which lives on the branch `claude/review-50-percent-viewer-delivery` at
`bb5b6bfc` rather than on this branch), `docs/design/viewer-delivery-implementation-plan-50-percent.md`,
and `CLAUDE.md` in ZMART-microscopy. The Viewer has no `CLAUDE.md` at
`02cf88d`, so the microscopy one was applied to both.

**How it was reviewed:** each commit was checked out into its own worktree
under `/tmp` (`/tmp/review-m`, `/tmp/review-v`, and `/tmp/review-mp` for the
parent `b79fb46e`); neither working folder was touched. Tests were run in the
worktrees (section 6). Five small probes were written in a scratch folder to
check things the tests do not; they are described where they matter and were
not committed anywhere.

Throughout, an **observed** fact is one read in the code or produced by a test
run or probe named here. An **inference** is labelled as such.

---

## Verdict: accept with follow-up

The compatibility half is real. The handshake refuses an old Viewer and stops
it; the embedded panel has no camera-range fallback left and disables its
controls honestly; a declared window is now called declared; the four blockers
of the previous review are closed in the code, and the two regression cases
from that review are permanent Viewer tests that pass. The sidecar wins over a
position that disagrees with it, which is the property the whole migration is
for, and I checked it with a tampered first position rather than trusting the
test.

Nothing found here makes M3 unsafe in principle. But six small things need doing
before M3 is started, and one sentence in the 80% document is not true as
written: "corrections found while running everything" sits beside a package,
`zmart_live`, whose whole test suite has been red since Codex's parent commit,
for the very fault this checkpoint fixed in `zmart_storage/cropped.py`. The
follow-ups are small and named below; none of them needs a redesign.

---

## 1. Findings, by severity

There are no blocking findings. The important ones are things that would
mislead an operator or a maintainer; the minor ones are hardening.

### I1. A whole package's tests are red from Codex's parent, and this checkpoint did not notice

**Observed.** Running the microscopy Python suites at `ae40fb58` gives
`80 failed, 822 passed, 4 skipped, 15 errors`. Every one of the 95 failures
and errors is in `zmart_live/tests/`, and every one carries the same message:

```
ValueError: channel 'channel 0' has no display window; omit the whole omero block
```

raised by `zmart_storage/canvas.py:1055` (`Channel.described`, made to raise
in `b79fb46e`) through `zmart_live/omezarr.py:357`, which still calls
`named.described(brightest)` for every channel whether or not it has a
window. The same suites at the parent `b79fb46e` give `96 failed, 800 passed,
15 errors`: the same 95 in `zmart_live` plus the 16 in `test_cropped.py` that
the 80% document says it found and fixed. So the `cropped.py` fix is real, and
the identical fault one package over was not looked for.

**Observed.** No file outside `zmart_live/tests/` imports `zmart_live`
(searched `application/`, `zmart_storage/`, `zmart_controller/`). *Inference:*
it is a dormant package, so this is not a production fault today. It is still
a red suite that the checkpoint document describes as green, and the same
call pattern sits unguarded in `zmart_storage/positions.py:474`
(`channel_blocks=[one.described(depth_max) for one in self._channels]`),
which today happens to be given a window by every caller in its tests.

**What to do.** Give `zmart_live/omezarr.py` the same "omit the whole block
when any channel has no window" treatment as `TileCanvases` and `cropped.py`,
or delete the package if it is truly dormant; either way, say which in the
100% document. Guard `positions.py:474` the same way.

### I2. A malformed health answer leaves a Viewer running that nothing can stop; a refused Viewer keeps its socket

**Observed, by probe.** `viewer_service._what_the_viewer_cannot_promise`
(`application/parts/storage/viewer_service.py:148-166`) wraps the HTTP
request in `try`, but not the parsing: line 165 does `set(promised)`, and a
`capabilities` list whose members are not hashable (for example
`[{"name": "acquisition-display-window-v1"}]`) raises `TypeError` there. That
escapes to the outer `except Exception` in `start()` (line 144), which records
`"the viewer server did not start: unhashable type: 'dict'"` — while the
server thread started at line 127 goes on serving, `_viewer["server"]` is
never set, so `stop()` cannot reach it, and the next `start()` starts a second
one beside it. The probe confirmed the pretend Viewer still answered
`/api/health` after `status()` reported it not running.

**Observed, by probe.** On the refusal path (lines 130-142) the server is
`shutdown()` and its thread joined, but `server_close()` is never called, so
the listening socket stays open until the object is garbage-collected. After
a refusal, a plain TCP connect to the refused Viewer's port succeeds. The test
`test_a_refused_viewer_is_stopped_not_left_running`
(`test_viewer_service.py:93-108`) passes all the same, because a connection
the kernel accepts and nobody answers times out after two seconds, and a
timeout is an `OSError`, which the test accepts. The same omission pre-exists
in `stop()` at line 179.

*Inference:* the real Viewer will never send a dictionary in `capabilities`,
so the first case is unlikely in practice; but the handshake exists precisely
to be careful of Viewers that are not the one expected, and "unknown answer"
should not be the one shape that leaks a server.

**What to do.** Move the parse inside the `try` (an unparseable answer is "no
promise", as the docstring already says); on any exception after the thread
has started, shut the server that was started; and call `server_close()`
after `shutdown()` on both the refusal path and in `stop()`. Then make the
test connect and assert a refused connection, not a timeout.

### I3. The upgrade sentence can be lost once and is then never repeated; and every unreachable Viewer is called "too old"

**Observed.** In `watching-the-run.js:151-168`, `toldAbout = trouble` is set
whether or not `ctx.picture()?.tell?.()` had anything to tell. `ctx.picture()`
is `stage.picture` (`main.js:1720`), which is the engine handle
(`viewer.js:1567`), `null` until the canvas has finished opening. The canvas
is opened at page load (`stage.js:145`), asynchronously; if the bridge answers
with the refusal sentence before that open completes — or if the engine never
opens in that browser — the sentence is dropped and, because `toldAbout`
already equals it, never offered again while the reason stays the same.

*Inference:* on the ordinary path the canvas opens seconds before an operator
finishes connecting, so this needs an engine that failed to open, in which
case the canvas is blank for a different reason anyway. It is narrow, but it
is exactly a "viewer refused, canvas silent" path, and the fix is one line:
set `toldAbout` only after a successful `tell`.

**Observed, by probe.** `_what_the_viewer_cannot_promise` returns "missing
both" for any failure to fetch `/api/health`, including a timeout (a Viewer
that answered after six seconds was refused as "too old"). The operator is
then told to update a package that may simply have been slow, or unreachable
through a system HTTP proxy (`urllib` honours `http_proxy`; `_ask` has had the
same exposure since before this checkpoint). Separate "did not answer" from
"answered without the promises" in the sentence; both should still refuse.

### I4. Decision 4 says the two canvases "show the same words for the same state"; they do not, and the embedded panel cannot reach one of the states

**Observed.** The standalone `LayerPanel.jsx:872-873, 921-935` shows: "this
acquisition cannot be read" (with no reason) when `unreadable` and no window;
"waiting for measurable pixels" when there is no window; "brightness measured
from pixels acquired so far" when `provisional`; nothing when `settled` or
`declared`. The embedded `viewer-panel.js:760-788` shows: "waiting for
measurable pixels"; "this acquisition cannot be read: <reason>"; and
**nothing** for `provisional` — the state exists only as a
`data-brightness` attribute nobody reads. So a live run that is still being
written says "measured from pixels acquired so far" in the standalone Viewer
and says nothing in the operator page.

**Observed.** The embedded panel can never be `settled`. `/api/measure`'s
successful answer (`server.py:733-740`) carries only `window` and
`histogram`, so `viewer-panel.js:244`
(`body.measurementState === "settled" ? "settled" : "provisional"`) always
yields `provisional`. The test `viewer-panel-waiting.test.js:118-135` feeds
`measurementState: "provisional"` and `"settled"` inside a successful answer —
a shape the real route never sends — so it mirrors the panel's expectation
rather than the server's behaviour. (The empty-answer half of that test does
match the route exactly, and is good.)

**What to do.** Either the route says `measurementState` on success as well
(cheap: `measure_here` knows whether the coarsest level was read) and the
panel shows the provisional sentence, or decision 4 is reworded to what the
code does. Then make the stub in the vitest match `_serve_measurement`.

### I5. Publication depends on hard links, and only "already exists" is handled

**Observed.** `write_acquisition_description`
(`acquisition_description.py:272`) publishes with `os.link(temporary,
target)`, catching `FileExistsError` only. *Inference:* on a filesystem that
does not support hard links — exFAT or FAT32 removable media, some SMB
shares — this raises `OSError` from `_start_scan` before the scan starts. That
is loud rather than silent, which is the right way round, but the message is a
stack-derived one, and decision 1 does not state the filesystem requirement.
Either catch `OSError` and fall back to `os.replace` plus the same
compare-after-write, or write the requirement into decision 1.

### Minor observations

- **A corrupt description is described as an empty one.** By probe,
  `/api/measure` on a store whose `.zattrs` is `{ this is not json` answers
  `unreadable` with "the image description names no pixel levels", because
  `_read_attrs_at` swallows the decode error before `_readability_problem`
  (`contrast.py:216-238`) can name it. The state is right; the sentence hides
  the only fact that would help.
- **A wrong request is called "waiting".** By probe, a `box` outside the
  picture or a `channel` the store does not have makes `measure_here` return
  `None`, `_readability_problem` finds nothing wrong, and the route answers
  `waiting` (`server.py:717-731`). The panel then says "waiting for
  measurable pixels" for a request that will never be satisfied.
- **The histogram's pointer handlers read a window without checking for
  one** (`viewer-panel.js:912-941`, and the min/max slider listeners at
  848-853). Unreachable from the real server, whose successful answer always
  carries a window, and the `!shape` guard covers the waiting state; a
  malformed answer with a histogram and no window would throw. Cheap to
  guard.
- **The microscopy repository's own `pyproject.toml:6-7` names itself
  `zmart-viewer`, version `0.1.0`.** `server.py:61-68` reports
  `importlib.metadata.version("zmart-viewer")` on `/api/health`, so on a
  machine where the microscopy checkout was ever `pip install -e`'d the
  Viewer would report 0.1.0. This is a good argument for decision 3 and a
  trap for whoever reads the version field.
- **The 80% document's I1 is not the plan's I1.** The plan's fifth equality
  is "the embedded operator panel's as-written window"; the test's fifth
  reading is `display_window(built)`, the Viewer's own, and the document
  quietly substitutes "the configuration row the page is handed". The
  embedded half is covered only by the jsdom stub.
- **`viewer-panel-contrast.spec.js` was not extended** with the
  empty-live-source-to-first-landing transition the plan asked for
  (searched for "waiting", "measurable", "65535": nothing). The 80% document
  admits the browser walk is missing; the plan said it was "required before
  M3, not left as post-migration polish".
- **A position that trips the contract is lost from the scan's records.**
  `_keep_position_as_zarr` re-raises (`bridge.py:735-739`) before
  `_records.setdefault(...).append(record)` at line 713, so the vendor files
  exist and the record does not.
- **`test_viewer_service.py` asserts the 0.2.0 shape by imitation.** The
  tests stand up a pretend server that answers `{"ok": true}`; nothing runs
  `9ff10b0` itself. That is adequate for a unit test and is not the
  "handshake observed refusing an old Viewer" the previous review asked for
  as M3 evidence.

### What was checked and is right

- **ngio 1.0.0 was checked here, not taken from the comment.** A probe wrote
  four OME-Zarr 0.5 stores with `zmart_storage.canvas._declare_one` and
  opened each with `ngio.open_ome_zarr_container`: no `omero` block opens
  (labels default to `channel_0`); a complete window opens (`GFP`);
  label-only and `min`/`max`-only are refused with `NgioValidationError`.
  That is exactly what `zmart_viewer/acquisition.py:238-241` records, so
  decision 9 is supported.
- **The sidecar beats a disagreeing first position.** A probe wrote two
  positions with the real writer and a sidecar declaring `300…4200`, then
  rewrote the first-sorting position's own `omero` window to `5…50`. The
  composed group still said `300…4200` with source `zmart-acquisition.json`.
  With the sidecar removed and the positions disagreeing, the composed group
  had no `omero` block and `displayWindows == []`. This is the property I1
  exists to prove, and it holds beyond what the test exercises.
- **No `{low: 0, high: 65535}` window fallback remains** in
  `viewer-panel.js`. The one `65535` left (line 687) is the track's upper
  bound in `theTrack`, the axis and not the window, matching the previous
  review's note about `LayerPanel.jsx`.
- **The embedded waiting test is a real check**, not a mirror: it asserts the
  four sliders are `disabled`, the sentence text and its ARIA role, and that
  `65535` appears nowhere on the card.
- **B2's two regression cases are permanent tests**
  (`test_a_position_without_omero_beside_positions_with_it_still_opens`,
  `test_per_image_non_channel_omero_keys_do_not_refuse_a_transfer`) and pass;
  `legacy_source_metadata` has no `raise` left in it and `read_the_transfer`
  guards the second description read (`compose.py:563-569`).
- **The vitest suite runs the new file** — `viewer-panel-waiting.test.js` is
  matched by the include pattern and `jsdom` is present in `node_modules`, so
  its passing is not an artefact of not running.

---

## 2. Answers to the nine questions

### Q1. Are the previous review's four blockers closed?

**B1 (a wrong channel count loses every position, silently) — closed.**
`bridge.py:850-880` requires `channel_count` in the scan request, applies the
recorded state, reads `observed["channel_count"]` from the instrument, and
refuses the scan before the thread exists when the two disagree;
`acquisition_description()` takes the count as an argument
(`acquisition_description.py:178-190`). `_keep_position_as_zarr` re-raises
`AcquisitionDescriptionError` (`bridge.py:735-739`), the scan worker catches
it into `_scan["error"]`, and `live.js:258` throws on that field so the page
sees it. The test `test_a_wrong_declared_channel_count_is_refused_before_a_scan_starts`
(`test_operator_bridge.py:488`) covers the first half. **Ways to reopen:** a
driver that does not report `channel_count` — only the Leica adapter,
mesoSPIM and the mock were taught it in `b79fb46e` — makes every scan that
carries `channels` refuse to start, loudly; and a recording made before
`b79fb46e` carries no `channels`, so it publishes no descriptor and goes down
the legacy path, which is safe today because `_a_window_onto` is still there
(and is one more reason M3 must not remove it before every recording has
been re-taken).

**B2 (legacy disagreement refuses the picture) — closed.**
`legacy_source_metadata` returns `(None, None)` for a missing block, a wrong
count, a non-dict entry or a channel identity disagreement, and never raises;
non-channel `omero` keys are ignored; `read_the_transfer` tolerates a second
description read failing. Both of the previous review's cases are tests and
pass. **Way to reopen:** the descriptor path still refuses a count mismatch
(`test_a_descriptor_whose_channel_count_disagrees_is_refused`), which is what
the plan's failure rules say and is fine, as long as nobody "fixes" the
legacy tolerance by routing legacy runs through that validator.

**B3 (the writer still declares the camera range) — closed.**
`Channel.described` raises when there is no window in both repositories
(`record/model.py:1720-1725`, `zmart_storage/canvas.py:1055`);
`the_channels_described` returns `[]` when any channel is unresolved and
`the_image_description` then writes no `omero`; the live path uses
`the_channels_for_display`, whose window lacks `start`/`end`, which
`_display_for` passes through as a window with no pair and
`described_channels` turns into `None` (`test_unresolved_profile_windows.py`).
**Ways to reopen:** any remaining caller of `.described()` on a window-less
channel — finding I1 is exactly that, in `zmart_live`, plus the unguarded
`zmart_storage/positions.py:474`.

**B4 (M3 would write OME-Zarr that ngio refuses) — closed as a decision.**
"Omit the whole `omero` block" is implemented on both sides
(`ome_channel_blocks` returns `[]` when unresolved, `source_metadata` returns
`None` when any channel lacks a window) and I verified the four shapes against
ngio 1.0.0 above. **Way to reopen:** the evidence is a code comment dated
2026-09-02, not a test; the day ngio is bumped nothing will re-check it. A
five-line test that opens the "no block" and "complete" shapes with ngio, and
expects the other two to be refused, would close it for good.

### Q2. Is the handshake safe in both directions, and can the refusal be bypassed?

**New writer, old Viewer (`9ff10b0`, `{"ok": true}`) — safe.** No
`capabilities` key means an empty set, both promises are missing, the server
is stopped and the sentence names both. This is exercised with a pretend
server in `test_a_viewer_that_promises_neither_is_refused_with_an_upgrade_sentence`.
And because `_a_window_onto` still stamps every position, even a Viewer that
somehow slipped past would draw the legacy way, not black.

**Old writer, new Viewer — safe.** An older `viewer_service` never asks
`/api/health`; the extra fields in the answer are ignored; the old writer
still stamps per-position windows, and the new Viewer's legacy path composes
them by consensus or measures.

**Bypass by a slow answer — no** (observed: a six-second answer is refused as
"too old"; the failure is closed, though the sentence misleads, finding I3).
**Bypass by a malformed answer — no, but it leaks** (finding I2: the parse
error is caught one level up, the Viewer is not used, and it is also not
stopped). **Bypass by a different server on the port — not possible:** the
port is read from the `HTTPServer` object that `make_server` just bound
(`viewer_service.py:128`), so the process is talking to its own socket; the
only way another program answers is a system HTTP proxy in front of
`urllib`, which would produce a refusal, not an acceptance, since a proxy's
error page has no `capabilities`. **A JSON list or a string in
`capabilities`** is refused (probe). The one acceptance bypass I could
construct is a Viewer that lies, which no handshake can prevent.

### Q3. Does the upgrade sentence reach an operator?

The chain, observed: `viewer_service.start()` sets `_viewer["error"]`
(`viewer_service.py:136-141`) → `/api/viewer` answers `status()` whose
`error` is that string (`bridge.py:1261-1262`, `viewer_service.py:184-202`) →
`live.js:107-115` `viewerTrouble()` returns it when it is a non-empty string
→ `main.js:1716` hands it to the watcher as `ctx.viewerTrouble` →
`watching-the-run.js:157-168`: when `whatToDraw()` returns `null` (no sources,
which is the case because a refused Viewer has `port is None` and
`viewerSources()` returns `null` for an empty `sources` map), it asks for the
trouble and calls `ctx.picture()?.tell?.(...)` → `viewer.js:1443` `tell` is
`say(text)`, which unhides `note` and sets its text beside the picture. The
watcher polls every 1.5 s (`watching-the-run.js:272`), so the sentence arrives
within two seconds of connecting. The mock backend returns `null`.

**Where it stays silent:** (a) finding I3 — `ctx.picture()` is `null` when
the sentence first arrives, and `toldAbout` is set anyway; (b) a page opened
with `?picture=` in its address, where `whatToDraw()` never returns `null`
and the trouble is never asked for (deliberate, and harmless: that page is not
looking at the run); (c) after the sentence is shown, any later engine open
overwrites the note with `sayWhichEngineIsDrawing()` (`viewer.js:703-706`),
and because `toldAbout` is unchanged it is not said again — which is fine
while a picture opened, and wrong only if the open was the operator pressing
an engine button on a canvas with nothing to draw. Nothing resets `toldAbout`
on disconnect, so a reconnect with the same old Viewer relies on the note
still holding the old sentence. None of these is the ordinary path; (a) is
the one worth the one-line fix.

### Q4. Every place the embedded panel reads a window; can anything act on `null`; do the four states agree?

Places a window is read in `viewer-panel.js`: `windowOf` (621-623, the one
source, now `?? null`); `theAxis` (631-643, returns the histogram's spread or
`0…1` when null); `theTrack` (669-695, substitutes `0…1`); `drawTheHistogram`
(712-757, returns after setting the viewBox when null); `refreshControls`
(760-825, the null branch disables min, max, brightness, contrast, leaves
opacity live, sets the sentence); `takeTheWindow` (832-845, reads its
argument, never `windowOf`); the min/max slider `input` listeners (848-853,
read `windowOf(...).high/.low` unguarded); the brightness/contrast listeners
(857-868, pass `windowOf(row)` into helpers); `Reset` (881-885, guarded by
`asWritten`); `Auto` (886-900, re-measures, and an empty answer lands in the
waiting branch); the histogram's `pointerdown`/`pointermove` (912-941, read
`window_.low/.high` unguarded); `chooseRow` (1261-1294) and `theRows`
(141-175, where `window` and `asWritten` both come from the store's `omero`).

**Can any control act on `null`?** Not from the real server. The four
sliders are `disabled` in the null branch, so their listeners do not fire;
`Reset` is disabled when there is no `asWritten`, and `asWritten` non-null
implies `window` non-null because both are set from the same block; `Auto`
handles an empty answer; the histogram handlers are guarded by `!shape`, and
`shape` is `null` in every waiting or unreadable state because `chooseRow`
clears it and an empty answer never sets it. The remaining hole is a
successful answer with a `histogram` but no `window` and no `autoWindow` —
then `shape` is set, `windowOf` is `null`, and a pointer press on the
histogram throws at line 919. `_serve_measurement` cannot produce that shape,
so it is a hardening item, not a fault.

**Do the states disagree between the two panels?** Yes, in three ways
(finding I4): the embedded panel says nothing for `provisional` where the
standalone says "brightness measured from pixels acquired so far"; the
embedded panel can never be `settled` because the route does not say so on
success; and the embedded `unreadable` sentence carries the reason while the
standalone does not. `waiting`, `unreadable` and `declared` are otherwise
consistent, and `declared` is derived the same way on both sides in practice
(the store's own `omero` window: `asWritten` in the embedded panel,
`_omero_window` / `_window_asked_for` in `contrast.py`).

### Q5. Does `/api/measure`'s empty answer distinguish absence from fault the way `measure()` does, and is `_readability_problem` safe on the resolved store?

The mechanism is the same helper called the same way: `measure()`
(`contrast.py:346-355`) calls `_readability_problem` when `_samples` returns
`None`; `_serve_measurement` (`server.py:719-731`) calls it when
`measure_here` returns `None`. So the two agree on what "unreadable" means:
a description that cannot be read, no levels, or an array whose metadata
cannot be opened. They also agree on what neither can see: a corrupt chunk
makes both `_samples` (line 176) and `measure_here` (line 511) skip or return
`None`, and `_readability_problem` opens only the array metadata, so both
answer "waiting" for a store whose pixels are damaged. That is a shared
limit, not a disagreement.

Where the route is looser than `measure()`: `measure_here` has extra `None`
exits that are not about the store at all — a `box` outside the picture or a
`channel` the axes do not hold (`_the_box_on` returning `None`, line 481) —
and those come back as "waiting" (probe). `measure()` has no such inputs.

`_readability_problem(store)` is safe on what the route resolved:
`Library.resolve` (`library.py:1162-1184`) returns a path inside a dataset
root or one of its borrows, and the route checks `is_dir()` first; the helper
only reads attributes and opens the group read-only, catching `OSError`,
`KeyError`, `UnicodeDecodeError`, `ValueError` and `MemoryError`. For a built
picture whose levels are declared but not yet written, `group[level]` opens
the array metadata without reading chunks, so a lazy picture is not called
unreadable. The cost is one extra metadata read on the empty path only.

### Q6. Is the I1 test proving the five equalities, or mirroring the implementation? Could first-position-wins pass it?

`test_one_declared_window_reaches_every_reading`
(`test_one_window_end_to_end.py:62-91`) reads five things and asserts each
equals `THE_WINDOW`: the sidecar, both positions' `omero` windows, the
composed group's window (plus `displayWindowSource ==
"zmart-acquisition.json"` and `resolvedFrom == "acquisition-record"`), the
built picture's window and its config row (`measurementState == "declared"`),
and `display_window(built)`. Those are real, independent readings from disk
and from the Viewer's public functions, not from the writer's internals, so
it is not a mirror.

**Could first-position-wins pass it?** On the numbers alone, yes: the
positions mirror the sidecar by construction, so a Viewer that took the
first position's window would produce `300…4200` too. What excludes it is the
provenance assertion at line 78-81 — a first-position path would say
`legacy-position-metadata`. That is an indirect proof; the direct one is the
probe above, which planted `5…50` on the first-sorting position and still got
`300…4200`. I would add exactly that tampering to the test so the property is
proved by the numbers and not by the label.

The legacy half (lines 94-119) does exclude first-position-wins directly:
with two disagreeing positions it asserts no `omero` block, `displayWindows
== []`, and that the measured window differs from both positions' windows.
One caveat: `windows[0] != windows[1]` (line 102) depends on `_a_window_onto`
measuring a dim and a bright field differently, so this half of the test
must change when M3 removes that measurement — which the plan already says.

What the test does **not** prove is the plan's fifth equality, the embedded
panel's `asWritten`; see the minor observation above.

### Q7. Decisions 1–9: wrong, unsupported, or contradicted?

1. **Descriptor location and schema — supported**, with one gap: "publication
   is a hard link" is true (`acquisition_description.py:272`) and the
   filesystem requirement that implies is unstated (finding I5). The
   directory fsync, the folder-name check and the single publisher are all
   observed; `capture_run.py` no longer publishes.
2. **The recording preset as the source — supported.** `settings.js:36-45`
   derives key, index and label; `bridge.py:857-873` checks the count against
   the instrument. One thing the document should say plainly: the label is
   parsed out of the preset's display string (`said.split("·")[0]`, and a
   `\d+ nm` match for the key), which is a convention on a string rather than
   a structured field. It works for the presets that exist.
3. **Capabilities, not versions — supported**, and the `pyproject.toml`
   name collision above is a live example of why.
4. **Absent-window behaviour "the same in both canvases" — contradicted by
   the code** (finding I4). The four states exist on both sides; the words
   do not match and one state is unreachable in the embedded panel.
5. **Scratch lock — a decision only**; nothing implemented, as the document
   says. Nothing to check yet.
6. **Mechanical definitions — unchanged**; nothing to check.
7. **No product bound on process-cold open — a deferral**; consistent with
   the code, which changes nothing there.
8. **Compact experiment unauthorised — supported**; the diffs touch no codec
   or pyramid code.
9. **Omit the whole `omero` block — supported by the code on both sides and
   verified here against ngio 1.0.0.** Unsupported only in the sense that the
   evidence is a comment, not a test.

### Q8. What does M3 need that is not in place?

Measured against the previous review's five conditions and the plan:

1. *M2 deployed, and the handshake observed refusing an old Viewer.* The
   refusal is unit-tested against a pretend `{"ok": true}`; it has not been
   observed against `9ff10b0` running, nor on the microscope PC. **Not met.**
2. *B4 resolved with the ngio check recorded against the pinned version.*
   Resolved and checked (here, and in a comment). **Met in substance; make
   it a test.**
3. *One real bridge-driven run with the five equalities in a screenshot,
   including the embedded panel.* Not done; the 80% document says so. **Not
   met.**
4. *The legacy-disagreement fixture measuring provisionally, not refusing.*
   Met by `test_two_positions_that_disagree_give_nobody_the_last_word` and
   the Viewer's legacy tests. **Met.**
5. *`measure_cold_open.py` before and after.* Not done. **Not met.**

So `_a_window_onto` may be removed when all of the following hold, and not
before:

- the Viewer with `02cf88d`'s `/api/health` is installed on the microscope PC
  and `viewer_service` has been seen accepting it, and seen refusing
  `9ff10b0`, with the sentence on the canvas (condition 1 and finding I3);
- every recording the operator page can replay carries `channels` (a
  pre-`b79fb46e` recording publishes no descriptor and would, after M3, write
  positions with no `omero` at all, which is what the Viewer now handles, but
  it should be a deliberate state, not an accident);
- the two repositories are released as a pair, since an M3 writer beside a
  `9ff10b0` Viewer is refused by design and draws nothing;
- findings I1 and I2 are fixed, because after M3 every unresolved channel is
  window-less and every `.described()` caller without a guard raises;
- the embedded panel's `provisional`/`settled` handling is settled one way or
  the other (finding I4), because after M3 the embedded panel will be
  `provisional` for every live channel of every run;
- the I1 test's legacy half is rewritten for a writer that no longer measures
  (its `windows[0] != windows[1]` will become `None == None`), and its
  declared half gains the tampered-first-position check;
- and, for the contract to have paid for itself, condition 5's cold-open
  numbers exist.

### Q9. Tests — see section 6.

---

## 3. Facts and inferences, in one place

**Observed:** everything in sections 1 and 2 marked observed, the probe
results, and the test numbers below.

**Inferred:** that `zmart_live` is dormant (no importer found; I did not look
for out-of-tree users); that hard links fail on the named filesystems (from
their documented semantics, not tried); that the canvas opens before an
operator finishes connecting (from reading `stage.js:145`, not timed); that a
system HTTP proxy would produce a refusal rather than an acceptance (from
`urllib`'s behaviour, not tried).

---

## 4. What the 80% document should say differently

- "Corrections found while running everything" → name the suites that were
  run, and add `zmart_live` to the list of things found.
- Decision 4 → either "the same four states, the same words" once I4 is
  fixed, or "the same four states; the embedded panel shows a sentence for
  two of them" as it stands.
- I1 → say the fifth reading is the Viewer's own, and that the embedded
  panel's `asWritten` is covered by the jsdom test only.
- Decision 1 → state that publication requires a filesystem with hard links,
  or add the fallback.

---

## 5. Instructions to the main process

```text
Verdict: accept with follow-up. M2 and I1 are real; the four 50% blockers are
closed in code and the closures are tested. Do not start M3 yet.

Before M3, in this order:

1. MICROSCOPY. zmart_live/omezarr.py:357 still calls Channel.described on
   window-less channels; 95 of its tests have been red since b79fb46e. Guard
   it like cropped.py, or retire the package and say so. Guard
   zmart_storage/positions.py:474 the same way.

2. MICROSCOPY. viewer_service.py: parse the health answer inside the try
   (a list of dicts in "capabilities" currently leaks a running server that
   stop() cannot reach); call server_close() after shutdown() on the refusal
   path and in stop(); make the test assert a refused connection, not a
   timeout; and say "did not answer" rather than "too old" when the fetch
   failed.

3. MICROSCOPY. watching-the-run.js:166: set toldAbout only when
   picture().tell actually ran.

4. BOTH. Decide the provisional/settled words. /api/measure never says
   measurementState on success, so the embedded panel is "provisional" for
   ever and shows no sentence for it, while LayerPanel.jsx shows one. Fix the
   route or the panel, then make viewer-panel-waiting.test.js's stub match
   the route.

5. MICROSCOPY. Add the tampered-first-position check to
   test_one_window_end_to_end.py so the sidecar's authority is proved by the
   numbers, not the provenance label. Decide os.link's fallback for
   filesystems without hard links, or document the requirement.

6. VIEWER. Turn the ngio 1.0.0 comment into a test of the four shapes.

Then the M3 gate: the handshake seen on the microscope PC accepting the new
Viewer and refusing 9ff10b0 with the sentence on the canvas; a real
bridge-driven run photographed with the five equalities including the
embedded panel; the cold-open numbers; and the two repositories released as a
pair.
```

---

## 6. Tests run

Environment: Linux container, Python 3.11.15, numpy and zarr as installed,
Node 22.22.2, software rendering. `ngio==1.0.0` was installed for the
decision-9 probe (plain `pip install` fails on Debian's `packaging`; it needed
`--ignore-installed packaging`). Playwright 1.62's own Chromium could not be
downloaded (the proxy returns 403 for `cdn.playwright.dev`); the Viewer's
tests were pointed at the Chromium already on the machine with
`ZMART_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, which
`tests/conftest.py` honours. The Viewer page was built in the worktree
(`npm --prefix app/page run build`, 7.7 s) rather than copied. The Viewer
package was used as `PYTHONPATH=/tmp/review-v`, and a check confirmed
`zmart_viewer.__file__` resolved into the worktree and not the editable
install in the working folder.

| Suite | Where | Result |
|---|---|---|
| microscopy `application/framework`, `application/parts`, `zmart_storage/tests`, `zmart_live/tests` | `ae40fb58` | **822 passed, 80 failed, 4 skipped, 15 errors** in 2 m 13 s — all 95 failures and errors in `zmart_live/tests` (finding I1) |
| the same four suites | parent `b79fb46e` | 800 passed, 96 failed, 4 skipped, 15 errors in 2 m 02 s — the same 95 in `zmart_live` plus 16 in `zmart_storage/tests/test_cropped.py` |
| microscopy `application/workflows` | `ae40fb58` | 103 passed, 2 skipped in 26 s |
| microscopy `vitest` (`npx vitest run` in `application/`) | `ae40fb58` | 28 files, **393 passed, 15 skipped** in 4.8 s; `viewer-panel-waiting.test.js` included |
| Viewer `test_contrast.py`, `test_a_transfer_is_built_into_one_picture.py`, `test_server.py`, `test_unresolved_profile_windows.py`, page built, real Chromium, `ZMART_REQUIRE_BROWSER=1` | `02cf88d` | **94 passed** in 32 s; the browser tests for the waiting and unreadable live sources ran and passed (software rendering) |
| Viewer full `tests/`, page built, real Chromium, `ZMART_REQUIRE_BROWSER=1` | `02cf88d` | **not completed in this review.** A first run with a per-test timeout that kills the process stopped after one test; a verbose re-run showed `tests/test_a_commit_storm_under_zooming.py::test_a_slow_or_transient_refresh_reaches_confirmation_after_quiet` hanging until the 150 s timeout (an untimed run before it sat on the same test for ten minutes with no output). A second run with that file deselected reached 8 passed and 1 failed — the ninth collected test, `tests/test_a_dataset_is_relived_as_a_live_run.py::TestReplayingATimelapse::test_a_watcher_sees_the_slider_grow_and_follow` — before it was stopped on the coordinator's request, who is running the suite from the working folder. Both stalls happened under software rendering with another browser suite competing for the CPU, so they say something about this machine and nothing yet about the code |
| Probe: handshake with unhashable, slow, string and list-bodied health answers | `ae40fb58` | leak on the unhashable case; socket open after refusal; slow answer refused as "too old"; string and list refused |
| Probe: `/api/measure` on corrupt `.zattrs`, broken `.zarray`, box outside | `02cf88d` | `unreadable` ("names no pixel levels"), `unreadable` (names the JSON error), `waiting` |
| Probe: sidecar versus a tampered first position; then no sidecar | both | sidecar wins; no sidecar means no `omero` and no windows |
| Probe: four `omero` shapes against ngio 1.0.0 | `ae40fb58` writer | no block and complete window open; label-only and min/max-only refused |

**Not run, and why:** the microscopy Playwright walks (`application/*.spec.js`)
need a built page, a dev server and a bridge, and the brief did not ask for
them — the missing browser walk for the upgrade sentence is noted above as a
gap in the checkpoint, not in this review; `viz_studio/tests` (the vendored
older viewer copy, untouched by these diffs, browser-heavy); the driver
hardware suites; and anything on the microscope PC. The pictures that were
drawn were drawn in software, so nothing here measures an operator's screen.
