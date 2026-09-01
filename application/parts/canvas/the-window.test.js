/**
 * One window, said two ways, and whether the two ways agree.
 *
 * The panel offers *min* and *max*, which say where the brightness window's
 * edges are, and *brightness* and *contrast*, which say how bright its middle
 * is and how tightly it is drawn around that middle. There is only ever one
 * window underneath, and the whole risk in offering both pairs is that they
 * quietly stop describing the same thing — an operator moves one pair, looks at
 * the other, and is told something untrue about their own picture.
 *
 * So most of what is checked here is a round trip: set a brightness, read the
 * brightness back off the window it produced, and require the two to match.
 */

import { describe, expect, it } from "vitest";
import {
  howBrightAndHowTight,
  theWindowThisBrightnessMeans,
  theWindowThisContrastMeans,
} from "./the-window.js";

/* A track like the one a real measurement gives: a light-sheet tile sitting a
   little above a background of about seventeen hundred counts. */
const track = { low: 1500, high: 2500 };

describe("reading a window as brightness and contrast", () => {
  it("calls a window filling the whole track no contrast at all", () => {
    /* Nothing is being stretched: every shade in the picture is spread thinly
       over the screen, which is what nought contrast means. */
    expect(howBrightAndHowTight({ low: 1500, high: 2500 }, track).contrast).toBe(0);
  });

  it("calls a tight window high contrast", () => {
    /* A tenth of the track filling the whole screen: small differences in the
       specimen become large differences on screen. */
    expect(howBrightAndHowTight({ low: 1950, high: 2050 }, track).contrast).toBe(90);
  });

  it("runs brightness backwards, because a low window is a bright picture", () => {
    /* This is the part that surprises people reading the code and nobody using
       it. Pulling the window down towards the dark end means more of the image
       lands above the window and is drawn at full strength, so the picture gets
       brighter. Every other image tool behaves this way. */
    const dark = howBrightAndHowTight({ low: 2300, high: 2400 }, track).brightness;
    const bright = howBrightAndHowTight({ low: 1600, high: 1700 }, track).brightness;
    expect(bright).toBeGreaterThan(dark);
  });

  it("puts a window centred on the middle of the track at half brightness", () => {
    expect(howBrightAndHowTight({ low: 1900, high: 2100 }, track).brightness).toBe(50);
  });
});

describe("moving the brightness", () => {
  it("slides the window along without changing how wide it is", () => {
    /* The same range of values is being shown; a different part of the range is
       being shown at full strength. If the width changed, the brightness slider
       would silently be a contrast slider as well. */
    const before = { low: 1800, high: 2000 };
    const after = theWindowThisBrightnessMeans(before, track, 30);
    expect(after.high - after.low).toBe(before.high - before.low);
  });

  it("gives back exactly the brightness it was asked for", () => {
    for (const asked of [0, 25, 50, 75, 100]) {
      const moved = theWindowThisBrightnessMeans({ low: 1800, high: 2000 }, track, asked);
      expect(howBrightAndHowTight(moved, track).brightness).toBe(asked);
    }
  });

  it("leaves the contrast where it was", () => {
    const before = { low: 1800, high: 2000 };
    const was = howBrightAndHowTight(before, track).contrast;
    const after = theWindowThisBrightnessMeans(before, track, 20);
    expect(howBrightAndHowTight(after, track).contrast).toBe(was);
  });
});

describe("moving the contrast", () => {
  it("draws the window in around its middle", () => {
    const before = { low: 1800, high: 2200 };
    const after = theWindowThisContrastMeans(before, track, 90);
    expect(after.high - after.low).toBeLessThan(before.high - before.low);
    expect((after.low + after.high) / 2).toBe((before.low + before.high) / 2);
  });

  it("gives back exactly the contrast it was asked for", () => {
    for (const asked of [0, 25, 50, 75, 99]) {
      const drawn = theWindowThisContrastMeans({ low: 1800, high: 2200 }, track, asked);
      expect(howBrightAndHowTight(drawn, track).contrast).toBe(asked);
    }
  });

  it("leaves the brightness where it was", () => {
    const before = { low: 1800, high: 2200 };
    const was = howBrightAndHowTight(before, track).brightness;
    const after = theWindowThisContrastMeans(before, track, 60);
    expect(howBrightAndHowTight(after, track).brightness).toBe(was);
  });

  it("never draws a window of no width at all", () => {
    /* A window with both edges in the same place makes every value in the
       picture land on the same shade, so the picture goes flat and nothing on
       screen says why. The panel's slider stops at ninety-nine for the same
       reason; this is the belt to that pair of braces. */
    const drawn = theWindowThisContrastMeans({ low: 1800, high: 2200 }, track, 100);
    expect(drawn.high).toBeGreaterThan(drawn.low);
  });
});

describe("a track with nothing in it", () => {
  it("is treated as one count wide rather than divided by", () => {
    /* This happens before anything has been measured. Without the guard the
       arithmetic divides by nought and every reading comes back as NaN, which
       reaches the screen as an empty box beside a handle that will not move. */
    const flat = { low: 700, high: 700 };
    const feel = howBrightAndHowTight({ low: 700, high: 700 }, flat);
    expect(Number.isFinite(feel.brightness)).toBe(true);
    expect(Number.isFinite(feel.contrast)).toBe(true);
  });
});
