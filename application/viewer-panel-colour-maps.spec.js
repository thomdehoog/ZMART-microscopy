/**
 * Colour maps, and whether choosing one changes the picture.
 *
 * A colour map paints one channel in a run of colours rather than one flat
 * colour — dim values one shade, bright values another, with a smooth path
 * between. On a single channel that usually reads far more detail than a flat
 * green, because the whole range of hue carries the brightness.
 *
 * Two things are worth checking and neither can be checked from the panel
 * alone. The chooser must offer only maps the engine says it can actually draw,
 * because a menu whose choices do nothing is precisely the kind of quiet
 * untruth this work has been about. And choosing one must change what is on
 * screen — so the page itself is photographed and the colours in it are counted,
 * rather than the panel being asked whether it thinks it did something.
 *
 * The screenshot is of the whole page, deliberately. A WebGL canvas does not
 * appear in a screenshot of its own element — it comes out convincingly blank —
 * and three separate "the picture is empty" conclusions on this branch came from
 * exactly that mistake.
 *
 * Point ZV_SOURCE at two served stores, separated by a space.
 */
import { expect, test } from "@playwright/test";
import { readPng } from "./workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/** How many plainly different colours are on the page, and the commonest few. */
function coloursIn(shot) {
  const { data, channels } = readPng(shot);
  const seen = new Map();
  for (let at = 0; at < data.length; at += channels) {
    if (channels === 4 && data[at + 3] < 250) continue;
    /* Rounded to sixteens: two shades a hand's breadth apart within one gradient
       are the same colour for this purpose, and counting every last value would
       make a photograph of noise look like a colour map. */
    const key = `${data[at] >> 4},${data[at + 1] >> 4},${data[at + 2] >> 4}`;
    seen.set(key, (seen.get(key) ?? 0) + 1);
  }
  return [...seen.entries()].sort((one, two) => two[1] - one[1]);
}

test("a channel can be painted through a colour map", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");

  await page.goto("/?backend=pretend");
  await page.evaluate(async (given) => {
    const host = document.createElement("div");
    host.id = "colour-maps-host";
    host.style.cssText = "position:fixed;inset:0;z-index:999;background:#202830;";
    document.body.append(host);
    const acquisitions = given.split(" ").map((url) => ({
      url, name: url.includes("focussing") ? "focussing" : "overview",
    }));
    const { openerFor } = await import("/parts/canvas/engines.js");
    const openViewer = await openerFor("neuroglancer-under");
    const viewer = await openViewer(host, { acquisitions, background: "#202830" });
    window.__panelViewer = viewer;
    const { mountViewerPanel } = await import("/parts/canvas/viewer-panel.js");
    window.__panelHandle = await mountViewerPanel(host, {
      viewer, acquisitions, css: () => "#202830",
    });
  }, source);
  await rest(5000);

  /* What the engine says it can draw, and what the chooser offers, have to be
     the same list. */
  const canDraw = await page.evaluate(() => window.__panelViewer.lutsItCanDraw);
  console.log("the engine says it can draw:", JSON.stringify(canDraw));
  expect(canDraw.length, "this engine offers colour maps at all")
    .toBeGreaterThan(0);

  const offered = await page.evaluate(() => {
    const panel = window.__viewerPanel;
    panel.querySelector("button[data-lut]").click();
    const list = [...document.body.children].reverse()
      .find((one) => one.style.position === "fixed");
    return [...list.querySelectorAll("button")].map((one) => one.textContent);
  });
  console.log("the chooser offers:", JSON.stringify(offered));
  for (const name of canDraw) {
    expect(offered.some((line) => line.startsWith(name)),
      `${name} is offered`).toBe(true);
  }
  /* And each map is described in plain colours, because the names mean nothing
     until you have seen one. */
  expect(offered.find((line) => line.startsWith("viridis")),
    "viridis says what it looks like").toContain("→");

  const asAFlatColour = coloursIn(await page.screenshot({ fullPage: false }));
  console.log("flat: the five commonest colours are",
    JSON.stringify(asAFlatColour.slice(0, 5)));

  /* Choose the first map the engine offers, from the chooser that is open. */
  await page.evaluate((name) => {
    const list = [...document.body.children].reverse()
      .find((one) => one.style.position === "fixed");
    [...list.querySelectorAll("button")]
      .find((one) => one.textContent.startsWith(name)).click();
  }, canDraw[0]);
  await rest(3000);

  const throughAMap = coloursIn(await page.screenshot({ fullPage: false }));
  console.log(`${canDraw[0]}: the five commonest colours are`,
    JSON.stringify(throughAMap.slice(0, 5)));

  /* The picture is drawn in different colours than it was. This is the whole
     assertion: the panel saying it sent a request proves nothing. */
  const wasCommonest = asAFlatColour.map(([key]) => key).slice(0, 8);
  const isCommonest = throughAMap.map(([key]) => key).slice(0, 8);
  const changed = isCommonest.filter((one) => !wasCommonest.includes(one));
  expect(changed.length,
    `${canDraw[0]} draws the picture in colours the flat one did not`)
    .toBeGreaterThan(0);

  /* And the swatch says which map the channel is painted through, so the row
     does not go on showing a flat colour it is no longer drawn in. */
  const swatchSays = await page.evaluate(
    () => window.__viewerPanel.querySelector("button[data-lut]").dataset.lut);
  expect(swatchSays, "the swatch says which map this row is painted through")
    .toBe(canDraw[0]);

  /* Going back to a flat colour puts the flat colour back. */
  await page.evaluate(() => {
    const panel = window.__viewerPanel;
    panel.querySelector("button[data-lut]").click();
    const list = [...document.body.children].reverse()
      .find((one) => one.style.position === "fixed");
    [...list.querySelectorAll("button")]
      .find((one) => one.textContent.startsWith("green")).click();
  });
  await rest(2000);
  const backToFlat = await page.evaluate(
    () => window.__viewerPanel.querySelector("button[data-lut]").dataset.lut);
  expect(backToFlat, "choosing a flat colour turns the map off").toBe("");
});
