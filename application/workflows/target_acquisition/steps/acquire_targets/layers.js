/**
 * What step 8 draws on the picture: the targets that have been imaged.
 */

export function acquiredLayers(theRun) {
  const { run, drawnIn, activeMode } = theRun;
  return {
    frames: {
    key: "frames",
    label: "Target frames",
    explains: "The frame each target will be taken with, laid where it will be taken "
      + "-- the plan the acquisition step images.",
    shown: activeMode === "select" && run.gated.size > 0 && !!run.targetFrameUm,
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      const half = run.targetFrameUm / 2;
      const side = run.targetFrameUm * scale;
      ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 1;
      for (const id of run.gated) {
        const c = run.cells.get(id);
        if (!c) continue;
        const [x, y] = place(c.x - half, c.y - half);
        if (x > w || y > h || x + side < 0 || y + side < 0) continue;
        ctx.strokeRect(x, y, side, side);
      }
    },
  },
    targets: {
    key: "targets",
    label: "Targets",
    explains: "The cells that have been imaged at high resolution -- each "
      + "acquired frame printed where it was taken; the chosen one's frame is outlined.",
    shown: activeMode === "targets" && run.acquired.length > 0,
    /* Readable over the very fields they were acquired in, like the cells
       and the masks: the see-through windows cut every non-solid layer, and
       the green rings survived only off the picture. */
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      for (const id of run.acquired) {
        const c = run.cells.get(id);
        if (!c) continue;
        /* The frames speak for themselves. The chosen one -- whose pair
           the gallery shows -- is outlined along its own frame's edge, so it
           is found among them without a mark over its pixels; the one under
           the pointer is outlined lightly, saying what a press would take. */
        const chosen = run.selectedTarget === id;
        const hovered = run.hoveredTarget === id && !chosen;
        if ((chosen || hovered) && run.targetFrameUm) {
          const half = run.targetFrameUm / 2;
          const [x, y] = place(c.x - half, c.y - half);
          const side = run.targetFrameUm * scale;
          ctx.strokeStyle = "#ffffff"; ctx.lineWidth = chosen ? 4 : 3;
          ctx.strokeRect(x, y, side, side);
          ctx.strokeStyle = "#16a34a"; ctx.lineWidth = chosen ? 1.5 : 1;
          if (hovered) ctx.setLineDash([4, 3]);
          ctx.strokeRect(x, y, side, side);
          ctx.setLineDash([]);
        }
      }
    },
  },
  };
}
