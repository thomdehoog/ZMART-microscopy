/**
 * The kinds of setting a run records off the microscope, and what a reading
 * of each looks like.
 *
 * A recording is a readout: the operator sets the instrument up in its own
 * software, names what they have set up, and presses record. This file says
 * which kinds exist and what shape their readings take; `recordings.js` holds
 * the slots a run keeps them in.
 */

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
const acquisition = ({ objective, pixelUm, framePx, channels, zStack }) => {
  const frameUm = Math.round(framePx * pixelUm);
  /* The line an operator checks a configuration by: the objective as the
     instrument names it, and how much sample one frame covers. The name
     already carries the magnification and the aperture, so picking those back
     out of it and setting them in a row of their own was the same reading
     written twice — and it threw away the part that identifies the lens on the
     shelf.

     The frame, not the pixel size. A collapsed configuration is read to answer
     "how much ground does one press get me", and the pixel size answers it
     only after being multiplied by a format that is not on the line. The two
     numbers it is made of are both in the detail below, for anyone checking
     the arithmetic. */
  const summary = `${objective}, ${frameUm} × ${frameUm} µm`;
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
const softwareAutofocus = ({ objective, pixelUm, framePx, channel, metric, rangeUm, stepUm }) => {
  const frameUm = Math.round(framePx * pixelUm);
  /* How far it sweeps, how finely, and at what format — the three an operator
     checks a focus configuration by, because they are what decide whether it
     will find the tissue and what it costs to look. The objective led this line
     and is the one thing the setting does not choose: it comes with the job. */
  const planes = Math.round((2 * rangeUm) / stepUm) + 1;
  return {
    summary: `${2 * rangeUm} µm stack, ${stepUm} µm steps, ${framePx} × ${framePx}`,
    kind: "software", pixelUm, framePx, frameUm,
    detail: [
      ["Focus", "Software · sharpness of the image"],
      ["Objective", objective],
      ["Channel", channel],
      ["Frame", `${framePx} × ${framePx} px · ${frameUm} × ${frameUm} µm`],
      ["Metric", metric],
      ["Stack", `${2 * rangeUm} µm · ±${rangeUm} µm about the start`],
      ["Steps", `${planes} planes · ${stepUm} µm apart`],
    ],
  };
};

const hardwareAutofocus = ({ objective, pixelUm, framePx, source, offset, hold }) => {
  const frameUm = Math.round(framePx * pixelUm);
  return {
    /* No stack and no steps: it measures the glass rather than looking through
       it, so what is left of the three is the format it holds at. */
    summary: `Hardware, no stack, ${framePx} × ${framePx}`,
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
export const SETTING_TYPES = [
  {
    key: "acquisition",
    label: "Acquisition",
    readings: [
      /* First in the list because the first recording an operator takes is
         the overview, and the overview is imaged at 20x. */
      acquisition({
        objective: "HC PL APO 20x / 0.75 NA dry",
        pixelUm: 0.33, framePx: 2048,
        channels: ["DAPI · 405 nm · 50 ms · gain 1.0", "GFP · 488 nm · 120 ms · gain 1.2"],
        zStack: "off",
      }),
      acquisition({
        objective: "HC PL APO 63x / 1.40 NA oil",
        pixelUm: 0.10, framePx: 1024,
        channels: ["DAPI · 405 nm · 30 ms · gain 1.0", "GFP · 488 nm · 80 ms · gain 1.5"],
        zStack: "11 planes · 0.50 µm",
      }),
      acquisition({
        objective: "HC PL APO 10x / 0.40 NA dry",
        pixelUm: 0.65, framePx: 2048,
        channels: ["GFP · 488 nm · 60 ms · gain 1.0"],
        zStack: "off",
      }),
      acquisition({
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
        metric: "Gradient", rangeUm: 30, stepUm: 1,
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
        metric: "Entropy-based", rangeUm: 60, stepUm: 3,
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
