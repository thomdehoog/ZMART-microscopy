/**
 * The step catalogue: every step that any workflow on this page can be built
 * from.
 *
 * Workflows compose from this rather than retyping, so a step that several runs
 * share is described in one place. Reword `connect` here and every workflow that
 * connects to a microscope says the new thing.
 *
 * This file is what the page runs on. `main.js` imports the workflows built out
 * of these steps, and so do the unit tests, so there is one description of a
 * step and both the operator and the tests are looking at it.
 *
 * What a step is made of
 * ----------------------
 *
 *   id         the short name the page files this step's result under
 *   title      what the step is called in the rail down the left
 *   why        one sentence saying what the step is for
 *   panels     which modules the step wants on screen, named. An empty list
 *              means "nothing of my own"; see `frame/steps.js`, which decides
 *              what that comes to once the canvas is in play.
 *   btn        the words on the button that carries the step out. A step with
 *              no `btn` has nothing to press.
 *   ownButton  the step's own panel builds its button, so the frame should not
 *              add a second one underneath.
 *   ms         how long this rehearsal pretends the work takes, in
 *              milliseconds. The page is a mock of a microscope for now; when a
 *              real instrument is wired in this is what the wait becomes.
 *   mode       which piece of behaviour `main.js` runs for this step —
 *              measuring focus, scanning, detecting, and so on.
 *   ready      what the step still needs before it may be carried out. It is
 *              handed the run so far and answers either `null`, meaning go
 *              ahead, or a short phrase saying what is missing, which the page
 *              shows beside the greyed-out button. A step with no rule is
 *              always ready.
 *   note       what the step writes beside itself in the rail once it has
 *              finished, for steps whose result is always the same sentence.
 *   nothingWaitsOnThis
 *              the steps after this one do not wait for it. A run is walked in
 *              order because each step usually produces something the next one
 *              needs; a step that only shows the operator something produces
 *              nothing to wait for, and saying so here lets them walk straight
 *              past it. See `frame/steps.js`, which is where the rule lives.
 *
 * Readiness belongs to the step rather than to the page around it. Only the
 * focus step knows that fitting a surface from points needs at least three of
 * them, and putting that here is what lets a new workflow be a list of steps
 * instead of another rule added to the shell.
 *
 * A step without a button is not an unfinished step. Some steps are completed by
 * doing the thing they are about — the carrier is settled by being configured,
 * the scan fields by being drawn, the viewer by being looked at — and asking for
 * a press afterwards would only ask the operator to confirm what they have
 * already done.
 */

/* Whether a step has what it needs is asked of the slot itself: a step waits
   for a reading to have been taken, not for a particular field on a record. */
import { activeRecording, hasRecording } from "../lib/recordings.js";

/** Which kind of autofocus the step is working with, if any. */
const autofocusKind = (slot) => activeRecording(slot)?.kind ?? null;

export const connect = {
  id: "connect",
  title: "Connect",
  why: "Choose the microscope, its API and the password, then open the session.",
  btn: "Connect",
  ownButton: true,
  /* The first step asks for the canvas, so the stage is there from the start:
     every step keeps the picture on the left and its controls in the channel. */
  panels: ["canvas"],
  ms: 1900,
};

/* The step that puts the run on the stage. Asking for the canvas here is what
   brings the picture up, and it stays for every step after this one, because
   from here on the run is something that happens on a stage. */
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

/* The preset the overview is taken with is recorded here, not in a step of
   its own: the fields take their frame from it, so it is tested where it
   matters. */
export const initialScanfields = {
  id: "scanfields",
  title: "Overview scan settings",
  why: "Record the preset the overview is taken with, then say where on the carrier it is taken.",
  panels: [],
  mode: "scanfields",
};

/* The autofocus preset is recorded here for the same reason: the sweeps that
   measure the surface are taken with it. */
export const focusStrategy = {
  id: "focus",
  title: "Autofocus settings",
  why: "Record the autofocus preset, then choose how this run keeps every image sharp across the sample.",
  btn: "Apply strategy",
  panels: [],
  ms: 1400,
  mode: "focus",
  /* Only one of the strategies has anything to wait for. Fitting a surface to
     measured positions needs at least three of them, because two points
     describe a line rather than a plane. A fixed height, autofocus at every
     position and reusing an earlier surface each have everything they need the
     moment they are chosen. */
  ready: ({ focus, focusPreset }) =>
    (!hasRecording(focusPreset) ? "record the autofocus preset first"
      : autofocusKind(focusPreset) === "hardware" ? null
        : focus.strategy === "plane" && focus.points.length < 3
          ? "place at least 3 points"
          : null),

  /* A hardware autofocus is not something the run performs. The stand holds
     focus itself, off the coverslip, at every position it is sent to — so
     there is no surface to measure and nothing to press, and the step is
     finished the moment such a reading is the active one. Only a software
     autofocus, which focuses by taking a short stack and scoring it, leaves
     the run anything to do. */
  acts: ({ focusPreset }) => autofocusKind(focusPreset) !== "hardware",
};

/* The count is the smaller half of what this step reports. The other half is
   the picture: the overview drawn from the images the run is writing, filling
   in position by position, so the operator can see that the sample is where it
   was meant to be and that the focus held — neither of which a count can say.
   `live/overview.js` holds that picture and explains how it is kept up to
   date. */
export const scanOverview = {
  id: "scan",
  title: "Scan the overview",
  why: "Drives the stage through every position, stitching tiles as they are saved.",
  btn: "Scan overview",
  panels: [],
  ms: 2600,
  mode: "scan",
};

/* Discovery brings no panel of its own: the targets it finds land on the
   canvas, and its controls sit in the channel beside it, the same shape as
   focus. */
export const detectCells = {
  id: "detect",
  title: "Discover Targets",
  why: "Segments every overview tile. Each cell found becomes one target candidate.",
  btn: "Discover Targets",
  panels: [],
  ms: 1600,
  mode: "detect",
  /* Settings are tried on a single tile first, because running them over every
     tile and then finding they were wrong is a long way to go for an answer. */
  ready: ({ detect }) => (detect.tested ? null : "try it on one tile first"),
};

/* Refinement is the same shape: the refined targets light up on the canvas,
   and the channel holds the scatter they are gated on. */
export const selectCells = {
  id: "select",
  title: "Refine Targets",
  why: "Gate the targets worth imaging — drag a box on the plot, or pick them on the canvas.",
  btn: "Confirm selection",
  panels: [],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};

/* And the gallery joins the channels: the acquired targets ring on the
   canvas, and the channel holds the acquisition type being recorded, the
   pairs, and the verdicts collected on them. */
export const acquireAndCurate = {
  id: "acquire",
  title: "Acquire Targets",
  why: "Record the acquisition type, then image every refined target with it and collect your verdicts.",
  btn: "Acquire Targets",
  panels: [],
  ms: 2200,
  mode: "targets",
  /* Acquiring needs to know what with: the type is a reading taken off the
     instrument in this step's own channel, the way an optics preset is. */
  ready: ({ gated, targetType }) =>
    (gated.size === 0 ? "nothing gated yet"
      : hasRecording(targetType) ? null : "record the acquisition type first"),
};

export const saveRun = {
  id: "save",
  title: "Save the run",
  why: "Writes the report, the layout picture and your verdicts beside the images.",
  btn: "Save results",
  panels: [],
  ms: 800,
  note: "report + layout written",
};


/**
 * The two steps of the canvas demonstration.
 *
 * Neither of these is a step of a real run, and the workflow they belong to says
 * so in its name. They exist so that the canvas — the picture of a run that an
 * operator pans and zooms — can be watched behaving inside the real operator
 * window, before it is put to work in a workflow that drives a microscope.
 *
 * There are two of them because the canvas is being written more than once, each
 * time over a different drawing engine, and the only fair way to compare two
 * ways of drawing the same thing is to look at one and then the other. So one
 * step opens the picture with Viv and the other opens it with neuroglancer.
 *
 * ## They do not wait for each other
 *
 * Both say `nothingWaitsOnThis`, which means the operator may go straight to
 * either one, in either order, as often as they like. That is not a shortcut: a
 * step that only shows you something produces nothing for a later step to use,
 * so there is genuinely nothing to wait for. The two steps share no state at
 * all — each opens its own picture, in its own box, with its own engine — so
 * whatever you do in one of them cannot change what the other shows. That is the
 * point of having two: any difference you see between them is a difference
 * between the two engines and nothing else.
 *
 * ## Each asks for one module and gets that alone
 *
 * There is no panel of controls down the right-hand side, because these steps
 * want only the picture and the handful of buttons above it.
 */
/**
 * The one bench step: a run, and the engines compared against each other in it.
 *
 * There were two of these, one per engine. They were dropped into one because the
 * row of engine buttons above the picture already does the comparing, and does it
 * better: changing engine keeps the view exactly where it is, so the same scene
 * is seen through each in turn rather than through two pictures that were never
 * guaranteed to be looking at the same place.
 */
export const theCanvas = {
  id: "canvas-picture",
  title: "Viewer comparison",
  why: "Opens the run and draws its three layers, once per drawing engine, side by side on the same scene.",
  panels: ["viewer-canvas"],
  nothingWaitsOnThis: true,
};

/**
 * The same step, in different words.
 *
 * A calibration run and an imaging run both save at the end, but they are saving
 * different things and should say so. This returns a copy of a step with some of
 * its wording replaced, which keeps what the step *does* in one place while
 * letting each workflow explain it in its own terms.
 */
export const reworded = (step, changes) => ({ ...step, ...changes });
