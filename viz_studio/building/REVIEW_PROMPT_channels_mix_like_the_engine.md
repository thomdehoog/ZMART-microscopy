# Review prompt: attack the channel-mixing plan before it is built

You are reviewing `PLAN_channels_mix_like_the_engine.md` in this folder,
adversarially, before a line of it is implemented. The plan keeps stock
neuroglancer's idioms (colour, window and weight as controls; nothing
operator-adjustable in the program text) but departs from its layer
arrangement: instead of one layer per channel added together, ONE layer
holds a picture and its channels mix inside one drawing program, where the
total is visible. The sum is NOT rescaled: it clips when it overflows, as
every reference viewer clips, because rescaling would make a channel's own
appearance depend on which other channels happen to be switched on. The
colour interface is unchanged in this build.

Ground rules for this review, learned the hard way this week: the
codebase's comments are HISTORY, not law — verify any constraint you lean
on against the installed engine's source
(`viz_studio/frontend/node_modules/neuroglancer/lib/`), especially
`layer/multi_channel_setup.js`, `sliceview/volume/image_renderlayer.js`,
`sliceview/frontend.js`, `trackable_blend.js` and
`webgl/shader_ui_controls.js`. Two prior reviews already audited the old
constraints; do not re-litigate those verdicts unless you find contrary
evidence in the source.

Attack these specifically:

1. **The one-layer mixing program.** A picture's channels become bound
   brightness controls (`invlerp ch0(channel=[0])`) of ONE layer, mixed in
   the program, with the sum scaled back only where it would overflow.
   Attack it: how many channels can one program sample before the engine's
   uniform or texture limits bite, and what happens at the boundary? The
   program's text depends on the channel count -- when exactly is it
   rebuilt, and can that rebuild land while an operator drags a slider?
   Does binding a control to a channel cost a rebuild when the panel
   changes which channels show? And the volume question: with one
   program sampling every channel, must every channel of the visible
   area be resident even when its weight is nought -- and if so, what
   does that cost on the 18-channel plate against today's one-layer-
   per-channel arrangement, where hiding a channel stops its reading?
2. **Clipping as the accepted outcome.** With no rescaling, a dense
   many-channel picture opens clipped until the operator brings white
   points down. Attack it: is the remedy discoverable from the panel, does
   the histogram tell the operator which channel to turn, and should the
   opening windows be gentler when a picture has many channels -- or would
   that be the same hidden adjustment under another name?
3. **Positions inside one layer.** The plan claims channel mixing and
   position stitching stop competing: channels mix inside a pass, positions
   cover each other across passes. Verify against the engine's draw order
   that this holds for a growing live picture, and say what the coverage
   term must be when some channels have data at a pixel and others do not.
4. **Row kind, if any remains.** The earlier draft chose blend by row KIND (channel-of-one-picture
   vs stitched-from-files) instead of counting sources. Pin down the exact
   predicate: where does the scene learn the kind, what happens to a live
   row that starts single-source and grows, and can a row change kind while
   an operator is watching it? The un-enforced middle here was yesterday's
   defect; do not let a new one ship.
5. **The shared shader.** One program for all flat channel rows means the
   colour arrives as `#uicontrol vec3 color`. Check the engine's control
   restore path (`applySettings` restores `shaderControlState` wholesale):
   can a window update race a colour update? Does the LUT (colormap) case,
   which keeps per-LUT program text, still share programs per LUT?
6. **The 3D view.** The plan says the volumetric shader takes its colour as
   a control the same way. Verify the volumetric path's blending is not
   silently different (MIP volume rendering vs slice blending), and that
   the 2D/3D parity the operator observed inverted (3D mixed, 2D covered)
   truly converges under the plan.
7. **Auto and windows under the mixing program.** Check the invariant the
   design turns on: a channel's contribution must depend only on its own
   window, colour and weight -- never on which other channels are showing.
   Find any path that breaks it.
8. **The stitched-regime label.** The plan promises the panel says why a
   stitched multichannel row cannot colour-mix. Where exactly, in whose
   words, and is the claim even true after the server-side composition path
   makes most rows single-source?
9. **What the plan forgot.** Segmentation masks, the targets layer, the
   18-channel plate's open-with-few-visible convention (who decides which
   few?), the replayed live runs whose rows are born mid-run.

Deliver findings as a numbered list, each with the failure scenario spelled
out and, where you have one, the smaller design that avoids it. Verdicts
"build as written", "build with amendments", or "do not build" at the end.
