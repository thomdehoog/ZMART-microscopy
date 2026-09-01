import { expect, test } from "@playwright/test";


const reference = process.env.ZMART_VIEWER_REFERENCE_URL;


test("Operator Auto and histogram use a real Smart Viewer 0.2 measurement", async ({ page, request }) => {
  test.skip(!reference, "set ZMART_VIEWER_REFERENCE_URL to the pinned Viewer 0.2 server");
  const configResponse = await request.get(`${reference}/api/config`);
  expect(configResponse.ok()).toBe(true);
  const config = await configResponse.json();
  const spec = config.layers.find((row) => row.kind === "image");
  expect(spec).toBeTruthy();
  const realSource = new URL(spec.sources[0].split("|")[0], reference).toString()
    + `|${spec.sources[0].split("|")[1]}`;
  let realRequests = 0;
  let lastBody = null;

  await page.goto("/?backend=pretend");
  await page.route("**/api/measure", async (route) => {
    lastBody = route.request().postDataJSON();
    realRequests += 1;
    const response = await request.post(`${reference}/api/measure`, {
      data: { ...lastBody, source: realSource },
    });
    await route.fulfill({
      status: response.status(),
      contentType: "application/json",
      body: await response.text(),
    });
  });
  await page.evaluate(async ({ spec }) => {
    document.body.innerHTML = `
      <main class="canvas-body" style="display:grid;grid-template-columns:1fr auto;height:760px">
        <div class="plot-host" style="position:relative;min-width:600px"><div id="panel-host"></div></div>
      </main>`;
    const module = await import("/parts/canvas/viewer-panel.js");
    const source = `${location.origin}/data/reference.ome.zarr/|zarr2:`;
    const acquisition = {
      name: "Viewer 0.2 reference",
      url: source,
      channels: [{
        name: spec.name,
        colour: spec.color,
        window: spec.window,
        range: spec.range,
        histogram: spec.histogram,
        channelIndex: spec.channelIndex,
        sources: [source],
      }],
    };
    const observed = [{
      visible: true, window: { ...spec.window }, weight: 1,
      sources: [{ lower: [0, 0, 0], upper: [1, 64, 64], matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] }],
    }];
    const viewer = {
      measurementBox: () => [[0, 0], [1, 1]],
      setChannel(index, change) {
        if (change.visible !== undefined) observed[index].visible = change.visible;
        if (change.window) observed[index].window = { ...change.window };
        if (change.weight !== undefined) observed[index].weight = change.weight;
      },
      layersForMeasurement: () => observed.map((row) => ({
        ...row, sources: row.sources.map((source) => ({ ...source })),
      })),
    };
    await module.mountViewerPanel(document.querySelector("#panel-host"), {
      viewer, acquisitions: [acquisition], requestedState: module.createViewerPanelState(),
    });
  }, { spec });

  await expect.poll(() => realRequests).toBeGreaterThanOrEqual(1);
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("ready");
  await expect(page.getByLabel(`histogram ${spec.name}`).locator("rect[fill='currentColor']"))
    .toHaveCount(spec.histogram.counts.length);
  expect(lastBody.box).toEqual([[0, 0], [1, 1]]);

  const beforeAuto = realRequests;
  await page.getByLabel(`min ${spec.name}`).evaluate((slider) => {
    slider.value = "1200";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.getByLabel(`auto contrast ${spec.name}`).click();
  await expect.poll(() => realRequests).toBeGreaterThan(beforeAuto);
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("ready");

  const direct = await request.post(`${reference}/api/measure`, {
    data: { source: realSource, channel: spec.channelIndex, box: [[0, 0], [1, 1]], span: null },
  });
  const expected = await direct.json();
  const actual = await page.evaluate(() =>
    window.__viewerPanel.snapshot().channels[0].requested.window);
  expect(actual.low).toBeCloseTo(expected.window.low, 5);
  expect(actual.high).toBeCloseTo(expected.window.high, 5);
});
