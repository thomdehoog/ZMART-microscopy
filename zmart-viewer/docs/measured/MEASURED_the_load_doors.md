# Measured: the load window's doors, 16 to 1,024 positions

> Measured 2026-08-18 by `measure_the_load_doors.py` on a Linux container
> drawing in software (headless Chromium, SwiftShader). As with the survey
> ladders beside this note: the shapes and ratios are the evidence, the
> absolute milliseconds belong to whichever machine runs it. To repeat it
> on the workstation::
>
>     python zmart-viewer/app/picture/measure_the_load_doors.py --fixtures D:/zmart-doors

Where the survey ladders measure the live path, this measures the
OPERATOR's path: every number below went through the same HTTP doors the
load window drives — the folder listing, the build without and with the
hard copy, opening through `/api/stores/open` exactly as Show does, and a
real page opening the baked scene. The fixtures are two-channel,
two-plane, 384-pixel positions on a 320 µm grid, so the bake is the
per-frame bake writing every (moment, channel) piece as its own file.

| positions | write s | list ms | linked build s | baked build s | open linked s | open baked s | to group s | ready s | pan ms |
|---|---|---|---|---|---|---|---|---|---|
| 16    | 0.0  | 4 | 0.11 | 0.31  | 0.04 | 0.05 | 0.22 | 0.23 | 117 |
| 64    | 1.3  | 5 | 0.11 | 1.24  | 0.02 | 0.05 | 0.16 | 0.17 | 153 |
| 256   | 6.0  | 3 | 0.22 | 5.01  | 0.02 | 0.06 | 0.41 | 0.42 | 171 |
| 1,024 | 24.0 | 4 | 1.07 | 19.36 | 0.02 | 0.06 | 0.16 | 0.16 | 185 |

What the table says:

- **The linked build is effectively instant at every rung** — one second at
  a thousand two-channel positions. The window's claim that the plain
  build "is immediate" holds through the whole ladder.
- **The baked build is honestly linear** (~19 ms per position here, two
  channels of frames each) and never blocks anything: it runs behind the
  progress bar and the operator can keep working. In camera terms this is
  the one-time cost the pane's info line describes.
- **Opening a built scene is flat.** Whether linked or baked, 16 or 1,024
  positions, `/api/stores/open` answers in under a tenth of a second and
  the page shows the group in under half a second — the written-down
  geometry (`tiles.json`) doing exactly what it was built for.
- **Responsiveness degrades only gently with scale.** The drawn-frame time
  while panning grew 117 → 185 ms across a 64-fold spread of positions —
  and those absolutes are software rendering; on the workstation's card the
  same probe should sit far below them. The shape (sub-linear growth) is
  the finding.

## Quirks found by the run, and their state

- **Broken-pipe tracebacks on every page close** — the server printed a
  full `BrokenPipeError` traceback each time a browser disconnected while
  an answer was in flight. The hang-up tolerance existed in
  `handle_one_request` but the constructor's final flush escapes it.
  FIXED the same day: `finish()` now carries the same tolerance
  (`server.py`), citing this run.
- **A replayed channel opens on the full-range window**, so a replay looked
  black until Auto was pressed. FIXED with the watchable-replay chapter:
  the writer's full-camera-range window is its way of declaring ignorance,
  so the reader now treats exactly that as "no window asked for" and every
  layer rests at the measured window instead (`restingWindow` in
  scene.js, shared with the panel's sliders). Any run written without a
  window benefits, not just replays. (Since the timelapse-replay chapter a
  replay is served as a LIVE run -- the run root is opened and bound, so
  the time slider offers only the written moments and follows the front.)
- **A replay does not frame itself** — the view stayed where it was, and
  the operator pressed Overview to see the landing tiles. FIXED the same
  day: starting a replay is an explicit ask to watch something, so once
  its images answer, the view steps to the first plane and moment and
  frames the whole picture (`watchTheReplay` in engine.js). Pinned by the
  hands-off gate: press Replay, touch nothing, and a healthy share of the
  canvas must light up with the landing tiles.
- **A running build or replay cannot be cancelled** from the window; the
  only path was waiting it out. FIXED with the stop chapter: both doors
  take a cooperative stop (`construct-cancel` / `replay-cancel`), read
  between steps so nothing is torn mid-write. A stopped build removes its
  half-made scene whole (pieces without a description are not a scene); a
  stopped replay keeps what landed, which is a real run that still opens.
  The window offers Stop beside the progress bar and on the other tab
  while a replay runs. Pinned by the abuse battery and two browser gates.
- **A plate store selected on the view/other tab** opened through the
  plain library door rather than the plate layout, drawing every well at
  the origin. FIXED with plate rung 2: the open door notices a plate,
  builds (or reuses, baked ground and all) the scene beside it exactly as
  the build tab would, and serves that -- the laid-out plate reaches the
  screen whichever tab opened it. The same chapter taught the layout to
  keep the places a writer recorded for its fields (squarest grid only as
  the fallback), to space wells by their actual extent, and to treat
  local and global field translations identically by anchoring each
  well's content at its own cell. Screenshot-inspected both ways.

## Quirks found with real data at the workstation, 2026-08-19

The doors met their first real datasets: a six-tile 25x Thy1 survey
(291 planes of 5056 x 2960 each), a 336-well two-channel HCS plate, and
an 18-channel fused overview plate. Two defects fell out before any
picture was on screen, both fixed at the cause the same day:

- **A real exported survey could not be built at all.** The Thy1 run is
  one OME-Zarr group -- a plain group file at the top, one store per
  position inside, exactly the shape our own live writer's containers
  take. The folder listing called anything with a description file
  directly inside a "store", so the build tab fell silent when the run
  was selected: the row highlighted and nothing else happened, no second
  step, no message. The backend's construct door built the very same
  folder without complaint, so the misclassification was the whole
  refusal. FIXED in the listing: "store" now means the description
  declares one picture the viewer draws whole (an image's multiscales,
  or a plate); a bare wrapper group falls through to the ordinary
  position-stores check and answers "folder", which is what it is.
  Pinned red-first by test_the_list_door_tells_raw_from_image.py.
- **Choosing a folder with the system chooser broke on Windows paths.**
  The page landed the listing on the picked folder's parent by slicing
  the path at its last "/" -- a Windows path has none, so the slice cut
  the last letter off the path instead, the listing showed a folder that
  does not exist, and the picked run never appeared as a row. Four gates
  in test_open_and_close.py were red on this machine and green in the
  Linux container because of exactly this. FIXED at the cause: the
  browse door answers the parent alongside the path (Python's own path
  rules, never the page's), and the page navigates to the server's word.
  Pinned in test_library.py::TestChoosingAFolder. A wrapper in App.jsx
  (tryNativeChooser) was quietly dropping every key but ``path`` from
  the door's answer -- worth remembering when the door learns new words.

With the listing fixed, the real survey built through the window with the
hard copy in 8.5 s (six tiles of 291 x 5056 x 2960), opened in 0.14 s, and
drew real neurons at its true stage coordinates (thy1_8_framed.png in the
session's D:/zmart-realdata-validation). Two more findings from the same
build:

- **The scene wore its suffix twice.** The scene folder is named
  ``<name>.ome.zarr`` and the real run is itself called
  ``Thy1_Mag25x_Ch561.ome.zarr``, so the scene landed as
  ``...ome.zarr.ome.zarr``. FIXED: one rule, ``the_scene_folder_name`` in
  declare.py, now composes every scene folder name and every lookup of
  one (the plate reuse, the cancelled build's cleanup), wearing the
  suffix exactly once. Pinned in test_a_transfer_is_built_into_one_picture.
- **OPEN -- Show leaves the camera where it was.** A shown scene at real
  stage coordinates (here 15 mm from the origin, z translated -15.6 mm)
  stays black: the view is parked at the origin and the focal plane is
  outside the stack. Overview recentres x and y but never z, so even the
  operator's natural recovery ends on blackness between acquisitions.
  The replay chapter answered this for replays (watchTheReplay: an
  explicit ask to watch is followed by the camera) -- Show and Open
  through the window are the same ask, but the whole-picture framing the
  replay uses would frame the VOID when a far acquisition is also open
  (hidden layers still count in the global bounds). The honest fix frames
  what was just opened -- per-layer extents said by the server, aimed by
  the engine -- and that interacts with replay framing and
  multi-acquisition semantics, so it is a designed chapter with a review,
  not a patch. Until then: open the window, close what you are done
  with, Show, press Overview, and bring Z inside the stack by hand.

The real plate (336 wells, 16 x 24, two channels of 4096 x 4096 fields)
found three more, the first two fixed the same day:

- **A real plate could not open at all.** The open door declared the
  plate's scene over the plate's PARENT folder, and a real plate lives
  beside the rest of the day's work -- here two plates, a survey and
  loose images -- so discovery refused the folder outright. Real plates
  are also named ``something.zarr``, which the ``*.ome.zarr`` suffix
  globs never matched. FIXED at the cause: the layout reader recognises
  a folder that is itself a plate (its own description says so, the
  name and the parent say nothing), the open door declares the scene
  over the plate and names it after the plate, candidates inside a
  folder are matched on the wider ``*.zarr``, and the relink judgment
  follows the same rule. Pinned in test_a_plate_lays_itself_out.py.
  With the fix the plate opened through the window in 3 s.
- **An unbaked scene opened at the camera's full range** -- a near-black
  grid, an empty histogram, a dead Auto, and no remedy but typing
  numbers. The open door declares every plate's scene without the hard
  copy, so this was every real plate's first look. FIXED the way live
  pictures were: the measurement follows the picture's own composer
  (``values_for`` on the composer, ``a_sample_behind`` in served,
  contrast's hollow-picture fallback), sampling the coarsest level's
  central pieces in milliseconds. Pinned red-first by
  test_an_unbaked_scene_opens_at_a_measured_window. With both fixes the
  real plate draws every well's monolayer at a measured 129-298 window.
- **What the unbaked plate costs, measured.** The composed scene keeps
  only the five levels its fields carry (4096 down to 256 per field),
  so its coarsest level is still 3850 x 6615 -- a whole-plate look is
  ~104 pieces of 512 composed on the fly, per channel, and the
  picture's own coarser levels above the fields' exist only when the
  hard copy is baked. Measured here: 1.2 s cold for one channel's 104
  pieces, 0.43 s warm -- tolerable on this workstation's local disk,
  paid again every session, and the reason the hard copy stays the
  recommendation for big formats. The remedy was then measured on the
  same plate (under concurrent test-suite load, so upper bounds):
  linking 0.52 s, baking the hard copy 6.2 s once (583 files, 125 MB,
  a fraction of a percent of the plate), opening the baked scene
  0.10 s, opening the plate itself with the baked scene reused 0.11 s.
  Six seconds once against a per-session compose is the info line's
  recommendation, confirmed on real data.
- **OPEN -- a heterogeneous plate is unioned in silence.** This real
  plate holds two kinds of acquisition: 268 fields of (c, y, x) with two
  channels and 134 fields of (t, c, z, y, x) with four. The composer
  quietly took the union -- one heading, four channels, the two-channel
  wells simply dark in channels 3 and 4. The viewer's own principle
  (an overview and a target scan are two pictures, each its own
  heading) suggests a plate of two kinds should split or refuse loudly;
  either is plate rung 3 design work, not a patch. The channel rows
  also wear generic names ("channel 1") and grey swatches -- the wells'
  own channel descriptions are not consulted.

The replay and stop doors, exercised the same day:

- **The replay door refused the real survey exactly as declared.** Fed
  the six-tile Thy1 run from the other tab, it answered in the window:
  "this dataset's frames are 5056 by 2960 pixels, and the replay of
  rectangular frames is its own chapter. Replay a square-framed dataset,
  or open this one instead." Nothing written, nothing crashed. The
  rectangular-frames chapter stays open work; no real timelapse (t > 1)
  exists on this workstation's data disk, so the growing-slider replay
  was exercised on a synthetic timelapse: the slider grew from one
  moment to two as sweep two began, and the value followed the front.
- **Stopping holds on real data.** The real Thy1 bake stopped at 25%
  through the window: state "cancelled", the half-made scene removed
  whole. A timelapse replay stopped mid-sweep kept its numbered run,
  one position finishing whole after the click.
- **A finished replay could not be opened again.** The window promises
  the replay writes "a real run ... so it can be opened again later",
  and later never came: the run root holds ``data`` beside ``views``
  and no image directly inside, so the plain door answered "no OME-Zarr
  image was found". The old gate checked the files were kept and never
  reopened them. FIXED: the plain door recognises a live run's root and
  opens it the way the replay door itself does -- served view named, so
  the registry binds it and the slider offers exactly the landed
  moments. Pinned red-first by
  test_a_finished_replay_opens_again_later.

Looking at the served plate with operator's hands (2026-08-19 evening)
found three more, one fixed:

- **OPEN -- only the topmost channel of a stack is visible.** The flat
  shader's transparency answers "was this spot imaged" (the coverage
  design scene.js documents), so on a four-channel plate the top
  channel is opaque over every imaged spot and the three beneath do not
  reach the screen at all. Measured decisively: recolouring channels 1,
  2 or 3 changed not one pixel of the blend; recolouring channel 4
  turned the picture green. This is why "changing the LUT does
  nothing": the recoloured channel was covered. Additive blending was
  rejected in scene.js for a real reason -- overlapping TILES within a
  row would sum into bright seams -- but that objection does not reach
  rows that pick their channel out of one shared store (a composed
  picture's rows have one source and no seams). Whether channels of one
  picture should sum like light while separate acquisitions keep
  covering each other is a compositing design chapter with a review,
  not a patch. Until then the operator's remedy is the eye: hide the
  channels above the one being looked at.
- **The lit Auto button could not be un-clicked.** The light means "the
  window is the measured one" and clicking it puts back the window the
  run declared -- and a run that declared nothing is served the
  measured window AS its window, so the button toggled between two
  equal values and visibly did nothing. FIXED in the panel: with
  nothing to restore, the lit button rests disabled and its tooltip
  says the run declared no other window. Pinned red-first in
  test_layer_panel.py::test_a_lit_auto_with_nothing_to_restore_says_so.
- **The contrast sliders' reach was checked and is honest.** On the
  served plate the MIN and MAX tracks span each channel's own measured
  range plus a fifth of headroom (channel 1: 0 to 313 for a window of
  10 to 225), not the camera's 65,535. The full-range track the
  operator saw belonged to a page served before the plate had its
  measured window.

The full suite then ran on this workstation: 1,591 passed and three
stood red -- all three present at bd5f5c39 before this session touched
anything, all three run to ground the same evening:

- **The opening zoom raced the panel's layout.** The whole-picture fit
  divides the picture's extent by the panel's size in pixels; a reload
  finds every answer in the browser's cache, the sources settle before
  the panel has a size, and the fit quietly became the engine's default
  zoom. Measured stable both ways: the same grown picture opened at a
  50 um scale bar warm and 100 um after F5, fourteen seconds steady
  each. FIXED in chooseScaleWhenTheImagesAreMeasured: the fit also
  waits for a laid-out slice panel (the settling watch already glances
  every quarter second). A first load never hit this because the
  network is slower than the layout -- which is why the container
  stayed green while the workstation went red.
- **The claim gate trusted the wrong pid.** On Windows a virtual
  environment's python.exe is a launcher that starts the real
  interpreter as its own child, so Popen.pid named the launcher while
  the claim file honestly named the interpreter. The refusal was
  correct all along; the GATE now compares against the pid the child
  itself reports.
- **The real-share mesoSPIM gate gave the page 30 s to boot** while
  booting includes the server measuring a cold store over the Z:
  share -- the very reading the gate's own chunk-waiting budgets 180 s
  for. One patience for both now; the suite's end-to-end read off the
  real share passes in ~90 s here.

The operator then drove the served plate and asked for three changes,
all landed the same night (the fourth finding was the browser page's
folder chooser):

- **Channels of one picture sum like light.** The compositing chapter
  closed the day it opened: the operator confirmed the additive merge
  every fluorescence viewer does is what they expect. Additive is set
  exactly where it is safe -- rows with ONE source, which is every
  composed picture -- and rows stitched from many tiles keep the
  covering rule (their overlaps would sum into bright seams, the
  recorded reason additive was once rejected). The blend travels with
  every settings write, so a live row that grows past one source falls
  back to covering. Seen on the real plate: green monolayer, nuclei
  white-pink where the magenta channel adds, and with all four white
  channels visible the sum honestly clips -- windows are the remedy,
  as in napari. Pinned by test_channels_of_one_picture_blend_like_light.
- **The brightness axis runs to the camera's whole range.** This
  reverses the handles-stay-near-the-data rule, and both decisions were
  the same operator's: the headroom-before-saturation reading is what a
  histogram is for, and the Log axis now makes the wide track workable.
  The server says each layer's range from the store's own number type
  (contrast.camera_range); floats keep the measured span. The histogram
  draws its measured bins at their true place on the wider axis.
- **Auto is a true toggle.** Off spreads the window over the camera's
  whole range -- everything shown, nothing clipped -- unless the run
  declared its own window, which then comes back. Verified on the real
  plate: off to (0, 65535), light out; on re-applies the measurement.
- **A browser-served page gets a real folder chooser.** The viewer
  binds to localhost, so whoever sees the page sits at this machine --
  and ask_this_machine_for_a_folder opens the desktop's own dialog for
  it (the launcher's no-native-window fallback uses it too). Before,
  the page asked the operator to type paths by hand, which read as a
  viewer with mock capabilities.

## Channels mix, 2026-08-20

The four-channel plate showed one channel: the top one covered the rest, so
recolouring any other changed not a pixel. Two reviews were run with orders
to treat the code's comments as history rather than law, and the design was
rebuilt against the engine's own source. What was found and done:

- **The engine's own multichannel display contradicted most of our commented
  rules** (`layer/multi_channel_setup.js`, sitting in node_modules all
  along): additive for every channel layer including the bottom one, colour
  carried as a control, no coverage transparency, opacity pinned at one. The
  viewer had reasoned its way to the opposite of each, at length, and the
  prose was persuasive enough that every later change bent around it.
- **One program cannot read two channels of our data.** The plan's better
  arrangement -- one layer per picture, channels mixed inside -- died on a
  measurement: a brightness control binds to a CHANNEL dimension, and an
  OME-Zarr `c` axis arrives as a LOCAL one (channel rank nought,
  `channel=[1]` refuses to parse). This is why neuroglancer splits channels
  into layers too.
- **Built: stock neuroglancer's shape.** Channels add between layers;
  colour, weight and window all travel as controls to one shared program;
  the weight is carried once, which retired a fade that squared its own
  setting (measured at a half reading a third).
- **Nothing is scaled to fit, by the operator's own rule**: the display must
  be a fact about the data and the dials that were set, so hiding a channel
  may not brighten the others. The mix clips and white points are the
  remedy -- as ImageJ, napari, OMERO and vizarr all do. Photographed on the
  real plate: four dense channels at their measured windows are pure white;
  each white point raised about fourfold and the same wells read as a true
  composite.
- **The Log brightness axis now turns on by itself** where the camera's
  range dwarfs the measured spread, which is what keeps the full-range axis
  usable while a white point is being brought down.
- **Three older gates moved to the new ownership, and one fell to the
  meta-gate.** `test_no_setting_is_dropped_on_the_way_to_the_engine` caught
  the blend a row is drawn with being added to a description with no line in
  the engine to carry it -- exactly the dead-control fault it exists for, and
  it found it the first time it ran. Unnamed channels no longer all open
  white (several white channels add to a flat glare, and recolouring one
  cannot help when they are all alike); a lone unnamed channel is still left
  plain. And the reveal-beneath property was restated for a regime that adds:
  while channels covered one another, fading the upper one had to BRIGHTEN
  some colour band, and now nothing can brighten -- what a fade must not do
  is eat into what the channel beneath contributes.

- **The spiral-growth gate is load-sensitive, and it cost an hour of wrong
  diagnosis.** `test_the_spiral_growth_is_visible` failed in the full suite
  and again in an isolated rerun, and the isolated rerun looked like proof
  the mixing chapter had caused it -- until the comparison was checked: the
  supposed baseline ran on a quiet machine while the supposed culprit ran
  beside another browser suite. Measured properly afterwards: 3 of 3 passes
  on a quiet machine WITH the chapter, 0 of 2 under concurrent load, and the
  gate polls for growth against a 30-second deadline with a 2-percent
  regression threshold. It is timing, not the change. Anyone bisecting a
  browser gate here should hold the machine's load constant across both
  sides, which this session did not.

- **OPEN, held as a strict expected failure:** a picture written as
  overlapping positions still cannot mix its channels, because adding is a
  property of a layer and a layer fed by several stores would sum their
  overlaps into seams. The cure is the composed picture the server builds.

The `settled` column of the raw run (five seconds at every rung) is a
fixed four-second wait inside the instrument plus readiness, kept out of
the table above because it measures the harness, not the viewer.

## The abuse battery, same day: two defects found by testing to falsify

`test_the_doors_survive_abuse.py` feeds every door exactly what nobody
should ever feed it. Its first pass found two real defects, both fixed at
the door the same day:

- **The construct name walked out of the scene folder.** Fed `../escaped`,
  the scene landed beside the folder the operator chose — anywhere the
  server can write. Names carrying path steps are now refused.
- **A negative replay pace killed the replay thread** on `time.sleep`'s
  raw refusal. The pace is clamped at zero.

The same pass hardened the gates themselves: the replay's pixel identity
is now pinned per position (a replay mapping a position onto the wrong
cell passed every count before), the plate layout is pinned
pairwise-disjoint, a 0.4 plate lays out identically to a 0.5 one, wells
without indices take their place from the plate's rows and columns lists,
and the per-frame bake gate was sabotaged once as evidence — two baked
channels swapped on disk — and went red, proving the gate can see the
failure it guards.

## Auto measures the part of the picture on screen (2026-08-20)

Auto used to answer with the whole picture's window, computed once at load.
On a 336-well plate that is a reading of the whole plate: press it while
looking at one well and the numbers had almost nothing to do with what was
in front of the operator. Auto now takes a fresh reading of the region in
view, every press.

**Where the work is split.** The panel knows *where* it is looking; only the
server has the pixels. So the panel sends the region as fractions of the
picture's own bounds -- `[[top, left], [bottom, right]]` -- and the server
reads there. Fractions rather than voxels, so the engine's arithmetic about
zoom and canonical voxel factors lives in exactly one place
(`whatIsOnScreen` in `engine.js`), and the server needs to know nothing
about how the view is arranged.

**Unimaged ground gets no vote.** `measure_here` drops every value equal to
the array's fill value before taking percentiles, so a view half off the
edge of a survey is windowed by the imaged half. A view holding *no* imaged
pixels answers `{"empty": true}` and the picture is left exactly as it is:
a press that measured nothing has nothing to say, and moving the operator's
window in answer to it would be worse than doing nothing.

**The light now says something narrower.** It used to be on at rest, because
a run that declares no window is served the measured one AS its window and
the two matched -- so the operator's first press was a press of a lit
button, which turns Auto *off*. The light now means "this window is the
brightness of what you are looking at, because you asked for it": off at
rest, on after a press, off again on the second press (which spreads the
window over the camera's whole range, or restores the window the run itself
declared).

**Measured on the real plate** (`HA-1a_Plate_4561`, 4 channels): whole-plate
window 10-900 with the histogram a single spike at the dim end; zoomed into
six wells and pressed, 10-218 with the cells' own distribution filling the
axis. Server side the reading costs one coarse-level read -- the plate's L8
chunk comes off the door in under 20 ms.

### Two traps that cost an hour, both in the harness rather than the viewer

- **`vite build` alone is not the build.** The script is
  `precompile-workers.mjs && patch_neuroglancer.mjs && vite build &&
  copy-async-worker.mjs`. Skip the last step and `async_computation.bundle.js`
  is missing from `dist/`: chunks arrive with 200s, nothing decodes, and the
  canvas is black with no console error, because the failure is inside a
  worker. It reads exactly like slow composition. Two quick tells: a 404 on
  `/async_computation.bundle.js`, or timing a coarse chunk straight off the
  HTTP door (which answered in milliseconds throughout).
- **A canvas read from JS is always black.** Neuroglancer does not preserve
  its drawing buffer, so `drawImage` into a scratch 2D canvas returns black
  even while the picture is plainly on screen. Waiting on such a readback
  just hangs; only `page.screenshot()` sees the picture.

## One Overview, and the histogram takes the panel (2026-08-20, same evening)

**Reset is gone; Overview does what it did.** The pair differed only after a
volume had been tilted: in 2-D they were the same press, so one face meant
two things depending on where the operator was. Overview now puts the whole
view back -- straight, centred, sized to the window -- in both views, and
still leaves the plane and the moment alone. The three gates that drove
Reset now drive Overview; `putTheViewBack` is the one function behind it.

**The histogram spans the panel.** Auto and Log used to stand in a 60-pixel
column beside it, taking a sixth of the picture to say four letters each.
They now sit under it, between the two boxes that set the drawn stretch of
brightness: `[from] Auto Log [to]`. Measured after the move -- picture 242 px
wide (was 176), its ends and the two boxes' outer edges within 2 px of each
other.

## Auto reads a copy of the picture that can still answer (2026-08-20, late)

Zoomed onto one nucleus and pressed, Auto turned the picture into two
colours: everything either black or saturated. The window it set was
157-175 on a plate whose pixels there run 114-213.

**Two faults, one behind the other.**

*It read the coarsest copy that held pixels.* That was deliberate -- a
button pressed by hand should read as little as possible -- and it is right
exactly while the whole picture is on screen. The coarsest copy of the
HA-1a plate is 241x414 for the whole tray, so a box around one nucleus
covered ONE pixel of it, and the 1st and 99th percentile of a single number
are the same number. The copy is now chosen by what the box covers on it:
coarsest first, taking the first one where the box still holds a 64x64
patch, and never reading more than 262,144 numbers per press.

*And the copy it needed holds no files.* A composed plate carries only its
baked levels as pixels -- here 4 through 8; levels 0-3 are declared and made
on ask, which is how the browser draws detail the folder does not hold. So
the measurement now asks the same door the browser asks: `the_values_inside`
builds the pieces overlapping the box (at most four, nearest the middle) and
crops them to the box.

**Measured on the plate afterwards**, box centred on one nucleus: 6,572
level-0 values, their 1st/99th percentile 122/176 -- and `measure_here`
answers 122/176. At the operator's own zoom the window came back 130-250,
the histogram filled its axis, and the nuclei showed their internal
structure against dark-but-not-crushed ground.

**The button is a plain press now**, not a light. It was briefly a toggle:
lit while the window matched its reading, a second press putting back the
run's window or the camera's whole range. Nobody presses Auto to undo it,
and a button meaning one thing on the way in and another on the way out has
to be remembered rather than read.

### Counting frames on a card measures the card, not the viewer

Moving the browser gates onto the machine's card (the operator's ask: draw
where an operator draws) quietly broke the two gates that count frames. A
card draws whatever is asked of it inside one frame and then waits for the
display, so both arms of the comparison came back at the refresh rate: 200
positions as separate stores drew 181 frames, the same positions as one
picture drew 180. That reads as "the per-position cost is gone" and is
actually "the clock ran out before the work did" -- and it turned the
standing xfail about that cost into a strict XPASS.

Both now take a `counting_browser`: software rendering on purpose, where
every frame costs what it costs. Everything else still draws on the card.
Proved not to be today's frontend work by rebuilding from HEAD and running
the pair again -- identical failures.
