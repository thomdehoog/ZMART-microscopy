/**
 * What step 8 draws on the picture: the targets that have been imaged.
 */
export function acquiredLayers(theRun) {
  const { run, drawnIn } = theRun;
  return {
    targets: {
    key: "targets",
    label: "Targets",
    explains: "The cells that have been imaged at high resolution.",
    shown: run.acquired.length > 0,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      for (const id of run.acquired) {
        const c = run.cells.get(id);
        const [x, y] = place(c.x, c.y);
        const rr = Math.max(7, 9 * Math.sqrt(scale / 0.03));
        ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2);
        ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 2.2; ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = "#16a34a"; ctx.fill();
      }
    },
  },
  };
}
