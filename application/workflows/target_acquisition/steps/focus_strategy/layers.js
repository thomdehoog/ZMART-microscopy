/**
 * What step 4 draws on the picture: the focus map.
 *
 * The points measured, the sweeps that measured them, and the surface fitted
 * through them, drawn in the stage's own projection because they are a
 * statement about the same glass the plan is drawn on.
 */
import { activeRecording } from "../../../../parts/microscope/recordings.js";

export function focusLayers(theRun) {
  const {
    run, drawnIn, activeMode, drawFocusLayer, drawFocusPoints, asAPress, renderActionBar,
    focusGrabbed, marqueeing, focusMarqueeTo, focusMarqueeTook,
    focusDragging, focusDraggedTo, endFocusDrag, focusPressed,
  } = theRun;
  return {
    focus: {
    key: "focus",
    label: "Focus",
    explains: "Where the microscope will focus, and what it has measured there. The "
      + "points stand above the plan and stay solid however far the rest is faded: "
      + "fading the plan to see the picture is not a request to lose them too.",
    /* Only while standing on that step — walking away leaves the canvas the
       plain picture every other step reads. */
    shown: activeMode === "focus",
    /* Early on purpose. The scan fields are drawn *over* the measured heat,
       so a predicted height never covers a field the operator can read, and
       the cost -- the shared fade reaches the map -- is right for a surface
       that colours the drawing. The points used to be in here too, and were
       painted over by the plan's grid; they are their own layer now, above
       the plan, which is the split this comment used to promise. */
    paint: (frame) => {
      const { place, scale, w, h } = drawnIn(frame);
      drawFocusLayer(frame.context, place, scale, w, h);
    },
  },
  /* The reticles, split from the map: they stand above the plan, where
     nothing paints over the thing the operator is placing, and they follow
     the Focus button rather than carrying a second one. */
  /* The frame the stack is being taken with, round the point the stage is
     at while the map is measured: the focussing preset's own frame, the
     way the scan's lit field is the overview's. Black on a white halo. */
  focusFrame: {
    key: "focusFrame",
    follows: "focus",
    /* Round the selected point whenever there is one: before the run it
       says what the stack will take, during it follows the stage, and after
       it stays where the run ended. A fresh recording -- Update -- opens a
       fresh map, and the frame must not go with the old one. */
    shown: activeMode === "focus"
      && !!run.focus.points[run.focus.selected] && !!activeRecording(run.focusPreset)?.frameUm,
    staysSolid: true,
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      const at = run.focus.points[run.focus.selected];
      const frameUm = activeRecording(run.focusPreset).frameUm;
      const half = frameUm / 2;
      const [x, y] = place(at.x - half, at.y - half);
      const side = frameUm * scale;
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 5;
      ctx.strokeRect(x, y, side, side);
      ctx.strokeStyle = "#000000"; ctx.lineWidth = 2;
      ctx.strokeRect(x, y, side, side);
    },
  },
  focusPoints: {
    key: "focusPoints",
    follows: "focus",
    shown: activeMode === "focus",
    staysSolid: true,
    paint: (frame) => {
      const { place } = drawnIn(frame);
      drawFocusPoints(frame.context, place);
    },
    /* A point already on the map is taken hold of before the picture is: it is
       the small thing on top, and a press that finds one should move it rather
       than move everything. Shift on empty ground draws a rectangle round a set
       of them instead — which the canvas offers rather than refusing, precisely
       so this can mean something. The presses live on this layer because the
       points do: claims are asked top of the stack down. */
    claims: (drag) => {
      const press = asAPress(drag);
      if (drag.phase === "started") return focusGrabbed(press);
      if (drag.phase === "moved") {
        if (marqueeing()) { focusMarqueeTo(press.offsetX, press.offsetY); return true; }
        if (focusDragging()) { focusDraggedTo(press.offsetX, press.offsetY); return true; }
        return true;
      }
      if (marqueeing()) { focusMarqueeTook(press.shiftKey); renderActionBar(); return true; }
      if (focusDragging()) {
        const { moved } = endFocusDrag();
        /* Held still on a point: the press picked it, and that is the whole of
           it. Placing happens where there is no point yet, which `focusPressed`
           answers for. */
        if (!moved && run.focus.placing) focusPressed(press.offsetX, press.offsetY);
        renderActionBar();
      }
      return true;
    },
  },
  };
}
