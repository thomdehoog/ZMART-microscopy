import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../testing/python.ts";
import { readPng, type Pixels } from "../../testing/pixels.ts";
import type { ThePicture } from "../../types.ts";

declare global {
  interface Window {
    /** Test-only: the run watcher the spec opens, so it can close its picture afterwards. */
    failureWatch?: { thePicture: ThePicture };
  }
}

for (const bake of [false, true]) test(`publication failure preserves valid pixels, bake ${bake}`, async ({ page }, info) => {
  test.setTimeout(60_000);
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "publication-failure-"));
  const fixture = fileURLToPath(new URL("./fixtures/serve-publication-failure.py", import.meta.url));
  const child = spawn(pythonForTheBridge(), [fixture, folder, String(bake)], { windowsHide: true });
  let logs = "";
  child.stderr.on("data", data => { logs += data; });
  const origin = await new Promise<string>((resolve, reject) => {
    let output = "";
    child.stdout.on("data", data => {
      output += data;
      if (output.includes("\n")) resolve(JSON.parse(output.split("\n")[0]).url);
    });
    child.on("exit", code => reject(new Error(`fixture exited ${code}: ${logs}`)));
    child.on("error", reject);
  });
  const chunks: string[] = [], errors: string[] = [];
  page.on("request", request => { if (/\/data\/.*\/c\//.test(request.url())) chunks.push(request.url()); });
  page.on("pageerror", error => errors.push(String(error)));
  try {
    await page.goto(`/?backend=pretend&bridge=${encodeURIComponent(origin)}`);
    await page.evaluate(async () => {
      const below = document.createElement("div");
      below.style.cssText = "position:fixed;left:0;top:0;width:640px;height:320px;z-index:999;background:magenta";
      below.innerHTML = '<div id="failure-host" style="width:100%;height:100%"></div><div id="failure-note" role="status"></div>';
      document.body.append(below);
      const { backend } = await import("/@zmart-workflows/target_acquisition/backend/live.ts");
      const { showPublicationStatus } = await import("/@zmart-workflows/target_acquisition/canvas/publication-note.ts");
      const { watchTheRun } = await import("/@zmart-workflows/target_acquisition/steps/scan_the_overview/watching-the-run.ts");
      window.failureWatch = watchTheRun({
        pictureHost: document.getElementById("failure-host")!, connected: () => true,
        viewerSources: () => backend.viewerSources(status => showPublicationStatus(document.getElementById("failure-note")!, status)),
        css: () => "#ffffff", view: () => ({ centre: { x: 80, y: 16 }, zoom: 0.25 }),
        carrierOriginUm: () => [0, 0],
      });
    });
    const photo = async (name?: string) => readPng(await page.locator("#failure-host").screenshot(name ? { path: info.outputPath(name) } : {}));
    const pixel = (shot: Pixels, x: number) => Array.from(shot.data.slice((160 * shot.width + x) * shot.channels,
      (160 * shot.width + x) * shot.channels + 3));
    await expect.poll(async () => pixel(await photo(), 64)).toEqual([120, 120, 120]);
    expect((await page.request.post(`${origin}/fail`)).ok()).toBe(true);
    await expect.poll(async () => pixel(await photo(), 448)).toEqual([240, 240, 240]);
    const failed = await photo("partial-publication.png");
    expect(pixel(failed, 64)).toEqual([120, 120, 120]);
    expect(pixel(failed, 224)).toEqual([255, 0, 255]);
    await expect(page.locator("#failure-note")).toContainText("overview: 1/2 stores available (blocked)");
    chunks.length = 0;
    await page.waitForTimeout(3200); // At least two normal 1.5-second polls.
    expect(chunks).toEqual([]);
    expect((await page.request.post(`${origin}/recover`)).ok()).toBe(true);
    // The claim is that the pixels come back, not how fast: a machine without a
    // graphics card draws in software, and there the redraw takes far longer.
    await expect.poll(async () => pixel(await photo(), 224), { timeout: 30_000 }).toEqual([180, 180, 180]);
    const recovered = await photo("recovered-publication.png");
    expect(pixel(recovered, 64)).toEqual([120, 120, 120]);
    expect(pixel(recovered, 448)).toEqual([240, 240, 240]);
    await expect(page.locator("#failure-note")).toBeHidden();
    await page.waitForTimeout(1800);
    chunks.length = 0;
    await page.waitForTimeout(3200);
    expect(chunks).toEqual([]);
    expect(errors).toEqual([]);
  } finally {
    await page.evaluate(() => window.failureWatch?.thePicture.reset()).catch(() => {});
    child.kill();
  }
});
