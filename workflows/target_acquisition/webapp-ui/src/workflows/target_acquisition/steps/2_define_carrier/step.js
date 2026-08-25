/**
 * Step 2 — Define Carrier.
 *
 * The step that puts the run on the stage. Asking for the canvas here is what
 * brings the picture up, and it stays for every step after this one, because
 * from here on the run is something that happens on a stage.
 *
 * The controls this step docks beside the canvas live in `widget.js`, in this
 * same folder; what a carrier *is* — where its wells sit, how wide they are —
 * lives in `../../shared/carriers.js`, because the scan-area step needs the
 * same geometry and two copies of a fact drift apart in silence.
 */

export const carrierConfiguration = {
  id: "carrier",
  title: "Define Carrier",
  why: "Tell the run what the sample is mounted in — it says where within the stage the sample sits.",
  panels: ["canvas"],
  mode: "carrier",
};

/* Registering the carrier — saying where the thing described here actually
   sits on the stage — belongs in the step above and will be built into it.
   It had a step of its own for a while, empty and declared a placeholder, and
   an empty step in the rail is a promise the run keeps failing to keep: the
   operator counts it, walks to it, finds nothing, and walks on. What it will
   be is another part of describing the carrier, which is what that step is
   for, so it will arrive there rather than here. */
