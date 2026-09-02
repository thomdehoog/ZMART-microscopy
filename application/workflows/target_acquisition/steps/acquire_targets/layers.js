/**
 * What step 8 draws on the picture: the targets that have been imaged.
 */

export function acquiredLayers(theRun) {
  const { run, drawnIn, activeMode } = theRun;
  return {
    targets: {
    key: "targets",
    label: "Targets",
    explains: "The cells that have been imaged at high resolution -- each "
      + "acquired frame printed where it was taken, with a ring to find it by.",
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
        /* The frames speak for themselves; only the chosen one -- whose
           pair the gallery shows -- is ringed, so it is found among them. */
        if (run.selectedTarget === id) {
          const [x, y] = place(c.x, c.y);
          const rr = Math.max(7, 9 * Math.sqrt(scale / 0.03));
          ctx.beginPath(); ctx.arc(x, y, rr + 2, 0, Math.PI * 2);
          ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 5; ctx.stroke();
          ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2);
          ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 2.2; ctx.stroke();
        }
      }
    },
  },
  };
}
