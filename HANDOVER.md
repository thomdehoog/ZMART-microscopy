# Where this stands, and what to do next

Written 2026-07-31, at the end of a long session, for whoever picks this up next —
which will probably be the same person, a day later, with none of it in mind.

It says what exists, where it lives, what was decided, what was tried and rejected,
and what to do first. The last part matters most: **the exploring is finished and the
integrating has not started**, and that is the shape of the work ahead.

---

## The honest summary in five lines

A great deal was settled this session, almost all of it by measurement rather than
argument. What was *not* done is put the pieces together. There are now five
branches, three working implementations of the same viewer, an operator window that
lives apart from the canvas it is meant to hold, and several documents that have to
say "see another branch" to be truthful. None of that is broken. All of it is
unfinished in the same way.

---

## What exists, and where

### The writer — `zmart_storage/`, branch `claude/viewer-only`

Turns a microscope's tiles into OME-Zarr. This is the most thoroughly tested thing
in the project: two quality passes, seventy-nine deliberate mutations of the
implementation between them, and every fault they exposed closed.

- **One image per acquisition type.** Tiles butt up against each other and land
  straight into their places. Overlapping runs are refused rather than mangled.
- **A record of where every tile was imaged** (`coverage.py`), written one line per
  tile, appended whole so that two tiles landing at once cannot splice each other.
  Sixteen threads writing together put sixteen whole lines on disk.
- **The pyramid follows the canvas size.** A stage-sized canvas went from three
  smaller copies to eight, and from roughly nineteen thousand requests to open a
  view down to about thirty.

### The existing viewer — `zmart-viewer/app/page` and `backend`, same branch

The React application with neuroglancer inside it. It works, and this session found
and fixed real faults in it — including one that had been shipping for months.

**Its current commit is not verified.** `483417f` holds a quality pass that was
stopped one step before it ran the suite. An agent is checking it now.

### The canvas — `zmart-viewer/parked/`, same branch

The new thing, and most of this session. **Three implementations of one interface**,
so they can be compared rather than argued about:

| | what it is |
| --- | --- |
| `neuroglancer-under` | neuroglancer in its own canvas, the operator's drawing above it |
| `viv-under` | the same arrangement, Viv and deck.gl below instead |
| `viv-inside` | no sandwich — Viv's layers and ours in one canvas, one pass |

All three take the same drawing functions, speak micrometres, and are measured by
the same suite. The two gestures they honour come out of one shared file they all
import, so dragging and the wheel cannot feel different from one to the next. The
table is in `RESULTS.md`.

### The operator window — branch `claude/live-tiles-mvp`

The step rail, the workflow chooser, the right-hand panel. Built before this session.
**It is not on the viewer branch**, because that branch was deliberately narrowed to
the viewer and the writer, and the workflow code went out with the rest.

### Two measurement rigs — `claude/sandwich-probe`, `claude/layer-stack-probe`

Not products. They answered whether stacked canvases stay locked together, and
whether one layer inside the engine can show through another. Their findings are
written up on those branches.

---

## What was decided, so it is not re-argued

**Neuroglancer**, for what it lets you build rather than what it can hold. Most of
the objections to embedding it dissolved when they were actually tested: the
background colour is a setting, the input bindings are a table you write to, the
keyboard traps were already removed, position and zoom drive from outside, and the
2-D/3-D toggle already exists. Three dimensions comes almost free. Viv stays built
and available, which costs nothing.

**Two gestures in the flat view.** Drag pans, the wheel zooms, nothing else moves the
view. Rotation is removed, because a rotated picture silently stops matching the
drawing over it.

**The layer stack.** Carrier at the bottom, the acquired picture, then a mask, then
the operator's planned tiles, then scribbles. The plan sits *above* the picture,
because photographing it the other way round showed the acquisition covering the tile
outlines exactly when an operator most wants them.

**No overlap, for now.** Overlap is a debt that must be settled by a checkerboard
acquisition or a real stitcher, and neither is here. Tiles step by a whole tile.
**The cost, accepted knowingly:** there is no recorded data with which to correct a
stage that is slightly off, so a seam from stage error is permanent. Overlap comes
back later if the viewer work settles and it turns out to be needed.

---

## What was tried and rejected, with the reason

These are written down because each looks attractive on its own and will be proposed
again otherwise.

**A floor of one in every tile**, so that nought would mean "nobody has been here".
Rejected: on a photon-counting detector zero is a real measurement, and clamping it
fabricates a count that was never recorded — in exactly the low-light work photon
counting exists for. The coverage record answers the same question as a fact, for any
detector, without touching a voxel.

**One bounded layer per imaged region**, so unvisited ground would have nothing drawn
over it. Rejected because a layer cannot be cropped: a bound written onto the output
axes is *accepted and silently ignored*, so it would need one store per region, which
breaks the single sparse canvas everything rests on.

**Shifting the writer's translations by half a voxel** so the picture lands where
neuroglancer expects. Rejected: that is changing the data to suit one reader. The
standard decides; a reader that disagrees compensates in its own adapter, which is
where the compensation already lives. The investigation into what the standard
actually says has since finished, and it found that **the standard does not say**:
neither OME-Zarr 0.4 nor 0.5 uses the words "corner" or "centre" anywhere, and the
question has been open with the format's authors since 2022. The writer therefore
states its own choice plainly — the number is the corner of the first voxel — and
`zmart_storage/VOXEL_PLACEMENT.md` records the whole of it, including why half a
voxel is worth the trouble at high magnification.

---

## What finished after the rest of this was written

**The interrupted viewer pass was sound.** Nothing in its 31 files was broken; the
suite it never ran now reads **542 passed, 10 skipped, 2 xfailed**. Two things came
out of checking it that were worth more than the check. The run had been failing for
a reason that had nothing to do with the change — two dozen tests were skipping on a
harness fault, and **neither the test runner nor the CI job built the page those
tests open**, so the skip would have returned on any fresh checkout and the CI
viewer job was red for the same reason. And of the eight fixes that pass claimed its
new tests would catch, seven held every time while **the eighth passed about one run
in three with the fix deliberately removed** — worse than no test, because it reports
a fault as guarded. It waited on the server's count of moments rather than the
engine's; it now reads the time axis out of the engine's own coordinate space.

**Stitching is gone**, and everything it left behind has been cleared away —
`measure_canvas_vs_checkerboard.py`, which no longer ran, and every document passage
that described a run being spread over several images. The measured table that
justified writing into one image is kept and now says on its face that it is history.

**The Viewer workflow exists**, on `claude/viewer-as-a-workflow`. It works, and it
falsified the operator framework's own claim — see the next section.

---

## Two findings that need a decision, and are not written up elsewhere

**The workflow list is declared twice.** `src/workflows/index.js` says of itself that
adding a workflow should never require changing the frame, and *"if it means editing
the frame, the frame is missing something and that is the bug."* Adding one needed
three changes. The serious one: that file is imported by nothing that runs — `main.js`
carries its own copy. So **the unit suite passes against a workflow the page does not
offer, and the page offers workflows no test has ever seen.** Each half looks
completely convincing alone. `ARCHITECTURE.md` had flagged the file as stale; this is
the first time anybody paid for it.

**The canvas contract had two gaps. The first is now closed on this branch; the
second still needs a decision.**

The page was made responsible for describing an acquisition's channels — name,
colour, brightness window — while that description exists only inside the store, and
the canvas offered no way to ask for it. So a page would have had to open the run
itself merely to learn what to tell the canvas about the run it was asking the canvas
to open. It passed nothing, and **a multi-colour run showed only its first channel.**

`channels` is now optional. Where a page says nothing, all three options read the
run's own description out of the store they are opening anyway — the OME-Zarr
`omero` block that `zmart_storage/canvas.py` writes. Where a page does say
something, what it says still wins. `zmart-viewer/parked/contract.md` §6 sets out the
rule, including the one part that is easy to get wrong: a channel's display window
comes from `start` and `end` and never from `min` and `max`, because `min` and `max`
are the camera's whole range and opening an acquisition with them shows a nearly
black picture. `zmart-viewer/tests/test_the_options_hold_together.py` checks it against
a photograph of a two-colour acquisition, for every option.

**The Viewer workflow on `claude/viewer-as-a-workflow` did not pick this up on its
own**, because it holds *copies* of these adapters rather than importing them. They
have since been brought across (`a5ac49e`), which cleared the multi-colour fault
there and the second-acquisition one with it. That is worth remembering as a
standing cost rather than a job now finished: as long as the two branches keep
separate copies, every fix has to be carried over by hand, and nothing announces
when one has been forgotten. Settling where the canvas lives — the first item on
the list below — is what makes that go away.

The coverage record is the gap that remains. The contract treats it as nearly
mandatory, the operator page has none to hand over, so the whole declared room is
drawn rather than only the part that was imaged.

**All three engines now reach that workflow, and the third one changed what the
build produces.** Neuroglancer hands the fetching and unpacking of image pieces to
background programs, and a browser will only start one of those from a file of its
own. The operator page had been built as a single self-contained document, because
the microscope computer has no toolchain to build anything. Those two could not both
hold, so the build now emits three files rather than one: the page, and the two
background programs beside it. Copying a folder instead of a file is a small enough
price for having the preferred engine available.

What did not change is that neuroglancer needs the page to be *served*. Opened
straight off the disk, a page has no origin and a browser refuses to start a
background program for it, so on a `file://` opening the chooser offers the other
two and says why. That is checked by a photograph rather than assumed.

---

## What to do next, in order

### 1. Settle where things live. This is the one that is costing us.

The repository was narrowed to the viewer and the writer on purpose. The integration
work needs the operator window and the canvas together. **Those two facts
contradict each other**, and the contradiction is already visible in the documents,
which keep having to point at other branches to stay truthful.

Two honest options. Either the operator window comes back into this repository and
the narrowing is partly undone, deliberately; or the canvas becomes something the
operator window depends on from outside — a package, with a version — and the
branches stay apart on purpose. Both are defensible. Drifting between them is not.

Nothing else on this list is comfortable until that is answered.

### 2. Fold the probe branches in or close them.

`claude/sandwich-probe` and `claude/layer-stack-probe` hold findings that other
documents cite. A citation to a branch is a citation with a short life. Bring the
write-ups across, or accept that they are historical and stop citing them.

### 3. Write the runbook.

From a fresh clone to three viewers on your own data: install, build, point it at a
store, which parameter picks which engine, how to make a test acquisition, what to
look at first. About twenty minutes of work, and it is the difference between "it can
be run" and "you can run it".

### 4. Then take it to real data on a real machine.

This is the highest-information action available and nothing substitutes for it.

---

## What has never been done, and will produce the next batch of faults

Everything found this session was found by reading code, breaking it on purpose, and
photographing pixels from stores written for the purpose. That method found about
twenty-five real faults — **none of which any suite had caught** — and it is close to
exhausted. What remains is what the method cannot reach:

- **No real data.** Every measurement used stores a few thousand voxels across.
- **No real graphics card.** Two rows of the comparison table are noise for this
  reason, and one option's cost is probably overstated.
- **No real operator.** Nobody has sat down and used it. The mirrored view survived
  months precisely because it looked fine.
- **No real microscope.** The operator window's mock pretends at the level of whole
  experiments rather than the instrument, so none of the code that will meet hardware
  has ever run. See `docs/design/controller_boundary.md`.
- **Windows.** The desktop shell has never been started.
- ~~**Two acquisitions at once.**~~ **Done, and it found what it was meant to.** A
  wide survey and a detailed scan over part of it are now written for the
  purpose, opened together by every option, and measured in micrometres from the
  photograph — `zmart-viewer/parked/RESULTS.md` row 8. The first time it was asked,
  **two of the three drew the finer run 898 µm from where its store says it is**:
  both had code that stretched a second acquisition to the first's voxel size and
  never moved it to where it said it was. Both have been put right and read 0.0 µm
  now. What remains unsettled is bounding the drawn region for two runs at once:
  the interface takes one coverage record, and a record counts in voxels of one
  particular image.

---

## Smaller things worth not losing

- **`zmart-viewer/INDEX.md`** still describes the design as "one store per position",
  which is no longer true and is the file that tells a new maintainer what to read.
- ~~**Registration is measured as unevenness**~~, which was blind to the two
  layers agreeing about position while disagreeing about magnification. **Fixed
  by reporting rather than by measuring**, which turned out to be most of what was
  needed: every side of the band was already recorded, and what was missing was
  the one piece of arithmetic that separates the two faults — averaging each pair
  of opposite sides, which is deaf to displacement exactly as the unevenness is
  deaf to size. Row 1c carries it, and it is shown catching an operator's drawing
  made two per cent too large while the unevenness sits at nought throughout.
- **`SLACK_AROUND_THE_IMAGED_GROUND`** is defined in two adapters and the harness
  sizes a measurement against it in prose. Change one and a row silently starts
  measuring something else.
- **The canvas should own its gestures**, with the right-hand panel selecting the
  tool — so a drag draws instead of panning when the operator has chosen a pen.
  Since done; see "What landed after the sections above were written" below.

---

## What landed after the sections above were written

Each of these was verified from its own reproduction rather than taken on the
agent's word, which has caught a wrong claim four times in this session.

**A multi-colour run now draws properly.** The contract asked the page to describe an
acquisition's channels while giving it no way to learn them, so pages passed nothing
and every engine fell back to one white channel. `channels` is now optional; left
out, each viewer reads the run's own description — the name, the colour, and the
display range the run asked for, never the camera's full range, because that opens a
picture almost black and it stays that way until somebody drags a slider.

Fixing it exposed two more faults in neuroglancer that only appear once something has
more than one colour. **Both layers of a two-channel run drew the same channel** —
and a page naming *one* channel of a two-channel run was shown the *second* one, in
the colour it asked for the first. And the engine's default layer opacity watered the
second channel down to 118 of a possible 255 against the first's 237.

**Two acquisitions at once had never been asked for, and two of the three engines got
it wrong.** Both Viv adapters drew a second acquisition **898 µm from where its store
says it is** — the whole run, right size, perfectly sharp, at the survey's corner.
They stretched it onto the first run's voxel size and never moved it: they read the
scale from the store's description and never read the origin sitting beside it.
Neuroglancer reads the description itself and was right first time. This is the
arrangement the whole project is built around — a wide survey with a detailed scan
over part of it — and nothing had ever drawn one.

**Registration could not see a disagreement about size.** All four margins grow
together when the operator's drawing is scaled slightly differently from the picture,
so the unevenness stays at nought while the outline is visibly the wrong size around
its tile. The fix was one piece of arithmetic on readings already taken. Drawing the
operator's layer 2% too large now moves the new reading from 0.5 to 2.5 while the old
number does not shift a digit.

**The workflows are declared once.** The list the tests read was imported by nothing
that runs, and `target_acquisition` shared only **7 of its 11 steps** with the version
the page offers — a unit test asserted the old numbering explicitly and passed.

**Neuroglancer reaches the operator page**, at the cost of two worker files beside the
single-file page. Inlining them was ruled out by measurement: the build tool copies
neuroglancer's worker stub without compiling it, and a browser silently refuses to
start a worker folded into a page above about two megabytes. It also found that
**over `file://` neuroglancer cannot start at all**, while both Viv engines draw — and
the desktop shell was opening the built page that way, so it would have offered an
engine that could never work.

**Asking for a canvas with no acquisitions hangs neuroglancer.** `openViewer` never
settles: the adapter waits for the engine to know its axes, and the engine derives
those from its image layers. That is the pre-run case — an operator laying out
positions on an empty plate — and the contract says nothing about what an empty
acquisition list means. There is also no way to abandon an `openViewer` that never
finishes.

---

## The canvas owns its gestures now

**Pan and zoom have moved out of the harness and into the canvas.** They live in
one shared file, `zmart-viewer/parked/gestures.js`, which all three options import;
`openViewer` puts the listeners on the box it was opened inside and `destroy` takes
them off again. The harness no longer attaches anything and no longer drives the
view when the operator drags — it hears where the view went through
`onViewChanged`, which already existed. Any page that embeds the canvas now gets
"drag pans, the wheel zooms" without writing a line, which is the whole reason it
moved.

One file for all three, rather than a copy each, is the property that had to
survive the move. It is why the harness owned them in the first place: if the
three each decided how far a wheel notch should zoom, a difference somebody felt
tomorrow might be the engine or might be somebody's arithmetic, and there would be
no way to tell which. The three wiring lines are word for word identical in every
`viewer.js`, and `contract.md` §2 shows them.

**And a drag can now be lent to the application**, which is what keeps annotation
possible: a drag that draws cannot also pan. `viewer.handDragsTo(handler)` makes
the canvas hand each drag over — one call as it begins, one per movement of the
hand, one when the operator lets go, each carrying where the pointer is on the
stage in micrometres — and `handDragsTo(null)` gives panning back. The canvas owns
the mechanics and never learns *why* the meaning changed; in the operator's window
that will be the panel on the right. **There is no pen, no scribble and no
annotation**, deliberately: only the switch, so that a tool can be built later
without touching the canvas. `contract.md` §2a records it.

**What is left for somebody else.** The operator page on
`claude/viewer-as-a-workflow` reaches into `zmart-viewer/parked/` by relative path,
including into `harness/src/gestures.js`, which no longer exists — so that branch
will not build against this one until it is brought across. That copy was already
queued separately and this work deliberately did not touch it.

**And the adapters on `claude/viewer-as-a-workflow` are a snapshot** taken before the
channel and placement fixes. That page still shows only the first channel of a
multi-colour run, and still puts a second acquisition in the wrong place. Copying them
across is the smallest useful piece of work available, and it is a symptom of the
branch question at the top of this document rather than a task worth repeating.
