/**
 * What Step 9 draws on the picture: the target tiles that have been imaged.
 */

export function acquiredLayers(theRun) {
  const { run, drawnIn, activeMode, css } = theRun;
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
      ctx.fillStyle = css("--accent");
      ctx.strokeStyle = css("--accent-deep"); ctx.lineWidth = 1;
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
       the selected outline survives only off the picture. */
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      for (const key of run.acquired) {
        const acquired = run.acquiredTiles[key];
        if (!acquired) continue;
        /* The frames speak for themselves. The chosen one -- whose pair
           the gallery shows -- is outlined along its own frame's edge, so it
           is found among them without a mark over its pixels; the one under
           the pointer is outlined lightly, saying what a press would take. */
        const chosen = run.selectedTarget === key;
        const hovered = run.hoveredTarget === key && !chosen;
        if (chosen || hovered) {
          const half = acquired.frameUm / 2;
          const [x, y] = place(acquired.x - half, acquired.y - half);
          const side = acquired.frameUm * scale;
          ctx.strokeStyle = "#ffffff"; ctx.lineWidth = chosen ? 4 : 3;
          ctx.strokeRect(x, y, side, side);
          ctx.strokeStyle = css("--accent"); ctx.lineWidth = chosen ? 1.5 : 1;
          if (hovered) ctx.setLineDash([4, 3]);
          ctx.strokeRect(x, y, side, side);
          ctx.setLineDash([]);
        }
      }
    },
  },
  };
}
