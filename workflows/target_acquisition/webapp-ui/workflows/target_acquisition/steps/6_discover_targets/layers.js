/**
 * What step 6 draws on the picture: the cells found, and the field being tuned on.
 *
 * The test field is a separate layer and stays solid, because it says which
 * position the channel's preview is of — a question about what you are looking
 * at rather than a thing the run produced.
 */
export function targetLayers(theRun) {
  const { run, css, drawnIn, theSample, activeMode } = theRun;
  return {
    cells: {
    key: "cells",
    label: "Cells",
    explains: "What detection found. The ones that passed the gate are ringed, so which "
      + "is which does not rest on colour alone.",
    shown: run.cellsShown,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      const ctxRad = Math.max(1.1, 1.4 * Math.sqrt(scale / 0.03));
      ctx.fillStyle = css("--mark-context");
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      for (const c of theSample().cells) {
        if (!run.detected.has(c.id) || run.gated.has(c.id)) continue;
        const [x, y] = place(c.x, c.y);
        if (x < -8 || y < -8 || x > w + 8 || y > h + 8) continue;
        ctx.moveTo(x + ctxRad, y);
        ctx.arc(x, y, ctxRad, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.globalAlpha = 1;

      // gated cells — ringed, so identity is not carried by colour alone
      const gr = Math.max(3, 4.2 * Math.sqrt(scale / 0.03));
      for (const c of theSample().cells) {
        if (!run.gated.has(c.id)) continue;
        const [x, y] = place(c.x, c.y);
        if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
        ctx.beginPath(); ctx.arc(x, y, gr, 0, Math.PI * 2);
        ctx.fillStyle = "#0284c7"; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
      }
    },
    reaches: (at) => {
      let best = 12 / scale, hit = null;
      for (const c of theSample().cells) {
        if (!run.detected.has(c.id)) continue;
        const d = Math.hypot(c.x - at.x, c.y - at.y);
        if (d < best) { best = d; hit = c; }
      }
      return hit;
    },
  },
    detect: {
    key: "detect",
    label: "Test field",
    explains: "The one position detection is being tuned on, so the canvas says which "
      + "tile the channel's preview is of.",
    shown: activeMode === "detect" && !!run.plan[run.detect.tile],
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      const t = run.plan[run.detect.tile];
      const half = t.frameUm / 2;
      const [x, y] = place(t.x - half, t.y - half);
      ctx.strokeStyle = css("--accent");
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, t.frameUm * scale, t.frameUm * scale);
    },
  },
  };
}
