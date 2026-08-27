/**
 * The same promises, asked of both backends.
 *
 * The pretend one is asked on every change, because it needs nothing running.
 * The live one is asked when there is a bridge to ask — start one and point
 * this at it:
 *
 *     python -m workflows.target_acquisition.workflow.webapp.bridge --port 8600
 *     BACKEND_BRIDGE=http://127.0.0.1:8600 npx vitest run tests/unit/backend-contract.test.js
 *
 * With the mock driver behind that bridge it is a full round of the real path
 * — controller, registry, driver contract — and the two answers are held
 * against the same list. That is the only arrangement in which the pretend
 * backend cannot quietly drift away from the instrument it stands for.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import { beforeAll, describe, expect, it } from "vitest";
import { promisesOfABackend } from "../backend-contract.js";
import { backend as pretend } from "../../parts/microscope/mock.js";

const promises = promisesOfABackend(expect);

describe("the pretend backend keeps the page's promises", () => {
  for (const promise of promises) {
    it(promise.what, async () => { await promise.keep(pretend); });
  }
});

/* Only when a bridge is running. Skipped rather than failed, because the
   offline suite is the one that runs on every change and it must not need a
   Python process; this is the run somebody makes deliberately, on the
   microscope PC or against the mock driver. */
const bridgeAt = process.env.BACKEND_BRIDGE;

describe.skipIf(!bridgeAt)("the live backend keeps the same promises", () => {
  let live = null;

  beforeAll(async () => {
    /* `live.js` reads the bridge's address off the page's own address, which
       is how an operator points it somewhere during development. There is no
       page here, so it is given one. */
    globalThis.location = { search: `?bridge=${bridgeAt}`, protocol: "http:" };
    ({ backend: live } = await import(
      "../../parts/microscope/live.js"
    ));
    /* Nothing answers before a session is open, and which instrument is
       opened is not left to the order the registry happens to list them in.
       These promises drive a stage about. The mock driver is chosen wherever
       one is offered — on a development machine the registry lists the Leica
       first, and a test that took the first entry would open a session on a
       real microscope and move it. Driving the real one is a deliberate act,
       so it takes a word from whoever is running this. */
    const offered = await live.instruments();
    const mockDriver = offered.find((one) => one.vendor === "mock");
    if (!mockDriver && !process.env.BACKEND_BRIDGE_MAY_MOVE_THE_MICROSCOPE) {
      throw new Error(
        "this bridge offers no mock driver, and these promises drive the stage."
        + " Set BACKEND_BRIDGE_MAY_MOVE_THE_MICROSCOPE=yes to run them against"
        + ` the instrument itself (${offered.map((one) => one.vendor).join(", ")}).`,
      );
    }
    await live.connect({ connection: mockDriver ?? offered[0] });
  }, 30_000);

  for (const promise of promises) {
    it(promise.what, async () => { await promise.keep(live); }, 30_000);
  }
});
