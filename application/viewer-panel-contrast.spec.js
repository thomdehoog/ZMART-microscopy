/**
 * The contrast controls, and whether the four of them describe one window.
 *
 * The panel offers *min* and *max*, which say where the brightness window's
 * edges are, and *brightness* and *contrast*, which say how bright its middle
 * is and how tightly it is drawn around that middle. Underneath there is only
 * ever one window, and the risk in offering both pairs is that they quietly
 * stop agreeing — an operator moves one, reads the other, and is told something
 * untrue about their own picture.
 *
 * So each control is moved and the *picture* is asked what window it is really
 * drawing through, rather than the panel being asked what it thinks. That
 * pairing is the whole reason this file exists; a panel that only agrees with
 * itself proves nothing.
 *
 * The other two things checked here are the ones an operator meets when
 * something has gone wrong. *Reset* has to put back the window the run was
 * written with, because dragging the handles about and wanting the picture back
 * is the commonest thing anybody does with this card. And a measurement that
 * did not work has to say so, rather than leaving an empty histogram and a pair
 * of sliders at their fallback range with nothing on screen to explain them.
 *
 * Point ZV_SOURCE at two served stores, separated by a space.
 */
import { expect, test } from "@playwright/test";

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/** One of the labelled sliders in the channel settings card. */
async function control(page, label) {
  return page.evaluate((wanted) => {
    const panel = window.__viewerPanel ?? document.body;
    const line = [...panel.querySelectorAll("label")]
      .find((one) => one.textContent.startsWith(wanted));
    const slider = line?.querySelector("input[type=range]");
    const box = line?.querySelector("span:last-child");
    return slider
      ? { value: Number(slider.value), reads: box?.textContent ?? null }
      : null;
  }, label);
}

/** Drag one of those sliders to a value, the way an operator would. */
async function move(page, label, to) {
  await page.evaluate(({ wanted, value }) => {
    const panel = window.__viewerPanel ?? document.body;
    const line = [...panel.querySelectorAll("label")]
      .find((one) => one.textContent.startsWith(wanted));
    const slider = line.querySelector("input[type=range]");
    slider.value = String(value);
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  }, { wanted: label, value: to });
  await rest(400);
}

/** The window the picture is really drawing the first channel through. */
async function theWindowOnScreen(page) {
  return page.evaluate(() => window.__panelViewer.layersForMeasurement()[0].window);
}

/** Press one of the buttons in the channel settings card by its wording. */
async function pressButton(page, wording) {
  await page.evaluate((wanted) => {
    const panel = window.__viewerPanel ?? document.body;
    [...panel.querySelectorAll("button")]
      .find((one) => one.textContent.trim() === wanted)
      .click();
  }, wording);
  await rest(600);
}

async function openThePanel(page, sources) {
  await page.goto("/?backend=pretend");
  await page.evaluate(async (given) => {
    const host = document.createElement("div");
    host.id = "panel-contrast-host";
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
  }, sources);
  await rest(4000);
}

test("brightness and contrast move the same window min and max do", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  const atTheStart = await theWindowOnScreen(page);
  console.log("the window the picture opened with:", JSON.stringify(atTheStart));

  /* Brightness slides the whole window along without changing how wide it is.
     Both edges have to move on screen, and by the same amount — a brightness
     slider that moved only one edge would be a contrast slider wearing the
     wrong label. */
  const wasBright = (await control(page, "brightness")).value;
  await move(page, "brightness", Math.min(95, wasBright + 20));
  const afterBrightness = await theWindowOnScreen(page);
  console.log("after moving brightness:", JSON.stringify(afterBrightness));
  expect(afterBrightness.low, "the low edge moved").not.toBe(atTheStart.low);
  expect(afterBrightness.high, "the high edge moved").not.toBe(atTheStart.high);
  expect(
    Math.abs((afterBrightness.high - afterBrightness.low)
      - (atTheStart.high - atTheStart.low)),
    "and the window is still the same width",
  ).toBeLessThan(2);

  /* Contrast draws the window in around its middle. */
  const wasTight = (await control(page, "contrast")).value;
  await move(page, "contrast", Math.min(95, wasTight + 30));
  const afterContrast = await theWindowOnScreen(page);
  console.log("after moving contrast:", JSON.stringify(afterContrast));
  expect(
    afterContrast.high - afterContrast.low,
    "a tighter contrast is a narrower window",
  ).toBeLessThan(afterBrightness.high - afterBrightness.low);

  /* And the traffic goes both ways. Taking hold of *min* has to move the
     brightness and contrast readings, because all four say the same thing. */
  const brightBefore = (await control(page, "brightness")).value;
  const tightBefore = (await control(page, "contrast")).value;
  const onScreen = await theWindowOnScreen(page);
  await move(page, "min", Math.round(onScreen.low - (onScreen.high - onScreen.low) / 2));
  const brightAfter = (await control(page, "brightness")).value;
  const tightAfter = (await control(page, "contrast")).value;
  console.log("moving min moved brightness", brightBefore, "→", brightAfter,
    "and contrast", tightBefore, "→", tightAfter);
  expect(brightAfter, "moving min moved the brightness reading").not.toBe(brightBefore);
  expect(tightAfter, "moving min moved the contrast reading").not.toBe(tightBefore);
});

test("Reset puts back the window the run was written with", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  const asOpened = await theWindowOnScreen(page);
  const canGoBack = await page.evaluate(() => {
    const panel = window.__viewerPanel ?? document.body;
    return ![...panel.querySelectorAll("button")]
      .find((one) => one.textContent.trim() === "Reset").disabled;
  });
  console.log("the window the acquisition opened with:", JSON.stringify(asOpened),
    "and Reset is", canGoBack ? "offered" : "greyed out");
  test.skip(!canGoBack,
    "this store declared no window, so there is nothing for Reset to go back to");

  /* Pull the handles well away from where they started, the way somebody
     hunting for their specimen does. */
  await move(page, "brightness", 90);
  await move(page, "contrast", 80);
  const pulledAbout = await theWindowOnScreen(page);
  expect(pulledAbout.low, "the window really did move").not.toBe(asOpened.low);

  await pressButton(page, "Reset");
  const putBack = await theWindowOnScreen(page);
  console.log("after Reset:", JSON.stringify(putBack));
  /* Exactly the picture the acquisition opened with. Within a count, because
     the panel rounds to whole counts on its way through the sliders. */
  expect(Math.abs(putBack.low - asOpened.low), "the low edge is back").toBeLessThan(2);
  expect(Math.abs(putBack.high - asOpened.high), "the high edge is back").toBeLessThan(2);
});

test("a measurement that did not work says so", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");

  /* Pointed at an address nobody is serving. Everything else about the panel is
     as it always is — the store still opens, the row is still there — so what is
     being checked is only what the panel does when the measurement fails. */
  const nobodyIsThere = "http://127.0.0.1:9/nothing/is/served/here.zarr";
  await page.goto("/?backend=pretend");
  await page.evaluate(async (dead) => {
    const host = document.createElement("div");
    host.id = "panel-trouble-host";
    host.style.cssText = "position:fixed;inset:0;z-index:999;background:#202830;";
    document.body.append(host);
    const { mountViewerPanel } = await import("/parts/canvas/viewer-panel.js");
    /* A stand-in for the drawing engine. This check is about the panel's own
       account of a failure, and opening a real engine on an address nobody is
       serving would fail earlier and for a different reason. */
    const viewer = {
      setChannel() {}, setPlane() {}, showPicture() {},
      theDepthItCanShow: () => null, layersForMeasurement: () => [],
      canShowVolume: false,
    };
    window.__panelHandle = await mountViewerPanel(host, {
      viewer, acquisitions: [{ url: dead, name: "nowhere" }], css: () => "#202830",
    });
  }, nobodyIsThere);
  await rest(6000);

  const said = await page.evaluate(() => {
    const panel = window.__viewerPanel ?? document.body;
    const notice = panel.querySelector("[data-trouble='1']");
    return notice ? notice.textContent : null;
  });
  console.log("the panel said:", said);
  expect(said, "the panel says a measurement failed rather than sitting quiet")
    .toBeTruthy();
  expect(said, "and it says what it asked for").toContain("127.0.0.1:9");
});
