# Lazy JPEG pyramids for display

Date: 2026-09-01

Status: design idea, not an implementation plan or a claim that this works.

## Why this is worth keeping

The microscope's TIFFs remain the scientific source. The operator viewer does
not need to transfer or decode those full files merely to draw them. It can use
lossy display derivatives instead: spatially registered JPEG tile pyramids that
are generated only when the viewer needs them and cached afterwards.

This extends the idea already present in
`viz_studio/backend/jpeg_tiles.py` and
`viz_studio/options/jpeg-under/viewer.js`. Those files currently make one small
JPEG for each field, load visible fields, decode them at a size appropriate to
the zoom, and notice fields arriving during a live scan. The missing capability
is a pyramid whose highest level retains the source image's full spatial
resolution.

## The display model

Treat an acquisition as `T x C x Z x Y x X`. Each `(time, channel, z-plane)`
has an XY JPEG tile pyramid. The viewer selects time and z, fetches the visible
XY tiles for the chosen channels, and composites those channels on the GPU.

The finest pyramid level is generated directly from the full-resolution TIFF
pixels. Coarser levels are progressively downsampled display copies. Thus a
whole-plate view transfers a few coarse tiles, while close zoom reaches one
source pixel per display pixel without loading the complete source image.

JPEGs are fixed-size tiles rather than one large image. Start by measuring
`1024 x 1024` tiles and keep the size configurable; `512 x 512` is the safer
fallback where latency or decoded browser memory dominates. A decoded RGBA
tile costs about 4 MiB at 1024 square and 16 MiB at 2048 square, regardless of
how small its JPEG file is.

Use high JPEG quality, approximately 90--95, at full resolution. Coarser levels
can use stronger compression because downsampling has already removed fine
detail. Edge tiles may be smaller or padded, but no individual response should
become an enormous JPEG.

## Lazy generation and live acquisition

The viewer asks for a tile by dataset, time, channel, z-plane, pyramid level,
and XY tile coordinate. The service returns a cached JPEG when it exists.
Otherwise it reads the necessary source region, renders the requested display
tile, writes it to the cache, and returns it.

When Smart Microscopy acquires another position:

1. Place it on a fixed global pixel grid from its recorded stage x/y position
   and pixel size.
2. Make its full-resolution display tiles available immediately or on their
   first request.
3. Mark only the overlapping coarse tiles dirty.
4. Rebuild those parents up to the whole-plate level.
5. Publish tiles and the manifest atomically, with a version that lets the
   browser invalidate stale cached responses.

The grid origin and scale must be settled once for the run. They must not move
as new positions arrive. A coarse tile may combine pixels from many acquired
positions, but each acquisition and logical channel keeps its own pyramid.
Spatial merging must not collapse the channel rows or prevent channels from
being shown independently. Overlap ownership and empty-ground behaviour also
need explicit, deterministic rules.

This gives a continuous, cheap whole-plate view without forcing the browser to
open thousands of individual fields. At close zoom it still fetches the
full-resolution tiles covering only the visible area.

## Display controls

Channel pyramids should be grayscale. The viewer assigns colour and performs
the display transform independently for every channel:

```text
shown = clamp((sample - black) / (white - black)) ^ gamma
colour = shown * channel_colour * opacity
```

That supports per-channel black and white points, brightness, contrast, gamma,
colour maps, opacity, visibility, and blend mode without regenerating tiles.
Time and z controls select another set of pyramids; they do not alter spatial
x/y placement. In particular, a z-plane value is selection metadata, not an
x/y transform for a flat overview.

Ordinary browser JPEG is an 8-bit display format. Conversion therefore needs a
broad, consistent per-channel intensity mapping that does not prematurely clip
useful signal. Adjustments can only recover values preserved by that mapping.
If the operator requests a range outside it, the service may render another
display tile from the TIFF, but measurement and analysis always use the TIFFs,
never the JPEG cache.

## What this does and does not replace

This is intended to simplify fast operator display and to avoid applying
volumetric storage transforms to flat overview imagery. It does not replace
the authoritative TIFFs or other analysis storage.

An XY pyramid per `(T, C, Z)` supports full-resolution XY slice viewing,
channel compositing, z navigation, and time playback. It does not by itself
provide efficient arbitrary 3-D volume rendering or XZ/YZ slicing. Those uses
still need suitable 3-D chunks, additional orthogonal pyramids, or another
representation.

Physical placement remains explicit metadata: global x/y origin, pixel size,
dimensions, orientation, pyramid levels, and cache version. The implementation
must not invent coordinate offsets to make an image appear aligned.
