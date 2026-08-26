# Handoff — ZMART operator page prototype

Paste the section below into a fresh session. It is written to be
self-contained: nothing in it depends on the conversation that produced the
prototype.

---

Continue work on the ZMART operator-page prototype. It is a **mock** — a real
microscope gets wired in later — so it should work well and be easy to change,
not be correct about physics.

## Start here

1. Read `workflows/target_acquisition/webapp-ui/ARCHITECTURE.md`, then the
   rest of this. Get the page running and click through it — most of what
   follows is easier to see than to read.
2. **Say what you would do and why before changing anything.** Check the
   reading against what is actually on screen.

**Focus points are laid so many to a tileset.** One number beside `Place`. The
tileset is divided into that many shares of equal area and the shares are then
settled against each other — Lloyd's algorithm, `sharePoints` in
`lib/scanfields.js` — until every point sits in the middle of the ground it
stands for: as far from its neighbours as that many can be, with every part of
the tileset having one speaking for it, and none on the rim, because the middle
of a share is inset from the edge by half a share. Three deterministic seedings
are settled and the most spread-out outcome kept, so five shares of a wide
tileset come out three over two rather than five thin strips.

A point is a **place**, not a position: somewhere the stage is driven to and a
height is read, which is not the same question as where the run will image, so
nothing about the plan's grid has a say in where it may sit. Tying points to
frame centres put three points on a triangle in a row — that was where the
frames were, not where the sample is. `Place` lays a fresh set rather than
adding to one, because the points are settled against each other and a second
set laid through the first would leave neither arrangement true. There used to
be four patterns to choose between (first, centre, every nth, n at random),
which was four answers to a question that only ever had one: how many. What is shared out is the ground, not the frames' middles: a frame covers a
square of sample, and standing for it by the dot at its centre made a tileset
nine dots instead of a filled block — six points over three by three frames came
to rest on the seams between them, leaving the top row with nothing. Shares that do not
divide evenly are dealt outwards from the middle in pairs, so the rows read the
same from either end: seven over a square block is two, three, two, and eight is
three, two, three. Dealt from the top instead, seven left a hole through the
middle of the block — the one place a surface has least to go on.

How many rows to deal them in is the one thing a formula cannot be trusted with:
five shares of a square block are two, one and two — the four corners with one in
the middle — where a count taken from the square root gives three and two, which
covers the same ground less evenly. So the likely counts either side of the
square root are laid, settled and measured, and the tightest is kept. One family
of arrangements, measured; there used to be three different heuristics scored
against each other, which is how eight points came out as something no operator
would have drawn.

What counts as one tileset is the plan's own answer, carried on every position
it lays: a drawn tileset is one, and the positions a grid put in one area are
that area's. Counting per *field* would have been counting per frame — `Add
grid` lays a block in every area at once and each of its positions is a field of
one, so asking for three points would have put three in every frame on the
plate.

**Either kind of focussing can be given a map.** Recording the preset finishes
the step: a hardware autofocus holds focus off the coverslip and a software one
finds it at every position, and both are complete answers on their own. A focus
map is the optional extra on top of either — a software one finds each point's
height by scoring a short stack, a hardware one is driven to the point and the
height it settles at is read — so there is something to press exactly when there
is a map to measure, whichever kind is measuring it. It used to be that a
hardware reading ended the step with nothing to map, which said the stand's own
focus and a measured surface were alternatives rather than one built on the
other.

**The focus map is on the canvas, not in a tab.** Step 4, `Focus strategy`,
draws its heatmap over the plan with the canvas's own projection, and its
controls — the map, the point list, the sweep and its preview — sit in the
channel beside it. The map is a named object, made the way a preset is: a name
and `New focus map`, or the button pressed empty for `Default n`, and the point
controls only appear once there is a map to put points in. The recording
decides whether there is a map at all: a hardware focussing preset finishes the
step by itself — the stand holds focus, there is no surface to measure — while
a software one asks for one.

A map's row is the same bar a recorded preset gets, and for the same reason: it
is a named object the step is working with, so it is chosen by pressing it,
opened by its triangle to show what is in it — how many points, how many
measured, the surface and its residual — and thrown away by its cross.

**One focus map, and it belongs to the recording.** A run focuses one way, so
there is one surface to fit and nothing to name or choose between: the point
controls appear as soon as a focussing preset is recorded. Maps were named
objects with a list of their own for a while — made, activated and forgotten
like presets — which was a second kind of thing to keep track of for a step that
only ever measures one surface.

`PLACE FOCUS POINTS` offers the same two ways the step before it does, side by
side under the same words: `MANUALLY` is the crosshair, `AUTOMATICALLY` is a
number and `Create`, with `Clear` beside it — three of one size, because they are
one decision with two answers. The points themselves are listed under
`INSPECT FOCUS TRACES`, where choosing one asks to see its sweep, which is what
that box is for.

**Points are picked the way tilesets are.** Shift and drag over the map draws
the same grey dashed rectangle the step before it draws, and takes the points it
covers; shift on a point adds it or takes it back out; a press on empty ground
lets go. Everything held moves together when one of them is dragged, and Delete
takes the whole set away. The list marks what the canvas marks. A mark is dark
grey — nothing else on the picture is, between the pale blue tilesets, their
green outlines and a heatmap running purple to yellow — and one that is held or
found by the pointer is the same mark in black and a little heavier, because a
picked point is the same thing picked out, not a different drawing.

Points are edited on the canvas as directly as in the list. The crosshair arms
placing: a press then puts a point where the press landed, and a press on a
point takes that one away. Unarmed, a point under the pointer says so — a
heavier mark and a `grab` cursor — and dragging carries it anywhere, while
Delete takes the chosen one away; a press over nothing still pans. One place
works out what the cursor says (`focusCursor()`) and the drawing sets it, so a
tool armed from the panel says so before the mouse is moved to find out. SURS
and the whole-canvas scope are gone.

**The scan step takes what was recorded; it records nothing.** Two boxes —
`SELECT ACQUISITION PRESET` and `SELECT FOCUSSING PRESET` — each listing what
has been recorded with the active one marked, because choosing here is the same
act as choosing on the step that recorded it: there is one active recording of a
kind and every step reads it. Under the focussing preset is the one thing this
step decides for itself, `Focus at every tile` or `Use focus map`, the second
greyed until a surface has actually been measured. Then `Start`, at the end of
what it acts on.

**Discovery is the same shape as focus.** Step 7 has no tab of its own: the
canvas keeps the picture — the cells it finds land there — and the channel
holds the settings (algorithm, its parameters, `Test on this tile`) with the
one **test position** beneath them: a pager, the tile preview, and what the
settings found on it. Picking the test position is either the pager or a
press on the canvas — the press takes the position under it, marks it on the
canvas, and resets `tested`, so the step's gate stays honest. The markup for them
is parked in `index.html` under `#focus-controls` and moved into the channel
while the step is standing, so it is built and wired once; anything that writes
into it asks `focusMounted()` first, because the channel hands it back when the
step is left.

**The step that defines the overview positions is built.** It is step 3,
Setup overview: the ways of making fields in one box beside the canvas,
ported from `06_scanfields.jsx`. The grid reads the carrier's area centres, so
the plate decides the plan. Drawing and the grid sit in one box, `CREATE
TILESETS`, with a word apiece over them — `MANUALLY` and `AUTOMATICALLY`. They
are two ways of answering the same question, either a whole answer on its own, and
the operator moves between them without leaving anything; the verb sits on the
button that does it, `Add grid` — and **the box is only there once a
preset has been recorded**, going again with the last one forgotten. It used
to stand greyed on the argument that a step showing what it will be beats an
empty column; with the recording above it saying what it waits for, a greyed
copy of the whole editor said it twice.

**What the objective sees must be inside an area.** A tile whose frame does not
fit wholly inside one of the carrier's areas is not in the plan — a square
hanging over the edge of a well is a square of plastic, and imaging it costs
what imaging sample costs. Three consequences worth knowing before reading a
number off the screen:
- **A block is only as big as a well can hold.** Three by three at 5x, whose
  frame is 2.66 mm, lays *one* position in a 6.6 mm well and nine in a 34.8 mm
  one. The same numbers on a different plate — or the same plate through a
  different objective — give a different plan, which is what changing the
  objective actually does.
- **A field is imaged in one area — the one it covers most.** A rectangle drawn
  over the gap reaches into two wells, and covering both is almost never what
  was meant: it is one sample, in one well, and the outline was loose at the
  edge. The larger share wins and the rest of the outline images nothing.
  Splitting it would quietly turn one field into two acquisitions of two
  different samples. Ties go to the first, which is the top-left of the ones
  tied, because the tiles are counted row-major.
- **What a run images inside an area is a square, whatever shape the area is.**
  A well is round and a plan is not: tiles laid to the edge of a circle come
  out as a rounded blob, no two rows the same length, an outline nobody drew.
  `scanBox()` in `lib/carriers.js` is the area's own rectangle with the corner
  arcs cut back to their chords — the whole rectangle when there is no corner,
  the inscribed square when the area is a circle — and every fitting test is
  against that. **An Area carrier is square-cornered**: the soft corner a glass
  slide happens to have is not part of what can be imaged in it, and carried in
  the preset it pulled the imageable rectangle in at every edge for a shape
  nobody was working to.
- **Connecting answers in a box of its own.** What the session was opened with
  is one thing and what came back when it was opened is another, so the checks
  stand under `CONNECTION CHECKS` rather than inside the form. There is no
  sentence at the end of them any more — six ticks with their answers beside
  them had already said it. Where the press was, an open session shows a green
  lamp and the word `Connected`, the way an instrument says it is on; it is not
  a button, because there is nothing to press about a state and a green one
  sitting where the press was invited a second press. `Disconnect` is the button,
  beside it.
- **One distance between boxes, `--box-gap`.** Every column of boxes used to
  space its own — 8px in the carrier step, 10 in the tilesets, 12 in the focus
  step, and a couple of others by accident — so no two steps read alike. One
  token now, set on each column, and a bar that fills its box from edge to edge
  rather than leaving slack at one end.
- **The focus mark has a colour nothing else uses.** Magenta, `--mark-focus`:
  the marks sit over pale blue tilesets, green outlines and a viridis heatmap
  that runs purple to yellow, and drawn in the page's blue they were one more
  blue thing among them. The one the pointer has found or the list has picked
  out is drawn in a brighter magenta and ringed, so choosing a row says which
  mark it is from across the picture.
- **A quiet word inside a box, where a second box would be too much.** The
  headings above the cards name subjects; a `.side-sub` inside one names a part
  of it — `MANUALLY` and `AUTOMATICALLY` over the two ways of laying tilesets,
  `CARRIER PRESET` over the catalogue and its Load/Save/Reset in the box that
  chose the carrier type.
  Picking a wellplate and picking the 96-well one out of the catalogue are the
  same question asked twice over, and a box apiece made the second look like a
  fresh subject.
- **A box says what it is above itself.** The heading sits over the white card,
  not inside it, so a card holds controls and nothing else and a column of them
  reads as a column of headings with their things underneath. One builder makes
  them — `sideGroup()` in `src/frame/box.js`, handing back the box to put in the
  panel and the card to put the controls in — and the heading and the card are
  one element from the outside, because a box that comes and goes has to take
  its heading with it. Every step is headed this way, the session card on step 1
  included: it used to carry a larger heading of its own inside its card, which
  made the first step look like a different kind of page.
- **The operator's word is "tileset", not "scanfield".** The boxes read
  `MANUALLY` and `AUTOMATICALLY` over the two halves of `CREATE TILESETS`, and
  focus points are laid so many to a tileset — the number box beside `Place` says how many without having to say
  per what. The code still calls them scan fields —
  `widgets/scanfields.js`, the `scanfields` step id, the `sf-` classes — and
  that is deliberate: renaming the ids would move what the run files its
  results under for the sake of a word nobody reads there.
- **The operator's word is "focus", not "autofocus".** The step is Focus
  strategy, what is recorded is a focussing preset, and what a reading says of
  itself is Software or Hardware. The mechanisms keep their names in the code —
  `softwareAutofocus`, `hardwareAutofocus` — because that is what they are.
- **A button that does something is blue** — `Record`, `Add grid`, `Fit`. The
  ghost buttons are the ones that only change what is being looked at.
- **The scale bar is flat and has a strip of its own** along the foot of the
  canvas: a line and a number, no upstanding ends, and the drawing is cut off
  above it rather than running under it. A rule with a plate showing through it
  can be read as either.
- **A region is drawn and resized in whole frames.** Dragging one out, or
  dragging a grip on it, moves its width and height a frame at a time, so its
  border and the tiles inside it land on the same line: nothing imaged outside
  what was drawn and no strip of it left unimaged. It rounds **down** — the
  shape never grows past the hand — with one frame as the floor, there being no
  imaging less than the objective sees at once. Activating another preset
  re-fits every region to the new frame (sizes only; where each sits is the
  operator's statement). A hand-drawn polygon is the one shape this cannot
  apply to, its outline being arbitrary, so its tiles still cross it by a
  fraction. `snapSpan()` in `lib/scanfields.js`.
- **A region's tiles are one lattice, moved as one.** Where the lattice runs
  over the edge of the area, the whole lattice is pushed back in until it
  fits, so the outline is covered into its corners. Moving the edge tiles on
  their own would fill the corner too, and it would change the overlap between
  an edge tile and its neighbour — the overlap is a number the operator set,
  not slack for the plan to spend. What still hangs over after the lattice has
  moved is dropped: a region wider than the well cannot be pushed into it. So
  is a tile the move carried off the outline it was laid for — moving the
  lattice must not image what nobody drew, which is what `covers()` in
  `lib/scanfields.js` is asked a second time for.
- **A position is seated where it is put down; a region is never moved.** A
  position is one frame and nothing else, so pressed or dropped on the plastic
  it slides into the well it was nearest — dragging one across a plate steps
  from well to well. A region is an outline somebody drew around something
  they were looking at: the plan reads it rather than obeys it, so it stays
  exactly where it was drawn even when it covers no well at all. Sliding it
  would move the statement instead of answering it.
  - **A drag is worked out from where it began**, against the fields as they
    were when the pointer went down — `ed.drag.held`. Stepping the current
    positions on by the last event's delta looks equivalent and is not, once
    seating exists: every step is pulled back into the middle of the well
    before the next one is added, so a position never leaves the well it
    started in while the pointer walks off without it. The browser suite holds
    this down — *a position dragged across the plate steps from well to well*.
- `frameFitsArea` / `frameSeat` / `nearestArea` in `lib/carriers.js` are the
  rule; `plan()` in the scanfields widget is the only place it is applied to a
  plan, and the widget's `clamped()` is the only place a field is seated.

**The editor's interaction model, since it is not all obvious from the source.**
The left button does whatever is under it: the editor is asked first, and only
what it turns down pans the stage — so a press on a field picks it up and a
press on empty canvas both lets go of the selection and moves the picture. A
double-click finishes a polygon, and the duplicate vertex its second press
leaves behind is dropped; Alt+drag pans regardless, and without it there is no
way to move the stage while a drawing tool is armed. The cursor is set by the
editor rather than by CSS, and says what the next press will do: `pointer` over
a field or a grip, `crosshair` with a tool armed, `default` otherwise.

**Exactly one thing is ever highlighted.** A grip beats the field it sits on
and the field behind it, and the nearest grip beats the rest — several are
inside the same twelve pixels once a field is small or the view is zoomed out.
Highlighting is a claim about what the next press will take hold of, so two of
them at once is worse than none. Point stays armed after use and its button toggles off; every other
tool disarms itself after one shape. A polygon is drawn closed from the first
two points, with the cursor standing in for the vertex about to be placed.

Three places it deliberately parts company with the JSX. Hover and selection
read the same, rather than as three weights. Grid positions can be picked,
given a preset and deleted but not dragged, because where they are is the
carrier's statement and the next Apply would silently undo a hand-move. And
**marked means brighter** — the field's ink and its tiles go to more chroma,
which is the one signal every kind of field can carry: a region has an outline
to thicken, a grid position has only its tile, and a tile cannot grow without
saying something false about how much of the sample it takes in. Away from grey
rather than towards it, because a plan is mostly tiles and darkening drags the
marked ones towards the greys the carrier is drawn in. A grid position
therefore draws nothing of its own at all; the tile is the position — and when
a preset's frame is under a pixel wide, a mark stands in for the tile, or a
high-magnification plan is hundreds of positions and an empty canvas.

Everything else about how objects appear, select, resize and rotate follows the
JSX — including that fields are clamped to the carrier, which the first port
missed.

**The sample follows the plan.** Tissue belongs to the plate — soft patches
over the carrier, there whether or not anybody looks. Cells belong to the plan:
they are generated inside the tiles the fields ask for, so the run only knows
about what it imaged. Move the fields and a different sample comes back. The
scan, the focus map and the tile detection is tuned on all read the same list.

## Where it is

- Clone: `C:\ProgramData\MinicondaZMB\home\t.de\ZMART-microscopy_merge`
- Branch: `claude/layered-view-operator-next-gcqxuu` (based on
  `layered-view-on-operator-next`) on `github.com/thomdehoog/ZMART-microscopy`
  — **public repo**. The branch runs ahead of the remote — check
  `git log @{u}..HEAD` rather than assuming, and do not push without asking.
  It touches nothing under `zmart_drivers/`; the driver's Z-readback work
  went to `main` on its own (PR #15, `docs/design/z-readback-stacked-drive.md`).
- The live project: `workflows/target_acquisition/webapp-ui/` — a Vite app.
  **Read its `ARCHITECTURE.md` first.** Since 2026-08-25 there is no `src/`:
  `frame/` and `workflows/` stand directly inside `webapp-ui/`.
- `git` is not on PATH: `C:\ProgramData\MinicondaZMB\Library\bin\git.exe`
- The plan for the next stretch — dissolving `main.js` into the step folders,
  tests moving beside what they test — is `docs/design/dissolving-main-js.md`
  with its review prompt beside it. Reviewers go first; nothing of it is
  started.

`docs/design/prototypes/operator-page-layout.html` is a frozen snapshot from
before the Vite move. Not the working copy; do not edit it.

## Running it

Node lives in the project conda env. Everything — node, `node_modules`, the
Playwright browsers — must stay under `C:\ProgramData\MinicondaZMB\`, because
AppLocker refuses to run executables from user-writable paths.

```bash
# POSIX form, not C:/... — bash splits PATH on the colon, so "C:/..." is two
# junk entries and python silently falls through to another env
E="/c/ProgramData/MinicondaZMB/envs/zmart-microscopy"
export PATH="$E:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright"
cd workflows/target_acquisition/webapp-ui

npm run dev        # http://127.0.0.1:5174 — hot reload
npm run build      # one self-contained file -> ../workflow/webapp/static/
npm run test:unit  # vitest, ~146 tests, ~1 s
npm run test:ui    # playwright, ~24 tests, ~130 s
python dev_window.py   # the page in a native pywebview window, still hot-reloading
```

CSS edits hot-swap and keep the run's state; a JS edit reloads the page and
resets it to step 1.

## What the page is

A narrow left rail of workflow steps; one layout for every step — the canvas
on the left from the very first step, and the standing step's controls in a
channel on the right whose width the operator drags with the divider (canvas
bigger by default). Nine steps in `target_acquisition`:

1 Connect · 2 Define Carrier · 3 Register Carrier · 4 Setup overview ·
5 Focus strategy · 6 Scan the overview · 7 Discover Targets · 8 Refine Targets ·
9 Acquire Targets

Register Carrier is a declared **placeholder** — empty channel, and it holds
nothing up (`nothingWaitsOnThis`) until registering the mounted carrier
against the stage actually lives there. There is no presets step, no
Disconnect step, no Save-the-run step, and no Restart button: each preset is
recorded in the step that uses it, the session card's own Disconnect ends a
run, and choosing a workflow (re)starts one. Two other workflows exist to
prove the frame is not built around one: `overview_only` (6 steps) and
`focus_check` (6).

## Decisions already settled — do not relitigate without asking

**Frame**

- The rail is **navigation only**: number and title, nothing else. The number
  carries the state — grey ahead, **green done**, **blue where you are**, and
  blue wins on a step that is both. There is no tick and no note: the badge
  says done, and what a step produced is on the canvas and in the action bar.
- **Nothing advances by itself.** Finishing a step leaves you on it. The rail
  still gates order — only the next step is enabled.
- **A step's action sits at the end of what it operates.** There is no action
  bar. Steps with a tab panel get a foot at its bottom; the carrier's is inside
  its channel. The button carries `.step-run` wherever it lands, which is what
  the tests find it by. `ownButton: true` means "this panel builds its own"
  (Connect does). Define Carrier and Setup overview have no button
  at all — they are settled by doing the work — and Connect's lives in its
  form.
- **The canvas is always on the stage — and only shows what the run knows.**
  Before a session is open it is empty; the stage limits appear with the
  session, because they are a readout from the connected microscope's
  configuration; the carrier appears at its own step, when the run is told
  what the sample is mounted in. Every step keeps the picture on the left and
  puts its own controls in the channel: the session card, the carrier
  designer, the scanfield editor and its preset, the focus patterns and their
  preset, detection, the gate, the gallery and the acquisition type — one
  layout, no tabs of their own. Configuring the carrier fixes the run's zero
  too, which is why no step asks for an origin; that happens behind the
  scenes and is deliberately not drawn.
- **The channel is resizable**: its edge is a divider the operator drags. The
  width lives in `--side-w` on the root, survives walking between steps, and
  is clamped so neither the picture nor the controls can be crushed. The
  canvas is the bigger half by default.
- **A tab is always drawn, even alone**, because it names what is loaded —
  the Canvas. It said "Setup" for every step once, and hiding it lost nothing.
- **The channel beside the canvas is headed, not tabbed**, and **it belongs to
  the step standing in it**. Define Carrier owns it on step 2, Initial
  scanfields on step 4; the heading sits at the right end of the tab row over
  the column it heads, styled exactly as a selected tab, because it names whose
  controls those are rather than offering a switch. One column, not two: a
  second would take width from the picture to hold controls for a step nobody
  is on. A step with no side widget gives the canvas the whole width.
- **A panel belongs to its step** and shows only while that step is selected.
  Walk back to Connect and the session and its checks are there again.
- Step **numbers are derived from position**, never typed.

**Setup panels**

- **Connect** is a form headed "Connect to the microscope": microscope, API,
  password, and its own button. Opening the session runs six checks that land
  one at a time (reachable, credentials, API version, stage, objectives,
  storage). An open session is **not editable** — its Disconnect button ends
  the run and is how you begin again. Nothing says "not connected" before it
  is; the fields and the button already do.
- **There is no presets step: each recording lives in the step that uses it,
  so the state is tested where it matters.** Three slots, all drawn the same
  way, as **one box**: `RECORD ACQUISITION PRESET` (or focussing preset, or
  acquisition type) is headed by the doing and names what the doing will make,
  since the operator is after the thing rather than the gesture. Inside it, a
  name box and a **Record** button, and directly under those **one row per
  reading taken**, each unfoldable to everything the controller returned and
  forgettable with ✕. The readings had a white box of their own until they were
  brought in here, which made them look like a second subject when they are the
  answer to this one — and then a quiet word of their own for a while, which was
  a heading saying what the heading above it had just said.
  - In the Overview-scan-settings channel the plan takes its frame from the
    active reading, so the editor waits behind it — and forgetting the last one
    takes the editor and the plan away again.
  - In the Focus-strategy channel the rest of the step appears only once a
    reading is taken. **An autofocus is software or hardware**: software focuses
    by taking a short stack and scoring it, hardware by measuring a beam off the
    coverslip and holding that distance at every position. Either is a complete
    answer on its own, so the recording finishes the step, and either can be
    given a focus map — see the focus section above. A step says whether it has
    anything to run through `acts(run)`, and the frame only asks.
    `softwareAutofocus` / `hardwareAutofocus` in `lib/microscopes.js` are two
    builders rather than one with a flag, because a hardware autofocus has no
    metric, no sweep and no steps.
  - `RECORD ACQUISITION TYPE` heads the Acquire-Targets channel; the acquire
    button waits for it.
  - Names are capitalised on the way in; `renderRecordingSlot` in `main.js`
    is the one implementation all three share, over `lib/recordings.js`.

- **Readings accumulate, and one of them is active.** Recording used to
  replace what the slot held, which said a reading is a thing done once — and
  it is not: the optics get changed in the middle of a session, and an
  overview taken dry at 5x and a detail taken at 63x in oil are one run. So a
  new reading lands beside the old ones, and the newest becomes the active
  one, because a reading is taken in order to be used.
  - **The row is the button: pressing one activates it, and activating is the
    whole of applying it.** Everything the step produces is taken with the
    active recording — the plan included, all of it, at once. There is no
    `Apply to selected` and no `Apply to all`, and a field carries no preset
    of its own: half a plan taken with optics that are no longer in the light
    path is not a state the run should be able to be in. Activating another
    preset re-takes every field where it stands; the plan changes what it
    covers, never where it looks.
  - There is no separate list of presets beside the rows — the same list drawn
    twice is one list and one copy that goes stale. The active preset's colour
    is the dot on its row and the ink the whole plan is drawn in.
  - **Any number of recordings can be unfolded at once**, and the list is as
    long as it needs to be. Both were tried the other way — one open at a time,
    three rows then scrolling — and both were wrong: comparing two readings
    means reading both, and a slot that scrolled inside itself hid readings
    behind a bar of its own. The channel scrolls if a step outgrows it.
  - ✕ forgets a recording whatever has been done with it. Nothing names a
    recording except the step itself, so what is left becomes active and the
    plan follows it. **Forgetting the last one takes the plan with it** —
    regions and grid positions included, not just the tiles: a field says what
    to image and with what, and with no preset left there is no with, so
    outlines kept on the canvas would be a picture of a plan the run could not
    run.
  - The slot is `{ type, from, records, active, seq }` in `lib/recordings.js`,
    with `withRecording` / `withoutRecording` / `withActive` returning new
    slots. Ids are counted, never positional, so a forgotten record cannot
    hand its id to the next one. `from` is which of the mock controller's
    states the slot's first reading comes back as — the acquisition type reads
    from a different one than the overview preset, so a plan that never
    switched objectives cannot look like one that did.

- **The carrier types read Area · Dish · Chamber · Wellplate**, wellplate at
  the right end. **Volume is gone for now** (2026-08-20) — the type, its
  cuvette preset, its icon and its tests. What it needed from the frame is
  still there and unused: a type may declare `deep`, and a carrier with a
  depth is drawn as a box behind its footprint. Nothing on offer declares one,
  and a unit test says so, so the day a deep carrier comes back the frame does
  not have to be rebuilt for it.
- **Define Carrier** is a full designer, not a dropdown: type, preset,
  rows/columns, area size, pitch and corner, each pair tieable. It has **no tab
  and no picture of its own** — it is what the canvas is drawing, so the
  controls dock in a channel to the right of the canvas and the carrier itself
  is drawn on the stage. One drawing, not two.
  - The channel is **not a menu for step 3**. The frame outlasts the step that
    set it: readable whenever the canvas is.
  - **No Apply button.** Configuring is the work, the way recording is — it always holds a valid carrier and every edit is already on the canvas.
    Standing on the step settles it. It stays editable until a later step has
    run, since that is when changing it would invalidate what was done.
  - `widgets/carrier.js` holds the controls *and* `drawOn` — one subject, one
    file — over the geometry in `lib/carriers.js`. It is the first extracted
    widget and the shape the rest should follow.

**Two panels worth understanding**

- **Focus strategy** works on the position list, not on imagery. Model chosen
  by geometry, matching `workflow/_focus_surface.py`: constant / least-squares
  plane / thin-plate spline, smoothing 0.1. Both sharpness metrics are drawn on
  one plot and the legend is the control. Peaks narrower than 4.5 µm are not
  tissue and are rejected but still drawn; dragging the line overrules the pick
  and the preview beside it defocuses as you drag.
- **Detection** is tuned on one tile before it may run the sample.

## How this user works — read this, it will save a cycle

- **Simplify wherever it makes things more powerful.** Fewer options. Better to
  add one later than ship one that has to be removed.
- **No redundancy.** One owner per fact. If a constant or rule needs to exist
  twice, the split was wrong — merge it back. Redundancy creeping in is the
  signal that something is over-split.
- **Nothing fixed in place.** A value typed at the point of use is a value in
  the wrong module. Derive it, or give it an owner.
- **Do not over-test at prototyping pace** — but do test before building
  further on something. The browser suite is a smoke net, not a specification.
- Expect **many small steering messages**, often mid-turn. Apply them, run the
  suites, commit, and say what changed. Small commits, each green.
- Screenshots are worth taking and *looking at*: several real defects here were
  invisible to assertions.

## Defects this shape has produced twice — watch for them

- **Re-rendering on input destroys the field being typed into.** Fixed for the
  password and the preset name by updating only what depends on the value.
  Any new form field will do it again unless handled.
- **Alignment drifts from structural causes**, not wrong numbers: a
  `grid-column` on a child of the wrong grid conjured an implicit column; a
  label sibling to a list inherited a different gap than one inside a group.
- **An explicit `display` beats the `hidden` attribute** — `.action-bar[hidden]`
  needed saying, and `.panel-foot:empty` does now.
- **A stray `}` in the stylesheet silently ate every custom property after
  it.** The channel and its heading came out 461px and 156px instead of 320,
  both falling back to content width, and the page looked plausible. Measure
  in the browser; do not trust the eye for widths.
- **A fixed-height child overflows its panel and swallows clicks** on whatever
  is beneath it. The focus trace strip did this to Apply strategy; the browser
  suite caught it as a click timeout naming the intercepting element.

## The state of the code — the important caveat

`frame/window/main.js` is **4,483 lines and runs the whole page** — read
section by section, about 70 % of it is the target-acquisition run (focus,
detection, gating, the gallery, the session card, the stage picture, the
synthetic sample) and about 30 % the engine the folders say the frame is.
The two are interleaved in one module scope (`state`, `sample`, `view`,
`stageCv`, `backend` are module-level singletons; `drawStage` has ~30 call
sites). `docs/design/dissolving-main-js.md` maps every section with line
ranges and says in what order they leave; read it before touching `main.js`.

The tree as it exists (2026-08-26; no `src/`):

| part | state |
|---|---|
| `workflows/target_acquisition/shared/carriers.js`, `shared/scanfields.js` | tested and **used** — by the page and the carrier / scan-area widgets |
| `workflows/target_acquisition/microscope/recordings.js`, `microscopes.js` | used |
| `workflows/target_acquisition/microscope/pretend-sample/{surface,sweep}.js` | tested and **used** by the page (one owner each) |
| `workflows/target_acquisition/microscope/pretend-sample/sample.js`, `microscope/mock.js` | tested; **not imported by the page** — the page rehearses with a plan-driven sample of its own in `main.js` (the one fact still written twice, plus its focus tilt a third time in `mock.js`) |
| `workflows/target_acquisition/microscope/live.js` + `workflow/webapp/bridge.py` | the backend seam for the mock and real workflows; one day old |
| `workflows/target_acquisition/steps/{2_define_carrier,3_define_scan_area}/widget.js` | the two extracted widgets — the pattern the rest should follow |
| `frame/rules/steps.js`, `frame/rules/finding-workflows.js`, `workflows/*/flow.js` | used: numbering, readiness, panels; the folders are the only declaration of the workflows |
| `index.html` | frame markup plus four parked blocks of one workflow's controls (`#focus-controls`, `#detect-controls`, `#analysis-controls`, `#gallery-controls`) that widgets move into the channel on mount; also references `#stage-layers`, which does not exist, so the layer bar has never rendered |

What a step *does* is still decided by seven `if`s on `mode` inside
`runStep` (443–561) plus ten more `mode` guards elsewhere, where the design
says a step carries its own `run(ctx)`. The three target-acquisition
workflows (`_prototype`, `_mock`, `_real`) share one step list
(`the-run.js`) and differ only in the backend line of their `flow.js`; that
stays.

Tests: `tests/unit/**` (vitest, 227) and `tests/*.spec.js` (Playwright, 62).
The rule going forward is that a test lives beside what it tests
(`frame/tests/`, `workflows/<name>/tests/`); the move is step 0 of the plan.
`tests/operator-page.spec.js` "focus points are laid so many to a tileset"
is a stopwatch flake on this machine (`waitForTimeout(1600)`), not a
regression.

**A widget owns its panel and redraws itself.** `steps/2_define_carrier/widget.js`
is the pattern: handed a value and a callback, knows nothing of run state,
and writes new values into the controls that already exist rather than
rebuilding — a rebuild per keystroke destroys the field being typed into.
It exports `drawOn` too, because the controls and what they put on the
canvas are one subject.

## Open questions — ask, do not invent

- Which preset the *acquisition* uses. The scan side is answered: the plan is
  taken with the active acquisition preset, and the tiles covering a field are
  that preset's frame — a number on the reading rather than words inside its
  detail line. Nothing yet says which preset step 9 images cells at, and the
  autofocus and acquisition-type slots keep an active recording that nothing
  downstream reads yet.
- **Where the carrier sits on the stage** is centred in the travel, and that is
  a default rather than an answer: the real offset comes from calibrating
  against a plate actually on the stage. `carrierOriginUm()` is the one line
  that answer replaces, and everything the run produces is placed through it,
  so the carrier and what was imaged inside it move together.
  `STAGE_LIMITS_MM` (120 × 80) is still a placeholder, standing in for what the
  controller will report.
- The synthetic sample is still a 7×5 tile grid unrelated to the carrier, so
  the scan area sits in the plate's corner rather than inside a well.
- Should the canvas show the planned tile grid before the scan, or stay blank?
- A single click in the focus trace jumps the line; it is not drag-only.
- The focus step wants ≥3 points, but `_focus_surface.py` accepts 1.
- `lib/microscopes.js` now carries microscopes, APIs, connect checks, setting
  types and carriers — more than its name promises. Wants splitting by subject.
- The password is prefilled (`demo`) for clicking through. **A real build must
  ship that empty.**

## The north star — context only, out of scope

Eventually an agent composes workflows: you describe a run and it assembles the
steps and the right-hand panels. That is why steps and panels are declarations.
The boundary to protect: **a workflow declares, the frame owns.** Declarations
get ids, titles, sentences, button labels, prerequisites, and which panels from
a fixed registry. The frame keeps the canvas projection, layer compositing,
selection state, the ordering guard, and every hardware call.

`backend/` is the seam where the real microscope arrives. Steps call the
backend and await — never a timer, never hardware. If wiring a microscope ever
means editing a widget, the seam leaked.
