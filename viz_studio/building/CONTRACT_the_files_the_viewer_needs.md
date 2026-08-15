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
which targets). This completes a symmetry that holds at every level:
one author and one record per floor. The controller authors the
experiment's record, the publisher authors each acquisition's, the
viewer authors each view's bookkeeping -- one pen per level, truth
flowing downhill, stamped copies below but never the pen.

One rule protects self-containment here: each acquisition carries
ABSOLUTE coordinates in the shared frame, so it stands alone when
shipped or moved. The experiment record defines and documents the frame
and remembers the why; it must never become required to interpret an
acquisition's numbers.

## The two-folder resolution: data and views

The structure above resolves, finally, to two folders per acquisition
with one pen each. The pixels and their logbook are two halves of one
thing -- the science -- and they bundle into a single folder the writer
owns, with the interoperability promise unharmed because it always
attached to each STORE, never to the folder listing:

    targets-2/
    ├── data/                   the writer's pen -- written by the run,
    │   ├── p00.ome.zarr/       never touched after: the pixels
    │   ├── ...                 and, inside with them,
    │   └── zmart-live/         their logbook
    └── views/                  the viewer's pen -- derived, disposable

One sentence rules it all: data/ is written once by the run and never
touched; views/ is written by lookers and never trusted. Shipping data/
ships the science complete, pixels with their proof. Today's code
spells the first folder positions/ with the logbook beside it; the
bundling and rename are a conversion item for the smart-microscopy
writer work, recorded here as the target.
