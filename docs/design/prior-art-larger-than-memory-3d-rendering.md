# Prior art: rendering larger-than-memory volumes with multiscale pyramids

Kept beside `prior-art-napari-progressive-loading.md` for the later
three-dimensional phase of the rendering-engine design. Looked up on
2026-09-02 from this machine, which can reach GitHub but not most journal,
forum or documentation sites; where only an abstract or a search summary
could be read, that is said. Nothing here is ours.

## The one idea every one of them shares

Every serious system below does the same four things, whatever it calls
them. Our later design should do them too, and the two-dimensional engine
should already be shaped so that it can.

1. **Bricks, not arrays.** The volume is cut into small cubes of a fixed
   size at every pyramid level (32 or 64 voxels a side is usual), and a brick
   is the unit of loading, caching and eviction.
2. **A fixed GPU budget.** A single large texture, the atlas or cache
   texture, holds however many bricks fit, and bricks are evicted least
   recently used. The picture never asks for more graphics memory than it
   was given.
3. **Indirection.** A small lookup structure (a page table, a lookup
   texture, or an octree) tells the shader where each brick of each level
   lives in the atlas, or that it is missing.
4. **Coarse stands in for fine.** When the brick the ray wants is not
   resident, the shader samples the coarsest resident brick that covers the
   place, so the picture is complete at once and sharpens as bricks arrive.
   How elegantly the substitution is done is most of the difference between
   the systems.

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

- Bricks, a fixed atlas, indirection and coarse-for-fine substitution are
  the design. Our two-dimensional tiles are bricks with a depth of one, and
  the tile cache should be written so that a brick with depth is the same
  object with one more coordinate.
- Several volumes at once is our ordinary case (channels, and collections at
  their own placements), so the residency-octree line of work fits us better
  than single-volume ray casters.
- WebGPU is where the browser-native work has gone. Our two-dimensional
  engine can be WebGL2; the three-dimensional phase should assume WebGPU and
  the compute-shader ray marching Kiln uses.
- What none of them do is our sparse, many-position layout with a register:
  they assume one dense volume, or a few. The register and the fan-in rule
  are ours to design; the brick machinery beneath them is not new.

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
