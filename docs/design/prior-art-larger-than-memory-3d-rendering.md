# Prior art: rendering larger-than-memory volumes with multiscale pyramids

Kept beside `prior-art-napari-progressive-loading.md` for the later
three-dimensional phase of the rendering-engine design. Looked up on
2026-09-02 from this machine, which can reach GitHub but not most journal,
forum or documentation sites; where only an abstract or a search summary
could be read, that is said. Nothing here is ours.

## A correction, added after review

Codex's review of the engine design (`docs/reviews/2026-09-02-review-of-the-rendering-engine-design-by-codex.md`,
finding 8) is right that this note overreached in two places. "Every one of
them" and "all browser-native work has moved to WebGPU" are not supported by
a survey that could read several entries only as abstracts; and neuroglancer
itself, in the version this project pins, keeps a texture per chunk rather
than one atlas. What the systems below do share is narrower and still
useful: bounded residency, multiscale chunks, an explicit lookup, and a
coarse fallback while fine data arrives. The atlas-plus-lookup layout is one
way to get there, not the way. The engine design no longer commits to it,
and a two-dimensional tile cache does not become a three-dimensional one by
adding a coordinate: bricks change filtering, borders, transfer size and
sampling, and WebGPU has a different resource model from WebGL2. Read the
section below with that in mind.

## What they share, said no more strongly than the evidence allows

The systems below differ in a great deal, and this note could read several
of them only as abstracts. What can be said of all of them is narrow:

1. **Bricks, not arrays.** The volume is cut into small blocks of a fixed
   size at every pyramid level, and a block is the unit of loading, caching
   and eviction.
2. **A bounded budget of graphics memory**, with some eviction rule when it
   is full. How the resident blocks are laid out differs: some use one large
   atlas texture, neuroglancer in the version this project pins keeps a
   texture per chunk.
3. **An explicit lookup** that tells the renderer where a block is resident,
   or that it is missing. Whether that lookup is a texture, a page table, a
   tree, or plain code on the CPU side differs.
4. **Coarse stands in for fine.** When the block a ray wants is not resident,
   a coarser resident block that covers the place is sampled instead, so the
   picture is complete at once and sharpens as blocks arrive.

## Web, browser-native

- **Kiln** (github.com/MPanknin/kiln-render, Apache 2.0, 2026). A WebGPU
  out-of-core volume renderer that reads OME-Zarr 0.4 and 0.5 directly, up to
  four channels, uint8, uint16 and float32. Fixed VRAM footprint through a
  brick atlas and virtual-texture indirection; level of detail chosen by
  screen-space error; least-recently-used brick cache; compute-shader ray
  marching with direct volume rendering, maximum projection, isosurface and
  slice modes. Needs WebGPU (Chrome or Edge 113, Safari 26, Firefox 141).
  Listed in the OME-NGFF tools registry. The closest thing to what we would
  build for 3D, and the one to read first; its README does not say how it
  schedules requests or what its numbers are.
- **Residency Octree** (Herzberger, Hadwiger, Krüger, Sorger, Pfister,
  Gröller, Beyer; IEEE VIS 2023, arXiv 2309.04393; a web renderer). Abstract
  read only. The point: an octree couples traversal with resolution choice,
  which makes empty-space skipping costly; a page table lets any resident
  brick be used from any level but gives no clean rule for substituting
  coarser data. The residency octree keeps a resolution-independent spatial
  tree and, per node, records which bricks of which levels are resident, so
  the shader can skip empty space by the tree and substitute by residency.
  Built for several volumes at once, which is our channels-and-collections
  case. Worth reading in full when the time comes.
- **Neuroglancer's volume rendering** (google/neuroglancer,
  `src/volume_rendering`). Ray marching through the chunks its ordinary
  chunk manager already prioritises, with a resolution indicator that sets
  the number of depth samples from the voxel spacing and view, opacity
  corrected for the sampling ratio, and modes for direct, maximum and minimum
  projection. It reuses the same chunk cache as the slice views, which is
  the same reuse our design promises. Its documentation says nothing about
  memory limits.
- **webKnossos** (scalableminds/webknossos, Nature Methods 2017). Data in
  cubes of 1024 voxels a side, streamed to the browser in buckets of 32
  voxels a side, which is the unit of request, cache and GPU upload; several
  magnifications; the client renders orthogonal slices from bucket textures
  and, more recently, 3D. Built for petabyte connectomics at interactive
  speed. Only the README and search summaries could be read here; the paper
  and documentation are the sources.
- **Viv** (hms-dbmi/viv). Multiscale 2D on the web from Zarr and OME-TIFF;
  its 3D is a whole-volume upload of one level, not out-of-core. Known to us
  already and measured slower than neuroglancer for our data.

## Desktop and Java, worth reading for the cache design

- **BigVolumeViewer** (bigdataviewer/bigvolumeviewer-core, Pietzsch). Adds a
  GPU cache tier to BigDataViewer's CPU cache: one large 3D cache texture cut
  into uniform blocks (32 voxels a side is the example), and a 3D lookup
  texture with one voxel per block of the base resolution pointing into the
  cache; ray casting with a step size adapted to viewer distance; the
  resolution level per block chosen from the view. The clearest published
  description of the atlas-plus-lookup pattern; the tech-demo thread on
  image.sc and the scenery paper (arXiv 1906.06726) describe it.
- **Voreen** (arXiv 2207.12746). Out-of-core bricking with an octree for
  level-of-detail selection and CPU-side caching; a mature reference for the
  bricking arithmetic.
- **Livre** (Blue Brain, arXiv 1706.10098). Octree level of detail, a
  task-parallel rendering pipeline, multi-GPU; a reference for what the
  scheduling looks like at the very large end.

## Papers on the technique itself

- "Octree Textures on the GPU" (GPU Gems 2, Lefebvre, Hornus, Neyret):
  the origin of octree-as-texture indirection.
- Gobbetti, Marton, Iglesias Guitián, "A single-pass GPU ray casting
  framework for interactive out-of-core rendering of massive volumetric
  datasets": bricks in an octree, an adaptive loader keeping a view- and
  transfer-function-dependent working set on the GPU.
- Liu, Clapworthy et al., "Octree Rasterization: Accelerating High-Quality
  Out-of-Core GPU Volume Rendering": rasterise the proxy geometry of a
  view-dependent cut through the octree and cull empty space.
- Balsa Rodríguez et al., "State-of-the-Art in Compressed GPU-Based Direct
  Volume Rendering" (2014): the survey, for when compression of resident
  bricks becomes the question.

## What of it applies to us, and what does not

- The four shared ideas apply: bounded residency, multiscale blocks, an
  explicit lookup, and a coarse fallback while fine data arrives. The
  particular layouts do not transfer: a two-dimensional tile cache does not
  become a three-dimensional one by adding a coordinate, because bricks
  change filtering, borders, transfer size and sampling, and WebGPU has a
  different resource model from WebGL2. The engine design therefore commits
  to a clean separation of tile source, cache policy and drawing, and to
  nothing more.
- Several volumes at once is our ordinary case (channels, and collections at
  their own placements), so the residency-octree line of work is the one to
  read most closely when the three-dimensional phase comes.
- The browser-native out-of-core renderers found here use WebGPU; that is a
  fact about these projects, not a survey of the field. The two-dimensional
  engine is WebGL2, and the three-dimensional phase will choose from
  measurements.
- What none of them do is our sparse, many-position layout with a register:
  they assume one dense volume, or a few. The register and the cost model are
  ours to design; the block machinery beneath them is not new.

## Links

- https://github.com/MPanknin/kiln-render
- https://arxiv.org/abs/2309.04393
- https://github.com/google/neuroglancer/blob/master/src/volume_rendering/README.md
- https://github.com/scalableminds/webknossos
- https://github.com/bigdataviewer/bigvolumeviewer-core
- https://arxiv.org/abs/1906.06726
- https://arxiv.org/abs/2207.12746
- https://arxiv.org/abs/1706.10098
- https://github.com/hms-dbmi/viv
- https://github.com/cellgeni/napari-large-3d-vis
