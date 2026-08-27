/**
 * What step 5 draws on the picture: the fields that have been imaged.
 *
 * Not the images themselves — those are the scan, drawn beneath everything by
 * the engine. This is the run's own account of which fields have been taken,
 * which is what an operator watches fill in.
 */
export function overviewLayers(theRun) {
  const { run, css, drawnIn, theSample, shown, ch0, ch1, tileTexture, density } = theRun;
  return {
    tiles: {
    key: "tiles",
    label: "Tiles",
    explains: "The fields the scan has taken, in the order it wrote them, with the "
      + "tissue each one found. This is what the run has actually seen.",
    shown: shown > 0,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      ctx.save();
      const done = run.plan.slice(0, shown);
      for (const t of done) tileTexture(ctx, t, place, scale);
      /* Tissue is drawn inside the tiles that have been taken, because an
         image is the only way the run knows it is there. */
      ctx.globalCompositeOperation = "lighter";
      for (const t of done) {
        const d = density(t.x, t.y);
        if (d < 0.02) continue;
        const [bx, by] = place(t.x, t.y);
        const br = (t.frameUm * 0.75) * scale;
        const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
        if (ch0) g.addColorStop(0, `rgba(34,211,238,${0.34 * d})`);
        g.addColorStop(0.55, ch1 ? `rgba(245,158,11,${0.16 * d})` : `rgba(34,211,238,${0.12 * d})`);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();

      // ---- scan frontier: the tile the stage is standing on
      if (run.running === "scan" && run.plan[shown]) {
        const t = run.plan[shown];
        const [fx, fy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
        ctx.strokeStyle = css("--accent");
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.strokeRect(fx, fy, t.frameUm * scale, t.frameUm * scale);
        ctx.setLineDash([]);
      }

      /* ---- sample bounds: the edge of what has been imaged, so it exists
         once something has been. Drawn from the first tile it was a second
         square sitting in the plate's corner before any of this had
         happened, which says the run has a sample somewhere it does not yet
         have one. */
      if (theSample().bounds) {
        const b = theSample().bounds;
        const [bx, by] = place(b.xMin, b.yMin);
        ctx.strokeStyle = css("--line-strong");
        ctx.lineWidth = 1;
        ctx.strokeRect(bx, by, (b.xMax - b.xMin) * scale, (b.yMax - b.yMin) * scale);
      }
    },
    /* A click on a taken field is a click on that field. This is what
       opening a position from the picture will hang off. */
    reaches: (at) => {
      const half = (t) => t.frameUm / 2;
      return run.plan.slice(0, shown).find(
        (t) => Math.abs(at.x - t.x) <= half(t) && Math.abs(at.y - t.y) <= half(t),
      ) ?? null;
    },
  },
  };
}
