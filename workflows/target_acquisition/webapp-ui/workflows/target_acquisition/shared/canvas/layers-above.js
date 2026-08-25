/**
 * The layers the operator's own drawing is made of, above the picture.
 *
 * The picture at the bottom is always solid. It is never faded and no window is
 * ever cut through it, because the engine that will eventually draw it —
 * neuroglancer — cannot be made see-through, and because there is nothing
 * underneath it for transparency to reveal anyway. `viz_studio/LAYERS.md` sets
 * that out in full.
 *
 * So everything that decides what shows through lives here, in the drawing
 * above. This file takes a stack of layers and turns it into the single paint
 * function the canvas hands to the engine's top slot.
 *
 * ## The three ways a layer can be made see-through
 *
 * **Its own fade.** Each layer carries an `opacity`, its own and nobody else's.
 * A carrier outline you want faintly present and a set of positions you want
 * solid are two different numbers, and neither should have to move when the
 * other does.
 *
 * **The shared dial.** One control fades everything at once. This is the thing
 * an operator reaches for while working — "let me see the picture" — and it is
 * a single movement rather than a visit to every layer in turn. It only ever
 * makes things fainter: a layer already set faint does not become solid because
 * the dial is turned up.
 *
 * **A window over chosen ground.** A list of rectangles, in micrometres on the
 * sample, where the drawing above is made see-through so the picture shows
 * through. This is how "let me see these particular fields" is said. It is in
 * micrometres rather than screen pixels for the same reason everything else
 * here is: it describes a piece of specimen, so it travels with the specimen
 * when the view is panned and grows when the view is magnified.
 *
 * ## What a window cuts through, and what it does not
 *
 * A window takes away everything drawn *before* it. That is deliberate and it
 * is the answer to a question that comes up immediately: if one layer is made
 * see-through, should the ones below it go too? Here they do, because otherwise
 * a window would reveal the next drawing down rather than the picture, and
 * revealing the picture is the entire purpose.
 *
 * A layer that should survive that says `staysSolid: true`. It is drawn after
 * the windows are cut and the dial does not touch it. Focus points are the
 * example worth having in mind: they mark where the microscope will focus, they
 * have to be readable whatever else is going on, and an operator fading the
 * plan to see the picture underneath does not mean they wanted to lose the
 * focus points too.
 *
 * ## The layers are things an operator works with, not decoration
 *
 * A layer can be touched. Positions are clicked to open the field they stand
 * for, a target is picked to look at it, a region is drawn by hand. So besides
 * drawing itself, a layer may say what of it is at a given place on the sample
 * — see {@link whoIsAt} — and the canvas asks the layers from the top down, so
 * that the thing an operator can see is the thing their click reaches.
 *
 * Dragging is a separate matter and already has an answer: the canvas can lend
 * a drag out with `handDragsTo`, which is what drawing a region by hand uses.
 * See `viz_studio/options/gestures.js`.
 *
 * ## Where the layers come from
 *
 * The canvas does not invent them. Each step of the workflow says what belongs
 * above the picture while that step is standing — the carrier at one step, the
 * positions at another, the cells that were found at a third — and hands the
 * list in. The canvas is never told which step it is in; it is told what to
 * draw. That is what keeps it movable from one workflow to the next.
 */

/**
 * Turn a stack of layers into one drawing to hand to the canvas's top slot.
 *
 * @param layers bottom of the stack first. Each is `{ paint, shown, opacity,
 *   staysSolid }`, where `paint(frame)` draws in exactly the way every canvas
 *   drawing does — one frame holding the view, the box, a drawing context and a
 *   way of turning micrometres into screen pixels, as
 *   `viz_studio/options/contract.md` sets out. `shown` defaults to true,
 *   `opacity` to 1, and `staysSolid` to false. A layer with no `paint` is
 *   skipped, so a step can leave a slot in the stack empty without the list
 *   having to change shape.
 * @param dial how much of the whole stack to keep, 0 to 1. Layers that stay
 *   solid ignore it.
 * @param seeThrough rectangles on the sample, in micrometres, where the drawing
 *   is made see-through: `{ x, y, w, h, letThrough }`. `letThrough` is how much
 *   of the picture to reveal, 0 (nothing) to 1 (all of it), and defaults to
 *   fully see-through.
 * @returns a paint function, or `null` if there is nothing at all to draw —
 *   which lets the canvas tell "this stack is empty" apart from "this stack
 *   drew nothing today", a distinction the engines care about.
 */
export function theDrawingAbove(layers = [], { dial = 1, seeThrough = [] } = {}) {
  const drawable = layers.filter((layer) => layer && typeof layer.paint === "function");
  if (!drawable.length) return null;

  return (frame) => {
    const fade = clamped(dial);

    for (const layer of drawable) {
      if (layer.shown === false || layer.staysSolid) continue;
      paintOneLayer(frame, layer, clamped(layer.opacity ?? 1) * fade);
    }

    cutTheWindows(frame, seeThrough);

    for (const layer of drawable) {
      if (layer.shown === false || !layer.staysSolid) continue;
      paintOneLayer(frame, layer, clamped(layer.opacity ?? 1));
    }
  };
}

const clamped = (value) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 1));

/**
 * Draw one layer at the strength it has ended up with.
 *
 * Wrapped in save and restore so that a layer which changes the drawing state —
 * a colour, a line width, a clip — cannot leak that into the layer above it.
 * These drawings come from the workflow rather than from here, so this file
 * cannot assume they tidy up after themselves, and one that does not would
 * otherwise show as a fault in a completely different layer.
 */
function paintOneLayer(frame, layer, strength) {
  if (strength <= 0) return;
  const { context } = frame;
  context.save();
  context.globalAlpha = strength;
  layer.paint(frame);
  context.restore();
}

/**
 * Take away what has been drawn, over the ground the windows name.
 *
 * `destination-out` is the browser's way of saying "remove what is already
 * here", and removing it is what lets the picture below show through. Cutting
 * rather than drawing something pale over the top matters: a pale rectangle
 * would still be a rectangle, sitting between the operator and the picture and
 * changing its colour. A window leaves nothing at all behind.
 */
function cutTheWindows(frame, windows) {
  if (!windows?.length) return;
  const { context, project, zoom } = frame;
  context.save();
  context.globalCompositeOperation = "destination-out";
  for (const window of windows) {
    const letThrough = clamped(window.letThrough ?? 1);
    if (letThrough <= 0) continue;
    const at = project(window.x, window.y);
    context.globalAlpha = letThrough;
    context.fillStyle = "#000";
    context.fillRect(at.x, at.y, window.w / zoom, window.h / zoom);
  }
  context.restore();
}


/**
 * What the operator just touched, asked of the layers from the top down.
 *
 * Every layer draws in micrometres on the sample, so a click is turned into
 * micrometres once, here, and each layer is asked the same question about the
 * same place. A layer answers with whatever it wants handed back — the position
 * that was clicked, the target that was picked — or with nothing, meaning the
 * click went past it.
 *
 * **Top down, and the first answer wins.** That is the order an operator
 * expects and the only one that is not surprising: what you can see is what you
 * hit. A target drawn over a position belongs to the target when you click it,
 * because the target is what is under the pointer.
 *
 * A layer that is switched off is not asked. Something invisible that still
 * catches clicks is among the more baffling things a page can do — the operator
 * clicks what they can see and something else answers.
 *
 * @param layers the same stack {@link theDrawingAbove} is given, bottom first.
 * @param at where the click landed on the sample, in micrometres.
 * @returns `{ layer, what }` for the topmost layer that claimed it, or `null`.
 */
export function whoIsAt(layers = [], at) {
  if (!at) return null;
  for (let index = layers.length - 1; index >= 0; index -= 1) {
    const layer = layers[index];
    if (!layer || layer.shown === false || typeof layer.reaches !== "function") continue;
    const what = layer.reaches(at);
    if (what !== null && what !== undefined && what !== false) return { layer, what };
  }
  return null;
}
