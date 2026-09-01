# What is left to finish the viewer in the operator window

**Companion to** `2026-09-01-why-the-acquired-overview-never-appeared.md`, which
is the account of what was wrong. This one is the list of what is still to be
built, in the order it is worth building.
**Branch:** `claude/viewer-layer-020-617xad`.
**Date:** 2026-09-01.

## 0. If you are picking this up cold

Work on `claude/viewer-layer-020-617xad`. Read the companion note first — it is
the account of four faults that each reported success while keeping the picture
off the screen, and it will stop you re-deriving them. Then read section 2
below, which is the one rule that decides where each of these steps belongs.

Everything runs against the mock instrument through the real bridge and the
real page; section 8 of the companion lists the commands. Two things that will
bite a fresh machine: the focus environment needs `ngio` (companion, section 9),
and the operator page needs `npm install` in `application/`.

One house rule, because it applies to every line you will write here: this
repository is read by microscopists and biologists who are learning, not by
software engineers. `CLAUDE.md` at the top of the repository says what that
means for comments, docstrings and anything an operator sees.

---

## 0a. The map of the code

Five files hold nearly all of this. Knowing which is which saves an afternoon.

| File | What it is |
|---|---|
| `application/parts/canvas/viewer-panel.js` | **The panel.** Everything in section 3 that says "panel only" happens here. |
| `application/parts/canvas/viewer.js` | The canvas part: the picture, the operator's overlay, the view. It owns `pictureOffsetUm`, which reconciles the carrier's micrometres with the stage's. |
| `application/parts/canvas/engines.js` | Which drawing engines exist and how one is opened. |
| `viz_studio/options/contract.md` | What every engine promises. Read before changing any engine. |
| `viz_studio/options/neuroglancer-under/viewer.js` | The engine the operator window draws with. The **only** file allowed to import from `neuroglancer/unstable/...` — see the guard below. |

The panel is mounted in two places, and both matter when you change its
signature: the run's own view mounts it at
`application/workflows/target_acquisition/steps/scan_the_overview/watching-the-run.js:182`,
and the specs mount it directly. Which engine draws the run is one named line
in `application/workflows/target_acquisition/shared/stage.js`, overridable in
the page's address with `?engine=`.

**A guard you will meet.** `viz_studio/tests/test_the_options_hold_together.py`
has `test_the_engine_stays_behind_its_adapter`, which fails if anything outside
that one adapter file imports neuroglancer. It exists so that swapping the
engine one day stays a single-file job. Step 6 works inside the adapter, which
is allowed; reaching for a neuroglancer type from the panel is not.

---

## 0b. A loop you can work in

The slowest thing about this work is getting a real picture in front of you.
This is the short way.

```bash
cd application
npm install                       # once
npm run dev                       # the page, on 127.0.0.1:5174

# in another shell: the bridge, with the mock instrument
python framework/bridge.py --port 8811 --output-root /tmp/a-run
```

Open `http://127.0.0.1:5174/?bridge=8811`, connect to the **mock** instrument,
and walk the workflow to step 5. Once a scan has landed a field or two, the
bridge will tell you where the pictures are being served:

```bash
curl -s http://127.0.0.1:8811/api/viewer
```

The `sources` in that answer are the addresses the panel and the specs want.
**They do not stay the same for long** — see the trap below — so ask again
rather than pasting an old one. Those addresses are what the panel's own spec
takes:

```bash
ZV_SOURCE="<focussing url> <overview url>" npx playwright test viewer-panel-eyes.spec.js
```

That spec is also the pattern to copy for anything you add: it presses a
control, then asks the *picture* what it is really doing, and requires the two
to agree. A panel test that only checks the panel proves nothing — the whole
reason the eyes were wrong for so long is that they agreed with themselves.

---

Everything below has been checked against the two panels side by side: the
standalone viewer's `viz_studio/frontend/src/LayerPanel.jsx` and
`AxisSlider.jsx`, and the operator window's vanilla port in
`application/parts/canvas/viewer-panel.js`. Where the two disagree, the
standalone one is the reference — except in the few places, listed in section
5, where the operator window is already the better of the two.

---

## 1. Where this stands

The canvas has one viewer. The run's focussing, overview and targets each
arrive as one linked OME-Zarr source and are drawn by the ZMART smart viewer's
engine, with the operator's own plan and marks drawn above it on a separate
surface. On the mock instrument a whole 96-well plate — eight hundred and
sixty-four fields — draws every field, and the panel's eyes can be trusted to
say what the picture is really doing.

Focussing now scores the run's own OME-Zarr position rather than the vendor's
loose plane files, so the height on the focus plot is measured on the same
image the operator can open in the viewer.

What is left is the **panel**. The canvas itself is finished for now; the
controls beside it are a partial port, and this document says what is missing.

---

## 2. A principle to hold on to while doing any of this

The canvas must not learn the habits of the engine underneath it. Today that
engine is neuroglancer reading OME-Zarr, and one day it will be something
better. So each step below says plainly which of three places the work belongs
in, and a step that seems to need work in two of them is a step that has not
been thought through yet.

- **The panel** (`application/parts/canvas/viewer-panel.js`) — controls the
  operator touches. It may only speak to the viewer through the contract.
- **The contract** (`viz_studio/options/contract.md`) — the short list of
  things every drawing engine promises to do. It grows only when a control
  genuinely cannot be built without it, and when it grows, every engine in
  `viz_studio/options/` answers it, even if the answer is "I cannot".
- **The engine adapter** (`viz_studio/options/<name>/viewer.js`) — the only
  place that knows how this particular engine works.

---

## 2a. Traps that have already cost this project days

None of these are your fault when you meet them, and all of them look like
something else.

**A promise that never settles looks exactly like loading.** This is the one
that keeps happening. An open that cannot finish, a measurement that never
answers — the screen shows nothing and says nothing, and the natural reading is
"it is still working". Give anything that waits a way to refuse.

**The addresses the pictures are served on change during a run.** The viewer
numbers what it serves in the order it was opened, so relinking a growing
folder lets the old address go, and a page holding one gets `403`. Ask
`/api/viewer` again rather than keeping an address. Relinking is deliberately
slowed to once every thirty seconds for the same reason.

**Neuroglancer forces its own canvas opaque at the end of every frame.** So
nothing painted beneath it is ever seen. That is why the operator's plan and
marks are drawn on a surface *above* the picture, and why the engine reports
`drawsUnder: false`. If you find yourself wondering why a drawing vanished,
this is why.

**A WebGL canvas does not appear in an element screenshot** — only in a
screenshot of the whole page. Measuring a picture by photographing its own
element gives a convincingly blank image, and three separate "the overview is
still empty" conclusions came from exactly that. Photograph the page.

**Measure each field separately.** A scan of fifty-four fields that drew twenty
looks, from far enough away, exactly like one that drew all fifty-four.
`every-tile-is-filled.spec.js` exists because of this.

**Look at the screenshots you take.** Not just the assertions — the pictures.
Several things on this branch passed their tests while plainly wrong on screen.

---

## 3. The steps

Each step says what an operator gets, where the code goes, whether the contract
has to grow, and how you would know it works. They are in the order I would do
them: the ones that fix something untrue come before the ones that add
something new.

### Step 1 — the depth slider must follow the picture, and count planes

*Needs: the contract to grow. Perhaps half a day.*

**What is wrong now.** The panel's depth slider only ever writes. Move through
the stack any other way — the scroll wheel, a step of the workflow, the viewer
opening itself on a plane — and the slider still shows where it last put you.
This is the same kind of untruth as the eyes that used to stay open on a hidden
channel, and it costs the same trust.

It also speaks in micrometres ("37 µm"), where a microscopist stepping through
a stack is thinking "plane 12 of 48". Both numbers are worth having; only one
of them is currently shown, and it is the less useful one.

**What to build.** A subscription on the handle — `whenTheViewMoves(tell)`,
answering the shape of `whenChannelsChange`, returning a function that stops
listening. The panel subscribes when it mounts, re-reads
`viewer.theDepthItCanShow()`, and redraws the slider from the answer. The
readout becomes `plane 12 / 48 · 37 µm`, because the plane number is what the
operator counts in and the micrometres are what the run was written in.

**Where.** Contract: one new line. Adapter: `neuroglancer-under` already has
the position signal it needs (`navigationState.changed`); `viv-under` has its
own; `jpeg-under` answers with a function that unsubscribes and never fires.
Panel: replace the write-only slider at `viewer-panel.js:581`.

**How to prove it.** A Playwright spec that scrolls the view through the stack
without touching the panel, and asserts the slider's number agrees with
`theDepthItCanShow().atUm` afterwards. That is the same shape of test as
`viewer-panel-eyes.spec.js`, and for the same reason.

### Step 2 — put back the window the run was written with

*Needs: nothing but the panel. An hour.*

**What is wrong now.** The store declares a display window per channel, and the
panel reads it once when it builds its rows — then overwrites it in place the
first time anybody drags a handle (`viewer-panel.js:348` and `:564`). After
that the original is gone for the session. There is an *Auto* button, which
re-measures the pixels, but nothing that says "put it back the way the run was
written".

Those two answer different questions and neither replaces the other. *Auto*
reads the brightness actually present. *Reset* puts back what the operator saw
when the images opened. Somebody who has pulled the handles about wants the
second far more often.

**What to build.** Keep the declared window untouched beside the live one on
each row, and add a *Reset* button beside *Auto*, disabled when there is
nothing to go back to.

**Done when** dragging the handles about and then pressing *Reset* gives back
exactly the picture the acquisition opened with, and *Reset* is greyed out on a
channel whose store declared no window.

### Step 3 — brightness and contrast, the way Fiji says it

*Needs: nothing but the panel. Half a day.*

The panel has *min* and *max*, which say **where** the window is. It has no
*brightness* and *contrast*, which say how bright the middle of the window is
and how tightly it is drawn around that middle. They are not a second setting —
underneath there is only ever one window, and moving either pair moves the
other — but they are the pair a microscopist has used for twenty years, and
having only the first pair makes the panel feel unlike every other image tool
they know.

The arithmetic is worked out in `LayerPanel.jsx:316–328` and can be copied
almost verbatim; both sliders funnel into the `setChannel(index, { window })`
the panel already calls, so nothing outside the panel changes. Brightness runs
backwards on purpose: pulling the window down towards the dark end makes the
picture brighter, because more of the image lands above it.

**Done when** moving *brightness* moves *min* and *max* together on screen,
moving *contrast* draws them in around the middle, and dragging a handle on the
histogram moves the brightness and contrast numbers back — because underneath
there is only one window and all four controls have to show it.

### Step 4 — the panel should say when a measurement failed

*Needs: nothing but the panel. An hour.*

`measured()` (`viewer-panel.js:114`) swallows every failure and returns
nothing. The histogram then simply does not appear, and the sliders sit at
their fallback range of nought to sixty-five thousand, with nothing on screen
to say why. This is precisely the failure mode this whole branch has been
about: something did not work, and the window looked merely quiet.

A single line of notice under the heading, in the standalone viewer's red
(`LayerPanel.jsx:680–684`), saying what was asked for and what came back.

**Done when** pointing the panel at an address that is not being served shows a
line saying so, rather than an empty histogram and no explanation.

### Step 5 — a stack, and a timelapse, that play

*Needs: the contract to grow. About a day, on top of step 1.*

**Depth.** A play button beside the depth slider that steps forward about seven
times a second and wraps at the end, so a stack can be watched rather than
scrubbed. `AxisSlider.jsx:200–238` is the whole behaviour, including the part
that matters most: it stops itself when the axis it was playing goes away.

**Time.** There is no time slider at all in the operator window. The handle
already has `setMoment(t)`, and has had since the contract was written — but
there is no way to ask how many moments there are, so a panel cannot draw a
control for it. This is exactly the gap `theDepthItCanShow()` was added to fill
for depth, and the fix is its twin: **`theMomentsItCanShow()`**, answering
`{ count, at }` or nothing at all when the run is not a timelapse.

That is the one contract addition here, and it should be made in all four
options at once — `neuroglancer-under`, `viv-under`, `viv-inside` and
`jpeg-under` — even where the answer is "nothing".

**Why it matters to a run.** A live acquisition that keeps going is a
timelapse whether or not anybody called it one. Once the run's positions carry
more than one moment, a panel that cannot reach them shows only the first.

**Done when** a stack plays and wraps, the button stops itself if the stack
goes away, and a run with one moment shows no time slider at all rather than a
slider that cannot move.

### Step 6 — colour maps

*Needs: work inside the engine adapter. About a day.*

A channel can be painted through a continuous colour map — viridis, magma, fire,
ice — rather than one flat colour. For a single-channel image that is often far
easier to read than a flat green, because a colour map uses the whole range of
hue to carry brightness.

Three pieces:

- the contract gains `setChannel(index, { lut })` and a
  `lutsItCanDraw` list, so the panel can offer only what the engine can draw;
- `viz_studio/options/neuroglancer-under/viewer.js` gains a colour-map branch
  in `shaderFor` (`:1453`). The standalone viewer already has one worth copying
  in `viz_studio/frontend/src/scene.js:36`;
- the panel gains a small chooser beside the colour swatch, with each map's
  name followed by a plain-language hint of what it looks like — the standalone
  viewer's `LUT_DESCRIPTIONS` (`LayerPanel.jsx:19`) exists because somebody
  meeting the list for the first time should not have to try all four.

This is the largest of the steps and the one most confined to a single file, so
it is a good one to hand to somebody on their own.

**Done when** a channel drawn through a colour map looks right on screen (look
at it), the chooser offers only maps the engine can actually draw, and
`test_the_engine_stays_behind_its_adapter` still passes.

### Step 7 — tidying a long list of acquisitions

*Needs: nothing but the panel. Half a day.*

A run with three acquisitions and several colours each fills the bar. Two small
things from the standalone panel help and neither touches the picture:

- a disclosure triangle that folds one acquisition's channels away
  (`LayerPanel.jsx:728–735`), with the number of channels shown beside the
  heading so a folded group still says how much is inside it;
- an opacity slider on the acquisition heading, which dims a whole acquisition
  at once while keeping its colours in balance. It needs no new engine support:
  it multiplies into the per-channel weight the panel already sends.

**Done when** folding a group away leaves the picture untouched — a fold is
about the bar, not about what is drawn — and the heading still says how many
channels are inside it.

### Step 8 — hold the selection by name, not by row number

*Needs: nothing but the panel. An hour.*

The panel remembers which channel the settings are pointed at as a row number.
When the list is rebuilt — which happens every time the run lands a new kind of
acquisition — that number points at whatever now occupies the slot, so the
sliders quietly start adjusting a different channel. The standalone viewer met
this and fixed it by holding a name instead (`App.jsx:296–299`); the same
change here is small and worth making before the list starts changing under an
operator's hands during a run.

**Done when** a channel stays selected across a rebuild of the list, and the
settings still act on that same channel afterwards. The run landing its first
target acquisition mid-scan is the case to test.

---

## 4. Deliberately not doing these, and why

**The × that closes an acquisition.** In the standalone viewer this asks the
server to stop serving a store the operator had opened by hand. In the operator
window nobody opened anything by hand: the workflow decides what is on screen,
and the next relink would bring a closed acquisition straight back. The honest
equivalent is already there — the eye beside the acquisition heading stops
showing it — and step 7's fold handles the clutter. Adding a × that means
"hide" would be a button that says one thing and does another, which is the
habit this branch has spent its time removing.

**Pan and zoom on the histogram.** This was listed as missing in the earlier
note and that was wrong: the standalone viewer's histogram is a plain picture
with no gestures on it at all. The operator window's is the richer of the two —
its window edges can be taken hold of and dragged, with six pixels of grace and
a cursor that changes to say so. Nothing to port; the note has been corrected.

**Volume rendering controls** (projection mode, gain, ray detail, depth fade)
and **per-axis stretch**. Both only matter once the operator is looking at a
volume, and the canvas today is nearly always looking at a plate. Worth doing
after somebody has actually wanted them. One loose end to know about if you
pick this up: the volume shader in `neuroglancer-under/viewer.js:1474` already
declares a depth-fade control and reads it at `:1518`, but nothing ever sets
it, so it is wired at one end only.

**A "load data" button.** The workflow decides what is drawn. The standalone
viewer's own comment says as much.

**Segmentation layers.** When the targets acquisition becomes a label image
rather than a picture, the panel will want to know that a row is objects rather
than brightness, and offer no contrast controls for it
(`LayerPanel.jsx:329`). Nothing writes such a layer yet.

---

## 5. Where the operator window is already ahead

Worth knowing so that nobody "ports" these away while working through section 3:
draggable window edges on the histogram, a log/linear toggle for it, the master
switch that stops drawing the picture without closing the viewer, red in the
palette, and — the one that took the longest to earn — a panel that asks the
picture what it is really drawing and redraws its eyes from the answer, rather
than trusting its own memory.

---

## 6. About focussing, and whether it could be one file

A fair question, since every focus point now begins at depth nought: could the
whole focus map be one OME-Zarr instead of one per point?

**The half that is already true.** The folder of focus positions *is* one
picture. The viewer lays each store where it says it sits and composes them
into a single linked scene, with depth running through the sweep, and nothing
is copied to make that happen. So on screen there is already one stack, not
sixty-one separate things.

**The half worth keeping as it is.** One file per point still earns its place.
Each point lands at its own moment during a run, and one shared array would
mean several points writing into the same file at once. The scoring step is
handed exactly one path per point rather than a slice of something larger. And
a point that is lost and driven again replaces one file, cleanly.

**Two things to know about that composed stack.** The `c` axis *is* used — a
focus job can capture more than one colour, and scoring takes the first one
present. And plane twelve of one point is not the same height above the stage
as plane twelve of another, because each sweep is centred on its own place in
the focus map. The composed stack's depth axis means *steps into the sweep*,
not height. That is the right thing for looking at, and it is why the height
itself is kept on the run's record rather than written into the store as
geometry — the reasoning is in `zarr_positions.py`, in `_the_corner_of`.
