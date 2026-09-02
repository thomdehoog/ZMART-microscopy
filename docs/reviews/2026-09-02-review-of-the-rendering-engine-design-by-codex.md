# Review of the rendering-engine design

Date: 2026-09-02

## Verdict: rethink

WebGL2 can draw the proposed two-dimensional picture. That is not the reason for this verdict. The design does not yet justify replacing Neuroglancer, and several promises about the register, depth, projections, cache consistency, and ten-thousand-position scale are not defined tightly enough to implement without choosing their meaning in code.

The most important conflict is with the project's existing stop decision. The target-machine phase-0 measurement has not been run (`docs/design/viewer-delivery-implementation-plan-100-percent.md:217-225`). The accepted earlier design says to keep the current Viewer, fix only a measured existing-path bottleneck, and consider a new renderer only if the installed engines still cannot meet the bound (`docs/design/lazy-jpeg-pyramids-for-the-viewer.md:536-578`). The new record instead begins with “we build it ourselves” (`docs/design/own-rendering-engine-and-position-register.md:17-24`). That is a reversal without the measurement which was meant to decide it.

“Rethink” does not mean discarding the useful parts. Keep the proposed performance gates, sparse lookup experiment, byte-bounded caches, revision-aware invalidation, and Neuroglancer comparison. First restore the stop gate, extend the existing Viewer record rather than create a parallel register, and specify the scientific meaning of geometry and projections. Then a measured failure can authorize the smallest renderer that addresses it.

## Scope and evidence

I read ZMART-microscopy commit `5284da89b6070b264e945c6fe673ccc92756fd29` on my branch `codex/review-own-rendering-engine`. The brief itself names the earlier commit `ab9f3f9f`, which is an ancestor of the user-specified commit; I followed the explicit request to review `5284da89`. I read ZMART Viewer commit `9b67bf8e843b5b80145f210fb3b180e2fce554ff` on `claude/viewer-delivery-to-100`. I also checked Neuroglancer package version `2.41.2`, which the microscopy lock file pins, against its source tag at commit `e13f1f4c62918f2ea07b12f2116bdcb6767b1499`.

This was a read-only design and source review. I did not implement the engine or change either source branch. The numerical estimates below are arithmetic from the writer's declared chunks, not benchmark results.

## Findings, ordered by consequence

### 1. The decision to build a second renderer precedes the measurement that was meant to decide it

**Facts.** The completed Viewer-delivery plan says that the phase-0 measurement on the microscope computer “has not been run” and that it is the work which decides whether the existing Viewer is fast enough (`viewer-delivery-implementation-plan-100-percent.md:217-221`). Its external-run path is one opening, not the ten-step trace or a memory measurement, and its bridge-written five-axis example currently draws an empty photograph because of a known placement expected failure (`:134-144`). The same document says no Windows, microscope-PC, or full bridge-driven acceptance run had been completed (`:229-239`, `:269-271`). The earlier rendering decision requires the same ten-step trace, real runs, GPU and memory observations, and a stop if Viewer 0.2 passes (`lazy-jpeg-pyramids-for-the-viewer.md:369-470`). It permits a new renderer only after the installed engines and the smallest correction to the existing path fail the bound (`:536-578`).

The new record correctly says that the location of Neuroglancer's time is still unmeasured (`own-rendering-engine-and-position-register.md:343-345`), but nevertheless settles the choice to build a replacement at `:17-24`. It also combines a new durable record, a new coarse product, a new tile protocol, and a new renderer. A comparison after all four have been built cannot say which one cured the measured problem.

**Inference.** The project cannot yet know that a second renderer is the right intervention. The decision should be conditional: run the agreed baseline, identify whether the limit is record enumeration, server composition, response bytes, browser decoding, GPU upload, or drawing, and authorize only the layer that fails. Otherwise the project assumes the cost and correctness risk of a second production viewer before showing that it buys an experimental benefit.

### 2. The planned-ahead register already exists in substance; making another one would create two truths

**Facts.** `zmart_viewer/record/` is not merely a manifest of positions which happened to arrive.

- `LivePublisher` requires either the complete grid or all named positions before the first pixel (`record/coordinator.py:324-386`). It creates and records an immutable `SceneLayoutRevision` containing all those placements at construction (`:387-415`).

- `AcquisitionProfile` seals axes, frame shape, data type, voxel size, pyramid geometry, channel names, and time room before publication. Its own contract says a changed acquisition must start a new instance (`record/model.py:695-747`).

- A `CommitEvent` is the append-only statement that a position, replacement, or timepoint is complete and safe to show (`record/model.py:1399-1555`). Replacement creates a new immutable generation instead of overwriting published pixels (`record/coordinator.py:1698-1766`).

- A Viewer on another computer reconstructs a run from its on-disk manifest, layout, profile, routes, and stores. `record/gateway.py:117-121`, `:210-257`, and `:479-516` do not require the acquisition bridge to be present.

There are real omissions. The event types are only `position_committed`, `timepoint_committed`, and `position_replaced` (`record/model.py:596-598`). `finish_the_run()` writes deferred view products but publishes no durable completed, stopped, or failed state (`record/coordinator.py:1808-1840`). `PositionPlacement` records a position and origin in the run's pixel coordinates, but it does not distinguish planned and observed stage positions or carry the stage reference frame and provenance needed for absolute three-dimensional placement (`record/model.py:1044-1152`). The profile carries channel names, not the full display descriptors (`:716-746`).

The bridge already receives the full position list when a scan starts (`application/framework/window/main.js:603-620`; `application/framework/bridge.py:663-705`), so that premise is true. But it currently files every scan of a type under `positions/<acquisition type>` (`application/framework/bridge.py:724-748`), and a fresh position store is opened in write mode (`zmart_storage/canvas.py:1965-1969`). A same-type rescan with repeated position labels therefore has no durable acquisition-instance boundary in this path.

There is also a mismatch inside the existing record: `SceneLayoutRevision` describes itself as what the run has “actually done so far” (`record/model.py:1249-1267`), although `LivePublisher` puts the entire planned layout into revision 1 before anything lands. The new design should repair that meaning rather than reproduce the ambiguity in another file.

**Inference.** Use the existing record as the base and version it. Do not introduce a second “one file” authority. Add a stable collection or acquisition-instance identity, terminal run outcome, planned versus observed geometry, coordinate-frame provenance, source-file provenance, and a reference to the one acquisition display contract. Preserve the immutable layout plus append-only commit model.

A planned position which never lands should remain visibly planned while the run is active and become “not acquired” or an explicitly skipped position when the run reaches a terminal state. A stopped run needs a terminal record with time and reason; it must not look like a slow live run forever. A rescan of the same acquisition type needs a new collection identity and run folder even if its human-readable label is the same. A remote reader needs only the self-contained record and stores. A legacy folder without that record still needs the Viewer's existing read-only folder-discovery path or a clear refusal; it must not require the absent bridge.

### 3. The z coordinate and aligned/side views do not yet have one scientifically reproducible meaning

**Facts.** The current bridge writer deliberately writes every position with z origin `0.0`. Its explanation says that raw focus heights split a nominally flat plate survey across many Viewer planes, making most fields invisible, while the original height remains only in the run record and vendor files (`application/parts/storage/zarr_positions.py:322-362`). It also reduces the recorded plane heights to one median z step and writes that uniform step into the OME-Zarr transform (`:313-319`, `:162-176`). Thus “Neuroglancer forced every store's height to nought” in the new record (`own-rendering-engine-and-position-register.md:47-48`) attributes an application policy to the engine. More importantly, neither the stored z origin nor its single step says where every raw plane actually sat. Replacing the current policy requires a calibration and presentation rule; merely copying a recorded stage number does not establish a common specimen z datum.

The record promises both a common relative depth in micrometres and that all stacks remain visible when their bottoms or tops are aligned (`own-rendering-engine-and-position-register.md:55-59`). Stacks can have different physical depths and z steps. A 10-plane stack at 1 µm and a 5-plane stack at 2 µm may cover the same depth, while two stacks with different coverage cannot both remain visible over the entire slider. A common micrometre offset and a normalized fraction through each stack are different scientific questions.

The side view is also internally inconsistent. An x-z slice uses y as its slice coordinate. In that view z is already an on-screen axis, so a two-dimensional projection “through depth” would collapse z and leave a line. A side projection which remains two-dimensional must instead reduce along y (or x for a y-z view). The record uses “depth” for both cases at `:65-71` and refers to an unspecified “other slider” at `:60-63`.

**Inference.** Before implementation, define the stage coordinate frame, axis directions, handedness, units, plane-centre and voxel-edge convention, calibration identity, and the relation between recorded stage height and specimen height. Preserve raw acquisition coordinates unchanged. Validate that z sampling is regular or record a per-plane coordinate vector; do not silently replace irregular heights with a median while promising each plane's true height. Treat table, ceiling, and custom alignment as named presentation transforms with their own provenance; do not rewrite acquisition geometry.

For aligned slices, choose explicitly between these two meanings:

1. A common offset in micrometres from aligned low or high voxel edges. Each stack selects the plane whose voxel interval contains that offset, and a shorter stack disappears outside its coverage.

2. A normalized fraction from 0 to 1 through each stack. All stacks can remain present, but the displayed planes are not the same physical distance from the aligned edge.

Calling those edges “low” and “high” is safer than “table” and “ceiling” until the direction of stage z is guaranteed. The record should specify top and side projection axes separately and add the missing x/y slice control for the side view.

### 4. The display contract stops before the cache and shader, where silent scientific changes can still enter

**Facts.** The current delivery work now preserves unresolved channel identity and uses one window authority. In the embedded panel, all rows are measured and the resulting window is sent to the engine from one place (`application/parts/canvas/viewer-panel.js:1352-1395`); provisional measurements are stated as such (`:835-843`). The position writer omits an OME channel block rather than invent a window, while preserving the acquisition's unresolved channel descriptors separately (`application/parts/storage/zarr_positions.py:146-180`, `:192-202`).

The new record says that the contract “stands”, but its engine address contains only `source` and numeric `channel`, and its cache contains “decoded pixels” without a declared data kind or texture format (`own-rendering-engine-and-position-register.md:217-239`). One WebGL atlas cannot safely mix arbitrary tile sizes and immutable texture formats such as unsigned 8-bit images, unsigned 16-bit images, floating projections, and integer labels. The record also says that projection windows are measured, but does not say who owns that measurement, when a live measurement becomes settled, or how projection kind and range enter its identity (`:72-79`).

The current panel's collection grouping is keyed by `acquisition.name`, not by a durable collection identifier (`application/parts/canvas/viewer-panel.js:1147-1189`). Two rescans with the same human-readable name can therefore be merged. Current overlap semantics are also explicit in the Viewer record: the position committed later lands on top (`zmart_viewer/record/model.py:1053-1055`). Drawing all overlapping position quads additively would brighten seams and change that answer.

**Inference.** Define one end-to-end identity before drawing:

`collection_id + source_id + source_generation + time + stable_channel_key + level + orientation + slice_or_projection + range + tile_row + tile_column`.

The register should map the stable channel key to its array index, label, colour, data kind, valid numeric range, window, and window state. The decoded cache must preserve source data type and a separate missing-data mask. The GPU cache needs pools by tile dimensions and WebGL internal format, or a specified lossless conversion. The shader must receive the exact supplied window and its state. If the window is absent, the channel is not drawn; camera range and data type are never display fallbacks. Provisional and settled may use the same two numerical endpoints, but that state must remain visible to the panel and measurements.

A projection is a new derived value domain. Its cache identity and display measurement must include projection axis, kind, range, source generation, and revision. A slice window must never be reused for a projection. Label data must stay integer and must not pass through brightness or image projection rules. Finally, absent/unlanded pixels need transparency distinct from a genuinely acquired black pixel, and source overlap order and alpha convention need to be stated.

### 5. “At least as performant as Neuroglancer” is possible in principle but unsupported by the proposed engine description

**Facts.** WebGL2 is sufficient for textured two-dimensional quads, but Neuroglancer is doing substantially more than issuing draws. In the exact pinned version:

- Its chunk manager prioritizes visible, predicted-next, and recently used chunks; caps concurrent downloads; aborts a lower-priority download for a higher-priority one; and evicts by both system and GPU memory capacity (`google/neuroglancer` v2.41.2, `src/chunk_manager/README.md:1-59`).

- Queueing, downloading, and decoding/transcoding run off the user-interface thread (`README.md:10-12`). Separate async workers are created up to a hardware-dependent maximum and pending tasks can be cancelled (`src/async_computation/request.ts:19-37`, `:84-123`).

- Chunks have explicit new, queued, downloading, worker-memory, main-memory, GPU-memory, failed, and expired states (`src/chunk_manager/base.ts:17-55`). WebGL upload still passes through the main thread. Volume chunks create and delete GPU textures as they enter and leave GPU memory (`src/sliceview/single_texture_chunk_format.ts:122-155`).

- Neuroglancer has general coordinate-space and layer transforms. That machinery has a cost, but the current ZMART path does not expose ten thousand position coordinate systems to it. The application hands each acquisition to the engine as one composed source, then creates a layer per channel (`application/parts/canvas/viewer.js:945-976`; `viz_studio/options/neuroglancer-under/viewer.js:987-1041`). Position lookup and composition are already on the Viewer side.

The record names byte limits, least-recent use, prefetch, cancellation, and upload metering, but it does not specify queue priorities, download concurrency, retry/backoff, fairness between channels and collections, stale-result races, main-thread transfer, WebGL context loss, or admission/eviction when a pinned plane exceeds the budget. Holding all new fetches while a hand moves is not equivalent to prioritizing the new visible view. The napari feature from which that rule is borrowed is experimental, opt-in, and implemented in Python/vispy/desktop OpenGL (`prior-art-napari-progressive-loading.md:8-38`, `:56-68`). It does not “cost nothing to adopt”.

**Inference.** An own engine may outperform Neuroglancer by having a smaller two-dimensional state model and a sparse tile service. It cannot do so by omitting the scheduler, worker boundary, and complete texture lifecycle. Those are the parts the record underestimates. Worker decoding might be removable only if measurements show that the server should return raw pixels; that choice increases response bytes and still leaves transfer and upload work. The cost of Neuroglancer's coordinate spaces is more likely overestimated for the current one-composed-source path than underestimated.

The claim should therefore be a hypothesis with a breakdown gate, not an architectural premise. Measure the current source at server wait, response transfer, decoding, main-thread handoff, upload, and draw. Compare identical source pixels, channels, views, and cold/warm cache states.

### 6. Fan-in is useful, but position count alone is not a safe kept/lazy boundary

**Facts.** The current composer pins the coarsest level plus levels whose voxel count is at most one per cent of the full mosaic (`zmart_viewer/compose.py:680`, `:1143-1165`). That answers a memory-residency question. The proposed fan-in threshold answers a server work question, so the record is right that they are different.

However, one position is not one read under the current bridge layout. Position arrays use chunks `(1, 1, 1, up to 128, up to 128)` (`zmart_storage/canvas.py:2116-2139`). A 512 by 512 output tile wholly inside one full-resolution position can require 16 source chunks for one time, channel, and z plane. It is one read only if the new engine tile is explicitly the same 128 by 128 chunk and aligned with it. No engine tile size is specified.

Maximum positions per tile also misses important costs: source chunks touched per position, bytes and codec, cold versus warm file cache, local disk versus network share, output tile size, data type, overlap and draw order, visible channel count, z/time, slice versus projection, sharding and range-read cost, concurrency, and the response-time budget. The rule “if any tile exceeds K” lets one exceptional overlap force a whole level to be persisted.

The current governed bake patches affected coarse pieces before installing the new composed state (`zmart_viewer/building.py:841-921`, `:1011-1094`). Dirtying is calculated from both old and new affected positions (`:1530-1556`). This preserves a simple truth: a visible source revision does not point at an old kept tile.

**Inference.** Use fan-in as one input to a measured cost model, preferably source chunks and bytes per output tile, not merely positions. Record cold and warm percentiles and a worst-case guard separately for local disk and a share. Decide persistence separately from CPU and GPU residency.

Kept tiles may lag a landing only if the protocol makes the lag explicit and fails closed. For acquisition revision R, a dirty kept tile stamped R-1 must either be composed lazily from revision R or be withheld until its R replacement exists. It must never be served as current. A separate derived-cache revision permits asynchronous patching and is more compatible with the 500 ms landing-to-visible gate. Without that fallback, patching must remain synchronous. Replacements and moved positions must dirty both their old and new footprints, and time/channel/projection identity must take part in the decision.

### 7. Ten thousand positions fit the lookup; the unsharded files and multiplied data products break first

**Facts.** The current bridge writes one OME-Zarr 0.5 store per position, retains every second y/x pixel down to a shortest side of 8, uses 128 by 128 spatial chunks, retains full z depth at every level, and does not pass the available `shard` argument (`application/parts/storage/zarr_positions.py:53-85`, `:162-188`; `zmart_storage/canvas.py:2104-2139`). Therefore every time, channel, and z plane has its own set of chunk files at every level.

For a square uint16 position of side F, one timepoint, one plane, and C channels:

`chunk files = C × sum over levels of ceil((F / 2^level) / 128)^2`.

The root and each level add one metadata file. The following counts exclude directories, compression, and the original vendor TIFFs:

| Position | Levels | Chunk files per channel and plane | Files for 10,000, one channel | Files for 10,000, three channels | Raw pyramid bytes, one channel | Raw pyramid bytes, three channels |
|---|---:|---:|---:|---:|---:|---:|
| 512 × 512 | 7 | 25 | 330,000 | 830,000 | 6.51 GiB | 19.53 GiB |
| 2,048 × 2,048 | 9 | 345 | 3,550,000 | 10,450,000 | 104.17 GiB | 312.50 GiB |

For Z planes and T moments, multiply the chunk-file and raw-byte parts by `Z × T`; the metadata count does not multiply. For example, a deep three-channel run can pass a billion small files even though ten thousand position names sound modest. Compression changes payload bytes according to the specimen but not this unsharded file count. The original TIFFs add another storage category.

The reusable storage library can create sharded OME-Zarr 0.5 when a caller supplies `shard`, but it currently shards only level 0 (`zmart_storage/canvas.py:2104-2110`, `:2126-2139`). The bridge path supplies no shard at all. Thus “the writer can already produce” sharded stores is true of the library and false as a description of the current bridge writer. Sharding level 0 alone is not a complete answer: a 2,048-pixel position still has 89 spatial chunk files per channel and plane in levels 1 through 8. Even one whole-position shard at level 0 would therefore leave about 2.8 million files for the three-channel flat example, including metadata.

The durable record itself is not the first size problem. Ten thousand planned positions mean 10,000 placement records plus about 10,000 first-landing events: about 20,000 logical records, with replacements and timepoints adding events rather than positions. An older compact 10,000-position pointer map was measured at 2.19 MB (`docs/history/PLAN_placement_by_transform.md:40-57`); the current placement and event records are richer, so several to tens of megabytes is a reasonable order-of-magnitude estimate. That fits memory, provided the browser receives an indexed snapshot rather than a complete rewritten plan after every landing. The existing source records why even a linear by-name lookup mattered at 12,769 positions (`zmart_viewer/record/model.py:1310-1314`).

For kept tiles, the record supplies no K, so an exact claim is impossible. A useful scale check is a contiguous 100 by 100 plate of 2,048-pixel positions, no overlap, 512-pixel output tiles, one plane and one moment. The current one-per-cent rule keeps levels 4 through 8:

| Level | Mosaic side in pixels | Spatial kept tiles |
|---:|---:|---:|
| 4 | 12,800 | 625 |
| 5 | 6,400 | 169 |
| 6 | 3,200 | 49 |
| 7 | 1,600 | 16 |
| 8 | 800 | 4 |
| **Total** |  | **863** |

Those are spatial addresses. The current warm pass calls them only for its default moment and channel (`zmart_viewer/compose.py:1095-1107`, `:1183-1203`). The proposed kept product says it is per channel, which makes 2,589 channel tiles for three channels. At 512 by 512 uint16, their uncompressed payload is about 1.26 GiB for one plane and moment before overhead. Depth, time, whole-stack projections, side copies, and multiple collections multiply it. It is not automatically “cheap”. For 512-pixel positions the analogous current-rule count is 69 spatial tiles, illustrating why field size belongs in the claim.

At 2,048 pixels per position, a 512-pixel output tile covers roughly 1, 4, 16, 64, 256, 1,024, and 4,096 positions at levels 2 through 8. If K were 16, levels 5 through 8 would keep 238 spatial tiles. If K were 64, levels 6 through 8 would keep 69. These are examples, not recommendations; the missing measured K changes the answer by multiples.

**Inference.** On current bridge output, the filesystem, directory enumeration, backup/antivirus work, and network-share metadata traffic break before the register or the WebGL draw loop. A measured bridge sharding plan which also addresses the remaining pyramid levels is therefore a prerequisite for an honest ten-thousand-position production claim, not an optional optimization after the engine. Next come server-side plan folding and the multiplication by z, time, channels, projections, and side-view copies. “Ten thousand” should always be accompanied by field dimensions, channels, z, time, overlap, codec, shard shape, and the local/share storage case.

### 8. The three-dimensional promise is constraining the first engine on evidence too weak to support it

**Facts.** The larger-than-memory note states that its access was incomplete and some entries rest only on abstracts or search summaries (`prior-art-larger-than-memory-3d-rendering.md:1-7`). It then generalizes a fixed atlas and indirection as the shared pattern (`:9-27`) and recommends shaping a two-dimensional tile as a depth-one brick (`:104-118`). Neuroglancer 2.41.2 itself uses separately created per-chunk WebGL textures in the checked path, not the single mandatory atlas pattern described above (`src/sliceview/single_texture_chunk_format.ts:122-155`). The note also mixes WebGL, WebGPU, desktop OpenGL, Java, implemented systems, papers, and prototypes.

**Inference.** The evidence supports broad ideas—bounded residency, multiscale chunks, explicit lookup, and a coarse fallback—not the claims that every renderer uses one atlas, that browser volume rendering has all moved to WebGPU, or that a 2D cache becomes a 3D cache by adding one coordinate. Three-dimensional bricks change texture dimensionality, filtering, border handling, transfer size, sampling, and residency. WebGPU also has a different resource and synchronization model from WebGL2.

Keep only a clean separation between tile source, cache policy, and drawing. Do not make the first engine carry a fixed atlas or unused three-dimensional abstractions merely to avoid a hypothetical rewrite. A later volume-rendering design should choose its own representation from measurements and better primary-source review.

## Answers to the eight questions

### 1. Can it be at least as performant as Neuroglancer without Neuroglancer's dismissed parts?

It is achievable in the narrow sense that WebGL2 can draw this two-dimensional workload, but the record does not yet make the performance claim credible. It may simplify coordinate handling and use coverage to avoid empty requests. It may not omit priority scheduling, bounded concurrency, cancellation, worker/main-thread transfer, explicit CPU/GPU states, eviction, failure handling, or texture lifecycle; those are part of why Neuroglancer remains responsive.

The scheduler and texture management are most underestimated. Worker decoding is undecided, not eliminated: raw server responses trade decoding for more bytes, while compressed responses still need decoding away from the interaction thread. Neuroglancer's general coordinate spaces do cost work, but ten thousand positions are already hidden behind one composed Viewer source. Their cost is unlikely to be the ten-thousand-position lever until measurements say otherwise.

The fair gate is an instrumented comparison of the same current source, not an own sparse service against Neuroglancer fed a less efficient source. Break time down into server work, transfer, decode, main-thread handoff, upload, and draw.

### 2. Does the register design hold up?

The lifecycle idea holds, but the proposed new register shape does not. The Viewer's existing record is the right base because it already separates a complete plan, sealed storage interpretation, immutable layout, append-only validated commits, generations, and a self-contained remote reader. Calling the new thing “one file” would be a regression from its atomic, fail-closed structure.

Extend it with:

- stable run and collection identities distinct from display names and acquisition types;

- planned origin, observed origin, their coordinate frame/calibration, and source-file provenance;

- a canonical reference to the acquisition-wide channel/display contract;

- terminal events or state for completed, stopped, failed, and deliberately skipped work;

- explicit schema version/capabilities and a compact spatial index derived from the record.

Never-landed positions remain planned during a live run and become not acquired or skipped at termination. A stopped scan remains readable and visibly incomplete. A same-type rescan is a new collection identity. A second computer reads the durable record without a bridge. Legacy unregistered folders retain a read-only discovery path or receive a clear refusal.

### 3. Is fan-in the right rule, and may kept data lag?

Fan-in is a better starting predictor of composition work than the current voxel-share rule, but positions per tile is too coarse. Use measured source chunks, bytes, codec cost, overlap, channels, mode, cache state, storage medium, and concurrency. State output and source tile sizes first; otherwise “one position” may mean 16 reads.

Do not use one global K. Record at least local-disk and share results, cold and warm percentiles, and separate slice, side, and projection cases. Avoid letting one pathological tile force an entire level to disk without evidence.

Kept data may lag only behind an explicit derived revision. A dirty stale tile must be withheld or composed on demand from the current acquisition revision. If the system cannot do that, patch synchronously before publishing the new revision. Disk persistence and CPU/GPU pinning are separate decisions and should have separate policies.

### 4. Which slicing modes and projections cost more than stated?

Absolute top slices are the smallest coherent first case, once the z datum and voxel edges are defined. Aligned slicing costs scientific specification as well as code: low-edge alignment, high-edge alignment, and normalized relative depth are not interchangeable for stacks with different steps and depths. Custom offsets need provenance and must remain presentation transforms.

Side slices cost many poorly used reads with the present layout. Every z plane is in a different chunk, while a side slice uses only one row from each. They also require an x or y slice control and a separately tiled x-z or y-z geometry. A side projection must reduce along the line of sight, y or x, not generically “through depth”. A transposed side-view derivative is a substantial additional data product, not merely different drawing.

For top projections, the existing pyramids decimate x and y by retaining every second pixel and do not decimate z (`zmart_storage/canvas.py:2035-2058`, `:2080-2085`). Therefore a z mean at a retained x/y sample is still the mean of that sample's z values. It is not the mean of all full-resolution pixels represented by the larger coarse pixel. A coarse maximum can miss a bright object discarded by x/y decimation. A coarse sum is not the total signal over the coarse pixel's area. The display and exported metadata must name that sampled meaning.

For side projections, the reduced x or y axis has already been decimated, so mean, maximum, and especially sum change with level unless the projection is computed from full-resolution samples or stored with sufficient statistics. Sum needs a wide accumulator. Mean across unequal or missing ranges needs sum plus count, not a mean of means. Custom ranges make the range part of the cache key and have work proportional to the source chunks in the range. Labels need a separate rule; numeric mean or sum of object identifiers is meaningless.

### 5. Is the display contract carried through without a gap?

No. The contract is sound up to the current panel, but the proposed register, tile address, cache, and shader do not yet carry stable collection/channel identity, data kind and type, window provenance state, projection identity, or missing-pixel coverage all the way through.

Use the end-to-end identity and format pools described in finding 4. A projection gets its own window authority and provisional/settled state. A side view preserves the same channel identity. No absent window reaches a shader as an inferred camera range. No label enters an image window shader. No unlanded position becomes an opaque zero tile. Overlap order must remain the recorded later-commit-wins rule unless a new, scientifically reviewed blending rule replaces it.

### 6. Is the ten-thousand-position claim honest?

Not yet. The position count is plausible for an indexed plan and viewport-bounded drawing, but it hides the dimensions which dominate storage. The current unsharded bridge output ranges from about 330,000 files and 6.51 GiB of raw pyramid values for 10,000 flat 512-pixel monochrome fields to about 10.45 million files and 312.50 GiB for flat 2,048-pixel three-channel fields. Z and time multiply both. The original TIFFs are additional.

The register is about 20,000 logical plan-plus-first-commit records and should remain in the several-to-tens-of-megabytes range. Kept tiles are unknowable until K is measured; the current one-per-cent policy gives 863 spatial coarse tiles for the stated 2,048-pixel plate example, or 2,589 tiles and about 1.26 GiB uncompressed for three channels, one plane, and one moment.

The first likely failure is small-file metadata work on Windows or a share, followed by multiplied derived products and any O(N) per-landing fold. Require a bridge-path sharding design for all file-dominant levels, and publish a full fixture tuple before making the claim.

### 7. What should be cut, and what must remain?

Before any engine work, cut the unconditional engine decision and run phase 0. If a new engine is then authorized, its first milestone should be top-view, absolute, two-dimensional image slices on the current five-axis scientific data. It should have the existing pan/zoom and z/time controls, current composed-source compatibility, and the exact comparison instrumentation.

Leave these out of that first milestone:

- aligned table/ceiling/custom placement;

- side slices and all transposed side data;

- sum, mean, maximum, and custom-range projections;

- rotation;

- persistent kept-and-patched levels until the measured fan-in boundary shows they are needed;

- a fixed atlas chosen for future volume rendering;

- volume rendering and WebGPU;

- new keyboard, touch, share-link, screenshot, scale-bar, and pointer-value features.

Do not cut the existing record as the one authority, stable collection/source/channel identity, scientific data type, a distinct label data kind, missing-versus-black coverage, exact window state, revision/generation, byte budgets, cancellation and stale-result handling, coordinate and voxel-edge conventions, overlap order, or real target-machine gates. Those cross every layer; adding them later would invalidate cache keys, stored derivatives, and scientific interpretation.

### 8. Are the statements presented as existing facts true?

Some are true, several need qualification, and several are false as written.

| Claim in the record | Result | Evidence and correction |
|---|---|---|
| Every flat engine uses the shared pan/zoom module unchanged. | True for the checked options. | `onlyPanAndZoom` is defined in `viz_studio/options/gestures.js:58-311` and imported by `jpeg-under`, `neuroglancer-under`, `viv-under`, and `viv-inside`. The application also uses the same module when an engine has no coordinate space (`application/parts/canvas/viewer.js:557-617`). |
| Drag pans; plain wheel zooms about the pointer; other moving gestures are refused and counted. | True, with one wording caution. | `gestures.js:111-250` implements and counts the table; `:221-239` preserves the point under the pointer. The `keys` counter counts keydown events, so it is evidence of refusal, not a catalogue of every possible key gesture. |
| Depth and time sliders already hide singletons, play, and wrap. | True. | `application/parts/canvas/viewer-panel.js:327-446`, `:1410-1499`. |
| The view in micrometres survives empty data and engine changes; `lookAt`, drag lending, `project`, and `unproject` exist. | True. | `application/parts/canvas/viewer.js:439-617`, `:830-935`, `:945-1005`, `:1624-1669`; `gestures.js:266-291`. |
| A view readout already exists. | True; the proposed richer pointer readout only partly exists. | Centre and micrometres per pixel are shown at `application/parts/canvas/viewer.js:667-682`. Pointer x/y and zoom are already shown at `:856-877`; pointer z and per-channel pixel values are new. |
| Collections are the grouping the Viewer and panel already use. | Partly true. | The panel groups rows by the human-readable acquisition name (`viewer-panel.js:1147-1189`). That is presentation grouping, not stable collection identity, and equal-name rescans can collide. |
| The bridge converts landed TIFF fields to five-axis OME-Zarr 0.5 positions. | True. | `application/parts/storage/zarr_positions.py:92-110`, `:162-188`; the declared arrays are t, c, z, y, x in `zmart_storage/canvas.py:1992-2024`. |
| The Viewer reads OME-Zarr 0.4 and 0.5. | True for the checked current readers/tests. | `zmart_viewer/compose.py:190-200` distinguishes v3/0.5 `zarr.json` from v2/0.4 `.zattrs`; the microscopy repository has direct 0.4/0.5 and sharded-v3 reader tests in `viz_studio/tests/test_zarr_v3.py`. |
| Sharded zarr v3 is something “the writer can already produce”. | Qualified. | `_declare_one` and the reusable run writer accept a shard (`zmart_storage/canvas.py:1919-1964`, `:2104-2139`; `zmart_storage/positions.py:511-600`). The actual bridge position writer does not pass it (`application/parts/storage/zarr_positions.py:162-177`). |
| The Viewer has a change stream and revisioned live-state document. | True. | The stream deliberately says only “something changed” (`zmart_viewer/live.py:1-9`, `:40-93`); validated manifest revisions trigger it (`:179-247`), and the returned state names source revisions (`:530-685`). |
| Live pieces have validators. | True, but not revision validators. | `zmart_viewer/server.py:522-603` derives an ETag from file size and modification time and serves `Cache-Control: no-cache`. That is file identity, not a dirty rectangle or manifest revision. |
| Segmentation rows exist in Viewer configuration. | True. | The standalone server emits rows with `kind: "segmentation"` at `zmart_viewer/server.py:1593-1616`. The new engine still needs this kind to survive the embedded route and cache. |
| A manifest-governed live run exists. | True, and it already includes the planned-ahead shape the record calls open. | `record/coordinator.py:324-415`, `record/model.py:695-747`, `:1249-1395`, `:1399-1555`, and `record/gateway.py:117-257`. The bridge writer does not use it yet, which is also true. |
| The bridge holds the whole planned position list at scan start. | True for the overview path checked. | The page sends `state.plan.map(...)` in one start request (`application/framework/window/main.js:603-620`), and `_scan_worker` receives and iterates that list (`application/framework/bridge.py:663-705`). |
| The composer and bake patcher have byte-exact footprint knowledge. | False as a general claim; true only as integer rectangular coverage for the supported path. | `compose.Tile.footprint` returns the bounding box of a rotated tile, not its exact occupied pixels (`zmart_viewer/compose.py:65-90`). Governed dirtying uses the unrotated position shape and piece rectangles (`zmart_viewer/building.py:1530-1556`). That is enough for conservative invalidation, not byte-exact arbitrary geometry. |
| The harness synthesizes coverage. | True. | When no recorded regions exist, `viz_studio/options/measure/data_server.py:363-400` supplies the whole store and marks it `synthesized`; the page deliberately does not call that bounded coverage (`harness/src/main.js:475-476`). |
| Neuroglancer forced store height to zero. | False. | The ZMART bridge writer deliberately writes z origin zero to make flat surveys visible (`application/parts/storage/zarr_positions.py:331-360`). That is an application presentation decision made around the current composite, not an action by Neuroglancer. |
| At fine zoom a tile inside one position is one read. | False until tile size and alignment are fixed. | Current source chunks are 128 by 128. A 512 by 512 output tile can need 16 reads per channel/plane (`zmart_storage/canvas.py:2133-2139`; current Viewer output `PIECE = 512` at `zmart_viewer/compose.py:659`). |
| Whole-stack projections change only when a position lands. | False for the supported lifecycle. | Existing records permit later timepoint commits and immutable position replacement (`record/model.py:596-598`; `record/coordinator.py:1623-1766`). Their projections must change too. |
| Interaction hold and metered uploads cost nothing to adopt in two dimensions. | False. | They require scheduling, cancellation, resumption, starvation, upload-budget, and stale-result rules. The cited napari work is experimental and in a different graphics/runtime stack (`prior-art-napari-progressive-loading.md:8-38`, `:56-68`). |
| One 2D atlas cache carries later 3D by adding one coordinate, and every examined renderer uses that atlas pattern. | Unsupported. | The survey admits incomplete primary access (`prior-art-larger-than-memory-3d-rendering.md:1-7`), and pinned Neuroglancer uses per-chunk textures in the checked path. The common principles are bounded multiscale residency and fallback, not one mandatory resource layout. |

## What I would cut

I would cut the following from the record now, rather than merely postpone its code:

- “We build it ourselves” as a settled choice. Replace it with a conditional decision after the already-defined phase-0 and smallest-fix gates.

- The new one-file register. Replace it with a versioned extension of `zmart_viewer/record/` and one overarching index when a workflow contains several collections.

- The claim that absolute z is obtained simply by using recorded stage height. Preserve that measurement, but require a calibrated coordinate frame and an explicit presentation rule.

- Aligned and side modes, all projections, rotation, and the navigation extras from the first engine milestone.

- The claim that kept data is cheap, and any fixed K before the complete fixture and storage medium are stated.

- Synchronous persistent patching as the default first implementation. Keep it only if measurement shows persistence is required and no fail-closed current-revision fallback can meet the live gate.

- The fixed-atlas and “same cache for 3D” commitments. Retain byte-bounded cache interfaces and coarse fallback, which are the durable ideas.

- Universal claims drawn from the limited prior-art survey, including “every renderer” and “all browser-native work”.

I would not cut the facts that make pixels interpretable: stable identity, source generation, complete lifecycle, coordinate calibration, voxel edges, data kind and type, the display-window state, missing coverage, overlap order, and revision-consistent publication. I would also not cut real-run, target-machine, local/share, cold/warm, and equal-input comparisons.

## Paste-back before implementation starts

> Change the engine choice from settled to conditional. Run the existing phase-0 microscope-PC trace first, then the smallest measured correction to the current Viewer, and authorize another renderer only if a named metric still fails.
>
> Extend `zmart_viewer/record/`; do not create a parallel one-file register. Add stable collection identity, terminal run outcome, planned and observed placement with coordinate-frame provenance, source-file provenance, and a reference to the one channel/display contract. Keep a legacy read-only opening path for runs without this record.
>
> Specify low/high voxel-edge alignment, normalized alignment if wanted, the x/y slice control and projection axis for side views, overlap order, and projection arithmetic. State that a mean on a decimated level is a mean only of retained samples, and that sum/mean need count and accumulator rules.
>
> Carry collection, generation, stable channel key, data kind/type, window plus provisional/settled/absent state, coverage, orientation, projection kind/range, and revision through the register, cache, and shader. Use format-compatible GPU pools; do not infer a window or turn missing ground into black pixels.
>
> Replace positions-per-tile K with a measured per-mode cost model including source chunks, bytes, codec, channels, overlap, cache state, and local disk versus share. A lagging kept tile must be withheld or composed from the current revision. State tile sizes and design bridge sharding for every file-dominant pyramid level before claiming 10,000 positions.
>
> Make the first authorized engine only an absolute top slice with the existing controls and comparison hooks. Defer aligned/side views, projections, rotation, new navigation, persistent coarse products unless measured necessary, and all 3D/WebGPU/atlas commitments.
