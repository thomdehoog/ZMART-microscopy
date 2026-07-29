/**
 * Fitting a focus surface z(x, y) from measured points.
 *
 * Pure: no DOM, no app state, micrometres in and micrometres out. It mirrors
 * `workflows/target_acquisition/workflow/_focus_surface.py`, which is the
 * authority — if the two ever disagree, that one is right.
 *
 * The model is chosen by geometry rather than by preference:
 *
 *     flat z (< 0.1 µm range) or 1 point   -> constant (mean z)
 *     >= 4 non-collinear points            -> thin-plate spline
 *     otherwise                            -> least-squares plane
 *
 * The spline is a *smoothing* one. It passes near the points, not exactly
 * through them, which is the only reason a residual afterwards means anything:
 * an interpolant's residual is zero by construction and would hide the single
 * autofocus that landed on a speck of dust.
 */

export const FLAT_TOLERANCE_UM = 0.1;
export const SPLINE_SMOOTHING = 0.1;

/** The thin-plate basis r² ln r — the function that minimises bending energy. */
export const kernelU = (r) => (r < 1e-9 ? 0 : r * r * Math.log(r));

/** Dense gaussian elimination with partial pivoting. n stays tiny here. */
export function solve(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let i = 0; i < n; i++) {
    let piv = i;
    for (let k = i + 1; k < n; k++) if (Math.abs(M[k][i]) > Math.abs(M[piv][i])) piv = k;
    if (Math.abs(M[piv][i]) < 1e-12) return null;
    [M[i], M[piv]] = [M[piv], M[i]];
    for (let k = i + 1; k < n; k++) {
      const f = M[k][i] / M[i][i];
      for (let j = i; j <= n; j++) M[k][j] -= f * M[i][j];
    }
  }
  const out = new Array(n).fill(0);
  for (let i = n - 1; i >= 0; i--) {
    let acc = M[i][n];
    for (let j = i + 1; j < n; j++) acc -= M[i][j] * out[j];
    out[i] = acc / M[i][i];
  }
  return out;
}

const ptp = (a) => Math.max(...a) - Math.min(...a);

/** Are the points spread in two dimensions, or strung out along one line? */
export function nonCollinear(xc, yc) {
  let sxx = 0, sxy = 0, syy = 0;
  for (let i = 0; i < xc.length; i++) {
    sxx += xc[i] * xc[i];
    sxy += xc[i] * yc[i];
    syy += yc[i] * yc[i];
  }
  const tr = sxx + syy;
  const det = sxx * syy - sxy * sxy;
  if (tr <= 0) return false;
  const smallest = tr / 2 - Math.sqrt(Math.max(0, (tr * tr) / 4 - det));
  return smallest > 1e-9 * tr;
}

/**
 * A surface with no measured points behind it: a fixed height, or one a
 * previous run recorded. `a` and `b` are µm of tilt across the full extent.
 */
export const affineSurface = ({ a = 0, b = 0, c, width, height }) =>
  ({ kind: "affine", model: "affine", a, b, c, width, height });

/** Height of a fitted surface at a stage position. */
export function surfaceZ(m, x, y) {
  if (!m) return 0;
  if (m.kind === "affine") {
    return m.a * (x / m.width - 0.5) + m.b * (y / m.height - 0.5) + m.c;
  }
  if (m.kind === "constant") return m.c;
  if (m.kind === "plane") return m.c0 * (x - m.x0) + m.c1 * (y - m.y0) + m.c2;

  const u = (x - m.x0) / m.scale;
  const v = (y - m.y0) / m.scale;
  let z = m.a0 + m.a1 * u + m.a2 * v;
  for (let i = 0; i < m.pts.length; i++) {
    const du = u - m.pts[i].u;
    const dv = v - m.pts[i].v;
    z += m.w[i] * kernelU(Math.sqrt(du * du + dv * dv));
  }
  return z;
}

/** Fit `[{x, y, z}]` and report which model the geometry bought via `.model`. */
export function fitSurface(points) {
  const n = points.length;
  if (!n) return null;

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const zs = points.map((p) => p.z);
  const x0 = xs.reduce((a, b) => a + b, 0) / n;
  const y0 = ys.reduce((a, b) => a + b, 0) / n;
  const xc = xs.map((x) => x - x0);
  const yc = ys.map((y) => y - y0);
  const meanZ = () => zs.reduce((a, b) => a + b, 0) / n;

  if (ptp(zs) < FLAT_TOLERANCE_UM || n === 1) {
    return { kind: "constant", model: "constant", c: meanZ() };
  }

  if (n >= 4 && nonCollinear(xc, yc)) {
    const scale = Math.max(ptp(xc), ptp(yc)) || 1;
    const u = xc.map((x) => x / scale);
    const v = yc.map((y) => y / scale);
    const N = n + 3;
    const A = Array.from({ length: N }, () => new Array(N).fill(0));
    const b = new Array(N).fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const du = u[i] - u[j];
        const dv = v[i] - v[j];
        A[i][j] = i === j ? SPLINE_SMOOTHING : kernelU(Math.sqrt(du * du + dv * dv));
      }
      A[i][n] = 1; A[i][n + 1] = u[i]; A[i][n + 2] = v[i];
      A[n][i] = 1; A[n + 1][i] = u[i]; A[n + 2][i] = v[i];
      b[i] = zs[i];
    }
    const sol = solve(A, b);
    if (sol) {
      return {
        kind: "spline", model: "spline", x0, y0, scale,
        pts: u.map((uu, i) => ({ u: uu, v: v[i] })),
        w: sol.slice(0, n), a0: sol[n], a1: sol[n + 1], a2: sol[n + 2],
      };
    }
  }

  const design = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  const rhs = [0, 0, 0];
  for (let i = 0; i < n; i++) {
    const row = [xc[i], yc[i], 1];
    for (let a = 0; a < 3; a++) {
      for (let b2 = 0; b2 < 3; b2++) design[a][b2] += row[a] * row[b2];
      rhs[a] += row[a] * zs[i];
    }
  }

  /* Points along one line leave the normal equations singular across that
     line. numpy answers with a minimum-norm fit — a plane tilted along the
     line and flat across it — so a ridge stands in for the same thing rather
     than collapsing to a constant. */
  let c = solve(design, rhs);
  if (!c) {
    const ridge = 1e-9 * (design[0][0] + design[1][1] + design[2][2]) || 1e-12;
    c = solve(design.map((row, i) => row.map((v, j) => (i === j ? v + ridge : v))), rhs);
  }
  if (!c) return { kind: "constant", model: "constant", c: meanZ() };
  return { kind: "plane", model: "plane", x0, y0, c0: c[0], c1: c[1], c2: c[2] };
}

/**
 * How far each measured point sits from the fitted surface. One large residual
 * is the tell that a single autofocus landed on dust and is quietly bending
 * everything else — the same reading as the Python `residuals_um`.
 */
export const residualsUm = (surface, points) =>
  points.map((p) => p.z - surfaceZ(surface, p.x, p.y));

/** RMS of the residuals, and the index of the point that fits worst. */
export function residualSummary(surface, points) {
  const errs = residualsUm(surface, points);
  if (!errs.length) return { errs, rms: 0, worst: -1 };
  const rms = Math.sqrt(errs.reduce((a, e) => a + e * e, 0) / errs.length);
  let worst = 0;
  errs.forEach((e, i) => { if (Math.abs(e) > Math.abs(errs[worst])) worst = i; });
  return { errs, rms, worst };
}

/**
 * Rebuild the surface without each point in turn, and ask what the remaining
 * points predict for the one held back.
 *
 * This exists because the fit residual is a poor alarm. A smoothing spline
 * bends toward an outlier, so it hides most of its own error: a point 18 µm
 * out of place shows a fit residual near 1 µm, which reads as healthy. The
 * leave-one-out error reports the full 18 µm, because the surface it is
 * measured against never saw the bad point.
 *
 * Note what it still cannot do: with few points, dropping one changes which
 * model the geometry buys (a spline becomes a plane), so every point's error
 * moves. Trust the magnitude as a warning; treat the index as a suggestion
 * until there are six or more points.
 */
export function looErrors(points) {
  if (points.length < 4) return points.map(() => null);
  return points.map((p, i) => {
    const rest = points.filter((_, j) => j !== i);
    return p.z - surfaceZ(fitSurface(rest), p.x, p.y);
  });
}
