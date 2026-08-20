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
  summed, per-channel colour and limits as dials, a ceiling of ten
  channels per layer (verified in the installed source), and its own
  viewer opens with only the first four turned on.
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
projection down to three numbers per pixel. Choosing each channel's colour
as a HUE is what scales -- named colours run out (which is why the
reference tools stop at eight, or four) while hues simply divide the
wheel -- and that is the next chapter's interface rather than this one's.
What bounds the count here is how many channels one program can sample
(Viv stops at ten), which is why every reference tool shows a few of a
high-plex picture at a time. For our 18-channel plate: every channel
listed in the panel, the first few showing, and the operator's own white
points deciding how the shown ones sit together.

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
Everything else the design asks for is layer state too: which channel a
brightness control reads, each channel's colour and weight, and the
mixing itself, which lives in the program text the layer is given. No
engine modification anywhere.

## The design, and what the engine allowed

**BUILT 2026-08-20.** The plan as written wanted one layer per picture, its
channels mixed inside one drawing program. The engine refused, for a reason
worth writing down because it is invisible from the outside: a brightness
control can be bound to a named CHANNEL dimension, and an OME-Zarr `c` axis
does not arrive as one. Measured on a real store: the layer reports its `c`
as a LOCAL dimension (`c'`) and a channel rank of nought, so
`invlerp ch1(channel=[1])` will not even parse. A local dimension is pinned
to one position per layer, so no single program can read two channels of it.

That is exactly why neuroglancer splits a multichannel volume into one layer
per channel, and the built design is therefore stock neuroglancer's own:

1. **One layer per channel, added by the engine.** The adding is a property
   of a layer (`blendMode = ADDITIVE`), so channels of one picture mix on the
   graphics card between layers rather than inside a program. Every channel
   reaches the screen; recolouring any of them shows.
2. **Colour, weight and window are controls, never program text.** One
   program is now shared by every flat channel, and choosing a colour costs
   one number handed to a program already compiled -- no rebuild, nothing
   re-read. The colour used to be written into the text, which compiled a
   fresh program per colour and gave every channel one of its own.
3. **The weight is carried once.** An added row contributes exactly the
   colour its program emits, so its weight lives there and the transparency
   the engine blends with stays at one; a covering row still reads the
   transparency, because that is what lets a faded row reveal what lies
   beneath. Carried in both, as it was, a channel faded as its own setting
   SQUARED -- measured at a half reading a third.
4. **Nothing is scaled to fit.** The sum clips when it overflows, as every
   reference viewer clips, and the operator's own white points are the
   remedy. Proven on the real plate: four dense channels at their measured
   windows add to white, and with each white point raised about fourfold the
   same wells read as a true composite -- green monolayer, pink nuclei, teal
   specks.
5. **The Log brightness axis turns on by itself** when the camera's range
   dwarfs the measured spread, which is what makes the full-range axis
   workable while an operator is bringing a white point down.

**The limit that remains, pinned as a measurement rather than a paragraph.**
A picture written as overlapping positions cannot mix its channels: adding
belongs to a layer, so a layer fed by several stores would add those stores
to each other and draw a bright seam along every join. Such a picture keeps
the covering rule and shows only its topmost channel. The cure is the
composed picture the server already builds -- one store, one source per
channel row, and the mixing works. `test_channels_mix.py` holds that limit as
a strict expected failure, so the day it lifts is not missed.

Touches: `scene.js` (one layer per picture, the mixing program, the
controls), `engine.js` (rows become one layer with per-channel controls
rather than one layer each), `LayerPanel.jsx` (a channel row now drives a
control, carries the hue dial, and owns the defaults), `stores.py` (the palette leaves).
Gates: the existing blend/panel gates updated, plus red-first gates that
every channel of a picture reaches the screen and answers a recolour,
that a channel's own brightness on screen does not change when another
channel is hidden or shown, that opacity fades linearly, and that the
positions of a stitched picture still cover each other without seams.
The trapping comment blocks listed in the review are rewritten to state
their conditions.

## Building it

- **Stage 0 -- the gates, red first.** A dense four-channel picture opens
  with colour and no clipped white; every channel's recolour visibly
  changes the canvas; a channel alone in its region draws at full
  brightness however many channels are open (the test the old weights
  design would have failed); opacity fades linearly; recolouring leaves
  the program's text untouched; positions of one picture still cover each
  other without seams; the Log axis is on by itself when the camera range
  dwarfs the measured spread. The existing blend, palette and channel
  gates move to the new ownership.
- **Stage 1 -- one picture, one layer, one mixing program** (`scene.js`,
  `engine.js`). A picture's channels stop being separate layers and become
  bound brightness controls of one layer; the program mixes them and
  scales the sum back only where it would overflow; coverage means
  coverage. The 3D program mixes the same way, so both views agree.
- **Stage 2 -- ownership moves** (`stores.py`, `LayerPanel.jsx`). The
  server reports only colours a run declared; the panel turns a hue dial
  for each channel, spaces the defaults around the wheel and owns them
  alone; a channel row drives a control rather than a layer, and its eye
  is a weight.
- **Stage 3 -- the many-channel convention.** A picture with more channels
  than one program samples offers them all in the panel and shows the
  first few, as every reference tool does.
- **Stage 4 -- the axis default** (`LayerPanel.jsx`). Log turns on when the
  camera's range dwarfs the measured spread; the toggle still overrides.
- **Stage 5 -- the comments.** The trapping blocks named by the review are
  rewritten to state their conditions, so the next reader inherits facts
  instead of lore.
- **Stage 6 -- proof on the real plate.** A screenshot gauntlet looked at
  with eyes: fresh open coloured and unclipped, recolour works on every
  channel, toggles rebalance nothing they should not, Auto toggles, 3D and
  2D mix alike, a stitched survey still has no seams. Then the full suite
  once, the ledger updated, pushed, the served viewer restarted.

## Closed pending detail

Fiji's exact opening display ranges could not be verified by the survey's
sub-check and remain unknown; nothing in the design turns on them. The
survey's other corrections are folded in above (Viv's ten-channel ceiling,
napari's first-channel special case, stock's own 1-99 percentile
auto-contrast, and the field-wide open-with-few-visible pattern for
high-plex data that the 18-channel plan point follows).
