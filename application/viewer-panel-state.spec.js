import { expect, test } from "@playwright/test";


async function mountPanel(page) {
  await page.goto("/?backend=pretend");
  await page.evaluate(async () => {
    document.body.innerHTML = `
      <main class="canvas-body" style="display:grid;grid-template-columns:1fr auto;height:820px">
        <div class="plot-host" style="position:relative;min-width:600px"><div id="panel-host"></div></div>
      </main>`;
    const module = await import("/parts/canvas/viewer-panel.js");
    const source = (group, channel, position = 0) =>
      `${location.origin}/data/${group}-${channel}-${position}.ome.zarr/|zarr3:`;
    const acquisitions = ["overview", "focussing", "targets"].map((group, groupAt) => ({
      name: group,
      url: source(group, 0),
      channels: [0, 1].map((channel) => ({
        name: `${group} ${channel}`,
        colour: groupAt === 0 ? [0, 1, channel ? 1 : 0.4]
          : groupAt === 1 ? [1, 0.2, 1]
            : [1, 0.75, 0.1],
        window: { low: 100 + channel * 10, high: 2000 + channel * 100 },
        channelIndex: channel,
        sources: [source(group, channel)],
      })),
    }));
    const rows = acquisitions.flatMap((acquisition) => acquisition.channels.map((channel) => ({
      name: channel.name,
      visible: true,
      window: { ...channel.window },
      weight: 1,
      sources: channel.sources.map((url, at) => ({
        url,
        lower: [0, 0, 0],
        upper: [1, 100, 100],
        /* Placed like a real position store: voxel size on the diagonal,
           the stage corner in the last row. */
        matrix: [1, 0, 0, 0, 0, 1.3, 0, 0, 0, 0, 1.3, 0, at, 28500, 23500 + at * 676.5, 1],
      })),
    })));
    const calls = [];
    const viewer = {
      setChannel(index, change) {
        calls.push({ index, change: structuredClone(change) });
        const row = rows[index];
        if (change.visible !== undefined) row.visible = change.visible;
        if (change.window) row.window = { ...change.window };
        if (change.weight !== undefined) row.weight = change.weight;
      },
      layersForMeasurement() {
        return rows.map((row) => ({
          name: row.name,
          visible: row.visible,
          window: row.window,
          weight: row.weight,
          sources: row.sources.map((one) => ({ ...one })),
        }));
      },
    };
    const state = module.createViewerPanelState();
    const changes = [];
    const handle = await module.mountViewerPanel(document.querySelector("#panel-host"), {
      viewer, acquisitions, requestedState: state,
      changed: () => changes.push(performance.now()),
    });
    window.__panelFixture = { module, viewer, acquisitions, rows, calls, changes, state, handle };
  });
  await expect(page.locator(".viewer-panel")).toBeVisible();
  await expect(page.locator("[data-channel-row]")).toHaveCount(6);
}


const snapshot = (page) => page.evaluate(() => window.__viewerPanel.snapshot());


test("acquisition eyes preserve channel requests for overview, focussing, and target", async ({ page }) => {
  await mountPanel(page);

  await page.getByLabel("toggle targets 1").first().click();
  for (const group of ["overview", "focussing", "targets"]) {
    const before = await snapshot(page);
    const matrices = before.channels.flatMap((row) =>
      (row.observed?.sources ?? []).map((source) => source.matrix));
    await page.getByLabel(`toggle group ${group}`).click();
    await expect.poll(async () => (await snapshot(page)).channels
      .filter((row) => row.acquisition === group)
      .every((row) => row.observed?.visible === false)).toBe(true);
    await page.getByLabel(`toggle group ${group}`).click();
    await expect.poll(async () => {
      const rows = (await snapshot(page)).channels.filter((row) => row.acquisition === group);
      return rows.map((row) => row.observed?.visible);
    }).toEqual(group === "targets" ? [true, false] : [true, true]);
    const after = await snapshot(page);
    expect(after.channels.flatMap((row) =>
      (row.observed?.sources ?? []).map((source) => source.matrix))).toEqual(matrices);
  }

  const target = (await snapshot(page)).channels.filter((row) => row.acquisition === "targets");
  expect(target.map((row) => row.requested.visible)).toEqual([true, false]);
  expect(target.map((row) => row.requested.effectiveVisible)).toEqual([true, false]);
});


test("selection, colour, opacity, window, Log, and collapse persist through growth and remount", async ({ page }) => {
  await mountPanel(page);
  await page.locator('[data-channel-row="focussing 1"]').click();
  await page.getByLabel("colour focussing 1").first().click();
  await page.getByLabel("red for focussing 1").click();
  await page.getByLabel("logarithmic counts").click();
  await page.getByLabel("collapse overview").click();

  await page.getByLabel("opacity focussing 1").evaluate((slider) => {
    slider.value = "0.37";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.getByLabel("min focussing 1").evaluate((slider) => {
    slider.value = "333";
    slider.dispatchEvent(new Event("input", { bubbles: true }));
  });

  await page.evaluate(() => { window.__panelFixture.panelBefore = window.__viewerPanel; });
  const matricesBefore = (await snapshot(page)).channels.flatMap((row) =>
    (row.observed?.sources ?? []).map((source) => source.matrix));
  await page.evaluate(async () => {
    const fixture = window.__panelFixture;
    const next = structuredClone(fixture.acquisitions);
    next.forEach((acquisition) => acquisition.channels.forEach((channel) => {
      const url = `${channel.sources[0].replace(".ome.zarr", "-grown.ome.zarr")}`;
      channel.sources.push(url);
    }));
    fixture.rows.forEach((row) => row.sources.push({
      url: `${row.sources[0].url.replace(".ome.zarr", "-grown.ome.zarr")}`,
      lower: [0, 0, 0], upper: [1, 100, 100],
      matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1],
    }));
    fixture.acquisitions = next;
    await fixture.handle.sourcesChanged(next);
  });
  expect(await page.evaluate(() =>
    window.__viewerPanel === window.__panelFixture.panelBefore)).toBe(true);

  await page.evaluate(async () => {
    const fixture = window.__panelFixture;
    fixture.handle.destroy();
    fixture.handle = await fixture.module.mountViewerPanel(
      document.querySelector("#panel-host"),
      { viewer: fixture.viewer, acquisitions: fixture.acquisitions, requestedState: fixture.state },
    );
  });
  await expect(page.locator('[data-channel-row="focussing 1"]')).toHaveAttribute("aria-current", "true");
  await expect(page.getByLabel("expand overview")).toBeVisible();
  await expect(page.getByLabel("plain counts")).toHaveAttribute("aria-pressed", "true");

  const after = await snapshot(page);
  const selected = after.channels.find((row) => row.key === after.selectedKey);
  expect(selected.requested.color).toBe("rgb(255,38,38)");
  expect(selected.requested.opacity).toBeCloseTo(0.37);
  expect(selected.requested.window.low).toBe(333);
  expect(after.channels.every((row) => row.observed.sources.length === 2)).toBe(true);
  expect(after.channels.flatMap((row) => row.observed.sources.slice(0, 1).map((source) => source.matrix)))
    .toEqual(matricesBefore);
});


test("acquisition grey mode survives a remount and restores the original colours", async ({ page }) => {
  await mountPanel(page);
  const original = (await snapshot(page)).channels
    .filter((row) => row.acquisition === "overview")
    .map((row) => row.requested.colour);
  const toggle = page.locator('[data-acquisition-grey="overview"]');

  await expect(toggle).toHaveText("colour");
  await toggle.click();
  await expect(toggle).toHaveText("grey");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => page.evaluate(() => window.__panelFixture.changes.length)).toBe(1);
  expect((await snapshot(page)).channels
    .filter((row) => row.acquisition === "overview")
    .every((row) => row.requested.colour[0] === row.requested.colour[1]
      && row.requested.colour[1] === row.requested.colour[2])).toBe(true);

  await page.evaluate(async () => {
    const fixture = window.__panelFixture;
    fixture.handle.destroy();
    fixture.handle = await fixture.module.mountViewerPanel(
      document.querySelector("#panel-host"),
      { viewer: fixture.viewer, acquisitions: fixture.acquisitions, requestedState: fixture.state },
    );
  });

  const restoredToggle = page.locator('[data-acquisition-grey="overview"]');
  await expect(restoredToggle).toHaveText("grey");
  await expect(restoredToggle).toHaveAttribute("aria-pressed", "true");
  await restoredToggle.click();
  await expect(restoredToggle).toHaveText("colour");
  expect((await snapshot(page)).channels
    .filter((row) => row.acquisition === "overview")
    .map((row) => row.requested.colour)).toEqual(original);
});


test("an external engine mutation is recorded and reconciled without becoming UI state", async ({ page }) => {
  await mountPanel(page);
  const before = await snapshot(page);
  const first = before.channels[0];
  await page.evaluate(() => { window.__panelFixture.rows[0].visible = false; });

  await expect.poll(async () => (await snapshot(page)).lastMismatch?.rows?.[0]?.key)
    .toBe(first.key);
  await expect.poll(async () => (await snapshot(page)).channels[0].observed.visible).toBe(true);
  const after = await snapshot(page);
  expect(after.channels[0].requested.visible).toBe(true);
  expect(after.channels[0].observed.visible).toBe(true);
  expect(after.channels[0].observed.sources[0].matrix).toEqual(first.observed.sources[0].matrix);
});
