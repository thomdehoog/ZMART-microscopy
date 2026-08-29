/**
 * What step 5 draws on the picture: the fields that have been imaged.
 *
 * Not the images themselves — those are the scan, drawn beneath everything by
 * the engine. This is the run's own account of which fields have been taken,
 * which is what an operator watches fill in.
 */
export function overviewLayers(theRun) {
  const { run, css, drawnIn, shown } = theRun;
  return {
    tiles: {
    key: "tiles",
    label: "Tiles",
    explains: "The fields the scan has taken, in the order it wrote them. The pictures "
      + "themselves are the scan, drawn beneath; this is the run's own account.",
    shown: shown > 0,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      ctx.save();
      /* An outline per taken field, never a picture of one: the pixels are
         the engine's, drawn beneath, and anything painted here would stand
         in front of what was actually imaged. */
      ctx.strokeStyle = css("--line");
      ctx.lineWidth = 1;
      for (const t of run.plan.slice(0, shown)) {
        const [sx, sy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
        ctx.strokeRect(sx + 0.5, sy + 0.5, t.frameUm * scale - 1, t.frameUm * scale - 1);
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
