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
 * The optical configurations a run can draw on. A run needs two: the one it
 * surveys the sample with, and the one it images the chosen targets with.
 *
 * They must not be the same. Imaging targets at overview quality is the
 * mistake the pairing exists to prevent, so it is refused rather than warned
 * about — the same rule the current webapp enforces on its two job captures.
 */
export const OPTICAL_CONFIGS = [
  { key: "ov_5x", label: "Overview 5x", detail: "1.30 µm/px · 2 ch · widefield" },
  { key: "ov_10x", label: "Survey 10x", detail: "0.65 µm/px · 1 ch · widefield" },
  { key: "tg_63x", label: "Target 63x", detail: "0.10 µm/px · 2 ch · confocal" },
  { key: "tg_100x", label: "Target 100x oil", detail: "0.06 µm/px · 2 ch · confocal" },
];

export const opticalConfig = (key) => OPTICAL_CONFIGS.find((o) => o.key === key);

export const DEFAULT_OPTICS = { overview: "ov_5x", target: "tg_63x" };

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
  password: "",
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
