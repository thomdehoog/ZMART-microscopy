import { chromium } from "@playwright/test";
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));
await page.goto("http://127.0.0.1:5174/");
await page.waitForTimeout(400);
await page.locator('.field input[type="password"]').fill("hunter2");
await page.locator(".session-form button.run").click();
await page.waitForTimeout(2300);
await page.locator('.step:has-text("Optical")').first().click();
await page.waitForTimeout(300);
const open = () => page.locator(".setting-box.open");
for (const [kind, name] of [["acquisition","survey"],["acquisition","target"],["autofocus","af-coarse"]]) {
  await open().locator("select").selectOption(kind);
  await open().locator("input").fill(name);
  await open().locator("button.run").click();
  await page.waitForTimeout(700);
}
console.log("box order:", await page.locator(".setting-box").evaluateAll(
  (els) => els.map((e) => (e.classList.contains("open") ? "OPEN" : e.querySelector(".rec-name").textContent))));
const y = await page.locator(".setting-box.open").boundingBox();
const first = await page.locator(".setting-box.done").first().boundingBox();
console.log("open above recorded:", y.y < first.y);
await page.screenshot({ path: "shot-order.png", clip: { x: 430, y: 150, width: 1010, height: 400 } });
console.log("errors:", errs);
await b.close();
