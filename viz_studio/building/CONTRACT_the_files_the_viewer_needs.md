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
