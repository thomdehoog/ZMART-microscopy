/**
 * What step 3 draws on the picture: the plan, and the shape being drawn by hand.
 *
 * They are two layers rather than one because they answer different questions.
 * The plan is where the run will image; the editing chrome is the handles and
 * guides of whatever is being drawn right now, which is why it stays solid and
 * ends up on top — you cannot edit what you cannot see.
 */
export function scanAreaLayers(theRun) {
  const {
    run, drawnIn, scanfieldsWidget, activePreset, indexOfStep, editing, shown,
    asAPress, editorTook, renderRail,
  } = theRun;
  return {
    plan: {
    key: "plan",
    label: "Plan",
    explains: "The positions the microscope was told to visit. It stays readable once "
      + "the tiles start landing on top of it, dimmed, because by then the images "
      + "are the answer and this is only the question.",
    /* Not before the step that says where to scan. Walking back to the
       carrier is walking back to a question the plan is an answer to — the
       fields were placed against these areas, and drawing them over a plate
       that is still being changed shows a plan for a carrier that may be
       about to stop existing. The fields are kept, not discarded: coming
       forward again finds them where they were. */
    shown: run.activeIdx >= indexOfStep("scanfields"),
    paint: (frame) => {
      const ctx = frame.context;
      const { place, scale } = drawnIn(frame);
      scanfieldsWidget.drawOn(ctx, {
        fields: run.fields, preset: activePreset(), carrier: run.carrier,
        toScreen: place, scale: scale, dim: shown > 0,
        marked: editing?.marked(),
      });
    },
  },
    editing: {
    key: "editing",
    label: "Editing",
    explains: "The handles and guides of whatever is being drawn by hand. Always solid "
      + "and always on top: you cannot edit what you cannot see.",
    shown: !!editing,
    staysSolid: true,
    paint: (frame) => {
      const { place, scale } = drawnIn(frame);
      editing.drawChrome(frame.context, { toScreen: place, scale });
    },
    /* Drawing a region, moving a field, closing an outline: each is a press,
       then the moves, then the release, and the editor needs the whole gesture
       or none of it. It is asked before the focus map because it sits higher in
       the stack, which is also the order an operator expects — the thing being
       drawn answers first. */
    claims: (drag) => {
      const press = asAPress(drag);
      if (drag.phase === "started") return editorTook("down", press);
      if (drag.phase === "moved") { editorTook("move", press); return true; }
      editorTook("up", press);
      renderRail();
      return true;
    },
  },
  };
}
