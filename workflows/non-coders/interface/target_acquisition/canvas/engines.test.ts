/* Opening an engine by name, and the one rule that governs it: a name that
 * cannot be opened is refused with a sentence saying what there is, never
 * answered with a box that stays empty. */

import { describe, it, expect } from "vitest";
import { openerFor } from "./engines.ts";

describe("asking for an engine that is not there", () => {
  it("is refused with the list of what there is, rather than a blank box", async () => {
    await expect(openerFor("no-such-engine")).rejects.toThrow(/there is no engine/);
    await expect(openerFor("no-such-engine")).rejects.toThrow(/neuroglancer-under/);
  });
});
