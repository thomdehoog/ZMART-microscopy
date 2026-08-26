# What is broken, and how we know

Begun 2026-07-29, at the end of a session that set out to check whether the tests were
testing what they claimed. They were not, and looking properly turned up fifteen real faults.
Brought up to date 2026-07-30, when the rest of them were fixed.

**Read the evidence column before acting on anything here.** Everything marked *measured*
has a reproduction that was run and whose output is quoted. Everything marked *reasoned* is a
hypothesis and should be treated as unproven until somebody runs it — three claims that
looked certain dissolved the moment they were measured, including several of mine.

A note on how these were found, because it decides where to look next. Not one of them was
found by the test suite. They were found by writing a test that had to *look at the picture*,
by attacking a fix on purpose to break it, and by an agent being told to behave like an
operator for an afternoon. The suite was green throughout.

---

## The two rules that came out of this

**A test that asks the engine whether it is happy is not a test.** The recurring fault in
this viewer is a picture that is silently absent: pieces fetched, layers built, the engine
reporting itself perfectly content, and nothing on screen. Waiting on engine state to know
*when* to photograph is right. Using it as the verdict is what let almost everything below
ship. `tests/pixels.py` says this already; the suite did not follow it.

**Prove a test can fail, in the test itself.** The strongest tests written here hide
or blank the thing under test and assert the measurement falls — `assert blanked < lit / 4`.
That proof re-runs forever, unlike an assurance in a report that nobody reads twice.

---

## Fixed

Every one of these has a test that fails without its fix. Where the fix arrived in a later
session than the fault, the commit is named.

### The writer

| | fault | evidence |
| --- | --- | --- |
| 1 | Declaring a run over one already imaged destroyed it and reported success | measured: a tile of 4242 read back as 0 |
| 2 | Bundled pieces lost tiles written at the same moment | measured: `[0,0,0,44]` of `[11,22,33,44]` |
| 4 | Re-running into the same folder kept the old, longer frame count | measured: 5 then 2, was 5 then 5 |
| 9 | The time axis was declared, then reversed to declare up front and fill in | see `docs/how_it_works/DATA_LAYOUT.md` |
| E | The guard against overwriting a run was defeated by the acquisition's name — `well[A1]` and `GFP[488]` were read as patterns, matched nothing, and the run was destroyed | measured: 4242 became 0. Fixed in `347624b` |
| N | Two writers could claim one folder and lose each other's tiles, 10 times out of 10; `discard_existing_run` left orphan images holding the old run's pixels; the bundling grain was read from the first image only | measured. Fixed in `347624b` |

The writer's guards were re-attacked independently on 2026-07-30 — names containing
`[`, `]`, `*` and `?`, joining a run into itself through a symlink, two processes racing,
and a writer killed without cleanup — and all 29 checks held.

### Reading a store

| | fault | evidence |
| --- | --- | --- |
| 3 | A channel given no brightness range got a full 16-bit one, so real data opened almost black | measured: opens at (230,393) not (0,65535) |
| 5 | A gap in the frames hid every frame past it — including an all-black frame, since zarr writes no piece for one | measured: `{0,7}` gave 1; 7 frames with the 4th black gave 3 |
| 6 | Frame counting could not read OME-Zarr 0.5 at all, on three of the four ways version 3 names its pieces | measured: 1000 declared / 3 imaged gave "I cannot say" |
| 7 | The axis-unit repair, which exists for foreign instruments, silently stopped working on version 3 | measured: `um` left unrepaired |
| 8 | The channel count fell back to trusting the description on version 3 | measured: 3 layers for a 2-channel array |
| M | The limits of the frame count were not written down anywhere | now recorded in `written_timepoints`; see below |
| O | `parked/prototype/README.md` and `stores.py` described grouping by filename, a design that had been replaced | fixed in `d196c46` |

### What reaches the screen

| | fault | evidence |
| --- | --- | --- |
| B | Brightness never reached the picture for a flat-colour layer: the shader put it all into transparency, which the engine discards for the bottom-most picture | measured: windows (500,4000) and (0,60000) gave byte-identical pictures. Fixed in `d196c46` |
| G | A second kind of scan arriving mid-run was silently swallowed into the first | measured: a target scan became a fourth position of the overview. Fixed in `d196c46` |
| A | An acquisition met before its image was on disk never drew, all session | measured. Fixed 2026-07-30 |
| C | A window measured before the whole-field copy was written stuck at (0, 1) | measured. Fixed 2026-07-30 |
| D | Keyboard shortcuts reached past our interface and trapped the operator | measured. Fixed 2026-07-30 |
| H | Every channel of a multi-channel store shared one window, histogram and Auto | measured. Fixed 2026-07-30 |
| I | The scale bar stated the wrong size in the 3-D view | measured. Fixed 2026-07-30 |
| J | Two nudges, and two full config rebuilds, per position | measured. Fixed 2026-07-30 |
| K | An announcement arriving during a config fetch was dropped | measured. Fixed 2026-07-30 |
| L | The viewer could not be started twice, and there was no `--port` | measured. Fixed 2026-07-30 |
| P | A live run written as OME-Zarr 0.5 stopped growing the moment the page opened | measured: frames 1 then 3 on 0.4, 1 then 1 on 0.5. Fixed 2026-07-30 |
| Q | A target imaged again at the next moment, or in a second colour, was refused as an overlap | measured. Fixed 2026-07-30 |
| R | The flat view drew every specimen mirrored left to right, so an operator clicking a well would send the stage to the one on the other side of the plate | measured: brightness across a picture of a ramp ran downhill at 65 grey levels per 100 px, and uphill by the same 65 after the fix. Fixed 2026-07-30; see `docs/how_it_works/CONTROLS.md` §1a |
| S | A multi-colour acquisition showed only its first channel, in white. The three options in `parked/` made the *page* responsible for describing a run's channels and gave it no way to learn them, so pages said nothing and every option fell back to one white channel | measured: on a run recorded in two colours, 4.8% of the window green and 4.7% red after the fix, against one white half and nothing else before it. Fixed 2026-08-01; see `parked/contract.md` §6 |
| T | Neuroglancer drew both layers of a two-channel run from the same channel, and drew the second at half strength. Only visible once something with more than one colour was actually drawn | measured: one colour missing and the other drawn twice; and 118 of a possible 255 against the first channel's 237. Fixed 2026-08-01 |

---

## The ten fixed on 2026-07-30, in more detail

These were the ones left standing at the start of that day: A, C, D, H, I, J, K, L, P and Q
from the tables above. Each is worth a paragraph because the reasoning matters more than the
diff, and two pairs are taken together below because they were found and fixed together.

### A. An acquisition met before its image is on disk

The viewer notices a store the instant its description lands, which is the earliest possible
moment and is deliberate. The engine then reads its pieces, finds nothing, and remembers that
with no time limit — so when the image arrived the panel went on showing black, with the
acquisition listed, its eye open, and nothing saying why. Only the open viewer was stuck:
reloading the page showed the data perfectly.

An ordinary `POST /api/announce` did not clear that memory. Only `wrote_image_in_place` did,
and a run writing one store per position has no reason to send it — from its point of view
nothing was written in place.

**The fix is a narrow signal rather than a blunt one.** The first thing tried was "an
announcement arrived and the answer came back identical, so something moved that no
description can show". That is the rule `engine.js` already documented, and it is wrong in
practice: redundant announcements are unavoidable with two independent notification
mechanisms, and each one then threw away everything fetched. Measured, that cost a refetch of
the whole view on every position arrival.

What is used instead is the transition itself. A store with nothing written yet has no
histogram — there were no pixels to measure — and no count of moments. When a store the panel
*already knew about* gains either, its picture has just arrived and the engine is told to
forget what it decoded. A store arriving for the first time is not this: nothing has been
decoded for it, so there is nothing to forget.

### C. A window measured before the whole-field copy exists

    coarsest level empty   -> window (0.0, 1.0)      histogram bins used 1
    coarsest level written -> window (328.0, 3196.0) histogram bins used 64

The brightness is measured from the smallest copy of the image, which covers the whole field
and is cheap. A writer produces that copy **last**, so for the whole of a run it is the one
thing not yet there — this hit ordinary live runs, not only empty stores.

The guard meant to prevent it ("only remember the answer if the histogram is not null") never
fired, because zarr does not report an unwritten piece as missing: it hands back the fill
value, so an untouched copy reads as a flawless picture of pure black and produces a perfectly
good histogram of one bar.

Two changes. Whether a copy has been written is now asked of the **folder on disk**, which can
tell "never written" from "written and dark" where the numbers cannot. And a measurement taken
before the whole-field copy exists is marked as one to take again, so it is used now — it is an
honest reading of the pixels that existed — and replaced once the run has finished writing.
The re-check is a directory listing, not a read of pixels, so it is affordable on every answer.

### D. Keyboard shortcuts reaching past our interface

    fresh load:      layout "yz",         1 panel
    press space:     layout "4panel-alt", 4 panels
    click 2D:        layout "4panel-alt", 4 panels    <- no way back
    click 3D then 2D: layout "yz",        1 panel     <- the only escape

`setDefaultInputEventBindings` installs three tables: two belonging to the image panels, and
one **global** table of single unmodified letters and digits. Only the global one was the
problem, and every action in it belongs to an interface this viewer hides. It is now simply
not installed; the panel tables, which are what pan, zoom, rotate and step through z, are
installed by hand.

Twelve of the fourteen tests written for this fail against the old build, which is the proof
they are worth keeping. One that could not fail was deleted rather than left as false cover:
`n` reaches the engine's "add a layer" dialog only through its layer panel, and this viewer is
built with that panel switched off, so the key does nothing either way.

### H. Every channel sharing one window

Brightness was measured per *store*, so a store with a channel axis got one measurement over
all its channels and handed it to every channel's row. On a store whose first channel peaks at
1200 and whose second at 39800, both rows got the pair's window — leaving the faint channel's
entire useful range inside about one pixel of its slider, the precise state the slider exists
to prevent.

It is measured per channel now, and the remembered answer is keyed by channel as well as by
store. **This had to land with B**, and did: while both channels drew saturated the fault was
invisible, and fixing the shader alone would have made the faint channel *invisible* rather
than merely flat — which would have looked like a new fault caused by a fix.

### I. The scale bar in the 3-D view

    what the bar claimed (50 µm over 143 px):  3.50e-7 m per pixel
    what the volume was really drawn at:       1.99e-7 m per pixel

It read 50 µm where the truth was 28.5, by a factor that also varied with the height of the
window, and it did not move at all when the operator magnified the volume.

The two views count their zoom differently: in the flat view it is how much of the specimen
one screen pixel covers, and in the volume view the same number counts across the whole height
of the panel. The bar read the flat view's zoom in both.

Two things were needed beyond the arithmetic, and both cost a round of measurement to find.
The volume panel cannot be recognised by its class name — the built page shortens those to a
couple of letters — so it is recognised by holding a *collection* of slices rather than being
one. And the panel keeps its own copy of the zoom which is brought into step a moment after
the viewer's, so reading it while responding to the change that has not reached it yet gave
the previous value and the bar stated the size the specimen was a moment ago. The zoom is
taken from the viewer and only the height from the panel.

The strict xfail that asserted the right behaviour did its job: it failed the moment the fix
landed, and the marker has been removed.

### J and K, together

Writing one store produced both the run's announcement and, within a second, the folder
watcher noticing the same write — two full config rebuilds per position, on a question that
takes over a second once a folder holds a few thousand acquisitions. Worse once A was fixed:
the second announcement arrived when nothing had moved since the first.

The microscope's announcement now records what the disk looked like as it was made, and the
watcher stays quiet when what it sees is that same thing. Compared by what the disk says
rather than by counting announcements, so a change landing *after* the microscope spoke is
still noticed.

Separately, an announcement arriving during a config fetch was dropped, because the note
asking for another look was written *after* the early return and so was never reached. It is
now written before, the fetch is repeated once when the answer in flight lands, and the note
is always cleared — it used to be left set and then consumed by an unrelated change.

### P and Q, found by closing the 0.5 gap

The register used to list "0.5 and on-the-fly are never tested together" as a gap that
could not be closed, because the writer only produced 0.4. It produces either now —
`TileCanvases.create(..., ome_zarr_version="0.5")` — and writing that test found two faults
immediately, which is the whole argument for having written it.

**A live run written as 0.5 stopped growing the moment the page opened.** The viewer decides
whether anything has changed by taking the modification time of the folder that gains an entry
as each moment is written. It took that to be the resolution level's own folder, `0` inside
the store, which is right for 0.4. A 0.5 store is built on zarr version 3, which files every
piece under a folder called `c` inside that one — so a frame landing changed `0/c` and left
`0` untouched, the answer never moved, and the viewer went on showing the length it read when
the page opened, for the rest of the session.

    0.4:  frames 1  ->  after two more moments, 3
    0.5:  frames 1  ->  after two more moments, 1

This is the same shape as fault 6 and in a different place. The frame counting was taught
about the `c` folder and `library.revision()` was not, because the two work it out separately.
They now share one function, which is the actual fix — the arrangement that let them drift is
what caused this.

**A target imaged again at the next moment was refused as an overlap.** When a tile is written
without saying where it sits in a scan pattern — which is what a workflow choosing its own
targets does, and which the writer documents as ordinary — the writer asks each image whether
the tile would land on something already in it. That question compared only *where* the tile
sat, ignoring which moment and which colour it belonged to. So:

    same place, moments 0 then 1    REFUSED   "writing it would destroy data"
    same place, colours 0 then 1    REFUSED
    same place, same moment, twice  REFUSED   (correctly)

It would not destroy anything: an image holds every moment and every colour separately. A
timelapse of workflow-chosen targets therefore could not be written past its first moment, and
a two-colour target could not have its second colour written at all. Nothing caught it because
every existing test passes `tile_index`, which takes the scan-pattern path and never reaches
the comparison. The moment and the colour are part of the comparison now, and the concurrency
guard beside it already had them, which is the tell that this was an oversight rather than a
decision.

### L. Starting the viewer twice

A port already in use raised an uncaught `OSError` with no advice, and there was no way to ask
for another — so on a lab PC where 8848 is taken the viewer could not be started at all.
There is now a `--port`, the refusal explains itself and suggests the way out, and the address
printed is the one the server actually got rather than the one it was asked for (`port=0`
previously yielded `http://127.0.0.1:0`).

---

## Still open

### The test suite's remaining gaps

These are real and none of them is fixed. They are listed in the order they would hurt.
Three that were here on 2026-07-29 have since been closed. The newer format is now written by
`zmart_storage` and tested on the live path (see P and Q above). The group size that keeps a
large folder from silently losing positions is checked against the measured limit on every
run, with the measurement itself available as an opt-in test. And a run that never looked at
a picture no longer reports green on a machine that was supposed to draw: setting
`ZMART_REQUIRE_BROWSER=1` — which CI now does — fails the run and says whether it was the
browser or the build that was missing. Verified both ways: exit 1 with the page hidden, exit 0
without the variable, so a plain checkout stays green. See `docs/how_it_works/TESTING.md` for all three.

- **The viewer pays a cost per position on every frame, and it is not fixed.** This is no
  longer an untested gap — it is now a measured, guarded fault. `test_the_drawing_keeps_up.py`
  measures how much of its own drawing rate the viewer keeps at ten times the positions:
  measured on this sandbox at 40%, 35%, 38% over three runs, where twenty positions manage
  about 125 frames in three seconds and two hundred manage about 50. It was first found far
  worse, at 24 frames in five seconds against 302 for a hundred positions.

  Two tests hold it. One fails if it slides further than it has already. The other states the
  rate actually wanted and is a **strict xfail**, so the day the architectural fix lands — the
  engine holding fewer positions, as `docs/open/NEXT_STEPS.md` sets out — the suite says so and the
  marker comes off. This is the largest fault still open.
- **Nothing tests the desktop shell.**

### What 36 deliberate breaks found in the viewer, 2026-07-31

The same exercise the writer had: break the code on purpose, run the tests that
claim to guard it, and see. Thirty-six breaks were made across the backend, the front
end and the server. **Twenty-eight were caught. Eight were not**, and all eight have
since been given a test that fails without the fix. Two shapes came out of it and both
are worth remembering.

(This section first said seven rather than eight, and then described eight. The eight
are the seven in the table below plus the one after it, each with a test of its own, so
eight is the number that matches what is actually here. Counted again on 2026-07-31
while the tests were being checked.)

**Seven of the eight were the same shape: a rule that is stated somewhere and checked
nowhere.** Each of them had a comment or a docstring setting out plainly why it
mattered — and no test.

| what was broken | what nobody would have noticed |
| --- | --- |
| `voxel_size` compared every axis instead of only the spatial ones | a timelapse and a still of the same specimen refused as two acquisitions |
| `_heading_for` handed out a heading already in use | two headings reading the same, and closing one closing both |
| `_channels_of` ignored the channel names a store gives itself | the panel labelled with names the microscopist never wrote |
| `normalise_units` was never called on the way out of the server | a store saying `um` refused by the engine, exactly as before the repair |
| the contrast track went back to the whole 16-bit range | every handle still worked and none was usable |
| the folder watcher repeated what the microscope had already announced | two rebuilds per position, and the whole view refetched each time |
| a quiet connection was never sent its sign of life | a page that had been closed never noticed, one thread kept per window |

**The eighth is the more interesting one, because a test did look and looked at the
wrong thing.** Stopping the engine from re-reading a store that has grown changed
nothing any test could see. `test_a_newer_format_timelapse_lengthens_as_it_is_written`
reads `window.zmartConfig`, which is the *server's* count and was never going to move;
and every fixture in the suite declares its moments up front, so the engine's own idea
of the length never had to change either. The path only matters for a store that
lengthens its own array, which nothing built. `test_a_store_that_lengthens_its_own_array_is_read_again`
now builds one and reads the slider off the screen.

**And that new test had the same fault in it, which is worth admitting.** All eight
breaks above were made a second time on 2026-07-31, after the tests were written, to
check that each really does fail without its fix. Seven failed every time. The eighth
— the one just described — *passed* on about one run in three against a build with the
fix deliberately removed, which is worse than no test at all, because it would have
reported the fault as guarded. The cause was the very mistake the test was written to
correct: it waited on `window.zmartConfig` to know that the engine had settled on one
moment, and that is the server's count, answered long before the engine has opened
anything. Sometimes the store grew before the engine ever looked, so it read three
moments the first time, the slider appeared, and nothing had been re-read. It now waits
on the width of the `t` axis in the engine's own coordinate space instead, and fails
five runs out of five without the fix. **The lesson is the one at the top of this file, and
it applies to the tests as much as to the code: ask the thing you are testing, not the
thing that is easy to ask.**

**Where this area is still weak.** The eight above were re-run and are proven; **the
twenty-eight said to have been caught were not**, so that number rests on one session's
word and nothing here would notice if it were wrong. The mutations were also chosen by
reading the code for rules worth guarding, so they are biased towards code that says
what it is for; the
quieter parts of `server.py` and the layout of the panel were sampled thinly. Nothing
was broken in `demo_data.py`, `launcher.py` or `browsercheck.py` at all. And nothing
here tests the desktop shell, which remains the largest untouched surface.

### Known limits, written down rather than fixed

- **The frame count is not bounded by the length the store declared.** A stray folder `9999`
  in a store declaring ten moments gives ten thousand; what keeps the slider sensible is that
  it clamps to the declared length itself, in `AxisSlider.jsx`. An empty leftover frame folder
  counts as reach. And freshness is exact equality on the folder's modification time, so a
  folder replaced by a shorter one with an identical timestamp — `cp -a` from an archive —
  keeps the old, longer answer until the viewer is reopened. All three are now recorded in
  `written_timepoints`.
- **A brightness measurement taken mid-run is taken from a larger copy of the image**, which
  covers less of the specimen at once than the whole-field copy does. It is replaced by the
  full measurement once the run has finished writing. The reading is good, not final.
- **The viewer's server is honestly not an installable package.** It is loose modules reached
  through the import path, and `pyproject.toml` says so rather than implying otherwise.

---

## Do not chase these — they were suspected and cleared

Each cost real time to check, so the next session should not spend it again.

- **`engine-chrome.css` is not stale.** All three selectors still match in neuroglancer
  2.41.2 and the elements are hidden in both views. `.maximize-button` matches nothing only
  because a single-panel layout has no maximize button.
- **Opacity, colour and lookup tables all reach the engine and the picture.** An initial
  "opacity does nothing" was the test harness failing React's value tracker, not a defect.
- **`letGoOfDecodedPieces` firing unconditionally does not stop the picture filling in.**
  Eight tiles at 200 ms apart went 0.000 → 0.250 → 0.496 → 0.746 → 0.992, and still reached
  0.992 with no gap at all.
- **The mesoSPIM shape is handled well**: six sibling per-tile-per-channel stores, no `omero`,
  no channel axis, two correct rows, and the translations honoured with tiles placed side by
  side.
- **The 2-D/3-D round trip loses nothing**, and odd folders — empty, non-zarr, a plain file, a
  missing path, a half-written store — are all answered plainly.
- **An invlerp with no range does not default to (0,1) on integer data.** It defaults to the
  type's full range. That hypothesis was mine and it was wrong; see B for what was actually
  happening.
- **"Announcement arrived and nothing changed" is not a usable signal for a store gaining its
  picture.** It is the rule `engine.js` documented and it looks right, but redundant
  announcements are ordinary and it fires on every one of them. Measured: a refetch of the
  whole view per position arrival. See A for what is used instead.

---

## Judgements made, so they can be argued with

- **Frame counting reports how far the images reach, not how many moments were written.**
  Where a moment in the middle holds nothing, the empty ones between are offered and draw
  empty. Stopping at a count would put readable data out of reach silently, which is worse. In
  a live run, where moments arrive in order, the two are the same thing.
- **A timelapse declares its length up front and fills it in**, reversing an earlier decision
  in the same session. `docs/how_it_works/DATA_LAYOUT.md` keeps both the original reasoning and the reversal.
- **Sharding stays out of the writer** until the exclusivity unit is right, because unsharded
  is verified correct and sharded silently loses tiles.
- **Intensity goes into RGB rather than making layers additive.** An analysis recommended
  `blend = "additive"` and it was overruled, because `docs/how_it_works/DATA_LAYOUT.md` records a measured
  decision that overlapping tiles are drawn one on top of another and not blended, "so the
  picture looks exactly as it would have if a single image had been used". Additive would sum
  overlaps into bright seams. `vec4(rgb*v, v)` is also wrong: neuroglancer's default blend is
  straight, not premultiplied, so that form darkens upper layers as `v²`.
- **A brightness measurement is shown before it is final.** The alternative is to show nothing
  until the run finishes writing, which would mean an operator watching a run seeing no
  histogram and no sensible window for its whole length.

---

## Observed 2026-08-17, at the workstation, not yet reproduced

**The volume view is sometimes brighter warm than after a reload.** *Observed*
by the operator while watching a built picture grow (the Thy1 one-source
spiral); a reload settled the brightness back down. Not yet reproduced under
instrumentation, so the mechanism is unproven. Two candidates, both plausible
and both catchable by the same instrument:

- the twin refresh deliberately draws the elder layer and its replacement
  together for a moment, and volume compositing **adds** — so a twin that
  lingers, or is created repeatedly under a storm of announcements, would
  read as extra brightness that a reload (one layer, no twin) does not have;
- the volume view's display window is derived once from what was sampled at
  load, and a picture that has since grown is being shown through a window a
  fresh page would derive differently.

The instrument that decides it is the 3-D variant of
`tests/test_a_built_picture_grows_while_watched.py`: the same held-view,
hands-off discipline with the volume view toggled on, comparing not just lit
fraction but mean brightness, warm against fresh. Until that exists and has
been seen red, this entry is an observation, not a fault.
