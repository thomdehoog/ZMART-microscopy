# The files the viewer needs — the contract, in plain terms

For anyone writing acquisition software that the ZMART viewer must be able
to show. A run is **one folder** holding **two things**, and one law binds
them.

## 1. `positions/` — the pixels

One OME-Zarr image per microscope position, named for its place in the
grid (`p00.ome.zarr`, `p01.ome.zarr`, …). Each is an ordinary zarr v3
image any tool can open, with:

- **five axes, in this order: t, c, z, y, x** — time and channel first,
  even while they are singletons;
- **a pyramid of levels** (level `0` full size, each next one halved in
  y and x by averaging), exactly as many as the run's sealed profile says;
- **its place written inside it**: every level carries a scale and a
  translation, and the translation must equal the layout's placement for
  that position times the voxel size — this is how the viewer knows where
  the tile sits without guessing;
- the profile's chunking and encoding (sharded chunks, uint16 here).

**Never overwrite a published position.** A retake is a new store beside
the old one — `p00.generation-1.ome.zarr` — plus a replacement commit in
the record below.

## 2. `zmart-live/` — the record that rules

The bookkeeping folder is the authority on what may be shown:

- `committed.json` — what is published *right now* (atomically replaced);
- `events.jsonl` — the append-only history, one line per publication;
- `layout.json` and `layouts/` — where every position the run will ever
  image sits, fixed **before the first pixel**;
- `profiles/` — how every store is written (frame, levels, chunking,
  number type), sealed with the layout;
- `publication.lock` — the writer's own lock; leave it alone.

## The one law

**Pixels first, record second.** Write a position's store completely, then
publish it with one atomic commit. The viewer believes the record and only
the record: a store on disk that was never committed is invisible, and a
committed store missing a chunk is treated as damage and refused — never
quietly filled in. Zero is the fill value, so an all-zero frame cannot be
published; write at least one.

## In practice

Do not write any of this by hand. `zmart_live`'s publisher
(`LivePublisher`) produces every file above correctly — layout and profile
sealing, pyramid building, translations, atomic commits, replacements.
This page exists so that any *other* writer knows exactly what it must
match, and so a reader of a run folder knows what they are looking at.

To show a run: declare it once (`viz_studio/building/declare.py`) and the
server serves the picture; each commit thereafter appears on screen by
itself. Announcing the commit to the running server
(`POST /api/announce`) is what makes it appear immediately rather than on
the next poll.

## What the viewer adds beside your data — and never inside it

The declared picture — the one the browser actually opens, with its
prebaked coarse levels — is a **separate store**, typically
`views/picture.ome.zarr` inside the run folder, beside `positions/`.
Nothing of the viewer's is ever written into a position store. The
declared picture is a valid OME-Zarr in its own right, but its metadata
says what it really is: derived ground, recording what it was built from
and which of its levels exist as baked files. The same holds for a
transfer served by pointing: the view store holds a small list naming
which bytes of which tile file each piece is, and the pixels are never
copied.

The consequence worth knowing: **the derived store is disposable.**
Deleting `views/` loses nothing but warm-up time — declaring again
rebuilds it from the positions and the record, which remain the only
truth. Your data and the viewer's cache never share a folder, so neither
can ever damage the other.

## Which layers promise interoperability

Interoperability is a promise, and a promise needs a boundary it is made
at. The recommended rule for everything built on this contract:

- **Pixels are interoperable at the position store.** Each
  `p*.ome.zarr` is plain OME-Zarr with canonical axes and its placement
  in its own translation -- the form stitching tools such as
  multiview-stitcher consume directly. This promise deserves a standing
  test through an independent reader (the `test_other_tools_can_read_us`
  pattern), and tools with their own native formats (BigStitcher's BDV
  XML) are served by small exporters written FROM the record, never by
  bending the stores toward them.
- **Structure is interoperable at the filesystem.** Runs group into
  plain folders -- an experiment holding sibling acquisitions, each named
  for what it is, each carrying its own `positions/`, `zmart-live/` and
  `views/`. The profile already records the acquisition type. No zarr
  group wraps any of this: a level that holds no pixels gains nothing
  from being zarr, and a human with a file manager is also a reader.
- **Everything in between is ours.** The `zmart-live/` records may
  evolve; outsiders who need their content get it through exporters or
  the gateway, not by reading the files as a stable format. And
  `views/` is openable but disposable by contract -- nothing should ever
  be built on a cache.

## The shape of an experiment

Acquisitions group into an experiment as plain folders, each acquisition a
complete run named for what it is and numbered, because an experiment
routinely holds several of the same kind:

    experiment-2026-08-15/
    ├── overview-1/            one acquisition = one complete run
    │   ├── positions/           the pixels (interoperable, immutable)
    │   ├── zmart-live/          the record that rules (ours)
    │   └── views/               the viewer's cache (disposable)
    ├── targets-2/
    │   ├── positions/
    │   ├── zmart-live/
    │   └── views/
    └── ...

Every acquisition carries all three -- the record is not optional and not
shared, because each run's layout and profile are sealed on their own. The
acquisition's TYPE lives inside it (the profile records it), never only in
the folder name. And when acquisitions cause one another -- an overview's
detections spawning target scans, which is the whole point of a smart
microscope -- that provenance belongs in a small record at the experiment
level, beside the acquisition folders: plain JSON, ours, following the
same rule as everything else here. Folders give structure, records give
truth, and zarr appears only where there are pixels.

## Sealing a view makes it shippable

A view becomes a complete, standalone thing through one gesture: sealing.
Sealing waits for the patch in flight to finish, then writes the slice of
the record the view has absorbed -- which positions, which generations, as
of which revision -- into the view's folder beside the store. A sealed
view folder can be copied to another machine, shared with a collaborator,
or archived, carrying its own truth with its moment declared. Frozen
views (exports, report crops) are born sealed; the live view is sealed
whenever it is handed off, typically when the acquisition ends. Note that
a LIVE view cannot be shipped mid-run wherever its truth lives -- its
baked files are being rewritten under any copy -- so sealing is not a
restriction added to shipping but the honest name for what shipping a
changing thing always required: a moment of quiet, stamped.

Sealed is complete in MEANING, not in pixels, and that is the point: a
sealed view carries its truth-slice and its baked coarse levels -- the
whole survey at overview zoom, a few percent of the data -- while its
fine levels remain addresses that resolve through the run's positions.
Views are as self-contained as they can be without carrying data they do
not need. When one genuinely must stand alone at full depth, that is a
third, explicit gesture -- materializing, which bakes every level into
the view at full data cost, opt-in for the rare view that earns it. The
ladder is: bookmark (live, follows the run), sealed (complete in meaning,
light), materialized (complete in pixels, heavy) -- each step a choice.

## The canvas comes first, and every view sticks to it

The coordinate system is not defined by any view. It is designed by the
process that comes before everything -- the controller that plans the run
-- and sealed into the layout and profile at the start: this world, this
size, these planned places. The run is born into that canvas. An empty
run is a valid empty canvas, every landing fills ground that already had
its address, and the canvas can never move, grow, or shrink while the
run lives -- a picture whose origin shifted whenever a far position
landed was one of this project's hardest-won lessons.

Every consumer inherits the one canvas rather than deriving its own. The
stage drives it, the writer stamps it into every store's translation,
the record diaries what landed on it, and every view -- live, cropped,
frozen, however many -- is a window onto it. That is why views can never
disagree about where things are, and why the picture on screen mirrors
the specimen on the stage.

And it is the foundation smart microscopy stands on: because screen and
stage share one coordinate system, the viewer is a control surface, not
just a display. A detection at (y, x) on the canvas IS a drivable stage
target -- the same number the motors understand, no conversion. See it,
click it, shoot it, see it land again in the same place: the loop closes
through the coordinate system precisely because the canvas precedes
every view instead of being defined by one.

## The experiment level: what supersedes acquisitions lives above them

The same test that sorts everything -- would this exist even if no
acquisition ran? -- names what lives at the experiment level, beside the
acquisition folders: the FRAME (the one coordinate system every
acquisition happens in: units, origin, orientation, calibration), the
SPECIMEN it all happened to, and the CONTROLLER'S DIARY (which
acquisitions ran, in what order, and why -- which detections spawned
which targets). These experiment-level records bundle together into one
CONFIG folder that lives next to the acquisition folders, so the
experiment's top level stays readable at a glance: acquisitions, and
one config/ that explains the world they happened in.

This completes a symmetry that holds at every level:
one author and one record per floor. The controller authors the
experiment's record, the publisher authors each acquisition's, the
viewer authors each view's bookkeeping -- one pen per level, truth
flowing downhill, stamped copies below but never the pen.

One rule protects self-containment here: each acquisition carries
ABSOLUTE coordinates in the shared frame, so it stands alone when
shipped or moved. The experiment record defines and documents the frame
and remembers the why; it must never become required to interpret an
acquisition's numbers. And a view that wants to be fully self-contained
may keep a STAMPED COPY of the canvas inside its own metadata folder --
a copy travels fine, because "stamped copies below but never the pen"
is exactly the rule: the one true canvas lives in config/ and never
moves, and a view's copy is a convenience for shipping, never a second
authority.

## The two-folder resolution: data and views

The structure above resolves, finally, to two folders per acquisition
with one pen each. The pixels arrive in data/ from the microscope and
are never touched afterwards -- that folder is exactly what the
acquisition produced, nothing added by anyone else. Everything of ours
lives in views/:

    targets-2/
    ├── data/                   the microscope's pen -- pixels arrive
    │   └── survey.ome.zarr/    here from the run, never touched after
    └── views/                  our pen -- everything the viewer needs
        └── live/
            ├── metadata/         the view's liveness record (see below)
            └── live.ome.zarr/    the baked, viewer-shaped pyramid

One sentence rules it all: data/ is written once by the run and never
touched; views/ is written for lookers and never trusted as science.
Shipping data/ ships the science complete. Today's code spells the
first folder positions/ with the zmart-live record beside it; the renames are a
conversion item for the smart-microscopy writer work, recorded here as
the target.

## The collection: one zarr for the community, membership by declaration

The final form of data/ answers the one-handle need directly: the
position images live INSIDE one collection zarr, so a single path opens
in napari, ImageJ, or any OME-Zarr tool. What makes this legal under the
law is one substitution -- membership by DECLARATION, not by presence.
The collection group's metadata carries the member list, and the run's
writer declares each member as part of publishing it: only complete,
current-generation members are ever declared. Presence keeps meaning
nothing; the community reads the declaration, written by the same pen
that wrote the pixels, updated after each store completes so any skew
shows less rather than more.

    data/
    └── survey.ome.zarr/        one collection zarr -- the community handle
        ├── zarr.json             member list: complete, current members only
        ├── p00/  p01/  ...       the position images, unchanged in structure
        └── p01.generation-1/     retired generations stay, undeclared

Trades, chosen not discovered: one more small write per commit (the
member list, same cost class as committed.json -- it joins that
instrument-before-scale item); raw directory-walkers that ignore
metadata may see undeclared entries, and the declared list is the honest
interface; BigStitcher still receives its XML export, now pointing into
the collection's members.

## The final vocabulary, and the renames that carry it

Every term names either a stored fact or a computed act, never both:

- **canvas** -- the experiment setting: units, origin, orientation,
  calibration. Decided once by the controller, above every acquisition.
- **locations** -- facts on the canvas: where each position physically
  is. Stored once by the run, driven by the stage, stamped into every
  store's translation. Owned by the writer.
- **signing** -- the writer's declaration that a store now counts,
  recorded in the data's own metadata (the member declaration); the
  view's metadata folder only restates it at viewer pace.
- **placements** -- computed acts, never stored: each window's on-the-fly
  projection of locations into its own pixels (its crop, its zoom). This
  is why views cannot disagree about where things are -- they share the
  locations and differ only in projection.
- **views** -- the windows: free to show less, forbidden to show more
  or other.

The renames the conversion carries, today to target:

    positions/ (flat stores)  ->  data/survey.ome.zarr/ (declared members)
    zmart-live/               ->  views/<view>/metadata/
    layout.json               ->  locations.json
    committed.json            ->  signed.json
    (per-run frame facts)     ->  config/canvas.json, at the experiment level
    views/                    ->  views/ (right all along)

## The view's metadata lives with the view

What this document long called "the logbook" gets its final, plainer
name here: it is the VIEW'S METADATA, and it lives in the view's
folder. An earlier draft placed it inside the collection, as the data's
own metadata. That was wrong, and the reason it was wrong is the honest
test of ownership: WHO READS IT. Today this record has exactly one
reader -- the visualizer. Nothing else depends on it, because nothing
else exists yet, and this contract does not build for readers that do
not exist.

So the placement follows from the ownership rule already on every other
line of this document. The data folder is the microscope's: pixels
arrive there from the run and nothing is ever added to them by anyone
else -- if liveness ever deserves to be metadata OF the data, that is
the experiment writer's and the microscope layer's decision, made with
their pen, outside our scope. This record is viewer plumbing, so it
lives inside the view it serves, next to the baked store, the same way
the layout already does:

    views/
    └── live/
        ├── metadata/          what is published, when, which generation
        │                        counts -- append-only diary plus one
        │                        atomically-replaced pointer
        └── live.ome.zarr/     the baked, viewer-shaped pyramid

And one consequence must hold, because it is what "just the viewer's"
means: DELETING THE VIEW'S METADATA IS FINE. Everything the viewer
truly needs to know -- which stores are complete, which generation is
current, what came when -- must be findable in the data and its own
metadata, and putting it there is the WRITER'S responsibility: the
member declaration, the timestamps, whatever record rides with the
files at the moment they are written belongs to the writer's side of
the fence. The view's metadata never holds the only copy of any truth.
It is the viewer's fast, viewer-shaped restatement of what the data
already says -- kept because re-reading a whole survey to learn "what
changed?" is too slow at live pace, rebuildable from data/ whenever it
is lost, and thrown away with the rest of views/ without losing one
fact.

## The acceptance test that rules everything

Delete views/. Hand data/ to a stranger with a community tool and no
ZMART anything. Everything must work: the collection opens, the members
are the signed current generations, every location is where the stage
put it. Nothing in data/ may reference, expect, or know about views/ --
the dependency points one way only, which is what "the view is just our
add-on" means structurally: an arrow with no arrow back. And the test
cuts both ways: deleting views/ deletes every file we ever wrote --
the views' metadata included -- and nothing of value is lost, because the data's
own metadata already tells the whole story and views/ can be rebuilt
from it. This test is the standing gate the conversion must ship with,
in the pattern of test_other_tools_can_read_us: data as clean as if we
had never existed, because for that reader, we haven't.
