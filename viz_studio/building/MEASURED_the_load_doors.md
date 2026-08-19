# Measured: the load window's doors, 16 to 1,024 positions

> Measured 2026-08-18 by `measure_the_load_doors.py` on a Linux container
> drawing in software (headless Chromium, SwiftShader). As with the survey
> ladders beside this note: the shapes and ratios are the evidence, the
> absolute milliseconds belong to whichever machine runs it. To repeat it
> on the workstation::
>
>     python viz_studio/building/measure_the_load_doors.py --fixtures D:/zmart-doors

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
