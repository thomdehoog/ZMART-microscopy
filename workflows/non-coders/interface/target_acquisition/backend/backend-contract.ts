/**
 * What the page is entitled to expect of a backend, whichever one it has.
 *
 * There are two of them — `pretend.ts`, which answers the page's verbs directly,
 * and `live.ts`, which speaks HTTP to the bridge and through it to a real
 * driver — and the page is supposed not to be able to tell them apart. It
 * could. Every fault worth a fix in the operator page this week was one of
 * them behaving unlike the other: a pretend stage that never moved, so the
 * mark on the canvas was never seen to be drawn in the wrong place; a height
 * the bridge did not report, so the plot's marks read a field only the pretend
 * one filled in; a focus map that came back a column of zeros.
 *
 * None of those were visible from either side alone. What catches them is one
 * list of promises, run twice.
 *
 * The promises are about *behaviour*, not shape. A stage that answers with the
 * right three keys and never moves passes a shape check and fails an operator,
 * so what is asserted here is what the page actually leans on: drive it and it
 * is there; ask twice and it says the same thing; name an axis and only that
 * axis moves.
 *
 * Written as data rather than as tests so both runners can use them: the
 * offline suite runs them against `pretend.ts` on every change, and
 * `BACKEND_BRIDGE=http://127.0.0.1:8600 npx vitest run` runs the same list
 * against a bridge, which is the only way the two are ever held to each other.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import type { ExpectStatic } from "vitest";
import type { Backend, CaptureRecord, Span, XyzReading } from "./verbs.ts";

/** One promise: a sentence, and the check that throws when it is broken. */
export interface BackendPromise {
  what: string;
  keep(backend: Backend): Promise<void>;
}

/** The stage's extent along x and y, in micrometres. */
interface Travel {
  x: Span;
  y: Span;
}

/** Micrometres per axis, out of the reading either backend answers with. */
const um = (reading: XyzReading) => ({
  x: reading.x.position,
  y: reading.y.position,
  z: reading.z.position,
});

/**
 * Somewhere on the stage that is not where it is now, and is well inside the
 * travel whatever the travel turns out to be. Worked out from a reading rather
 * than written down, because the two backends are two different instruments
 * and only one of them is pretend.
 */
const somewhereElse = (from: { x: number; y: number; z: number }, travel: Travel) => {
  const mid = (range: Span) => (range[0] + range[1]) / 2;
  const step = (range: Span) => (range[1] - range[0]) / 6;
  return {
    x: from.x > mid(travel.x) ? from.x - step(travel.x) : from.x + step(travel.x),
    y: from.y > mid(travel.y) ? from.y - step(travel.y) : from.y + step(travel.y),
    z: from.z,
  };
};

/** The instrument's own extent, `get_xyz`'s `canvas` per axis, for every
    coordinate a promise drives to: written numbers were the mock's stage,
    and out-of-travel drives on anything real. The canvas is wider than the
    travel by half a field at each end, and the driver refuses a move past
    the travel; every place a promise drives to is at least a tenth of the
    way in from either edge, which on any real stage is far more than half a
    field, so it is always inside the travel. */
const theTravelOf = async (backend: Backend): Promise<Travel> => {
  const at = await backend.get_xyz();
  if (!at.x.canvas || !at.y.canvas) throw new Error("get_xyz says nothing of where its pictures can show");
  return { x: at.x.canvas, y: at.y.canvas };
};

/** A place a given fraction of the way across the travel. */
const across = (travel: Travel, fx: number, fy: number) => ({
  x: travel.x[0] + fx * (travel.x[1] - travel.x[0]),
  y: travel.y[0] + fy * (travel.y[1] - travel.y[0]),
});

const spanOf = (travel: Travel): Span => [
  travel.x[1] - travel.x[0],
  travel.y[1] - travel.y[0],
];

/**
 * Every promise, in the order they are worth reading.
 *
 * Each is `{ what, keep }`: a sentence and an async check handed the backend.
 * A check throws — through the caller's own `expect` — when the promise is
 * broken.
 */
export function promisesOfABackend(expect: ExpectStatic): BackendPromise[] {
  return [...promisesOfTheController(expect), ...promisesOfTargetAcquisition(expect)];
}

/** The controller's own verbs: connecting, the stage, the settings, a capture. */
function promisesOfTheController(expect: ExpectStatic): BackendPromise[] {
  return [
    {
      what: "says where the stage is, in micrometres per axis",
      async keep(backend) {
        const at = await backend.get_xyz();
        for (const axis of ["x", "y", "z"] as const) {
          expect(typeof at[axis].position, `${axis} is a number`).toBe("number");
          expect(Number.isFinite(at[axis].position), `${axis} is finite`).toBe(true);
        }
      },
    },
    {
      what: "says the same thing when asked twice in a row",
      async keep(backend) {
        /* A stage nobody has driven does not wander. This is what makes a
           change in the reading mean something happened. */
        expect(um(await backend.get_xyz())).toEqual(um(await backend.get_xyz()));
      },
    },
    {
      what: "is standing where it was driven",
      async keep(backend) {
        const going = somewhereElse(um(await backend.get_xyz()), await theTravelOf(backend));
        await backend.set_xyz(going);
        const now = um(await backend.get_xyz());
        expect(now.x, "x arrived").toBeCloseTo(going.x, 0);
        expect(now.y, "y arrived").toBeCloseTo(going.y, 0);
      },
    },
    {
      what: "answers a drive with where it ended up",
      async keep(backend) {
        const going = somewhereElse(um(await backend.get_xyz()), await theTravelOf(backend));
        const answered = um(await backend.set_xyz(going));
        /* The answer and the reading afterwards agree, which is what lets the
           page move the mark on the answer instead of waiting for the watch. */
        expect(answered).toEqual(um(await backend.get_xyz()));
      },
    },
    {
      what: "leaves an axis alone when it is not asked about",
      async keep(backend) {
        const start = somewhereElse(um(await backend.get_xyz()), await theTravelOf(backend));
        await backend.set_xyz(start);
        const now = um(await backend.set_xyz({ x: start.x - 5_000 }));
        expect(now.y, "y held").toBeCloseTo(start.y, 0);
        expect(now.z, "z held").toBeCloseTo(start.z, 0);
      },
    },
    {
      what: "offers a menu of how a capture is triggered, its default, and what is chosen",
      async keep(backend) {
        const menu = await backend.get_acquisition_settings();
        const named = Object.entries(menu);
        expect(named.length, "the instrument offers something").toBeGreaterThan(0);
        for (const [name, offered] of named) {
          const spec = offered as { active?: unknown; default?: unknown; options?: unknown };
          expect(spec, `${name} says what is chosen`).toHaveProperty("active");
          expect(spec, `${name} says what the driver chose to start with`).toHaveProperty("default");
          expect(spec, `${name} says what may be chosen`).toHaveProperty("options");
          /* Where the choices are a list, the default and what is active have
             to be on it — a menu whose current value is not on it cannot be
             shown as a chooser, and cannot be handed back to `acquire` either. */
          if (Array.isArray(spec.options)) {
            expect(spec.options, `${name}'s default is one of its options`).toContain(spec.default);
            expect(spec.options, `${name}'s active is one of its options`).toContain(spec.active);
          }
        }
      },
    },
    {
      what: "is set to the job it was told to be set to",
      async keep(backend) {
        /* Whatever the instrument calls its stored acquisitions. Which one
           is selected is part of the state, set with `set_state`; the driver
           answers with what it applied, read back from the instrument. */
        const { applied } = await backend.set_state({ job: "Target" });
        expect(applied.job, "the driver says it took the job").toBe("Target");
        await backend.set_state({ job: "Overview" });
      },
    },
    {
      what: "refuses a job it does not have",
      async keep(backend) {
        /* Refused, not accepted quietly: a capture taken with a job the
           instrument has never heard of would not run. */
        await expect(backend.set_state({ job: "no such job" })).rejects.toThrow();
      },
    },
    {
      what: "says what a capture wrote, and where",
      async keep(backend) {
        /* The record is the half nothing else can reconstruct: where a run
           will land is knowable in advance, what one capture produced is not.
           One acquisition is one file per plane, and the driver names them. */
        const label = "K00_M000001_G000000_P000042_V00";
        const answer = await backend.acquire({
          acquisition_type: "overview", position_label: label,
        });
        /* The controller's own answer, as a Python script receives it. */
        expect(Object.keys(answer).sort(), "the controller's two parts").toEqual(["output", "success"]);
        expect(answer.success).toBe(true);
        /* Succeeded, as just held: the output is the record. */
        const record = answer.output as CaptureRecord;
        expect(record.position_label).toBe(label);
        /* `files` is the name the ZMART Controller's contract fixes for every
           file a capture saved; each plane's file is one of them. How a
           driver names its files is its own business, so no name is read. */
        expect(record.files.length, "it names what it wrote").toBeGreaterThan(0);
        expect(record.files).toEqual(expect.arrayContaining(record.planes.map((p) => p.path)));
        expect(record.images, "the old name is gone").toBeUndefined();
        for (const plane of record.planes) {
          for (const key of ["t", "z", "c"] as const) {
            expect(Number.isInteger(plane[key]) && plane[key] >= 0, `a plane counts its ${key} from 0`).toBe(true);
          }
          for (const key of ["x_um", "y_um", "z_um"] as const) {
            const value = plane[key];
            expect(value === null || Number.isFinite(value), `${key} is micrometres or unknown`).toBe(true);
          }
        }
      },
    },
    {
      what: "says where its pictures can show, and what the session stands on",
      async keep(backend) {
        const checks: string[] = [];
        await backend.connect(
          { instrument: (await backend.instruments()).instruments[0].name },
          { onChecks: (keys) => checks.push(...keys) },
        );
        /* The page lays the stage out from `get_xyz`'s canvas and lists the
           checks under Connect. The mock always reported both; the Leica once
           reported neither, so a real connect drew a stage of no size with
           nothing to say. Each axis says exactly what the controller says of
           it: its position, its unit, the motor it moved by, every motor's
           reading and its canvas; the travel stays inside the driver. */
        const at = await backend.get_xyz();
        for (const axis of ["x", "y", "z"] as const) {
          expect(Object.keys(at[axis]).sort(), `${axis} reads position, unit, used_actuator, actuator_readings and canvas`)
            .toEqual(["actuator_readings", "canvas", "position", "unit", "used_actuator"]);
          expect(Object.keys(at[axis].actuator_readings), `${axis}'s used actuator is one of its motors`)
            .toContain(at[axis].used_actuator);
          const { canvas } = at[axis];
          expect(Array.isArray(canvas) && canvas.length === 2, `${axis} has a canvas`).toBe(true);
          const [low, high] = canvas as Span;
          expect(low, `${axis}'s canvas runs low to high`).toBeLessThanOrEqual(high);
        }
        for (const axis of ["x", "y"] as const) {
          const [low, high] = at[axis].canvas as Span;
          expect(high, `${axis}'s canvas spans something`).toBeGreaterThan(low);
        }
        expect(checks.length, "the checks are named as they are asked").toBeGreaterThan(0);
        /* Left open: the promises after this one stand on the session the
           live suite opened, and closing it here took it from all of them. */
      },
    },
    {
      what: "captures where it stands, and every plane says where it was taken",
      async keep(backend) {
        /* The whole display path leans on these three fields, and no promise
           held them: the record is the only thing that knows where on the
           sample a file came from. */
        const travel = await theTravelOf(backend);
        const going = across(travel, 0.5, 0.5);
        await backend.set_xyz({ ...going, z: um(await backend.get_xyz()).z });
        const { output } = await backend.acquire({
          acquisition_type: "overview", position_label: "contract",
        });
        const record = output as CaptureRecord;
        expect(record.planes.length, "a capture has planes").toBeGreaterThan(0);
        for (const plane of record.planes) {
          for (const key of ["t", "c", "z"] as const) {
            expect(typeof plane[key], `${key} is a number`).toBe("number");
          }
          expect(typeof plane.path, "a plane names its file").toBe("string");
          expect(plane.x_um, "x_um is where the stage stood").toBeCloseTo(going.x, 0);
          expect(plane.y_um, "y_um is where the stage stood").toBeCloseTo(going.y, 0);
        }
      },
    },
    {
      what: "says where a scan's pictures can be fetched, or that it has none",
      async keep(backend) {
        const where = backend.viewOf("overview");
        /* Either an address the canvas can open, or `null`. What is not
           allowed is an address that will not answer: the page fetches an
           engine before it fetches a picture, and an engine is a large thing
           to load for a scan that was never taken. */
        if (where !== null) {
          expect(typeof where, "an address is a string").toBe("string");
          expect(where.endsWith("/overview"), "and names the scan asked about").toBe(true);
        }
      },
    },
  ];
}

/** This workflow's own verbs: the focus map, the scans, the targets. */
function promisesOfTargetAcquisition(expect: ExpectStatic): BackendPromise[] {
  return [
    {
      what: "measures a focus point and reports a height for it",
      async keep(backend) {
        const travel = await theTravelOf(backend);
        const { points } = await backend.measureFocus(
          [across(travel, 0.25, 0.3)],
          { metric: "brenner", extent: spanOf(travel) },
        );
        expect(points.length, "one point asked for, one back").toBe(1);
        const [point] = points;
        /* A height, or a plain admission that there is none. What is not
           allowed is a made-up number: the page fits a surface through these,
           so one invented zero drags the whole map somewhere nobody looked. */
        if (point.z === null) {
          expect(point.lost, "a point with no height says so").toBe(true);
        } else {
          expect(Number.isFinite(point.z), "the height is a number").toBe(true);
          expect(point.zAuto, "and the instrument's own answer is kept").toBe(point.z);
        }
      },
    },
    {
      what: "keeps every point it was asked about, in the order asked",
      async keep(backend) {
        const travel = await theTravelOf(backend);
        const asked = [
          across(travel, 0.1, 0.15),
          across(travel, 0.4, 0.4),
          across(travel, 0.75, 0.75),
        ];
        const { points } = await backend.measureFocus(asked, {
          metric: "brenner", extent: spanOf(travel),
        });
        expect(points.map((p) => [p.x, p.y])).toEqual(asked.map((p) => [p.x, p.y]));
      },
    },
    {
      what: "asks where each search begins only once the point before it has landed",
      async keep(backend) {
        /* The page starts each point's stack at the height just found at the
           point before, so it has to be asked after that point is reported,
           never all at once up front. */
        const travel = await theTravelOf(backend);
        const asked = [across(travel, 0.2, 0.2), across(travel, 0.3, 0.3), across(travel, 0.4, 0.4)];
        const happened: string[] = [];
        await backend.measureFocus(asked, {
          metric: "brenner", extent: spanOf(travel),
          beginAt: (index) => { happened.push(`begin ${index}`); return undefined; },
          onPoint: (_, index) => happened.push(`landed ${index}`),
        });
        expect(happened).toEqual([
          "begin 0", "landed 0", "begin 1", "landed 1", "begin 2", "landed 2",
        ]);
      },
    },
    {
      what: "says where it stood as a scan goes",
      async keep(backend) {
        /* The mark on the canvas follows these answers. The watch's own poll
           is seconds behind a stage that moves on every field, so a scan the
           operator is watching had a mark that trailed the run -- the
           positions are in every progress answer already, and saying them is
           the backend's job because only its records know where it stood. */
        const travel = await theTravelOf(backend);
        const positions = [across(travel, 0.4, 0.4), across(travel, 0.6, 0.6)];
        const stood: { x: number; y: number; z: number | null }[] = [];
        await backend.scanOverview({
          positions, ms: 200,
          onProgress: (done, of, at) => { if (at) stood.push(at); },
        });
        expect(stood.length, "progress says where it stood").toBeGreaterThan(0);
        const last = stood[stood.length - 1];
        expect(last.x, "x is the last field's").toBeCloseTo(positions[1].x, 0);
        expect(last.y, "y is the last field's").toBeCloseTo(positions[1].y, 0);
      },
    },
  ];
}
