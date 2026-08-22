/**
 * The layers above the picture: an arbitrary stack, each one an operator's to
 * work with.
 *
 * The canvas is not three fixed layers any more. Below is the picture, always
 * solid and always at the bottom, and above it is a stack that grows as a
 * workflow goes: where the microscope is now, the carrier, the positions, the
 * focus points, the heatmap, the targets once discovery has found them, the
 * refined targets after that. Each has a button, each can be faded, each can be
 * touched, and one control fades the lot.
 *
 * These drive a real browser and read what it drew, because every one of the
 * faults this guards against passes a test that only counts things. A stack
 * that reports itself perfectly and draws in the wrong order is exactly the
 * kind of failure that reaches an operator.
 */

import { expect, test } from "@playwright/test";

/* A page holding nothing but a canvas, so what is being looked at is the canvas
   and not the operator window around it. Built here rather than in the
   application so that the stack can be anything these tests need it to be. */
const A_PAGE_WITH_ONLY_A_CANVAS = `
<!doctype html><meta charset="utf-8">
<style>
  html,body{margin:0;background:#05070d;font:13px system-ui}
  #layers{display:flex;gap:4px;align-items:center;padding:6px}
  #box{position:relative;width:640px;height:420px;background:#05070d}
</style>
<div id="head"><span id="name"></span><span id="readout"></span></div>
<div id="chooser"></div><div id="layers"></div><div id="why"></div>
<div id="box"></div><div id="note" hidden></div>
<script type="module">
const el = (id) => document.getElementById(id);
const { putTheCanvasIn } = await import("/src/canvas/panel.js");

/* Three plain layers, each a flat square of its own colour on its own piece of
   sample, so that which of them reached the screen can be counted from a
   photograph. Squares rather than something prettier for exactly that reason. */
const aSquare = (colour, x, y, side) => ({
  paint: ({ context, project, zoom }) => {
    const at = project(x, y);
    context.fillStyle = colour;
    context.fillRect(at.x, at.y, side / zoom, side / zoom);
  },
  reaches: (at) => (at.x >= x && at.x < x + side && at.y >= y && at.y < y + side ? true : null),
});

window.__touched = [];
window.__canvas = await putTheCanvasIn({
  box: el("box"), note: el("note"), chooser: el("chooser"), layers: el("layers"),
  why: el("why"), readout: el("readout"), name: el("name"),
  acquisitions: [], engine: "jpeg-under",
  layersAbove: [
    { key: "carrier", label: "Carrier", ...aSquare("rgb(30,80,190)", 0, 0, 300) },
    { key: "tiles", label: "Tiles", ...aSquare("rgb(240,160,30)", 60, 60, 180) },
    { key: "focus", label: "Focus", staysSolid: true,
      ...aSquare("rgb(20,220,120)", 100, 100, 60) },
  ],
  onTouched: ({ layer, at }) => window.__touched.push({ key: layer.key, at }),
});
await window.__canvas.whenShown();
window.__ready = true;
</script>`;

/**
 * How much of the box is within reach of the given colour.
 *
 * Waits for a drawing to finish first. The canvas asks the browser for a frame
 * rather than drawing on the spot — which is what stops a burst of changes
 * redrawing it a dozen times — so reading the pixels straight after pressing a
 * button can catch the frame before the change, and see the layer that was
 * just switched off.
 */
async function howMuchIs(page, [red, green, blue]) {
  await page.evaluate(() => new Promise((done) => {
    requestAnimationFrame(() => requestAnimationFrame(done));
  }));
  return page.evaluate(([r, g, b]) => {
    const canvases = [...document.querySelectorAll("#box canvas")];
    let hits = 0, all = 0;
    for (const canvas of canvases) {
      const ctx = canvas.getContext("2d");
      const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
      all = data.length / 4;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] > 8
            && Math.abs(data[i] - r) < 30
            && Math.abs(data[i + 1] - g) < 30
            && Math.abs(data[i + 2] - b) < 30) hits += 1;
      }
    }
    return all ? hits / all : 0;
  }, [red, green, blue]);
}

/** Where a place on the sample is on screen right now, ready to be clicked. */
async function onScreen(page, x, y) {
  return page.evaluate(([mx, my]) => {
    const where = window.__canvas.view;
    const box = document.getElementById("box").getBoundingClientRect();
    return {
      x: box.left + box.width / 2 + (mx - where.centre.x) / where.zoom,
      y: box.top + box.height / 2 + (my - where.centre.y) / where.zoom,
    };
  }, [x, y]);
}

/* Where all three squares overlap. The carrier covers 0–300 µm, the tiles
   60–240 and the focus points 100–160, so this one place is inside every one
   of them — which is what makes it the right place to ask "whose click is
   this?". */
const WHERE_ALL_THREE_OVERLAP = [120, 120];

const THE_CARRIER = [30, 80, 190];
const THE_TILES = [240, 160, 30];
const THE_FOCUS = [20, 220, 120];

test.beforeEach(async ({ page }) => {
  await page.route("**/only-a-canvas.html", (route) =>
    route.fulfill({ contentType: "text/html", body: A_PAGE_WITH_ONLY_A_CANVAS }));
  await page.goto("/only-a-canvas.html");
  await page.waitForFunction(() => window.__ready === true, null, { timeout: 30_000 });
});

test("gives every layer in the stack a button of its own", async ({ page }) => {
  const named = await page.locator("#layers button[data-layer]").evaluateAll(
    (buttons) => buttons.map((b) => b.dataset.layer));
  // The two fixed slots, then one per layer the workflow handed in, in order.
  expect(named).toEqual(["beneath", "picture", "carrier", "tiles", "focus"]);
});

test("turns one layer off and leaves the others exactly where they were", async ({ page }) => {
  for (const key of ["carrier", "tiles", "focus"]) {
    await page.locator(`#layers button[data-layer="${key}"]`).click();
  }
  const all = await Promise.all([howMuchIs(page, THE_CARRIER), howMuchIs(page, THE_TILES),
                                 howMuchIs(page, THE_FOCUS)]);
  expect(all.every((share) => share > 0.005), `one of the three never drew: ${all}`).toBe(true);

  /* This is the reason the heatmap and the focus points are separate layers
     rather than one drawing: an operator who wants the heatmap out of the way
     is not asking to lose the focus points with it. */
  await page.locator('#layers button[data-layer="tiles"]').click();
  expect(await howMuchIs(page, THE_TILES)).toBeLessThan(0.002);
  expect(await howMuchIs(page, THE_FOCUS)).toBeGreaterThan(0.005);
  expect(await howMuchIs(page, THE_CARRIER)).toBeGreaterThan(0.005);
});

test("fades the whole stack with one control, and leaves the solid ones solid", async ({ page }) => {
  for (const key of ["carrier", "tiles", "focus"]) {
    await page.locator(`#layers button[data-layer="${key}"]`).click();
  }
  const before = await howMuchIs(page, THE_TILES);
  const focusBefore = await howMuchIs(page, THE_FOCUS);

  await page.locator("#layers input[data-layer-fade]").fill("25");
  await page.locator("#layers input[data-layer-fade]").dispatchEvent("input");
  await page.waitForTimeout(200);

  expect(await howMuchIs(page, THE_TILES), "the tiles did not fade").toBeLessThan(before / 2);
  /* Focus points mark where the microscope will focus. Fading the plan to see
     the picture underneath is not a request to lose them too. */
  expect(await howMuchIs(page, THE_FOCUS), "the focus points faded with the rest")
    .toBeGreaterThan(focusBefore * 0.8);
});

test("opens a window over chosen ground, cutting through every layer below it", async ({ page }) => {
  for (const key of ["carrier", "tiles", "focus"]) {
    await page.locator(`#layers button[data-layer="${key}"]`).click();
  }
  const tilesBefore = await howMuchIs(page, THE_TILES);
  const carrierBefore = await howMuchIs(page, THE_CARRIER);

  /* A window wider than the tiles, so it reaches ground the carrier holds on
     its own. That matters: a window has to take away *every* layer below it,
     not only the top one, because what is meant to show through is the
     picture — and if it only cut the top layer, the next drawing down would
     appear instead, which is the opposite of what was asked for. */
  await page.evaluate(() => window.__canvas.seeThrough([{ x: 0, y: 0, w: 280, h: 280 }]));
  await page.waitForTimeout(200);

  expect(await howMuchIs(page, THE_TILES)).toBeLessThan(tilesBefore * 0.2);
  expect(await howMuchIs(page, THE_CARRIER),
    "the window did not reach the carrier below the tiles").toBeLessThan(carrierBefore * 0.5);
  /* And the focus points, which stay solid, are drawn after the window is cut
     and so survive it — even though the window covers the ground they are on. */
  expect(await howMuchIs(page, THE_FOCUS)).toBeGreaterThan(0.005);
});

test("hands a click to the layer the operator can see", async ({ page }) => {
  for (const key of ["carrier", "tiles", "focus"]) {
    await page.locator(`#layers button[data-layer="${key}"]`).click();
  }
  const at = await onScreen(page, ...WHERE_ALL_THREE_OVERLAP);
  await page.mouse.click(at.x, at.y);
  const touched = await page.evaluate(() => window.__touched.map((t) => t.key));
  expect(touched.at(-1)).toBe("focus");
});

test("a drag pans the picture and is not also a click", async ({ page }) => {
  await page.locator('#layers button[data-layer="focus"]').click();
  const at = await onScreen(page, ...WHERE_ALL_THREE_OVERLAP);
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(at.x + 90, at.y + 40, { steps: 6 });
  await page.mouse.up();
  /* An operator who drags the picture across the screen and happens to let go
     over a focus point has not chosen that focus point. */
  expect(await page.evaluate(() => window.__touched.length)).toBe(0);
});

test("locks the layers so nothing can be picked, and still pans", async ({ page }) => {
  await page.locator('#layers button[data-layer="focus"]').click();
  await page.locator("#layers button[data-lock]").click();
  expect(await page.locator("#layers button[data-lock]").getAttribute("aria-pressed"))
    .toBe("true");

  const at = await onScreen(page, ...WHERE_ALL_THREE_OVERLAP);
  const before = await page.evaluate(() => window.__canvas.view);
  await page.mouse.click(at.x, at.y);
  expect(await page.evaluate(() => window.__touched.length), "a locked layer was picked").toBe(0);

  // Locking is about picking, not about moving. The canvas is still something
  // to look around in.
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(at.x - 70, at.y, { steps: 5 });
  await page.mouse.up();
  const after = await page.evaluate(() => window.__canvas.view);
  expect(after.centre.x).not.toBeCloseTo(before.centre.x, 3);

  await page.locator("#layers button[data-lock]").click();
  // The view moved while panning, so ask again where that piece of sample is.
  const nowAt = await onScreen(page, ...WHERE_ALL_THREE_OVERLAP);
  await page.mouse.click(nowAt.x, nowAt.y);
  expect(await page.evaluate(() => window.__touched.length),
    "unlocking did not give the layers back").toBeGreaterThan(0);
});

test("grows the stack while somebody is watching, keeping what they had set", async ({ page }) => {
  await page.locator('#layers button[data-layer="carrier"]').click();

  /* Targets appear when discovery finishes and refined targets after that, so
     the stack is not the same at the end of a workflow as at the beginning. */
  await page.evaluate(() => {
    const now = window.__canvas.layersAbove;
    window.__canvas.setLayersAbove([
      ...now,
      { key: "targets", label: "Targets", paint: ({ context }) => {
          context.fillStyle = "rgb(220,40,140)";
          context.fillRect(0, 0, 40, 40);
        } },
    ]);
  });

  const named = await page.locator("#layers button[data-layer]").evaluateAll(
    (buttons) => buttons.map((b) => b.dataset.layer));
  expect(named).toEqual(["beneath", "picture", "carrier", "tiles", "focus", "targets"]);
  /* An operator who turned the carrier on should not find it off again because
     a target was discovered somewhere else entirely. */
  expect(await page.evaluate(() => window.__canvas.layers.carrier)).toBe(true);
});
