/**
 * The layers above the picture, and the three ways they can be made see-through.
 *
 * These run without a browser, against a pretend drawing surface that simply
 * writes down what it was asked to do. That is enough, because everything here
 * is about *order and strength* — which layer is drawn when, and how solid —
 * and both are plainly visible in the list of calls. What a browser would add
 * is the actual pixels, and those are checked by a photograph elsewhere.
 */

import { describe, expect, it } from "vitest";

import { theDrawingAbove, whoIsAt } from "../../src/canvas/layers-above.js";

/** A drawing surface that remembers what it was told, and nothing more. */
function aPretendSurface() {
  const done = [];
  const state = { globalAlpha: 1, globalCompositeOperation: "source-over", fillStyle: "#000" };
  const kept = [];
  return {
    done,
    get globalAlpha() { return state.globalAlpha; },
    set globalAlpha(v) { state.globalAlpha = v; },
    get globalCompositeOperation() { return state.globalCompositeOperation; },
    set globalCompositeOperation(v) { state.globalCompositeOperation = v; },
    get fillStyle() { return state.fillStyle; },
    set fillStyle(v) { state.fillStyle = v; },
    save() { kept.push({ ...state }); },
    restore() { Object.assign(state, kept.pop()); },
    fillRect(x, y, w, h) {
      done.push({ what: "fillRect", x, y, w, h,
        alpha: state.globalAlpha, how: state.globalCompositeOperation });
    },
  };
}

/**
 * A frame of the kind every engine hands a drawing, one micrometre to the
 * pixel with the sample's origin at the corner of the box.
 *
 * The same shape as the real thing — see `viz_studio/options/contract.md` —
 * because a composer that took some other shape would work perfectly in a test
 * and draw nothing at all on a page.
 */
const aFrame = (surface) => ({
  context: surface,
  centre: { x: 50, y: 50 },
  zoom: 1,
  width: 100,
  height: 100,
  density: 1,
  project: (x, y) => ({ x, y }),
  unproject: (x, y) => ({ x, y }),
});

/** A layer that simply records that it was asked to draw, and how solidly. */
const aLayerThatMarks = (name, extra = {}) => ({
  paint: ({ context }) => context.done.push({ what: name, alpha: context.globalAlpha }),
  ...extra,
});

describe("the drawing above the picture", () => {
  it("is nothing at all when there is nothing to draw", () => {
    expect(theDrawingAbove([])).toBeNull();
    expect(theDrawingAbove([{ shown: true }])).toBeNull();
  });

  it("draws the layers bottom of the stack first", () => {
    const surface = aPretendSurface();
    theDrawingAbove([aLayerThatMarks("carrier"), aLayerThatMarks("positions")])(aFrame(surface));
    expect(surface.done.map((d) => d.what)).toEqual(["carrier", "positions"]);
  });

  it("leaves out a layer that has been switched off", () => {
    const surface = aPretendSurface();
    theDrawingAbove([
      aLayerThatMarks("carrier", { shown: false }),
      aLayerThatMarks("positions"),
    ])(aFrame(surface));
    expect(surface.done.map((d) => d.what)).toEqual(["positions"]);
  });

  it("gives each layer its own strength, and the dial fades them all together", () => {
    const surface = aPretendSurface();
    theDrawingAbove(
      [aLayerThatMarks("carrier", { opacity: 0.5 }), aLayerThatMarks("positions")],
      { dial: 0.5 },
    )(aFrame(surface));
    // A layer already half faded ends up a quarter as solid; one that was solid
    // ends up half. The dial multiplies what is there, it does not replace it.
    expect(surface.done).toEqual([
      { what: "carrier", alpha: 0.25 },
      { what: "positions", alpha: 0.5 },
    ]);
  });

  it("only ever makes a layer fainter, never more solid", () => {
    const surface = aPretendSurface();
    theDrawingAbove([aLayerThatMarks("carrier", { opacity: 0.3 })], { dial: 1 })(aFrame(surface));
    expect(surface.done[0].alpha).toBeCloseTo(0.3);
  });

  it("does not ask a layer faded to nothing to draw at all", () => {
    const surface = aPretendSurface();
    theDrawingAbove([aLayerThatMarks("carrier")], { dial: 0 })(aFrame(surface));
    expect(surface.done).toEqual([]);
  });

  it("cuts a window over the ground it was given, in micrometres", () => {
    const surface = aPretendSurface();
    theDrawingAbove([aLayerThatMarks("plan")], {
      seeThrough: [{ x: 10, y: 20, w: 30, h: 40 }],
    })(aFrame(surface));
    const cut = surface.done.find((d) => d.what === "fillRect");
    expect(cut).toMatchObject({ x: 10, y: 20, w: 30, h: 40, how: "destination-out" });
  });

  it("cuts through every layer below the window, so the picture is what shows", () => {
    const surface = aPretendSurface();
    theDrawingAbove([aLayerThatMarks("carrier"), aLayerThatMarks("positions")], {
      seeThrough: [{ x: 0, y: 0, w: 10, h: 10 }],
    })(aFrame(surface));
    const order = surface.done.map((d) => d.what);
    expect(order).toEqual(["carrier", "positions", "fillRect"]);
  });

  it("leaves a layer that stays solid alone, above the window and out of the dial", () => {
    const surface = aPretendSurface();
    theDrawingAbove(
      [aLayerThatMarks("plan"), aLayerThatMarks("focus points", { staysSolid: true })],
      { dial: 0.2, seeThrough: [{ x: 0, y: 0, w: 10, h: 10 }] },
    )(aFrame(surface));
    expect(surface.done.map((d) => d.what)).toEqual(["plan", "fillRect", "focus points"]);
    // Faded with the rest, the plan is nearly gone; the focus points are untouched.
    expect(surface.done[0].alpha).toBeCloseTo(0.2);
    expect(surface.done[2].alpha).toBe(1);
  });

  it("lets a window be half open, so the drawing is thinned rather than removed", () => {
    const surface = aPretendSurface();
    theDrawingAbove([aLayerThatMarks("plan")], {
      seeThrough: [{ x: 0, y: 0, w: 10, h: 10, letThrough: 0.4 }],
    })(aFrame(surface));
    expect(surface.done.find((d) => d.what === "fillRect").alpha).toBeCloseTo(0.4);
  });

  it("does not let one layer's settings leak into the next", () => {
    const surface = aPretendSurface();
    theDrawingAbove([
      { paint: ({ context }) => { context.globalAlpha = 0.01; context.fillStyle = "red"; } },
      aLayerThatMarks("positions"),
    ])(aFrame(surface));
    // The second layer draws at its own full strength, not at whatever the
    // first one happened to leave behind.
    expect(surface.done).toEqual([{ what: "positions", alpha: 1 }]);
  });
});

describe("what a click reaches", () => {
  const aTileAt = (key, x, y) => ({
    key,
    paint: () => {},
    reaches: (at) => (at.x >= x && at.x < x + 10 && at.y >= y && at.y < y + 10 ? key : null),
  });

  it("finds nothing where no layer claims the click", () => {
    expect(whoIsAt([aTileAt("plan", 0, 0)], { x: 500, y: 500 })).toBeNull();
    expect(whoIsAt([], { x: 0, y: 0 })).toBeNull();
    expect(whoIsAt([aTileAt("plan", 0, 0)], null)).toBeNull();
  });

  it("hands the click to the layer the operator can see, which is the top one", () => {
    const stack = [aTileAt("positions", 0, 0), aTileAt("targets", 0, 0)];
    expect(whoIsAt(stack, { x: 5, y: 5 }).what).toBe("targets");
  });

  it("falls through to the layer below where the top one does not claim it", () => {
    const stack = [aTileAt("positions", 0, 0), aTileAt("targets", 100, 100)];
    expect(whoIsAt(stack, { x: 5, y: 5 }).what).toBe("positions");
  });

  it("does not let a layer that is switched off catch a click", () => {
    const hidden = { ...aTileAt("targets", 0, 0), shown: false };
    const stack = [aTileAt("positions", 0, 0), hidden];
    expect(whoIsAt(stack, { x: 5, y: 5 }).what).toBe("positions");
  });

  it("passes over a layer that has nothing to say about being touched", () => {
    const stack = [aTileAt("positions", 0, 0), { key: "heatmap", paint: () => {} }];
    expect(whoIsAt(stack, { x: 5, y: 5 }).what).toBe("positions");
  });
});
