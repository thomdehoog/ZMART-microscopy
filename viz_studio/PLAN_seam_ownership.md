# Work order: make a linked view open a run that has drifted

Written 5 August 2026. This is a plan for one piece of work, written so that
somebody picking it up cold can do it without re-deciding anything. The reasoning
behind it is in `LINKING_INSTEAD_OF_COPYING.md`, under "The condition, and what it
costs us"; read that first, because this document assumes it.

---

## The problem in four sentences

A linked view hands the viewer a tile's own files untouched, which is only possible
when a tile begins exactly on one of the view's piece boundaries. A microscope
stage asked to step 1792 voxels steps 1792 give or take a couple, so real tiles do
not begin on those boundaries. `zmart_storage/linked.py` currently refuses such a
run rather than showing it wrongly, which is the right instinct and the wrong
outcome. **The tool therefore opens the tidy grids the tests build and does not open
a real acquisition**, and that is the only thing standing between this and being
useful.

## What to build instead of refusing

Stop asking "where exactly does this tile land". Ask "which pieces of the view is
this tile the best source for", and give every piece to exactly one tile.

The tile still supplies whole pieces of itself, so nothing is cut or copied and the
passthrough survives. What moves is the seam between two tiles: instead of landing
exactly on the midline of the overlap, it lands on the piece boundary nearest the
midline. The picture is then right to within the stage's drift rather than exactly
right — which is precisely the accuracy the copying arrangement already gives,
since it also places tiles before a stitcher has measured anything. Nobody loses
accuracy they had.

**The rule, stated so it can be tested:** a piece of the view belongs to whichever
tile's centre is nearest to that piece's centre, among the tiles that cover the
piece completely. "Covers completely" matters — a tile must own only pieces it can
fill entirely from its own pixels, or the view would serve a tile's edge padding as
though it were specimen. Ties are broken by the tile's own position, lowest first,
so that the same run always produces the same view.

---

## Tasks, in the order to do them

### 1. Give a tile an owned block instead of a placement

**Where:** `zmart_storage/linked.py`, around `PlacedTile` (line 142) and
`_where_the_view_begins` (line 451).

`PlacedTile` currently records where a tile lands in voxels and which part of it is
shown. Add a step that turns those into a block of *pieces* the tile owns, and let
everything downstream work from the block. Rounding happens once, here, and every
later stage sees whole pieces only.

For each tile, in each of `y` and `x` independently:

- work out which pieces of the view the tile covers completely — the first whole
  piece at or after where it begins, through to the last whole piece ending at or
  before where it ends;
- record which of the tile's own pieces the first of those is. This is where the
  drift is absorbed, and it must come out a whole number by construction rather
  than by hoping.

Then resolve overlaps between blocks with the nearest-centre rule above, so no
piece is claimed twice.

### 2. Replace the refusal with the ownership

**Where:** `_refuse_a_placement_that_does_not_land_on_whole_pieces`, line 503.

Delete it, and let the ownership from task 1 do the work. Keep exactly one refusal
in its place, for the case ownership genuinely cannot fix: a tile too small to
contain a single whole piece of the view. That tile contributes nothing and the
operator should be told, with the same tone the current message uses — say what is
wrong, say what to change.

Note in the docstring how far a seam can now move, so the number is discoverable:
at most half a piece, which is 64 voxels with pieces of 128.

### 3. Say how far each tile was moved

**Where:** the pointer file written by `_write_the_list_of_pointers` (line 843),
and the record `zmart_storage/coverage.py` keeps.

Every tile now sits up to half a piece from where the stage says it does. That
number must be written down rather than discarded, for two reasons. An operator
needs to know the picture is approximate and by how much. And a stitcher that later
measures the true offsets needs to know what was already applied, or it will
correct for the same drift twice.

Bump `LINKS_VERSION` to 2 in both `zmart_storage/linked.py` (line 110) and
`viz_studio/backend/linking.py` (line 63) — they are checked against each other and
must change together. A reader meeting a version it does not know already refuses
rather than guesses, which is the behaviour to keep.

### 4. Tell a missing file apart from ground nobody imaged

**Where:** `viz_studio/backend/linking.py`, and wherever the server answers.

Both currently answer 404. That is correct for ground nobody imaged and quietly
wrong for a tile file that has been deleted, moved, or half-written: the operator
sees blank ground either way and cannot tell a sparse run from a broken one.

**Keep the 404 on the wire.** Neuroglancer's `isNotFoundError` treats 403, 404 and
a failed connection as "this piece is absent" and fills from the fill value without
retrying or erroring; a politer answer such as 204 is read as a successful empty
reply and fails to decode. Do not change the status code.

What to add is a note beside it: when the pointer list says a tile should be there
and the file is not, log it once per tile rather than once per piece, and surface it
in the viewer's own status the way other run problems are surfaced.

### 5. Tests

Add to `viz_studio/tests/test_the_linked_view_matches_the_canvas.py`, which already
writes the same run both ways and compares every voxel through the viewer's own
server. It is the right place because it catches exactly the failure this work can
cause: a picture that is silently wrong.

- **A drifted run opens at all.** Tiles nudged by one, two and seven voxels — none
  of them a whole number of pieces. Today this raises; it must not.
- **Every piece has exactly one owner.** Walk the whole grid of the view and check
  no piece is claimed twice and none that a tile covers is left unclaimed.
- **No padding is served inside the picture.** Fill the border of each tile with a
  value that appears nowhere else and check it never appears in the view except at
  the view's own edge. This is the one that catches a tile owning a piece it cannot
  completely fill.
- **The seam moved by less than half a piece.** Compare the drifted view against
  the canvas written from the same tiles and check no feature has moved further
  than that. Not voxel-for-voxel equality — the seam has genuinely moved, and the
  test should say by how much rather than demand it did not.
- **The same run always gives the same view.** Build it twice and compare the
  pointer files.
- **An undrifted run is unchanged.** Every existing test in this file must still
  pass untouched. If any needed changing, the ownership rule disagrees with the
  exact-grid case and is wrong.

### 6. What to run before saying it is done

```
python -m pytest zmart_storage/tests/ -q
python -m pytest viz_studio/tests/test_the_linked_view_matches_the_canvas.py -q
python -m pytest viz_studio/tests/test_the_linked_view_draws.py -q
```

All of `zmart_storage/tests/` passes today (112 tests); it must still.

---

## What this work is not

- **Not stitching.** Nothing here measures where a tile really went. It makes the
  view open at the accuracy the stage reports, which is what the copying
  arrangement already does.
- **Not blending.** Each piece comes from one tile, whole. There is nothing to
  blend and no seam to feather.
- **Not sharding.** Sharded tiles keep a piece inside a larger file rather than as
  one, so it cannot be handed over as a file. Still open, written up in
  `LINKING_INSTEAD_OF_COPYING.md`.
- **Not the zoomed-out copies.** Those genuinely cannot be pointed at and are still
  written once, at about a quarter of the picture. Unchanged by this work.

## Two things not to do

- **Do not round a tile to the nearest whole piece and leave it there.** That moves
  it by up to half a piece — 64 voxels with pieces of 128 — which is far larger
  than the drift being corrected, so the picture ends up worse than if nothing had
  been done. Ownership moves the *seam*, not the tile.
- **Do not fall back to cutting and pasting pixels when a tile does not line up.**
  That is the copying this whole arrangement exists to avoid, and doing it quietly
  inside a request would make the viewer slow for a reason nobody could see.

## The exact answer, for later

Ownership is right to within the drift, and there is a way to be exact: for a
drifted tile, most pieces still line up and can be pointed at, while a thin border
does not and can be written out properly. That is the eventual answer for showing a
run at a stitcher's accuracy rather than the stage's. It is more work, it is not
needed to open a real plate, and it should not be attempted as part of this task.
