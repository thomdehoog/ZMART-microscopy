import { describe, it, expect } from "vitest";
import {
  fitSurface, surfaceZ, residualSummary, looErrors, affineSurface, nonCollinear, solve,
} from "../../src/lib/surface.js";

/* The contract these pin is not ours — it is
   workflows/target_acquisition/workflow/_focus_surface.py. Change one and the
   other is wrong. */

const plane = (x, y) => -412 + 0.006 * x + 0.004 * y;
const grid = (pts) => pts.map(([x, y]) => ({ x, y, z: plane(x, y) }));

describe("model chosen by geometry", () => {
  it("one point gives a constant at that height", () => {
    const m = fitSurface([{ x: 100, y: 200, z: -410 }]);
    expect(m.model).toBe("constant");
    expect(surfaceZ(m, 9999, 9999)).toBeCloseTo(-410, 9);
  });

  it("a flat sample gives a constant however many points there are", () => {
    const pts = [[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000]]
      .map(([x, y]) => ({ x, y, z: -400.02 }));
    expect(fitSurface(pts).model).toBe("constant");
  });

  it("three spread points give a plane, and it goes through them", () => {
    const pts = grid([[0, 0], [9000, 500], [3000, 6000]]);
    const m = fitSurface(pts);
    expect(m.model).toBe("plane");
    for (const p of pts) expect(surfaceZ(m, p.x, p.y)).toBeCloseTo(p.z, 6);
  });

  it("four non-collinear points earn a spline", () => {
    const m = fitSurface(grid([[0, 0], [9000, 0], [0, 6000], [9000, 6000]]));
    expect(m.model).toBe("spline");
  });

  it("four points on one line do NOT earn a spline", () => {
    const m = fitSurface(grid([[0, 3000], [3000, 3000], [6000, 3000], [9000, 3000]]));
    expect(m.model, "collinear points cannot support a surface").toBe("plane");
  });

  it("a plane fitted to collinear points still tilts along the line", () => {
    const m = fitSurface(grid([[0, 3000], [3000, 3000], [6000, 3000], [9000, 3000]]));
    // the singular direction must not collapse the fit to a constant
    expect(surfaceZ(m, 9000, 3000) - surfaceZ(m, 0, 3000)).toBeCloseTo(0.006 * 9000, 3);
  });

  it("no points is no surface", () => {
    expect(fitSurface([])).toBeNull();
  });
});

describe("the spline smooths rather than interpolates", () => {
  const coords = [[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000]];

  it("reproduces a genuinely flat sample exactly — its affine part is a plane", () => {
    const pts = grid(coords);
    const { rms } = residualSummary(fitSurface(pts), pts);
    expect(rms).toBeLessThan(1e-9);
  });

  it("trades accuracy for smoothness once the surface has curvature", () => {
    const pts = grid(coords).map((p) => ({ ...p, z: p.z + 6 * Math.sin(p.x / 3000) }));
    const { errs, rms } = residualSummary(fitSurface(pts), pts);
    expect(errs.some((e) => Math.abs(e) > 1e-6),
      "an exact interpolant would leave nothing to read").toBe(true);
    expect(rms, "and it still sits close to them").toBeLessThan(3);
  });
});

describe("what a fit residual can and cannot tell you", () => {
  const spoiled = (n = 5, bad = 2, by = 18) => {
    const coords = [[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000],
      [2000, 1500], [7000, 4500], [4500, 300]].slice(0, n);
    const pts = grid(coords);
    pts[bad].z += by;                                 // this autofocus hit dust
    return pts;
  };

  it("a spoiled point does raise the rms", () => {
    const pts = spoiled();
    expect(residualSummary(fitSurface(pts), pts).rms).toBeGreaterThan(0.5);
  });

  it("but the fit residual badly understates how wrong the point is", () => {
    const pts = spoiled();
    const { errs } = residualSummary(fitSurface(pts), pts);
    // 18 µm out of place, reported as about 1 — the spline bent to meet it
    expect(Math.abs(errs[2])).toBeLessThan(4);
  });

  it("and it can blame the wrong point outright", () => {
    const pts = spoiled();
    expect(residualSummary(fitSurface(pts), pts).worst,
      "a good neighbour takes the blame — do not present this as the culprit").not.toBe(2);
  });

  it("three points fit exactly, so a bad one is invisible", () => {
    const pts = grid([[0, 0], [9000, 500], [3000, 6000]]);
    pts[0].z += 18;
    expect(residualSummary(fitSurface(pts), pts).rms).toBeLessThan(1e-6);
  });

  it("reports no worst point when there are no points", () => {
    expect(residualSummary(null, []).worst).toBe(-1);
  });
});

describe("leave-one-out is the honest alarm", () => {
  const spoiled = (coords, bad, by = 18) => {
    const pts = grid(coords);
    pts[bad].z += by;
    return pts;
  };

  it("recovers the full error at the point that was fooled", () => {
    for (const [coords, bad] of [
      [[[0, 0], [9000, 0], [0, 6000], [9000, 6000]], 2],
      [[[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000]], 2],
      [[[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000], [2000, 1500],
        [7000, 4500], [4500, 300]], 4],
    ]) {
      const pts = spoiled(coords, bad);
      expect(Math.abs(looErrors(pts)[bad])).toBeGreaterThan(10);
    }
  });

  it("stays quiet when every point agrees", () => {
    const pts = grid([[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000]]);
    for (const e of looErrors(pts)) expect(Math.abs(e)).toBeLessThan(2);
  });

  it("names the culprit once there are enough points to spare one", () => {
    const coords = [[0, 0], [9000, 0], [0, 6000], [9000, 6000], [4500, 3000],
      [2000, 1500], [7000, 4500], [4500, 300]];
    for (const bad of [0, 2, 4]) {
      const errs = looErrors(spoiled(coords, bad));
      const worst = errs.reduce((b, v, i) => (Math.abs(v) > Math.abs(errs[b]) ? i : b), 0);
      expect(worst).toBe(bad);
    }
  });

  it("declines to answer below four points, where dropping one changes the model", () => {
    const pts = grid([[0, 0], [9000, 500], [3000, 6000]]);
    expect(looErrors(pts)).toEqual([null, null, null]);
  });
});

describe("affine surfaces, for fixed Z and reused runs", () => {
  it("a flat one reads the same everywhere", () => {
    const m = affineSurface({ c: -412, width: 18634, height: 13310 });
    expect(surfaceZ(m, 0, 0)).toBeCloseTo(-412, 9);
    expect(surfaceZ(m, 18634, 13310)).toBeCloseTo(-412, 9);
  });

  it("tilt is expressed across the full extent", () => {
    const m = affineSurface({ a: 96, b: 0, c: -412, width: 18634, height: 13310 });
    expect(surfaceZ(m, 18634, 0) - surfaceZ(m, 0, 0)).toBeCloseTo(96, 6);
  });
});

describe("the primitives underneath", () => {
  it("solve returns null rather than nonsense on a singular system", () => {
    expect(solve([[1, 2], [2, 4]], [1, 2])).toBeNull();
  });

  it("nonCollinear sees a line as a line", () => {
    expect(nonCollinear([-3, -1, 1, 3], [0, 0, 0, 0])).toBe(false);
    expect(nonCollinear([-3, -1, 1, 3], [0, 2, -1, 1])).toBe(true);
  });
});
