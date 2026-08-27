/**
 * What the page is entitled to expect of a backend, whichever one it has.
 *
 * There are two of them — `mock.js`, which answers the page's verbs directly,
 * and `live.js`, which speaks HTTP to the bridge and through it to a real
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
 * offline suite runs them against `mock.js` on every change, and
 * `BACKEND_BRIDGE=http://127.0.0.1:8600 npx vitest run` runs the same list
 * against a bridge, which is the only way the two are ever held to each other.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

/** Micrometres per axis, out of the reading either backend answers with. */
export const um = (reading) => ({
  x: reading.x.value,
  y: reading.y.value,
  z: reading.z.value,
});

/**
 * Somewhere on the stage that is not where it is now, and is well inside the
 * travel whatever the travel turns out to be. Worked out from a reading rather
 * than written down, because the two backends are two different instruments
 * and only one of them is pretend.
 */
const somewhereElse = (from) => ({
  x: from.x > 60_000 ? from.x - 20_000 : from.x + 20_000,
  y: from.y > 40_000 ? from.y - 15_000 : from.y + 15_000,
  z: from.z,
});

/**
 * Every promise, in the order they are worth reading.
 *
 * Each is `{ what, keep }`: a sentence and an async check handed the backend.
 * A check throws — through the caller's own `expect` — when the promise is
 * broken.
 */
export function promisesOfABackend(expect) {
  return [
    {
      what: "says where the stage is, in micrometres per axis",
      async keep(backend) {
        const at = await backend.get_xyz();
        for (const axis of ["x", "y", "z"]) {
          expect(typeof at[axis].value, `${axis} is a number`).toBe("number");
          expect(Number.isFinite(at[axis].value), `${axis} is finite`).toBe(true);
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
        const going = somewhereElse(um(await backend.get_xyz()));
        await backend.set_xyz(going);
        const now = um(await backend.get_xyz());
        expect(now.x, "x arrived").toBeCloseTo(going.x, 0);
        expect(now.y, "y arrived").toBeCloseTo(going.y, 0);
      },
    },
    {
      what: "answers a drive with where it ended up",
      async keep(backend) {
        const going = somewhereElse(um(await backend.get_xyz()));
        const answered = um(await backend.set_xyz(going));
        /* The answer and the reading afterwards agree, which is what lets the
           page move the mark on the answer instead of waiting for the watch. */
        expect(answered).toEqual(um(await backend.get_xyz()));
      },
    },
    {
      what: "leaves an axis alone when it is not asked about",
      async keep(backend) {
        const start = somewhereElse(um(await backend.get_xyz()));
        await backend.set_xyz(start);
        const now = um(await backend.set_xyz({ x: start.x - 5_000 }));
        expect(now.y, "y held").toBeCloseTo(start.y, 0);
        expect(now.z, "z held").toBeCloseTo(start.z, 0);
      },
    },
    {
      what: "offers a menu of what a capture may be told, and what is chosen",
      async keep(backend) {
        const menu = await backend.get_acquisition_options();
        const named = Object.entries(menu);
        expect(named.length, "the instrument offers something").toBeGreaterThan(0);
        for (const [name, spec] of named) {
          expect(spec, `${name} says what is chosen`).toHaveProperty("active");
          expect(spec, `${name} says what may be chosen`).toHaveProperty("options");
          /* Where the choices are a list, what is active has to be one of
             them — a menu whose current value is not on it cannot be shown as
             a chooser, and cannot be handed back to `acquire` either. */
          if (Array.isArray(spec.options)) {
            expect(spec.options, `${name}'s active is one of its options`)
              .toContain(spec.active);
          }
        }
      },
    },
    {
      what: "is set to the job it was told to be set to",
      async keep(backend) {
        /* Whatever the instrument calls its stored recipes. Every one has
           them, and which is chosen is the setting an operator reaches for
           before anything else. */
        const { job } = await backend.get_acquisition_options();
        const other = job.options.find((one) => one !== job.active);
        const { applied } = await backend.set_state({ job: other });
        expect(applied.job, "the driver says it took the job").toBe(other);
        /* And says so when asked again — an instrument that reports one job
           and captures with another is worse than one that refuses. */
        expect((await backend.get_acquisition_options()).job.active).toBe(other);
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
        const record = await backend.acquire({
          acquisition_type: "overview", position_label: label,
        });
        expect(record.images.length, "it names what it wrote").toBeGreaterThan(0);
        expect(record.images).toEqual(record.planes.map((p) => p.path));
        for (const plane of record.planes) {
          for (const axis of ["t", "z", "c"]) {
            expect(typeof plane[axis], `a plane says its ${axis}`).toBe("number");
          }
          /* The canonical name, flat: what the capture was, which capture it
             was, where on the sample, and which plane of it. */
          expect(plane.path).toContain(`overview_${record.acquisition_hash}_${label}_`);
          expect(plane.path).toMatch(/_T\d{6}_C\d{2}_Z\d{5}\.ome\.tiff$/);
        }
      },
    },
    {
      what: "measures a focus point and reports a height for it",
      async keep(backend) {
        const { points } = await backend.measureFocus(
          [{ x: 30_000, y: 25_000 }],
          { metric: "brenner", extent: [120_000, 80_000] },
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
        const asked = [
          { x: 10_000, y: 10_000 },
          { x: 50_000, y: 30_000 },
          { x: 90_000, y: 60_000 },
        ];
        const { points } = await backend.measureFocus(asked, {
          metric: "brenner", extent: [120_000, 80_000],
        });
        expect(points.map((p) => [p.x, p.y])).toEqual(asked.map((p) => [p.x, p.y]));
      },
    },
  ];
}
