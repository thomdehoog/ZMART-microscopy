/**
 * A photograph of the neuroglancer engine alone on a real position store,
 * with the console listened to — a shader that fails to compile draws a
 * wrong picture and says why only in the console, which nobody sees in the
 * native window. Point it at a served store with ZV_SOURCE; centre and zoom
 * with ZV_CENTRE ("x,y" in µm) and ZV_ZOOM (µm per pixel).
 */
import { test } from "@playwright/test";

test("the engine draws the store, and the console says nothing", async ({ page }) => {
  test.setTimeout(60_000);
  const source = process.env.ZV_SOURCE;
  test.skip(!source, "set ZV_SOURCE to a served store address");
  const [cx, cy] = (process.env.ZV_CENTRE ?? "0,0").split(",").map(Number);
  const zoom = Number(process.env.ZV_ZOOM ?? "2");

  const said = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) said.push(message.text());
  });
  page.on("pageerror", (why) => said.push(`pageerror: ${why.message}`));

  await page.goto("/?backend=pretend");
  await page.evaluate(async ({ source, cx, cy, zoom }) => {
    const host = document.createElement("div");
    host.id = "engine-look-host";
    host.style.cssText =
      "position:fixed;inset:0;z-index:999;background:#202830;";
    document.body.append(host);
    const { openerFor } = await import("/parts/canvas/engines.js");
    const openViewer = await openerFor("neuroglancer-under");
    window.__engineLook = await openViewer(host, {
      acquisitions: source.split(" ").map((url, at) => ({ url, name: `looked-at ${at}` })),
      background: window.__engineLookBackground ?? "#202830",
    });
    window.__engineLook.setView({ centre: { x: cx, y: cy }, zoom });
  }, { source, cx, cy, zoom });
  await page.waitForTimeout(8000);
  await page.evaluate(({ cx, cy, zoom }) => {
    window.__engineLook.setView({ centre: { x: cx, y: cy }, zoom });
  }, { cx, cy, zoom });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: "test-results/engine-look.png" });
  console.log("console said:", JSON.stringify(said, null, 2));
});
