# The governed picture grows a z-axis

> Written 2026-08-17, the evening the want was felt at the screen. The operator
> watched a survey of real three-dimensional blocks grow as one picture and
> said what they wanted in one sentence: **"I want 3D to be smooth. It should
> appear properly."** This plan says what that takes, what already exists,
> what has to be built, and how we will know it is done. It is a plan to
> review, not work in progress — nothing here is started.

## The want, and the evening that produced it

A survey was shown growing as **one picture** built from real specimen — 49
blocks of the Thy1 acquisition, each a 1.3 KB description whose pixel folders
are links back to one real tile, so 36 GB of specimen was laid out 49 times
for 195 KB and nothing was copied. The picture was three-dimensional: the
depth slider and the volume view worked, because the transfer door's composer
carries the tiles' full pyramid, depth included, in 32-plane slabs.

It grew, and the growing was **laggy** — blocks took long seconds to appear,
and the picture felt like it was being re-earned after every landing. That lag
is not a bug and no amount of fixing will remove it from that door, because it
is the door's contract: a transfer is finished, so **every** re-declaration
throws away the server's composer and its composed pieces, and the page's
whole-source refresh then refetches everything on screen into a server that
has just forgotten everything it knew. One block landed; the whole visible
picture recomposed from 120 MB chunks. Every second.

We know what smooth growth looks like because the flat governed picture
already does it: a landing costs the change, not the survey — 196 ms median
at 64 positions and 210 ms at 4,096, landing-to-visible between 90 and
225 ms, zero dark frames, warm equal to reload at every zoom, held at twenty
landings a second on this workstation (2026-08-17, real GPU). The smoothness
machinery is the governed door's: the manifest that says what may be shown,
the per-commit bake that patches only the pieces a landing touched, and the
announcement that tells the page something changed in place.

So the want is the union of the two doors, and the repository has already
decided which door the future belongs to
(`DECISION_finish_the_migration_to_one_live_path.md`): the governed picture
is to become the one live source. Three-dimensionality therefore belongs
**on the governed picture**. Teaching the transfer door to grow instead
would build a second live path, which is exactly what the decision retired.

## What already exists (less is missing than it feels)

- **The piece address space is already three-dimensional.** Both doors answer
  `level/c/z/y/x`; the governed picture simply always says `z = 0`. Nothing
  about the wire format changes.
- **Composing a slab is built, working code.** The transfer door served Thy1
  in 32-plane slabs tonight, through the same `served.py` plumbing.
- **The writer already writes depth.** `z_planes` is an ordinary profile
  field; positions on disk are stacks, and the manifest commits them whole.
- **The client needs nothing — but only because the bake exists.** Whole-source
  invalidation refetches everything on screen at every landing, and that blunt
  strategy is only survivable when the refetch **converges before the next
  landing invalidates it again**. The flat picture holds twenty landings a
  second because baked pieces are files and the refetch finishes in the gap;
  the growing 3-D demo that motivated this plan thrashed at one landing a
  second because every piece was composed afresh and the refetch never
  finished at all — the whole-picture-granularity ceiling (~2/s) this
  repository already measured and cured once, met again from the outside. So
  the bake is not an optimization in this plan; it is what makes the client's
  decided refresh strategy converge, and the slab bake's speed is therefore
  the feature's critical number.

## What has to be built

1. **Declaring the whole room, on every axis, before the first landing.**
   `declare_a_governed_picture` takes its z extent from the profile and
   declares slab-shaped pieces (the transfer door's 32-plane slab is the
   sensible starting shape) — and the same holds for time and channel **by
   definition**: the profile already says how many channels and timepoints
   the acquisition will have, so the picture is declared over its full
   (t, c, z, y, x) room on day zero. Nothing that lands may ever move the
   description. This is not caution but a measured rule: the page's in-place
   refresh re-reads pixels, never the description, so a picture whose shape
   grows only grows on screen after a reload — watched happen, twice, the
   evening this plan was written. Ground not yet imaged is expressed by
   absence, exactly as the flat picture already does it.
2. **The bake patches slabs.** A landing's dirty footprint becomes
   slabs × rows × columns. The patcher's arithmetic grows one axis, and the
   per-landing bake cost multiplies by roughly the slab count — ten at 291
   planes in 32-plane slabs. **An instrument first, as always**: extend the
   ladder's columns before trusting any of this, because a ×10 on the bake
   column changes where the ceiling sits.
3. **The derive and the announcements carry z.** Dirty pieces are named as
   (level, slab, row, column); the manifest and gateway already carry whole
   positions, so this is bookkeeping, not new truth.
4. **The serving door reads slab addresses for governed pictures** — the
   five-part form it already parses, with z finally meaning something.

## Two traps, both already written down elsewhere in this repository

- **The tall thin coarsest copy.** The smaller copies shrink y and x only, so
  a deep canvas's coarsest level is hundreds of planes of mostly-empty space,
  and the sampled percentiles that choose the display window land in that
  emptiness and describe nothing (`measure_declared_room.py` measured exactly
  this). The contrast window for a deep governed picture needs to sample
  imaged ground, not declared room.
- **Whether z halves down the pyramid is an OPEN decision, to be measured,
  not argued.** The Thy1 acquisition halves depth as it coarsens
  (291 → 146 → 73 → 37); the writer's pyramid never does. The cases:

  *For halving*: a slab of a coarse level spans more of the specimen's depth,
  so "the whole depth at a glance" becomes cheap exactly where the volume
  view and the zoomed-out flat view need it; at the coarsest level the whole
  stack is a piece or two. It is also what the acquisitions this viewer
  exists for (Thy1, mesoSPIM) already do, so interop reads it natively.

  *Against halving*: every level's bake stays a pure x/y patch — a landing's
  pixels map to one level's pieces without resampling across planes — and
  the patcher's dirty arithmetic stays the flat picture's with one more
  index. Halved levels make the per-commit patch re-derive across planes,
  which is new cost in the one place this plan says speed is critical.

  *The deciding experiment*: build the slab bake both ways behind a switch,
  run the ladder's landing and bake columns on a deep survey, and read the
  answer off the table — bake milliseconds per landing against
  bytes-fetched-per-zoom-out. Neither intuition survives contact with a
  measurement it disagrees with, and this repository has the scars to prove
  it. Until then, nothing downstream may assume either choice.

## How we will know it is done

The operator's sentence, made measurable. With the depth slider and the
volume view in use, on a growing survey of real-shaped blocks:

- a landing is **visible within the flat picture's own bound** (90–225 ms
  landing-to-visible at every rung of the ladder), and the cost of a landing
  follows the change, not the survey;
- **zero transients** — the per-frame recorder counts no frame in which held
  ground dips dark and returns, on any plane;
- **warm equals reload** — the pixel census, run at several zoom bands AND
  several planes, shows the storm session and a fresh client identical to the
  last digit;
- the storm gate's rate holds — twenty commits a second did not bend the flat
  picture on this workstation, and the slab bake must be measured against the
  same bar, not assumed past it.

The existing browser gates are the harness for all four; they grow a plane
axis in their census loops rather than new machinery.

## What is deliberately not in this plan

- No named/dirty-piece invalidation on the client — whole-source invalidation
  is the page's decided default, and the T400 measurements (2026-08-17) stand
  behind it.
- No growing pictures on the transfer door, for the reason above.
- No linking of foreign pyramids — measured impossible for Thy1-shaped data
  (only L0 aligns; the deeper levels disagree in both chunking and depth),
  and the reason is now recorded rather than just the verdict.
