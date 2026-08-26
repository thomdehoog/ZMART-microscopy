# What we learned putting OME-Zarr into Neuroglancer

Written 5 August 2026. A short list of the things that cost us time, so they cost
somebody else less. Each one is a mistake that was actually made here, not a general
warning.

---

## The shape of the problem

**Neuroglancer's cost is per *source*, not per byte.** It builds drawing layers for
every store it is given — an image layer, a volume layer, a bounds annotation — and
every one of them takes part in every frame. A thousand positions handed over
separately drew 24 frames in five seconds where one image managed 255. This is the
whole reason any of the rest exists.

**Nesting zarrs inside a zarr does not help.** A parent group is a container and
nothing more. OME-Zarr's `multiscales` describes the *zoom levels of one array* and
has no way to say "these ten thousand arrays are tiles of one picture", so no reader
fuses them. What buys the speed is a single array *description*, not a tidy folder.

**A description can exist without the pixels.** That is the whole trick. Write the
`.zarray` and the `multiscales`, leave the chunk files absent, and have the server
answer each request with the file that already holds those exact bytes. The image is
real to the viewer and weighs a few kilobytes.

---

## Writing the OME-Zarr

**Position goes beside each resolution, not once for the image.** OME-Zarr allows
`coordinateTransformations` in both places and **they compose** — write both and the
image is moved twice. Worse, much of the Python world (anything on `ngff-zarr`,
including `multiview-stitcher`) reads *only* the per-dataset one and silently places
the image at the origin if it is missing. We shipped stores that other tools drew
stacked on top of each other.

**Everything of yours goes outside the `.ome.zarr` folder.** Put a file of your own
inside one and zarr tells whoever opens it *"Object at zmart-links.json is not
recognized as a component of a Zarr hierarchy"*. A colleague in napari meets a
warning about a file they have never heard of. It also makes a live run look like it
is changing thousands of times, because the viewer notices change by when a folder
was last touched.

**Shrinking by decimation, not averaging, is a load-bearing choice.** `image[::2, ::2]`
keeps every second voxel, so a zoomed-out voxel comes from exactly one tile and there
is no join to blend. That is what lets a view point at the tiles' own pyramids
instead of writing its own. Averaging would look smoother and would quietly make all
of it impossible.

---

## Handing bytes over untouched

**Everything about the encoding must match exactly, and a mismatch is silent.** The
view describes bytes it did not write, so if the description disagrees the viewer
draws whatever those bytes happen to decode to — no error anywhere. All of these
have to agree between view and tiles:

- the number type, **including which way round the bytes go** (a big-endian tile
  drawn as little-endian is noise);
- the compression and its settings;
- the fill value, which decides what unwritten ground looks like;
- how pieces are named — zarr allows a dot or a nested folder, and serving one where
  the reader expects the other gives a black screen rather than a complaint;
- the memory order, row-major or column-major;
- the order of the axes — `t c z y x` against `z y x` reads the same bytes as a
  different picture;
- the generation of zarr, since the driver is chosen by looking at the disk.

**Zarr pads the chunk at an image's edge with the fill value.** That is right for the
tile it belongs to, and wrong the moment you serve that chunk somewhere *inside* a
larger picture — a band of blank ground in the middle of the specimen, from a file
that is not corrupt and a server that did nothing wrong. Only ever point at chunks a
tile fills completely.

**The alignment rule, and why nothing can get round it.** A tile's chunk can be a
view's chunk only if the tile begins on a multiple of the chunk size. Zarr describes
an image as one regular grid, so there is no way to write "this tile is two voxels
further along" and still have a reader find whole chunks. **A view can keep a tile's
true position or hand over its files untouched, but not both.** A stage asked to step
1792 voxels steps 1792 give or take a couple, so this bites on real data immediately.
Fix it in the acquisition — pad each tile's low edge by the overshoot — not in the
view.

**Once the zoomed-out copies are pointed at too, the rule gets stricter.** Shrinking
counts from each picture's own corner, so a tile must begin on a multiple of the
chunk size **times the largest shrink**. With chunks of 128 and five levels, that is
multiples of 2048 voxels. A tile one chunk out is not slightly wrong — it keeps a
different set of voxels entirely.

---

## Serving it

**404 is the correct answer for ground nobody imaged, and 204 is not.** Neuroglancer's
`isNotFoundError` treats 403, 404 and a failed connection as "this piece is absent"
and fills from the fill value without retrying or erroring. A 204 reads as a
successful reply with an empty body and fails to decode. The polite answer is the
broken one.

**Zarr v3 puts a `c` in front of a chunk's name as a path component of its own** —
`c/0/0/0/1/2`, not `c0/0/0/1/2`. Joining it onto the first number gives a path that
exists nowhere, so every request is answered "nothing here" and the picture is blank
at full size with no error at all.

**Never hold an index with an entry per chunk.** We did, and a list that was a few
megabytes on disk became about 16 GB in memory at ten thousand tiles — invisible in
tests, because test tiles are small. Hold it per *tile* and work the chunk out
arithmetically. This is also the reason to prefer Kerchunk's Parquet form over its
JSON one, if you ever adopt it.

**Kerchunk and VirtualiZarr do not connect to Neuroglancer.** They produce reference
files that `fsspec` reads in Python; Neuroglancer runs in a browser and fetches zarr
over HTTP, with no driver for a reference set. Something on the server side has to
turn a manifest into answers whatever format the manifest is in. Worth adopting later
for what they *can* express — a chunk as *(file, offset, length)*, which reaches
inside sharded files, TIFF and HDF5 — not as a way to avoid writing the server half.

---

## Measuring it

**Always measure how much of the screen has specimen on it.** An empty panel redraws
beautifully. Two separate times here, a table of healthy frame rates turned out to
have been measured over a completely black screen — once because the test pattern was
painted at one per cent brightness, once because the display window was worked out by
reading a picture that deliberately holds no pixels. Nothing else in either table so
much as twitched.

**Measure the case the instrument produces, not the one that is easy to loop.**
"0.32 ms per tile, flat" was true for adding thousands in a tight loop and wrong by a
factor of two hundred for a microscope, where tiles arrive seconds apart and each one
actually writes.

**One row is not a trend.** A reading at 3200 tiles looked like the start of a slope
and was written up that way; the next size came back faster. On a shared machine,
argue from a shape, never from a figure.

**Software rendering makes absolute frame rates meaningless**, and makes volume
rendering worse than meaningless — ray-marching is exactly what a graphics card is
for. What travels between machines is whether a number *changes* with the run size,
not what it was.
