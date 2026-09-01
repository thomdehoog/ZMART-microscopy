/**
 * The eyes in the viewer panel, and whether they do what they say.
 *
 * There are two of them and they answer different questions. The eye beside a
 * channel says whether that one colour is being drawn. The eye beside an
 * acquisition's heading says whether anything of that acquisition is on
 * screen at all — which is the one an operator reaches for when they want to
 * put the focussing away and look at the overview.
 *
 * Both are checked here against the picture itself rather than against the
 * panel's own opinion: after every press, the drawing engine is asked which
 * of its rows it is really drawing, and the answer has to agree with what the
 * eye is showing. That pairing is the whole point. The panel used to draw
 * every eye open when it built a row and change one only when that eye's own
 * button was pressed, so a channel turned off any other way kept an open eye
 * and the panel quietly said the opposite of the truth.
 *
 * Point ZV_SOURCE at two served stores, separated by a space.
 */
import { expect, test } from "@playwright/test";

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

/** What the panel is showing, and what the picture is really drawing. */
async function whatTheEyesSay(page) {
  return page.evaluate(() => {
    const panel = window.__viewerPanel ?? document.body;
    const eyes = [...panel.querySelectorAll("button[data-shown]")];
    return {
      /* In the order they stand on screen: an acquisition's heading, then
         its channels, then the next acquisition. */
      panelSays: eyes.map((eye) => ({
        of: eye.title.replace(/^(Hide|Show) this /, ""),
        shown: eye.dataset.shown === "1",
        /* Which row this eye belongs to, taken from the eye itself rather than
           counted. The eyes stand in the order heading, channels, heading,
           channels, so counting to reach a particular channel only works while
           every acquisition happens to have the same number of colours. */
        row: eye.dataset.row === undefined ? null : Number(eye.dataset.row),
      })),
      pictureDraws: window.__panelViewer.layersForMeasurement()
        .map((row) => ({ name: row.name, shown: row.visible !== false })),
    };
  });
}

/** Press the nth eye on the panel. */
async function press(page, nth) {
  await page.evaluate((at) => {
    const panel = window.__viewerPanel ?? document.body;
    [...panel.querySelectorAll("button[data-shown]")][at].click();
  }, nth);
  await rest(700);
}

test("the eyes hide what they say they hide", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");

  await page.goto("/?backend=pretend");
  await page.evaluate(async (sources) => {
    const host = document.createElement("div");
    host.id = "panel-eyes-host";
    host.style.cssText = "position:fixed;inset:0;z-index:999;background:#202830;";
    document.body.append(host);
    const { openerFor } = await import("/parts/canvas/engines.js");
    const openViewer = await openerFor("neuroglancer-under");
    const viewer = await openViewer(host, {
      acquisitions: sources.split(" ").map((url) => ({
        url, name: url.includes("focussing") ? "focussing" : "overview",
      })),
      background: "#202830",
    });
    window.__panelViewer = viewer;
    const { mountViewerPanel } = await import("/parts/canvas/viewer-panel.js");
    window.__panelHandle = await mountViewerPanel(host, {
      viewer,
      acquisitions: sources.split(" ").map((url) => ({
        url, name: url.includes("focussing") ? "focussing" : "overview",
      })),
      css: () => "#202830",
    });
  }, source);
  await rest(4000);

  const atTheStart = await whatTheEyesSay(page);
  console.log("at the start:", JSON.stringify(atTheStart));
  expect(atTheStart.panelSays.length,
    "there is an eye for each acquisition and each of its channels")
    .toBe(atTheStart.pictureDraws.length + 2);
  for (const eye of atTheStart.panelSays) {
    expect(eye.shown, "every eye opens on a picture that is being drawn").toBe(true);
  }

  /* The first eye is the first acquisition's heading. Pressing it must put
     that whole acquisition away — every one of its channels — and nothing
     else. */
  await press(page, 0);
  const acquisitionAway = await whatTheEyesSay(page);
  console.log("with the first acquisition hidden:", JSON.stringify(acquisitionAway));
  const first = acquisitionAway.pictureDraws[0].name.split("/")[0];
  for (const row of acquisitionAway.pictureDraws) {
    expect(row.shown, `${row.name} while its acquisition is hidden`)
      .toBe(!row.name.startsWith(first));
  }
  expect(acquisitionAway.panelSays[0].shown,
    "the acquisition's own eye is closed while it is hidden").toBe(false);

  /* And pressing it again brings the whole acquisition back. */
  await press(page, 0);
  const acquisitionBack = await whatTheEyesSay(page);
  for (const row of acquisitionBack.pictureDraws) {
    expect(row.shown, `${row.name} once the acquisition is shown again`).toBe(true);
  }
  expect(acquisitionBack.panelSays[0].shown, "its eye is open again").toBe(true);

  /* The second eye is the first channel of that acquisition. Pressing it must
     put away that one colour and leave every other alone. */
  await press(page, 1);
  const oneChannelAway = await whatTheEyesSay(page);
  console.log("with one channel hidden:", JSON.stringify(oneChannelAway));
  expect(oneChannelAway.pictureDraws[0].shown, "the channel pressed is hidden").toBe(false);
  for (const row of oneChannelAway.pictureDraws.slice(1)) {
    expect(row.shown, `${row.name} is untouched by another channel's eye`).toBe(true);
  }
  expect(oneChannelAway.panelSays[1].shown, "that channel's eye is closed").toBe(false);

  /* And an eye follows the picture even when the picture is changed from
     somewhere else entirely, which is what `refresh` is for. */
  await page.evaluate(() => {
    window.__panelViewer.setChannel(1, { visible: false });
    window.__panelHandle.refresh();
  });
  await rest(700);
  const afterRefresh = await whatTheEyesSay(page);
  console.log("after a change made behind the panel's back:", JSON.stringify(afterRefresh));
  expect(afterRefresh.pictureDraws[1].shown, "the row changed from elsewhere is hidden")
    .toBe(false);
  expect(afterRefresh.panelSays.find((eye) => eye.row === 1).shown,
    "and its eye followed").toBe(false);
});
