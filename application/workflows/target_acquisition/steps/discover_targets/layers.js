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
import { cellsInAllGates } from "../refine_targets/gating.js";

const maskImages = new Map();
/* Which discovery the pictures belong to: a new one asks for every file
   afresh, past the browser's own cache of the same address. */
let discovery = 0;

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
  img.src = `${base}/${label}.mask.png?d=${discovery}`;
  return null;
}

/* The raw label masks, read back pixel by pixel: each pixel's label rides
   in the PNG's colour bytes, so any one object's true shape can be lit. */
const labelMaps = new Map();

function labelMap(base, label, redraw) {
  const held = labelMaps.get(label);
  if (held) {
    if (held.ready) return held;
    if (!held.failed || performance.now() - held.failed < 5000) return null;
  }
  const img = new Image();
  img.crossOrigin = "anonymous";
  const keep = { img, ready: false, failed: 0, w: 0, h: 0, labels: null };
  labelMaps.set(label, keep);
  img.onload = () => {
    const cv = document.createElement("canvas");
    cv.width = img.naturalWidth; cv.height = img.naturalHeight;
    const paint = cv.getContext("2d");
    paint.drawImage(img, 0, 0);
    const px = paint.getImageData(0, 0, cv.width, cv.height).data;
    const labels = new Int32Array(cv.width * cv.height);
    for (let i = 0, p = 0; i < labels.length; i++, p += 4) {
      if (px[p + 3]) labels[i] = px[p] | (px[p + 1] << 8) | (px[p + 2] << 16);
    }
    keep.w = cv.width; keep.h = cv.height; keep.labels = labels; keep.ready = true;
    redraw();
  };
  img.onerror = () => { keep.failed = performance.now(); };
  img.src = `${base}/${label}.labels.png?d=${discovery}`;
  return null;
}

/* One tinted bitmap per field per selection: rebuilt only when what is lit
   there changes, drawn as a picture after that. */
const shapeOverlays = new Map();

function shapeOverlay(base, fieldLabel, wanted, redraw) {
  const stamp = [...wanted.entries()].map(([l, c]) => `${l}${c}`).sort().join(",");
  const held = shapeOverlays.get(fieldLabel);
  if (held && held.stamp === stamp) return held.canvas;
  const map = labelMap(base, fieldLabel, redraw);
  if (!map) return null;
  const cv = document.createElement("canvas");
  cv.width = map.w; cv.height = map.h;
  const paint = cv.getContext("2d");
  const out = paint.createImageData(map.w, map.h);
  const colours = new Map();
  for (const [l, hex] of wanted) {
    colours.set(l, [
      parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16),
      parseInt(hex.slice(5, 7), 16),
    ]);
  }
  for (let i = 0, p = 0; i < map.labels.length; i++, p += 4) {
    const c = colours.get(map.labels[i]);
    if (!c) continue;
    out.data[p] = c[0]; out.data[p + 1] = c[1]; out.data[p + 2] = c[2];
    out.data[p + 3] = 170;
  }
  paint.putImageData(out, 0, 0);
  shapeOverlays.set(fieldLabel, { stamp, canvas: cv });
  return cv;
}

/** The masks are forgotten when a discovery begins: a field's mask from a
    tile test would otherwise stand in for the run's own until the page was
    reopened. */
export function forgetTheMasks() {
  maskImages.clear();
  /* And the label maps and the shapes lit from them: kept, a field's
     old map was lit with the new run's label numbers, and the wrong
     objects -- whole merged regions -- came up in blue. */
  labelMaps.clear();
  shapeOverlays.clear();
  discovery += 1;
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
    /* The chosen cells' shapes belong to the step that chooses them. On the
       discovery step the masks themselves are on the picture; on the
       acquisition step the frames are, and a lit shape over a frame hid the
       very pixels it was imaged for. */
    shown: run.cellsShown && activeMode === "select",
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
      /* Only the chosen cells are drawn: a grey dot on every candidate
         read as an artefact on the picture, and the masks on the discovery
         step already showed the whole population. */

      /* The chosen, in their own segmented shapes: each selected cell's
         mask pixels lit in accent, acquired ones in green -- a blob where a
         cell stands says less than the cell itself. A field whose label map
         has not arrived yet falls back to the blob, honestly. */
      const gr = Math.max(3, 4.2 * Math.sqrt(scale / 0.03));
      /* The plot's marks, on the picture: what the gates let through in
         blue while they are drawn; once Restrict has drawn under the
         ceiling, what it kept in green and nothing else -- the rest of the
         gate's catch is not the selection any more. */
      const restricted = run.done.has("select");
      const lit = restricted ? run.gated : cellsInAllGates([...run.cells.values()], run.gates);
      if (activeMode !== "detect" && lit.size) {
        const inkOf = () => css(restricted ? "--mark-selected" : "--mark-gated");
        const byField = new Map();
        const strays = [];
        for (const id of lit) {
          const c = run.cells.get(id);
          if (!c) continue;
          const fieldLabel = run.fieldLabels[c.field];
          if (Number.isFinite(c.label) && fieldLabel) {
            if (!byField.has(c.field)) byField.set(c.field, new Map());
            byField.get(c.field).set(c.label, inkOf(id));
          } else {
            strays.push(c);
          }
        }
        const base = run.overviewPictures;
        for (const [field, wanted] of byField) {
          const t = run.plan[field];
          const fieldLabel = run.fieldLabels[field];
          const over = base && t ? shapeOverlay(base, fieldLabel, wanted, redraw) : null;
          if (over) {
            const half = t.frameUm / 2;
            const [x, y] = place(t.x - half, t.y - half);
            ctx.drawImage(over, x, y, t.frameUm * scale, t.frameUm * scale);
          } else {
            for (const label of wanted.keys()) {
              const c = [...run.cells.values()].find(
                (one) => one.field === field && one.label === label);
              if (c) strays.push(c);
            }
          }
        }
        for (const c of strays) {
          const [x, y] = place(c.x, c.y);
          if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
          ctx.beginPath(); ctx.arc(x, y, gr, 0, Math.PI * 2);
          ctx.fillStyle = inkOf(c.id);
          ctx.fill();
          ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
        }
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
       The layer's own button still brings them back wherever wanted. And
       they are the run's, not a tile test's: a test is judged in the
       panel's own picture, and the canvas shows the masks as the run lays
       them down, field by field. */
    shown: activeMode === "detect" && run.cellsShown,
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      const base = run.overviewPictures;
      if (!base) return;
      for (let i = 0; i < run.plan.length; i++) {
        const label = run.fieldLabels[i];
        /* Only fields the run has examined: a mask file a tile test left
           beside a field's picture is the test's, and stood in for the
           run's the moment Segment all was pressed. */
        if (!label || !run.examined.has(i)) continue;
        const t = run.plan[i];
        const half = t.frameUm / 2;
        const [x, y] = place(t.x - half, t.y - half);
        const size = t.frameUm * scale;
        if (x > w || y > h || x + size < 0 || y + size < 0) continue;
        const img = maskImage(base, label, redraw);
        if (!img) continue;
        ctx.globalAlpha = 0.8;
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
