/**
 * Measure, inside the operator's own window, how far the masks sit from their
 * nuclei -- the same question the walk asks off a Playwright page, asked of
 * the WebView2 window the operator actually looks at.
 *
 * The window has to have been opened with a debugging port:
 *
 *     WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222
 *
 * and the page has to be showing masks over a scanned overview (step 6, after
 * detection). Then:
 *
 *     node measure-masks-in-window.mjs [http://127.0.0.1:9222]
 *
 * It photographs the middle of the canvas with the masks solid red and again
 * with them hidden, and reports the shift that lays the red over the bright
 * nuclei, whole and per quarter, at the view as it stands and at zooms either
 * side of it. Photographs go beside this file under `measure-masks/`.
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { bestShift, readPng } from "./workflows/target_acquisition/steps/scan_the_overview/pixels.js";

const endpoint = process.argv[2] ?? "http://127.0.0.1:9222";
const rest = (ms) => new Promise((done) => setTimeout(done, ms));
const out = path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "measure-masks");
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.connectOverCDP(endpoint);
const page = browser.contexts().flatMap((c) => c.pages()).find((p) => /zmart|127\.0\.0\.1/i.test(p.url()));
if (!page) throw new Error("no ZMART page found behind the debugging port");
console.log(`measuring ${page.url()}`);

async function photograph(share = 0.6) {
  const box = await page.locator("#picture-host").boundingBox();
  const margin = (1 - share) / 2;
  const clip = { x: box.x + box.width * margin, y: box.y + box.height * margin, width: box.width * share, height: box.height * share };
  return readPng(await page.screenshot({ clip }));
}

async function measure(label) {
  const withMasks = await photograph();
  fs.writeFileSync(path.join(out, `${label}-with-masks.png`), await page.screenshot());
  await page.locator("#mask-eye").click();
  await rest(900);
  const withoutMasks = await photograph();
  fs.writeFileSync(path.join(out, `${label}-without-masks.png`), await page.screenshot());
  await page.locator("#mask-eye").click();
  await rest(400);
  const { width, height, channels } = withMasks;
  const masks = new Uint8Array(width * height);
  const nuclei = new Uint8Array(width * height);
  for (let i = 0; i < width * height; i++) {
    const a = i * channels;
    const [r, g, b] = [withMasks.data[a], withMasks.data[a + 1], withMasks.data[a + 2]];
    masks[i] = r > 150 && g < 110 && b < 110 ? 1 : 0;
    const bright = Math.max(withoutMasks.data[a], withoutMasks.data[a + 1], withoutMasks.data[a + 2]);
    nuclei[i] = bright > 90 ? 1 : 0;
  }
  const whole = bestShift(masks, nuclei, width, height, 16);
  const view = await page.evaluate(() => window.__theStageCanvas.view());
  console.log(`${label}: ${view.zoom.toFixed(3)} um/px, dpr ${await page.evaluate(() => devicePixelRatio)}: dx=${whole.dx} dy=${whole.dy} px = ${(whole.dx * view.zoom).toFixed(2)},${(whole.dy * view.zoom).toFixed(2)} um, overlap ${whole.score.toFixed(2)}`);
  const hw = Math.floor(width / 2), hh = Math.floor(height / 2);
  for (const [name, x0, y0] of [["top-left", 0, 0], ["top-right", hw, 0], ["bottom-left", 0, hh], ["bottom-right", hw, hh]]) {
    const a = new Uint8Array(hw * hh), b = new Uint8Array(hw * hh);
    for (let y = 0; y < hh; y++) for (let x = 0; x < hw; x++) {
      a[y * hw + x] = masks[(y + y0) * width + x + x0];
      b[y * hw + x] = nuclei[(y + y0) * width + x + x0];
    }
    const q = bestShift(a, b, hw, hh, 16);
    console.log(`   ${name}: dx=${q.dx} dy=${q.dy} overlap ${q.score.toFixed(2)}`);
  }
}

/* The masks solid red and fully opaque, so red means mask and nothing else. */
await page.locator("#mask-btn").click();
await rest(400);
const dress = await page.evaluate(() => ({
  colour: document.querySelector("#mask-picker")?.value, fill: document.querySelector("#mask-fill")?.getAttribute("aria-pressed"),
  opacity: document.querySelector("#mask-opacity")?.value,
}));
await page.locator("#mask-picker").fill("#ff0000");
await page.locator("#mask-fill").click();
await page.locator("#mask-opacity").evaluate((slider) => { slider.value = "100"; slider.dispatchEvent(new Event("input", { bubbles: true })); });
await rest(900);

const standing = await page.evaluate(() => window.__theStageCanvas.view());
await measure("as-it-stands");
for (const times of [0.5, 2, 4]) {
  await page.evaluate((view) => window.__theStageCanvas.lookAt(view), { zoom: standing.zoom * times, centre: standing.centre });
  await rest(1200);
  await measure(`${times}x`);
}
await page.evaluate((view) => window.__theStageCanvas.lookAt(view), standing);

/* The dress as the operator had it. */
if (dress.colour) await page.locator("#mask-picker").fill(dress.colour);
if (dress.fill !== "true") await page.locator("#mask-line").click();
if (dress.opacity) await page.locator("#mask-opacity").evaluate((slider, v) => { slider.value = v; slider.dispatchEvent(new Event("input", { bubbles: true })); }, dress.opacity);
await page.keyboard.press("Escape");
await browser.close();
console.log(`photographs in ${out}`);
