/**
 * Playing a stack, and whether the time control tells the truth about a run.
 *
 * Two things are checked, and they are two halves of the same idea.
 *
 * A stack that plays walks one plane at a time and wraps round at the end, so a
 * sweep loops rather than stopping on its last frame — from across a room, a
 * loop that has stopped and a loop that has stalled look identical, and one of
 * them means the microscope is in trouble. And the play button stops itself if
 * the axis it was playing goes away, because a button quietly stepping
 * something that is not there is a control saying it is doing something it is
 * not.
 *
 * The time control is the other half. A run with one moment is not a timelapse,
 * and the panel draws no time slider at all for it — rather than a slider that
 * cannot move, which reads as a broken control rather than as an honest "there
 * is nothing here".
 *
 * Point ZV_SOURCE at two served stores, separated by a space.
 */
import { expect, test } from "@playwright/test";

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/** One of the two stepping lines in the picture card, and what it says. */
async function axis(page, label) {
  return page.evaluate((wanted) => {
    const panel = window.__viewerPanel ?? document.body;
    const line = [...panel.querySelectorAll("label")]
      .find((one) => one.textContent.startsWith(wanted));
    if (!line) return null;
    const slider = line.querySelector("input[type=range]");
    const play = line.querySelector("button[data-playing]");
    return {
      drawn: line.style.display !== "none",
      at: slider ? Number(slider.value) : null,
      reads: line.querySelector("span:last-child")?.textContent ?? null,
      playing: play ? play.dataset.playing === "1" : null,
    };
  }, label);
}

/** Press the play button on one of those lines. */
async function pressPlay(page, label) {
  await page.evaluate((wanted) => {
    const panel = window.__viewerPanel ?? document.body;
    [...panel.querySelectorAll("label")]
      .find((one) => one.textContent.startsWith(wanted))
      .querySelector("button[data-playing]")
      .click();
  }, label);
}

async function openThePanel(page, sources) {
  await page.goto("/?backend=pretend");
  await page.evaluate(async (given) => {
    const host = document.createElement("div");
    host.id = "stack-plays-host";
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

test("a stack plays, and wraps round rather than stopping", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  const atTheStart = await axis(page, "depth (z)");
  console.log("the depth control at the start:", JSON.stringify(atTheStart));
  test.skip(!atTheStart.drawn,
    "these stores are flat, so there is no stack to play");
  expect(atTheStart.playing, "nothing is playing until it is asked to").toBe(false);

  await pressPlay(page, "depth (z)");
  await rest(1200);
  const playing = await axis(page, "depth (z)");
  console.log("a second or so into playing:", JSON.stringify(playing));
  expect(playing.playing, "the button says it is playing").toBe(true);
  expect(playing.at, "and the picture has moved through the stack")
    .not.toBe(atTheStart.at);

  /* Wrapping. Put the picture on the last plane and let one step happen: it has
     to come back to the first rather than sit on the end. */
  await page.evaluate(() => {
    const depth = window.__panelViewer.theDepthItCanShow();
    window.__panelViewer.setPlane(depth.highUm);
  });
  await rest(600);
  const wrapped = await axis(page, "depth (z)");
  console.log("just after the end of the stack:", JSON.stringify(wrapped));
  const span = await page.evaluate(() => {
    const depth = window.__panelViewer.theDepthItCanShow();
    return { low: depth.lowUm, high: depth.highUm };
  });
  expect(wrapped.at, "it came back to the start rather than stopping on the end")
    .toBeLessThan(span.low + (span.high - span.low) / 2);

  /* And pressing it again stops it. */
  await pressPlay(page, "depth (z)");
  await rest(200);
  const stopped = await axis(page, "depth (z)");
  const restedAt = stopped.at;
  await rest(1000);
  const stillStopped = await axis(page, "depth (z)");
  console.log("after stopping:", JSON.stringify(stillStopped));
  expect(stillStopped.playing, "the button says it has stopped").toBe(false);
  expect(stillStopped.at, "and the picture stayed where it was").toBe(restedAt);
});

test("a run with one moment shows no time slider at all", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  const moments = await page.evaluate(
    () => window.__panelViewer.theMomentsItCanShow?.() ?? null);
  const time = await axis(page, "time (t)");
  console.log("the run holds", JSON.stringify(moments),
    "and the time control is", JSON.stringify(time));

  if (!moments || moments.count < 2) {
    /* Not a timelapse. The control is not drawn at all, rather than drawn and
       unable to move — the second reads as a broken control rather than as an
       honest "there is nothing here". */
    expect(time.drawn, "no time control on a run that is not a timelapse")
      .toBe(false);
    return;
  }

  expect(time.drawn, "a timelapse gets a time control").toBe(true);
  expect(time.reads, "which says which moment of how many")
    .toBe(`moment 1 / ${moments.count}`);

  await pressPlay(page, "time (t)");
  await rest(1200);
  const playing = await axis(page, "time (t)");
  console.log("a second or so into playing the timelapse:", JSON.stringify(playing));
  expect(playing.playing, "the button says it is playing").toBe(true);
  expect(playing.at, "and the picture moved through the moments").not.toBe(time.at);
  await pressPlay(page, "time (t)");
});
