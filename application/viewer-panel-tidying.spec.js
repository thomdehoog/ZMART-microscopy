/**
 * Tidying a long list of acquisitions, and keeping hold of a channel.
 *
 * Three things, all of them about a run that changes while somebody is working
 * in it.
 *
 * **Folding.** A run with three acquisitions and several colours each fills the
 * whole bar. Folding one away is about the bar and nothing else — what is drawn
 * must be exactly what it was — and the channel count stays beside the heading,
 * so a folded group still says how much is inside it.
 *
 * **Dimming a whole acquisition.** The heading's opacity slider takes an
 * acquisition down as a whole while the balance of colours inside it stays as
 * the operator set it. It asks nothing of the engine: it multiplies into the
 * weight the panel already sends for each channel.
 *
 * **Keeping hold of a channel.** The panel is built again whenever the run
 * lands a new kind of acquisition, which happens in the middle of a scan. The
 * settings have to stay pointed at the channel the operator was working on, and
 * they are carried by name — a row number stays a perfectly valid number after
 * a rebuild and would quietly refer to a different channel.
 *
 * Point ZV_SOURCE at two served stores, separated by a space.
 */
import { expect, test } from "@playwright/test";

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

const twoStores = (given) => given.split(" ").map((url) => ({
  url, name: url.includes("focussing") ? "focussing" : "overview",
}));

async function openThePanel(page, sources) {
  await page.goto("/?backend=pretend");
  await page.evaluate(async (given) => {
    const host = document.createElement("div");
    host.id = "panel-tidying-host";
    host.style.cssText = "position:fixed;inset:0;z-index:999;background:#202830;";
    document.body.append(host);
    const acquisitions = given.split(" ").map((url) => ({
      url, name: url.includes("focussing") ? "focussing" : "overview",
    }));
    window.__acquisitions = acquisitions;
    const { openerFor } = await import("/parts/canvas/engines.js");
    const openViewer = await openerFor("neuroglancer-under");
    const viewer = await openViewer(host, { acquisitions, background: "#202830" });
    window.__panelViewer = viewer;
    window.__panelHost = host;
    const { mountViewerPanel } = await import("/parts/canvas/viewer-panel.js");
    window.__panelHandle = await mountViewerPanel(host, {
      viewer, acquisitions, css: () => "#202830",
    });
  }, sources);
  await rest(4000);
}

test("an acquisition folds away without changing the picture", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  const before = await page.evaluate(() => ({
    rowsOnScreen: [...window.__viewerPanel.querySelectorAll("button[data-shown]")].length,
    drawn: window.__panelViewer.layersForMeasurement()
      .map((row) => ({ name: row.name, shown: row.visible !== false })),
    countBeside: [...window.__viewerPanel.querySelectorAll("button[data-folded]")]
      .map((one) => one.parentElement.lastElementChild.textContent),
  }));
  console.log("before folding:", JSON.stringify(before));
  expect(before.countBeside.length,
    "there is a fold for each acquisition").toBeGreaterThan(0);
  for (const said of before.countBeside) {
    expect(Number(said), "the heading says how many channels are inside it")
      .toBeGreaterThan(0);
  }

  await page.evaluate(() => {
    window.__viewerPanel.querySelector("button[data-folded]").click();
  });
  await rest(700);

  const after = await page.evaluate(() => ({
    folded: window.__viewerPanel.querySelector("button[data-folded]").dataset.folded,
    stillSaysHowMany: window.__viewerPanel
      .querySelector("button[data-folded]").parentElement.lastElementChild.textContent,
    drawn: window.__panelViewer.layersForMeasurement()
      .map((row) => ({ name: row.name, shown: row.visible !== false })),
  }));
  console.log("after folding:", JSON.stringify(after));
  expect(after.folded, "the group says it is folded").toBe("1");
  expect(after.stillSaysHowMany, "and still says how much is inside it")
    .toBe(before.countBeside[0]);
  /* The whole point: a fold is about the bar, not about what is drawn. */
  expect(after.drawn, "the picture is exactly what it was").toEqual(before.drawn);
});

test("an acquisition's opacity dims all of it without upsetting its balance", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  /* Give the first channel of the first acquisition an opacity of its own, so
     there is a balance inside the group that dimming must not flatten. */
  await page.evaluate(() => {
    const panel = window.__viewerPanel;
    panel.querySelectorAll("[data-shown]")[1].parentElement.parentElement.click();
  });
  await rest(600);
  await page.evaluate(() => {
    const panel = window.__viewerPanel;
    const line = panel.querySelector("[data-control='opacity']");
    const slider = line.querySelector("input[type=range]");
    slider.value = "0.5";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await rest(600);

  const before = await page.evaluate(() =>
    window.__panelViewer.layersForMeasurement().map((row) => row.weight));
  console.log("the weights before dimming the group:", JSON.stringify(before));

  await page.evaluate(() => {
    const panel = window.__viewerPanel;
    const line = panel.querySelector("[data-control='acquisition opacity']");
    const slider = line.querySelector("input[type=range]");
    slider.value = "0.4";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await rest(600);

  const after = await page.evaluate(() =>
    window.__panelViewer.layersForMeasurement().map((row) => row.weight));
  console.log("and after:", JSON.stringify(after));

  /* Every channel of the first acquisition came down by the same share, so the
     balance the operator chose inside it survives. */
  const firstGroup = await page.evaluate(() => {
    const drawn = window.__panelViewer.layersForMeasurement();
    const family = drawn[0].name.split("/")[0];
    return drawn.map((row, at) => (row.name.startsWith(family) ? at : -1))
      .filter((at) => at >= 0);
  });
  for (const at of firstGroup) {
    expect(after[at], `channel ${at} came down to two fifths`)
      .toBeCloseTo(before[at] * 0.4, 5);
  }
});

test("the channel in hand survives the list being built again", async ({ page }) => {
  test.setTimeout(180_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to two served stores, space separated");
  await openThePanel(page, source);

  /* Point the settings at a channel that is not the first one — the first is
     what a panel with no memory falls back to, so choosing it would prove
     nothing. */
  const chosen = await page.evaluate(() => {
    const panel = window.__viewerPanel;
    const eyes = [...panel.querySelectorAll("button[data-shown]")];
    /* The eyes run heading, channels, heading, channels. The last one is a
       channel of the last acquisition, which is as far from the first row as
       this run goes. */
    eyes[eyes.length - 1].parentElement.parentElement.click();
    return window.__panelHandle.theChannelInHand();
  });
  await rest(800);
  console.log("the operator is working on:", JSON.stringify(chosen));
  expect(chosen, "a channel is in hand").toBeTruthy();

  /* And now the panel is built again, exactly as the page does it when the run
     lands a new kind of acquisition mid-scan. */
  const afterRebuild = await page.evaluate(async () => {
    const wasInHand = window.__panelHandle.theChannelInHand();
    window.__panelHandle.destroy();
    const { mountViewerPanel } = await import("/parts/canvas/viewer-panel.js");
    window.__panelHandle = await mountViewerPanel(window.__panelHost, {
      viewer: window.__panelViewer,
      acquisitions: window.__acquisitions,
      css: () => "#202830",
      startOn: wasInHand,
    });
    return window.__panelHandle.theChannelInHand();
  });
  await rest(1500);
  console.log("after the list was built again:", JSON.stringify(afterRebuild));
  expect(afterRebuild, "the same channel is still in hand").toEqual(chosen);

  /* And the settings really act on it: the heading above the sliders names the
     same channel. */
  const named = await page.evaluate(() =>
    [...window.__viewerPanel.querySelectorAll("div")]
      .map((one) => one.textContent)
      .find((text) => text.startsWith(window.__panelHandle.theChannelInHand().acquisition)));
  expect(named, "and the settings say which channel they are acting on")
    .toContain(chosen.name);
});
