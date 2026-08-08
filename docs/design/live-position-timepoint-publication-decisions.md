# Live publication of positions and timepoints

**Status:** architecture decision record; no production code is changed by this document.

This records the decision made after discussing how a smart-microscopy run should appear in Neuroglancer while the microscope is still acquiring it.

## The questions that led here

1. Positions arrive on the fly. How should a newly acquired position appear in an already-open Neuroglancer session?
2. Existing positions can gain timepoints. How should those appear without exposing a partially written timepoint?
3. What is the correct moment to tell Neuroglancer that something changed?

The answer to the third question settles the first two:

> **Neuroglancer is updated only after a whole position, or a whole timepoint added to an existing position, has finished writing.**

The publication unit is therefore an acquisition unit, not a Zarr chunk.

## Existing architecture this decision keeps

- One canonical OME-Zarr store holds each position.
- Each position contains its own multiscale pyramid and spatial transform.
- The raw-overlap and seamless/de-overlapped presentations are views over the positions; they do not replace the canonical position data.
- Fine and intermediate view levels should point at existing position chunks wherever their mapping permits it.
- View-specific global coarse levels may still be required for responsive whole-run navigation.
- Neuroglancer remains the renderer. The ZMART backend and frontend controller own discovery, publication state, and live refresh.

This decision refines the live behavior described in
[`../../viz_studio/OPEN_a_run_that_changes_while_you_watch.md`](../../viz_studio/OPEN_a_run_that_changes_while_you_watch.md)
and [`../../viz_studio/DATA_LAYOUT.md`](../../viz_studio/DATA_LAYOUT.md).

## Decision 1: the atomic publication units

There are two valid live commits:

### A completed new position

A new position becomes visible only when all data promised by that position is complete, including:

- all expected channels and planes;
- its initial complete timepoint or time extent;
- every pyramid level advertised in its OME-Zarr metadata;
- final array metadata, transforms, and display metadata; and
- validation that the expected chunks can be opened.

### A completed new timepoint

A timepoint appended to an existing position becomes visible only when it is complete across:

- all expected channels;
- all expected z planes;
- every advertised pyramid level; and
- any derived chunks required by the published view contract.

There is no viewer event for an individual channel, plane, chunk, or partially generated pyramid level.

This also prevents the existing multi-channel coarse-level failure mode in which whichever channel arrives first can be used to build the view before the later channels exist.

## Decision 2: writing and visibility are separate states

The lifecycle is explicit:

```text
writing -> complete -> committed -> indexed -> visible
```

Chunks may exist while the unit is `writing`, but their existence does not make them visible. A published manifest or catalog is the authority; the filesystem is not.

The required order is:

```text
microscope writes hidden data
          |
          v
position/timepoint completes and validates
          |
          v
one atomic catalog or manifest commit
          |
          v
monotonic view revision advances
          |
          v
frontend is notified
          |
          v
Neuroglancer reads the new committed revision
```

A reader therefore sees either the previous complete revision or the next complete revision, never a mixture.

## Decision 3: the revision is truth; the announcement is a hurry-up

The current growing linked view notices a new position because the pointer list becomes longer. That is insufficient for an appended timepoint or a replacement at an existing position: neither necessarily changes the pointer-list length.

Replace “pointer file length changed” as the general truth with a monotonic committed revision. Every successful position or timepoint commit advances it.

The backend may announce the new revision over the viewer's existing live connection, a WebSocket, or server-sent events. That message is an optimization, not the only record:

- If the message arrives, the frontend refreshes immediately.
- If the message is lost, polling or the next request discovers the higher committed revision.

This follows the “counter is truth, announcement is hurry-up” direction already proposed in `OPEN_a_run_that_changes_while_you_watch.md`.

## Decision 4: one append-only run event manifest

The clean source of truth is the append-only run event manifest already recommended by the OME-Zarr design review.

At minimum, a commit event records:

- `revision`;
- event type: `position_committed`, `timepoint_committed`, or `position_replaced`;
- position/store identity;
- timepoint identity, where applicable;
- acquisition type;
- spatial placement and owned region;
- affected channels and levels;
- timestamp; and
- completion/validation status.

The linked pointer map, available timepoints, coverage summary, and view invalidations are derived from this manifest. They are not competing sources of run truth.

## Decision 5: refresh the source, not the entire page

After observing a higher committed revision, the TypeScript controller refreshes or replaces only the affected versioned Neuroglancer source. It preserves:

- camera position and zoom;
- selected time and z position where still valid;
- annotations;
- shader and contrast controls;
- selected channels and visibility; and
- the remaining open datasets.

The page itself should not reload.

Revision-addressed metadata and chunk responses prevent the browser or Neuroglancer cache from serving an older answer under an unchanged address. In particular, an unwritten future chunk must not become a permanently cached blank after it is committed.

## Consequences for time storage

The present ZMART rule—declare room for timepoints at the start—still helps because appending a timepoint need not resize the array. It does **not** remove the need for a commit record: the controller still needs to know when the complete timepoint is safe to expose, and previously requested empty chunks may be cached.

If a future workflow must grow the declared `t` shape, the resize and all new chunks must be published as the same transaction. Plain multi-file Zarr does not make a multi-key update atomic by itself, so this would require a versioned manifest/indirection layer or a transactional store. No new storage dependency is selected by this decision.

If observations differ in shape, voxel size, transform, or time cadence, they should remain separate immutable observation images linked by a track/acquisition catalog rather than being forced into one rectangular `T` array.

## Global raw and seamless coarse levels

Raw-overlap and seamless views have different pixels and therefore different global coarse pyramids. A position or timepoint commit dirties only the output chunks intersecting its affected spatial and temporal region.

One implementation choice remains deliberately open:

1. **Strict publication:** rebuild and commit every affected global coarse chunk before advancing the visible revision. This gives one fully consistent revision at the cost of latency.
2. **Live overlay over a stable aggregate:** publish the complete position through its own pyramids immediately, rebuild the affected global coarse chunks in the background, and absorb it into a later aggregate revision. This is faster, but the temporary overlay must obey exactly the same raw/seamless ownership rule.

Until that choice is made, “complete enough to publish” must be explicit about whether it includes the view-specific global coarse chunks.

For the seamless view, adding a position can also alter ownership at a neighboring seam. The dirty region must include any neighbor whose ownership changes; it is not necessarily limited to the new position's rectangle.

## Sharding does not change the transaction boundary

The same complete-position/complete-timepoint rule applies with sharding. A shard being present is not a commit marker. Every shard needed by the acquisition unit is written and validated before the manifest revision exposes that unit.

Large existing shards should not be repeatedly rewritten for tiny live updates. Live data may use bounded update-local shards or unsharded hot storage and be compacted after acquisition. That packaging choice is separate from the logical publication rule.

## Required tests

The implementation is not complete until tests demonstrate that:

1. A half-written position never appears in the view.
2. A half-written timepoint never appears, even when some channels or pyramid levels already exist.
3. One commit makes the entire position/timepoint visible together.
4. A lost announcement delays refresh but cannot leave the viewer permanently stale.
5. An appended timepoint is detected even though the position pointer and pointer-list length are unchanged.
6. Cached blank/missing chunks are not reused after the corresponding data is committed.
7. Raw and seamless views invalidate the correct—and only the correct—coarse regions.
8. Changing sources preserves camera, annotations, controls, and other open datasets.

## Invariant

> **Data becomes discoverable only after the complete position or complete timepoint has been committed.**
