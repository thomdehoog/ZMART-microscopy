/**
 * What step 2 draws on the picture: the plate, and the marks that register it.
 *
 * The carrier is the room the run happens in, so it is drawn low in the stack
 * and under everything the run then puts inside it. The anchors are the points
 * it is being registered from — where the plate really is, as against where it
 * was assumed to be — and they belong to the step that places them.
 */
export function carrierLayers(theRun) {
  const {
    run, css, drawnIn, carrierWidget, activeMode, crosshair,
    redraw, anchorsChanged,
  } = theRun;

  /* How near a press has to be to take hold of an anchor: a few pixels,
     measured in what the picture is showing rather than in micrometres, so it
     is the same reach however far out the picture is zoomed. */
  const REACH_PX = 12;
  const under = (drag) => {
    let best = REACH_PX * drag.zoom, found = -1;
    run.anchors.forEach((a, i) => {
      const d = Math.hypot(a.x - drag.at.x, a.y - drag.at.y);
      if (d < best) { best = d; found = i; }
    });
    return found;
  };
  return {
    carrier: {
    key: "carrier",
    label: "Carrier",
    explains: "The plate the sample is mounted in — its outline and its wells. The "
      + "room the run happens in.",
    shown: run.done.has("carrier"),
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      /* Grey, not the accent: the carrier is the room the run happens in,
         not a thing the run produced. Dark enough to read against the stage
         behind it, which is grey too. */
      carrierWidget.drawOn(ctx, {
        config: run.carrier, toScreen: place, scale: scale,
        colour: css("--ink-3"), fill: css("--surface-3"),
      });
    },
  },
    anchors: {
    key: "anchors",
    label: "Anchors",
    explains: "The points the carrier is being registered from — where the plate really "
      + "is, as opposed to where it was assumed to be. Solid, because a mark you are "
      + "placing by hand has to be exactly where you put it.",
    /* Only on the step that places them: away from it they are answered
       questions, and the carrier drawn from them says the same thing. */
    shown: activeMode === "carrier" && run.anchors.length > 0,
    staysSolid: true,
    /* An anchor is a statement about where the carrier is, and one made by hand
       can be corrected by hand: the four are put down where the shape says and
       moved from there to wherever the operator can actually see something to
       drive to. Dragged rather than retyped, because where it goes is decided
       by looking at the picture.

       Claimed here, on the layer the marks are drawn on. Nothing outside this
       file needed changing for it, which is the point of a layer owning what a
       press on it means. */
    claims: (drag) => {
      if (drag.phase === "started") {
        run.anchorHeld = under(drag);
        return run.anchorHeld >= 0;
      }
      if (!(run.anchorHeld >= 0)) return false;
      if (drag.phase === "moved") {
        run.anchors = run.anchors.map((a, i) => (
          i === run.anchorHeld ? { ...a, x: drag.at.x, y: drag.at.y } : a));
        /* The mark moves and so does what it says: one already driven to keeps
           its stage reading, so dragging it re-states where the carrier is and
           the drawing follows. */
        redraw();
        anchorsChanged?.();
        return true;
      }
      run.anchorHeld = -1;
      anchorsChanged?.();
      return true;
    },
    paint: (frame) => {
      const ctx = frame.context;
      /* Anchors are placed in the carrier's own coordinates, like everything
         else the run puts down, so they are drawn in the carrier's frame. */
      const { place } = drawnIn(frame);
      /* Green, and not the red the focus points and the stage mark use: an
         anchor is a place the carrier is being aligned from, which is a
         different kind of thing from where the microscope is or where it will
         measure — and three sorts of red crosshair on one picture is three
         things an operator has to tell apart by size. */
      run.anchors.forEach((a, i) => {
        const [x, y] = place(a.x, a.y);
        /* The one being pointed at in the list is drawn heavier and deeper, so
           a row and a mark can be matched by looking rather than by counting
           round the carrier. */
        const lit = i === (run.anchorLit ?? -1);
        /* The mark says the same thing its button does: amber while it is
           waiting to be driven to, green once it has been. An operator
           working through the four should be able to look at the picture and
           see which are left, without reading the list at all. */
        const colour = a.stage
          ? css(lit ? "--mark-anchor-lit" : "--good")
          : css("--warn-ink");
        ctx.strokeStyle = colour;
        ctx.fillStyle = colour;
        ctx.lineWidth = (a.stage ? 2.4 : 1.6) * (lit ? 1.8 : 1);
        crosshair(ctx, x, y, lit ? 13 : 11, 4, (a.stage ? 3 : 2) * (lit ? 1.5 : 1));
      });
    },
  },
  };
}
