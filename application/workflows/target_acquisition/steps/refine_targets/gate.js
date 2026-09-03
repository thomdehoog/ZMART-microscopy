/**
 * Step 7's channel — the scatter the targets are gated on.
 *
 * Discovery finds every cell; this is where the operator says which are worth
 * imaging. A gate is one polygon on one feature pair — laid point by point
 * and closed on its first vertex, the way the scan-area polygon is — and
 * gates accumulate in a list. The selection is the intersection: a cell must
 * fall inside every gate, so adding one only ever narrows. Each plot carries
 * at most its own pair's polygon; choosing a gate from the list brings its
 * plot back, axes and all.
 *
 * The rules live in `gating.js`, where they are pinned without a canvas.
 * The widget owns its markup, its canvas and its gestures; what it reads and
 * what it changes arrive in `ctx`, and it never reaches for the page.
 */

import {
  cellFeature, cellsInAllGates, featureNames, gateForPair, insidePolygon,
} from "./gating.js";
import { sideGroup } from "../../../../framework/window/panels.js";

/** Room for the axes, in pixels. */
/* The plot takes the card: room at the left for the tick labels and the
   axis title, a little at the top so the top tick is not clipped, and a
   line for the ticks and one for the title under it. */
/* The frame starts at the card's left edge, in line with the rows above;
   the y tick labels and the y title stand outside it at the right, each in
   its own column. Below, a line for the x ticks and one for the x title. */
const PAD = { l: 1, r: 62, t: 1, b: 38 };

/** How near a press must land to take a vertex or an edge, in pixels. */
const REACH = 9;

export default {
  id: "gate",
  label: "Discover Targets",

  /**
   * `ctx` carries:
   *   `cells()` `gated()` `acquired()`  what to draw; `gated()` is the
   *                     intersection the run holds
   *   `gates()`         every gate laid, `[{fx, fy, vertices}]`
   *   `cap()`           the per-tileset ceiling the run holds
   *   `setGates(gates, ids, cap)`  the gates changed; the run takes all three
   *   `showing()`       whether discovery has run, so there is anything to gate
   *   `sizeCanvas(cv)` `css(name)`  the page's canvas plumbing
   */
  mount(host, ctx) {
    /* Which features the plot spans right now. */
    let fx = "area";
    let fy = "intensity";
    /* The polygon being laid, in feature units, until it closes. */
    let draft = null;
    /* The vertex the hand holds mid-drag, and the one last chosen. */
    let held = null;
    let chosen = -1;
    /* The corner under the pointer, lit before it is held; and whether
       Ctrl is down, which turns the press on it into taking it away. */
    let hovered = -1;
    let ctrlHeld = false;
    let xHi = 1;
    let yHi = 1;
    /* The floors: zero, unless a feature goes below it -- kurtosis does. */
    let xLo = 0;
    let yLo = 0;

    const side = document.createElement("div");
    side.className = "analysis-side";

    /* Which way the targets are refined, above the box that does it -- the
       same row as the discovery step's method. Gating is the one way there
       is today; the menu stands so another can be chosen when there is one. */
    const method = sideGroup("Refinement method");
    const methodRow = document.createElement("div");
    methodRow.className = "detect-params";
    const methodParam = document.createElement("div");
    methodParam.className = "param method";
    const methodPick = document.createElement("select");
    methodPick.id = "refine-method";
    methodPick.setAttribute("aria-label", "how the targets are refined");
    const gating = document.createElement("option");
    gating.value = "gating";
    gating.textContent = "Gating";
    methodPick.append(gating);
    methodParam.append(methodPick);
    methodRow.append(methodParam);
    method.body.append(methodRow);

    /* The same boxed group every earlier step's channel is made of. */
    const boxed = sideGroup("Gating");
    /* One feature per axis: the gate drawn here is drawn across these. */
    const axes = document.createElement("div");
    axes.className = "gate-axes";
    /* The pickers end where the plot's frame ends, not where the canvas
       does: the y labels stand in a column of their own past the frame. */
    axes.style.paddingRight = `${PAD.r}px`;
    const pick = (id, label) => {
      const wrap = document.createElement("label");
      wrap.append(label);
      const sel = document.createElement("select");
      sel.id = id;
      wrap.append(sel);
      axes.append(wrap);
      return sel;
    };
    const pickX = pick("gate-fx", "x");
    const pickY = pick("gate-fy", "y");


    const legend = document.createElement("div");
    legend.className = "legend analysis-legend";
    for (const [ink, what] of [["--mark-context", "all cells"],
      ["--mark-gated", "gated"], ["--mark-selected", "selected"]]) {
      const one = document.createElement("span");
      one.innerHTML = `<i class="dot" style="background:var(${ink})"></i> `;
      one.append(what);
      legend.append(one);
    }

    const wrap = document.createElement("div");
    wrap.className = "scatter-wrap";
    const canvasHost = document.createElement("div");
    canvasHost.className = "scatter-host";
    const cv = document.createElement("canvas");
    cv.id = "scatter-canvas";
    canvasHost.append(cv);
    wrap.append(canvasHost);

    const readout = document.createElement("div");
    readout.className = "side-note";
    readout.id = "gate-readout";

    const list = document.createElement("div");
    list.className = "gate-list";
    list.id = "gate-list";

    boxed.body.append(axes, legend, wrap, readout, list);

    side.append(method.group, boxed.group);
    host.append(side);

    const sx = (v, w) => PAD.l + ((v - xLo) / (xHi - xLo)) * (w - PAD.l - PAD.r);
    const sy = (v, h) => (h - PAD.b) - ((v - yLo) / (yHi - yLo)) * (h - PAD.t - PAD.b);
    const invX = (px, w) => xLo + ((px - PAD.l) / (w - PAD.l - PAD.r)) * (xHi - xLo);
    const invY = (py, h) => yLo + (((h - PAD.b) - py) / (h - PAD.t - PAD.b)) * (yHi - yLo);

    /* The gate as it stands on the screen, and the grips a hand finds on it:
       its corners, the point at the middle of its top edge to turn it by,
       and its inside to carry it. All in screen pixels, because the two axes
       are not the same scale and a turn should look like a turn. */
    const onScreen = (gate, w, h) => gate.vertices.map(([gx, gy]) => [sx(gx, w), sy(gy, h)]);
    /* The middle of the gate: the centre of its area, not the mean of its
       corners -- a side with corners crowded along it pulled the mean
       towards that side. A gate with no area falls back to the mean. */
    const centreOf = (pts) => {
      let twiceArea = 0, cx = 0, cy = 0;
      for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
        const cross = pts[j][0] * pts[i][1] - pts[i][0] * pts[j][1];
        twiceArea += cross;
        cx += (pts[j][0] + pts[i][0]) * cross;
        cy += (pts[j][1] + pts[i][1]) * cross;
      }
      if (Math.abs(twiceArea) > 1e-9) return [cx / (3 * twiceArea), cy / (3 * twiceArea)];
      return pts.reduce(([mx, my], [x, y]) => [mx + x / pts.length, my + y / pts.length], [0, 0]);
    };
    /* The grip to turn by hangs off the first corner, away from the
       gate's middle; the gate turns about its middle, and the corner the
       grip hangs from swings round with it. */
    const turnGripOf = (pts) => {
      const [x, y] = pts[0];
      const [cx, cy] = centreOf(pts);
      const away = Math.hypot(x - cx, y - cy) || 1;
      return [x + ((x - cx) / away) * 30, y + ((y - cy) / away) * 30];
    };
    const putBack = (gate, pts, w, h) => {
      gate.vertices = pts.map(([x, y]) => [invX(x, w), invY(y, h)]);
    };

    const theCells = () => [...ctx.cells()];
    const shownGate = () => gateForPair(ctx.gates(), fx, fy);

    /* Gates changed: the run takes the list, what they let through, and the
       ceiling as typed. The ceiling is not applied here -- the step's own
       press, Restrict, does that -- so what the plot rings is what the
       gates say, until the operator asks for the draw. */
    const commit = (gates) => {
      ctx.setGates(gates, cellsInAllGates(theCells(), gates), ctx.cap());
      sayIt();
      renderList();
      draw();
    };

    const sayIt = () => {
      const cells = theCells();
      const gates = ctx.gates();
      if (draft) {
        readout.textContent =
          `laying a gate on ${fx} × ${fy} — ${draft.length} point(s), close it on the first`;
        return;
      }
      if (!gates.length) {
        readout.textContent = "";
        return;
      }
      const inGates = cellsInAllGates(cells, gates).size;
      const took = ctx.gated().size;
      readout.textContent =
        (took < inGates
          ? `${took} kept of ${inGates} in gates · `
          : `${took} of ${cells.length} selected · `)
        + `${gates.length} gate${gates.length === 1 ? "" : "s"}`;
    };

    /** The gates, each a row that brings its own plot back. */
    function renderList() {
      list.textContent = "";
      const cells = theCells();
      ctx.gates().forEach((gate, at) => {
        const row = document.createElement("div");
        row.className = "gate-row";
        row.setAttribute("aria-current", String(gate === shownGate()));
        const open = document.createElement("button");
        open.type = "button";
        open.className = "gate-open";
        const inside = cellsInAllGates(cells, [gate]).size;
        open.innerHTML = `<span class="idx">${at + 1}</span>`
          + `<span>${gate.fx} × ${gate.fy}</span>`
          + `<span class="gate-n">${inside} in</span>`;
        open.addEventListener("click", () => {
          fx = gate.fx;
          fy = gate.fy;
          draft = null;
          chosen = -1;
          refreshPickers();
          renderList();
          draw();
          sayIt();
        });
        const drop = document.createElement("button");
        drop.type = "button";
        drop.className = "rec-drop";
        drop.textContent = "✕";
        drop.title = "throw this gate away";
        drop.addEventListener("click", () => {
          commit(ctx.gates().filter((g) => g !== gate));
        });
        row.append(open, drop);
        list.append(row);
      });
    }

    /** The pickers offer every feature the cells carry; the pair in use wins. */
    function refreshPickers() {
      const names = featureNames(theCells());
      for (const [sel, current] of [[pickX, fx], [pickY, fy]]) {
        sel.textContent = "";
        for (const name of names) {
          const o = document.createElement("option");
          o.value = name;
          o.textContent = name;
          sel.append(o);
        }
        sel.value = current;
      }
    }
    for (const [sel, take] of [[pickX, (v) => { fx = v; }], [pickY, (v) => { fy = v; }]]) {
      sel.addEventListener("change", () => {
        take(sel.value);
        draft = null;
        chosen = -1;
        renderList();
        draw();
        sayIt();
      });
    }

    function draw() {
      if (!ctx.sizeCanvas(cv)) return;
      const paint = cv.getContext("2d");
      const w = cv.cssW, h = cv.cssH;
      paint.clearRect(0, 0, w, h);
      paint.fillStyle = ctx.css("--screen");
      paint.fillRect(0, 0, w, h);

      const cells = theCells();
      xHi = 1; yHi = 1; xLo = 0; yLo = 0;
      for (const c of cells) {
        const vx = cellFeature(c, fx), vy = cellFeature(c, fy);
        xHi = Math.max(xHi, vx); yHi = Math.max(yHi, vy);
        xLo = Math.min(xLo, vx); yLo = Math.min(yLo, vy);
      }
      /* A little headroom, so the outermost cells sit inside the plot
         instead of on its axis line -- at the bottom too, when the feature
         goes below zero. */
      xHi += (xHi - xLo) * 0.05; yHi += (yHi - yLo) * 0.05;
      if (xLo < 0) xLo -= (xHi - xLo) * 0.05;
      if (yLo < 0) yLo -= (yHi - yLo) * 0.05;

      // recessive grid
      paint.strokeStyle = ctx.css("--line");
      paint.lineWidth = 1;
      paint.fillStyle = ctx.css("--ink-3");
      paint.font = "11.5px system-ui, sans-serif";
      paint.textAlign = "left";
      /* Round-number ticks: the step is the nearest 1/2/5 decade to a
         quarter of the span, so the grid says 50, 100, 150 -- never 0.95,
         1.90, 2.84. The labels are the numbers themselves, trimmed. */
      const tickStep = (span) => {
        const raw = span / 4;
        const mag = 10 ** Math.floor(Math.log10(raw));
        const unit = raw / mag;
        return (unit < 1.5 ? 1 : unit < 3 ? 2 : unit < 7 ? 5 : 10) * mag;
      };
      const sayTick = (v) => String(parseFloat(v.toPrecision(3)));
      const yStep = tickStep(yHi - yLo);
      for (let v = Math.ceil(yLo / yStep) * yStep; v <= yHi + yStep * 0.001; v += yStep) {
        const y = sy(v, h);
        paint.beginPath(); paint.moveTo(PAD.l, y); paint.lineTo(w - PAD.r, y); paint.stroke();
        paint.fillText(sayTick(v), w - PAD.r + 8, y + 4);
      }
      paint.textAlign = "center";
      const xStep = tickStep(xHi - xLo);
      for (let v = Math.ceil(xLo / xStep) * xStep; v <= xHi + xStep * 0.001; v += xStep) {
        if (v === 0 && xLo === 0) continue;
        const x = sx(v, w);
        paint.beginPath(); paint.moveTo(x, PAD.t); paint.lineTo(x, h - PAD.b); paint.stroke();
        paint.fillText(sayTick(v), x, h - PAD.b + 18);
      }

      // the plot's frame, a shade darker than the grid, closed on all four sides
      paint.strokeStyle = ctx.css("--line-strong");
      paint.lineWidth = 1;
      paint.strokeRect(PAD.l + 0.5, PAD.t + 0.5, w - PAD.l - PAD.r - 1, h - PAD.t - PAD.b - 1);
      /* Zero, when the plot crosses it, is a line of its own. */
      if (yLo < 0) {
        paint.beginPath(); paint.moveTo(PAD.l, sy(0, h)); paint.lineTo(w - PAD.r, sy(0, h)); paint.stroke();
      }
      if (xLo < 0) {
        paint.beginPath(); paint.moveTo(sx(0, w), PAD.t); paint.lineTo(sx(0, w), h - PAD.b); paint.stroke();
      }

      // axis titles are the chosen features, because that is what this plot IS
      // -- in the ticks' own ink and size, only bolder, each beyond its ticks
      paint.fillStyle = ctx.css("--ink-3");
      paint.font = "600 11.5px system-ui, sans-serif";
      paint.textAlign = "center";
      paint.fillText(fx, (PAD.l + w - PAD.r) / 2, h - 6);
      paint.save();
      paint.translate(w - 12, (PAD.t + h - PAD.b) / 2);
      paint.rotate(Math.PI / 2);
      paint.fillText(fy, 0, 0);
      paint.restore();

      const gated = ctx.gated();

      // every cell, quietly; the survivors of ALL gates, ringed.
      // The quiet dots earn their size: thousands of them at radius 2
      // fused into a slab that hid its own density, so a crowded plot
      // draws smaller and fainter and the structure shows through.
      const crowd = cells.length;
      const dot = crowd > 3000 ? 1.2 : crowd > 800 ? 1.7 : 2;
      paint.fillStyle = ctx.css("--mark-context");
      paint.globalAlpha = crowd > 3000 ? 0.35 : 0.5;
      paint.beginPath();
      const restricted = ctx.restricted?.() ?? false;
      const marked = restricted ? gated : cellsInAllGates(cells, ctx.gates());
      for (const c of cells) {
        if (marked.has(c.id)) continue;
        const x = sx(cellFeature(c, fx), w), y = sy(cellFeature(c, fy), h);
        paint.moveTo(x + dot, y); paint.arc(x, y, dot, 0, Math.PI * 2);
      }
      paint.fill();
      paint.globalAlpha = 1;

      /* One mark at a time: what the gates let through, in blue, while they
         are drawn; once Restrict has drawn under the ceiling, what it kept,
         in green, and the rest of the catch goes quiet again. */
      for (const c of cells) {
        if (!marked.has(c.id)) continue;
        const x = sx(cellFeature(c, fx), w), y = sy(cellFeature(c, fy), h);
        paint.beginPath(); paint.arc(x, y, restricted ? 4.2 : 3.4, 0, Math.PI * 2);
        paint.fillStyle = ctx.css(restricted ? "--mark-selected" : "--mark-gated");
        paint.fill();
        paint.lineWidth = 2; paint.strokeStyle = ctx.css("--screen"); paint.stroke();
      }

      // this pair's own gate, and only its own — with its handles
      const gate = shownGate();
      if (gate) {
        /* A region, not a wire: a light fill inside a solid edge. */
        paint.beginPath();
        gate.vertices.forEach(([gx, gy], i) => {
          const x = sx(gx, w), y = sy(gy, h);
          if (i) paint.lineTo(x, y); else paint.moveTo(x, y);
        });
        paint.closePath();
        paint.fillStyle = "rgba(2, 132, 199, 0.08)";
        paint.fill();
        paint.strokeStyle = "#0284c7"; paint.lineWidth = 1.5;
        paint.stroke();
        /* The corners in the scan area's own grips: a round handle, white
           until it is held or hovered, then filled and a little larger. */
        gate.vertices.forEach(([gx, gy], i) => {
          const x = sx(gx, w), y = sy(gy, h);
          const hot = i === chosen || i === hovered;
          paint.fillStyle = hot ? "#0284c7" : "#ffffff";
          paint.strokeStyle = "#0284c7"; paint.lineWidth = 1.5;
          paint.beginPath(); paint.arc(x, y, hot ? 6 : 4.5, 0, Math.PI * 2);
          paint.fill(); paint.stroke();
          /* Ctrl over a corner offers to take it away: a minus on the grip. */
          if (i === hovered && ctrlHeld) {
            paint.strokeStyle = "#ffffff"; paint.lineWidth = 2;
            paint.beginPath(); paint.moveTo(x - 3.5, y); paint.lineTo(x + 3.5, y); paint.stroke();
          }
        });
        /* The grip to turn it by, on a thin stem off the first corner:
           the stem is not part of the shape, it only says where the grip
           belongs and what the gate turns about. */
        const pts = onScreen(gate, w, h);
        const [ax, ay] = pts[0];
        const [gx, gy] = turnGripOf(pts);
        paint.beginPath(); paint.moveTo(ax, ay); paint.lineTo(gx, gy);
        paint.strokeStyle = "#0284c7"; paint.lineWidth = 1; paint.setLineDash([3, 3]);
        paint.stroke();
        paint.setLineDash([]);
        const turning = hovered === "turn" || held?.kind === "turn";
        paint.beginPath(); paint.arc(gx, gy, turning ? 6.5 : 5, 0, Math.PI * 2);
        paint.fillStyle = turning ? "#0284c7" : "#ffffff"; paint.fill();
        paint.lineWidth = 1.5; paint.strokeStyle = "#0284c7"; paint.stroke();
      }

      // the polygon being laid, open, its first point marked as the way home
      if (draft) {
        paint.strokeStyle = ctx.css("--accent"); paint.lineWidth = 1.5;
        paint.setLineDash([4, 3]);
        paint.beginPath();
        draft.forEach(([gx, gy], i) => {
          const x = sx(gx, w), y = sy(gy, h);
          if (i) paint.lineTo(x, y); else paint.moveTo(x, y);
        });
        paint.stroke();
        paint.setLineDash([]);
        const [hx, hy] = draft[0];
        paint.beginPath(); paint.arc(sx(hx, w), sy(hy, h), 5, 0, Math.PI * 2);
        paint.stroke();
      }
    }

    /* How far a press is from the segment a-b, in pixels. */
    const toSegment = (px, py, ax, ay, bx, by) => {
      const dx = bx - ax, dy = by - ay;
      const t = Math.max(0, Math.min(1,
        ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)));
      return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
    };

    cv.addEventListener("pointerdown", (e) => {
      if (!ctx.showing()) return;
      const w = cv.cssW, h = cv.cssH;
      const gate = shownGate();

      if (gate) {
        /* An existing gate takes the press: a corner to move, the grip to
           turn it by, an edge to grow through, its inside to carry it. One
           polygon per plot means empty space stays empty. */
        for (let i = 0; i < gate.vertices.length; i++) {
          const [gx, gy] = gate.vertices[i];
          if (Math.hypot(sx(gx, w) - e.offsetX, sy(gy, h) - e.offsetY) < REACH) {
            if (e.ctrlKey) {
              /* A corner taken away; a gate that cannot stand on two goes whole. */
              hovered = -1;
              chosen = -1;
              if (gate.vertices.length > 3) {
                gate.vertices.splice(i, 1);
                commit([...ctx.gates()]);
              } else {
                commit(ctx.gates().filter((g) => g !== gate));
              }
              return;
            }
            chosen = i;
            held = { gate, kind: "corner", at: i };
            cv.setPointerCapture(e.pointerId);
            draw();
            return;
          }
        }
        const pts = onScreen(gate, w, h);
        const [gx, gy] = turnGripOf(pts);
        if (Math.hypot(gx - e.offsetX, gy - e.offsetY) < REACH) {
          const centre = centreOf(pts);
          held = {
            gate, kind: "turn", centre, from: pts,
            start: Math.atan2(e.offsetY - centre[1], e.offsetX - centre[0]),
          };
          cv.setPointerCapture(e.pointerId);
          draw();
          return;
        }
        for (let i = 0; i < gate.vertices.length; i++) {
          const [ax, ay] = gate.vertices[i];
          const [bx, by] = gate.vertices[(i + 1) % gate.vertices.length];
          if (toSegment(e.offsetX, e.offsetY,
            sx(ax, w), sy(ay, h), sx(bx, w), sy(by, h)) < REACH) {
            gate.vertices.splice(i + 1, 0, [invX(e.offsetX, w), invY(e.offsetY, h)]);
            chosen = i + 1;
            held = { gate, kind: "corner", at: i + 1 };
            cv.setPointerCapture(e.pointerId);
            draw();
            return;
          }
        }
        if (insidePolygon(e.offsetX, e.offsetY, pts)) {
          held = { gate, kind: "carry", from: pts, at: [e.offsetX, e.offsetY] };
          cv.setPointerCapture(e.pointerId);
          cv.style.cursor = "grabbing";
          return;
        }
        return;
      }

      /* No gate on this pair: the press lays the polygon, and landing back on
         the first point closes it. */
      if (draft && draft.length >= 3) {
        const [gx, gy] = draft[0];
        if (Math.hypot(sx(gx, w) - e.offsetX, sy(gy, h) - e.offsetY) < REACH) {
          const vertices = draft;
          draft = null;
          commit([...ctx.gates(), { fx, fy, vertices }]);
          return;
        }
      }
      (draft ??= []).push([invX(e.offsetX, w), invY(e.offsetY, h)]);
      sayIt();
      draw();
    });

    cv.addEventListener("pointermove", (e) => {
      const w = cv.cssW, h = cv.cssH;
      if (held) {
        if (held.kind === "corner") {
          held.gate.vertices[held.at] = [invX(e.offsetX, w), invY(e.offsetY, h)];
        } else if (held.kind === "turn") {
          const [cx, cy] = held.centre;
          const by = Math.atan2(e.offsetY - cy, e.offsetX - cx) - held.start;
          const cos = Math.cos(by), sin = Math.sin(by);
          putBack(held.gate, held.from.map(([x, y]) =>
            [cx + (x - cx) * cos - (y - cy) * sin, cy + (x - cx) * sin + (y - cy) * cos]), w, h);
        } else if (held.kind === "carry") {
          const dx = e.offsetX - held.at[0], dy = e.offsetY - held.at[1];
          putBack(held.gate, held.from.map(([x, y]) => [x + dx, y + dy]), w, h);
        }
        draw();
        return;
      }
      if (!ctx.showing()) return;
      /* What the hand is over on the gate, lit before it is held, and the
         cursor saying what a press would do. */
      const gate = shownGate();
      let over = -1;
      let cursor = "crosshair";
      if (gate) {
        const pts = onScreen(gate, w, h);
        for (let i = 0; i < pts.length; i++) {
          if (Math.hypot(pts[i][0] - e.offsetX, pts[i][1] - e.offsetY) < REACH) { over = i; cursor = "grab"; break; }
        }
        if (over === -1) {
          const [gx, gy] = turnGripOf(pts);
          if (Math.hypot(gx - e.offsetX, gy - e.offsetY) < REACH) { over = "turn"; cursor = "grab"; }
          else if (insidePolygon(e.offsetX, e.offsetY, pts)) cursor = "move";
        }
      }
      cv.style.cursor = cursor;
      if (over !== hovered) { hovered = over; draw(); }
    });

    cv.addEventListener("pointerup", (e) => {
      if (!held) return;
      held = null;
      cv.style.cursor = "crosshair";
      cv.releasePointerCapture?.(e.pointerId);
      /* The drag settled: the run re-reads the intersection once, not per frame. */
      commit([...ctx.gates()]);
    });

    cv.addEventListener("pointerleave", () => {
      if (hovered !== -1) { hovered = -1; draw(); }
    });

    const sayCtrl = (e) => {
      if (ctrlHeld === e.ctrlKey) return;
      ctrlHeld = e.ctrlKey;
      if (host.isConnected && hovered !== -1) draw();
    };
    window.addEventListener("keydown", sayCtrl);
    window.addEventListener("keyup", sayCtrl);

    window.addEventListener("keydown", (e) => {
      if (!host.isConnected || !ctx.showing()) return;
      if (e.key === "Escape" && draft) {
        draft = null;
        sayIt(); draw();
        return;
      }
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      const gate = shownGate();
      if (!gate || chosen < 0) return;
      e.preventDefault();
      /* A vertex goes; a polygon that cannot stand on two goes whole. */
      if (gate.vertices.length > 3) {
        gate.vertices.splice(chosen, 1);
        chosen = -1;
        commit([...ctx.gates()]);
      } else {
        chosen = -1;
        commit(ctx.gates().filter((g) => g !== gate));
      }
    });



    new ResizeObserver(() => draw()).observe(canvasHost);

    refreshPickers();
    renderList();
    sayIt();
    draw();
    return {
      redraw: () => { refreshPickers(); renderList(); sayIt(); draw(); },
    };
  },
};
