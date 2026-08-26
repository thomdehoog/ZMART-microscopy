# What can be made smaller, and what only looks as though it can

Written 5 August 2026, after a screening pass over `zmart-viewer/` and `zmart_storage/`
looking for code that could go without losing anything the tool can do.

**The short answer is that the size is mostly earned**, and the useful half of this
document is section 4 — the things that look like waste and are load-bearing. Read
that before deleting anything.

---

## 1. The verdict, with the evidence

The screening went looking for bloat and found very little of it.

| what was checked | what was found |
|---|---|
| line coverage of `zmart_storage` from its own tests | **96%** — `canvas.py` 90%, `linked.py` 89%, `cropped.py` 99%, `positions.py` 97% |
| coverage of `zmart-viewer/backend` | `server.py` 87%, `stores.py` 89%, `announcements.py` 99%, `linking.py` 86% |
| symbols in the whole non-test Python tree that nothing references | **two** |
| `TODO`, `FIXME` or `deprecated` markers | **none** |
| exports of `scene.js` and `engine.js` that nothing imports | **none** |

The uncovered lines that were inspected are error messages, the Windows-only
branches in `canvas.py`, and refusal paths — not dead code.

**"`server.py` is 1521 lines" is a misleading number**, and it is worth knowing why
before anyone sets out to split it. Roughly half of the large files is prose, which
`CLAUDE.md` requires:

| file | total | code | comments | docstrings |
|---|---|---|---|---|
| `zmart-viewer/app/server/server.py` | 1521 | **629** | 381 | 374 |
| `zmart-viewer/app/server/stores.py` | 1182 | **317** | 212 | 470 |
| `zmart_storage/canvas.py` | 2082 | **648** | 331 | 851 |
| `zmart_storage/cropped.py` | 965 | **281** | 66 | 483 |

`stores.py` is a 317-line module. Splitting these moves prose between files; it does
not make the tool smaller.

---

## 2. Three things that were broken, and are now fixed

The screening was looking for size and found these instead. All three are committed.

**The viewer's test suite was not running at all.** One import error stopped
collection of every one of its 622 tests, so `python zmart-viewer/run_tests.py` — the
command the README and the index both give — failed outright. The cause was a rename
in commit `adf6c23`: `a_row_of_tiles` became `a_grid_of_tiles`, and
`test_one_picture_keeps_the_drawing_rate.py` was not brought with it.

That test is the one that pins the whole claim of this work — two hundred separate
positions against one linked view — so the most expensive finding in the repository
had been unguarded for as long as it had been broken. **Nothing noticed because CI
runs only on `main` and `microscope-agnostic-layer`, and this is neither.**

**Its two thresholds were calibrated on a layout that no longer exists**, and both
had to come down. They were "at least 3 times faster" and "keeps at least 0.66 of its
rate", measured when the tiles were laid out in a single row. A row of two hundred
tiles is a long thin strip mostly off the screen, so the single picture had almost
nothing to draw and its rate flattered it — 5.59 times faster, keeping 0.90.

Measured three times on the mosaic that replaced it: **2.29, 1.50 and above 3.0**.
That spread is what a contended machine with no graphics card gives, and a threshold
inside it would fail about half the time, which teaches people to ignore the test.
They are now 1.3 and 0.40, and the comment beside them says plainly that they guard
the effect *existing* rather than its size, and where to read the size instead.

This is the same fault as the black-screen frame-rate tables, in a different costume:
a measurement that looked healthy because the thing being measured was barely
happening.

**Six citations pointed at the wrong line.** `canvas.py:1562` is cited in five
documents as the line the whole pointed-at-pyramid arrangement depends on. The
decimation is at line 1675 now. `docs/how_it_works/ARCHITECTURE.md` already records that citing line
numbers was tried once and failed for exactly this reason; it happened again, to the
most load-bearing line here. They now cite `TileCanvases._write_smaller_copies` by
name.

Along with them, **93 lines that nothing called** were removed from
`measure_the_frame_rate_of_a_linked_view.py` — a drifted-run builder referenced
exactly once, by its own `def`. The same ground is covered properly by
`test_a_drifted_run_is_placed_truthfully.py`, which checks every voxel.

---

## 3. What is still available, and loses nothing

Each of these leaves the tool able to do everything it does today.

| what | lines | risk |
|---|---|---|
| Delete the legacy pointer-map locations in `zmart-viewer/app/server/linking.py` — two of the three places it looks are unreachable, so the compatibility they claim does not exist | −60 | very low |
| Delete `LINKS_FOLDER`, `LINKS_FILE` and `LINKS_ADDED_FILE` in `zmart_storage/linked.py`, which are declared and used nowhere in either module | included above | none |
| Move the shared browser-and-server harness out of a measurement script into a module beside `tests/pixels.py` | −150 to −200 | low to medium |
| Merge `measure_cold_open.py`, `measure_sources.py` and `measure_many_positions.py` into one script, keeping all three distinct columns | −250 of 676 | medium |
| Extract the view declaration shared by `link_the_tiles` and `start_a_growing_view` | −30 | low |
| Bring `measure_everything.py`'s list of scripts up to date | ~15 changed | none |
| Correct `INDEX.md`, which says `workflows/` is not on this branch — it is | ~4 changed | none |
| Add `run_live_run_demo.py` to the README, since it works and appears in no document | +1 | none |

About 500 lines in total, none of it changing what the tool can do.

**The legacy map locations are worth a note**, because the reasoning is instructive.
`linking.py` looks in three places for a view's pointer map and only the first can
ever be reached: a view is by construction a complete OME-Zarr image, so it always
has a `zarr.json` or a `.zattrs`, and the loop always returns there. The screening
demonstrated this rather than inferring it — a view built in the old shape does not
open. So the two later branches are not compatibility; they are the *appearance* of
compatibility, which is worse than none, because it invites somebody to rely on it.

---

## 4. Things that look like waste and are not

**This is the important section.** Each of these is large, and each would be a
mistake to remove.

**`zmart_storage/cropped.py` (965 lines) is the oracle.**
`docs/open/HANDOVER_a_view_that_writes_nothing.md` invites somebody to decide whether it is
dead. It is not, and not for the reason that handover gives.
`test_the_linked_view_matches_the_canvas.py` writes the same run **both ways over the
same tiles** and compares every voxel of the pointed-at view against every voxel of
the written canvas, at every zoom, in every moment and colour, read over HTTP through
the real server. That is the strongest evidence here that pointing is correct —
because, as its own header says, a pointer to the wrong file produces a picture
rather than an error. Delete `cropped.py` and three invariants become untested. What
it needs is a paragraph at the top saying it is kept deliberately, because a reader
today genuinely cannot tell.

**`canvas.py` and `positions.py` barely overlap.** `positions.py` is 478 lines of
which 128 are code; it imports `_declare_one` from `canvas.py` and delegates.
`linked.py` declares a view through `TileCanvases.create`, the same writer an
ordinary run uses — which is precisely what keeps a view's storage description
identical to its tiles'.

**`zmart-viewer/parked/` (13 617 lines) is an unfinished comparison, not an abandoned
one.** Its own results document says the table is stale and that no column has been
re-taken since a real 75 GB acquisition was opened. Removing two of the three options
ends a comparison waiting on a measurement, not one that has concluded.

**`stores.py`'s frame counting (340 lines) is heavily earned.** `written_timepoints`
is asserted about thirty times across the stress and zarr-v3 suites — on both
generations, on gappy timelapses, abandoned runs and a 901-moment store.

**`browsercheck.py` shows 0% coverage and is not dead.** A test runs it as a
subprocess, and the README documents it as the shipped render check. The same is true
of `launcher.py`, which `run_demo.py` imports.

**`_fill_in_the_zoomed_out_copies` in `linked.py` is not the code the pointed-at
pyramid replaced.** It is the branch for tiles carrying *fewer* levels than the view
keeps, which is a real capability.

**The historical documents are already curated.** Every superseded plan carries a
status banner in its first three lines and is listed under "Kept as history" in
`INDEX.md`. Every document is reachable from the index.

**`scene.js` and `engine.js` duplicate nothing.** Every export of both is imported.
`lettingGo` and `sourcesStillWaiting` look like debug leftovers and are the hooks the
browser tests read.

---

## 5. Would cost something, so it is a decision rather than a refactor

| what | lines | what would be lost |
|---|---|---|
| Retire the copying arrangement's own tests and measurements, keeping `cropped.py` as the oracle | −1 009 | the ability to check the copying path still draws, and to re-measure it out to ten thousand tiles |
| Retire `cropped.py` entirely | −1 863 | the copying arrangement **and** the oracle. The oracle role would have to move first |
| Drop the two Viv options from `parked/` | −5 061 | the three-way comparison that is waiting on a measurement |
| Retire the three contact-sheet measurement scripts | −648 | the ability to reproduce `docs/how_it_works/TILES_IN_ONE_STORE.md`. Marking them historical costs six lines and loses nothing |
| Drop `dtype` and `ome_zarr_version` from `positions.start_a_run` | −20 | writing a run that is not 16-bit, and writing OME-Zarr 0.4 — which is the default elsewhere because almost everything reads it |
| Drop `app/server/resolution_demo.py` | −240 | a diagnostic volume whose bars make the pyramid level being drawn legible from the picture. Undocumented, so probably forgotten rather than retired |

---

## 6. Two things that cost almost nothing

**Turn on CI for this branch.** `.github/workflows/viewer.yml` triggers only on `main`
and `microscope-agnostic-layer`. Every finding in section 2 would have been caught the
day it appeared. This is one line.

**Stop citing line numbers in documents.** It has now failed twice, the second time on
the line this whole arrangement depends on. Cite the function or the method; those
move far less often, and a reader who cannot find one knows immediately that something
has changed.
