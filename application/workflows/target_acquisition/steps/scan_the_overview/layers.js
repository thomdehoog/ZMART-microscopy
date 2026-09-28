/**
 * What step 5 draws on the picture: the fields that have been imaged.
 *
 * Not the images themselves — those occupy the canvas's middle slot.
 * This is the run's own account of which fields have been taken,
 * which is what an operator watches fill in.
 */
/* The tiles a field index names: the plan as it was scanned, which is how
   the bridge numbered the fields it answered with; the plan itself before
   any scan. Read this and never `run.plan` for a result, so a picture stays
   where it was taken when the plan is edited afterwards. */
const fieldsOf = (run) => run.scanned?.plan ?? run.plan;

import { afterMarquee, tilesInBox } from "./test-tiles.js";

/* Under how many pixels a Shift-drag was a Shift-click: one tile toggled,
   not a rectangle. */
const MARQUEE_MIN_PX = 6;

export function overviewLayers(theRun) {
  const { run, css, drawnIn, shown, indexOfStep, testTilesChanged, step } = theRun;
  const onTheScanStep = () => step(run.activeIdx).mode === "scan" && !run.running && !run.protocol?.running;
  return {
    /* The tiles the overview is rehearsed on, pressed green over the plan:
       drawn from the scan step on, and only while any are green. */
    testTiles: {
      key: "testTiles",
      label: "Test tiles",
      explains: "The tiles pressed green in Step 5: the scan takes only these while any are "
        + "green. The protocol run takes the whole plan.",
      /* On screen from the scan step on: a layer not shown is never asked
         for a gesture, and the Shift-drag that makes the first green tile
         has to be asked. With nothing green and no rectangle it draws
         nothing. */
      shown: run.activeIdx >= indexOfStep("scan"),
      /* A Shift-drag on the scan step draws a rectangle over the tiles and
         turns the ones it took in green, or back; a Shift-click toggles
         the one under it. Anything without Shift is declined and pans. */
      claims: (drag) => {
        if (!onTheScanStep() || !drag.shift) return false;
        /* The drag speaks in the carrier's frame, as the plan does. */
        const at = drag.at;
        if (drag.phase === "started") {
          run.testMarquee = { sx: at.x, sy: at.y, cx: at.x, cy: at.y, screen: drag.screen };
          return true;
        }
        if (!run.testMarquee) return false;
        if (drag.phase === "moved") {
          run.testMarquee = { ...run.testMarquee, cx: at.x, cy: at.y };
          theRun.drawStage?.();
          return true;
        }
        const m = run.testMarquee;
        run.testMarquee = null;
        const px = Math.hypot(drag.screen.x - m.screen.x, drag.screen.y - m.screen.y);
        if (px < MARQUEE_MIN_PX) {
          const over = run.plan.findIndex((t) =>
            Math.abs(m.sx - t.x) <= t.frameUm / 2 && Math.abs(m.sy - t.y) <= t.frameUm / 2);
          if (over >= 0) {
            if (run.testTiles.has(over)) run.testTiles.delete(over); else run.testTiles.add(over);
          }
        } else {
          run.testTiles = afterMarquee(run.testTiles, tilesInBox(run.plan, m));
        }
        testTilesChanged?.();
        return true;
      },
      paint: (frame) => {
        const ctx = frame.context;
        const { place, scale } = drawnIn(frame);
        const ink = css("--good");
        const m = run.testMarquee;
        if (m) {
          const [x0, y0] = place(Math.min(m.sx, m.cx), Math.min(m.sy, m.cy));
          const [x1, y1] = place(Math.max(m.sx, m.cx), Math.max(m.sy, m.cy));
          ctx.globalAlpha = 0.15;
          ctx.fillStyle = ink;
          ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
          ctx.globalAlpha = 1;
          ctx.strokeStyle = ink;
          ctx.lineWidth = 1.5;
          ctx.setLineDash([5, 4]);
          ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
          ctx.setLineDash([]);
        }
        for (const i of run.testTiles) {
          const t = run.plan[i];
          if (!t) continue;
          /* The whole tile, filled, the way the plan's tiles are filled
             blue -- under the picture, so a scanned tile shows its pixels
             and an unscanned one is solid green. */
          const [fx, fy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
          const side = t.frameUm * scale;
          ctx.globalAlpha = 0.45;
          ctx.fillStyle = ink;
          ctx.fillRect(fx, fy, side, side);
          ctx.globalAlpha = 1;
          ctx.strokeStyle = ink;
          ctx.lineWidth = 2;
          ctx.strokeRect(fx, fy, side, side);
        }
        /* And the one the hand is over, whichever way the press would turn it. */
        const over = run.testHovered ?? -1;
        const t = run.plan[over];
        if (t && !run.running) {
          const [fx, fy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
          ctx.strokeStyle = ink;
          ctx.lineWidth = 2;
          ctx.setLineDash([4, 3]);
          ctx.strokeRect(fx, fy, t.frameUm * scale, t.frameUm * scale);
          ctx.setLineDash([]);
        }
      },
    },
    tiles: {
    key: "tiles",
    label: "Tiles",
    explains: "The field the stage is imaging right now. What has been taken needs no "
      + "mark of its own: acquired images cover the plan at those positions.",
    shown: shown > 0,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      // Acquired image pixels cover the plan; only the active frontier needs a mark.

      // ---- scan frontier: the tile the stage is standing on
      if (run.running === "scan" && fieldsOf(run)[shown]) {
        const t = fieldsOf(run)[shown];
        const [fx, fy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
        ctx.strokeStyle = css("--accent");
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.strokeRect(fx, fy, t.frameUm * scale, t.frameUm * scale);
        ctx.setLineDash([]);
      }
    },
    /* A click on a taken field is a click on that field. This is what
       opening a position from the picture will hang off. */
    reaches: (at) => {
      const half = (t) => t.frameUm / 2;
      return fieldsOf(run).slice(0, shown).find(
        (t) => Math.abs(at.x - t.x) <= half(t) && Math.abs(at.y - t.y) <= half(t),
      ) ?? null;
    },
  },
  };
}
