/**
 * What step 8 draws on the picture: the targets that have been imaged.
 */

/* The acquired frames' pictures, by their capture label, fetched once and
   redrawn into place when they arrive -- the same arrangement as the
   segmentation masks. */
const pictures = new Map();

function targetPicture(base, label, redraw) {
  const held = pictures.get(label);
  if (held !== undefined) return held;
  pictures.set(label, null);
  const img = new Image();
  img.onload = () => { pictures.set(label, img); redraw(); };
  /* A miss is forgotten, not kept: a view asked for a beat too early would
     otherwise stay a hole forever -- the next redraw simply asks again. */
  img.onerror = () => pictures.delete(label);
  img.src = `${base}/${label}.jpg`;
  return null;
}

export function acquiredLayers(theRun) {
  const { run, drawnIn, activeMode, redraw } = theRun;
  return {
    targets: {
    key: "targets",
    label: "Targets",
    explains: "The cells that have been imaged at high resolution -- each "
      + "acquired frame printed where it was taken, with a ring to find it by.",
    shown: activeMode === "acquire" && run.acquired.length > 0,
    /* Readable over the very fields they were acquired in, like the cells
       and the masks: the see-through windows cut every non-solid layer, and
       the green rings survived only off the picture. */
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      const base = run.targetPictures;
      const frameUm = run.targetFrameUm;
      for (const id of run.acquired) {
        const c = run.cells.get(id);
        if (!c) continue;
        /* The acquired frame itself, standing on the overview at its true
           size and place: the high-res pixels are the layer's whole point,
           and the ring still says "imaged" while a picture is on its way. */
        const label = run.acquiredLabels?.[id];
        if (base && label && frameUm) {
          const half = frameUm / 2;
          const [px, py] = place(c.x - half, c.y - half);
          const size = frameUm * scale;
          if (!(px > w || py > h || px + size < 0 || py + size < 0)) {
            const img = targetPicture(base, label, redraw);
            if (img) {
              ctx.drawImage(img, px, py, size, size);
              ctx.strokeStyle = "#16a34a";
              ctx.lineWidth = 1;
              ctx.strokeRect(px + 0.5, py + 0.5, size - 1, size - 1);
            }
          }
        }
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
