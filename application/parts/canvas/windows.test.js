/* Which window a channel opens with — and that no window is ever invented.
 *
 * `viz_studio/options/windows.js` is the one rule all three engines follow.
 * What is guarded here is the end of that rule: a channel nobody has given a
 * window gets none, rather than the fixed nought-to-4095 the engines used to
 * fall back on, which on the operator's canvas could not be told apart from a
 * window somebody had chosen.
 */

import { describe, expect, it } from "vitest";

import { isAWindow, theWindowToOpenWith } from "../../../viz_studio/options/windows.js";

describe("the window a channel opens with", () => {
  it("takes what the page said before anything else", async () => {
    const found = await theWindowToOpenWith({
      page: { low: 120, high: 880 }, store: { low: 1, high: 2 },
      pixels: async () => ({ low: 3, high: 4 }),
    });
    expect(found).toEqual({ window: { low: 120, high: 880 }, from: "page" });
  });

  it("then what the run declared", async () => {
    const found = await theWindowToOpenWith({
      store: { low: 300, high: 4200 }, pixels: async () => ({ low: 3, high: 4 }),
    });
    expect(found).toEqual({ window: { low: 300, high: 4200 }, from: "store" });
  });

  it("then what the pixels ask for, and says it was measured", async () => {
    const found = await theWindowToOpenWith({ pixels: async () => ({ low: 807, high: 3921 }) });
    expect(found).toEqual({ window: { low: 807, high: 3921 }, from: "pixels" });
  });

  it("and with nothing to go on, gives nothing — never a camera's range", async () => {
    const found = await theWindowToOpenWith({ pixels: async () => null });
    expect(found).toEqual({ window: null, from: null });
    expect(await theWindowToOpenWith({})).toEqual({ window: null, from: null });
  });

  it("refuses a window that is not one", () => {
    expect(isAWindow({ low: 0, high: 4095 })).toBe(true);
    expect(isAWindow({ low: 5, high: 5 })).toBe(false);
    expect(isAWindow({ low: NaN, high: 1 })).toBe(false);
    expect(isAWindow(null)).toBe(false);
  });
});
