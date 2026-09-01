// @vitest-environment jsdom
/**
 * A channel with no window yet says so, and offers no controls that pretend.
 *
 * This is the embedded half of the promise the Viewer makes as
 * `absent-display-window-v1`. Before the first field of a live run lands,
 * the run has declared no window and there are no pixels to measure one
 * from. The panel used to fill that gap with nought to sixty-five thousand —
 * the whole of a sixteen-bit camera — and two live sliders sitting at those
 * numbers, which is indistinguishable on screen from a run somebody set up
 * that way. Now it says it is waiting, and the four brightness controls are
 * disabled until there is something honest to show.
 *
 * A store that cannot be read at all is a different thing and gets a
 * different sentence: "waiting" over a corrupt store would wait for ever.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mountViewerPanel } from "./viewer-panel.js";

/* The jsdom this project happens to carry predates `replaceChildren`, which
   every browser the panel runs in has had for years. Fill it in rather than
   let the check fail over the test bed. */
if (typeof Element.prototype.replaceChildren !== "function") {
  Element.prototype.replaceChildren = function replaceChildren(...children) {
    while (this.firstChild) this.firstChild.remove();
    this.append(...children);
  };
}

/** A viewer that draws one acquisition of one channel and answers nothing else. */
function aQuietViewer() {
  return {
    layersForMeasurement: () => [{ visible: true, window: null }],
    setChannel: vi.fn(),
    whenChannelsChange: () => () => {},
    whenTheViewMoves: () => () => {},
  };
}

/**
 * Pretend to be the viewer's server: the store's description, and one answer
 * to every measurement. `measure` is what /api/measure says.
 */
function servedBy(measure, description = { multiscales: [] }) {
  globalThis.fetch = vi.fn(async (url, how) => {
    const address = String(url);
    if (address.endsWith("/api/measure")) {
      return { ok: true, json: async () => measure };
    }
    if (address.endsWith("/.zattrs")) {
      return { ok: true, json: async () => description };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  });
}

const rest = (ms) => new Promise((done) => setTimeout(done, ms));

async function mounted() {
  const host = document.createElement("div");
  document.body.append(host);
  const handle = await mountViewerPanel(host, {
    viewer: aQuietViewer(),
    acquisitions: [{ url: "http://127.0.0.1:1/data/0/overview.zmartview.zarr/|zarr2:",
      name: "overview" }],
  });
  /* Pick the one channel, the way an operator would, and let the measurement
     it asks for come back. */
  const panel = document.querySelector(".viewer-panel");
  panel.querySelector('[data-channel-row="0"]').click();
  await rest(50);
  return { panel, handle };
}

function settingsOf(panel) {
  const card = panel.querySelector("[data-brightness]");
  const control = (name) => card.querySelector(`[data-control="${name}"] input[type=range]`);
  return {
    card,
    state: card?.dataset.brightness,
    waiting: card.querySelector("[data-waiting]"),
    min: control("min"), max: control("max"),
    brightness: control("brightness"), contrast: control("contrast"),
  };
}

describe("a channel with no window yet", () => {
  let handle;
  afterEach(() => { handle?.destroy(); globalThis.fetch = undefined; });

  it("says it is waiting and offers no brightness controls", async () => {
    servedBy({ empty: true, measurementState: "waiting", measurementError: null });
    ({ handle } = await mounted());
    const panel = document.querySelector(".viewer-panel");
    const found = settingsOf(panel);
    expect(found.state).toBe("waiting");
    expect(found.waiting.style.display).toBe("block");
    expect(found.waiting.textContent).toBe("waiting for measurable pixels");
    expect(found.waiting.getAttribute("role")).toBe("status");
    for (const slider of [found.min, found.max, found.brightness, found.contrast]) {
      expect(slider.disabled).toBe(true);
    }
    /* And nowhere on the card does the camera's whole range stand in for a
       window somebody chose. */
    expect(found.card.textContent).not.toMatch(/65535/);
  });

  it("names a store that cannot be read instead of waiting for it", async () => {
    servedBy({ empty: true, measurementState: "unreadable",
      measurementError: "the image description names no pixel levels" });
    ({ handle } = await mounted());
    const found = settingsOf(document.querySelector(".viewer-panel"));
    expect(found.state).toBe("unreadable");
    expect(found.waiting.getAttribute("role")).toBe("alert");
    expect(found.waiting.textContent).toMatch(/cannot be read/);
    expect(found.waiting.textContent).toMatch(/names no pixel levels/);
    expect(found.min.disabled).toBe(true);
  });

  it("wakes the controls the moment a measurement arrives", async () => {
    servedBy({
      histogram: { low: 100, high: 900, counts: [1, 2, 3, 4], autoWindow: { low: 120, high: 880 } },
      window: { low: 120, high: 880 },
      measurementState: "provisional",
    });
    ({ handle } = await mounted());
    const found = settingsOf(document.querySelector(".viewer-panel"));
    expect(found.state).toBe("provisional");
    /* Said, the way the standalone Viewer says it, while the run is still
       being written. */
    expect(found.waiting.style.display).toBe("block");
    expect(found.waiting.textContent).toBe("brightness measured from pixels acquired so far");
    expect(found.min.disabled).toBe(false);
    expect(Number(found.min.value)).toBe(120);
    expect(Number(found.max.value)).toBe(880);
  });

  it("calls a window the run wrote 'declared', and leaves it alone", async () => {
    servedBy(
      { histogram: { low: 100, high: 900, counts: [1, 2, 3, 4] }, window: { low: 150, high: 850 },
        measurementState: "settled" },
      { multiscales: [], omero: { channels: [
        { label: "GFP", color: "00FF00", window: { min: 0, max: 65535, start: 300, end: 4200 } },
      ] } },
    );
    ({ handle } = await mounted());
    const found = settingsOf(document.querySelector(".viewer-panel"));
    expect(found.state).toBe("declared");
    expect(Number(found.min.value)).toBe(300);
    expect(Number(found.max.value)).toBe(4200);
  });
});
