/**
 * What step 8 draws on the picture: the targets that have been imaged.
 */

export function acquiredLayers(theRun) {
  const { run, drawnIn, activeMode } = theRun;
  return {
    frames: {
    key: "frames",
    label: "Target tiles",
    explains: "The tiles laid round the restricted targets, in the target settings' "
      + "frame -- the plan the acquisition step images.",
    shown: activeMode === "select" && run.targetTiles.length > 0,
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      ctx.globalAlpha = run.targetTilesAlpha;
      ctx.fillStyle = "#16a34a";
      ctx.strokeStyle = "#15803d"; ctx.lineWidth = 1;
      for (const tile of run.targetTiles) {
        const half = tile.frameUm / 2;
        const [x, y] = place(tile.x - half, tile.y - half);
        const side = tile.frameUm * scale;
        if (x > w || y > h || x + side < 0 || y + side < 0) continue;
        ctx.fillRect(x, y, side, side);
        ctx.strokeRect(x, y, side, side);
      }
      ctx.globalAlpha = 1;
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
