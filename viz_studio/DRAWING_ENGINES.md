# Which engine draws the picture, and why there may be two

Written 2026-07-30, after measuring whether Viv can read what this project writes.

This records a decision that was made once before, on evidence that has since changed. The
earlier decision is in `docs/design/web-viewer.md` on the full-repository branch, and it is
still worth reading — nothing in it was wrong. What changed is the question being asked of it.

---

## The question

The viewer's interface is React, and the engine underneath it is neuroglancer. That works, and
everything in this repository is built on it. But neuroglancer is an *application* that has
been persuaded to behave as an engine, and it resists being embedded in somebody else's React
page in ways that are concrete rather than stylistic:

- its build step compiles workers by overwriting files **inside `node_modules`**, which a
  clean install silently undoes;
- its worker assets only resolve when the page is served from the root of a site;
- every import is through a path the package itself calls `unstable`;
- the code driving it here keeps its state in module-level variables, so a page cannot hold
  two viewers;
- and the layer that turns a store into something drawable reads `window.location.origin`, so
  the addresses are absolute against the page's own server.

None of that is fixable from outside. So the question is whether a *different* engine could
draw the everyday two-dimensional view inside a React canvas the application owns, leaving
neuroglancer to do the thing it is genuinely exceptional at.

## Why the earlier answer was "no", and why that has changed

`web-viewer.md` considered Viv and rejected it, in one sentence:

> The alternative considered was vizarr/Viv, which is the better tool for 2-D plates and
> slides but uploads a whole resolution level to the GPU for 3-D. Level 0 of a single tile
> here is 6.1 GB uncompressed, so that path can only ever show a downsampled volume.

Read that carefully. It rejects Viv **only** for three-dimensional rendering, and in the same
breath calls it the better tool for two dimensions. The measurement behind it — 6.1 GB for one
tile's full-resolution level — has not changed and is not in doubt.

What has changed is that we are no longer asking one engine to do both. If the volume view
stays with neuroglancer, the only objection on record does not apply.

## What was measured

Three stores, written for the purpose. Two of them by this project's own writer, the third by
hand because **our writer does not shard** — sharding was deliberately kept out after it was
measured losing three tiles out of four on concurrent writes.

| store | metadata read | draws | pyramid engages |
| --- | --- | --- | --- |
| 0.4, unsharded — the control | yes | yes: 241 distinct colours, spread 84.1 | yes |
| **0.5, unsharded — what we write** | yes | yes: 241 distinct colours, spread 84.1 | yes |
| **0.5, sharded — what an instrument might write** | yes | yes: 284 distinct colours, spread 78.7 | yes |

A blank panel measures 1 distinct colour and a spread of 0.0, so those numbers are a long way
from nothing being drawn.

**And it was checked against what was written, not merely that something appeared.** The
brightness ramp correlates with position across the image at exactly 1.0; the count of bright
lines on screen matches the number written into the data once the magnification is taken into
account; the two stores written as separate tiles show two tiles side by side while the
sharded one shows a single continuous ramp, each as it was made. Two channels render in their
own colours with their ramps running opposite ways. Choosing a plane and choosing a moment
both land on the right one.

**The pyramid genuinely engages.** Zoomed in, the full-resolution copy is fetched. Zoomed out,
it is fetched **not at all** and a coarser copy is used instead — which is the whole of what
makes a large acquisition affordable.

**Sharding works by the right mechanism.** The reader fetches a shard's index once, using a
request for the last few bytes of the file, then pulls each piece inside it by offset: 112
requests against four shard files. Worth knowing, though, is what sharding does and does not
buy. The index is remembered but the shard's contents are not, so every piece is still its own
request. Sharding relieves the *filesystem* of millions of small files; it does not reduce the
number of requests the viewer makes. That is the same trade-off neuroglancer has.

## The decision

**Two dimensions: Viv, as layers inside a canvas the application owns.** It is React-first, it
reads what we write including the newer format, and it draws a picture that matches the data.

**Three dimensions: neuroglancer, as a separate view.** The 6.1 GB measurement stands. Nothing
else on offer does out-of-core volume rendering at this scale.

## What this costs, so it is chosen rather than discovered

**Two engines means two caches.** Switching to the volume view will re-fetch what it needs
rather than sharing what has already been decoded. At a handful of stores that is a second or
two, not a stall — but today the 2-D/3-D toggle shares one cache and switching is free, and
that is being given up.

**Something has to own "where am I".** Position, which channels are visible, the brightness
range, which acquisition is shown. If both engines own it, the application will spend more
effort keeping them in step than on either view. One source of truth in the interface, with
both engines following it, is the arrangement to aim for.

## The trap, which is worth more than the verdict

A sharded store served by something that ignores requests for **part** of a file draws a
partly blank, structurally wrong picture — and does so **silently**. No error reaches the
page, and the loader reports itself satisfied.

Worse, and this is the part to take to heart: the blunt measurement this project uses to ask
"is there a picture on screen" **passed it**, at 252 distinct colours and a spread of 78.3.
Only a message in the browser's console revealed anything was wrong.

Two things follow. A test of a sharded store must compare the picture to what was written,
because variety of colour is not enough to catch a picture that is varied and wrong. And the
thing serving the data must honour requests for part of a file — this project's own server
does, and says in a comment that sharded zarr is exactly why, so the real path is safe. It is
plain static hosting that is not.

## What a React front end still has to write for itself

Neither is a blocker; both should be budgeted.

**The scale bar.** Viv's physical-size plumbing is only filled in for OME-TIFF, so a store read
as OME-Zarr arrives with no record of how large a voxel is — for the older format as much as
the newer. The numbers are present in the metadata Viv hands back; the application has to take
the scale out of the store's own description and give it to the scale bar. That is a small
piece of work and it must be done, because a bar that states the wrong size is worse than no
bar at all. This session found exactly that fault in the existing viewer's volume view.

**The brightness range.** Rather than sampling the image, use the window the writer already
records in the store's description. It parsed correctly on all three stores, and a measured
window has been the source of two separate faults in this project already.

**And one limit to remember**: Viv assumes each copy of the image is exactly half the size of
the one before, and does not consult the store's own description to check. That is true of what
this writer produces, so it is safe here, and it would not be for a pyramid built any other way.

## What carries over unchanged

Most of the system, which is the reason this is a smaller change than it sounds. The server,
the writer, the reading of stores, the measuring of brightness, the live path by which a run
says it has written something — none of that is tied to which engine draws. So is the way this
project tests: look at the picture, and prove the test can fail. That rule was learned the hard
way here and applies to any engine.

## Not decided

Whether the existing interface — the layer panel, the sliders, the scale bar — is ported to
the new engine or rewritten. It is written against neuroglancer's way of describing where the
view is, so it cannot move across untouched; how much of it survives is a judgement nobody has
made yet with the code in front of them.
