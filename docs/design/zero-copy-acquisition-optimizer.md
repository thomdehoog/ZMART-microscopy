# Strict zero-copy acquisition profiles

**Status:** implemented in `zmart_live` on 2026-08-09.

This is the storage rule for live tiled acquisitions. It replaces the earlier
idea that some view levels or outer-edge strips could be copied into `views/`.
The canonical position pyramids hold every pixel. Both operator views contain
only array descriptions and routes back to those canonical bytes.

## The layout

```text
run/
  positions/
    posA.ome.zarr/            canonical pixels and every pyramid level
    posB.ome.zarr/
  views/
    overview-seamless.ome.zarr/  metadata only; no c/ chunk payloads
    overview-raw.zarr/           metadata only; no c/ chunk payloads
  zmart-live/
    links.json                immutable-generation routes
    committed.json            publication truth
```

The seamless view chooses one owner for each overlap. With one-sided ownership,
an ordinary tile supplies one grid step from its own top-left corner. A tile on
the last row or column supplies its complete remaining camera edge. The raw view
adds a small `tile` selector axis so both measurements of an overlap remain
available. Neither view stores a second copy of a pixel.

OME-Zarr readers can open the seamless view's multiscale metadata. The ZMART
gateway supplies a requested encoded chunk by reading its byte range from a
canonical position shard. A plain static file server cannot serve these virtual
chunk keys by itself.

## The hard geometry

Resolution level `L` is downsampled by exactly `2^L` in `y` and `x`. Packaging
may change at each level; resolution does not.

For one tiled axis, let:

- `F` be the full-resolution camera frame;
- `O` be the overlap;
- `S = F - O` be the stage/grid step;
- `C_L` be the logical chunk at level `L`; and
- `D_L = 2^L` be that level's downsampling.

A directly linked level must satisfy all of these:

```text
F % D_L = 0
O % D_L = 0
S % D_L = 0

(F / D_L) % C_L = 0
(O / D_L) % C_L = 0
(S / D_L) % C_L = 0
```

Therefore every valid `C_L` is a divisor of:

```text
gcd(F / D_L, O / D_L)
```

The same calculation is done independently for `y` and `x`, so rectangular
cameras and confocal scan formats are first-class inputs. There is no need for a
single square chunk.

These conditions are deliberately stricter than Zarr's ability to store a short
terminal chunk. A short source chunk can describe a canonical edge, but it
cannot answer a normal full-sized virtual-view chunk byte-for-byte. ZMART does
not link half or a quarter of a chunk and does not decode/re-encode one on demand.

The often-mentioned reverse relation—"the chunk is a multiple of the
overlap"—does not buy partial linking. It helps only when the resulting seam is
still a whole chunk boundary. The actual zero-copy unit is always one complete,
independently encoded inner chunk.

## What the optimizer searches

Each acquisition type supplies:

- frame height and width;
- number of exact power-of-two pyramid levels;
- permitted and preferred overlap bands;
- minimum and maximum logical chunk sizes;
- a soft maximum number of chunks across a level; and
- target shard bytes.

The current ordinary defaults are:

| setting | default |
| --- | ---: |
| pyramid levels | 4 (`1x`, `2x`, `4x`, `8x`) |
| permitted overlap | 10–20% per tiled axis |
| minimum level chunk | 8 pixels |
| maximum level chunk | 1024 pixels |
| soft request grid | at most 12 chunks across |
| target shard | 128–512 MiB by acquisition type |

An acquisition may override the overlap band, including a band below 10%, before
its profile is sealed. Published profiles never change in place.

For each axis the optimizer enumerates overlaps in the band that survive every
power-of-two level. At each level it chooses the largest permitted divisor of
the frame/overlap greatest common divisor. It removes candidates that use both
more microscope area and at least as many logical chunks as another candidate.
The returned `OptimizationReport` contains the recommended geometry and all
remaining Pareto alternatives, so a facility can inspect the trade-off instead
of accepting a hidden fallback.

Examples under the current overview defaults:

| frame (`y by x`) | overlap | chunks at levels 0, 1, 2, 3 | chunks across |
| --- | --- | --- | --- |
| `512 x 512` | `64 x 64` (12.5%) | `64, 32, 16, 8` | `8, 8, 8, 8` |
| `1152 x 1152` | `144 x 144` (12.5%) | `144, 72, 36, 18` | `8, 8, 8, 8` |
| `2000 x 2000` | `200 x 200` (10%) | `200, 100, 50, 25` | `10, 10, 10, 10` |
| `2304 x 2304` | `288 x 288` (12.5%) | `288, 144, 72, 36` | `8, 8, 8, 8` |
| `4608 x 4608` | `576 x 576` (12.5%) | `576, 288, 144, 72` | `8, 8, 8, 8` |
| `1152 x 2304` | `144 x 288` (12.5%) | `144x288, 72x144, 36x72, 18x36` | `8x8` at every level |

The 8-pixel chunk in the deepest 512-pixel example is small in stored pixels but
not in the viewer's world scale: it covers the same full-resolution footprint as
the 64-pixel level-0 chunk. The request grid remains eight by eight.

If no strict candidate exists, profile planning stops and names the available
remedies: use fewer pyramid levels, permit a smaller chunk, widen or move the
overlap band, or choose another configurable frame. It never silently creates a
physical view level.

## Shards and why small chunks do not mean millions of files

Every canonical pyramid level is Zarr v3 sharded. Its logical chunks remain
independently compressed, but many are bundled into one file:

- shard extent in `t`: `1` (implicit in the writer);
- shard extent in `c`: `1` (implicit in the writer);
- shard extent in `y` and `x`: the complete position at that level; and
- shard extent in `z`: as many complete planes as fit near the acquisition's
  target bytes, capped by the position depth.

Every shard dimension is a whole multiple of its inner chunk. This reduces
filesystem, copy and backup pressure, including on Windows, without changing
seam alignment. It does not reduce Neuroglancer's logical chunk requests; that
is why the optimizer also bounds the chunk grid instead of treating sharding as
a complete performance solution.

## Live publication

For a new position or timepoint, the writer completes and validates all canonical
levels first. It then writes a generation-specific link map and metadata-only
view descriptions. The manifest commit is the atomic visibility step. Before
that commit the gateway refuses the candidate generation; after it, raw and
seamless routes switch together.

Replacing a published position creates an immutable new canonical generation.
It changes routes, not shared view pixels. If replacement fails before commit,
the old generation's link map is restored. Legacy `views/**/c` trees are removed
when a virtual view is refreshed, and inspection refuses publication if any view
payload reappears.

## Deliberately separate concerns

- Stitching comes later. These views use the planned integer grid and do not
  correct drift.
- Analysis may use the recorded visual and analysis ownership ROIs to discard
  duplicate detections. Its reads need not align to chunks.
- OME-Zarr scenes remain a later interoperability layer. Neuroglancer currently
  reaches the two views through ZMART's adapter and gateway.

## Verification

`zmart_live/tests/test_profiles.py` exercises square and rectangular formats
from 512 through 5120 pixels, including 2304-pixel Hamamatsu data, and checks the
strict equations on every level and axis. Coordinator and gateway tests write
real sharded Zarr v3 positions, follow encoded inner-chunk byte ranges at seams
and outer edges, verify raw tile selection and timepoint/replacement gating, and
assert that no view level owns a `c/` payload tree.

Windows/SMB throughput and real-microscope timing remain qualification work;
the geometry and zero-copy correctness do not substitute for that benchmark.
