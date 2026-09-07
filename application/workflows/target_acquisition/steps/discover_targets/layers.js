/**
 * What step 6 draws on the picture: the cells found, and the field being tuned on.
 *
 * The test field is a separate layer and stays solid, because it says which
 * position the channel's preview is of — a question about what you are looking
 * at rather than a thing the run produced.
 */
import { dressTheMask } from "./mask-dress.js";
import { activeRecording } from "../../../../parts/microscope/recordings.js";
/* One mask picture per field, fetched when first painted. A field whose
   detection has not run answers 404; that is remembered briefly and asked
   again, because a discovery marching across the sample fills them in. */
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

/* The map for a field as it stands: ready with its labels, still on its
   way, or failed -- and a failed one is asked for again after a while. */
function labelMap(base, label, redraw) {
  const held = labelMaps.get(label);
  if (held && (held.ready || !held.failed || performance.now() - held.failed < 5000)) return held;
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
  img.onerror = () => { keep.failed = performance.now(); redraw(); };
  img.src = `${base}/${label}.labels.png?d=${discovery}`;
  return keep;
}

/* One bitmap per field per selection: the lit shapes cut from the label
   map, each in its own ink, then dressed the way the operator dressed the
   targets in their card -- one colour over all, filled or outlined.
   Rebuilt only when what is lit or the dress changes, drawn as a picture
   after that; the dress's opacity is applied at the drawing.

   Answers with the field's state: the shapes, or that the map is still on
   its way, or that it failed. The three are drawn differently -- a map on
   its way is drawn as nothing, since a dot that turns into a shape a
   moment later read as a flash on the picture. */
const shapeOverlays = new Map();
function shapeOverlay(base, fieldLabel, wanted, dress, redraw) {
  const stamp = [...wanted.entries()].map(([l, c]) => `${l}${c}`).sort().join(",")
    + `|${dress.colour}|${dress.show}`;
  const held = shapeOverlays.get(fieldLabel);
  if (held && held.stamp === stamp) return { shapes: held.canvas };
  const map = labelMap(base, fieldLabel, redraw);
  if (!map.ready) return map.failed ? { failed: true } : { loading: true };
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
    out.data[p + 3] = 255;
  }
  paint.putImageData(out, 0, 0);
  const dressed = dressTheMask(cv, {
    size: map.w, colour: dress.colour ?? null, mode: dress.show === "line" ? "line" : "fill",
  });
  shapeOverlays.set(fieldLabel, { stamp, canvas: dressed });
  return { shapes: dressed };
}

/* One dressed mask per field per mask layer, in the colour and look the
   operator chose for that layer, rebuilt only when that choice changes. */
const dressedMasks = new Map();

function dressedMask(label, img, layer) {
  const colour = layer.dress.colour ?? null;
  const mode = layer.dress.show === "line" ? "line" : "fill";
  const stamp = `${colour}|${mode}|${discovery}`;
  const key = `${layer.id}:${label}`;
  const held = dressedMasks.get(key);
  if (held && held.stamp === stamp) return held.canvas;
  const canvas = dressTheMask(img, { size: img.naturalWidth || img.width, colour, mode });
  dressedMasks.set(key, { stamp, canvas });
  return canvas;
}

/** The masks are forgotten when a discovery begins: a field's mask from a
    tile test would otherwise stand in for the run's own until the page was
    reopened. */
export function forgetTheMasks() {
  maskImages.clear();
  dressedMasks.clear();
  /* And the label maps and the shapes lit from them: kept, a field's
     old map was lit with the new run's label numbers, and the wrong
     objects -- whole merged regions -- came up in blue. */
  labelMaps.clear();
  shapeOverlays.clear();
  discovery += 1;
}

export function targetLayers(theRun) {
  const { run, css, drawnIn, activeMode, redraw, whereTheStageIs, toCarrier } = theRun;
  /* Before a scan has taken anything, the current field is the one the
     stage stands over: its position, in the overview's frame. */
  const beforeTheScan = () => activeMode === "scan" && !(run.tilesShown > 0);
  const theFieldUnderTheStage = (frameUm) => {
    const here = whereTheStageIs?.();
    if (!here || !frameUm) return null;
    const at = toCarrier(here);
    return { x: at.x, y: at.y, frameUm };
  };
  /* Which field the frame is about, in the frame of the recording active
     on the step: before the scan, the field under the stage in the
     overview's; on the steps about the targets, the current target tile
     once tiles are placed, else the field under the stage in the target
     settings' -- so importing a closer job shrinks it there and then;
     otherwise the current field of the plan, which is the field detection
     was last on. There is one from the first plan on, on every step, so
     Tile always has somewhere to go. */
  const theTargetTiles = () => run.targetTiles ?? [];
  /* The focus frame, while there is one: the chosen point in the
     focussing settings' frame, which the focus layer draws on the focus
     step. It is the position there; two frames stood on that step, this
     layer's on the plan's field and the focus layer's on the point, and
     the operator asked which was the position. */
  const theFocusFrame = () => {
    if (activeMode !== "focus") return null;
    const at = run.focus.points[run.focus.selected];
    const frameUm = activeRecording(run.focusPreset)?.frameUm;
    return at && frameUm ? { x: at.x, y: at.y, frameUm } : null;
  };
  const theCurrentField = () => {
    const focus = theFocusFrame();
    if (focus) return focus;
    if (beforeTheScan()) return theFieldUnderTheStage(run.plan[0]?.frameUm);
    if (activeMode === "select" || activeMode === "targets") {
      const tiles = theTargetTiles();
      if (!tiles.length) return theFieldUnderTheStage(run.targetFrameUm);
      /* While the targets are being taken the frame is on the stage: it
         goes with the crosshair from tile to tile, where the acquisition
         is, rather than standing on the tile Tile last framed. */
      if (activeMode === "targets" && run.running) return theFieldUnderTheStage(run.targetFrameUm);
      const t = tiles[Math.min(run.detect.targetTile ?? 0, tiles.length - 1)];
      return { x: t.x, y: t.y, frameUm: t.frameUm ?? run.targetFrameUm };
    }
    return run.plan[run.detect.tile];
  };
  /* The tile after the current one, in reading order and round again: what
     Tile goes to when the current one is already framed. Before the scan the
     frame is the stage's, and the stage is not walked from here. */
  const theNextField = () => {
    if (beforeTheScan()) return;
    if (activeMode === "select" || activeMode === "targets") {
      const n = theTargetTiles().length;
      if (n) run.detect.targetTile = ((run.detect.targetTile ?? 0) + 1) % n;
      return;
    }
    if (run.plan.length) run.detect.tile = (run.detect.tile + 1) % run.plan.length;
  };
  /* How far a press reaches, in world units. Taken from the last paint --
     which always precedes a press -- because `reaches` is handed a place and
     no frame; reading `scale` here was a ReferenceError, and every click on
     a cell died on it. */
  let reach = 12 / 0.03;
  return {
    cells: {
    key: "cells",
    label: "Cells",
    explains: "Targets selected for the workflow. Before feature gating every candidate is "
      + "shown; afterwards only targets inside the gate remain.",
    /* The chosen cells' shapes belong to the steps that choose and image
       them. On the discovery step the masks themselves are on the picture;
       on the acquisition step the frames are, and a lit shape over a frame
       hides the very pixels it was imaged for -- so there the layer's eye
       is pressed off for the operator on the way in, and its cell stays in
       the strip for a look. */
    shown: run.cellsShown && ["gate", "select", "targets"].includes(activeMode),
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

      /* The chosen, in their own segmented shapes: each target's mask
         pixels lit. A dot says less than the shape itself, so it is only
         the honest fallback for a target whose shape cannot be had -- a
         field whose label map failed to load, or a target with no label. */
      const gr = Math.max(3, 4.2 * Math.sqrt(scale / 0.03));
      /* One population, one colour. Step 7 starts with all candidates so the
         operator can see what there is to gate, then removes everything the
         gate excluded. Step 8 narrows once more to the targets its ceiling
         kept. Nothing irrelevant is carried forward under another colour. */
      const lit = activeMode === "gate"
        ? (run.done?.has("select") ? run.restricted
          : run.gates.length ? run.gated : new Set(run.cells.keys()))
        : (run.restricted.size ? run.restricted : run.gated);
      if (activeMode !== "detect" && lit.size) {
        const uncovered = new Set((run.tilePlan?.uncovered ?? []).map((one) => one.id ?? one));
        const inkOf = (id) => css(uncovered.has(id) ? "--warn-ink" : "--mark-selected");
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
        const dress = run.targetsDress;
        ctx.globalAlpha = dress.alpha;
        for (const [field, wanted] of byField) {
          const t = run.plan[field];
          const fieldLabel = run.fieldLabels[field];
          const over = base && t ? shapeOverlay(base, fieldLabel, wanted, dress, redraw) : { failed: true };
          if (over.shapes) {
            const half = t.frameUm / 2;
            const [x, y] = place(t.x - half, t.y - half);
            ctx.drawImage(over.shapes, x, y, t.frameUm * scale, t.frameUm * scale);
          } else if (over.failed) {
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
          ctx.fillStyle = dress.colour ?? inkOf(c.id);
          ctx.fill();
          ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
    },
    reaches: (at) => {
      let best = reach, hit = null;
      const ids = activeMode === "gate"
        ? (run.done?.has("select") ? run.restricted
          : run.gates.length ? run.gated : new Set(run.cells.keys()))
        : (run.restricted.size ? run.restricted : run.gated);
      for (const id of ids) {
        const c = run.cells.get(id);
        if (!c) continue;
        const d = Math.hypot(c.x - at.x, c.y - at.y);
        if (d < best) { best = d; hit = c; }
      }
      return hit;
    },
  },
    segmentation: {
    key: "segmentation",
    label: "Object detection",
    explains: "Cellpose's masks laid over the fields they were found in, each "
      + "object in its own colour -- what detection actually saw, not just "
      + "where it put a point.",
    /* The run has masks once detection has examined a field, and keeps
       them through every step after: the canvas shows them until the
       operator turns them off, and its button brings them back. They are
       the run's, not a tile test's: a test is judged in the panel's own
       picture, and the canvas shows the masks as the run lays them down,
       field by field. */
    has: run.examined.size > 0,
    /* Shown while any mask layer on the overview is: the layer's own
       switch is the cell in the masks bar, and the canvas's layer button
       stands over all of them. */
    shown: (run.masks ?? []).some((one) => one.kind === "overview" && one.shown),
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale, w, h } = drawnIn(frame);
      const base = run.overviewPictures;
      if (!base) return;
      const layers = (run.masks ?? []).filter((one) => one.kind === "overview" && one.shown);
      if (!layers.length) return;
      for (let i = 0; i < run.plan.length; i++) {
        const label = run.fieldLabels[i];
        /* Only fields the run has examined: a mask file a tile test left
           beside a field's picture is the test's, and stood in for the
           run's the moment Detect objects was pressed. */
        if (!label || !run.examined.has(i)) continue;
        const t = run.plan[i];
        const half = t.frameUm / 2;
        const [x, y] = place(t.x - half, t.y - half);
        const size = t.frameUm * scale;
        if (x > w || y > h || x + size < 0 || y + size < 0) continue;
        const img = maskImage(base, label, redraw);
        if (!img) continue;
        /* Worn the way the operator dressed the layer -- colour, fill or
           line, opacity -- in its card in the masks bar. */
        for (const layer of layers) {
          ctx.globalAlpha = layer.dress.alpha;
          ctx.drawImage(dressedMask(label, img, layer), x, y, size, size);
        }
        ctx.globalAlpha = 1;
      }
    },
  },
    detect: {
    key: "detect",
    label: "Current field",
    explains: "The one position detection is being tuned on, so the canvas says which "
      + "tile the channel's preview is of.",
    /* On every step from the first plan on: the current tile is the one
       the run is on, and the frame says which, whatever the step. */
    shown: !!theCurrentField(),
    staysSolid: true,
    /* Where the frame stands, for the canvas's own press that brings the
       view in on it, and the way on to the next one. */
    field: theCurrentField,
    next: theNextField,
    paint: (frame) => {
      /* While the focus frame stands, the focus layer draws it on the
         point; drawn here too, two frames stood for one position. The
         field stays the layer's, so Tile still has somewhere to go. */
      if (theFocusFrame()) return;
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      const t = theCurrentField();
      if (!t) return;
      const half = t.frameUm / 2;
      const [x, y] = place(t.x - half, t.y - half);
      /* Black on a white halo: readable on the tissue and on the dark
         ground alike, and not one more blue on a picture full of them. */
      const side = t.frameUm * scale;
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 5;
      ctx.strokeRect(x, y, side, side);
      ctx.strokeStyle = "#000000"; ctx.lineWidth = 2.5;
      ctx.strokeRect(x, y, side, side);
      ctx.strokeStyle = "#dc2626"; ctx.lineWidth = 1;
      ctx.strokeRect(x, y, side, side);

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
