# Where things stand, 30 July 2026

Written at the end of a long session, for somebody arriving in the morning with a
cup of coffee and no memory of it. It says what was fixed, what was measured, what
was decided, what was written down but deliberately not built, and — because it
matters more than the rest — what turned out to be wrong.

Everything below is on `claude/viewer-only` unless it says otherwise.

---

## The one thing to read if you read nothing else

**A third of the viewer's test suite had been skipping silently.**

Playwright in this container expects a Chromium build that is not installed, and
`playwright install` is blocked. So the browser fixture failed to launch and every
test that looks at pixels skipped — 157 of them, about 31% of the suite — while the
run reported success:

```
336 passed, 174 skipped     EXIT=0
```

Those are precisely the tests that catch the fault this project keeps meeting: a
picture that is silently absent, with every piece of image fetched, every layer
built, and the engine reporting itself perfectly content.

It is fixed (`1115517`). The suite now finds whatever Chromium the machine actually
has, prefers the newest, and prints a **NO PICTURE WAS LOOKED AT** banner on every
run where nobody looked at the picture — not only under `ZMART_REQUIRE_BROWSER`.
After the fix, same machine: `503 passed, 9 skipped, 2 xfailed`. The nine remaining
skips are honest ones — no graphics card, no real acquisition to point at.

**What it means for anything said before this was found.** Statements of the form
"the viewer suite is green, so the picture is fine" covered the data reading, the
contrast arithmetic, the server's path safety and the layer bookkeeping, and said
nothing whatever about whether the viewer draws. The writer's own tests
(`zmart_storage`) are unaffected — they open no browser. The measurements from the
live-tiles work, the sandwich probe and the coverage work are also unaffected,
because those ran their own browsers directly and photographed the results.

---

## Fixed and verified

Each of these was re-run from the original reproduction rather than taken on trust.

**The specimen was drawn mirrored left to right** (`328cb26`). The viewer handed the
engine its axes in the order the file declares them — depth, height, width — which
is width, height, depth with two swapped. Swapping two axes turns a coordinate frame
into its mirror, the way a right glove becomes a left one. An operator clicking a
well would have driven the stage to the wrong one.

It survived because the obvious test cannot find it. Dragging the picture and
watching which way it moves measures **+1.0 both before and after the fix** — an
engine pans using the same axis mapping it draws with, so the picture follows the
hand pixel for pixel whichever way round it is drawn. Only something asymmetric
*inside* the specimen can say which way round the picture is, which is why the new
test writes an acquisition dim at one edge and bright at the other and checks the
bright end lands on the right. Before: `-65.0` grey levels per hundred pixels.
After: `+65.0`.

**A record of where every tile was imaged** (`af92d1c`), in `zmart_storage/coverage.py`.
Nothing on disk previously said which parts of a declared canvas hold picture. One
line per tile, appended, each handed to the operating system whole in a single write
— so two tiles landing at the same instant cannot splice one line out of both.
Sixteen threads writing at once put sixteen whole lines on disk. It also keeps a
short `regions.json` summary, tolerates a truncated final line (what a power cut
leaves behind), and warns rather than failing if the record cannot be started at
all, because the acquisition matters more than the bookkeeping.

**The pyramid now follows the canvas size** (`3cc11bc`). Keep halving the wider of
height and width until the smallest copy is about a thousand voxels, never fewer
than three copies and never more than ten. A stage-sized canvas goes from three
copies to eight, and from roughly nineteen thousand requests to open a view down to
about thirty. Writing costs 6–27% more time depending on how deep the stack is.

**A warning that told operators to do the impossible** (`bc8a184`). The deeper
pyramid made an existing check compare a camera tile against the piece size of the
coarsest copy — 32,768 voxels on a wide canvas — so every large run warned that "a
tile of 32768 voxels would avoid the wait". No camera has one. The check now
compares against the largest piece a tile of that size could actually line up with,
so an ordinary tile is silent however many copies the run keeps, while a genuinely
awkward one is still flagged with a size the camera could be set to.

**`fuse.py` and three stale documents** (`fc0f64b`). The after-the-fact stitcher
still fixed the pyramid at three copies; it now uses the same rule as the writer.
`ARCHITECTURE.md` §3 described departures that have all been closed. `DATA_LAYOUT.md`
described rows gathered by acquisition type, where the truth is now that one load is
one group. A comment in `server.py` justified a restriction with a hazard that was
real on 28 July and gone by the 29th — rewritten with the reason that does still
hold, and the byte-range machinery left strictly alone, since sharded stores depend
on it.

---

## Measured

**Viv reads everything this project writes** — 0.4, 0.5 and sharded — and draws a
picture that matches what was written, with the pyramid genuinely engaging. See
`DRAWING_ENGINES.md`.

**Viv paints unimaged room opaque black**, and a twelve-line shader addition fixes
it: 0 of 19 empty squares showing the ground beneath, against 19 of 19 with it. See
the live-tiles work.

**The sandwich arrangement holds registration.** Neuroglancer in its own canvas
underneath, the operator's canvas on top with holes cut in it. Worst margin
unevenness in any single frame, in screen pixels:

| arrangement | at rest | panning | zooming | thrown about |
| --- | --- | --- | --- | --- |
| one canvas (the control) | 0 | 0 | 0 | 0 |
| sandwich, overlay follows the pointer | 1 | 11 | 35 | 25 |
| sandwich, overlay follows the presented frame | 1 | 1 | 2 | 1 |

The discipline that makes it work: repaint the operator's canvas **only from inside
neuroglancer's end-of-frame announcement**, using the view state read at that
instant. The control reading zero is what makes the rest believable — it says the
measurement is not measuring itself. Full detail in `SANDWICH.md`, which is not on
this branch — it lives on `claude/sandwich-probe`, commit `1277e30`.

**No interface freeze was found** even with the server delayed 200 ms per request.
The engine draws what it has and redraws as more arrives, so a slow disk changes
what is *in* the picture rather than whether the interface answers. The longest
pause was the same at every delay including zero, which makes it the software
renderer rather than the disk. This should be repeated on real hardware.

**Three requests in four are wasted on a sparse canvas.** 250 requests to draw one
view, 190 of them for ground nobody imaged. Bounding the drawn region with the
coverage record takes that to 25 requests, and from 1.30 s to 0.20 s at 20 ms per
request. This is the number that decides whether a store on a network drive is
comfortable.

---

## Decided

**Neuroglancer, on the strength of what it lets you build rather than what it can
hold.** The original reason to move away from it was that it resists embedding, and
most of that dissolved during the session: the background colour is a setting, the
input bindings are a table you write to, the keyboard traps were already removed,
position and zoom are drivable from outside, the layout toggle already exists, and
the cache can be told to forget a chunk. Three dimensions comes almost free, being
the same engine with a different layout.

What does not go away is that every import is through a path the package itself
calls `unstable` — meaning *unpromised*, not *unreliable*. The mitigation is to pin
the version, keep every such import inside one adapter module, and let the test
suite be what tells you an upgrade moved something.

**The flat view has exactly two gestures**: drag pans, the plain wheel zooms.
Rotation is removed, because a rotated view stops lining up with the drawing over it
and nothing reports that it has. Recorded in `CONTROLS.md`.

**The layer stack**, bottom to top: the plate layout, then the acquisition with
unimaged room see-through, and the tiles the operator selected above it. The plate
is written once per carrier type and reused; the tiles are written at the moment
the operator presses save, before the run starts. Recorded in `LAYERS.md` and
`OPTIONS.md`.

The order of the last two was the other way round when this was first written, and
the layer-stack probe corrected it by photographing the stack being built: with the
plan underneath, the acquisition covered the tile outlines exactly where the two
overlapped, so a tile lost its outline at the moment it was imaged — which is the
moment the operator most wants to compare what they planned against what they got.
The plate stays at the bottom because a backdrop is meant to be covered.

---

## Written down, deliberately not built

**Telling "imaged and dark" from "never visited"** — `OPTIONS.md`. Writing a floor
of one into every tile makes zero mean "nobody has been here", exactly and always,
at the cost of the one intensity a camera never produces. Worth checking first
whether anything in the pipeline writes a true zero at all: a sensor sits at an
offset of a hundred counts or so, so this may already be true by accident.

**Drawing nothing until there is something to draw** — `OPTIONS.md`. Instead of one
layer across the whole declared canvas, one bounded layer per imaged region. It
settles transparency, wasted requests and the dark-versus-absent ambiguity with a
single mechanism, and the coverage record makes it affordable by joining touching
tiles into regions. Whether it is possible at all depends on a question being
measured now: can several layers show different rectangles of *one* store? If it
needs a store per region it breaks the single sparse canvas everything rests on, and
should be dropped rather than worked around.

---

## What I got wrong, so it is not inherited

- I said the mirror would show up as the picture moving the wrong way when dragged.
  It does not; the slope is +1.0 either way.
- I said a stall would freeze the whole interface if the overlay were locked to the
  engine's frame. It does not.
- I said a semi-transparent layer could not tint the image. It can — stacked
  canvases composite normally. The real constraint is that nothing placed *beneath*
  neuroglancer's canvas can be seen, because it clears opaque.
- I reported three failing tests in the coverage work when there was one, from a
  stale measurement I did not re-take.
- I cited `DATA_LAYOUT.md` for a rule that is actually in `zmart_storage/canvas.py`.
- And a commit of mine swept up an agent's deliberately-broken code mid-experiment,
  which is why every agent is now told to stage its own files by name.

---

## Still open

- The desktop shell has never been run on Windows. It needs a Windows machine.
- The viewer pays a cost per position on every frame — twenty positions manage about
  125 frames in three seconds, two hundred manage about 50. Guarded by two tests so
  it cannot quietly worsen, and by a strict expected-failure that will announce
  itself the day the architectural fix lands.
- Neuroglancer ignores `devicePixelRatio`, which costs sharpness on a dense screen
  and nothing else.
- A layer given a source address beginning with `/` is never fetched and **nothing
  says so** — no error, no request, the page waits for ever. A trap for whoever
  builds on this next.
- `viz_studio/INDEX.md` still describes the design as "one store per position" and
  does not mention the writer. It is the file that tells a new maintainer what to
  read first, so it is probably the most consequential document still wrong.

---

## Running when this was written

Two agents. One is building the shared harness, the shared measurement suite and the
first of the three viewers — neuroglancer underneath, built as the implementation to
keep rather than a demonstration, with the adapter done properly. The other is
testing the layer stack: whether a layer underneath really hands its transparency
back to the layer above, whether a coarse plate lands correctly against a fine
acquisition, what a plate actually costs to write, whether a pattern survives being
shrunk down, and whether several layers can crop one store.

Their results will be in `viz_studio/options/RESULTS.md` and `viz_studio/LAYER_STACK.md`.
Only the first of those is on this branch; the second lives on
`claude/layer-stack-probe`, commit `4960d17`.
