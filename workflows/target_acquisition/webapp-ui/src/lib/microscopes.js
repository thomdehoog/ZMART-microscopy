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
export const SETTING_TYPES = [
  {
    key: "acquisition",
    label: "Acquisition",
    /* A reading is a summary and the detail behind it. The summary is the
       objective and the channel count — what decides whether a preset can see
       the thing being looked for. The detail is everything the controller
       read, for when the summary is not enough to trust it. */
    readings: [
      {
        summary: "5x / 0.15 NA dry · 2 channels",
        detail: [
          ["Objective", "HC PL FLUOTAR 5x / 0.15 NA dry"],
          ["Pixel size", "1.30 µm"],
          ["Frame", "2048 × 2048 px · 2662 × 2662 µm"],
          ["Channel 1", "DAPI · 405 nm · 50 ms · gain 1.0"],
          ["Channel 2", "GFP · 488 nm · 120 ms · gain 1.2"],
          ["Z stack", "off"],
        ],
      },
      {
        summary: "63x / 1.40 NA oil · 2 channels",
        detail: [
          ["Objective", "HC PL APO 63x / 1.40 NA oil"],
          ["Pixel size", "0.10 µm"],
          ["Frame", "1024 × 1024 px · 102 × 102 µm"],
          ["Channel 1", "DAPI · 405 nm · 30 ms · gain 1.0"],
          ["Channel 2", "GFP · 488 nm · 80 ms · gain 1.5"],
          ["Z stack", "11 planes · 0.50 µm"],
        ],
      },
      {
        summary: "10x / 0.40 NA dry · 1 channel",
        detail: [
          ["Objective", "HC PL APO 10x / 0.40 NA dry"],
          ["Pixel size", "0.65 µm"],
          ["Frame", "2048 × 2048 px · 1331 × 1331 µm"],
          ["Channel 1", "GFP · 488 nm · 60 ms · gain 1.0"],
          ["Z stack", "off"],
        ],
      },
      {
        summary: "40x / 1.10 NA water · 3 channels",
        detail: [
          ["Objective", "HC PL APO 40x / 1.10 NA water"],
          ["Pixel size", "0.16 µm"],
          ["Frame", "1024 × 1024 px · 164 × 164 µm"],
          ["Channel 1", "DAPI · 405 nm · 40 ms · gain 1.0"],
          ["Channel 2", "GFP · 488 nm · 90 ms · gain 1.3"],
          ["Channel 3", "mCherry · 561 nm · 150 ms · gain 1.6"],
          ["Z stack", "21 planes · 0.30 µm"],
        ],
      },
    ],
  },
  {
    key: "autofocus",
    label: "Autofocus",
    /* An autofocus runs through an objective like anything else, so it reports
       the same summary an acquisition does. Its detail carries the sweep. */
    readings: [
      {
        summary: "10x / 0.40 NA dry · 1 channel",
        detail: [
          ["Objective", "HC PL APO 10x / 0.40 NA dry"],
          ["Channel", "GFP · 488 nm · 20 ms · gain 1.0"],
          ["Metric", "Brenner gradient"],
          ["Range", "±30 µm"],
          ["Steps", "61 · 1.0 µm apart"],
        ],
      },
      {
        summary: "5x / 0.15 NA dry · 1 channel",
        detail: [
          ["Objective", "HC PL FLUOTAR 5x / 0.15 NA dry"],
          ["Channel", "GFP · 488 nm · 30 ms · gain 1.0"],
          ["Metric", "DCT energy"],
          ["Range", "±60 µm"],
          ["Steps", "41 · 3.0 µm apart"],
        ],
      },
      {
        summary: "20x / 0.75 NA dry · 1 channel",
        detail: [
          ["Objective", "HC PL APO 20x / 0.75 NA dry"],
          ["Channel", "DAPI · 405 nm · 15 ms · gain 1.0"],
          ["Metric", "Brenner gradient"],
          ["Range", "±15 µm"],
          ["Steps", "31 · 1.0 µm apart"],
        ],
      },
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
 * What the sample is mounted in. The carrier decides where the stage may go
 * and how the survey is laid out, so it is settled before anything moves.
 */
export const CARRIERS = [
  { key: "slide", label: "Slide", detail: "76 × 26 mm · one region" },
  { key: "dish35", label: "35 mm dish", detail: "one circular region" },
  { key: "plate24", label: "24-well plate", detail: "6 × 4 · 15.6 mm wells" },
  { key: "plate96", label: "96-well plate", detail: "12 × 8 · 6.4 mm wells" },
];

export const carrier = (key) => CARRIERS.find((c) => c.key === key);

export const DEFAULT_CARRIER = "slide";

export const DEFAULT_SESSION = {
  microscope: "stellaris5",
  api: "cam",
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
