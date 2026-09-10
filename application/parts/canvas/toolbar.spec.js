import { expect, test } from "@playwright/test";

test("view controls and acquisition strips stay inside a narrow canvas", async ({ page }, info) => {
  await page.goto("/?backend=pretend");
  await page.evaluate(async () => {
    const { canvasPanel } = await import("/parts/canvas/panel.js");
    const host = document.createElement("div");
    document.body.replaceChildren(host);
    canvasPanel.build(host);
    const column = host.querySelector(".plot-column");
    column.style.cssText = "width:620px;height:400px";
    for (const id of ["view-modes", "acquisition-pick", "canvas-masks"]) {
      host.querySelector(`#${id}`).hidden = false;
    }
    host.querySelector("#canvas-chips").innerHTML = [1, 2, 3].map(n =>
      `<span class="chip"><span class="chip-dot">${n}</span></span>`).join("");
  });
  for (const width of [620, 480]) {
    await page.locator(".plot-column").evaluate((column, width) => {
      column.style.width = `${width}px`;
    }, width);
    const bounds = await page.locator(".canvas-toolbar").evaluate(toolbar => {
      const box = toolbar.getBoundingClientRect();
      return ["#view-modes", "#carrier-btn", "#acquisition-pick", "#canvas-masks"].map(selector => {
        const child = toolbar.querySelector(selector).getBoundingClientRect();
        return child.left >= box.left && child.right <= box.right && child.bottom <= box.bottom;
      });
    });
    expect(bounds).toEqual([true, true, true, true]);
  }
  await page.screenshot({ path: info.outputPath("wrapped-toolbar.png") });
});
