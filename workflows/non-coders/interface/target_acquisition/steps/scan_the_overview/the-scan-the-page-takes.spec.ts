/**
 * What a scan keeps, and what it only shows.
 *
 * The mock microscope through the controller, the bridge writing the run's
 * OME-TIFFs, and the small JPEG copies the page's gallery, previews and masks
 * are drawn from. Whether the fields reach the screen as they land is the
 * walk's question (`../../walk.spec.ts`, through the real bridge) and, at the
 * drawing engine, `workflows/target_acquisition/canvas/source-refresh.spec.ts`'s.
 */

import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { startTheBridge } from "../../testing/live-bridge.ts";

const PORT = Number(process.env.LIVE_BRIDGE_PORT ?? 8791);

/** A scan of a few fields is a run, and a run is not quick. */
const A_RUN_TAKES_A_WHILE = 180_000;

let bridge: Awaited<ReturnType<typeof startTheBridge>> | null = null;

test.beforeAll(async () => {
  bridge = await startTheBridge({ port: PORT });
});
test.afterAll(async () => { await bridge?.stop(); });

test("the pixels stay in the TIFFs; only a copy is drawn", async () => {
  test.setTimeout(A_RUN_TAKES_A_WHILE);
  await bridge!.image([{ x: 0, y: 0, z: 5_000 }]);
  // Looking is what makes the copies: nothing is made for a scan nobody opens.
  await fetch(`${bridge!.pictures}/tiles.json`);

  const data = path.join(bridge!.run, "overview", "data");
  const view = path.join(bridge!.run, "overview", "view");

  /* Two folders, and the acquisition is in only one of them. A display copy is
     lossy on purpose and nothing is ever read back out of it, so the run's own
     pixels must stay where the driver wrote them. */
  expect(fs.readdirSync(data).some((name) => name.endsWith(".ome.tiff"))).toBe(true);
  expect(fs.readdirSync(view).some((name) => name.endsWith(".jpg"))).toBe(true);
  expect(fs.readdirSync(view).some((name) => name.endsWith(".tiff"))).toBe(false);
  expect(fs.existsSync(path.join(view, "tiles.json"))).toBe(true);
});
