/** Opt-in pixel check of actual LAS X captures already published by the operator. */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { pythonForTheBridge } from "../../workflows/target_acquisition/steps/scan_the_overview/live-bridge.js";
import { readPng } from "../../workflows/target_acquisition/steps/scan_the_overview/pixels.js";

test("saved live simulator captures render Top, specimen Slice and MIP", async ({page}, info) => {
  test.skip(!process.env.SIMULATOR_OPERATOR_RECORDS,
    "Requires a live operator publisher and independently captured LAS X records");
  test.setTimeout(180000);
  const oracle = fileURLToPath(new URL("./fixtures/simulator_pixel_oracle.py", import.meta.url));
  const cases = JSON.parse(execFileSync(pythonForTheBridge(), [oracle,
    process.env.SIMULATOR_OPERATOR_RECORDS], {encoding:"utf8", windowsHide:true}));
  const bridge = process.env.SIMULATOR_OPERATOR_URL || "http://127.0.0.1:8865";
  const state = await (await page.request.get(bridge + "/api/viewer")).json();
  expect(state.error).toBeNull();
  expect(Object.values(state.publications).every(p => p.state === "ready")).toBe(true);
  const errors = [], requests = [];
  page.on("pageerror", error => errors.push(String(error)));
  page.on("request", request => { if (/\/data\/.*\/c\//.test(request.url())) requests.push(request.url()); });
  await page.goto("/?backend=pretend");
  await page.evaluate(() => {
    const host = document.createElement("div");
    host.id = "simulator-pixels";
    host.style.cssText = "position:fixed;left:0;top:0;width:640px;height:640px;z-index:999;background:magenta";
    document.body.append(host);
  });
  try {
    for (const [index, sample] of cases.entries()) {
      await page.evaluate(async ({state, sample}) => {
        const acquisition = state.acquisitions.find(a => a.name === sample.name);
        const api = await import(acquisition.embeddingUrl);
        const rows = acquisition.channels.map(c => ({...c, group:acquisition.name}));
        const choice = api.viewChoices(rows)[0];
        const selected = api.selectedViews(rows, {[choice.id]:sample.mode});
        const channels = rows.filter(c => api.inSelectedView(c, selected) && c.channelIndex === 0)
          .map(c => ({...c, colour:[0,1,0], window:{low:0, high:255}, visible:true}));
        const acquisitions = [{...acquisition, channels, url:channels[0].sources[0]}];
        if (!window.simulatorViewer) {
          const {openerFor} = await import("/parts/canvas/engines.js");
          window.simulatorViewer = await (await openerFor("neuroglancer-under"))(
            document.querySelector("#simulator-pixels"),
            {acquisitions, presentation:"2d-overlay", transparentBackground:true});
        } else if (!await simulatorViewer.addSources(acquisitions)) throw new Error("Viewer reopened");
        simulatorViewer.setView({centre:sample.centre, zoom:sample.spacing});
        simulatorViewer.setPlane(sample.mode === "slice" ? sample.z : sample.plane);
      }, {state, sample});
      const error = async () => {
        const image = readPng(await page.locator("#simulator-pixels").screenshot());
        return Math.max(...sample.samples.flatMap(([x,y,value]) => {
          const at = ((64+y)*image.width+64+x)*image.channels;
          return [Math.abs(image.data[at+1]-value), image.data[at], image.data[at+2]];
        }));
      };
      await expect.poll(error, {message:JSON.stringify({name:sample.name,mode:sample.mode,plane:sample.plane}),
        timeout:20000}).toBeLessThanOrEqual(1);
      await page.locator("#simulator-pixels").screenshot({path:info.outputPath(`${index}-${sample.name}-${sample.mode}-${sample.plane}.png`)});
      console.log({name:sample.name,mode:sample.mode,plane:sample.plane,pixels:sample.samples.length});
    }
    const before = requests.length;
    for (let i=0; i<10; i++) {
      await page.request.get(bridge + "/api/viewer");
      await page.waitForTimeout(200);
    }
    expect(requests.length).toBe(before);
    expect(errors).toEqual([]);
    console.log({imageRequests:before,idleImageRequests:0});
  } finally {
    await page.evaluate(() => window.simulatorViewer?.destroy());
  }
});
