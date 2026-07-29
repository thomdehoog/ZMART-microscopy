import { chromium } from "@playwright/test";
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto("http://127.0.0.1:5174/");
await page.waitForTimeout(400);
const pw = page.locator('.field input[type="password"]');
await pw.click();
// type character by character, the way a person does
await page.keyboard.type("hunter2", { delay: 60 });
console.log("value kept    :", await pw.inputValue());
console.log("still focused :", await page.evaluate(
  () => document.activeElement?.type === "password"));
console.log("button ready  :", await page.locator(".session-form button.run").isEnabled());
console.log("hint hidden   :", await page.locator(".session-hint").isHidden());
await b.close();
