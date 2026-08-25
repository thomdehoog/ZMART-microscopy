/* Which drawing engines the page offers, and the one rule that governs it.
 *
 * The rule is short and it is worth stating before the tests: **the page never
 * offers an engine it cannot open.** A button that draws nothing is worse than a
 * button that is not there, because a picture that never arrives looks exactly
 * like a picture that is still loading, and telling those two apart has cost
 * this project days at a time.
 *
 * There is a real reason the list can be shorter than what was built in. One of
 * the two engines, neuroglancer, hands part of its work to a background
 * program, and a browser will not start one of those for a page that was opened
 * straight off the disk. `src/workflows/target_acquisition/shared/canvas/engines.js` explains that at length. What
 * these tests do is hold the page to it in both directions: the engine is
 * offered when it can work, and absent — with a reason — when it cannot.
 *
 * These run without a browser, so `location` is set by hand below. That is the
 * whole of what the page reads to decide, which is what makes it checkable here
 * rather than only by opening the page and looking.
 */

import { describe, it, expect, afterEach } from "vitest";
import {
  describeEngine, enginesBuiltIn, enginesOnOffer, openerFor, whyOneIsMissing,
} from "../../src/workflows/target_acquisition/shared/canvas/engines.js";

/** Pretend the page was opened from the given kind of address. */
function pageOpenedFrom(protocol) {
  globalThis.location = { protocol, href: `${protocol}//somewhere/index.html` };
}

afterEach(() => { delete globalThis.location; });

describe("what the page was built with", () => {
  it("carries every engine, so they can be compared", () => {
    /* Written out rather than counted, so that adding one is a decision
       somebody made here and not something that happened. The three do
       genuinely different things: two read the microscope's own store and draw
       it in the browser, and `jpeg-under` reads small pictures made ahead of
       time, which is the one that opens a scan of ten thousand fields. */
    expect(enginesBuiltIn()).toEqual(["viv-under", "neuroglancer-under", "jpeg-under"]);
  });

  it("says in plain words what each one does, for the note beside the buttons", () => {
    for (const name of enginesBuiltIn()) {
      expect(describeEngine(name).length, `${name} has no sentence describing it`)
        .toBeGreaterThan(20);
    }
  });

  it("opens the page on a Viv engine, which is a decision and not an accident", () => {
    expect(enginesBuiltIn()[0]).toBe("viv-under");
  });
});

describe("what the page offers, which depends on where it was opened from", () => {
  it("offers everything it has when it was served over HTTP", () => {
    pageOpenedFrom("http:");
    expect(enginesOnOffer()).toEqual(enginesBuiltIn());
    expect(whyOneIsMissing()).toBeNull();
  });

  it("offers everything it has over HTTPS too", () => {
    pageOpenedFrom("https:");
    expect(enginesOnOffer()).toEqual(enginesBuiltIn());
  });

  it("leaves out the engine that needs a background program when opened off the disk", () => {
    pageOpenedFrom("file:");
    // Only neuroglancer needs one. The other two are ordinary JavaScript and
    // draw perfectly well in a page opened straight off the disk.
    expect(enginesOnOffer()).toEqual(["viv-under", "jpeg-under"]);
  });

  it("says which engine is missing and what to do about it", () => {
    pageOpenedFrom("file:");
    const why = whyOneIsMissing();
    expect(why).toContain("neuroglancer-under");
    // Not just "it is not available": the sentence has to end somewhere useful.
    expect(why).toContain("HTTP");
  });

  it("still offers something to draw with, whatever the page was opened from", () => {
    for (const protocol of ["http:", "https:", "file:"]) {
      pageOpenedFrom(protocol);
      expect(enginesOnOffer().length, `nothing to draw with over ${protocol}`)
        .toBeGreaterThan(0);
    }
  });

  /* The rule this whole file exists for. Whatever the page decides to offer, it
     has to be something it knows how to open — if these two lists ever drift
     apart, the page grows a button that draws nothing. */
  it("never offers a name it has no way of opening", () => {
    for (const protocol of ["http:", "https:", "file:"]) {
      pageOpenedFrom(protocol);
      for (const name of enginesOnOffer()) {
        expect(enginesBuiltIn(), `${name} is offered over ${protocol} but not built in`)
          .toContain(name);
      }
    }
  });
});

describe("asking for an engine that is not there", () => {
  it("is refused with the list of what there is, rather than a blank box", async () => {
    pageOpenedFrom("http:");
    await expect(openerFor("no-such-engine")).rejects.toThrow(/there is no engine/);
    await expect(openerFor("no-such-engine")).rejects.toThrow(/viv-under/);
  });
});
