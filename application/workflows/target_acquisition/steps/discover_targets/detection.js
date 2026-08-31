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
  border: settings.border, binning: settings.binning,
});

/** Golden-angle hues, so neighbouring labels never share a colour. */
export const labelColour = (n, alpha = 1) =>
  `hsla(${(n * 137.508) % 360}, 68%, 58%, ${alpha})`;

import { sideGroup } from "../../../../framework/window/panels.js";

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

    /* The step's own press lives at the top of its channel, not in the
       bar under the panel: the hand finds Run where the controls begin. */
    const act = document.createElement("div");
    act.className = "detect-action side-act";

    /* One box carries the whole act of looking: the image being judged,
       the settings that produced it, and the presses that try them -- the
       operator tunes and looks in one place instead of two cards apart. */
    const test = sideGroup("Test object detection");
    const params = document.createElement("div");
    params.className = "detect-params";
    const picker = document.createElement("div");
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

    const canvasHost = document.createElement("div");
    canvasHost.className = "tile-host";
    const cv = document.createElement("canvas");
    cv.id = "tile-canvas";
    /* The picker rides the image's own bottom line, centred beside the
       scale bar rather than on a row of its own. */
    canvasHost.append(cv, picker);

    const readout = document.createElement("div");
    readout.className = "side-note";
    readout.id = "detect-readout";

    /* Inside the card, the segmentation is a grey header over its rows --
       a section of the box, not a box of its own -- and the two presses
       share one row: try it here, or run it everywhere. */
    const cellposeHead = document.createElement("div");
    cellposeHead.className = "side-subhead";
    cellposeHead.textContent = "Cellpose segmentation";
    const tryBtn = document.createElement("button");
    tryBtn.className = "ghost";
    tryBtn.type = "button";
    tryBtn.id = "detect-try";
    tryBtn.textContent = "Test this tile";
    const presses = document.createElement("div");
    presses.className = "detect-presses";
    presses.append(tryBtn, act);
    test.body.append(canvasHost, readout, cellposeHead, params, presses);

    /* Where the run says how it is going: hidden until a run begins, then
       one line for what is being segmented and one for the arithmetic --
       done, still to go, and the time that pace projects. The projection is
       re-figured every time a field lands, so the first field paying the
       workers' spawn corrects itself instead of colouring the estimate. */
    const progress = sideGroup("Progress");
    progress.group.style.display = "none";
    const doingLine = document.createElement("div");
    doingLine.className = "side-note";
    doingLine.id = "detect-doing";
    const countLine = document.createElement("div");
    countLine.className = "side-note";
    countLine.id = "detect-count";
    progress.body.append(doingLine, countLine);

    side.append(test.group, progress.group);
    host.append(side);

    /* The picture of the field being looked at, drawn when it arrives. The
       whole point of this view is judging a diameter against the tissue, so
       the picture comes with the field -- not, as it first did, only after a
       test had already been run blind on it. */
    let picture = null;
    let pictureFor = null;
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

      /* The picture follows the field, whoever chose it: the arrows, a press
         on the canvas, the step coming up. Drawn-for is tracked so a redraw
         is never a refetch, and a changed tile always is. */
      if (pictureFor !== settings.tile) {
        pictureFor = settings.tile;
        showThePictureOf(ctx.labelOf?.(settings.tile));
      }

      /* Nothing painted behind: the image square sits straight on the
         card, its margins the card's own white rather than a grey mat. */
      paint.clearRect(0, 0, w, h);

      const tile = ctx.plan()[settings.tile];
      if (!tile) return;
      const frame = tile.frameUm;
      /* Flush with the card's content: the image starts where the rows
         below it start, full width, with one line under it kept for the
         scale bar and the picker. */
      const pad = 26;
      const scale = Math.min(w / frame, (h - pad) / frame);
      const ox = 0, oy = 0;
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
      /* A cell nearer the field's edge than this is dropped: a clipped cell
         measures as a smaller, dimmer thing that it is not. Zero keeps
         everything, edges included. */
      number("Border", "border", 0, 500, 1, "µm");
      /* Segment on a smaller copy: 2 halves each side before cellpose sees
         it, which is most of the waiting gone -- the masks come back scaled
         to the full frame, and the features are still measured there. */
      number("Binning", "binning", 1, 8, 1, "×");

      if (settings.tested) {
        readout.textContent =
          `${settings.tried.length} objects at position ${settings.tile + 1}`;
      } else {
        /* Nothing to say until something was measured: the card carries no
           standing caption, only results and errors. */
        readout.textContent = "";
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
        refresh();
      });
    }

    tryBtn.addEventListener("click", () => {
      const settings = ctx.settings();
      settings.tested = false;
      readout.textContent = `looking at position ${settings.tile + 1}…`;
      /* The first test on a cold machine pays the worker's whole spawn --
         a silent minute that read as a dead button. The bar says so, and
         counts, so the wait has a size instead of a mood. */
      const began = performance.now();
      const saying = () => ctx.status?.say(
        `testing on position ${settings.tile + 1} — segmenting… `
        + `${Math.round((performance.now() - began) / 1000)} s`);
      saying();
      const ticking = setInterval(saying, 1000);
      const settled = () => { clearInterval(ticking); ctx.status?.quiet(); };
      ctx.tryOn(settings.tile, settingsFor(settings)).then((found) => {
        settled();
        settings.tried = found.cells;
        settings.tested = true;
        showThePictureOf(found.position_label);
        refresh();
      }, (why) => { settled(); readout.textContent = why.message; });
    });

    /** A duration in the box's own words. */
    const saySpan = (s) => (s >= 90
      ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")} s`
      : `${s >= 10 ? Math.round(s) : Math.max(0.1, s).toFixed(1)} s`);

    /* When the run under way began, for the pace the count line projects.
       Cleared when the run ends; restarted if the panel was remounted
       mid-run, which loses the early pace but never shows a stale one. */
    let ranSince = null;

    /** One discovery's story, told as the page hears it land. */
    function sayProgress(snap) {
      progress.group.style.display = "";
      if (snap.start) {
        ranSince = performance.now();
        doingLine.textContent = "starting the workers…";
        countLine.textContent = "";
        return;
      }
      if (snap.doing != null) doingLine.textContent = snap.doing;
      if (snap.done != null && snap.of) {
        if (ranSince === null) ranSince = performance.now();
        const gone = (performance.now() - ranSince) / 1000;
        const per = snap.done ? gone / snap.done : null;
        const still = snap.of - snap.done;
        countLine.textContent = per === null
          ? `0 of ${snap.of} segmented`
          : `${snap.done} of ${snap.of} segmented · ${still} still to go`
            + (still ? ` · ≈ ${saySpan(per * still)} left (${saySpan(per)} each)` : "");
      }
      if (snap.ended) {
        doingLine.textContent = snap.note;
        ranSince = null;
      }
    }

    new ResizeObserver(() => drawTheTile()).observe(canvasHost);

    drawTheControls();
    drawTheTile();
    return {
      redraw: () => { drawTheControls(); drawTheTile(); },
      progress: sayProgress,
    };
  },
};
