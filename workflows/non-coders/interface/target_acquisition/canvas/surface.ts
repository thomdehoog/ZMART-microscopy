/**
 * The canvas's own surface: where the operator pans and zooms, and where the
 * workflow's drawings go around the run's picture.
 *
 * Three things are stacked in the box: a drawing surface for what lies beneath
 * the picture, a middle slot the run's picture is put in, and a drawing surface
 * for what lies over it. The view — the place on the sample at the middle of the
 * box, and how much sample one screen pixel covers — is held here, and moves
 * only by the two gestures every canvas shares (`engines/gestures.ts`) or when
 * the page asks. Everything registered to the canvas follows the view this
 * reports, which is how the picture in the middle and the drawings around it
 * stay one picture.
 *
 * Positions are in micrometres on the sample. A drawing is handed one frame:
 * the view, the box's size, a drawing context, and `project`/`unproject`
 * between micrometres and pixels from the top-left of the box.
 */

import { onlyPanAndZoom, type DragHandler } from "./engines/gestures.ts";
import type { View } from "./engines/opening-view.ts";

/** A place, in micrometres on the sample or in pixels in the box. */
interface XY {
  x: number;
  y: number;
}

/** Where things are drawn: the view, the box's size and density, and the way between micrometres and pixels. */
export interface Where {
  centre: XY;
  zoom: number;
  width: number;
  height: number;
  density: number;
  project(x: number, y: number): XY;
  unproject(x: number, y: number): XY;
}

/** What a drawing is handed: where things are, a context to draw in, and what of the picture is covered. */
export interface Frame extends Where {
  context: CanvasRenderingContext2D;
  coverage: unknown;
}

/** A drawing. */
export type Paint = (frame: Frame) => void;

/** The surface, as the page drives it. */
export interface Surface {
  setView(view?: { centre?: XY; zoom?: number }): void;
  getView(): View;
  readonly middleSlot: HTMLElement;
  handDragsTo(handler: DragHandler | null | undefined): void;
  drawUnder(paint: Paint | null | undefined): void;
  drawOver(paint: Paint | null | undefined): void;
  whereThingsAreDrawn(): Where;
}

/** The box and the three things stacked in it. */
interface Surfaces {
  box: HTMLDivElement;
  under: HTMLCanvasElement;
  middle: HTMLDivElement;
  over: HTMLCanvasElement;
}

/** What the surface keeps. */
interface Own {
  element: HTMLElement;
  background: string;
  onViewChanged: ((where: Where) => void) | null;
  paintUnder: Paint | null;
  paintOver: Paint | null;
  view: View;
  surfaces: Surfaces;
  size: { width: number; height: number; density: number } | null;
  frameAsked: boolean;
}

/**
 * Lay the surface down inside `element` and hand back the way to drive it.
 *
 * @param background what is behind everything; `"transparent"` for a host that
 *   draws something of its own beneath the canvas.
 * @param onViewChanged told the view, as it now is, every time it moves.
 */
export function openTheSurface(element: HTMLElement, { background = "#05070d", onViewChanged = null }: {
  background?: string; onViewChanged?: ((where: Where) => void) | null;
} = {}): Surface {
  const own: Own = {
    element,
    background,
    onViewChanged,
    paintUnder: null,
    paintOver: null,
    view: { centre: { x: 0, y: 0 }, zoom: 1 },
    surfaces: buildTheSurfaces(element, background),
    size: null,
    frameAsked: false,
  };
  fitTheSurfaces(own);

  const handle: Surface = {
    setView({ centre, zoom } = {}) {
      if (centre && Number.isFinite(centre.x) && Number.isFinite(centre.y)) {
        own.view.centre = { x: Number(centre.x), y: Number(centre.y) };
      }
      if (zoom !== undefined && Number.isFinite(zoom) && zoom > 0) own.view.zoom = Number(zoom);
      askForAFrame(own);
      own.onViewChanged?.(whereThingsAre(own));
    },

    getView() {
      return { centre: { ...own.view.centre }, zoom: own.view.zoom };
    },

    /** The element the run's picture is put in, between the two drawings. */
    get middleSlot() { return own.surfaces.middle; },

    /** Lend a drag out before it pans; see `engines/gestures.ts`. */
    handDragsTo(handler) { gestures.handDragsTo(handler); },

    drawUnder(paint) {
      own.paintUnder = paint || null;
      askForAFrame(own);
    },

    drawOver(paint) {
      own.paintOver = paint || null;
      askForAFrame(own);
    },

    whereThingsAreDrawn() {
      return whereThingsAre(own);
    },
  };

  const gestures = onlyPanAndZoom(own.surfaces.box, {
    getView: () => handle.getView(),
    setView: (v) => handle.setView(v),
  });

  /* The view it opens on is not announced: nothing has moved yet, and a host
     still setting itself up should not be called into before it has finished. */
  askForAFrame(own);
  return handle;
}

/** The two drawing surfaces and the slot between them, laid in `element`. */
function buildTheSurfaces(element: HTMLElement, background: string): Surfaces {
  const box = document.createElement("div");
  Object.assign(box.style, {
    position: "absolute", inset: "0", background, overflow: "hidden",
  });

  const drawingSurface = (zIndex: string) => {
    const canvas = document.createElement("canvas");
    Object.assign(canvas.style, {
      position: "absolute", inset: "0", width: "100%", height: "100%", display: "block", zIndex,
    });
    return canvas;
  };

  const under = drawingSurface("0");
  const middle = document.createElement("div");
  Object.assign(middle.style, { position: "absolute", inset: "0", zIndex: "1" });
  const over = drawingSurface("2");
  box.append(under, middle, over);
  element.append(box);
  return { box, under, middle, over };
}

/** Keep the drawing surfaces the box's size, in device pixels. */
function fitTheSurfaces(own: Own): { width: number; height: number; density: number } {
  const rect = own.element.getBoundingClientRect();
  const density = globalThis.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * density));
  const height = Math.max(1, Math.round(rect.height * density));
  for (const canvas of [own.surfaces.under, own.surfaces.over]) {
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
  }
  own.size = { width: rect.width, height: rect.height, density };
  return own.size;
}

/**
 * Where a point on the sample lands in the box, and back again: micrometres in,
 * browser pixels from the top-left of the box out.
 */
function whereThingsAre(own: Own): Where {
  const { width = 0, height = 0, density = 1 } = own.size || {};
  const { centre, zoom } = own.view;
  const project = (x: number, y: number) => ({
    x: width / 2 + (x - centre.x) / zoom,
    y: height / 2 + (y - centre.y) / zoom,
  });
  const unproject = (x: number, y: number) => ({
    x: centre.x + (x - width / 2) * zoom,
    y: centre.y + (y - height / 2) * zoom,
  });
  return { centre: { ...centre }, zoom, width, height, density, project, unproject };
}

/** Draw on the next frame, once however many changes asked for it. */
function askForAFrame(own: Own): void {
  if (own.frameAsked) return;
  own.frameAsked = true;
  const draw = () => {
    own.frameAsked = false;
    drawBoth(own);
  };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(draw);
  else draw();
}

/**
 * Draw both surfaces. Each is cleared whether or not there is anything to draw:
 * an empty slot still has to leave an empty surface, or a drawing switched off
 * stays on screen.
 */
function drawBoth(own: Own): void {
  const { density } = fitTheSurfaces(own);
  const where = whereThingsAre(own);
  const clear = (canvas: HTMLCanvasElement) => {
    const context = canvas.getContext("2d")!;
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.scale(density, density);
    return context;
  };
  const under = clear(own.surfaces.under);
  own.paintUnder?.({ ...where, context: under, coverage: null });
  const over = clear(own.surfaces.over);
  own.paintOver?.({ ...where, context: over, coverage: null });
}
