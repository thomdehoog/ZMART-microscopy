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
  stellaris5: {
    label: "Leica Stellaris 5",
    detail: "y42h93",
    vendor: "leica",
    apis: {
      cam: { label: "CAM", detail: "socket · LAS X 4.9" },
      pyapi: { label: "PyApi", detail: "in-process · LAS X 4.9" },
    },
  },
  zen: {
    label: "Zeiss ZEN",
    detail: "zenapi",
    vendor: "zeiss",
    apis: {
      zenapi: { label: "ZEN API", detail: "gRPC · gateway token" },
    },
  },
  mesospim: {
    label: "mesoSPIM",
    detail: "benchtop",
    vendor: "mesospim",
    apis: {
      remote_control: { label: "Remote Control", detail: "TCP 42000" },
      remote_scripting: { label: "Remote Scripting", detail: "legacy bridge" },
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
const autofocus = ({ summary, objective, pixelUm, framePx, channel, metric, range, steps }) => {
  const frameUm = Math.round(framePx * pixelUm);
  return {
    summary, pixelUm, framePx, frameUm,
    detail: [
      ["Objective", objective],
      ["Channel", channel],
      ["Frame", `${framePx} × ${framePx} px · ${frameUm} × ${frameUm} µm`],
      ["Metric", metric],
      ["Range", range],
      ["Steps", steps],
    ],
  };
};

export const SETTING_TYPES = [
  {
    key: "acquisition",
    label: "Acquisition",
    readings: [
      acquisition({
        summary: "5x / 0.15 NA dry · 2 channels",
        objective: "HC PL FLUOTAR 5x / 0.15 NA dry",
        pixelUm: 1.30, framePx: 2048,
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
    ],
  },
  {
    key: "autofocus",
    label: "Autofocus",
    readings: [
      autofocus({
        summary: "10x / 0.40 NA dry · 1 channel",
        objective: "HC PL APO 10x / 0.40 NA dry",
        pixelUm: 0.65, framePx: 2048,
        channel: "GFP · 488 nm · 20 ms · gain 1.0",
        metric: "Brenner gradient", range: "±30 µm", steps: "61 · 1.0 µm apart",
      }),
      autofocus({
        summary: "5x / 0.15 NA dry · 1 channel",
        objective: "HC PL FLUOTAR 5x / 0.15 NA dry",
        pixelUm: 1.30, framePx: 2048,
        channel: "GFP · 488 nm · 30 ms · gain 1.0",
        metric: "DCT energy", range: "±60 µm", steps: "41 · 3.0 µm apart",
      }),
      autofocus({
        summary: "20x / 0.75 NA dry · 1 channel",
        objective: "HC PL APO 20x / 0.75 NA dry",
        pixelUm: 0.33, framePx: 2048,
        channel: "DAPI · 405 nm · 15 ms · gain 1.0",
        metric: "Brenner gradient", range: "±15 µm", steps: "31 · 1.0 µm apart",
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
  microscope: "stellaris5",
  api: "cam",
  /* Prefilled so the mock can be clicked through without typing. A real build
     must ship this empty — a default credential is not a convenience, it is a
     credential everybody has. */
  password: "demo",
};

/**
 * Presets the mock starts with, as though they had already been recorded.
 *
 * The same convenience the prefilled password is, and the same caveat: a real
 * build starts with none. Recording is the work this step exists for, and a
 * preset that was never read off an instrument is a preset that can disagree
 * with one.
 *
 * One of each thing a target run needs — the low magnification it maps the
 * sample at, the high one it images single cells at, and the autofocus that
 * keeps both sharp. `nth` picks which reading the controller returns, so the
 * magnifications here are the ones those readings actually describe.
 */
export const DEMO_PRESETS = [
  { name: "Overview", type: "acquisition", nth: 0 },
  { name: "Target", type: "acquisition", nth: 1 },
  { name: "AF", type: "autofocus", nth: 0 },
];

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
 * What an opened session says for itself, once every check has answered. The
 * rail carries the same fact as a label; this is the sentence the checks end
 * on, so the two are worded here rather than in the panel that shows them.
 *
 * Returned in pieces, with the two names marked, so whatever shows the
 * sentence can set them apart from the words around them without slicing a
 * string it did not write.
 */
export const describeConnection = ({ microscope, api }) => {
  const scope = MICROSCOPES[microscope];
  const apiDef = scope?.apis?.[api];
  if (!scope || !apiDef) return [{ text: "No session is open" }];
  return [
    { text: "Successfully connected to the " },
    { text: scope.label, name: true },
    { text: " over " },
    { text: apiDef.label, name: true },
  ];
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
    result: ({ microscope, api }) => {
      const port = { cam: "8895", pyapi: "in-process", zenapi: "50051", remote_control: "42000", remote_scripting: "42100" }[api];
      return micro(microscope) === "mesospim" ? `127.0.0.1:${port}` : `127.0.0.1:${port}`;
    },
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
    result: ({ microscope }) =>
      (micro(microscope) === "mesospim" ? "4x, 16x" : "5x, 63x"),
  },
  {
    id: "storage",
    label: "Storage writable",
    result: () => "smart/organoid-screen_a7f3c1/",
  },
];

const micro = (key) => MICROSCOPES[key]?.vendor;
