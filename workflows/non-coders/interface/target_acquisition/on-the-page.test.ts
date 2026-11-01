/* Target acquisition's hooks: what it does when the page tells it the run
   starts over or another workflow is chosen. The clock that reads where the
   stage is must stop either way -- left running, it would go on asking a
   closed session, or another workflow's backend, where its stage is. */

import { describe, it, expect } from "vitest";
import { theHooksOf } from "./on-the-page.ts";
import type { TaPage } from "./types.ts";

function aPage() {
  const stopped: string[] = [];
  const page = {
    stageWatch: { stop: () => stopped.push("stopped") },
    view: { fitted: true },
    shown: {},
    renderPointList: () => {},
    listInstruments: () => {},
  };
  /* Enough of a page for the hooks, handed over as the page. */
  return { page, stopped, asPage: page as unknown as TaPage };
}

describe("the stage's clock", () => {
  it("stops when the run starts over, as on Disconnect", () => {
    const { page, stopped, asPage } = aPage();
    theHooksOf(asPage).onReset!();
    expect(stopped).toEqual(["stopped"]);
    expect(page.stageWatch).toBe(null);
    expect(page.view.fitted).toBe(false);
  });

  it("stops when another workflow is chosen", () => {
    const { page, stopped, asPage } = aPage();
    theHooksOf(asPage).onLeave!();
    expect(stopped).toEqual(["stopped"]);
    expect(page.stageWatch).toBe(null);
  });
});
