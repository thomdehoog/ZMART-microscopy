/**
 * What step 2 draws on the picture: the plate, and the marks that register it.
 *
 * The carrier is the room the run happens in, so it is drawn low in the stack
 * and under everything the run then puts inside it. The anchors are the points
 * it is being registered from — where the plate really is, as against where it
 * was assumed to be — and they belong to the step that places them.
 */
export function carrierLayers(theRun) {
  const { run, css, drawnIn, carrierWidget, activeMode, crosshair } = theRun;
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
    paint: (frame) => {
      const ctx = frame.context;
      /* Anchors are placed in the carrier's own coordinates, like everything
         else the run puts down, so they are drawn in the carrier's frame. */
      const { place } = drawnIn(frame);
      ctx.strokeStyle = css("--mark-focus");
      ctx.fillStyle = css("--mark-focus");
      for (const a of run.anchors) {
        const [x, y] = place(a.x, a.y);
        ctx.lineWidth = a.stage ? 2.4 : 1.6;
        crosshair(ctx, x, y, 11, 4, a.stage ? 3 : 2);
      }
    },
  },
  };
}
