/**
 * The step catalogue.
 *
 * Workflows compose from this rather than retyping. A step owns its own
 * readiness rule and its own work, so the frame never learns what "focus" or
 * "detect" mean — which is what makes a new workflow a list rather than a
 * change to the shell.
 *
 * Every `run` receives:
 *
 *   backend  the microscope, mock or real
 *   run      the current run state, to read
 *   update   (patch, note?) — merge state, optionally set this step's result
 *   note     (text) — set this step's result line
 */

export const connect = {
  id: "connect",
  title: "Connect",
  why: "Opens the microscope session and starts the analysis engine.",
  button: "Connect",
  run: async ({ backend, note }) => note(await backend.connect()),
};

export const setOrigin = {
  id: "origin",
  title: "Set origin",
  why: "Marks the stage where it stands as (0, 0) for this run.",
  button: "Set origin",
  run: async ({ backend, update }) =>
    update({ originSet: true }, await backend.setOrigin()),
};

export const captureOverviewJob = {
  id: "job_ov",
  title: "Capture overview job",
  why: "Select the low-magnification job in LAS X, then capture its settings.",
  button: "Capture overview job",
  run: async ({ backend, note }) => note(await backend.captureJob("overview")),
};

export const captureTargetJob = {
  id: "job_tg",
  title: "Capture target job",
  why: "Now select the high-magnification job and capture it too.",
  button: "Capture target job",
  run: async ({ backend, note }) => note(await backend.captureJob("target")),
};

export const focusStrategy = {
  id: "focus",
  title: "Focus strategy",
  why: "Choose how this run keeps every image sharp across the sample.",
  button: "Apply strategy",
  widget: "focus",
  ready: ({ focus }) =>
    (focus.strategy === "plane" && focus.points.length < 3 ? "place at least 3 points" : null),
  run: async ({ backend, run, update }) => {
    const result = await backend.measureFocus(run.focus);
    update({
      focus: {
        ...run.focus, ...result, applied: true,
        points: result.points, selected: 0,
      },
    }, result.note);
  },
};

export const scanOverview = {
  id: "scan",
  title: "Scan the overview",
  why: "Drives the stage through every position, stitching tiles as they are saved.",
  button: "Scan overview",
  run: async ({ backend, update, note }) => {
    note(await backend.scanOverview({
      onProgress: (n, total) => update({ tiles: n }, `${n} / ${total} tiles`),
    }));
  },
};

export const detectCells = {
  id: "detect",
  title: "Detect cells",
  why: "Segments every overview tile. Each cell found becomes one point.",
  button: "Detect cells",
  widget: "detect",
  ready: ({ detect }) => (detect.tested ? null : "try it on one tile first"),
  run: async ({ backend, run, update }) => {
    const { ids, note } = await backend.detectAll(run.detect);
    update({ detected: ids, cellsShown: true }, note);
  },
};

export const selectCells = {
  id: "select",
  title: "Select cells",
  why: "Gate the cells worth imaging — drag a box on the plot, or pick them on the canvas.",
  button: "Confirm selection",
  widget: "analysis",
  ready: ({ gated }) => (gated.size ? null : "nothing gated yet"),
  run: async ({ backend, run, note }) => note(await backend.confirmSelection(run.gated)),
};

export const acquireAndCurate = {
  id: "acquire",
  title: "Acquire and curate",
  why: "Images the selected cells at target magnification and collects your verdicts.",
  button: "Acquire selection",
  widget: "gallery",
  ready: ({ gated }) => (gated.size ? null : "nothing selected yet"),
  run: async ({ backend, run, update }) => {
    const { pairs, note } = await backend.acquire(run.gated);
    update({ acquired: pairs }, note);
  },
};

export const saveRun = {
  id: "save",
  title: "Save the run",
  why: "Writes the report, the layout picture and your verdicts beside the images.",
  button: "Save results",
  run: async ({ backend, note }) => note(await backend.saveResults()),
};

export const disconnect = {
  id: "disconnect",
  title: "Disconnect",
  why: "Releases the microscope and shuts the analysis engine down.",
  button: "Disconnect",
  run: async ({ backend, update }) =>
    update({ locked: false }, await backend.disconnect()),
};

/** Same step, different words — a calibration run explains itself differently. */
export const reworded = (step, changes) => ({ ...step, ...changes });
