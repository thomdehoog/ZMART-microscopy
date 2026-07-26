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
  const already = sourcesApplied.get(layer) || [];
  const fresh = wanted.filter((url) => !already.includes(url));
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
  if (fresh.length) sourcesApplied.set(layer, wanted);
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
  names.forEach((name, wanted) => {
    const here = manager.managedLayers.findIndex((managed) => managed.name === name);
    if (here >= 0 && here !== wanted) manager.reorderManagedLayer(here, wanted);
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
    sourcesApplied.set(managed.layer, sourceList(spec));
    viewer.layerSpecification.add(managed, index);
    reshaped += 1;
  });

  applyOrder(manager, specs.map((spec) => spec.name));
  return reshaped;
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
  viewer.showScaleBar.value = true;
}
