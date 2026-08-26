# Independent review: what the composer must survive to serve the live run

> Reviewed 2026-08-12, by an independent Claude agent given the code, the
> superseding decision (`docs/design/pointing-and-building.md` on the live
> branch) and the responsiveness plan, and asked to find what breaks when
> this folder is promoted from import viewer to the main, manifest-gated
> serving path. Branch state reviewed: the building code at `e07e96a6` with
> the plan at `055ab5df`. Findings are ordered most severe first, each with
> the load-bearing lines quoted; the closing section records what the review
> confirmed already sound, so tomorrow's build does not re-litigate it.

# Findings, most severe first

## 1. There is no gate anywhere: the picture's source list is a filesystem glob, so uncommitted, partial, rolled-back, and superseded data all get drawn

`mosaic.py:478`:

```python
stores = sorted(one for one in folder.glob(f"*{IMAGE_SUFFIX}") if one.is_dir())
```

That glob is the composer's entire notion of "what exists". It never consults
`RunManifest`, `CommittedState`, or the layout. Under the live role, where
files appear on disk continuously and deliberately before publication
(`zmart_live/manifest.py` header: "Files existing means nothing. This record
means everything"):

- A position written but not yet committed is drawn immediately — the exact
  leak the gateway exists to prevent (`gateway.py:368-396` steps over
  unpublished claims).
- A rolled-back commit keeps being drawn: nothing here re-reads anything
  after open (see finding 4), and even a fresh `read_the_transfer` would
  still glob the store off disk.
- A **replaced position appears twice**: both `pos.ome.zarr` and
  `pos.generation-2.ome.zarr` match `*.ome.zarr`, so old and new generations
  are both in `tiles` as independent tiles, laid one over the other.
  `mosaic.py` has no counterpart of the gateway's `_generation_named`
  (`gateway.py:84-108`).
- A half-written position (some pyramid level's `zarr.json` not yet written)
  doesn't just draw wrong — it makes the **whole picture unopenable**:
  `_how_a_resolution_is_stored` raises (`mosaic.py:338-342`), as does the
  `keeps` disagreement check (`mosaic.py:494-501`). One in-flight arrival
  takes down serving for the entire run.
- A run with **zero committed positions** cannot be served at all:
  `mosaic.py:480-484` raises on an empty folder, and
  `Mosaic.voxel_um`/`slab_depth` index `tiles[0]`.

This is "change zero" from the plan, confirmed absent. Direction: source
discovery must come from the manifest/layout (position id, generation,
published moments), never from `glob`; shape/dtype/voxel geometry must come
from the profile so an empty run is a valid empty picture.

## 2. Draw order is alphabetical filename order, not commit order — and the replaced-generation case inverts later-wins

The order tiles are laid is fixed at three chained points, none of which
knows about commits:

- `mosaic.py:478` — `sorted(...glob...)`: lexicographic store-name order.
- `mosaic.py:255` — `found = [(tile, self.lands_at(tile, level)) for tile in
  self.tiles]`: placements preserve that order.
- `composer.py:225-231` — the piece index appends in placements order:

```python
for tile, at in self.mosaic.placements(level):
    ...
    index.setdefault((row, column), []).append((tile, at))
```

- `composer.py:320` — `for tile, at in
  self._tiles_in_each_piece(level).get((row, column), ()):` with plain
  overwrite, so **last in list wins**.

It is deterministic, but the determinism is wrong for the live role, which
demands later-commit-on-top (`docs/design/pointing-and-building.md`: "laid
in commit order, the later commit on top"; the gateway validates this order
against the manifest at `gateway.py:250-287`). Concrete failures:
`pos-10.ome.zarr` sorts before `pos-2.ome.zarr` regardless of which
committed later; and because `'g' < 'o'`, `pos.generation-2.ome.zarr` sorts
**before** `pos.ome.zarr`, so where a replacement overlaps its own old
generation or a neighbour, the *older* pixels are laid on top of the newer
ones — later-committed-wins exactly inverted.

Also note the harness cannot catch this: `check.py:72-88` (`truth_for`)
iterates `for tile in mosaic.tiles` — the same order as the composer — so a
wrong overlap order passes byte-identical. Direction: sort each piece's tile
list by manifest commit revision at build time (or rebuild the index on
every counter change), and give `check.py` an independent order oracle, as
the plan's sabotage campaign ("lay in arrival order; watched failing
first") requires.

## 3. Fail-open reads: absent chunk bytes become fill zeros laid over published ground, and nothing distinguishes fill from dark specimen

The laying code is plain assignment, `composer.py:331-336`:

```python
slab[from_z - low_z:to_z - low_z,
     from_y - top:to_y - top,
     from_x - left:to_x - left] = self._read_from(
         tile.copies[level],
         (from_z - at[0], from_y - at[1], from_x - at[2]),
         (to_z - at[0], to_y - at[1], to_x - at[2]))
```

A later-laid tile overwrites everything under its clipped rectangle. For a
finished, unpadded transfer every pixel of that rectangle is real specimen
and this is fine. Under the live role it is not, because of how `_read_from`
gets pixels: `_a_block_of` at `composer.py:254-258` slices `copy.array[...]`,
and **zarr silently returns the fill value for any chunk file absent on
disk**. So:

- a position whose commit line exists but whose chunk files are damaged or
  half-written is laid in as a rectangle of zeros **over a neighbour's real,
  published pixels** — the occlusion problem, produced not by padding but by
  absence;
- combined with finding 1, an in-flight (uncommitted, partially written)
  position blanks published ground beneath it.

Compare the gateway's explicit opposite rule, `gateway.py:373-379`: "if its
chunk bytes are absent, the answer is absence, never an older tile's pixels,
because … a gap in it is damage to fail closed on."

There is no fill/real distinction anywhere: `slab = np.zeros(...)`
(`composer.py:318`) and `"fill_value": 0` (`composer.py:451`) mean
"unimaged", "withheld", "damaged", and "genuinely dark specimen" are all the
identical uint16 zero, with no mask, no error, no log line. Direction: lay
only manifest-published tiles; verify chunk presence (or read through an
interface that reports missing chunks) and fail the piece closed — a 404 —
when a committed chunk is absent, rather than encoding plausible zeros.

## 4. Everything is read once and cached forever, with no generation or change-counter in any key

The read-once inventory, each with its live failure:

- **The tile list itself**: `Mosaic.tiles` is fixed at `read_the_transfer`;
  nothing re-globs or re-reads. A position committed mid-session is simply
  **invisible until process restart**.
- **Placements and shape**: `mosaic.py:195-198` `_placed` / `_shape`, with
  the comment "The arithmetic cannot change while a transfer is open, since
  it comes from descriptions on disk that are not being written" — a stated
  immutability assumption the live role breaks by definition.
- **The piece index**: `composer.py:137` `self._indexed: dict[int, dict[...]]
  = {}`, filled once per level (`composer.py:220-233`); no invalidation path
  exists. A new tile never enters any piece's list.
- **Slab cache**: key at `composer.py:342` is `key = (level, (plane // depth)
  * depth, row, column)` — no generation, no counter. After a commit touches
  that ground, the pre-commit slab keeps answering until LRU eviction
  happens to drop it; after a rollback, the withheld pixels keep being
  served. This is precisely the sabotage fault the plan names ("keep serving
  a cached piece across a commit that touched it").
- **Block cache**: key at `composer.py:246` is `(copy.held_in, at)` —
  path-keyed. Generations get distinct paths, so replacement doesn't
  collide, but any store rewritten in place serves stale bytes forever.
- **Open zarr arrays**: `Copy._opened` (`mosaic.py:100-113`) is never closed
  or refreshed; a store deleted by rollback turns reads into `OSError`s (see
  finding 9) or, worse, fill zeros (finding 3).
- **The composer registry**: `served.py:44` `_composers: dict[Path, Composer
  | None]` keeps one composer per store for the process lifetime; nothing
  watches `manifest.fingerprint()` the way `_LiveRun._published_units` does
  (`gateway.py:133-137`). It also **negatively caches `None` forever**
  (`served.py:79-83, 96-103`): a store that becomes a built picture after
  first being asked stays "not built" until `forget()`.

Direction: adopt the gateway's pattern — check `manifest.fingerprint()` per
request, and on change swap in a freshly derived immutable snapshot (tiles,
placements, index) rather than mutating; put the change counter (per-store
revision from `CommittedState.by_store`) into the slab key and the planned
disk-cache key.

## 5. The declared shape is a snapshot of a picture that grows, and the origin is derived from the tiles, so growth either blanks or silently shifts the picture

`declare.py:69-77` writes `zarr.json` for the group and every level **once,
at declare time**, from the mosaic-of-that-moment; `composer.array_json`
(`composer.py:441-445`) computes `"shape": [depth, height, width]` from
`mosaic.shape(level)`, and `mosaic.shape` is max-over-tiles
(`mosaic.py:263-268`). Two distinct failures for a growing run:

- **Growth toward +y/+x**: the on-disk declared shape and the cached
  composer's grid both stay at the old extent. The browser never asks beyond
  the declared shape; anything it does ask beyond the composer's stale
  `grid()` gets `None` from `served.the_bytes_behind` (`served.py:131-133`)
  → 404 → Neuroglancer renders fill. New ground is permanently blank, with
  no error anywhere.
- **Growth toward −y/−x (the nastier one)**: `corner_um = min over tiles`
  (`mosaic.py:524-526`), and every `lands_at` subtracts it
  (`mosaic.py:245-249`). A new position more negative than any existing one
  moves the origin, which re-maps **every** voxel coordinate at every level.
  If the mosaic were naively re-read while the browser holds the old
  metadata (old `translation` in `group_json`, `composer.py:414-416`), the
  same chunk index would name different ground on the two sides — the
  entire picture silently misregistered by the shift.

Direction: the picture's origin and maximum extent must come from the run's
immutable layout/profile (a fixed world frame), not from min/max over
currently-present tiles; declared metadata must be versioned and re-served
(with Neuroglancer's invalidate) when the counter moves, never merely
rewritten under a live viewer.

## 6. The slab cache's own docstring claims a guarantee the code does not provide, and under refresh that gap becomes a torn picture

`composer.py:130-132` says the slabs are "Guarded because … two of them
wanting the same slab must not both build it." The code at
`composer.py:339-361` checks under the lock, **releases it, builds, then
inserts**:

```python
with self._guard:
    found = self._slabs.get(key)
    ...
built = self._build_slab(level, plane, row, column)
with self._guard:
    ...
    self._slabs[key] = built
```

Today that is only duplicated work. Under the live role it is a staleness
window: a slab whose build began before a commit landed is inserted after
it, keyed without any counter (finding 4), and then answers post-commit
requests with pre-commit pixels — while neighbouring pieces built a moment
later show post-commit pixels. That is exactly the "torn mixture" the plan's
parallel-fire test forbids ("a commit landing mid-storm must never … hand
back a torn mixture"). The same build-outside-lock shape exists in
`_a_block_of` (`composer.py:247-272`), and `Mosaic._placed`/`_shape`/
`Copy._opened` are mutated with no lock at all (`mosaic.py:251-270,
111-113`) — benign only while the data is static. Direction: stamp the
counter into the key at the *start* of the build and discard-or-rekey on
insert if it moved; treat any mosaic refresh as an atomic whole-object
swap, never in-place mutation.

## 7. The built path structurally bypasses the live gateway, and `built_from` is an unaudited, arbitrary filesystem path

In the real serving path, `zmart-viewer/app/server/server.py:352` gates on the
**request's resolved path**: `live = answer_from_a_live_run(target)`. A
built picture's request path is the hollow declared store, which is not
inside the run folder, so the gateway returns `None` and the request falls
through to `_built` (`app/server/server.py:397, 446-472`), whose composer then
reads the run's position bytes **directly through zarr**, invisible to the
gate. `app/server/server.py:458-461` even documents that the tiles "are **not**
resolved by the library". So anyone who can get a declared store into an
opened folder — or simply declare one with

```python
made = Composer(read_the_transfer(Path(ours["built_from"])), ...)   # served.py:99
```

pointing `built_from` at `<run>/positions` — reads withheld pixels straight
past every fail-closed mechanism the gateway has, and more broadly reads any
path on the machine named by file *content* rather than by an operator's
decision. The `served.py` header calls the widening deliberate for import;
for the live role it is a gate bypass. Direction: when the transfer root
lies inside a governed run (`live_run_holding`), the composer must refuse or
route every tile read through the manifest decision; restrict `built_from`
to an allow-listed root.

## 8. The composer cannot represent moments (or channels), but the live gate is per position **and moment**

The manifest publishes units of `(position_id, moment, generation)`
(`gateway.py:141-166`), and the live view's chunk coordinate carries the
moment first (`gateway.py:383` `moment = piece[0]`). The built picture is
strictly 3-axis z/y/x — `mosaic.py:514-520` refuses anything else,
explicitly deferring to pointing:

```python
raise ValueError(
    f"{tiles[0].store} stores its picture as {', '.join(axes)}. This builds "
    "over transfers of three axes — depth, height and width — which is what "
    "a mesoSPIM transfer writes. A five-axis run of ours is shown by pointing instead..."
)
```

and `composer.bytes_for`'s `plane` is a z index, not a timepoint. Promoting
building to the main live path means a timelapse run either cannot open at
all, or the moment axis gets folded into z with no per-moment gating. This
is a structural gap in "change zero", not an integration detail. Direction:
the composer's address space must grow a moment axis (t as an outer
coordinate on the piece key and slab key) with per-(position, moment)
gating.

## 9. Exceptions become blank ground, and one bad store makes every request re-read the whole transfer forever

Two error paths turn damage into a silently plausible screen:

- Nothing catches exceptions from `served.the_bytes_behind`:
  `app/server/server.py:397` calls it bare, and `composer.bytes_for` →
  `Copy.array` raises `OSError` on a store a rollback deleted (finding 4).
  The handler's connection dies; the building server's own docstring
  (`app/picture/server.py:112-119`) states the consequence: the engine "treats
  403, 404 and a failed connection as 'this piece is absent' and fills the
  ground from the fill value without complaint." Damage renders as clean
  dark ground, distinguishable from real specimen by nothing.
- When `read_the_transfer` raises inside `_composer_for` (`served.py:92-103`)
  — which one half-written live position makes routine (finding 1) — no
  entry is stored in `_composers`, so **every subsequent request repeats the
  full transfer read**, serialized behind that store's `_being_made` lock:
  an accidental standing DoS of the serving thread pool, thousands of file
  reads per piece request, forever.

Direction: catch per-request, answer fail-closed 404 with a logged reason,
and negatively cache failures briefly (keyed by fingerprint so recovery is
noticed).

## 10. Smaller concrete items

- **Coarse-level dtype unchecked, silent cast**: `_refuse_tiles_that_disagree`
  compares only `tile.copies[0].dtype` (`mosaic.py:432-437`); a tile whose
  coarser copy differs passes the door, and `slab[...] =
  self._read_from(...)` (`composer.py:331`) casts silently — producing at
  level N exactly the "black square or field of noise" the level-0 check
  exists to refuse.
- **`isdigit`/`int` mismatch crashes instead of 404**: `served.py:123-125`
  and `app/picture/server.py:89-95` validate with `str.isdigit()` then call
  `int()`. Superscript digits (e.g. `"²"`) pass `isdigit()` but make `int()`
  raise `ValueError`, escaping as finding 9's connection-kill instead of the
  intended clean `None`/404. The gateway has the same pattern
  (`gateway.py:77-81`) but wraps it in `except ValueError → allowed=False`
  (`gateway.py:472-480`); served.py has no wrapper. Use `str.isdecimal()` or
  try/except.
- **No cache headers on the standalone server**: `app/picture/server.py:_send`
  (lines 50-57) sends no `Cache-Control`. The plan requires `no-store` on
  every live answer ("Nothing between the gateway and the operator's eyes
  may remember a live answer"). The backend server already does this
  (`app/server/server.py:485-486`), but only when `self._live` is set — a flag
  that must be guaranteed true for built-over-live pictures.
- **`slab_depth` assumes uniform chunking**: `composer.py:188` reads
  `tiles[0].copies[level].chunks[0]`; nothing checks other tiles agree.
  Correctness holds (reads are range-based) but the slab economy silently
  vanishes for mixed-chunking runs, and `tiles[0]` is just whichever name
  sorts first.
- **Private zarr API on the hot path**: `composer.py:392`
  `bytes(encoder.store._store_dict["c/0/0/0"].to_bytes())` (also
  `check.py:58`) reaches into `MemoryStore` internals; a zarr upgrade breaks
  serving with no test failing earlier than the wire.
- **Unbounded aggregate memory**: each `Composer` may hold ~1.25 GB
  (`SLABS_WEIGH_AT_MOST` + `BLOCKS_WEIGH_AT_MOST`, `composer.py:81, 100`),
  and `served._composers` never evicts — several open pictures multiply that
  on whatever machine serves the live run.
- **Dead rotation support with a subtle trap**: `Tile.footprint`
  (`mosaic.py:138-161`) accounts for `turned`, but nothing calls it — the
  piece index (`composer.py:226-231`) and the laying code both use the
  unturned rectangle, so a tile carrying `turned_radians` is drawn unrotated
  and mis-indexed, silently. Either wire it through or refuse turned tiles
  at the door.
- **Ledger races in the measurement server**: `app/picture/server.py:69-70, 76,
  84` mutate `ledger["first_asked"]`/`["descriptions"]` without the guard
  used for the other fields. Harness-only, but it is the tool the plan's
  checks lean on.

# What is already fine for the live role

- **The parallel-encoding fix is real and tested.** One encoder per thread
  (`composer.py:363-384`), with the history and the regression test in
  `check.py:154-183`. Identical-input concurrent builds return correct,
  independent bytes.
- **The encoding is verified at the door.** `Composer.__init__`
  (`composer.py:158-173`) round-trips the declared `CODECS` against what
  zarr actually writes, and `check.py:decode` re-reads the wire bytes
  through zarr itself — the black-window class of fault is well covered.
- **Placement arithmetic is sound and hard-won.** `lands_at`'s
  `math.floor(x + 0.5)` from micrometres per copy (`mosaic.py:243-249`),
  with the half-voxel bound argued in the docstrings and independently
  measured by `check_the_pyramid.py` through micrometres with a single-tile
  control. Dense arbitrary float placement — the reason building was chosen
  — genuinely works.
- **The piece index and cache economics scale as claimed.** Per-level index
  built once under its own lock (`composer.py:220-233`), byte-bounded LRU
  caches whose weight accounting stays correct even under concurrent
  duplicate insert (same-size replacement, `composer.py:260-271, 349-360`),
  and always-keep-the-newest so a 120 MB block is never dropped-and-
  redecoded. All of it survives the live role once keys carry the counter.
- **Geometry edge cases are handled.** Block reads clip correctly at array
  edges (`composer.py:290-292`), edge pieces are zero-padded to full `PIECE`
  size before encoding (`composer.py:318`), tiles shallower than the picture
  are depth-checked per slab (`composer.py:322-327`), and per-level voxel
  sizes come from the tiles rather than blind halving (`mosaic.py:200-209`)
  — the non-uniform z-downsampling case is right.
- **URL parsing in `served.the_bytes_behind` is not a traversal vector.**
  `served.py:122-133` accepts only digit-shaped five-part `level/c/z/y/x`
  addresses bounds-checked against the grid; the widened read scope comes
  solely from `built_from` file content (finding 7), not from the request.
- **The thundering-herd fix in `served._composer_for` works for the success
  path** (`served.py:84-104`): per-store making lock, double-checked, one
  transfer read per picture however many threads arrive.
- **The 404-for-absent convention matches the engine**
  (`app/picture/server.py:110-119` documents why 404 beats 204), and the
  backend server already sends `Cache-Control: no-store` on live answers and
  fails closed when the gateway classified a piece
  (`app/server/server.py:352-380, 485-486`).
- **The live side already provides everything the fixes need.**
  `manifest.fingerprint()` is a per-request-cheap change signal,
  `CommittedState.by_store` gives the per-position counter the cache keys
  want, `events()` gives commit order for the draw sort, and the gateway
  (`gateway.py:133-166, 368-396`) is a working reference implementation of
  gate-then-serve, fail-closed, generation-aware logic — change zero is a
  port, not an invention.
