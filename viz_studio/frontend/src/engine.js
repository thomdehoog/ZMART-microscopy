/**
 * Keeping the engine's picture in step with the panel, without rebuilding it.
 *
 * The panel and the engine hold the same information in two different shapes.
 * The panel thinks in acquisition types and channels; the engine thinks in a flat
 * list of layers. Something has to carry changes from one to the other, and this
 * is that something.
 *
 * The obvious way to do it is to hand Neuroglancer a fresh description of the
 * whole scene every time anything changes, and let it sort out the difference.
 * Neuroglancer offers exactly that call, and we used it. It turns out not to work
 * the way the name suggests: `restoreState` does not compare the new description
 * against the old one. It throws every existing layer away and builds the lot
 * again from scratch. So nudging one contrast slider was quietly demolishing and
 * rebuilding every layer on screen.
 *
 * Three things go wrong when that happens, and they get worse as the data gets
 * bigger:
 *
 * 1. Anything the operator drew is lost. A drawn target lives inside its layer,
 *    and the rebuilt layer is a new, empty one — so the target disappears from the
 *    image while the list beside it still claims the target is there.
 * 2. The pieces of image already fetched are dropped and asked for again. They
 *    are kept in a shared cache that survives for a moment after the last layer
 *    lets go of them, so a fast enough rebuild often catches them still warm and
 *    nothing is refetched. That is luck, not design, and on a run of several
 *    hundred gigabytes — where a rebuild can easily land while pieces are still
 *    in flight — it is luck that runs out.
 * 3. Everything the engine had worked out about the scene has to be worked out
 *    again: which pyramid level to draw, how the layers line up in space, which
 *    shader programs to compile. None of it changed.
 *
 * So this module does the comparing itself. It looks at what the engine currently
 * has, works out the smallest set of changes that would turn it into what the
 * panel is asking for, and makes only those. A layer is built only when it is
 * genuinely new, and thrown away only when it has genuinely gone. Everything else
 * — brightness, colour, opacity, whether a channel is showing, what order the
 * acquisition types are drawn in — is written straight onto the layer that is
 * already there, which is what Neuroglancer expects and is fast enough to do on
 * every drag of a slider.
 */

import { makeLayer, deleteLayer } from "neuroglancer/unstable/layer/index.js";

// The addresses each layer was last given. Kept here rather than read back out of
// the engine because Neuroglancer tidies up the addresses it is handed, so what
// comes back out is not always character-for-character what went in — and a
// comparison that got that wrong would add the same image over and over. A
// WeakMap is used so that a layer being thrown away takes its entry with it.
const sourcesApplied = new WeakMap();

function sourceList(spec) {
  if (spec.source == null) return [];
  return Array.isArray(spec.source) ? spec.source : [spec.source];
}

/**
 * Give one layer any images it does not yet have.
 *
 * A row in the panel can be drawn from several stores at once — the same channel
 * of the same acquisition type, recorded at a dozen stage positions — and during a
 * run those positions appear one at a time. Adding the new one to the layer that
 * is already there costs nothing; rebuilding the layer would throw away the
 * eleven positions that were fine.
 *
 * Only additions are made. A position is never removed on its own: closing things
 * is done a whole acquisition type at a time, which removes the layer outright, so
 * there is no case where a layer should quietly lose one of its images.
 *
 * Returns how many images were added, so the caller knows whether the shape of
 * the scene changed.
 */
function syncSources(layer, spec) {
  const wanted = sourceList(spec);
  // Held as a set rather than a list. A row can be drawn from as many stores as
  // the run has positions, and asking a list "do you already contain this?" for
  // each of them means walking the whole list every time -- which for a few
  // thousand positions is most of a second, spent on every single step of a
  // contrast drag, on the same thread the engine draws with.
  const already = sourcesApplied.get(layer) || new Set();
  const fresh = wanted.filter((url) => !already.has(url));
  for (const url of fresh) {
    // Neuroglancer's own reader turns the address into whatever it needs, so the
    // format the panel writes and the format the engine wants cannot drift apart.
    // It is handed a list of one rather than a bare address on purpose: that is
    // the same path a layer takes when it is first built, so an image added later
    // is set up in exactly the same way as one that was there from the start.
    for (const source of layer.getDataSourceSpecifications({ source: [url] })) {
      layer.addDataSource(source);
    }
  }
  if (fresh.length) sourcesApplied.set(layer, new Set(wanted));
  return fresh.length;
}

/**
 * Write the adjustable settings of one layer.
 *
 * These are the things the operator changes constantly — contrast, colour,
 * opacity, whether a channel is showing — so this runs very often and does as
 * little as possible. Each setting is a value the engine watches, and writing the
 * value it already holds is ignored, so setting all of them and letting the engine
 * notice which actually moved is both correct and cheap.
 */
function applySettings(managed, spec) {
  const visible = spec.visible !== false;
  if (managed.visible !== visible) managed.setVisible(visible);
  const layer = managed.layer;
  if (!layer) return;
  if (spec.type === "image") {
    // The shader is the small program that turns stored numbers into what you
    // see: it carries the channel colour and any colour map. Setting it to the
    // text it already holds is ignored by the engine, so this is free whenever
    // the colour has not changed -- which is nearly always.
    if (spec.shader != null) layer.fragmentMain.value = spec.shader;
    // The contrast window and the 3-D opacity travel separately, as values for
    // controls the program declares. Sent this way they reach a program that is
    // already compiled, so dragging a contrast handle costs the graphics card
    // almost nothing however many layers are open.
    if (spec.shaderControls) layer.shaderControlState.restoreState(spec.shaderControls);
    if (spec.opacity != null) layer.opacity.value = spec.opacity;
    layer.volumeRenderingMode.restoreState(spec.volumeRendering ?? "off");
    if (spec.volumeRenderingDepthSamples != null) {
      layer.volumeRenderingDepthSamplesTarget.value = spec.volumeRenderingDepthSamples;
    }
  } else if (spec.type === "segmentation") {
    // A mask has no brightness to adjust; how strongly it is painted over the
    // image is the only thing there is to set.
    layer.displayState.selectedAlpha.value = spec.selectedAlpha ?? 1;
    layer.displayState.notSelectedAlpha.value = spec.notSelectedAlpha ?? 0;
  } else if (spec.type === "annotation" && spec.annotationColor) {
    layer.annotationDisplayState.color.restoreState(spec.annotationColor);
  }
  // Note what is deliberately absent: for an annotation layer, the annotations
  // themselves. Once the layer exists, the drawings inside it belong to the
  // engine, and the panel's list is a reflection of them rather than the other way
  // round. Writing them back here is what used to erase whatever had just been
  // drawn.
}

/**
 * Put the layers in the order the panel shows them.
 *
 * This is a real setting rather than tidying: the engine paints the list from
 * bottom to top, so the order decides which acquisition type covers which.
 */
function applyOrder(manager, names) {
  // Where each layer currently sits, looked up once. Searching the list for every
  // name instead costs the square of the number of layers, which at a few thousand
  // is tens of milliseconds -- again on every step of a slider drag.
  const at = new Map(manager.managedLayers.map((managed, index) => [managed.name, index]));
  names.forEach((name, wanted) => {
    const here = at.get(name);
    if (here === undefined || here === wanted) return;
    manager.reorderManagedLayer(here, wanted);
    // Moving one layer shifts the others, so the map is rebuilt rather than
    // trusted. This happens only when the order has genuinely changed.
    manager.managedLayers.forEach((managed, index) => at.set(managed.name, index));
  });
}

/**
 * Bring the engine's layers into line with what the panel is asking for.
 *
 * ``specs`` is the scene the panel wants, in the order it should be drawn, each
 * entry written the way Neuroglancer describes a layer.
 *
 * Returns how many layers were built, removed or given a new image — in other
 * words, how much of the scene actually changed shape. That number matters
 * because it is the only case where the engine has to work out where everything
 * sits in space again, so the interface uses it to decide whether the view needs
 * putting back where the operator had it. It is also what the browser tests
 * watch: for an ordinary change — a slider moved, a channel hidden — it must be
 * zero.
 */
export function syncLayers(viewer, specs) {
  const manager = viewer.layerManager;
  const wanted = new Set(specs.map((spec) => spec.name));
  let reshaped = 0;

  // Anything the panel no longer lists has genuinely been closed, so let it go.
  // Doing this first also frees the name, in case something new is taking it.
  for (const managed of [...manager.managedLayers]) {
    if (wanted.has(managed.name)) continue;
    deleteLayer(managed);
    reshaped += 1;
  }

  specs.forEach((spec, index) => {
    let managed = manager.getLayerByName(spec.name);
    // A layer that has changed kind — an image where there was a mask — cannot be
    // adjusted into the other; that one really does have to be built again.
    if (managed && managed.layer?.type !== spec.type) {
      deleteLayer(managed);
      managed = undefined;
      reshaped += 1;
    }
    if (managed) {
      reshaped += syncSources(managed.layer, spec);
      applySettings(managed, spec);
      return;
    }
    managed = makeLayer(viewer.layerSpecification, spec.name, spec);
    // Building from the description already applied everything in it, including
    // the images; record them so the next pass does not add them a second time.
    sourcesApplied.set(managed.layer, new Set(sourceList(spec)));
    viewer.layerSpecification.add(managed, index);
    reshaped += 1;
  });

  applyOrder(manager, specs.map((spec) => spec.name));
  return reshaped;
}

/**
 * Wait for the images to say how big they are, then let the engine choose the
 * starting magnification again.
 *
 * Without this the viewer opens on an empty grey rectangle, with the data
 * present and correct but drawn far too small to see. It is worth explaining
 * why, because the cause is nowhere near the symptom.
 *
 * The engine picks a starting magnification the first moment it believes it
 * knows what space the picture lives in. It expresses that magnification in
 * physical units — so many micrometres to a screen pixel — and it is careful
 * afterwards: if the size of a voxel changes, it adjusts the number so that what
 * is on screen stays the same real size. That is the right thing to do, and it
 * is exactly what hurts us here.
 *
 * The trouble is timing. We hand the engine its layers immediately, while the
 * images themselves are still being read over the network. For a moment there
 * are layers but no axes yet, and in that moment the engine considers the space
 * settled — an empty space, in which it has no voxel size to work from and falls
 * back to treating one voxel as one metre. It picks its ordinary default of one
 * voxel to a pixel, which now means *one metre* to a pixel. A little later the
 * real axes arrive saying a voxel is a third of a micrometre, and the engine
 * dutifully preserves the physical scale it was given. A specimen a tenth of a
 * millimetre across is then drawn about a ten-thousandth of a pixel wide, which
 * is to say invisibly, and the panel shows nothing but its own background.
 *
 * So we wait for the axes to actually arrive and then clear the magnification,
 * which makes the engine choose it once more — this time knowing how big a voxel
 * really is. This happens once, before anything is on screen, so it cannot
 * disturb an operator who has started looking around. Afterwards the engine's
 * careful adjustment is left alone, because from then on it is working from real
 * sizes and is right.
 *
 * Returns a function that stops the waiting, for the caller to use when the
 * viewer goes away.
 */
export function chooseScaleWhenTheImagesAreMeasured(viewer) {
  const { position } = viewer.navigationState;
  // Axes, not images: a space with no axes is the placeholder described above.
  // The moment it has any, the engine knows how big a voxel is.
  const measured = () => (position.coordinateSpace.value?.rank ?? 0) > 0;
  let stop = () => {};
  const check = () => {
    if (!measured()) return;
    // Clearing rather than setting a number of our own on purpose: the engine's
    // own default is a sensible starting point, and it is the one an operator
    // who has used neuroglancer elsewhere will expect. All that was ever wrong
    // with it was when it got decided.
    viewer.navigationState.zoomFactor.reset();
    viewer.perspectiveNavigationState.zoomFactor.reset();
    stop();
    stop = () => {};
  };
  stop = position.coordinateSpace.changed.add(check);
  // In case the axes are already known by the time we are asked -- reopening a
  // folder, say, where the descriptions are still in hand.
  check();
  return () => stop();
}

/**
 * Set the parts of the view that are not layers: which panels are on screen, and
 * whether the engine draws its own furniture.
 *
 * Rebuilding the panel layout means new drawing surfaces, so it is done only when
 * the operator has actually switched between the flat view and the volume — never
 * as a side effect of some unrelated change.
 */
export function syncView(viewer, { layout, chrome }) {
  if (viewer.layout.toJSON() !== layout) viewer.layout.restoreState(layout);
  viewer.showDefaultAnnotations.value = chrome;
  viewer.showAxisLines.value = chrome;
  // Neuroglancer's own scale bars are off. It draws one per axis along the bottom
  // left, including one for time -- which looks like a distance and is not one. A
  // single bar for distance is drawn in the corner of the image instead, and it is
  // ours so it can be put somewhere out of the way. See ScaleBar.jsx.
  viewer.showScaleBar.value = false;
  // Black behind the slice, rather than the engine's mid-grey.
  //
  // Fluorescence images are mostly dark, and a grey surround sitting right up
  // against a dark specimen makes the specimen look brighter than it is -- the
  // eye judges brightness by comparison, so the same image reads differently
  // depending on what is next to it. Black is also simply what a microscopist
  // expects to see around an image.
  //
  // Worth knowing if you are debugging: this grey used to be the only clue that
  // nothing was being drawn at all, since an empty panel showed the engine's
  // background and a drawn one did not. That clue is no longer needed, because a
  // test now looks at the picture and fails if it is a flat colour -- see
  // tests/pixels.py. It is the test that makes this line safe to have.
  //
  // Written through `restoreState` rather than assigned: it parses the colour and
  // only writes when it differs from what is already there, and this function
  // runs on every change to the view.
  viewer.crossSectionBackgroundColor.restoreState("#000000");
}
