/**
 * Which microscopes a session can open, over which API, and what is checked
 * before a run is allowed to start.
 *
 * Sole owner of that catalogue. The names match the drivers in the repo —
 * `zmart_drivers/<vendor>/<microscope>/<api>` — because the session the
 * operator picks here is the driver that will be loaded, and inventing
 * friendly names that map to nothing would be a lie the day this is wired up.
 *
 * The checks are the interesting part. Connecting is not one action, it is a
 * handful of questions the answers to which the operator needs to see: an
 * autofocus that fails an hour into a run because the storage path was never
 * writable is a bad way to find out.
 */

export const MICROSCOPES = {
  mock: {
    label: "Mock",
    detail: "the controller's fake driver",
    vendor: "mock",
    /* What the bridge is asked to connect. */
    instrument: "mock",
    apis: {
      mock: { label: "Mock API", detail: "in-process · made-up data" },
    },
  },
  stellaris5: {
    label: "Leica Stellaris 5",
    detail: "y42h93",
    vendor: "leica",
    instrument: "leica",
    apis: {
      navigator_expert: { label: "Navigator Expert", detail: "CAM socket 8895 · LAS X 4.9" },
    },
  },
};

/**
 * The kinds of setting a run can record off the microscope.
 *
 * The operator sets the instrument up in its own software, names what they
 * have set up, and presses record — the controller reads the state back and
 * the run keeps it under that name. Nothing is typed in twice, which is the
 * point: a value re-entered by hand is a value that can disagree with the
 * instrument.
 *
 * This list is meant to grow. Adding a kind is adding an entry here; the panel
 * offers whatever is in it and always leaves an empty row at the bottom.
 * `sample` stands in for the controller read that a real backend would do.
 */
/**
 * A reading is a summary and the detail behind it, composed from what the
 * controller reports rather than written out twice.
 *
 * The frame is the case that matters: it is the pixel count times the pixel
 * size, so it is worked out here and carried as a number. Anything that has to
 * lay tiles out needs that number, and a number living only inside a sentence
 * meant for reading is a number nothing can use — which is how the overview
 * tile size came to be typed a second time somewhere else.
 */
const acquisition = ({ summary, objective, pixelUm, framePx, channels, zStack }) => {
  const frameUm = Math.round(framePx * pixelUm);
  return {
    summary, pixelUm, framePx, frameUm,
    detail: [
      ["Objective", objective],
      ["Pixel size", `${pixelUm.toFixed(2)} µm`],
      ["Frame", `${framePx} × ${framePx} px · ${frameUm} × ${frameUm} µm`],
      ...channels.map((c, i) => [`Channel ${i + 1}`, c]),
      ["Z stack", zStack],
    ],
  };
};

/* An autofocus runs through an objective like anything else, so it reports the
   same summary and the same frame an acquisition does. Its detail carries the
   sweep instead of a stack. */
/**
 * An autofocus is one of two things, and which one it is decides the rest of
 * what it reports.
 *
 * **Software** focuses by looking: it takes a short stack, scores each plane by
 * a sharpness metric and keeps the best one. It costs frames and time, it can
 * be fooled by a field with nothing in it, and it is described by its metric,
 * how far it sweeps and in what steps.
 *
 * **Hardware** focuses by measuring: a beam off the coverslip tells the stand
 * how far the glass is, and it holds that distance. It costs almost nothing
 * and never looks at the sample, so it is described by the offset from the
 * glass at which the sample sits — and it can hold nothing at all if there is
 * no coverslip to bounce off.
 *
 * Written out as two builders rather than one with a flag, because a hardware
 * autofocus has no metric, no sweep and no steps: filling those in as blanks
 * would be a form pretending the two are the same kind of thing.
 */
const softwareAutofocus = ({ objective, pixelUm, framePx, channel, metric, range, steps }) => {
  const frameUm = Math.round(framePx * pixelUm);
  return {
    summary: `Software · ${short(objective)}`,
    kind: "software", pixelUm, framePx, frameUm,
    detail: [
      ["Focus", "Software · sharpness of the image"],
      ["Objective", objective],
      ["Channel", channel],
      ["Frame", `${framePx} × ${framePx} px · ${frameUm} × ${frameUm} µm`],
      ["Metric", metric],
      ["Range", range],
      ["Steps", steps],
    ],
  };
};

const hardwareAutofocus = ({ objective, pixelUm, framePx, source, offset, hold }) => {
  const frameUm = Math.round(framePx * pixelUm);
  return {
    summary: `Hardware · ${short(objective)}`,
    kind: "hardware", pixelUm, framePx, frameUm,
    detail: [
      ["Focus", "Hardware · reflection off the coverslip"],
      ["Objective", objective],
      ["Source", source],
      ["Frame", `${framePx} × ${framePx} px · ${frameUm} × ${frameUm} µm`],
      ["Offset", offset],
      ["Hold", hold],
    ],
  };
};

/**
 * The short way an objective is said when it shares a line with something —
 * its magnification and nothing else. The row an autofocus is read on is a
 * column of a narrow channel, and what an operator picks between there is
 * software or hardware and through which lens; the rest of it is one fold
 * away.
 */
const short = (objective) => objective.match(/\d+x/)?.[0] ?? objective;

export const SETTING_TYPES = [
  {
    key: "acquisition",
    label: "Acquisition",
    readings: [
      /* First in the list because the first recording an operator takes is
         the overview, and the overview is imaged at 20x. */
      acquisition({
        summary: "20x / 0.75 NA dry · 2 channels",
        objective: "HC PL APO 20x / 0.75 NA dry",
        pixelUm: 0.33, framePx: 2048,
        channels: ["DAPI · 405 nm · 50 ms · gain 1.0", "GFP · 488 nm · 120 ms · gain 1.2"],
        zStack: "off",
      }),
      acquisition({
        summary: "63x / 1.40 NA oil · 2 channels",
        objective: "HC PL APO 63x / 1.40 NA oil",
        pixelUm: 0.10, framePx: 1024,
        channels: ["DAPI · 405 nm · 30 ms · gain 1.0", "GFP · 488 nm · 80 ms · gain 1.5"],
        zStack: "11 planes · 0.50 µm",
      }),
      acquisition({
        summary: "10x / 0.40 NA dry · 1 channel",
        objective: "HC PL APO 10x / 0.40 NA dry",
        pixelUm: 0.65, framePx: 2048,
        channels: ["GFP · 488 nm · 60 ms · gain 1.0"],
        zStack: "off",
      }),
      acquisition({
        summary: "40x / 1.10 NA water · 3 channels",
        objective: "HC PL APO 40x / 1.10 NA water",
        pixelUm: 0.16, framePx: 1024,
        channels: [
          "DAPI · 405 nm · 40 ms · gain 1.0",
          "GFP · 488 nm · 90 ms · gain 1.3",
          "mCherry · 561 nm · 150 ms · gain 1.6",
        ],
        zStack: "21 planes · 0.30 µm",
      }),
      acquisition({
        summary: "5x / 0.15 NA dry · 2 channels",
        objective: "HC PL FLUOTAR 5x / 0.15 NA dry",
        pixelUm: 1.30, framePx: 2048,
        channels: ["DAPI · 405 nm · 50 ms · gain 1.0", "GFP · 488 nm · 120 ms · gain 1.2"],
        zStack: "off",
      }),
    ],
  },
  {
    key: "autofocus",
    label: "Focus",
    readings: [
      softwareAutofocus({
        objective: "HC PL APO 10x / 0.40 NA dry",
        pixelUm: 0.65, framePx: 2048,
        channel: "GFP · 488 nm · 20 ms · gain 1.0",
        metric: "Brenner gradient", range: "±30 µm", steps: "61 · 1.0 µm apart",
      }),
      hardwareAutofocus({
        objective: "HC PL APO 20x / 0.75 NA dry",
        pixelUm: 0.33, framePx: 2048,
        source: "785 nm · off the coverslip",
        offset: "12.4 µm above the glass",
        hold: "continuous, while the stage moves",
      }),
      softwareAutofocus({
        objective: "HC PL FLUOTAR 5x / 0.15 NA dry",
        pixelUm: 1.30, framePx: 2048,
        channel: "GFP · 488 nm · 30 ms · gain 1.0",
        metric: "DCT energy", range: "±60 µm", steps: "41 · 3.0 µm apart",
      }),
      hardwareAutofocus({
        objective: "HC PL APO 63x / 1.40 NA oil",
        pixelUm: 0.10, framePx: 1024,
        source: "785 nm · off the coverslip",
        offset: "3.0 µm above the glass",
        hold: "on arrival at each position",
      }),
    ],
  },
];

export const settingType = (key) => SETTING_TYPES.find((t) => t.key === key);

/** What the controller reports for the nth recording of a kind. */
export const sampleReading = (key, nth) => {
  const { readings } = settingType(key);
  return readings[nth % readings.length];
};

/**
 * How far the stage can travel, in millimetres — the canvas is this area drawn
 * to scale, and every carrier sits inside it.
 *
 * A stand-in until the controller is asked. One number for every microscope
 * here, which is exactly the part that is not true: it is the first thing the
 * live driver replaces, per instrument.
 */
export const STAGE_LIMITS_MM = { width: 120, height: 80 };

export const DEFAULT_SESSION = {
  /* The mock, so a page opened by accident drives nothing. */
  microscope: "mock",
  api: "mock",
  /* Prefilled so the mock can be clicked through without typing. A real build
     must ship this empty — a default credential is not a convenience, it is a
     credential everybody has. */
  password: "demo",
};

/** The APIs a microscope offers, as [key, {label, detail}] pairs. */
export const apisFor = (microscope) =>
  Object.entries(MICROSCOPES[microscope]?.apis ?? {});

/** The first API a microscope offers — what to fall back to when it changes. */
export const defaultApiFor = (microscope) => apisFor(microscope)[0]?.[0] ?? null;

export const describeSession = ({ microscope, api }) => {
  const scope = MICROSCOPES[microscope];
  const apiDef = scope?.apis?.[api];
  return scope && apiDef ? `${scope.label} · ${apiDef.label}` : "not chosen";
};

/**
 * What connecting actually verifies, in the order it is verified. Each check
 * knows how to describe its own result for the session it was run against, so
 * adding one is adding an entry here and nothing else.
 */
export const CONNECT_CHECKS = [
  {
    id: "reachable",
    label: "Microscope reachable",
    result: ({ api }) => (api === "navigator_expert" ? "127.0.0.1:8895" : "in-process"),
  },
  {
    id: "credentials",
    label: "Credentials accepted",
    result: () => "token valid",
  },
  {
    id: "version",
    label: "API version",
    result: ({ microscope, api }) => MICROSCOPES[microscope]?.apis?.[api]?.detail ?? "unknown",
  },
  {
    id: "stage",
    label: "Stage responds",
    result: () => "x 0.0 · y 0.0 · z −412.0 µm",
  },
  {
    id: "objectives",
    label: "Objectives listed",
    result: () => "5x, 63x",
  },
  {
    id: "storage",
    label: "Storage writable",
    result: () => "smart/organoid-screen_a7f3c1/",
  },
];

