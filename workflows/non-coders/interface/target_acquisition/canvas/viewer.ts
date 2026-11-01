/**
 * The canvas, put inside the operator window as a panel of its own.
 *
 * This is the page's side of the canvas: the box the operator pans and zooms,
 * the workflow's layers drawn in it, a button for each layer, one fade for the
 * lot and a lock, and the routing of a press or a drag to whichever layer can
 * take it. The run's own picture is not drawn here: a workflow hands its
 * element in (`pictureHost`), it sits in the canvas's middle slot, and it
 * follows the view this reports (`onViewMoved`).
 *
 * ## What the canvas is never told
 *
 * The canvas is handed what to draw and, if the page wants them, functions to
 * answer a press with. It is not told which step it is in, which workflow it
 * belongs to, or what the operator has done so far. That is deliberate. A
 * picture that has learned the shape of one workflow cannot be moved into the
 * next one without being taken apart again. If wiring it into some future step
 * ever seems to want a piece of run state passed in, that is a sign the step
 * wants something the canvas does not yet offer, and the canvas is where the
 * answer belongs.
 *
 * ## Layers below the picture and above it
 *
 * A workflow hands in a stack of layers, bottom first. A layer keyed `picture`
 * marks where the run's picture goes: what comes before it is drawn beneath
 * the picture, what comes after it over the picture. A stack with no such
 * marker is drawn wholly over the picture.
 */

import { theDrawingAbove, whoClaims, whoIsAt, type Layer } from "./layers-above.ts";
import { openTheSurface, type Surface, type Where } from "./surface.ts";
import type { Drag, DragHandler } from "./engines/gestures.ts";
import type { View } from "./engines/opening-view.ts";

/** A place, in micrometres on the sample or in pixels in the box. */
interface XY {
  x: number;
  y: number;
}

/** A press a layer took: the layer, what of it was pressed, and where. */
export interface Touch {
  layer: Layer;
  what: unknown;
  at: XY;
  screen: XY;
}

/** A press nothing took: where it landed, on the sample and in the box. */
export type Press = XY & { at: XY; screen: XY };

/** The canvas, as the workflow drives it. */
export interface TheCanvas {
  readonly layers: Record<string, boolean | undefined>;
  fadeTo(howSolid: number): void;
  showLayer(key: string, on: boolean): void;
  layerShown(key: string): boolean;
  readonly gesturing: boolean;
  readonly locked: boolean;
  lock(on?: boolean): void;
  setLayersAbove(list?: Layer[]): void;
  readonly layersAbove: Layer[];
  readonly view: View | null;
  lookAt(where: { centre?: XY; zoom?: number } | null | undefined): void;
  project(x: number, y: number): XY;
  unproject(px: number, py: number): XY;
  whenShown(): Promise<Surface | null>;
}

declare global {
  interface Window {
    /** The canvas, for a browser test; nothing on the page reads it. */
    __theCanvas?: TheCanvas;
  }
}

/**
 * A drawing that draws nothing, for a layer that has been switched off.
 *
 * Handing a slot `null` says the application has nothing for it at all, and the
 * surface is then free to skip clearing it. That is right when the canvas has
 * only just been opened and its surfaces are still blank. It is not enough for
 * a layer switched off while somebody is watching: a surface cleared only on
 * its way to painting keeps the last drawing. Handing a drawing that paints
 * nothing clears it either way.
 */
const paintNothingAtAll = () => {};

/**
 * What a layer is, and what a workflow may say about one.
 *
 * ```js
 * { key, label, explains, paint, reaches, claims, shown, has, follows, opacity, staysSolid }
 * ```
 *
 * - `key` — its name in the buttons and in what a test reads back; `picture`
 *   marks where the run's picture goes in the stack.
 * - `label` — the word on its button.
 * - `explains` — one sentence, shown when the pointer rests on the button.
 * - `paint(frame)` — how it draws: in micrometres on the sample, so it pans and
 *   magnifies with the picture.
 * - `reaches(at)` — what of it is at a place on the sample, or nothing. This is
 *   what makes a layer something an operator can work with rather than look at.
 * - `claims(drag)` — whether it takes a drag (see `layers-above.ts`).
 * - `has` — whether the run has anything for it; a layer that has nothing gets
 *   no button.
 * - `follows` — the key of the layer it is chrome for; it is shown with it.
 * - `shown`, `opacity`, `staysSolid` — see `layers-above.ts`.
 */

/**
 * Put the canvas inside a box on the page and hand back the way to drive it.
 *
 * @param box the element the picture fills.
 * @param layers an element to fill with one button per layer, and the fade and
 *   the lock beside them.
 * @param readout a small element that says where the pointer, or the view, is.
 * @param layersAbove the workflow's layers, bottom of the stack first.
 * @param pictureHost the run's picture, put in the canvas's middle slot.
 * @param onTouched told what an operator clicked, when a layer claims the click.
 * @param handDragsTo offered a drag no layer claimed, before it pans.
 * @param onPressed a press that claimed nothing and did not travel.
 * @param readoutSays how the readout is phrased, for a host that measures in
 *   something other than what the layers are drawn in.
 * @param background what is behind the picture.
 * @param onViewMoved told whenever the view moves, with the view as it now is.
 *
 * @returns the handle the workflow drives the canvas with.
 */
export function putTheCanvasIn({
  box, layers, readout,
  layersAbove = [],
  pictureHost = null,
  onTouched = null,
  handDragsTo = null,
  onPressed = null,
  readoutSays = null,
  background = "#05070d",
  onViewMoved = null,
}: {
  box: HTMLElement;
  layers: HTMLElement;
  readout?: HTMLElement | null;
  layersAbove?: Layer[];
  pictureHost?: HTMLElement | null;
  onTouched?: ((touch: Touch) => void) | null;
  handDragsTo?: DragHandler | null;
  onPressed?: ((press: Press) => void) | null;
  readoutSays?: ((where: { at: XY; zoom: number }) => string) | null;
  background?: string;
  onViewMoved?: ((where: Where) => void) | null;
}): TheCanvas {
  const said: HTMLElement = readout ?? Object.assign(document.createElement("div"), { hidden: true });

  let viewer: Surface | null = null;      // the canvas's surface, once opened

  /* The layers, in drawing order, each carrying its own `shown`. Copied rather
     than used in place, because the canvas writes `shown` on them and a
     workflow's own list should not change under it. */
  let stackAbove: Layer[] = layersAbove.map((layer) => ({ shown: false, ...layer }));

  /* How much of the stack over the picture to keep, 0 to 1. One control for
     all of it, because "let me see the picture" is one thought. */
  let dial = 1;

  const buttons = new Map<string, HTMLButtonElement>();

  /* Which layers the operator has switched off, by key — kept apart from
     whether a layer has anything to draw, because they are two questions. */
  const turnedOff = new Set<string>();

  /* Where the view is, in micrometres on the stage. */
  function sayWhereTheViewIs(where: View | null | undefined) {
    if (!where) {
      said.textContent = "—";
      return;
    }
    said.textContent =
      `centre ${Math.round(where.centre.x)}, ${Math.round(where.centre.y)} µm` +
      ` · ${where.zoom.toFixed(2)} µm per pixel`;
  }

  /** Show each button in the state its layer is actually in. */
  function markTheButtons() {
    for (const [key, button] of buttons) {
      button.setAttribute("aria-pressed", String(isShowing(key)));
      button.disabled = !viewer;
    }
  }

  /**
   * Hand the two drawing slots what the stack says they should hold: the layers
   * before the `picture` marker beneath the picture, the rest over it with the
   * fade.
   *
   * @param openedJustNow true when the surfaces have only just been made, so
   *   there is nothing on them yet.
   */
  function handTheSlotsTheirDrawings(picture: Surface | null = viewer, { openedJustNow = false } = {}) {
    if (!picture) return;
    const nothingToDraw = openedJustNow ? null : paintNothingAtAll;
    const split = stackAbove.findIndex((layer) => layer.key === "picture");
    const below = split === -1 ? [] : stackAbove.slice(0, split);
    const above = split === -1 ? stackAbove : stackAbove.slice(split + 1);
    picture.drawUnder(theDrawingAbove(below) ?? nothingToDraw);
    picture.drawOver(theDrawingAbove(above, { dial }) ?? nothingToDraw);
  }

  /**
   * Turn a press that did not travel into a touch on whichever layer it reached.
   *
   * A press that *did* travel was a pan, and must not also count as a click. A
   * few pixels rather than none, because a hand on a trackpad is never quite
   * still.
   */
  const A_PRESS_THAT_DID_NOT_TRAVEL = 4;   // browser pixels
  let pressedAt: XY | null = null;

  /**
   * Whether the layers may be touched at all. Locked, the canvas still pans and
   * zooms and every button still works, but a click reaches nothing — "I am
   * reading, not editing".
   */
  let locked = false;

  box.addEventListener("pointerdown", (event) => {
    pressedAt = { x: event.clientX, y: event.clientY };
  });

  /* What is under the pointer, said along the bottom; the view again once the
     pointer leaves. */
  box.addEventListener("pointermove", (event) => {
    const where = viewer?.whereThingsAreDrawn?.();
    if (!where?.unproject) return;
    const bounds = box.getBoundingClientRect();
    const at = where.unproject(event.clientX - bounds.left, event.clientY - bounds.top);
    said.textContent = readoutSays
      ? readoutSays({ at, zoom: where.zoom })
      : `${at.x.toFixed(0)}, ${at.y.toFixed(0)} µm · ${where.zoom.toFixed(2)} µm per pixel`;
  });

  box.addEventListener("pointerleave", () => sayWhereTheViewIs(viewer?.getView?.()));

  box.addEventListener("click", (event) => {
    const from = pressedAt;
    pressedAt = null;
    if (locked || !from || !viewer || !(onTouched || onPressed)) return;
    if (Math.hypot(event.clientX - from.x, event.clientY - from.y) > A_PRESS_THAT_DID_NOT_TRAVEL) {
      return;
    }
    const where = viewer.whereThingsAreDrawn?.();
    if (!where?.unproject) return;
    const bounds = box.getBoundingClientRect();
    const at = where.unproject(event.clientX - bounds.left, event.clientY - bounds.top);
    const found = whoIsAt(stackAbove, at);
    const screen = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
    if (found) onTouched?.({ ...found, at, screen });
    /* Nothing of anyone's under it: the workflow's own picking, in pixels inside
       the box as well as micrometres on the sample. */
    else onPressed?.({ ...at, at, screen });
  });

  /* The layer holding the drag that is under way, if one is: what a drag means
     is settled when it begins and holds until the operator lets go. */
  let holdingTheDrag: Layer | null = null;
  let theHostHasTheDrag = false;

  /**
   * A drag, offered to the layers top of the stack down, then to the workflow,
   * before the picture takes it as a pan. Answers `false` when nobody wanted it.
   */
  function theLayersMayHaveThisDrag(drag: Drag): boolean | void {
    if (drag.phase === "started") {
      holdingTheDrag = locked ? null : whoClaims(stackAbove, drag);
      if (holdingTheDrag) return true;
      theHostHasTheDrag = !locked && handDragsTo ? handDragsTo(drag) !== false : false;
      return theHostHasTheDrag;
    }
    if (holdingTheDrag) {
      const answer = holdingTheDrag.claims?.(drag);
      // Whoever borrowed it is always told it ended, however it ended.
      if (drag.phase === "finished") holdingTheDrag = null;
      return answer;
    }
    if (theHostHasTheDrag) {
      const answer = handDragsTo?.(drag);
      if (drag.phase === "finished") theHostHasTheDrag = false;
      return answer;
    }
    return false;
  }

  /** Lay the canvas's surface down in the box. */
  function openTheCanvas() {
    const opened = openTheSurface(box, {
      background,
      onViewChanged: (where) => { sayWhereTheViewIs(where); onViewMoved?.(where); },
    });
    if (pictureHost) opened.middleSlot.append(pictureHost);
    handTheSlotsTheirDrawings(opened, { openedJustNow: true });
    opened.handDragsTo?.(theLayersMayHaveThisDrag);
    viewer = opened;
    sayWhereTheViewIs(opened.getView());
    return opened;
  }

  /** Whether the named layer is being drawn. */
  function isShowing(key: string | undefined): boolean {
    return stackAbove.find((layer) => layer.key === key)?.shown ?? false;
  }

  /** Turn one layer on or off; the operator's choice is remembered. */
  function showTheLayer(key: string | undefined, on: boolean) {
    if (!viewer || isShowing(key) === on) return;
    const layer = stackAbove.find((one) => one.key === key);
    if (!layer) return;
    layer.shown = on;
    if (key !== undefined && on) turnedOff.delete(key);
    else if (key !== undefined) turnedOff.add(key);
    letTheChromeFollow();
    handTheSlotsTheirDrawings();
    markTheButtons();
  }

  /** How solid the stack over the picture is drawn, 0 to 1. */
  function fadeTo(howSolid: number) {
    dial = Math.min(1, Math.max(0, Number(howSolid)));
    handTheSlotsTheirDrawings();
  }

  /* A layer that is chrome for another goes with it: hide what the handles are
     for and the handles go too. */
  function letTheChromeFollow() {
    const shownOf = new Map(stackAbove.map((one) => [one.key, one.shown]));
    for (const layer of stackAbove) {
      if (layer.follows) layer.shown = layer.shown && shownOf.get(layer.follows) !== false;
    }
  }

  /* What the row of buttons currently says, so it is built again only when it
     would come out different: a run redraws many times a second while it is
     scanning, and rebuilding the row that often takes away the press an
     operator is in the middle of. */
  let theRowSays = "";

  /**
   * A button for every layer there is, and the fade and the lock beside them.
   * Built again whenever the stack changes, because the stack grows while an
   * operator is working.
   */
  function buildTheLayerButtons() {
    const wouldSay = stackAbove
      .map((l) => `${l.key}:${l.label}:${l.has !== false}:${l.shown}`)
      .join("|");
    if (wouldSay === theRowSays) return;
    theRowSays = wouldSay;

    layers.textContent = "";
    /* The strip beside the buttons is rebuilt with them, so a stack that grew
       does not leave two fades and two locks behind it. */
    layers.parentElement?.querySelectorAll(":scope > .layer-extra")
      .forEach((old) => old.remove());
    buttons.clear();

    for (const layer of stackAbove) {
      // Nothing to draw, nothing to switch; chrome is switched with its owner.
      if (layer.has === false || layer.follows) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "layer-chip";
      button.disabled = true;      // until the canvas is open
      button.setAttribute("aria-pressed", String(layer.shown));
      button.dataset.layer = layer.key ?? "";
      button.title = layer.explains ?? "One of the operator's own layers.";
      button.textContent = layer.label ?? layer.key ?? "";
      button.addEventListener("click", () => showTheLayer(layer.key, !isShowing(layer.key)));
      buttons.set(layer.key ?? "", button);
      layers.append(button);
    }

    /* The fade and the lock in a strip of their own beside the buttons: the
       buttons are one joined row of switches, and a slider dropped into it
       reads as something having gone wrong. */
    const beside = document.createElement("div");
    beside.className = "layer-extra";
    layers.after(beside);

    const fade = document.createElement("label");
    fade.className = "layer-fade";
    fade.title =
      "How solid everything over the picture is drawn. Turn it down to see the " +
      "picture through your own drawing. Layers marked to stay solid — the focus " +
      "points, say — are not affected.";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "100";
    slider.step = "1";
    slider.value = String(Math.round(dial * 100));
    slider.dataset.layerFade = "";
    slider.setAttribute("aria-label", "How solid the layers over the picture are");
    slider.addEventListener("input", () => fadeTo(Number(slider.value) / 100));
    fade.append(document.createTextNode("Fade"), slider);
    beside.append(fade);

    lockButton = document.createElement("button");
    lockButton.type = "button";
    lockButton.dataset.lock = "";
    lockButton.setAttribute("aria-pressed", String(locked));
    lockButton.title =
      "Lock the layers so that nothing can be picked or moved by accident. " +
      "Panning and zooming go on working.";
    lockButton.textContent = "Lock";
    lockButton.addEventListener("click", () => handle.lock(!locked));
    beside.append(lockButton);
  }

  /* The lock's own button, remembered so its state can be shown when the lock
     is changed from somewhere other than the button itself. */
  let lockButton: HTMLButtonElement | null = null;

  buildTheLayerButtons();

  const handle: TheCanvas = {
    /** Which layers are being drawn, for a test to read back. */
    get layers() {
      return Object.fromEntries(stackAbove.map((layer) => [layer.key ?? "", layer.shown]));
    },

    fadeTo,

    /** Draw one of the layers, or stop drawing it — the same as its button. */
    showLayer(key, on) { showTheLayer(key, on); },
    /** Whether the named layer is being drawn. */
    layerShown(key) { return isShowing(key); },

    /** Whether a layer, or the workflow, is holding a gesture right now. */
    get gesturing() { return holdingTheDrag !== null || theHostHasTheDrag; },

    get locked() { return locked; },
    lock(on = true) {
      locked = !!on;
      box.classList.toggle("locked", locked);
      if (lockButton) lockButton.setAttribute("aria-pressed", String(locked));
    },

    /**
     * Say what belongs in the stack now. A layer that was already there keeps
     * whether it was being shown; a layer that says what it `has` shows what
     * the run has, less what the operator turned off.
     */
    setLayersAbove(list = []) {
      const before = new Map(stackAbove.map((layer) => [layer.key, layer.shown]));
      stackAbove = list.map((layer) => {
        if (layer.has !== undefined) {
          return { ...layer, shown: layer.has !== false && !turnedOff.has(layer.key ?? "") };
        }
        return {
          ...layer,
          shown: before.has(layer.key) ? before.get(layer.key) : (layer.shown ?? false),
        };
      });
      letTheChromeFollow();
      buildTheLayerButtons();
      handTheSlotsTheirDrawings();
      markTheButtons();
    },

    /** The stack as it stands, for a workflow that wants to add one to it. */
    get layersAbove() { return stackAbove.map((layer) => ({ ...layer })); },

    /** Where the canvas is looking, and a way to put it somewhere else. */
    get view() { return viewer?.getView?.() ?? null; },
    lookAt(where) { if (where) viewer?.setView?.(where); },

    /** Where a place on the sample is on screen, and back again: the same
        projection the layers are drawn through. */
    project(x, y) {
      const where = viewer?.whereThingsAreDrawn?.();
      return where ? where.project(x, y) : { x: 0, y: 0 };
    },
    unproject(px, py) {
      const where = viewer?.whereThingsAreDrawn?.();
      return where ? where.unproject(px, py) : { x: 0, y: 0 };
    },

    /**
     * Called each time the panel comes into view. The canvas is opened the
     * first time and kept afterwards, so where the operator panned to stays.
     */
    async whenShown() {
      /* Left where a browser test can reach it; nothing on the page reads it. */
      window.__theCanvas = handle;
      if (!viewer) {
        openTheCanvas();
        markTheButtons();
      }
      return viewer;
    },
  };

  return handle;
}
