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

## Decision 6: chunk and shard layout belongs to the acquisition type

There is no project-wide frame, overlap, chunk, or shard shape. Each acquisition type has a storage profile derived from its microscope and acquisition settings. An overview, target scan, confocal scan format, mesoSPIM acquisition, and camera-based acquisition may therefore use different profiles.

The profile records at least:

- frame shape and dtype;
- voxel size and axis order;
- overlap in pixels on each spatial axis;
- seamless ownership policy;
- inner chunk shape at every pyramid level;
- outer shard shape at every pyramid level;
- pyramid downsampling factors;
- codec pipeline; and
- which pyramid levels may be directly linked into each view.

The distinction is:

| quantity | chosen for |
| --- | --- |
| frame | what the microscope or camera produces |
| overlap and ownership | acquisition/stitching evidence and where the quick-look seam is placed |
| inner chunk | the smallest independently compressed/read unit, Neuroglancer requests, and direct-link alignment |
| shard | physical file count and efficient write/copy size |

Across acquisition types these values may differ freely. Within one directly linked acquisition view, positions must use a compatible dtype, codec, pyramid, and inner-chunk grid. If the acquisition changes format midway, it starts a new acquisition instance/storage profile or uses the computed rechunking fallback; it does not silently pretend the new positions have the old layout.

### Enforce compatibility, not an exact overlap percentage

Overlap is an intent and a permitted band, not normally one literal percentage. Define overlap fraction explicitly as `overlap_pixels / frame_pixels` on each axis. A profile may, for example, request:

```yaml
overlap:
  preferred_fraction: [0.10, 0.20]
  permitted_fraction: [0.08, 0.25]
  preferred_target: 0.15
```

The exact bounds belong to the instrument/acquisition profile. Ten to twenty per cent is a useful ordinary target, while values such as 9%, 12.5%, 21%, or 25% may be the best compatible choice for a particular frame and should not be rejected merely because they are not round percentages.

The profile builder enumerates candidate inner chunks and integer overlaps, then selects a compatible combination:

1. Prefer inner chunks in the configured useful size/byte range that divide the frame.
2. For one-sided ownership, enumerate `overlap = k * inner_chunk`.
3. For midpoint ownership, enumerate `overlap = 2 * k * inner_chunk`.
4. Keep candidates inside the permitted overlap band and prefer the configured target/band.
5. Validate placement and every pyramid level intended for direct linking.
6. Among otherwise suitable candidates, prefer the larger useful inner chunk because it produces fewer logical requests.
7. Choose a shard shape that is a multiple of that inner chunk and near the configured write-size target.

If no candidate satisfies the hard alignment requirements, the system may change an adjustable confocal scan format, choose a different permitted overlap, explicitly pad/trim within a configured bound, or use computed boundary chunks. It must never round a position or advertise incompatible bytes silently.

Where ZMART controls acquisition, the selected profile is sent to the microscope workflow and then stored with the run. For imported or externally controlled acquisitions, the same logic operates as a validator: compatible positions take the direct-link path, while incompatible or uncertain positions take the explicit computed fallback.

## Decision 7: seamless overlap ownership need not be split in half

A 50/50 split is an option, not a requirement. For a regular raster, the simpler quick-look rule is **top/left predecessor wins**:

- the first tile keeps its complete image;
- a tile with a real left neighbour omits the complete overlap on its left;
- a tile with a real top neighbour omits the complete overlap on its top;
- a tile below and to the right omits both strips; and
- outer edges are kept where no neighbour exists.

At a four-tile intersection, the same rule gives every output location one deterministic owner. This must be based on stable spatial identity, such as `(row, column, position_id)`, **not acquisition arrival order**. Replaying the same run must produce the same view even if positions completed in another order.

When ZMART owns the scan plan, a planned acquisition order may be used to assign the persisted ownership priority before acquisition begins. It is still the persisted priority—not the wall-clock completion order—that decides the view. When acquisition order is external, asynchronous, or unknown, ownership is derived from geometry plus a stable position identifier. Arrival time is never the implicit tie-breaker.

For one-sided ownership at full resolution, the zero-copy conditions on an axis are:

```text
frame_size % inner_chunk == 0
overlap % inner_chunk == 0
(frame_size - overlap) % inner_chunk == 0
```

The third follows automatically when the first two hold. For a symmetric split, the stricter condition is:

```text
(overlap / 2) % inner_chunk == 0
```

Therefore one-sided ownership can use an inner chunk as large as the complete overlap. A symmetric view of the same overlap needs an inner chunk that divides half the overlap.

For a 2304 × 2304 uint16 frame, examples near a modest overlap are:

| inner chunk | one-sided overlap | overlap fraction | inner chunks per plane |
| ---: | ---: | ---: | ---: |
| 128 | 256 | 11.1% | 324 |
| 192 | 192 | 8.3% | 144 |
| 256 | 256 | 11.1% | 81 |

The 256/256 profile is especially useful: later tiles retain 2048 pixels, exactly eight chunks, while a 50/50 split of the same 256-pixel overlap would require 128-pixel chunks. The one-sided rule can therefore reduce the number of logical requests without sacrificing the overlap in the canonical positions.

It does **not** reduce the amount of unique specimen area in the final seamless image. Its benefit is simpler ownership and a less restrictive alignment rule. Its visual tradeoff is that the seam lies at one acquisition edge rather than halfway through the overlap; a midpoint seam may better balance illumination falloff or edge aberrations. Both policies remain available per acquisition type.

For sparse or adaptive acquisitions, a tile is cropped only where an actual higher-priority neighbour covers it. Blindly removing the top and left strips would create gaps when a neighbour is absent. The general rule is consequently chunk ownership by deterministic spatial priority; top/left cropping is its fast rectangular-grid specialization.

This ownership rule applies to the seamless quick-look view only. Every complete position, including every overlap pixel, remains in the canonical position store for stitching and the raw view. A single scalar composite cannot expose two different measurements at the same world coordinate simultaneously, so a truly raw overlap presentation must retain distinct position sources/layers or provide a position-selection mechanism.

### Alignment through linked pyramid levels

At a directly linked pyramid level `l`, let `d_l` be its downsampling relative to level 0 and `C_l` its inner chunk in level-`l` pixels. Expressed in level-0 pixels, one-sided ownership requires:

```text
overlap % (d_l * C_l) == 0
```

For a symmetric split, replace `overlap` with `overlap / 2`. View placement, crop origin, and retained extent must satisfy the same grid phase.

Sharding does not relax this pyramid-phase rule. Link only the levels for which it holds; above that cutoff, build the raw and seamless view-specific global levels from the composed view. Stage-origin drift is a separate alignment problem and still needs padding or computed boundary chunks when it misses the global inner-chunk grid.

## Global raw and seamless coarse levels

Raw-overlap and seamless views have different pixels and therefore different global coarse pyramids. A position or timepoint commit dirties only the output chunks intersecting its affected spatial and temporal region.

One implementation choice remains deliberately open:

1. **Strict publication:** rebuild and commit every affected global coarse chunk before advancing the visible revision. This gives one fully consistent revision at the cost of latency.
2. **Live overlay over a stable aggregate:** publish the complete position through its own pyramids immediately, rebuild the affected global coarse chunks in the background, and absorb it into a later aggregate revision. This is faster, but the temporary overlay must obey exactly the same raw/seamless ownership rule.

Until that choice is made, “complete enough to publish” must be explicit about whether it includes the view-specific global coarse chunks.

For the seamless view, adding a position can also alter ownership at a neighboring seam. The dirty region must include any neighbor whose ownership changes; it is not necessarily limited to the new position's rectangle.

## Decision 8: shard canonical positions, resolve views at inner-chunk granularity

Zarr v3 sharding separates the two units this architecture needs:

- inner chunks are independently compressed and read; and
- shards group many inner chunks into one physical file and are the preferred write unit.

Every shard dimension must be a whole multiple of its inner-chunk dimension. Shards solve physical file count and copying; they do not change seam alignment or the number of logical chunks Neuroglancer may request.

The intended arrangement is:

1. **Canonical position arrays are sharded.** Inner chunks are selected from the acquisition profile's viewing and overlap geometry. Shards are selected for manageable files and efficient writes.
2. **Directly linked virtual view levels are logically unsharded.** For one requested view chunk, the backend reads the source shard index and returns the encoded byte range of the corresponding inner chunk. The virtual keys do not exist as millions of physical files.
3. **View-specific global raw and seamless levels may be physically sharded.** They contain newly derived pixels rather than source-chunk references, so they are written and packaged independently.

The existing whole-shard byte-forwarding path cannot gain this behavior merely by setting a `shards=` parameter. Whole-shard pass-through requires the view and source shard geometry, index, origin, and owned extent to match. A seam aligned only to an inner chunk may cross an outer shard. Supporting the intended design therefore requires an inner-chunk range resolver or a measured composition implementation such as TensorStore.

### Initial live shard policy

- Give a shard a time extent of `1`, so appending a timepoint creates new shards instead of rewriting shards containing earlier timepoints.
- Initially give it a channel extent of `1`, unless buffering all channels into one shard is explicitly measured and chosen.
- Use bounded z-slabs rather than a whole unbounded time series or an unnecessarily large position shard.
- Benchmark approximately 8–16 z planes per shard on the Windows microscope computers, then adjust from measurements.

For a 2304 × 2304 uint16 plane, one uncompressed plane is about 10.1 MiB. Eight planes are about 81 MiB and sixteen about 162 MiB per timepoint and channel before compression. These are benchmark starting points, not format requirements.

The same complete-position/complete-timepoint transaction rule applies: a shard being present is not a commit marker. Every shard needed by the acquisition unit is finalized and validated before the manifest exposes that unit. No reader may observe a half-written shard index.

Large existing shards should not be repeatedly rewritten for tiny live updates. The shard layout must follow the live commit unit, and completed shards should be treated as immutable wherever possible.

References:

- [Zarr terminology and sharding behavior](https://zarr.readthedocs.io/en/stable/user-guide/glossary/)
- [Zarr v3 sharding-indexed codec](https://zarr-specs.readthedocs.io/en/latest/v3/codecs/sharding-indexed/index.html)
- [OME-Zarr 0.5 storage format](https://ngff.openmicroscopy.org/0.5/index.html)
- [Neuroglancer Zarr support](https://neuroglancer-docs.web.app/datasource/zarr/index.html)

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
9. One-sided ownership is invariant to acquisition arrival order and creates neither gaps nor duplicate ownership on a complete grid.
10. Sparse grids keep an edge when the neighbour that would have owned it is absent.
11. A virtual inner chunk extracted from a source shard decodes identically to the canonical position chunk.
12. A position with an incompatible acquisition storage profile is refused or routed through the explicit computed fallback; it is never byte-linked under false metadata.
13. The profile builder chooses only frame/chunk/overlap/shard combinations satisfying the hard divisibility rules and reports the selected overlap fraction explicitly.
14. Planned ownership priority and geometry-derived ownership both remain stable when position completion events are delivered in a different order.

## Invariant

> **Data becomes discoverable only after the complete position or complete timepoint has been committed.**
