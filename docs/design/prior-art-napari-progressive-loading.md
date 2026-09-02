# Prior art: napari's progressive loading for 2D and 3D

Kept for the later three-dimensional phase of the rendering-engine design
(`own-rendering-engine-and-position-register.md`). Looked up on 2026-09-02.
Nothing here is ours; it is what napari did, and what of it is worth
borrowing when the time comes.

## The pull request

- napari/napari pull request 9067, "Progressive loading for 2D and 3D", by
  Kyle Harrington (kephale), opened June 2026, experimental and opt-in
  (Preferences, or `NAPARI_PROGRESSIVE_LOADING=1`). At the last discussion
  it was slated to merge into the experimental namespace, with follow-ups
  promised: documentation, splitting it into parts, and coordination with a
  view-direction refactor.
- Its own words: "a production-grade streaming pipeline that works with real
  remote data (tested against zebrahub OME-Zarr)".
- Depends on three small merged fixes: a half-voxel offset fix (9065), a
  status fix for RGB in 3D (9135), and a multiscale slice fix when switching
  to 3D (9141).
- Reviewer's main objection (brisvag): it is "at least 4 (entirely?)
  orthogonal PRs" in one: progressive loading, 3D pyramid rendering, vispy
  changes, and texture management.
- Known gap in its description: moving the dims slider does not re-render;
  only a zoom triggers a level update.

## How it works

- Viewport-bounded three-dimensional sub-volume tiles, fetched front to back.
- Zoom-driven automatic level selection in 3D.
- The coarsest level is kept resident as a backdrop that fills the volume
  while finer tiles stream in.
- An interaction hold: streaming is suspended while the camera is being
  moved, and resumed after.
- Per-chunk partial GPU texture updates (`glTexSubImage3D`) into
  double-buffered volume textures, with uploads metered to the frame rate so
  a frame is never stalled by an upload.
- A worker pool with rate limiting; a "virtual data" abstraction over lazy
  multiscale arrays; generative zarr stores (Mandelbrot, Mandelbulb) for
  tests.

## Related, merged

- Pull request 8917 (May 2026): a manual lock on the multiscale level for 2D
  and 3D, `layer.locked_data_level`, with a check against the GL texture limit
  that disables levels too large for the card.
- Pull request 8715 (April 2026): a materialised thumbnail level for
  multiscale 2D.
- Issue 5942 is the roadmap item, "Performant 3D rendering of
  larger-than-memory data for all layer types", open since June 2023 and in
  early progress; issue 4856 asks that 3D open on a level that fits in RAM.
- A plugin, cellgeni/napari-large-3d-vis, does the crude version: a coarse
  level when the camera is outside the volume, a RAM-bounded crop when it is
  inside; at most four channels.

## What of it applies to us

- None of the code. It is Python, vispy and desktop OpenGL inside Qt; our
  engine is WebGL in a browser page.
- The shape matches the design already written for the later phase: kept
  coarse level as backdrop, viewport-bounded tiles, fetch order by what the
  eye meets first, metered uploads, double buffering so the old picture stays
  until the new one is whole.
- Worth adopting in two dimensions already: the interaction hold, which stops
  fetching while the hand is moving the view and spends the budget on the
  frame; and metering uploads to the frame rate.
- Worth avoiding: one pull request that is four. Data source, cache,
  renderer and option are separate stages in our order of work for this
  reason.

## Links

- https://github.com/napari/napari/pull/9067
- https://github.com/napari/napari/pull/8917
- https://github.com/napari/napari/pull/9065
- https://github.com/napari/napari/issues/5942
- https://github.com/napari/napari/issues/4856
- https://github.com/cellgeni/napari-large-3d-vis
