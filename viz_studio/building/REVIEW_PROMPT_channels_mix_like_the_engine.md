# Review prompt: attack the channel-mixing plan before it is built

You are reviewing `PLAN_channels_mix_like_the_engine.md` in this folder,
adversarially, before a line of it is implemented. The plan converges the
viewer's channel display on stock neuroglancer's own multichannel shape
(one shared shader, colour and window as controls, additive for every
channel layer, opacity carried once) plus one stated deviation:
sum-normalised channel weights so a dense plate cannot clip to white.

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
   Does the scale-back read as a brightness ceiling an operator will
   misread as saturation, and is the plain divide-by-peak the right curve?
   Does binding a control to a channel cost a rebuild when the panel
   changes which channels show?
2. **Colour chosen as a hue.** The operator turns a hue (with saturation
   beside it) and the panel hands the engine red-green-blue. Attack it:
   does anything downstream need the triple back (a run that DECLARED a
   colour, a saved scene, the row swatch, annotations)? Is a hue-only
   interface a loss for the operator who wants an exact colour, and what
   is the escape hatch? Are equal hue steps good enough for eighteen
   channels, or does the perceptual spacing (OKLCH) need to be in the
   first build rather than a later refinement? Where does the hue live
   when a scene is saved and reopened?
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
7. **Auto and windows under additive.** The Auto light compares the window
   to the measured one per channel. With weights rescaling on visibility
   toggles, can the picture change while every Auto light stays lit —
   and is that acceptable to an operator?
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
