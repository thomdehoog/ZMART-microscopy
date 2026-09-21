import { expect, test } from "@playwright/test";

for (const kind of ["gallery", "detection"]) {
  test(`${kind}: failed previews are visible and a new image recovers`, async ({ page }) => {
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    await page.route("**/failed-preview.jpg", route => route.fulfill({
      status: 500, contentType: "application/json", body: '{"error":"reader unavailable"}',
    }));
    // Load only the widget under test; no controller or acquisition is started.
    await page.goto("/package.json");
    await page.setContent('<main id="preview-host" style="width:400px"></main>');
    await page.evaluate(async kind => {
      const host = document.querySelector("main");
      const tile = { x: 16, y: 16, frameUm: 32, targetId: "cell" };
      let address = "/failed-preview.jpg";
      let widget;
      if (kind === "gallery") {
        const { default: gallery } = await import("/workflows/target_acquisition/steps/acquire_targets/gallery.js");
        widget = gallery.mount(host, {
          acquired: () => ["target"], selected: () => "target", select() {},
          tileByKey: () => tile, cellById: () => ({ id: "cell", x: 16, y: 16, r: 2 }),
          fieldOf: () => ({ ...tile, cropFrameUm: 32, picture: address }),
          pictureOf: () => address, recordingSlot() {}, changed() {},
        });
      } else {
        const { default: detection } = await import("/workflows/target_acquisition/steps/discover_targets/detection.js");
        const settings = { tile: 0, algo: "fast", diameter: 30, threshold: 100,
          border: 0, binning: 1, tested: false, tried: [] };
        widget = detection.mount(host, {
          settings: () => settings, plan: () => [tile], labelOf: () => "P0",
          pictureOf: () => address, changed() {}, css: () => "#ffffff",
          sizeCanvas(cv) {
            cv.width = cv.cssW = 300; cv.height = cv.cssH = 300;
            return true;
          },
        });
      }
      window.recoverPreview = () => {
        const image = document.createElement("canvas");
        image.width = image.height = 32;
        image.getContext("2d").fillRect(0, 0, 32, 32);
        address = image.toDataURL();
        if (kind === "gallery") widget.chosen();
        else widget.redraw();
      };
    }, kind);
    const canvases = page.locator("canvas[data-picture]");
    const count = kind === "gallery" ? 2 : 1;
    await expect(page.locator('canvas[aria-label="Preview unavailable"]')).toHaveCount(count);
    // The failure message contributes bright pixels; an ordinary black image
    // must stay black and must not be classified as a failed request.
    expect(await canvases.first().evaluate(cv => Array.from(
      cv.getContext("2d").getImageData(0, 0, cv.width, cv.height).data,
    ).some((value, i) => i % 4 !== 3 && value > 200))).toBe(true);
    await page.evaluate(() => window.recoverPreview());
    await expect(page.locator('canvas[aria-label="Preview unavailable"]')).toHaveCount(0);
    await expect.poll(() => canvases.first().evaluate(cv => {
      const pixel = cv.getContext("2d").getImageData(cv.width / 2, cv.height / 2, 1, 1).data;
      return Array.from(pixel).slice(0, 3);
    })).toEqual([0, 0, 0]);
    expect(errors).toEqual([]);
  });
}
