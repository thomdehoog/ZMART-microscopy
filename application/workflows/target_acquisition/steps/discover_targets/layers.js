/**
 * What step 6 draws on the picture: the cells found, and the field being tuned on.
 *
 * The test field is a separate layer and stays solid, because it says which
 * position the channel's preview is of — a question about what you are looking
 * at rather than a thing the run produced.
 */
/* One mask picture per field, fetched when first painted. A field whose
   detection has not run answers 404; that is remembered briefly and asked
   again, because a discovery marching across the sample fills them in. */
const maskImages = new Map();

function maskImage(base, label, redraw) {
  const held = maskImages.get(label);
  if (held) {
    if (held.ready) return held.img;
    if (!held.failed || performance.now() - held.failed < 5000) return null;
  }
  const img = new Image();
  const keep = { img, ready: false, failed: 0 };
  maskImages.set(label, keep);
  img.onload = () => { keep.ready = true; redraw(); };
  img.onerror = () => { keep.failed = performance.now(); };
  img.src = `${base}/${label}.mask.png`;
  return null;
}

export function targetLayers(theRun) {
  const { run, css, drawnIn, activeMode, redraw } = theRun;
  /* How far a press reaches, in world units. Taken from the last paint --
     which always precedes a press -- because `reaches` is handed a place and
     no frame; reading `scale` here was a ReferenceError, and every click on
     a cell died on it. */
  let reach = 12 / 0.03;
  return {
    cells: {
    key: "cells",
    label: "Cells",
    explains: "What detection found. The ones that passed the gate are ringed, so which "
      + "is which does not rest on colour alone.",
    shown: run.cellsShown && ["detect", "select", "acquire"].includes(activeMode),
    /* Readable over the very fields they were found in: the see-through
       windows that reveal the picture cut every layer beneath them, and the
       objects were cut away exactly where the tissue is. The layer's own
       button remains the way to put them away. */
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      reach = 12 / scale;
      const ctxRad = Math.max(1.1, 1.4 * Math.sqrt(scale / 0.03));
      /* Each step its own funnel: discovery shows everything found and
         nothing chosen; refine and acquisition show the chosen alone --
         context dots on the tissue read as clutter once the step is about
         the selection. */
      if (activeMode === "detect") {
        ctx.fillStyle = css("--mark-context");
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        for (const c of run.cells.values()) {
          if (activeMode !== "detect" && run.gated.has(c.id)) continue;
          const [x, y] = place(c.x, c.y);
          if (x < -8 || y < -8 || x > w + 8 || y > h + 8) continue;
          ctx.moveTo(x + ctxRad, y);
          ctx.arc(x, y, ctxRad, 0, Math.PI * 2);
        }
        ctx.fill();
        ctx.globalAlpha = 1;
      }

      // gated cells — ringed, so identity is not carried by colour alone
      const gr = Math.max(3, 4.2 * Math.sqrt(scale / 0.03));
      for (const id of (activeMode === "detect" ? [] : run.gated)) {
        const c = run.cells.get(id);
        if (!c) continue;
        const [x, y] = place(c.x, c.y);
        if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
        ctx.beginPath(); ctx.arc(x, y, gr, 0, Math.PI * 2);
        ctx.fillStyle = "#0284c7"; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
      }
    },
    reaches: (at) => {
      let best = reach, hit = null;
      for (const c of run.cells.values()) {
        const d = Math.hypot(c.x - at.x, c.y - at.y);
        if (d < best) { best = d; hit = c; }
      }
      return hit;
    },
  },
    segmentation: {
    key: "segmentation",
    label: "Segmentation",
    explains: "Cellpose's masks laid over the fields they were found in, each "
      + "object in its own colour -- what detection actually saw, not just "
      + "where it put a point.",
    /* The masks belong to the step that tunes them: from the refine step
       on, the picture is about the selection, and later the acquisition.
       The layer's own button still brings them back wherever wanted. */
    shown: activeMode === "detect",
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      const base = run.overviewPictures;
      if (!base) return;
      for (let i = 0; i < run.plan.length; i++) {
        const label = run.fieldLabels[i];
        if (!label) continue;
        const t = run.plan[i];
        const half = t.frameUm / 2;
        const [x, y] = place(t.x - half, t.y - half);
        const size = t.frameUm * scale;
        if (x > w || y > h || x + size < 0 || y + size < 0) continue;
        const img = maskImage(base, label, redraw);
        if (!img) continue;
        ctx.globalAlpha = 0.45;
        ctx.drawImage(img, x, y, size, size);
        ctx.globalAlpha = 1;
      }
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

      /* And the one under the pointer, lightly: the press it invites picks
         it as the test position. */
      const over = run.plan[run.detect.hovered];
      if (over && run.detect.hovered !== run.detect.tile) {
        const oh = over.frameUm / 2;
        const [hx, hy] = place(over.x - oh, over.y - oh);
        ctx.globalAlpha = 0.5;
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeRect(hx, hy, over.frameUm * scale, over.frameUm * scale);
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }
    },
  },
  };
}
