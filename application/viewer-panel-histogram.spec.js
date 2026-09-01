import { expect, test } from "@playwright/test";


const histogram = {
  low: 0,
  high: 4095,
  counts: Array.from({ length: 64 }, (_, at) =>
    at < 4 ? 2000 - at * 300 : Math.max(1, Math.round(900 / (at + 1)))),
  autoWindow: { low: 240, high: 1800 },
};


async function mountHistogram(page, answer = null) {
  await page.goto("/?backend=pretend");
  await page.evaluate(({ histogram, answer }) => {
    document.body.innerHTML = `
      <main class="canvas-body" style="display:grid;grid-template-columns:1fr auto;height:760px">
        <div class="plot-host" style="position:relative;min-width:600px"><div id="panel-host"></div></div>
      </main>`;
    window.__measurementAnswer = answer ?? { histogram, window: histogram.autoWindow };
  }, { histogram, answer });
  await page.route("**/api/measure", async (route) => {
    const reply = await page.evaluate(() => window.__measurementAnswer);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(reply) });
  });
  await page.evaluate(async (histogram) => {
    const module = await import("/parts/canvas/viewer-panel.js");
    const acquisition = {
      name: "overview",
      url: `${location.origin}/data/overview.ome.zarr/|zarr3:`,
      channels: [{
        name: "overview 0",
        colour: [0, 1, 0.4],
        window: { low: 200, high: 2000 },
        range: { low: 0, high: 4095 },
        histogram,
        channelIndex: 0,
        sources: [`${location.origin}/data/overview.ome.zarr/|zarr3:`],
      }],
    };
    const observed = [{
      visible: true, window: { low: 200, high: 2000 }, weight: 1,
      sources: [{ lower: [0, 0, 0], upper: [1, 64, 64], matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] }],
    }];
    const viewer = {
      measurementBox: () => [[0.2, 0.3], [0.8, 0.9]],
      setChannel(index, change) {
        if (change.visible !== undefined) observed[index].visible = change.visible;
        if (change.window) observed[index].window = { ...change.window };
        if (change.weight !== undefined) observed[index].weight = change.weight;
      },
      layersForMeasurement: () => observed.map((row) => ({
        ...row, sources: row.sources.map((source) => ({ ...source })),
      })),
    };
    const state = module.createViewerPanelState();
    const handle = await module.mountViewerPanel(document.querySelector("#panel-host"), {
      viewer, acquisitions: [acquisition], requestedState: state,
    });
    window.__histogramFixture = { module, viewer, acquisition, observed, state, handle };
  }, histogram);
  await expect(page.getByLabel("histogram overview 0")).toBeVisible();
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("ready");
}


async function windowAndAxis(page) {
  return page.evaluate(() => {
    const state = window.__viewerPanel.snapshot().channels[0].requested;
    return { window: state.window, axis: state.axis };
  });
}


test("histogram edge drag, background pan, wheel zoom, reset, and pointer feedback", async ({ page }) => {
  await mountHistogram(page);
  const plot = page.getByLabel("histogram overview 0");
  const face = await plot.boundingBox();
  const axisFrom = page.getByLabel("axis from overview 0");
  const axisTo = page.getByLabel("axis to overview 0");
  const axis = {
    low: Number(await axisFrom.inputValue()),
    high: Number(await axisTo.inputValue()),
  };
  const before = await windowAndAxis(page);
  const xOf = (value) => face.x + face.width * ((value - axis.low) / (axis.high - axis.low));
  const y = face.y + face.height / 2;

  await page.mouse.move(xOf(before.window.low), y);
  await page.mouse.down();
  await page.mouse.move(xOf(before.window.low + 240), y, { steps: 5 });
  await page.mouse.up();
  const dragged = await windowAndAxis(page);
  expect(dragged.window.low).toBeGreaterThan(before.window.low);
  expect(dragged.window.high).toBeCloseTo(before.window.high);

  const widthBeforePan = Number(await axisTo.inputValue()) - Number(await axisFrom.inputValue());
  await page.mouse.move(face.x + face.width * 0.5, y);
  await page.mouse.down();
  await page.mouse.move(face.x + face.width * 0.62, y, { steps: 4 });
  await page.mouse.up();
  const panned = {
    low: Number(await axisFrom.inputValue()),
    high: Number(await axisTo.inputValue()),
  };
  expect(panned.high - panned.low).toBeCloseTo(widthBeforePan, 0);
  expect((await windowAndAxis(page)).window).toEqual(dragged.window);

  await page.mouse.move(face.x + face.width * 0.5, y);
  await page.mouse.wheel(0, -350);
  const zoomedWidth = Number(await axisTo.inputValue()) - Number(await axisFrom.inputValue());
  expect(zoomedWidth).toBeLessThan(widthBeforePan);

  await page.mouse.move(face.x + face.width * 0.7, y);
  await expect(page.getByLabel("histogram value")).toContainText("value");
  await expect(page.getByLabel("histogram value")).toContainText("pixels");

  const windowBeforeReset = (await windowAndAxis(page)).window;
  await plot.dblclick({ position: { x: face.width * 0.55, y: face.height / 2 } });
  expect((await windowAndAxis(page)).axis).toBeNull();
  expect((await windowAndAxis(page)).window).toEqual(windowBeforeReset);
});


test("typed axis/window/opacity values and Log match Viewer behavior", async ({ page }) => {
  await mountHistogram(page);
  for (const [label, value] of [
    ["axis from overview 0", "100"],
    ["axis to overview 0", "2600"],
    ["min value overview 0", "350"],
    ["max value overview 0", "1750"],
    ["opacity value overview 0", "42%"],
  ]) {
    const input = page.getByLabel(label);
    await input.fill(value);
    await input.press("Enter");
  }
  const state = (await windowAndAxis(page));
  expect(state.axis.low).toBe(100);
  expect(state.axis.high).toBe(2600);
  expect(state.window).toEqual({ low: 350, high: 1750 });
  expect(await page.getByLabel("opacity value overview 0").inputValue()).toBe("42%");

  const bars = async () => plotBars(page);
  const plain = await bars();
  await page.getByLabel("logarithmic counts").click();
  const logged = await bars();
  expect(logged.map((bar) => bar.x)).toEqual(plain.map((bar) => bar.x));
  expect(logged.map((bar) => bar.width)).toEqual(plain.map((bar) => bar.width));
  expect(logged.map((bar) => bar.height)).not.toEqual(plain.map((bar) => bar.height));
  await expect(page.getByLabel("plain counts")).toHaveAttribute("aria-pressed", "true");
});


async function plotBars(page) {
  return page.getByLabel("histogram overview 0").locator("rect[fill='currentColor']")
    .evaluateAll((bars) => bars.map((bar) => ({
      x: Number(bar.getAttribute("x")),
      width: Number(bar.getAttribute("width")),
      height: Number(bar.getAttribute("height")),
    })));
}


test("a delayed Auto cannot overwrite a newer manual window", async ({ page }) => {
  await page.goto("/?backend=pretend");
  let calls = 0;
  await page.route("**/api/measure", async (route) => {
    calls += 1;
    if (calls > 1) await new Promise((resolve) => setTimeout(resolve, 500));
    const body = calls > 1
      ? { histogram, window: { low: 900, high: 1500 } }
      : { histogram, window: { low: 240, high: 1800 } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) })
      .catch(() => {});
  });
  await mountWithoutRoute(page);
  await expect.poll(() => calls).toBeGreaterThanOrEqual(1);
  await page.getByLabel("auto contrast overview 0").click();
  await page.getByLabel("min overview 0").evaluate((slider) => {
    slider.value = "650";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForTimeout(650);
  expect((await windowAndAxis(page)).window).toEqual({ low: 650, high: 2000 });
});


test("a newer Auto cancels an older response, and a failure keeps the window visible", async ({ page }) => {
  await page.goto("/?backend=pretend");
  let calls = 0;
  let failNext = false;
  await page.route("**/api/measure", async (route) => {
    calls += 1;
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 503, body: "unavailable" });
      return;
    }
    if (calls === 2) await new Promise((resolve) => setTimeout(resolve, 450));
    const window = calls === 2 ? { low: 500, high: 1200 }
      : calls >= 3 ? { low: 700, high: 1700 }
        : { low: 240, high: 1800 };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ histogram, window }),
    }).catch(() => {});
  });
  await mountWithoutRoute(page);
  await expect.poll(() => calls).toBeGreaterThanOrEqual(1);
  await page.getByLabel("auto contrast overview 0").click();
  await page.waitForTimeout(40);
  await page.getByLabel("auto contrast overview 0").click();
  await expect.poll(async () => (await windowAndAxis(page)).window).toEqual({ low: 700, high: 1700 });

  const beforeFailure = (await windowAndAxis(page)).window;
  failNext = true;
  await page.getByLabel("auto contrast overview 0").click();
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("failed");
  expect((await windowAndAxis(page)).window).toEqual(beforeFailure);
  await expect(page.locator("[data-measurement-state='failed']"))
    .toContainText("Measurement failed");
});


async function mountWithoutRoute(page) {
  await page.evaluate((histogram) => {
    document.body.innerHTML = `
      <main class="canvas-body" style="display:grid;grid-template-columns:1fr auto;height:760px">
        <div class="plot-host" style="position:relative;min-width:600px"><div id="panel-host"></div></div>
      </main>`;
    window.__histogramForMount = histogram;
  }, histogram);
  await page.evaluate(async () => {
    const module = await import("/parts/canvas/viewer-panel.js");
    const histogram = window.__histogramForMount;
    const acquisition = {
      name: "overview",
      url: `${location.origin}/data/overview.ome.zarr/|zarr3:`,
      channels: [{
        name: "overview 0", colour: [0, 1, 0.4],
        window: { low: 200, high: 2000 }, range: { low: 0, high: 4095 }, histogram,
        channelIndex: 0, sources: [`${location.origin}/data/overview.ome.zarr/|zarr3:`],
      }],
    };
    const observed = [{
      visible: true, window: { low: 200, high: 2000 }, weight: 1,
      sources: [{ lower: [0, 0, 0], upper: [1, 64, 64], matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] }],
    }];
    const viewer = {
      measurementBox: () => [[0.2, 0.3], [0.8, 0.9]],
      setChannel(index, change) {
        if (change.visible !== undefined) observed[index].visible = change.visible;
        if (change.window) observed[index].window = { ...change.window };
        if (change.weight !== undefined) observed[index].weight = change.weight;
      },
      layersForMeasurement: () => observed.map((row) => ({
        ...row, sources: row.sources.map((source) => ({ ...source })),
      })),
    };
    const state = module.createViewerPanelState();
    const handle = await module.mountViewerPanel(document.querySelector("#panel-host"), {
      viewer, acquisitions: [acquisition], requestedState: state,
    });
    window.__histogramFixture = { module, viewer, acquisition, observed, state, handle };
  });
  await expect(page.getByLabel("histogram overview 0")).toBeVisible();
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("ready");
}
