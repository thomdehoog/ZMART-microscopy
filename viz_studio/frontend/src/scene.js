/**
 * Turning what the panel says into what the engine should draw.
 *
 * This is the translation layer, and it is kept on its own because none of it
 * touches React or the browser: give it the panel's state and it hands back plain
 * descriptions of layers, which `engine.js` then applies to the engine. That makes
 * it the easiest part of the viewer to reason about and to check, and it keeps the
 * shell free of the fiddly business of writing shader programs.
 */

// A lookup table paints a single channel in a run of colours rather than one flat
// colour: dim values one shade, bright values another, with a smooth path between.
// On a single channel that reads far more detail than a plain brightness ramp,
// which is why it is a staple of microscopy display.
//
// These are written as the small shader program the engine already compiles for
// every layer, so nothing new runs anywhere -- the colour is decided on the
// graphics card exactly as a flat colour is. The stops are the well-known
// perceptually-even maps: evenly spaced in apparent brightness, so equal steps in
// the data look like equal steps on screen, and none of them is red-green.
export const LOOKUP_TABLES = {
  viridis: [[0.267,0.005,0.329],[0.190,0.407,0.556],[0.208,0.718,0.473],[0.993,0.906,0.144]],
  magma:   [[0.001,0.000,0.014],[0.443,0.122,0.507],[0.925,0.412,0.372],[0.987,0.991,0.750]],
  fire:    [[0.000,0.000,0.000],[0.600,0.100,0.000],[1.000,0.650,0.000],[1.000,1.000,0.900]],
  ice:     [[0.000,0.000,0.100],[0.000,0.400,0.700],[0.400,0.800,1.000],[1.000,1.000,1.000]],
};

// The colour maps on offer, worked out once. Building this list inside the render
// would hand the panel a brand-new array every time anything at all changed, and
// the panel would have to assume the choices had changed with it.
export const LOOKUP_TABLE_NAMES = Object.keys(LOOKUP_TABLES);

// Turn a table of colour stops into the few lines of shader that walk between
// them. Straight-line blending between neighbouring stops is enough: the stops are
// chosen so that is faithful, and it keeps the generated program small.
export function lutShader(stops) {
  const literal = (c) => `vec3(${c.map((v) => v.toFixed(4)).join(",")})`;
  let body = `  vec3 c = ${literal(stops[0])};\n`;
  const step = 1.0 / (stops.length - 1);
  for (let i = 1; i < stops.length; i++) {
    const lo = ((i - 1) * step).toFixed(4);
    body += `  c = mix(c, ${literal(stops[i])}, clamp((v - ${lo}) / ${step.toFixed(4)}, 0.0, 1.0));\n`;
  }
  return `vec3 zmartLut(float v) {\n${body}  return c;\n}\n`;
}

// Real acquisitions occupy a narrow band of the 16-bit range, so without an
// explicit window they render black. In 3-D the intensity drives opacity as
// well, or every background voxel along the ray adds haze and the specimen is
// lost in fog.
//
// Note what is *not* written into the text below: the contrast window itself, and
// the 3-D opacity. Both are declared as controls with no particular value, and
// the values are sent separately (see `shaderControlsFor`). The reason is worth
// knowing. This little program runs on the graphics card, and the engine has to
// compile it before it can draw. Writing the numbers into the text means a
// different program every time a contrast handle moves — so dragging one would
// recompile the program for every layer, several times a second. Declared as
// controls, the numbers are sent to a program already compiled, which is what
// makes dragging smooth however much data is open.
export function shaderFor(color, volumetric, lut = null) {
  let source = "#uicontrol invlerp normalized\n";
  const stops = lut ? LOOKUP_TABLES[lut] : null;
  if (stops) source += lutShader(stops);
  // Declared in both views, and the flat one is the interesting case -- see the
  // long note further down about why an opacity that reaches the picture only
  // through the alpha cannot dim the bottom-most row.
  source += "#uicontrol float opacity slider(min=0, max=1, default=1)\n";
  if (volumetric) {
    // Fading the far side of the specimen away, which the engine does not offer
    // and napari calls an attenuated projection. Everything along a line of sight
    // otherwise arrives with equal weight, so a deep specimen reads as one flat
    // sheet with no telling front from back. `depthAtRayPosition` is declared by
    // the engine immediately above this program and set afresh at every step
    // along the ray, so all that is needed here is to weigh by it.
    //
    // Nought means no fading at all, which is exactly the old behaviour, so this
    // changes nothing until somebody asks for it.
    source += "#uicontrol float attenuation slider(min=0, max=8, default=0)\n";
    const faded = "exp(-attenuation * depthAtRayPosition)";
    // `emitIntensity` is what decides the contest in a projection: the engine
    // keeps whichever voxel along the ray reports the largest value, and only
    // then asks for its colour. Fading the colour alone -- which is all
    // `emitRGBA` can do -- dims a distant winner without letting a nearer, dimmer
    // voxel win, so it reads as shading rather than as depth. Fading the
    // *intensity* is what napari means by an attenuated projection.
    //
    // Safe in both modes. Where there is no projection the engine declares
    // `void emitIntensity(float value) {}` and the call costs nothing, and at no
    // fading `exp(0)` is 1, so the picture is exactly what it was before.
    const chooses = `emitIntensity(v * ${faded});`;
    if (stops) {
      return source + "void main() { float v = normalized();"
        + ` ${chooses} emitRGBA(vec4(zmartLut(v), v * opacity * ${faded})); }`;
    }
    const [r, g, b] = color || [1, 1, 1];
    return source
      + "void main() { float v = normalized();"
      + ` ${chooses} emitRGBA(vec4(${r}, ${g}, ${b}, v * opacity * ${faded})); }`;
  }
  // A flat picture has three things to get right at once, and they pull against
  // each other, so it is worth setting out all three before the code. The third
  // was added on 6 August 2026 and is at the bottom, beside `covered`.
  //
  // **The brightness has to reach the screen.** Turning the contrast handles is how
  // a microscopist finds their specimen, so whatever window is chosen must change
  // what the picture looks like. That means the *colour* the shader emits has to
  // carry the brightness: `colour × v`, where `v` is the value after the window has
  // been applied.
  //
  // **Ground nothing has been imaged on has to come out transparent, not black.**
  // Most of a row is usually empty — a canvas is declared to the size of the stage
  // and filled in as the run goes, so at the start it is empty everywhere. A row
  // drawn opaque everywhere therefore blacks out every row below it, and an
  // experiment with an overview and a target scan, or simply two channels, shows
  // only whichever happens to be on top. Both rows load, both hold their data, and
  // one of them is invisible. That means the *transparency* has to say whether this
  // spot was imaged at all — and nothing else.
  //
  // So brightness goes in the colour and coverage goes in the transparency. They are
  // two separate questions and each gets its own channel.
  //
  // This corrects an earlier attempt that put the brightness into the transparency
  // instead, on the belief that the engine multiplies colour by transparency before
  // drawing. It does not, for the bottom-most picture on screen: there it switches
  // blending off altogether and writes the colour straight out, using transparency
  // only as a yes-or-no test for "is this background?". A window chosen by the
  // operator therefore never reached the picture — every window drew the same flat
  // white shape — which is the fault this shape fixes.
  //
  // Two temptations to record, because both are wrong in ways that are hard to see.
  // Writing `vec4(colour * v, v)` fixes the bottom picture and quietly darkens every
  // picture above it twice over, because the engine's ordinary blending is
  // *straight* transparency rather than the pre-multiplied kind and so multiplies by
  // `v` a second time. And asking for additive blending fixes the brightness by
  // making overlapping tiles sum into bright seams, which breaks the property the
  // several-images arrangement exists to provide: where tiles overlap, one picture is
  // simply drawn over the other and the result looks as it would have if a single
  // image had been used.
  const covered = "v > 0.0 ? 1.0 : 0.0";
  // **And the opacity goes in the colour, not only in the alpha.** This is the
  // third thing the flat shader has to get right, and it was missing until
  // 6 August 2026, when the slider was found to be doing nothing whatsoever.
  //
  // The engine draws the **bottom-most** image of a slice view with blending
  // switched off -- `image_renderlayer.js:setGLBlendMode` enables it only for
  // `renderLayerNum > 0`. Nothing then reads that row's alpha except the
  // composite, which asks `sampledColor.a == 0.0` and paints the background where
  // that is true. So alpha is a yes-or-no answer to "was this spot imaged", and an
  // opacity of 0.4 is just as much a yes as 1.0. Measured on one open channel, the
  // picture came out 18.61 grey levels at 1.0, at 0.5 and at 0.1 -- the same
  // number, not merely a similar one. Handing the opacity to `layer.opacity` or
  // declaring it as a shader control and putting it in the alpha are the same
  // thing arriving by two roads, and both were measured to change nothing at all.
  //
  // The colour is the only part of the bottom row's drawing that survives, so that
  // is where the opacity goes. `layer.opacity` still carries it into the alpha as
  // well (see `layersFor`), and that half is what a row **above** the bottom one
  // needs: without it a fading row would blacken whatever is beneath it instead of
  // revealing it, which was measured too -- the row underneath went from 0.90 grey
  // levels to 0.00.
  //
  // The price, which is real and is why this is written out at length: a row that
  // is not the bottom one now has the opacity applied twice, once to its colour
  // and once as the alpha it is blended with, so it fades as opacity *squared*.
  // Measured on a second channel, a half reads 1.74 where it used to read 3.50,
  // while what shows through underneath is unchanged. The endpoints are exact and
  // the fade is smooth. No single program can avoid it: the bottom row can only be
  // dimmed through its colour, a row above it can only reveal what is beneath
  // through its alpha, and a shader cannot know which of the two it is.
  if (stops) {
    // A lookup table already carries the brightness in its colour, since that is
    // what a lookup table is, so the brightness needs no saying here -- only the
    // dimming and the coverage.
    return source + "void main() { float v = normalized();"
      + ` emitRGBA(vec4(zmartLut(v) * opacity, ${covered})); }`;
  }
  // White is the honest default for a single channel with no colour of its own:
  // there is nothing to distinguish it from, so a colour would be an invention.
  const [r, g, b] = color || [1, 1, 1];
  return source + "void main() { float v = normalized();"
    + ` emitRGBA(vec4(vec3(${r}, ${g}, ${b}) * v * opacity, ${covered})); }`;
}

// The values for the controls declared above. These reach the graphics card
// without the program being touched, which is why contrast is smooth to drag.
export function shaderControlsFor(window_, volumetric, opacity, attenuation = 0) {
  if (!window_) return undefined;
  const controls = { normalized: { range: [window_.low, window_.high] } };
  // Sent in both views. In the volume it is the alpha the ray accumulates; in the
  // flat view it dims the colour, which is the only way to fade the bottom-most
  // row -- see the note in `shaderFor`. Sent as a control rather than written into
  // the program, so that dragging the slider does not recompile a shader per layer
  // on every step, exactly as the contrast window is.
  controls.opacity = opacity;
  if (volumetric) controls.attenuation = attenuation;
  return controls;
}

// How one channel is recognised again after something has been opened or closed.
// The acquisition type and the channel name together, because that pair is what
// stays the same across such a change: a row's position in the list moves as soon
// as anything is added or removed, so a number would quietly come to mean a
// different channel. This is the key the panel carries colour and contrast across
// on, and it never leaves the page.
export function layerKey(spec) {
  return `${spec.group}/${spec.name}`;
}

// What the engine is told to call a layer. The engine keeps one flat list and
// requires the names in it to be unique, while the panel shows them gathered under
// their acquisition type. Two types can easily hold a channel of the same name --
// both an overview and a target scan have a "marker-a" -- so the name handed over
// carries the type with it. The panel still shows the short name on screen; this is
// only what the engine hears.
export function engineName(spec) {
  return spec.group ? `${spec.group} · ${spec.name}` : spec.name;
}

/**
 * Turn the panel's state into the layer list the engine should draw.
 *
 * Two things are decided here. The **order** follows the panel, because the
 * engine composites in list order and so the order is what decides which
 * acquisition type sits on top of which. And **visibility** needs both the
 * group and the channel: hiding a group hides its channels without forgetting
 * which of them were individually switched off. Opacity is the channel's own,
 * from the slider in its display settings -- the per-acquisition opacity that
 * used to multiply in here was removed with its slider (2026-08-18): two
 * opacities acting on one channel read as a control that does nothing.
 */
/**
 * The brightness window a layer rests at before the operator touches anything.
 *
 * The run's own recorded window comes first: that is what the microscopist
 * asked for, and it stays authoritative. Where the run recorded nothing, the
 * window measured from the pixels (the same one the Auto button applies) is
 * used instead of the camera's whole range -- a real specimen sits in the
 * bottom few per cent of that range, so the whole range showed a picture that
 * was very nearly black until somebody pressed Auto. Watched on every replay
 * before this fallback existed. Both the canvas and the panel's sliders read
 * the window through here, so they can never disagree about where a fresh
 * layer starts.
 */
export function restingWindow(spec, volumetric) {
  const asked = volumetric ? spec.volumeWindow || spec.window : spec.window;
  return asked || spec.histogram?.autoWindow || null;
}

export function layersFor(config, mode, layerState, groupState, groupOrder,
                          volumeMode = "max", volume = {}) {
  const volumetric = mode === "volume";
  const rows = config.layers.map((spec, index) => ({ spec, index }));
  const ordered = groupOrder.flatMap((group) =>
    rows.filter(({ spec }) => (spec.group || "") === group),
  );
  // Anything whose group is somehow not in the order still gets drawn: a layer
  // silently missing is far worse than one in an unexpected place.
  const seen = new Set(ordered.map(({ index }) => index));
  const all = [...ordered, ...rows.filter(({ index }) => !seen.has(index))];

  return all.map(({ spec, index }) => {
    const { visible, color, opacity, lut, window: windowOverride } = layerState[index];
    const group = groupState[spec.group || ""] || { visible: true };
    const displayWindow = windowOverride || restingWindow(spec, volumetric);
    // A segmentation mask is drawn by a different kind of layer: the engine gives
    // every object its own colour and lets one be picked out, which is what a mask
    // is for. Brightness and contrast mean nothing on an identity number, so none
    // of that is sent.
    const isMask = spec.kind === "segmentation";
    const layer = {
      type: isMask ? "segmentation" : "image",
      name: engineName(spec),
      // A row may be drawn from several stores -- several positions of the same
      // acquisition type. The engine takes the list and places each one using the
      // stage position recorded inside it.
      source: (spec.sources || [spec.source]).map(
        (source) => `${window.location.origin}${source}`,
      ),
      // How many frames the server has counted on disk for each store above, in the
      // same order. It is carried through to the engine for one narrow purpose: it
      // is what says which stores have actually grown since the last look, and
      // re-reading a store is only worth doing when it has. A row with no time axis
      // leaves this undefined and is never re-read at all.
      //
      // Per store rather than for the row as a whole, and that distinction is the
      // whole point. A row's own frame count is the highest across its positions, so
      // one position advancing moves it and says nothing about which one moved --
      // which left the engine going back to every store on the row to ask. See
      // syncSources in engine.js, and NEXT_STEPS.md for what that cost.
      frameCounts: spec.frameCounts ?? undefined,
      // Manifest-driven sources keep a stable address.  Their separately carried
      // identities and committed revisions tell engine.js exactly which existing
      // source must be refreshed after a publication, without making the address
      // itself look like a new image.
      sourceIds: spec.sourceIds ?? undefined,
      sourceRevisions: spec.sourceRevisions ?? undefined,
    };
    // Where a store holds its channels inside one array, this is what picks the
    // channel: the engine exposes it as a per-layer dimension, and each row pins
    // it to its own index. Nothing splits the data; one store feeds every row.
    if (Array.isArray(spec.localPosition)) layer.localPosition = spec.localPosition;
    else if (spec.channelIndex != null) layer.localPosition = [spec.channelIndex];
    layer.visible = visible && group.visible;
    if (isMask) {
      layer.selectedAlpha = opacity;
      layer.notSelectedAlpha = opacity;
      return layer;
    }
    layer.shader = shaderFor(color, volumetric, lut);
    const controls = shaderControlsFor(displayWindow, volumetric, opacity,
                                       volume.attenuation ?? 0);
    if (controls) layer.shaderControls = controls;
    if (volumetric) {
      // Which way the ray is turned into a colour, and it is not a detail.
      // "on" accumulates every voxel it passes, which on sparse specimen
      // gives a milky picture -- measured on 6 August 2026 over a run of a
      // thousand positions, a spread of 8 grey levels against 41 for "max".
      // "max" keeps the brightest voxel along each ray, which is what a
      // microscopist means by a projection and what napari calls mip; it
      // needs no transparency tuned before anything can be seen. "min" is
      // the same for dark objects on a bright field.
      layer.volumeRendering = volumeMode;
      // This, not the zoom, chooses which copy of the image the volume is drawn from.
      // How many steps a ray takes through the volume, and the number that
      // decides how sharp it is allowed to be: the engine will only draw from a
      // level whose voxels are bigger than one step, so a small budget pins a
      // large specimen to its coarsest copy however far you zoom in. Measured on
      // a 75 GB skin volume: 256 stays at 27.2 um until absurdly close, 2048
      // reaches full resolution once zoomed in, and 32768 would refine from the
      // opening view but is too slow to drive. Which of those is right depends
      // on the specimen and the machine, which is why it is a control rather
      // than a constant -- the flag it falls back to is only the starting point.
      layer.volumeRenderingDepthSamples = volume.depthSamples ?? config.depthSamples;
      // Brightness for the accumulated mode, which the engine has had all
      // along and this viewer never set. Accumulation piles alpha up along
      // the ray and washes out; this is the knob built to answer that. The
      // engine raises it to a power, so nought is unchanged.
      layer.volumeRenderingGain = volume.gain ?? 0;
    } else {
      // The same number the shader was just given, and deliberately not instead
      // of it. This one is the alpha the engine blends a row with, which is what
      // lets a row above another fade and reveal it; the shader's copy dims the
      // colour, which is the only thing that reaches the bottom-most row's
      // drawing. Two carriers because they are read in two different places by
      // two different regimes -- see the note in `shaderFor`.
      layer.opacity = opacity;
    }
    return layer;
  });
}
