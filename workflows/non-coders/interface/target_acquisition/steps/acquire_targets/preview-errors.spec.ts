import { expect, test } from "@playwright/test";
import type { GalleryContext } from "./gallery.ts";

declare global {
  interface Window {
    /** Test-only: swaps the failed preview for a good image and redraws. */
    recoverPreview?: () => void;
  }
}

test("gallery: failed previews are visible and a new image recovers", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(String(error)));
  await page.route("**/failed-preview.jpg", route => route.fulfill({
    status: 500, contentType: "application/json", body: '{"error":"reader unavailable"}',
  }));
  // Load only the widget under test; no controller or acquisition is started.
  await page.goto("/package.json");
  await page.setContent('<main id="preview-host" style="width:400px"></main>');
  await page.evaluate(async () => {
    const host = document.querySelector("main")!;
    const tile = { x: 16, y: 16, frameUm: 32, targetId: "cell" };
    let address = "/failed-preview.jpg";
    const { default: gallery } = await import("/@zmart-workflows/target_acquisition/steps/acquire_targets/gallery.ts");
    /* A stand-in for the channel: only what the previews read, handed over as the whole context. */
    const widget = gallery.mount(host, {
      acquired: () => ["target"], selected: () => "target", select() {},
      tileByKey: () => tile, cellById: () => ({ id: "cell", x: 16, y: 16, r: 2 }),
      fieldOf: () => ({ ...tile, cropFrameUm: 32, picture: address }),
      pictureOf: () => address, recordingSlot() {}, changed() {},
    } as unknown as GalleryContext);
    window.recoverPreview = () => {
      const image = document.createElement("canvas");
      image.width = image.height = 32;
      image.getContext("2d")!.fillRect(0, 0, 32, 32);
      address = image.toDataURL();
      widget.chosen();
    };
  });
  const canvases = page.locator("canvas[data-picture]");
  await expect(page.locator('canvas[aria-label="Preview unavailable"]')).toHaveCount(2);
  // The failure message contributes bright pixels; an ordinary black image
  // must stay black and must not be classified as a failed request.
  expect(await canvases.first().evaluate((cv: HTMLCanvasElement) => Array.from(
    cv.getContext("2d")!.getImageData(0, 0, cv.width, cv.height).data,
  ).some((value, i) => i % 4 !== 3 && value > 200))).toBe(true);
  await page.evaluate(() => window.recoverPreview!());
  await expect(page.locator('canvas[aria-label="Preview unavailable"]')).toHaveCount(0);
  await expect.poll(() => canvases.first().evaluate((cv: HTMLCanvasElement) => {
    const pixel = cv.getContext("2d")!.getImageData(cv.width / 2, cv.height / 2, 1, 1).data;
    return Array.from(pixel).slice(0, 3);
  })).toEqual([0, 0, 0]);
  expect(errors).toEqual([]);
});
