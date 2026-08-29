/**
 * Step 6 — finding the targets: the settings, and the one field they are
 * tried on before the whole overview is run.
 *
 * Detection is tuned rather than configured: a diameter that is well off the
 * truth loses objects at both ends, and the only way to see that is to look.
 * So the channel shows one field of the overview, its picture, with every
 * object the settings found drawn over it. The finding is the analysis's: the
 * page asks the backend and draws what comes back, with the same settings the
 * run then applies to every field — what is tried here and what is run there
 * is one request, not two that agree today.
 */

/** The algorithms this page offers, and what their settings mean. */
/* One, for now. A plain brightness threshold was offered beside it and is
   parked rather than deleted — the row that chose between the two comes back
   the day a second is wanted. A picker with one option in it is a control
   that cannot be used. */
export const ALGOS = {
  cellpose: {
    label: "Cellpose",
    blurb: "Diameter is the size it looks for; cell probability is how sure it has to be.",
  },
};

/**
 * The settings as the backend is asked for them: what detection needs, and
 * nothing the page keeps for its own bookkeeping.
 */
export const settingsFor = (settings) => ({
  diameter: settings.diameter, cellprob: settings.cellprob,
});

/** Golden-angle hues, so neighbouring labels never share a colour. */
export const labelColour = (n, alpha = 1) =>
  `hsla(${(n * 137.508) % 360}, 68%, 58%, ${alpha})`;

export default {
  id: "detect",
  label: "Discover Targets",

  /**
   * Build the channel and draw the field being tried on.
   *
   * `ctx` carries:
   *   `settings()`   the detection settings, changed here; `tile` is the field
   *                  being tried on, `tested` whether it has been, `tried`
   *                  what was found there
   *   `plan()`       the fields, one of which is being looked at
   *   `tryOn(field, settings)`  ask the backend for this one field's targets;
   *                  resolves `{ cells, position_label }`
   *   `pictureOf(label)`  where a field's picture is, or null when the backend
   *                  makes none
   *   `sizeCanvas(cv)` `css(name)` `drawScaleBar(ctx, w, h, scale)`  plumbing
   *   `changed()`    say that what the page shows around this has changed
   *
   * Returns a handle whose `redraw()` draws it again — after the canvas has
   * been used to pick a different field, or on a theme change.
   */
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "detect-side";

    const head = document.createElement("div");
    head.className = "side-head";
    head.textContent = "Cellpose segmentation";

    const bar = document.createElement("div");
    bar.className = "detect-bar";
    const params = document.createElement("div");
    params.className = "detect-params";
    bar.append(params);

    const testHead = document.createElement("div");
    testHead.className = "side-head";
    testHead.append("Test position");
    const picker = document.createElement("span");
    picker.className = "tile-pick";
    const prev = document.createElement("button");
    prev.type = "button"; prev.className = "ghost tiny";
    prev.setAttribute("aria-label", "previous position");
    prev.textContent = "◀";
    const which = document.createElement("span");
    which.id = "tile-label";
    const next = document.createElement("button");
    next.type = "button"; next.className = "ghost tiny";
    next.setAttribute("aria-label", "next position");
    next.textContent = "▶";
    picker.append(prev, which, next);
    testHead.append(picker);

    const canvasHost = document.createElement("div");
    canvasHost.className = "tile-host";
    const cv = document.createElement("canvas");
    cv.id = "tile-canvas";
    canvasHost.append(cv);

    const readout = document.createElement("div");
    readout.className = "side-note";
    readout.id = "detect-readout";

    side.append(head, bar, testHead, canvasHost, readout);
    host.append(side);

    /* The field's picture, fetched once a field has been tried and drawn when
       it arrives. */
    let picture = null;
    function showThePictureOf(label) {
      const where = ctx.pictureOf(label);
      picture = null;
      if (!where) return;
      const img = new Image();
      img.onload = () => { picture = img; drawTheTile(); };
      img.src = where;
    }

    /** The field being tried on, drawn larger than life. */
    function drawTheTile() {
      if (!ctx.sizeCanvas(cv)) return;
      const paint = cv.getContext("2d");
      const w = cv.cssW, h = cv.cssH;
      const settings = ctx.settings();

      paint.clearRect(0, 0, w, h);
      paint.fillStyle = ctx.css("--surface-3");
      paint.fillRect(0, 0, w, h);

      const tile = ctx.plan()[settings.tile];
      if (!tile) return;
      const frame = tile.frameUm;
      const pad = 18;
      const scale = Math.min((w - 2 * pad) / frame, (h - 2 * pad) / frame);
      const ox = (w - frame * scale) / 2, oy = (h - frame * scale) / 2;
      const X = (x) => ox + (x - (tile.x - frame / 2)) * scale;
      const Y = (y) => oy + (y - (tile.y - frame / 2)) * scale;

      paint.save();
      paint.beginPath();
      paint.rect(ox, oy, frame * scale, frame * scale);
      paint.clip();

      paint.fillStyle = "#05090e";
      paint.fillRect(ox, oy, frame * scale, frame * scale);
      if (picture) paint.drawImage(picture, ox, oy, frame * scale, frame * scale);

      /* What the settings found here, each object at its own size: the point
         of this view is to judge whether the diameter is right. */
      (settings.tested ? settings.tried : []).forEach((cell, n) => {
        const r = Math.max(3, cell.r * scale);
        paint.beginPath(); paint.arc(X(cell.x), Y(cell.y), r, 0, Math.PI * 2);
        paint.fillStyle = labelColour(n, 0.35);
        paint.fill();
        paint.lineWidth = 1.4;
        paint.strokeStyle = labelColour(n, 1);
        paint.stroke();
      });
      paint.restore();

      paint.strokeStyle = ctx.css("--line-strong");
      paint.lineWidth = 1;
      paint.strokeRect(ox + 0.5, oy + 0.5, frame * scale - 1, frame * scale - 1);
      ctx.drawScaleBar(paint, w, h, scale);
    }

    /** The settings, the position picker and the sentence underneath. */
    function drawTheControls() {
      const settings = ctx.settings();
      which.textContent = `${settings.tile + 1} / ${ctx.plan().length}`;

      params.textContent = "";
      const number = (label, key, min, max, step, unit) => {
        const wrap = document.createElement("div");
        wrap.className = "param";
        wrap.innerHTML = `<label>${label}</label>`
          + `<input type="number" min="${min}" max="${max}" step="${step}">`
          + (unit ? `<span class="hint">${unit}</span>` : "");
        const input = wrap.querySelector("input");
        input.value = settings[key];
        input.addEventListener("input", () => {
          settings[key] = Number(input.value);
          // a setting changed is a test undone: what was tried is not this
          settings.tested = false;
          refresh();
        });
        params.append(wrap);
      };

      number("Diameter", "diameter", 4, 200, 1, "µm");
      number("Cell prob.", "cellprob", -6, 6, 0.5, "");

      const test = document.createElement("button");
      test.className = "ghost";
      test.type = "button";
      test.textContent = "Test on this tile";
      test.addEventListener("click", () => {
        settings.tested = false;
        readout.textContent = `looking at position ${settings.tile + 1}…`;
        ctx.tryOn(settings.tile, settingsFor(settings)).then((found) => {
          settings.tried = found.cells;
          settings.tested = true;
          showThePictureOf(found.position_label);
          refresh();
        }, (why) => { readout.textContent = why.message; });
      });
      params.append(test);

      if (settings.tested) {
        readout.textContent =
          `${settings.tried.length} objects at position ${settings.tile + 1}`;
      } else {
        readout.textContent = ALGOS[settings.algo].blurb;
      }
    }

    function refresh() {
      drawTheControls();
      drawTheTile();
      ctx.changed();
    }

    for (const [button, step] of [[prev, -1], [next, 1]]) {
      button.addEventListener("click", () => {
        const settings = ctx.settings();
        const total = ctx.plan().length || 1;
        settings.tile = (settings.tile + step + total) % total;
        settings.tested = false;
        picture = null;
        refresh();
      });
    }

    new ResizeObserver(() => drawTheTile()).observe(canvasHost);

    drawTheControls();
    drawTheTile();
    return { redraw: () => { drawTheControls(); drawTheTile(); } };
  },
};
