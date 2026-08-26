/**
 * What step 4 draws on the picture: the focus map.
 *
 * The points measured, the sweeps that measured them, and the surface fitted
 * through them, drawn in the stage's own projection because they are a
 * statement about the same glass the plan is drawn on.
 */
export function focusLayers(theRun) {
  const { drawnIn, activeMode, drawFocusLayer } = theRun;
  return {
    focus: {
    key: "focus",
    label: "Focus",
    explains: "Where the microscope will focus, and what it has measured there. Stays "
      + "solid however far the rest is faded: fading the plan to see the picture is "
      + "not a request to lose the focus points too.",
    /* Only while standing on that step — walking away leaves the canvas the
       plain picture every other step reads. */
    shown: activeMode === "focus",
    /* Not held back to the end, though it was at first. The scan fields are
       drawn *over* the focus map — that is the order the page had before
       any of this was a stack — and holding the map back put it on top
       instead, which covered the very fields the operator is placing focus
       points among. A layer that stays solid is a layer drawn last, so it
       cannot also be a layer drawn early: this one has to be early, and the
       cost is that the shared fade reaches it. Splitting the map from the
       points would buy back both, and is the thing to do if that fade ever
       matters here. */
    paint: (frame) => {
      const { place, scale, w, h } = drawnIn(frame);
      drawFocusLayer(frame.context, place, scale, w, h);
    },
  },
  };
}
