import path from "node:path";

import { expect, test } from "@playwright/test";


const reference = process.env.ZMART_VIEWER_REFERENCE_URL;
const evidenceDir = process.env.PANEL_UX_EVIDENCE_DIR;
const gotoStep = (page, name) => page.locator(`.step:has-text("${name}")`).first().click();


function unexpectedBrowserProblems(page) {
  const problems = [];
  const expectedProbes = [];
  page.on("console", (message) => {
    if (message.type() === "error"
        && !message.text().startsWith("Failed to load resource:")) {
      problems.push(`console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`page: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const message = `response: ${response.status()} ${response.url()}`;
    if (response.status() === 404 && response.url().endsWith("/.zarray")) {
      expectedProbes.push(message);
    } else problems.push(message);
  });
  page.on("requestfailed", (request) => {
    const message = `request: ${request.method()} ${request.url()} ${request.failure()?.errorText}`;
    if (request.url().endsWith("/.zarray")) expectedProbes.push(message);
    else problems.push(message);
  });
  return { problems, expectedProbes };
}


async function recordSlot(page, host, name) {
  const bar = page.locator(`#${host} .setting-box.open`);
  const field = bar.locator("input");
  if (await field.count()) await field.fill(name);
  await bar.locator("button.run").click();
  await page.waitForTimeout(650);
}


test("record the real Smart Viewer 0.2 panel reference", async ({ page }) => {
  test.skip(!reference || !evidenceDir, "reference URL and evidence directory are required");
  const browser = unexpectedBrowserProblems(page);
  await page.goto(reference, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.zmartConfig !== undefined, null, { timeout: 30_000 });
  await page.waitForFunction(
    () => window.zmartSourcesWaiting && window.zmartSourcesWaiting() === 0,
    null,
    { timeout: 60_000 },
  );
  const light = page.getByText("light-mode", { exact: true });
  if (await light.count()) await light.click();
  const marker = page.getByLabel("toggle marker-b");
  const name = await marker.getAttribute("aria-label");
  await marker.click();
  await page.getByLabel("logarithmic counts").click();
  await expect(page.locator("[aria-current='true']")).toBeVisible();
  await expect(page.getByLabel("plain counts")).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({
    path: path.join(evidenceDir, "smart-viewer-0.2-reference.png"),
    fullPage: true,
  });
  expect(name).toBeTruthy();
  expect(browser.problems).toEqual([]);
  expect(browser.expectedProbes.some((message) => message.includes("/.zarray"))).toBe(true);
});


test("record the corresponding Smart Operator panel state", async ({ page, request }) => {
  test.setTimeout(120_000);
  test.skip(!reference || !evidenceDir, "reference URL and evidence directory are required");
  const browser = unexpectedBrowserProblems(page);
  const config = await (await request.get(`${reference}/api/config`)).json();
  const imageRows = config.layers.filter((row) => row.kind === "image");
  expect(imageRows.length).toBeGreaterThanOrEqual(3);
  const realSource = (spec) => new URL(spec.sources[0].split("|")[0], reference).toString()
    + `|${spec.sources[0].split("|")[1]}`;
  let realMeasurements = 0;

  await page.goto("/?backend=pretend");
  await page.route("**/api/measure", async (route) => {
    const body = route.request().postDataJSON();
    const chosen = imageRows.find((row) => row.channelIndex === body.channel) ?? imageRows[0];
    realMeasurements += 1;
    const answer = await request.post(`${reference}/api/measure`, {
      data: { ...body, source: realSource(chosen) },
    });
    await route.fulfill({
      status: answer.status(), contentType: "application/json", body: await answer.text(),
    });
  });
  await page.locator('.field input[type="password"]').fill("hunter2");
  await page.locator(".session-foot button.run").click();
  await page.waitForTimeout(2200);
  await gotoStep(page, "Define Carrier");
  await page.locator(".carrier-type[data-type='wellplate']").click();
  await page.locator(".carrier-preset").selectOption({ label: "6-well · Nunc Nunclon" });
  await gotoStep(page, "Define scan area");
  await recordSlot(page, "sf-preset", "overview");
  await page.locator(".sf-apply-grid").click();

  await page.evaluate(async ({ imageRows }) => {
    const module = await import("/parts/canvas/viewer-panel.js");
    const source = (group, spec) =>
      `${location.origin}/data/${group}-${spec.channelIndex}.ome.zarr/|zarr2:`;
    const groupSpecs = [
      ["overview", imageRows],
      ["focussing", [imageRows[1]]],
      ["target", [imageRows[2]]],
    ];
    const acquisitions = groupSpecs.map(([group, specs]) => ({
      name: group,
      url: source(group, specs[0]),
      channels: specs.map((spec) => ({
        name: spec.name,
        colour: spec.color,
        window: spec.window,
        range: spec.range,
        histogram: spec.histogram,
        channelIndex: spec.channelIndex,
        sources: [source(group, spec)],
      })),
    }));
    const rows = acquisitions.flatMap((acquisition) => acquisition.channels.map((channel) => ({
      visible: true, window: { ...channel.window }, weight: 1,
      sources: [{
        lower: [0, 0, 0], upper: [1, 64, 64],
        matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      }],
    })));
    const viewer = {
      measurementBox: () => [[0, 0], [1, 1]],
      setChannel(index, change) {
        if (change.visible !== undefined) rows[index].visible = change.visible;
        if (change.window) rows[index].window = { ...change.window };
        if (change.weight !== undefined) rows[index].weight = change.weight;
      },
      layersForMeasurement: () => rows.map((row) => ({
        ...row, sources: row.sources.map((source) => ({ ...source })),
      })),
    };
    await module.mountViewerPanel(document.querySelector("#picture-host"), {
      viewer, acquisitions, requestedState: module.createViewerPanelState(),
    });
    window.__panelEvidenceMatrices = rows.flatMap((row) =>
      row.sources.map((one) => structuredClone(one.matrix)));
  }, { imageRows });

  const overviewMarker = page.locator('[data-channel-row="marker-b"]').first();
  await overviewMarker.click();
  await expect.poll(() => realMeasurements).toBeGreaterThanOrEqual(1);
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("ready");
  await overviewMarker.getByLabel("toggle marker-b").click();
  await page.getByLabel("logarithmic counts").click();
  await page.getByLabel("toggle group target").click();
  await expect(page.locator("[aria-current='true']")).toContainText("marker-b");
  await expect(page.getByLabel("plain counts")).toHaveAttribute("aria-pressed", "true");
  await expect.poll(async () => page.evaluate(() => {
    const snapshot = window.__viewerPanel.snapshot();
    return {
      groups: Object.fromEntries(Object.entries(snapshot.acquisitions)
        .map(([name, state]) => [name, state.visible])),
      observed: Object.fromEntries(snapshot.channels.map((row) => [
        `${row.acquisition}/${row.name}`, row.observed.visible,
      ])),
    };
  })).toEqual({
    groups: { overview: true, focussing: true, target: false },
    observed: {
      "overview/structure": true,
      "overview/marker-a": true,
      "overview/marker-b": false,
      "focussing/marker-a": true,
      "target/marker-b": false,
    },
  });
  await page.screenshot({
    path: path.join(evidenceDir, "smart-operator-comparable-panel.png"),
    fullPage: true,
  });
  await page.locator('[data-channel-row="marker-a"]').last().click();
  await expect.poll(() => realMeasurements).toBeGreaterThanOrEqual(2);
  await expect.poll(async () =>
    page.evaluate(() => window.__viewerPanel.snapshot().measurement.state)).toBe("ready");
  await page.getByLabel("logarithmic counts").click();
  await expect(page.locator("[aria-current='true']")).toContainText("marker-a");
  await page.screenshot({
    path: path.join(evidenceDir, "smart-operator-focussing-overlay.png"),
    fullPage: true,
  });
  await page.getByLabel("toggle group focussing").click();
  await expect.poll(async () => page.evaluate(() => {
    const snapshot = window.__viewerPanel.snapshot();
    return snapshot.channels
      .filter((row) => row.acquisition === "focussing")
      .every((row) => row.observed.visible === false);
  })).toBe(true);
  await expect.poll(async () => page.evaluate(() => {
    const snapshot = window.__viewerPanel.snapshot();
    return snapshot.channels
      .filter((row) => row.acquisition === "overview")
      .map((row) => row.observed.visible);
  })).toEqual([true, true, false]);
  expect(await page.evaluate(() => window.__viewerPanel.snapshot().channels.flatMap((row) =>
    row.observed.sources.map((one) => one.matrix))))
    .toEqual(await page.evaluate(() => window.__panelEvidenceMatrices));
  await page.screenshot({
    path: path.join(evidenceDir, "smart-operator-overview-only.png"),
    fullPage: true,
  });
  expect(browser.problems).toEqual([]);
});
