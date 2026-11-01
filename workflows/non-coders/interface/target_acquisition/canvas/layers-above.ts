/**
 * The layers the operator's own drawing is made of, above the picture.
 *
 * This turns drawing layers into one paint function for a canvas slot. It
 * controls how solid the drawing is, not what of the run's picture is covered:
 * the picture is its own layer in the canvas's middle slot.
 *
 * ## The two ways a layer can be made fainter
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
 * A layer that should not fade says `staysSolid: true`: it is drawn after the
 * others and the dial does not touch it. Focus points are the example worth
 * having in mind: they mark where the microscope will focus, and an operator
 * fading the plan to see the picture underneath does not mean they wanted to
 * lose the focus points too.
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
 * See `engines/gestures.ts`.
 *
 * ## Where the layers come from
 *
 * The canvas does not invent them. Each step of the workflow says what belongs
 * above the picture while that step is standing — the carrier at one step, the
 * positions at another, the cells that were found at a third — and hands the
 * list in. The canvas is never told which step it is in; it is told what to
 * draw. That is what keeps it movable from one workflow to the next.
 */

import type { Drag } from "./engines/gestures.ts";
import type { Frame, Paint } from "./surface.ts";

/** A layer over the picture: how it draws, whether and how solidly it is shown, and what of it is under a press or a drag. */
export interface Layer {
  key?: string;
  label?: string;
  /** One sentence, shown when the pointer rests on its button. */
  explains?: string;
  /** Whether the run has anything for it; one with nothing gets no button. */
  has?: boolean;
  /** The key of the layer it is chrome for; it is shown with it. */
  follows?: string;
  paint?: Paint | null;
  shown?: boolean;
  opacity?: number;
  staysSolid?: boolean;
  reaches?: (at: { x: number; y: number }) => unknown;
  claims?: (drag: Drag) => boolean | void;
  [more: string]: unknown;
}

/**
 * Turn a stack of layers into one drawing to hand to the canvas's top slot.
 *
 * @param layers bottom of the stack first. Each is `{ paint, shown, opacity,
 *   staysSolid }`, where `paint(frame)` draws in exactly the way every canvas
 *   drawing does — one frame holding the view, the box, a drawing context and a
 *   way of turning micrometres into screen pixels, as
 *   `docs/viewer-slot.md` sets out. `shown` defaults to true,
 *   `opacity` to 1, and `staysSolid` to false. A layer with no `paint` is
 *   skipped, so a step can leave a slot in the stack empty without the list
 *   having to change shape.
 * @param dial how much of the whole stack to keep, 0 to 1. Layers that stay
 *   solid ignore it.
 * @returns a paint function, or `null` if there is nothing at all to draw —
 *   which lets the canvas tell "this stack is empty" apart from "this stack
 *   drew nothing today", a distinction the engines care about.
 */
export function theDrawingAbove(
  layers: (Layer | null | undefined)[] = [], { dial = 1 } = {},
): Paint | null {
  const drawable = layers.filter((layer): layer is Layer & { paint: Paint } => !!layer && typeof layer.paint === "function");
  if (!drawable.length) return null;

  return (frame) => {
    const fade = clamped(dial);

    for (const layer of drawable) {
      if (layer.shown === false || layer.staysSolid) continue;
      paintOneLayer(frame, layer, clamped(layer.opacity ?? 1) * fade);
    }

    /* All the way down means the picture alone: a mark that never fades
       still steps aside when the operator asks for maximum transparency. */
    if (fade === 0) return;
    for (const layer of drawable) {
      if (layer.shown === false || !layer.staysSolid) continue;
      paintOneLayer(frame, layer, clamped(layer.opacity ?? 1));
    }
  };
}

const clamped = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 1));

/**
 * Draw one layer at the strength it has ended up with.
 *
 * Wrapped in save and restore so that a layer which changes the drawing state —
 * a colour, a line width, a clip — cannot leak that into the layer above it.
 * These drawings come from the workflow rather than from here, so this file
 * cannot assume they tidy up after themselves, and one that does not would
 * otherwise show as a fault in a completely different layer.
 */
function paintOneLayer(frame: Frame, layer: Layer & { paint: Paint }, strength: number): void {
  if (strength <= 0) return;
  const { context } = frame;
  context.save();
  context.globalAlpha = strength;
  layer.paint(frame);
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
export function whoIsAt(
  layers: (Layer | null | undefined)[] = [], at: { x: number; y: number } | null | undefined,
): { layer: Layer; what: unknown } | null {
  if (!at) return null;
  for (let index = layers.length - 1; index >= 0; index -= 1) {
    const layer = layers[index];
    if (!layer || layer.shown === false || typeof layer.reaches !== "function") continue;
    const what = layer.reaches(at);
    if (what !== null && what !== undefined && what !== false) return { layer, what };
  }
  return null;
}

/**
 * Which layer wants this drag, if any.
 *
 * The same question `whoIsAt` asks about a point, asked about a gesture, and
 * answered the same way: from the top of the stack down, so the layer the
 * operator can see wins. The difference is what a claim is for. A click is
 * over the moment it happens; a drag is a press, then the moves, then the
 * release, and a layer drawing a shape needs all three or it has none of them.
 *
 * Every candidate is *asked* — it is handed the opening of the drag and says
 * whether it is theirs — because only the layer knows whether the press landed
 * on anything of its own. Returning `false` declines; anything else takes it.
 *
 * @param layers the stack, bottom first.
 * @param drag the opening of the gesture, `{ phase: "started", at, screen }`.
 * @returns the layer that took it, or `null` if none did and it should pan.
 */
export function whoClaims(layers: (Layer | null | undefined)[] = [], drag: Drag | null | undefined): Layer | null {
  if (!drag) return null;
  for (let index = layers.length - 1; index >= 0; index -= 1) {
    const layer = layers[index];
    if (!layer || layer.shown === false || typeof layer.claims !== "function") continue;
    if (layer.claims(drag) !== false) return layer;
  }
  return null;
}
