# Plan: channels mix like the engine does

> Written 2026-08-20, after a day of driving the real 336-well plate and an
> adversarial review of the viewer's channel display against the engine's own
> source. The operator's instruction that shaped it: stay as close as
> possible to how neuroglancer itself does things. Status: DESIGN, awaiting
> the owner's go. Nothing here is built yet.

## The story so far, in one paragraph

On the real four-channel plate, only the topmost channel ever reached the
screen: recolouring the others changed not one pixel. We made channels add
together like light, gave them distinct colours, and the plate turned pure
white instead — every well clipped. Each step was locally reasonable and the
result was still wrong, so the design was reviewed from scratch by agents
told to treat the code's own comments as history rather than law, and to
verify every claimed constraint against the engine's source.

## What we learned

### The engine already contains the answer

Neuroglancer ships its own multichannel display
(`node_modules/neuroglancer/lib/layer/multi_channel_setup.js`), and it
contradicts nearly every rule our comments treat as law. Stock behaviour,
verified in the installed source:

- One image layer per channel, all sharing **one** small drawing program.
- The channel's colour is an adjustable **control** (`#uicontrol vec3
  color`), a number handed to a program that is already compiled — exactly
  like the brightness window. Recolouring never rebuilds anything.
- Every channel layer — including the bottom one — is **additive** with
  opacity 1. No channel can hide another.
- The program is two lines: window the value, emit `colour × value`. There
  is no "was this spot imaged" transparency, no opacity in the program.
- Default colours are red, green, blue, then white; declared (omero)
  colours win. Channels beyond the fourth open hidden.

### Which of our commented "constraints" are real

| Claim in our comments | Verdict |
|---|---|
| "The bottom-most image draws with blending off" | Only under the DEFAULT blend. An additive layer blends everywhere. Our essay derived a whole architecture from the special case. |
| "Additive sums overlapping tiles into bright seams" | TRUE — but it is a fact about rows stitched from MANY files, not about additive. It was written as a categorical rejection and delayed channel mixing for a chapter. |
| "Colour must be baked into the program text" | FALSE. The engine's colour control is a dial. Our way recompiles per recolour and defeats the engine's program cache. |
| "Transparency must mean coverage" | Only load-bearing under DEFAULT blend stacking. Stock's channel rows have no coverage term at all. |
| "Opacity-squared fade is unavoidable" | FALSE — an artifact of carrying opacity twice. Worse: since yesterday's additive change, every blended channel row fades as opacity SQUARED. A live defect. |
| Windows travel as controls, not text | TRUE — the one the code got right. |

### How the reference viewers actually do it

- **Stock neuroglancer**: as above.
- **napari**: per-channel colormap + contrast limits + gamma, additive over
  black when opened with a channel axis. Same arithmetic.
- **ImageJ/Fiji composite**: sums the coloured channels and clips (verified
  in source; composite display caps at 8 channels).
- **vizarr (Viv)** — installed in our own node_modules from the
  pluggable-engine days: all channels sampled in ONE drawing pass and
  summed, per-channel colour and limits as dials, a channel-count ceiling
  of about six per layer.
- **Every one of them clips dense-in-every-channel data to white.** There
  is no hidden mechanism anywhere; fluorescence usually escapes because
  each channel is mostly dark, and stock's red/green/blue defaults cannot
  overflow a colour component by construction.

### Why OUR plate went white, precisely

Two multipliers, both ours: the 1–99 percentile auto-window maps a dense
monolayer near full brightness in every channel (the reference viewers'
defaults are gentler), and our palette (green, magenta, cyan, amber) shares
colour components between channels — together they oversubscribe the
screen's red/green/blue budget about 2.75×, so clipping begins at 40%
brightness wherever channels overlap. Distinct hues cannot fix this:
distinctness is a hue property, clipping is a component-sum property.

### The operator's cross-check: 3D mixed, 2D did not

Colours DID mix in the 3D view while the flat view showed only the top
channel -- the same root cause seen from the other side. The 3D drawing
carries brightness in its transparency, so dim voxels are see-through and
channels below shine through; the flat drawing carried a hard yes/no "was
this spot imaged" -- fully opaque over any data -- so the top channel
occluded everything. Removing that yes/no term from channel rows makes both
views mix the same way.

### Five channels and more

A screen has three primaries, so five or more channels are always a
projection down to three numbers per pixel. The workable shapes: hues
around the colour wheel for any count; **weights scaled so the visible
channels can only just reach white** (then no count ever clips, and
all-bright honestly reads as white); winner-takes-the-pixel for very high
counts (10–40-plex); and the stock convention that channels beyond the
first few open hidden. For our 18-channel plate: palette turns around the
wheel, sum-normalised weights, open with a handful visible.

### Honest verdicts on yesterday's three changes

- *Additive for single-source rows*: right direction, wrong trigger — it
  keyed the display decision on how many FILES a row came from, left tiled
  multichannel runs with the original hidden-channels bug, and introduced
  the opacity-squared fade.
- *Default palette turns in the server*: right instinct, wrong owner (the
  palette now lives in three places), and it could never fix clipping.
- *Brightness axis to the camera's range*: honest for the histogram, but
  without the Log axis on by default it recreates the
  two-pixels-of-useful-travel problem the old rule existed to prevent.

## The owner's model, which the design serves

Channels go into neuroglancer as layers, and everything about the mixing is
handed to it through neuroglancer's own API as layer state. The engine's
layer API takes, per layer: a drawing program, adjustable controls for it
(the brightness window already travels this way), a blend mode, and an
opacity. Today's one violation of that model is the colour, written into
the program text instead of handed over as a control -- the plan ends it.
The just-reach-white scaling also fits without anything special: the panel
computes the scaled values and delivers them as ordinary colour settings
through the same API. No engine modification anywhere.

## The design

**Converge on stock neuroglancer's multichannel shape, plus one addition it
lacks: sum-normalised channel weights.** Concretely:

1. **One shared program for all flat channel rows.** Colour (and weight)
   become dials, exactly like the window. `scene.js` stops writing colours
   into program text; recolouring becomes free.
2. **Channel rows always add, bottom included; opacity has one carrier**
   (`layer.opacity`); the coverage transparency term disappears from
   channel rows. This deletes the opacity-squared defect and the
   only-the-top-channel-shows defect at their root.
3. **Rows stitched from many files keep the covering rule**, stated plainly
   as a stitching regime, chosen by row KIND — not by counting sources —
   and marked in the panel as not colour-mixable. It retires when the
   server serves every row as one composed picture (already the direction
   of travel).
4. **Sum-normalised weights**: scale the visible channels' colours so
   together they can only just reach white. All-bright reads as white
   honestly; any imbalance reads as colour; hiding channels brightens the
   rest automatically; a single channel is untouched. This is the entire
   white-plate fix, and it is one multiplication on a dial the engine
   already owns. Stated deviation from stock — stock clips this data too.
5. **Defaults owned once.** The server reports colours a run DECLARED, or
   nothing; the default palette lives in exactly one place (the panel).
   Keep green/magenta first (the colour-blind-safest pair) — with
   normalisation, any palette is safe from clipping, so the stock
   red/green/blue argument loses its force.
6. **The Log brightness axis turns on by itself** when the camera's range
   dwarfs the measured spread, so the full-range histogram stays usable.
7. The per-channel windows stay the server's measured 1–99 percentile: it
   also draws the histogram, works before the graphics card has read a
   pixel, and is reproducible. Stated deviation from stock's on-the-fly
   guess.

Touches: `scene.js` (the program and the layer settings), a little of
`engine.js` and `LayerPanel.jsx`, removal of the palette from `stores.py`.
Gates: the existing blend/panel gates updated, plus red-first gates that a
dense four-channel picture opens unclipped, that opacity fades linearly,
and that a stitched multichannel row says on the panel why it cannot mix.
The trapping comment blocks listed in the review are rewritten to state
their conditions.

## Building it

- **Stage 0 -- the gates, red first.** A dense multichannel picture opens
  unclipped (a bounded share of pure-white pixels, and every channel's
  recolour visibly changes the canvas); opacity fades linearly (half
  opacity measures half brightness, not a quarter); recolouring leaves the
  drawing program's text untouched (the colour arrives as a control); a
  stitched multichannel row keeps covering and the panel says why; the Log
  axis is on by itself when the camera range dwarfs the measured spread.
  The existing blend, palette and channel gates move to the new ownership.
- **Stage 1 -- the program and the API state** (`scene.js`, a little of
  `engine.js`). One shared drawing program for flat channel rows (window
  and colour as controls, emit colour x value); the coverage term leaves
  channel rows; blend chosen by row kind; opacity carried once, in
  `layer.opacity`. The 3D program takes its colour as a control the same
  way.
- **Stage 2 -- ownership moves** (`stores.py`, panel). The server reports
  only colours a run declared; the panel assigns palette turns to
  colourless channels and scales the visible set to just-reach-white,
  rescaling when eyes toggle; the duplicate palette leaves the server.
- **Stage 3 -- the axis default** (`LayerPanel.jsx`). Log turns on when
  the camera's range dwarfs the measured spread; the toggle still
  overrides.
- **Stage 4 -- the comments.** The five trapping blocks named by the
  review are rewritten to state their conditions, so the next reader
  inherits facts instead of lore.
- **Stage 5 -- proof on the real plate.** A screenshot gauntlet looked at
  with eyes: fresh open coloured and unclipped, recolour works on every
  channel, toggles rebalance, Auto toggles, 3D and 2D mix alike. Then the
  full suite once, the ledger updated, pushed, the served viewer
  restarted.

## One pending detail

Fiji's exact opening display ranges are still being confirmed; nothing in
the design turns on them.
