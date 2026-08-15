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
