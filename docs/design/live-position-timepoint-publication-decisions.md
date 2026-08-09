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

## Decision: interoperability stops at a deliberate boundary

The `positions/` and `views/` arrangement is kept. It is not what makes the data
non-interoperable. Interoperability applies at three different layers, and they
must not be conflated:

```text
<run>/                                  ZMART run container
  positions/
    pos-00001.ome.zarr/                 canonical, portable OME-Zarr image
      zarr.json
      0/ 1/ 2/ ...                      real pixels and complete pyramids
    pos-00002.ome.zarr/
  views/
    overview-seamless.ome.zarr/         one virtual source for Neuroglancer
    overview-raw.ome.zarr/              overlap-preserving selector view
  zmart-live/
    profiles/ layouts/ manifest/ ...    ZMART operational state
```

1. **Every canonical position is independently interoperable.** Its own path is
   a conforming OME-Zarr image with `ome.version`, `multiscales`, named axes,
   per-level scale and translation, and matching array `dimension_names`. A
   standard reader can open a position directly without understanding ZMART,
   the run container, or either view.
2. **The run container is a ZMART collection layer.** A plain directory is the
   least ambiguous representation today. It may instead be a Zarr group, but
   generic OME-Zarr 0.5 readers will not automatically know that sibling
   `positions/` and `views/` form one scene. That limits automatic discovery of
   the whole run; it does not reduce the portability of any child position.
3. **A virtual view has OME-Zarr-facing metadata but ZMART-specific pixel
   routing.** The linked chunk/range map is not currently part of standard
   OME-Zarr. The ZMART adapter resolves it and exposes a stable image endpoint to
   Neuroglancer. Opening the link records directly with an unrelated reader is
   therefore not promised to work. A view becomes independently portable only
   when its pixels are materialized as an ordinary OME-Zarr image.

The raw-overlap view's local tile selector is also a presentation extension: it
lets Neuroglancer choose among multiple measurements of the same specimen
location without creating one drawing source per position. Canonical access to
those measurements remains through the standard position images.

Native OME-Zarr scene metadata can later make the outer collection and spatial
relationships discoverable to scene-aware tools. It changes the serialization
of the collection, not the canonical position layout or the live publication
contract. Until then, documentation and APIs must say precisely whether they
mean a portable position, an adapter-backed virtual view, or the ZMART run as a
whole; "OME-Zarr" must not be used to imply that all three have identical reader
support.

## Decision 1: the atomic publication units

There are two valid live commits:

### A completed new position

A new position becomes visible only when all data promised by that position is complete, including:

- all expected channels and planes;
- its initial complete timepoint or time extent;
- every pyramid level advertised in its OME-Zarr metadata;
- final array metadata, transforms, and display metadata;
- the complete, validated virtual-link/resolver state and affected raw/seamless view data required by the published view contract; and
- validation that the expected chunks, links, and derived view chunks can be opened.

### A completed new timepoint

A timepoint appended to an existing position becomes visible only when it is complete across:

- all expected channels;
- all expected z planes;
- every advertised position pyramid level;
- every virtual link or deterministic resolver entry needed to expose that timepoint;
- every affected raw and seamless global coarse chunk; and
- the finalized scene/layout ownership revision and timepoint-specific readiness state that the atomic commit will reference.

There is no viewer event for an individual channel, plane, chunk, or partially generated pyramid level.

This also prevents the existing multi-channel coarse-level failure mode in which whichever channel arrives first can be used to build the view before the later channels exist.

This selects **strict publication**. A position or timepoint is not temporarily exposed through a partial overlay while pyramids, links, ownership metadata, or affected global coarse chunks are still being completed in the background.

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
position/timepoint data and position pyramids complete
          |
          v
virtual links and affected raw/seamless view chunks complete
          |
          v
scene/layout ownership snapshot completes and validates
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
- immutable `acquisition_profile_id`;
- `scene_layout_revision` and virtual-link/resolver revision;
- mosaic component and integer `(row, column)`, where the acquisition uses an overlapping grid;
- spatial placement and owned region;
- affected channels and levels;
- readiness of the advertised position pyramids and affected raw/seamless view chunks;
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

The profile is agreed and sealed before the first unit of an acquisition instance is committed. Frame, overlap, inner chunks, shards, codecs, pyramid scheme, and visual/analysis ownership policies do not mutate underneath published data. A change to any incompatible profile field starts a new acquisition instance/profile or takes the explicit computed fallback; it never silently reinterprets earlier timepoints.

The profile records at least:

- frame shape and dtype;
- voxel size and axis order;
- overlap in pixels on each spatial axis;
- topology: independent positions or connected overlapping grid;
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
5. Validate nominal grid placement and every pyramid level intended for direct linking.
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

At a four-tile intersection, the same rule gives every output location one deterministic owner. There is no configurable per-tile ownership priority and no dependency on acquisition arrival order: the integer grid coordinates define the result. The smaller column owns a horizontal overlap and the smaller row owns a vertical overlap.

### Enforced overlapping-grid contract

Any acquisition that enables the direct-linked seamless-overlap path declares one or more connected rectilinear mosaic components. Every position in a component has a unique integer `(row, column)` and one shared acquisition storage profile.

For frame `F` and overlap `O`, the nominal grid step is:

```text
S = F - O
x(row, column) = x0 + column * Sx
y(row, column) = y0 + row * Sy
```

The scan plan is valid only when:

- every non-root tile is edge-adjacent to the component already described by the plan;
- neighbours overlap by the profile's declared pixel extent on the shared axis;
- a grid cell is occupied by at most one position per timepoint, except through the explicit replacement/version operation;
- diagonal contact alone does not join two components; and
- no unexpected overlap occurs between non-neighbours.

An isolated target or a separate target patch is an explicit singleton/new mosaic component, not an irregular exception inside another component. An acquisition type that does not need mosaicking may instead declare independent positions and does not use the seamless-overlap crop rule.

The plan is validated before a ZMART-controlled acquisition and again when each completed position commits. Externally produced data enters the direct-link path only if it declares or reconstructs the same grid contract. A topology violation is refused by the seamless acquisition view; the position remains available as canonical raw data for a separate component or stitching, but it is never silently inserted into the grid.

Completion order remains irrelevant. A tile's left/top crop follows its declared neighbours even if asynchronous writing delivers the positions in another order. No `ownership_priority` field is required.

The directly linked seamless view deliberately uses this nominal grid. Measured deviations from the planned stage step do not participate in its chunk mapping; a visible step at the seam is accepted. Canonical positions remain untouched and retain every overlap pixel and any measured stage metadata.

Any annotation or target exported from the nominal quick-look view must retain the source position identity and local coordinates if downstream code needs to return to the microscope accurately. Nominal mosaic coordinates must not be mislabeled as stitched coordinates.

### Stitching is a separate concern

The live storage/view path does not register, blend, correct drift, invoke a stitcher, wait for a stitcher, or update its ownership from stitching results. Its only obligation toward possible later stitching is to preserve every canonical position with its complete overlap and metadata.

A stitcher, if and when run, is a separate downstream job that reads the canonical positions and writes a separate derived product. The nominal seamless view is a responsive preview, not an unfinished stitched dataset, and its publication transaction has no dependency on stitching.

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

At a declared component boundary, the complete outer edge is kept. An unexpected internal hole makes the component incomplete; it is not treated as an ordinary boundary merely because a neighbour has not arrived yet.

This ownership rule applies to the seamless quick-look view only. Every complete position, including every overlap pixel, remains in the canonical position store for stitching and the raw view. A single scalar composite cannot expose two different measurements at the same world coordinate simultaneously, so a truly raw overlap presentation must retain distinct position sources/layers or provide a position-selection mechanism.

### Alignment through linked pyramid levels

At a directly linked pyramid level `l`, let `d_l` be its downsampling relative to level 0 and `C_l` its inner chunk in level-`l` pixels. Expressed in level-0 pixels, one-sided ownership requires:

```text
overlap % (d_l * C_l) == 0
```

For a symmetric split, replace `overlap` with `overlap / 2`. View placement, crop origin, and retained extent must satisfy the same grid phase.

Sharding does not relax this pyramid-phase rule. Link only the levels for which it holds; above that cutoff, build the raw and seamless view-specific global levels from the composed nominal grid.

## Global raw and seamless coarse levels

Raw-overlap and seamless views have different pixels and therefore different global coarse pyramids. A position or timepoint commit dirties only the output chunks intersecting its affected spatial and temporal region.

The selected policy is **strict publication**: rebuild, validate, and commit every affected raw and seamless global coarse chunk before advancing the visible revision. Neuroglancer and concurrent analysis therefore consume one internally consistent generation. A background overlay over an older aggregate is not part of the published contract.

Because grid ownership is declared in advance, adding a completed position does not redefine a neighbour's ownership. It fills only the region assigned to its grid cell. The affected global chunks are the chunks intersecting that owned region; changing the grid plan itself requires a new component/view revision rather than retroactively changing seams.

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

## Decision 9: analyse the full overlap, publish each result once

The margin-free seamless presentation is not the canonical analysis input. Analysis reads each complete canonical position, including its overlap. The overlap acts as a halo that gives a model context near an internal tile boundary.

```text
complete overlapping position
          |
          v
analysis on the full tile and halo
          |
          v
apply the declared analysis-ownership rule
          |
          v
publish or count one owned result
```

Computing predictions more than once in an overlap is permitted and often desirable. Publishing or counting the same biological object more than once is not. Objects are not rejected merely because they occur in an overlap; only the duplicate result produced by a non-owning position is rejected.

### Visual ownership and analysis ownership are related but distinct

Both rules are derived from the same realized acquisition layout, but they need not use the same seam:

- `visual_source_roi` selects the pixels exposed by the seamless quick-look view. It may use the chunk-aligned top/left-predecessor rule from Decision 7.
- `analysis_core_roi` selects the output region for which a position owns analysis results. It may use the same rule, but models that need context on both sides of an internal boundary should normally place this boundary inside the overlap, commonly near its midpoint.
- `analysis_input_roi` is normally the complete canonical position. It includes the core plus the available overlap halo.

A one-sided visual seam is efficient because it can lie on a source chunk boundary. That same seam lies at one acquisition-image edge, where the owning image has no context beyond the edge. A midpoint or otherwise model-aware analysis boundary can give both neighbouring owners usable halo. The necessary halo width is therefore an analysis-profile setting, not an assumption hidden in the viewer.

These ROIs are logical pixel/voxel intervals. Analysis correctness does not require them to align with inner chunks or shards. A non-aligned read may increase I/O, but full-tile inference already reads the overlap. Chunk and shard alignment remains a zero-copy visualization and storage optimization, not an object-ownership rule.

### Result-type rules

- For semantic labels, probability maps, and other pixelwise outputs, publish pixels only inside `analysis_core_roi` when constructing a unique acquisition-wide result.
- For detections and instance segmentation, assign each instance a deterministic anchor, preferably the model's detection seed or a nucleus centre. Keep the instance only when that anchor lies in the position's half-open `analysis_core_roi`.
- Keep the accepted instance's complete local mask and measurements where available; do not clip the biological object merely because its mask crosses the ownership boundary.
- Give an accepted object a stable identity such as `(position_id, local_label_id)`, or allocate a global identifier during consolidation, and record `owner_position_id` and `layout_revision`.
- Mark objects touching the outside boundary of the whole acquisition as potentially truncated because there is no neighbouring halo beyond that boundary.

Independent segmentations can move a centroid or boundary slightly. When exact instance uniqueness matters, detections in a narrow internal seam band are reconciled between declared neighbours using an explicit rule such as seed identity, mask overlap, or centroid distance. This is analysis-result reconciliation, not image stitching, and it does not modify canonical pixels or nominal placement.

Tile-local label images may remain below the canonical position's `labels/` hierarchy. A unique acquisition-wide label view and object table apply the ownership rule above; the table records which canonical position and local label supplied each retained object.

### The acquisition layout is reported, never inferred

The acquisition-type storage profile is a plan. Analysis consumes a versioned realized acquisition layout that records the exact grid produced by a run. Percent overlap, filenames, stage coordinates, and chunk geometry are insufficient substitutes.

The live contract has three immutable/versioned objects:

| object | responsibility | update rule |
| --- | --- | --- |
| `AcquisitionProfile` | frame, axes, overlap, chunks, shards, codecs, pyramid scheme, topology, and visual/analysis ownership policies | sealed per acquisition instance |
| `SceneLayoutRevision` | scene membership, transforms, committed positions, neighbours, explicit visual/analysis ROIs, and the spatial routing template | new immutable revision when realized membership or layout changes |
| `PositionCommit` or `TimepointCommit` | the completed data unit and the exact profile, scene/layout, pyramid, link/resolver, and raw/seamless view revisions it uses | one atomic record per published unit |

OME-Zarr scene semantics describe image membership, coordinate systems, and spatial relationships. ZMART's layout extension adds the operational information that a scene alone does not define: overlap ownership, analysis cores, virtual-link routing, readiness, and live revision state.

The realized layout records at least:

- schema version, acquisition/run identity, acquisition type, and storage-profile identity;
- axes, exact frame shape, overlap in integer pixels/voxels, and nominal grid step on every tiled axis;
- mosaic-component identity, integer `(row, column)`, declared neighbours, and coordinate transform for every position;
- explicit half-open `visual_source_roi`, `analysis_input_roi`, and `analysis_core_roi` values in level-0 local coordinates for every position;
- the visual and analysis ownership policies, model halo requirement, and deterministic odd-pixel rounding convention;
- the committed positions and spatial membership covered by the layout revision, while per-timepoint availability remains in the commit manifest; and
- any permitted per-position exception, with the actual value taking precedence over the acquisition-type default.

Writing the explicit per-position ROIs prevents the viewer and every analysis implementation from independently recreating neighbour, boundary, and odd-overlap logic.

For live work, the layout cannot be reported only after the run:

1. The acquisition-type profile and planned component exist before acquisition starts.
2. The ownership policies remain fixed; arrival order never changes how an already declared grid cell is owned.
3. Committing a position that changes realized membership publishes a new immutable `SceneLayoutRevision` atomically with the data revision.
4. A timepoint whose spatial layout is unchanged references the existing scene/layout revision rather than rewriting the complete map.
5. Every analysis result records the scene/layout revision it consumed.
6. The end of the run freezes an immutable final layout report.

The live update is therefore realized spatial occupancy plus per-timepoint availability, not a changing ownership algorithm. Spatial occupancy is versioned by `SceneLayoutRevision`; timepoint availability and its link/view readiness are versioned by the atomic commit record. Both the Neuroglancer adapter and concurrent analysis discover the same monotonic commit revision and pin its referenced immutable objects. Neither infers readiness or ownership by watching files appear.

If the grid changes in a way that would retroactively change ownership, it becomes a new component or view/layout revision. Previously published objects are never silently reassigned by the arrival order of later tiles. The same spatial layout normally applies across channels, z, and time; any axis-specific exception must be explicit.

The core rule is:

> **Segment complete overlapping canonical positions, then publish and count only results owned by the explicit analysis core recorded in the realized acquisition layout.**

## OME-Zarr 0.6 scenes: semantics now, native serialization later

Scene semantics are architectural now. ZMART's internal scene model represents the positions, overview/target images, derived views, coordinate systems, and transformations as related images rather than forcing them into one rectangular array. The Neuroglancer adapter compiles that model into the sources, layers, affine transforms, and virtual URLs that Neuroglancer currently understands.

Native serialization as OME-Zarr 0.6 scene metadata remains deferred. The current released specification remains OME-Zarr 0.5, while the available 0.6 release candidate introduces scenes for collections of images that share spatial relationships. Until the release and reader ecosystem are suitable, the persisted/view-facing contract remains 0.5-compatible. The internal model should map cleanly to the eventual scene serialization rather than require an architectural rewrite.

Scene transformations do not replace ZMART's explicit visual and analysis ownership ROIs, link map, or commit state. Those remain versioned operational metadata consumed by the viewer adapter and analysis workers.

References:

- [Current OME-Zarr specifications](https://ngff.openmicroscopy.org/specifications/index.html)
- [OME-Zarr 0.6 release-candidate scene layout](https://ngff.openmicroscopy.org/specifications/dev/index.html#scene)

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
9. Grid-derived one-sided ownership is invariant to acquisition arrival order and creates neither gaps nor duplicate ownership on a complete component.
10. A declared outer boundary keeps its complete edge, while an unexpected internal hole leaves the component incomplete rather than being silently reclassified as a boundary.
11. A virtual inner chunk extracted from a source shard decodes identically to the canonical position chunk.
12. A position with an incompatible acquisition storage profile is refused or routed through the explicit computed fallback; it is never byte-linked under false metadata.
13. The profile builder chooses only frame/chunk/overlap/shard combinations satisfying the hard divisibility rules and reports the selected overlap fraction explicitly.
14. Duplicate cells, diagonal-only joins, wrong overlap, non-neighbour overlap, and disconnected insertions are refused by the direct-linked seamless path.
15. Measured stage coordinates do not change nominal quick-look placement, canonical position pixels remain untouched, and exported targets retain source-position/local-coordinate identity.
16. Position/timepoint publication neither invokes nor waits for a stitcher, and a stitched output is represented as a separate derived dataset.
17. Full overlapping positions are used as analysis input, while semantic outputs outside the declared `analysis_core_roi` are excluded from the unique acquisition-wide result.
18. An instance appearing in two neighbouring position analyses is retained exactly once according to its deterministic anchor and the recorded half-open ownership ROIs.
19. Objects in an overlap are not discarded wholesale, accepted instance masks and measurements are not clipped at an internal ownership boundary, and outer-acquisition truncation is flagged.
20. Visual and analysis ownership can use different seam positions without copying or modifying canonical position pixels.
21. Every published analysis result references the realized-layout revision that defines its owner, and a later tile arrival cannot silently change that ownership.
22. Odd overlaps, component edges, internal four-tile intersections, and permitted per-position exceptions produce explicit ROIs with neither ownership gaps nor duplicate ownership.
23. A timepoint remains invisible until all advertised position pyramids, virtual links/resolver state, ownership metadata, and affected raw/seamless global coarse chunks validate successfully.
24. Neuroglancer and a concurrent analysis worker that observe the same commit pin the same immutable `AcquisitionProfile` and `SceneLayoutRevision`.
25. Position arrival can create a new realized scene/layout revision but cannot mutate the sealed ownership policy or silently reassign previously published results.
26. A later timepoint with unchanged spatial membership reuses the existing scene/layout revision while still receiving its own atomic timepoint commit.
27. The internal scene model compiles into Neuroglancer sources/transforms without requiring native OME-Zarr 0.6 scene support, while preserving a clean path to later 0.6 serialization.

## Invariant

> **Data becomes discoverable only after the complete position or complete timepoint has been committed.**

> **Analysis may read overlap as context, but a committed layout gives every published result exactly one owner.**

> **Viewer and analysis visibility advance together only after data, pyramids, links, views, and ownership state form one validated revision.**
