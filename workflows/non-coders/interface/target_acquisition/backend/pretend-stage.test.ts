/* The pretend instrument's stage: the one part of it that stays where it was
 * put.
 *
 * It used to answer with the same corner every time, which made the page look
 * well on the pretend backend and hid a whole class of fault — a mark that
 * never moves is a mark nobody can catch being drawn in the wrong place. These
 * are about the two verbs the controller has for a stage, under the names the
 * controller gives them.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { backend } from "./pretend.ts";
import type { XyzReading } from "./verbs.ts";

const um = (reading: XyzReading) => ({
  x: reading.x.position, y: reading.y.position, z: reading.z.position,
});

describe("the pretend stage", () => {
  /* Put back where it parks, because the module keeps one stage between
     tests, exactly as an instrument keeps one between sessions. */
  beforeEach(async () => { await backend.set_xyz({ x: 4800, y: 3200, z: -412 }); });

  it("answers each axis with its position, its unit, its motor, its motors and its canvas, in micrometres", async () => {
    const at = await backend.get_xyz();
    expect(Object.keys(at.x).sort()).toEqual(["actuator_readings", "canvas", "position", "unit", "used_actuator"]);
    expect(um(at)).toEqual({ x: 4800, y: 3200, z: -412 });
  });

  it("stays where it was driven", async () => {
    await backend.set_xyz({ x: 61_000, y: 42_000, z: -380 });
    expect(um(await backend.get_xyz())).toEqual({ x: 61_000, y: 42_000, z: -380 });
  });

  it("answers the drive with where it ended up", async () => {
    const at = await backend.set_xyz({ x: 12_345, y: 6_789, z: -400 });
    expect(um(at)).toEqual({ x: 12_345, y: 6_789, z: -400 });
  });

  it("refuses a move past the ends of its travel, and stays where it was", async () => {
    /* A real driver does, before anything moves, and a page that believed its
       own request would draw the mark somewhere the stage never went. */
    await expect(backend.set_xyz({ x: 999_999, y: -999_999, z: -412 }))
      .rejects.toThrow(/outside the stage's travel/);
    expect(um(await backend.get_xyz())).toEqual({ x: 4800, y: 3200, z: -412 });
  });

  it("leaves an axis alone when it is not asked about", async () => {
    /* Driving across the plate is not a request to change how far the
       objective is from it. */
    await backend.set_xyz({ x: 20_000, y: 30_000, z: -390 });
    expect(um(await backend.set_xyz({ x: 25_000 })))
      .toEqual({ x: 25_000, y: 30_000, z: -390 });
  });
});
