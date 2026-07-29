import { chromium } from "@playwright/test";
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));
page.on("console", (m) => m.type() === "error" && errs.push(m.text()));
await page.goto("http://127.0.0.1:5174/");
await page.waitForTimeout(400);
await page.locator('.field input[type="password"]').fill("hunter2");
await page.locator(".session-form button.run").click();
await page.waitForTimeout(2300);
await page.locator('.step:has-text("Optical")').first().click();
await page.waitForTimeout(300);
const open = () => page.locator(".setting-box.open");
// deliberately interleaved, to prove the grouping is not just insertion order
for (const [kind, name] of [["acquisition","survey"],["autofocus","af-coarse"],
                            ["acquisition","target"],["autofocus","af-fine"]]) {
  await open().locator("select").selectOption(kind);
  await open().locator("input").fill(name);
  await open().locator("button.run").click();
  await page.waitForTimeout(700);
}
console.log("recorded in order :", ["survey","af-coarse","target","af-fine"].join(", "));
console.log("shown as          :", await page.locator(".rec-name").allInnerTexts());
console.log("groups            :", await page.locator(".setting-group").count());
console.log("action bar hidden :", await page.locator("#action-bar").isHidden());
console.log("step done         :",
  await page.locator('.step:has-text("Optical")').first().getAttribute("class"));
console.log("next step open    :",
  await page.locator('.step:has-text("Carrier")').first().isEnabled());
await page.screenshot({ path: "shot-group.png", clip: { x: 430, y: 110, width: 1010, height: 560 } });
console.log("errors:", errs);
await b.close();
