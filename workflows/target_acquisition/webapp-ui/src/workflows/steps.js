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

export const connect = {
  id: "connect",
  title: "Microscope configuration",
  why: "Choose the microscope, its API and the password, then open the session.",
  btn: "Connect",
  ownButton: true,
  panels: ["connect"],
  ms: 1900,
};

export const opticalConfiguration = {
  id: "optics",
  title: "Optical configuration",
  why: "Set the microscope up in its own software, name the preset, and record it.",
  ownButton: true,
  panels: ["optics"],
  mode: "optics",
  /* A preset is recorded once it has been read off the instrument, which is
     what gives a bar something to say for itself. */
  ready: ({ bars }) =>
    (bars.some((b) => b.state) ? null : "record at least one preset"),
};

/* The step that puts the run on the stage. Asking for the canvas here is what
   brings the picture up, and it stays for every step after this one, because
   from here on the run is something that happens on a stage. */
export const carrierConfiguration = {
  id: "carrier",
  title: "Carrier configuration",
  why: "Tell the run what the sample is mounted in — it says where within the stage the sample sits.",
  panels: ["canvas"],
  mode: "carrier",
};

export const initialScanfields = {
  id: "scanfields",
  title: "Initial scanfields",
  why: "Say where on the carrier the overview is taken — a block in every area, or regions drawn by hand.",
  panels: [],
  mode: "scanfields",
};

export const focusStrategy = {
  id: "focus",
  title: "Focus strategy",
  why: "Choose how this run keeps every image sharp across the sample.",
  btn: "Apply strategy",
  panels: ["focus"],
  ms: 1400,
  mode: "focus",
  /* Only one of the strategies has anything to wait for. Fitting a surface to
     measured positions needs at least three of them, because two points
     describe a line rather than a plane. A fixed height, autofocus at every
     position and reusing an earlier surface each have everything they need the
     moment they are chosen. */
  ready: ({ focus }) =>
    (focus.strategy === "plane" && focus.points.length < 3
      ? "place at least 3 points"
      : null),
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

export const detectCells = {
  id: "detect",
  title: "Detect cells",
  why: "Segments every overview tile. Each cell found becomes one point.",
  btn: "Detect cells",
  panels: ["detect"],
  ms: 1600,
  mode: "detect",
  /* Settings are tried on a single tile first, because running them over every
     tile and then finding they were wrong is a long way to go for an answer. */
  ready: ({ detect }) => (detect.tested ? null : "try it on one tile first"),
};

export const selectCells = {
  id: "select",
  title: "Select cells",
  why: "Gate the cells worth imaging — drag a box on the plot, or pick them on the canvas.",
  btn: "Confirm selection",
  panels: ["analysis"],
  ms: 600,
  mode: "select",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
};

export const acquireAndCurate = {
  id: "acquire",
  title: "Acquire and curate",
  why: "Images the selected cells at target magnification and collects your verdicts.",
  btn: "Acquire selection",
  panels: ["gallery"],
  ms: 2200,
  mode: "targets",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
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

export const disconnect = {
  id: "disconnect",
  title: "Disconnect",
  why: "Releases the microscope and shuts the analysis engine down.",
  btn: "Disconnect",
  panels: [],
  ms: 600,
  note: "session closed",
};

/**
 * The canvas on its own, with the whole window to itself.
 *
 * This step has no action and produces nothing. Standing on it is the whole of
 * it: the picture of the run appears, and the operator pans, zooms and changes
 * the engine drawing it. That is unusual for a step and it is deliberate — the
 * canvas is being built to be put into several workflows later, and a step that
 * does nothing but show it is how it can be tried in the real operator window
 * first, on its own, without an acquisition going on around it.
 *
 * It asks for one module and names it, so it is given that and nothing else.
 * There is no panel of controls down the right-hand side, because this step
 * wants only the picture.
 */
export const lookAtTheRun = {
  id: "viewer",
  title: "Look at the run",
  why: "Draws the run this page was pointed at, so the canvas can be tried on its own.",
  panels: ["viewer"],
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
