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
export function lutShader(stops, name = "zmartLut") {
  const literal = (c) => `vec3(${c.map((v) => v.toFixed(4)).join(",")})`;
  let body = `  vec3 c = ${literal(stops[0])};\n`;
  const step = 1.0 / (stops.length - 1);
  for (let i = 1; i < stops.length; i++) {
    const lo = ((i - 1) * step).toFixed(4);
    body += `  c = mix(c, ${literal(stops[i])}, clamp((v - ${lo}) / ${step.toFixed(4)}, 0.0, 1.0));\n`;
  }
  return `vec3 ${name}(float v) {\n${body}  return c;\n}\n`;
}

// A colour as the engine's own control expects it. The engine parses the same
// specifications a stylesheet does and keeps the value as a uniform, so this is
// simply how a colour is spelled on the way over.
export function hexColour(rgb) {
  if (!rgb) return "#ffffff";
  const part = (value) =>
    Math.round(Math.min(1, Math.max(0, value)) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${part(rgb[0])}${part(rgb[1])}${part(rgb[2])}`;
}


// Real acquisitions occupy a narrow band of the 16-bit range, so without an
// explicit window they render black. In 3-D the intensity drives opacity as
// well, or every background voxel along the ray adds haze and the specimen is
// lost in fog.
//
// **What is not written into the text below**: the window, the colour and the
// weight. Every one of them is declared as a control and sent as a number to a
// program the engine has already compiled, so choosing a colour or dragging a
// handle costs one number handed to the graphics card -- no rebuild, and
// nothing re-read from disk, since what has been downloaded is keyed by the
// store and the piece and knows nothing of how it is being shown. The colour
// used to be written into the text, which compiled a fresh program per colour
// and gave every channel a program of its own; the engine's own multichannel
// display has always used a control (`#uicontrol vec3 color`) and so does this.
//
// **Channels are separate layers, and that is the engine's arrangement rather
// than ours.** A brightness control can be bound to a named channel of the data
// -- but only where the data declares CHANNEL dimensions, and an OME-Zarr `c`
// axis arrives as a LOCAL dimension instead (measured 2026-08-20: the layer
// reports `c\'` local and a channel rank of nought, so `channel=[1]` will not
// even parse). A local dimension is pinned to one position per layer, so no
// single program can read two channels of it. This is exactly why neuroglancer
// splits a multichannel volume into one layer per channel too, and why the
// channels are added by the engine between layers rather than by a program
// within one.
export function shaderFor(volumetric, lut = null) {
  const stops = lut ? LOOKUP_TABLES[lut] : null;
  const declared = [
    "#uicontrol invlerp normalized",
    "#uicontrol float weight slider(min=0, max=1, default=1)",
    // The raw value, untouched by the window: mapped over a fixed nought-to-
    // one range without clamping, so ``imaged()`` simply answers the pixel's
    // own number. It exists for one question only — was anything written
    // here at all — which the window must have no say in.
    "#uicontrol invlerp imaged(range=[0, 1], clamp=false)",
  ];
  if (!stops) declared.push('#uicontrol vec3 color color(default="white")');
  if (volumetric) {
    declared.push("#uicontrol float attenuation slider(min=0, max=8, default=0)");
  }
  const lines = [...declared];
  if (stops) lines.push(lutShader(stops));
  lines.push("void main() {", "  float v = normalized();");
  // A colour map already carries the brightness in its colour, which is what a
  // colour map is; a flat colour has to be multiplied by it.
  lines.push(stops
    ? "  vec3 shown = zmartLut(v) * weight;"
    : "  vec3 shown = color * (v * weight);");
  if (volumetric) {
    // Fading the far side of the specimen away, which the engine does not offer
    // and napari calls an attenuated projection. `emitIntensity` is what decides
    // the contest in a projection -- the engine keeps whichever voxel along the
    // ray reports the largest value -- so the weight belongs in it as well, or a
    // channel turned down would still win the ray and then be drawn dim.
    lines.push(
      "  float faded = exp(-attenuation * depthAtRayPosition);",
      "  emitIntensity(v * weight * faded);",
      "  emitRGBA(vec4(shown * faded, v * weight * faded));",
      "}");
  } else {
    // Brightness rides in the colour and coverage rides in the transparency,
    // and they answer two different questions: how bright is this spot, and
    // was it imaged at all. A row that is ADDED to its neighbours needs the
    // second one only so that ground nobody imaged contributes nothing; a
    // row that COVERS needs it so an empty corner does not black out the
    // picture beneath.
    //
    // Coverage is read from the RAW value now, never from the windowed one.
    // For a day it was read from the window, and raising MIN above real but
    // dim ground punched a see-through hole in the picture where the
    // dimmest pixels lived — the operator watched it happen (2026-08-23,
    // closing the limit recorded 2026-08-11). The display does exactly what
    // a window means: below MIN clamps to black, above MAX to full, and
    // only a pixel holding nothing at all — a true zero, the fill of ground
    // never written — is not drawn.
    lines.push("  emitRGBA(vec4(shown, imaged() > 0.0 ? 1.0 : 0.0));", "}");
  }
  return `${lines.join("\n")}\n`;
}

// The values for the controls declared above. These reach the graphics card
// without the program being touched, which is why contrast is smooth to drag.
export function shaderControlsFor(window_, volumetric, weight, colour,
                                  lut = null, attenuation = 0) {
  if (!window_) return undefined;
  const controls = { normalized: { range: [window_.low, window_.high] } };
  // The weight is what an eye and an opacity slider both come to: nought hides
  // the channel, one shows it whole, and everything between fades it. Sent as a
  // number rather than as a switch on purpose -- the engine treats a checkbox as
  // part of a program's identity and would recompile on every glance, while a
  // number reaches the program already running.
  controls.weight = weight;
  // A channel painted through a colour map has no flat colour to send.
  if (!lut) controls.color = hexColour(colour);
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
      // syncSources in engine.js, and docs/open/NEXT_STEPS.md for what that cost.
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
    layer.shader = shaderFor(volumetric, lut);
    // A row that got here is a channel a microscope wrote as its own file, so
    // the engine has to add it to its neighbours from outside -- there is no
    // one program holding both. Adding is safe only while the row is fed by a
    // single store: the engine draws each store as its own pass, so a row
    // stitched from overlapping tiles would sum them into a bright seam along
    // every join, and such a row keeps the covering rule instead (and with it
    // the old fault, where only the topmost channel is seen). The cure is not
    // a cleverer rule here but the composed picture the server already builds,
    // whose channels live together and mix in one program.
    if ((spec.sources || [spec.source]).length === 1) {
      layer.blend = "additive";
    }
    const controls = shaderControlsFor(displayWindow, volumetric, opacity,
                                       color, lut, volume.attenuation ?? 0);
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
      // Which of the two places a weight is read from depends on how this row
      // meets the rows beneath it, and it must be read from exactly one of
      // them or a channel fades as its own setting SQUARED -- measured on this
      // viewer, a half reading a quarter.
      //
      // A row the engine ADDS contributes precisely the colour its program
      // emits, and the weight is already in that colour, so this stays at one.
      // A row that COVERS is the other case: there the engine reads this
      // number to let a faded row reveal what lies beneath it, which the
      // colour alone cannot do, and the old squared fade is the price. No one
      // program can avoid it while a single number has to both dim a row and
      // reveal what it is covering.
      layer.opacity = layer.blend === "additive" ? 1 : opacity;
    }
    return layer;
  });
}
