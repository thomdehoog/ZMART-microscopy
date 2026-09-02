# Review brief: the design for a rendering engine of our own, for an independent reviewer

Date: 2026-09-02

Please review; do not implement. This is a design record, not code. It was
written in one conversation between the microscopist who runs this project
and the assistant that wrote the Viewer delivery migration you reviewed
earlier. Your job is the same as before: find what that shared blind spot
missed, and this time before a line is written rather than after.

## What to read

ZMART-microscopy, branch `claude/viewer-delivery-to-100` at `ab9f3f9f`.
Use a fresh clone or worktree; do not modify the branch.

1. `docs/design/own-rendering-engine-and-position-register.md` — the design
   record. Every bullet is a choice the microscopist made or accepted; the
   review is of those choices and of the facts stated beside them.
2. `docs/design/prior-art-napari-progressive-loading.md` and
   `docs/design/prior-art-larger-than-memory-3d-rendering.md` — what was
   looked up and what of it the record borrows. Several entries rest on
   abstracts and search summaries because the machine that wrote them could
   not reach the journals; the notes say which.
3. `docs/design/viewer-delivery-implementation-plan-100-percent.md` and
   your own `docs/reviews/2026-09-02-review-of-the-viewer-delivery-migration-by-codex.md`
   — the contract the engine must consume unchanged: channel identity, one
   window authority, provisional versus settled, and no window invented.
4. The code the record claims as fact: `viz_studio/options/gestures.js`,
   `viz_studio/options/neuroglancer-under/viewer.js`, `application/parts/canvas/viewer.js`,
   `application/parts/canvas/viewer-panel.js`, the Viewer's `zmart_viewer/compose.py`
   (`pinned_levels`, `PINNED_SHARE`), `zmart_viewer/live.py`, `zmart_viewer/record/`,
   and `docs/design/lazy-jpeg-pyramids-for-the-viewer.md`.
5. `CLAUDE.md` — the writing rule applies to the record itself.

## What the record decides, so you can judge each against its reason

- An engine of our own, WebGL2, two-dimensional, drawing one plane of a
  five-dimensional acquisition at a time; neuroglancer kept as the reference
  in the harness until beaten on its numbers; no Viv, no deck.gl.
- One three-dimensional stage space in micrometres; every position at its
  own x, y, z; views from the top or the side; placement absolute or aligned
  (table, ceiling, custom); slices or projections (sum, mean, max); no volume
  rendering now, an open door later.
- Collections (focussing, overview, target) as the unit of loading, register,
  panel heading and placement.
- A register written by the bridge at scan start, committed to as fields
  land, read by the Viewer, by coverage, by the kept coarse pyramid and by the
  engine's lookup.
- Fine levels assembled on demand; coarse levels kept and patched; the
  boundary by fan-in with a measured K; sharding for the file count.
- Tiles keyed by revision; dirty rectangles published per revision; a cache
  shaped as an atlas with a lookup; coarse standing in for fine; fetching
  held while the hand moves; uploads metered.
- Inputs: our flat OME-TIFF convention converted at the door, and OME-Zarr
  0.4 or 0.5 with t, c, z, y, x; one form inside.
- Navigation kept as it is (drag pans, wheel zooms about the pointer, sliders
  for depth and time, the view in micrometres), with a list of small
  additions.

## Questions — lead with whichever you can answer with evidence

1. **Is "at least as performant as neuroglancer" achievable in WebGL2 in a
   browser page, for our sparse many-position case, without the parts of
   neuroglancer the record dismisses?** Name what neuroglancer does that the
   record has not accounted for: its chunk scheduler, worker decoding,
   texture management, and the cost of its coordinate spaces. Say which of
   those the record underestimates.
2. **Does the register design hold up?** Is the Viewer's existing manifest
   (`zmart_viewer/record/`) the right base, or does a planned-ahead register
   need a different shape? What happens to positions that were planned and
   never land, to a scan stopped part way, to a re-scan of the same type,
   and to a run opened from another machine that has no bridge?
3. **Is the fan-in rule right?** Argue for or against deciding the kept
   boundary by positions per tile rather than by the share of voxels the
   composer uses today. Say what K would depend on besides disk versus
   share, and whether the kept levels must be patched synchronously with a
   landing or may lag.
4. **Which of the three slicing modes and three projections cost more than
   the record admits?** The side view is flagged; check the aligned mode
   (what "table" and "ceiling" mean for stacks of different depths and
   steps) and the projections (which levels a projection can be taken from
   honestly, and whether a mean over decimated levels is still a mean).
5. **Is the display contract carried through without a gap?** Follow one
   channel from the register through the engine's tile cache to the shader
   and find any place a window could be invented, a channel lost, or a
   provisional measurement drawn as settled. Projections and the side view
   are the places to look.
6. **Is the ten-thousand-position claim honest?** Estimate, with numbers
   from the current writer's chunking, how many files, how many bytes, how
   many register entries and how many kept tiles a plate of that size makes,
   and where the first thing breaks.
7. **What would you cut?** The record is broad. Name what should be left out
   of the first engine to reach the gates sooner, and what must not be cut
   because leaving it out would have to be undone.
8. **Are the facts stated as facts true?** The record separates what exists
   in the code from what is new; check the "exists" claims against the
   files listed above and name any that are wrong.

## Output

A verdict — accept, accept with changes, or rethink — then findings ordered
by consequence, facts separated from inferences, then answers to the eight
questions, then the list of what you cut and why. Name the commit you read.
Write in complete sentences for a reader who is a microscopist, as
`CLAUDE.md` asks. Put the review at
`docs/reviews/2026-09-02-review-of-the-rendering-engine-design-by-codex.md`
on a branch of your own, and end with a short paste-back section of the
changes the record should take before any implementation starts.
