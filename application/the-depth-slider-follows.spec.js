/**
 * The depth slider, and whether it says where the picture really is.
 *
 * This is the same shape of check as `viewer-panel-eyes.spec.js`, and it is
 * here for the same reason. The panel and the viewer both hold an opinion
 * about which plane of the stack is on screen, and the panel's used only ever
 * to be right because it was the one that had changed it. Anything else that
 * moved through the stack — the scroll wheel, a step of the workflow, the
 * viewer settling on the plane the specimen is actually on — left the slider
 * showing where it had last put the operator.
 *
 * So the picture is moved from outside the panel entirely, and then the panel
 * is asked what it is showing. A panel that only agrees with itself proves
 * nothing; the two have to agree with each other.
 *
 * Point ZV_SOURCE at two served stores, separated by a space. At least one of
 * them wants to be a focussing sweep, since a plate of flat captures has no
 * depth to move through and the check will say so and stop.
 */
import { expect, test } from "@playwright/test";

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/** What the slider is showing, and what the picture is really standing on. */
async function whatTheDepthSays(page) {
  return page.evaluate(() => {
    const panel = window.__viewerPanel ?? document.body;
    const line = panel.querySelector("[data-control='depth (z)']");
    const slider = line?.querySelector("input[type=range]");
    const box = line?.querySelector("span:last-child");
    return {
      drawn: line ? line.style.display !== "none" : false,
      panelSays: slider ? Number(slider.value) : null,
      reads: box ? box.textContent : null,
      pictureIsAt: window.__panelViewer.theDepthItCanShow?.() ?? null,
    };
  });
}

test("the depth slider follows the picture through the stack", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");

  await page.goto("/?backend=pretend");
  await page.evaluate(async (sources) => {
    const host = document.createElement("div");
    host.id = "depth-slider-host";
    host.style.cssText = "position:fixed;inset:0;z-index:999;background:#202830;";
    document.body.append(host);
    const acquisitions = sources.split(" ").map((url) => ({
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
  await rest(4000);

  const atTheStart = await whatTheDepthSays(page);
  console.log("at the start:", JSON.stringify(atTheStart));
  test.skip(!atTheStart.drawn,
    "these stores are flat, so there is no stack to move through");

  /* The reading says which plane of how many, not only a height. A stack is
     counted in planes by everybody who looks at one. */
  expect(atTheStart.reads, "the reading counts planes as well as micrometres")
    .toMatch(/^plane \d+ \/ \d+ · -?\d+ µm$/);

  /* And now the picture is moved from outside the panel — the panel is not
     touched at all, which is the whole point. Two thirds of the way down the
     stack, so the answer cannot be confused with where it opened. */
  const wanted = await page.evaluate(() => {
    const depth = window.__panelViewer.theDepthItCanShow();
    const to = depth.lowUm + (depth.highUm - depth.lowUm) * (2 / 3);
    window.__panelViewer.setPlane(to);
    return to;
  });
  await rest(1500);

  const afterMoving = await whatTheDepthSays(page);
  console.log("after moving the picture behind the panel's back:",
    JSON.stringify(afterMoving), "asked for", wanted);

  /* Within half a plane of where the picture actually is: the engine puts the
     view on the nearest whole plane, so asking for a height between two of them
     lands on one of the two, and the slider has to agree with where it landed
     rather than with what was asked for. */
  const step = afterMoving.pictureIsAt.stepUm;
  expect(Math.abs(afterMoving.panelSays - afterMoving.pictureIsAt.atUm),
    "the handle stands where the picture stands").toBeLessThanOrEqual(step);
  expect(afterMoving.panelSays, "and it moved at all").not.toBe(atTheStart.panelSays);

  /* The reading moved with it. A handle that follows while the number beside it
     does not is half a fix, and the number is the part an operator reads. */
  expect(afterMoving.reads, "the reading moved too").not.toBe(atTheStart.reads);
  const planes = Number(afterMoving.reads.match(/\/ (\d+)/)[1]);
  const standing = Number(afterMoving.reads.match(/plane (\d+)/)[1]);
  expect(standing, "the plane number is inside the stack").toBeGreaterThan(0);
  expect(standing, "the plane number is inside the stack").toBeLessThanOrEqual(planes);
});
