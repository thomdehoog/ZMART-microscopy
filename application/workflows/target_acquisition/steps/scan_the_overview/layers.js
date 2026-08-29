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
    explains: "The field the stage is imaging right now. What has been taken needs no "
      + "mark of its own: the scan's picture shows through the ground exactly there.",
    shown: shown > 0,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      /* Nothing is painted over a taken field: the pixels beneath are what
         was imaged there, and an outline on a window's edge survived the cut
         as a hairline over the tissue. */

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
