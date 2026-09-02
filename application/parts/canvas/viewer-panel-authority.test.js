// @vitest-environment jsdom
/**
 * The panel is the picture's one authority on brightness.
 *
 * For a while it was not. The panel measured a window, drew its sliders at
 * those numbers, and never told the engine — which went on drawing through a
 * fixed guess of its own. An independent review caught it with a spy on the
 * engine: a measurement of 1000…1001 reached the sliders and the engine
 * received no window at all. These checks are that spy, kept: for every state
 * a channel can be in, what the engine is told is asserted, not inferred.
 *
 *   declared    — the run wrote a window; it reaches the engine as given.
 *   provisional — measured while the run is still being written; applied.
 *   settled     — measured after the acquisition finished; applied.
 *   waiting     — no pixels yet; the engine is told nothing, the panel says so.
 *   flat        — pixels of one value, which is no window; treated as waiting.
 *   unreadable  — a broken store; nothing applied, and a fault is said.
 *
 * And every row is measured as the panel goes up, not only the chosen one, so
 * a three-colour run does not show one colour until each is clicked on.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { mountViewerPanel } from "./viewer-panel.js";

if (typeof Element.prototype.replaceChildren !== "function") {
  Element.prototype.replaceChildren = function replaceChildren(...children) {
    while (this.firstChild) this.firstChild.remove();
    this.append(...children);
  };
}

function anEngine(howMany) {
  return {
    layersForMeasurement: () => Array.from({ length: howMany }, () => ({ visible: true, window: null })),
    setChannel: vi.fn(),
    whenChannelsChange: () => () => {},
    whenTheViewMoves: () => () => {},
  };
}

/** The viewer's server: one answer per channel index, or one for all. */
function servedBy(answers) {
  globalThis.fetch = vi.fn(async (url, how) => {
    const address = String(url);
    if (address.endsWith("/api/measure")) {
      const asked = JSON.parse(how.body);
      const answer = Array.isArray(answers) ? answers[asked.channel] : answers;
      return { ok: true, json: async () => answer };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
}

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

const SOURCE = "http://127.0.0.1:1/data/0/overview.zmartview.zarr/|zarr3:";

async function mounted(channels, howMany = channels.length) {
  const host = document.createElement("div");
  document.body.append(host);
  const viewer = anEngine(howMany);
  const handle = await mountViewerPanel(host, {
    viewer,
    acquisitions: [{ url: SOURCE, name: "overview", channels }],
  });
  await handle.everyRowMeasured;
  await rest(20);
  return { viewer, handle };
}

/** Every window the engine was handed for one row, in order. */
const windowsGivenTo = (viewer, row) => viewer.setChannel.mock.calls
  .filter(([index, change]) => index === row && change.window)
  .map(([, change]) => change.window);

const stateOf = () => document.querySelector("[data-brightness]").dataset.brightness;
const waitingLine = () => document.querySelector("[data-waiting]");

describe("what the engine is told about brightness", () => {
  let handle;
  afterEach(() => { handle?.destroy(); globalThis.fetch = undefined; });

  it("hands a declared window to the engine as given", async () => {
    servedBy({ histogram: { low: 0, high: 5000, counts: [1, 1] }, window: { low: 9, high: 10 },
      measurementState: "settled" });
    let viewer;
    ({ viewer, handle } = await mounted([
      { name: "GFP", index: 0, colour: [0, 1, 0], window: { low: 300, high: 4200 } },
    ]));
    expect(windowsGivenTo(viewer, 0)).toEqual([{ low: 300, high: 4200 }]);
    expect(stateOf()).toBe("declared");
  });

  it("applies a provisional measurement and says it is from pixels so far", async () => {
    servedBy({ histogram: { low: 100, high: 900, counts: [1, 2, 3] }, window: { low: 1000, high: 1001 },
      measurementState: "provisional" });
    let viewer;
    ({ viewer, handle } = await mounted([{ name: "GFP", index: 0, colour: null, window: null }]));
    expect(windowsGivenTo(viewer, 0)).toEqual([{ low: 1000, high: 1001 }]);
    expect(stateOf()).toBe("provisional");
    expect(waitingLine().textContent).toBe("brightness measured from pixels acquired so far");
  });

  it("applies a settled measurement and says nothing more", async () => {
    servedBy({ histogram: { low: 100, high: 900, counts: [1, 2, 3] }, window: { low: 120, high: 880 },
      measurementState: "settled" });
    let viewer;
    ({ viewer, handle } = await mounted([{ name: "GFP", index: 0, colour: null, window: null }]));
    expect(windowsGivenTo(viewer, 0)).toEqual([{ low: 120, high: 880 }]);
    expect(stateOf()).toBe("settled");
    expect(waitingLine().style.display).toBe("none");
  });

  it("tells the engine nothing while waiting for pixels", async () => {
    servedBy({ empty: true, measurementState: "waiting", measurementError: null });
    let viewer;
    ({ viewer, handle } = await mounted([{ name: "GFP", index: 0, colour: null, window: null }]));
    expect(windowsGivenTo(viewer, 0)).toEqual([]);
    expect(stateOf()).toBe("waiting");
    expect(waitingLine().textContent).toBe("waiting for measurable pixels");
  });

  it("treats a flat field — pixels of one value — as no window, not as one", async () => {
    /* The server answers a one-value field the way it answers no field: there
       is no window in a single number, and inventing one would draw the field
       through a guess. */
    servedBy({ empty: true, measurementState: "waiting", measurementError: null });
    let viewer;
    ({ viewer, handle } = await mounted([{ name: "GFP", index: 0, colour: null, window: null }]));
    expect(windowsGivenTo(viewer, 0)).toEqual([]);
    expect(document.querySelector("[data-brightness]").textContent).not.toMatch(/4095|65535/);
  });

  it("tells the engine nothing about a store it cannot read, and says the fault", async () => {
    servedBy({ empty: true, measurementState: "unreadable",
      measurementError: "the image description names no pixel levels" });
    let viewer;
    ({ viewer, handle } = await mounted([{ name: "GFP", index: 0, colour: null, window: null }]));
    expect(windowsGivenTo(viewer, 0)).toEqual([]);
    expect(stateOf()).toBe("unreadable");
    expect(waitingLine().getAttribute("role")).toBe("alert");
  });

  it("measures every channel as it goes up, not only the chosen one", async () => {
    servedBy([
      { histogram: { low: 0, high: 1, counts: [1] }, window: { low: 10, high: 20 }, measurementState: "provisional" },
      { histogram: { low: 0, high: 1, counts: [1] }, window: { low: 30, high: 40 }, measurementState: "provisional" },
      { histogram: { low: 0, high: 1, counts: [1] }, window: { low: 50, high: 60 }, measurementState: "provisional" },
    ]);
    let viewer;
    ({ viewer, handle } = await mounted([
      { name: "DAPI", index: 0, colour: [0, 0, 1], window: null },
      { name: "GFP", index: 1, colour: [0, 1, 0], window: null },
      { name: "mCherry", index: 2, colour: [1, 0, 0], window: null },
    ]));
    expect(windowsGivenTo(viewer, 0)).toEqual([{ low: 10, high: 20 }]);
    expect(windowsGivenTo(viewer, 1)).toEqual([{ low: 30, high: 40 }]);
    expect(windowsGivenTo(viewer, 2)).toEqual([{ low: 50, high: 60 }]);
    /* And the rows are named as the viewer named them, in its order. */
    const names = [...document.querySelectorAll("[data-channel-row]")].map((line) => line.textContent);
    expect(names).toEqual(["DAPI", "GFP", "mCherry"]);
  });
});
