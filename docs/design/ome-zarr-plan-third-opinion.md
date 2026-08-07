# Third opinion on the OME-Zarr storage design

Reviewed 7 August 2026.

Scope:

1. docs/design/ome-zarr-plan-for-review.md
2. docs/design/ome-zarr-plan-review.md
3. docs/design/ome-zarr-decisions.md

The claims were checked against the implementation on
claude/frame-rate-stores-scaling-cngfct, especially zmart_storage/canvas.py,
linked.py, positions.py, cropped.py and coverage.py, and
viz_studio/backend/server.py, linking.py and stores.py.

## The three things I would change first

1. **Land B1 and B4 immediately.** The position metadata is genuinely invalid:
   every dataset needs its own scale and optional translation, with translation
   after scale. The existing view repair already demonstrates the fix. This is
   the only clearly blocking correctness defect. Test it against the OME-NGFF
   schemas, ngio, and one independent reader.

2. **Stop treating B2 plus B7 as a valid combined design.** After sharding,
   linked.py aligns placement, crop origin and crop size to the outer shard, not
   the inner 128/192-pixel chunk. A one-tile-plane shard therefore cannot expose
   a chunk-trimmed overlap. Implementing B2 as proposed makes B7 fail.

3. **Prototype TensorStore overlay before adding more custom pointer logic or
   deleting cropped.py.** A controlled benchmark clears the latency bar
   comfortably. If it survives the real Windows/NTFS/concurrent-browser
   benchmark, use it and remove most of the custom composition machinery. If it
   does not, implement inner-chunk byte-range forwarding rather than another
   copying writer.

## Plain adjudication

| Disagreement | Verdict |
| --- | --- |
| Delete B3 | **Yes, for the current whole-shard design.** |
| Do not write positions through ngio | **Yes.** |
| Delete zmart-coverage | **Yes, but only after preserving or explicitly rejecting its real capabilities.** |
| Delete cropped.py after B7 | **No—not with tile-plane shards and the current pointer mechanism.** |
| Custom view is “about 590 lines in one module” | **No. It is roughly 2,380 production lines across linked.py and backend linking.py, before server integration and tests.** |

### B3

The review is correct. server.py already handles HEAD, suffix ranges such as
bytes=-N, and ordinary ranges. _send_file serves an arbitrary byte interval.
The pointer resolver maps a requested virtual outer shard to the complete source
shard, after which the browser reads its index.

Add one integration test using an actual HTTP-backed TensorStore/Zarr client.
The existing tests prove the mapping and server range behavior, but do not quite
reproduce the exact HEAD → suffix index → inner range sequence.

There is an important caveat: **B7 reintroduces a B3-like requirement.** If the
view needs to expose inner chunks from inside a shard, something must parse and
cache the shard index and return the encoded inner-chunk byte range—or
TensorStore must decode and re-encode it. B3 is already built for whole shards;
it is not built for chunk-level cropping inside shards.

### ngio writing

The review's reversal is right. Keep direct zarr writing in the acquisition loop
and use ngio or the official schemas as a cold-path validator.

An independent clean-environment benchmark gave:

| Input | Direct Zarr | ngio mode=numpy | ngio default |
| --- | ---: | ---: | ---: |
| 1 × 512² plane | 17.6 ms | 40.9 ms | 129 ms |
| 16 × 512² planes | 140 ms | 290 ms | 1,265 ms |

Optimized ngio was about 2.1–2.3× slower; the default path was 7–9× slower. A
clean ngio 1.0 installation resolved 55 distributions and occupied about 788 MB
unpacked. Those exact numbers are environment-dependent, but the direction is
clear.

The review overweights ngio's shard-capping behavior: once only L0 is pointed
at, sublevel shard geometry no longer affects pointer correctness. The decisive
arguments are measured acquisition-path cost and unnecessary dependency
surface. The lost capability is library-enforced metadata construction and
future migration support; B4's external validation is the appropriate
replacement.

### Deleting coverage

Delete the implementation, but do not pretend its full capability is already in
the pointer map.

coverage.py records:

- every successful write, including frame and channel;
- exact origin and shape;
- scan tile_index;
- timestamp and write order;
- finished-versus-abandoned state;
- was_imaged(..., frame=, channel=).

The pointer map records a position once and deliberately omits t and c. A
one-row-per-position run table also cannot preserve repeated visits without
lists or a separate event relation.

Use one append-only run event manifest containing store, placement, owned crop,
frame, channel, timestamp and tile index. Derive the final pointer attribute,
timepoint count, coverage summary and B10 table from that. Then delete
coverage.py and its tests. If exact per-channel/per-time visit history is
unwanted, state that and delete it outright; that is the capability being
surrendered.

## TensorStore: measured answer

stack is not the relevant operation: it introduces a new dimension. overlay is
the spatial composition primitive; it places translated layers in a common
domain, with later layers taking precedence. TensorStore can open layer Specs
on demand and has a native Zarr 3 driver.

The controlled benchmark used TensorStore 0.1.85 with:

- 10,000 translated layers;
- uint16, 2048² tiles;
- 128² inner chunks;
- one 2048² Zarr 3 shard per plane;
- Zstd;
- overlapping placement with a 1,792-pixel step;
- reads deliberately crossing two-dimensional seams.

| Operation | Median | p95 |
| --- | ---: | ---: |
| Direct TensorStore chunk decode | 0.150 ms | 0.217 ms |
| Overlay seam decode | 0.223 ms | 0.319 ms |
| Overlay decode + Zstd re-encode | **0.441 ms** | **0.518 ms** |
| Same pipeline over persistent localhost HTTP | **0.586 ms** | **1.018 ms** |
| 10,000 distinct store paths, decode + encode | **0.734 ms** | **1.032 ms** |

The maximum localhost result was 2.6 ms. In-process overlay routing added
roughly 0.07 ms over a direct TensorStore read.

The distinct stores were hard-linked and the cache was warm, so this does not
measure independent cold NTFS reads. It does measure routing, metadata/path
count, sharded decoding, seam composition and encoding. Eagerly opening 10,000
distinct paths took about 428 ms; building their overlay took another 49 ms and
used about 216 MB RSS.

**TensorStore overlay is likely fast enough and deserves precedence over the
custom composition code.** It has not yet earned production adoption because
the real microscope test still needs:

- Windows/NTFS and actual independent files;
- cold and warm cache;
- concurrent screen-fill requests, not isolated chunks;
- live addition of positions;
- the real codecs and contrast workload.

Use an acceptance gate of median below 5 ms, p95 below 10 ms, and overlay
rebuild below 100 ms per acquisition update.

It would not replace everything. The project still needs:

- persistent OME-Zarr metadata for the virtual view;
- a run/placement manifest;
- an HTTP chunk endpoint;
- a zero-fill layer for unimaged gaps;
- an atomic live-update strategy, because overlays are immutable.

It would replace most coordinate lookup, crop composition, shard-alignment
refusal, and probably both cropped.py and much of linked.py/backend linking.py.
The lost capability is compressed-byte pass-through: each requested chunk is
decoded and re-encoded. Pixel values remain exact, but the compressed bytes do
not.

## The 8× ladder question

The review is directionally right, but understates the conflict.

For three pointed 8× levels, the largest shrink is 8² = 64. The required
alignment is:

    handed-over file extent × 64

Without sharding, chunk 192 gives 12,288 pixels, as the review says. With the
proposed 2048-pixel tile-plane shard, the actual requirement is **131,072
pixels**. Thus “mutually exclusive” is practically correct for these tiles,
though not mathematically absolute.

“Point only at L0 and write the view pyramid” is sound, with three corrections:

1. **Do not delete all shrink alignment.** Averaging tile-by-tile equals
   averaging the whole canvas only when ownership boundaries and origins share
   the global averaging phase. For three 8× levels, require multiples of 64, or
   compose averaging blocks that cross seams.

2. **Decide whether positions retain their own pyramids.**
   - Keep them: individual positions remain fast multiscale OME-Zarr images, but
     the pyramid is duplicated.
   - Make positions L0-only: lower file count and disk use, but standalone
     position viewing loses its multiscale pyramid.

3. **This is a rewrite, not a parameter change.** Current code hardcodes
   2 ** level and striding in positions.py, canvas.py and linked.py.

Retain the user-facing caveat: an averaged coarse voxel is not a raw
measurement. Thresholding or quantitative intensity work must use L0.

## Arithmetic audit

Assumptions below are decimal TB, uint16, 2048² planes, 128² chunks, and five
levels: 2048/1024/512/256/128.

| Claim | Verdict |
| --- | --- |
| 5 TB at 128² gives 153 million files | Correct for L0 data: 5e12/(128²×2) = 152.59 million. |
| 5 TB with one 2048² plane shard gives 596,000 files | Correct for **L0 only**: about 596,046. |
| Current 2 TB layout gives 20.3–20.6 million files | Correct: 238,419×(1+64+16+4+1) = 20.50 million. |
| Bundling every level reduces 2 TB to 318,000 files | **Wrong for per-position stores.** Each level still needs at least one shard per plane: 238,419×5 = 1.192 million files. |
| 10,000 positions × 100 planes × 5 levels is about 600,000 files | **Wrong. It is 5,000,000 data files** with one plane per shard. |
| One file per position per level is about 50,000 | Correct only for one t,c combination and a shard spanning the whole z-stack; add about 60,000 per-position metadata files. |
| 2×/4×/8× pyramids cost 36%/7.6%/1.8% | Plausible measured physical sizes, but theoretical pixel overhead is 33.33%/6.67%/1.587%. |
| 8× pyramid on 5 TB costs 90 GB | Theoretical range is 78–79 GB; 90 GB is valid only as a measured codec/index result. |
| 10%, 12.5%, 20%, 25% overlap cost 1.23×, 1.31×, 1.56×, 1.78× | Correct for overlap on both y and x: 1/((1-o_y)(1-o_x)). |
| 144, 400 and 100 requests per tile-plane | The chunk counts are correct. Under sharding, actual HTTP transactions also include shard HEAD/index requests. |
| HTTP/2 changes 440 ms to 26 ms | Correct only as a latency-only estimate: roughly 100 requests, six HTTP/1 connections, 26 ms RTT and perfect HTTP/2 multiplexing. It is not a measured screen-fill time. |

The 318,000 error is especially telling: it is approximately
238,419×(1+1/4+1/16+...), as if lower-resolution pixels from different position
stores could share files. They cannot.

The 1.98× → 1.3× comparison also mixes baselines. At 12.5% overlap, acquisition
is 1.306× unique specimen area. A second non-overlapping materialized copy gives:

- 1.766× relative to acquired bytes; or
- 2.306× relative to unique specimen bytes.

Thus 1.98× may be a valid measured dataset result, but it is not a general
consequence of the layout. Every disk multiplier should state whether its
denominator is acquired pixels, unique specimen pixels, or current on-disk
bytes.

“Six files and 20 KB” is not scale-invariant either. A representative
10,000-position pointer map is about 1.2 MB minified and about 2.1 MB with the
current indentation, before other metadata. It remains negligible, but is not
20 KB.

## Bloat the review missed

- **The view mechanism is not contained in 590 lines.** linked.py is 1,788
  lines and backend linking.py another 592. It has two construction paths—batch
  link_the_tiles and GrowingLinkedView—not one entry point. If TensorStore fails,
  make the batch builder a wrapper around one incremental implementation.

- **Keeping canvas.py does not require keeping all 2,083 lines.** The view needs
  declaration and pyramid writing, not the complete monolithic canvas writer,
  cross-process ownership machinery, collision tracking and coverage
  integration. positions.py already calls _declare_one directly. Extract a
  focused declarer/pyramid sink and retire the public canvas writer if no
  supported workflow still needs it. Lost capability: directly writing a
  stitched monolithic canvas with concurrent tiles.

- **Internally generated positions are reparsed as foreign data.** Run knows
  dtype, axes, frames, channels, chunking, voxel size and levels, yet
  GrowingLinkedView.add reopens every position and reconstructs that contract.
  Pass one immutable storage contract to both writers. Retain ngio/schema
  validation for imported stores. Lost capability: detecting self-produced
  metadata corruption on every add; replace it with CI plus an optional
  validation mode.

- **There are too many sources of run truth.** The growing pointer sidecar,
  folded pointer attribute, coverage journal/summary, timepoint filesystem
  scanner/cache and planned B10 table overlap. One append-only run event
  manifest should feed all of them.

- **The reader supports three pointer-map locations and three versions.** If
  these branches have not produced durable released runs, delete that
  compatibility now. Otherwise provide one migration and then delete it. Lost
  capability: opening old experimental views without migration.

- **Reopen the z-shard decision.** The design treats one-plane and whole-stack
  shards as the only choices. An 8–16-plane z-slab is a useful middle ground:
  64–128 MB uncompressed for 2048² uint16, much fewer files, and only slab-sized
  visibility delay. Because Run.write already receives the complete 3-D position
  array, the claimed 800 MB buffering cost is not entirely new memory; the
  encoder's additional copy and live-publication delay are what need measuring.

## Recommended end state

Use direct Zarr position writing, valid OME metadata, L0 physical positions, one
canonical run manifest, TensorStore overlay for the virtual L0 view, and an
averaged 8× physical view pyramid. Keep the current byte-passthrough route only
if the real-machine TensorStore test misses the stated latency gate.
