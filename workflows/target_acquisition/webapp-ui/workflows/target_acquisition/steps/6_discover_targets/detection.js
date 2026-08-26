/**
 * Step 6 — finding the targets: the settings, and the one position they are
 * tried on before the whole sample is run.
 *
 * Detection is tuned rather than configured: a diameter that is well off the
 * truth loses objects at both ends, and the only way to see that is to look.
 * So the channel shows one position, drawn with every object the settings
 * would keep coloured and every object they would throw away still visible —
 * what a setting discards matters as much as what it keeps.
 *
 * The rule itself is exported, because the run applies it to every position
 * once the operator is satisfied with it: what is tried here and what is run
 * there must be the same sentence, not two that agree today.
 */

/** The algorithms this page offers, and what their settings mean. */
export const ALGOS = {
  cellpose: {
    label: "Cellpose",
    blurb: "Diameter is the size it looks for; cell probability is how sure it has to be.",
  },
  threshold: {
    label: "Threshold",
    blurb: "Everything brighter than the level, larger than the minimum area.",
  },
};

/**
 * Whether these settings would keep this object. The one rule of the step,
 * used by the tile test and by the run across the whole sample.
 */
export function detects(settings, cell) {
  if (settings.algo === "cellpose") {
    const diameter = 2 * cell.r;
    /* A diameter well off the truth costs objects at both ends — which is the
       whole reason to try it on one position before running the sample. */
    return diameter > settings.diameter * 0.70
      && diameter < settings.diameter * 1.55
      && cell.intensity > 0.36 + settings.cellprob * 0.05;
  }
  return cell.intensity >= settings.thresh && cell.area >= settings.minArea;
}

/** Golden-angle hues, so neighbouring labels never share a colour. */
export const labelColour = (id, alpha = 1) =>
  `hsla(${(id * 137.508) % 360}, 68%, 58%, ${alpha})`;

export default {
  id: "detect",
  label: "Discover Targets",

  /**
   * Build the channel and draw the position being tried on.
   *
   * `ctx` carries:
   *   `settings()`   the detection settings, changed here
   *   `plan()`       the positions, one of which is being looked at
   *   `cellsInTile(i)` `density(x, y)`  what the sample has there
   *   `sizeCanvas(cv)` `css(name)` `drawScaleBar(ctx, w, h, scale)`  plumbing
   *   `changed()`    say that what the page shows around this has changed
   *
   * Returns a handle whose `redraw()` draws it again — after the canvas has
   * been used to pick a different position, or on a theme change.
   */
  mount(host, ctx) {
    const side = document.createElement("div");
    side.className = "detect-side";

    const head = document.createElement("div");
    head.className = "side-head";
    head.textContent = "Detection";

    const bar = document.createElement("div");
    bar.className = "detect-bar";
    const algos = document.createElement("div");
    algos.className = "seg";
    algos.setAttribute("role", "radiogroup");
    algos.setAttribute("aria-label", "Detection algorithm");
    for (const [key, algo] of Object.entries(ALGOS)) {
      const pick = document.createElement("button");
      pick.type = "button";
      pick.setAttribute("role", "radio");
      pick.dataset.algo = key;
      pick.textContent = algo.label;
      algos.append(pick);
    }
    const params = document.createElement("div");
    params.className = "detect-params";
    bar.append(algos, params);

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

    /** The position being tried on, drawn larger than life. */
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

      // the tissue this position happens to sit on, at the brightness it has
      const dens = ctx.density(tile.x, tile.y);
      const cx = X(tile.x), cy = Y(tile.y), rr = frame * 0.8 * scale;
      const glow = paint.createRadialGradient(cx, cy, 0, cx, cy, rr);
      glow.addColorStop(0, `rgba(34,211,238,${0.30 * dens})`);
      glow.addColorStop(0.6, `rgba(34,211,238,${0.10 * dens})`);
      glow.addColorStop(1, "rgba(34,211,238,0)");
      paint.fillStyle = glow;
      paint.beginPath(); paint.arc(cx, cy, rr, 0, Math.PI * 2); paint.fill();

      /* Objects are drawn larger than life: at this magnification a cell is a
         couple of pixels, and the point of this view is to judge the labels. */
      const here = ctx.cellsInTile(settings.tile);
      for (const cell of here) {
        const r = Math.max(5, cell.r * scale * 2.4);
        const kept = settings.tested && detects(settings, cell);
        paint.beginPath(); paint.arc(X(cell.x), Y(cell.y), r, 0, Math.PI * 2);
        if (kept) {
          paint.fillStyle = labelColour(cell.id, 0.55);
          paint.fill();
          paint.lineWidth = 1.6;
          paint.strokeStyle = labelColour(cell.id, 1);
          paint.stroke();
        } else {
          // what a setting threw away stays visible
          paint.fillStyle = `rgba(226,232,240,${settings.tested ? 0.26 : 0.62})`;
          paint.fill();
        }
      }
      paint.restore();

      paint.strokeStyle = ctx.css("--line-strong");
      paint.lineWidth = 1;
      paint.strokeRect(ox + 0.5, oy + 0.5, frame * scale - 1, frame * scale - 1);
      ctx.drawScaleBar(paint, w, h, scale);
    }

    /** The settings, the position picker and the sentence underneath. */
    function drawTheControls() {
      const settings = ctx.settings();
      for (const pick of algos.querySelectorAll("button")) {
        pick.setAttribute("aria-checked", String(pick.dataset.algo === settings.algo));
      }
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

      if (settings.algo === "cellpose") {
        number("Diameter", "diameter", 4, 60, 1, "µm");
        number("Cell prob.", "cellprob", -6, 6, 0.5, "");
      } else {
        number("Level", "thresh", 0, 1, 0.05, "");
        number("Min area", "minArea", 20, 400, 10, "µm²");
      }

      const test = document.createElement("button");
      test.className = "ghost";
      test.type = "button";
      test.textContent = "Test on this tile";
      test.addEventListener("click", () => {
        settings.tested = true;
        refresh();
      });
      params.append(test);

      if (settings.tested) {
        const here = ctx.cellsInTile(settings.tile);
        const kept = here.filter((cell) => detects(settings, cell)).length;
        readout.textContent =
          `${kept} of ${here.length} objects at position ${settings.tile + 1}`;
      } else {
        readout.textContent = ALGOS[settings.algo].blurb;
      }
    }

    function refresh() {
      drawTheControls();
      drawTheTile();
      ctx.changed();
    }

    algos.addEventListener("click", (e) => {
      const pick = e.target.closest("button[data-algo]");
      if (!pick) return;
      const settings = ctx.settings();
      settings.algo = pick.dataset.algo;
      settings.tested = false;
      refresh();
    });

    for (const [button, step] of [[prev, -1], [next, 1]]) {
      button.addEventListener("click", () => {
        const settings = ctx.settings();
        const total = ctx.plan().length || 1;
        settings.tile = (settings.tile + step + total) % total;
        settings.tested = false;
        refresh();
      });
    }

    new ResizeObserver(() => drawTheTile()).observe(canvasHost);

    drawTheControls();
    drawTheTile();
    return { redraw: () => { drawTheControls(); drawTheTile(); } };
  },
};
