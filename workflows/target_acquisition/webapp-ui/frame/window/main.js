import "./style.css";
import { sideGroup } from "./panels.js";
import { blockedBecause, isReachable, panelsFor } from "../rules/steps.js";
import { theDrawingAbove, whoIsAt } from "../../workflows/target_acquisition/shared/canvas/layers-above.js";
import { assembleWorkflows } from "../rules/finding-workflows.js";
import {
  MICROSCOPES, DEFAULT_SESSION, apisFor, defaultApiFor,
  describeSession, STAGE_LIMITS_MM, isFailed,
} from "../../workflows/target_acquisition/microscope/microscopes.js";
/* The seam. Connecting, reading a preset off the instrument, measuring the
   focus map and driving the overview scan all go through the backend and are
   awaited; this window never knows whether a real stage moved. Which side of
   the seam answers is the chosen workflow's declaration: the prototype
   rehearses everything in the browser, and the mock and real workflows speak
   HTTP to the bridge — through it to the zmart controller, and on to the
   driver each of them names. */
import { backend as pretendBackend } from "../../workflows/target_acquisition/microscope/mock.js";
import { backend as liveBackend } from "../../workflows/target_acquisition/microscope/live.js";
import { centres, DEFAULT_CARRIER, describeCarrier } from "../../workflows/target_acquisition/shared/carriers.js";
/* Where focus points go inside a field: equal shares of it, measured at the
   middle of each. The geometry lives with the rest of the plan's geometry. */
import { sharePoints } from "../../workflows/target_acquisition/shared/scanfields.js";
import {
  emptySlot, hasRecording, withRecording, withoutRecording, withActive,
  activeRecording, nextReadingIndex,
} from "../../workflows/target_acquisition/microscope/recordings.js";
import carrierWidget from "../../workflows/target_acquisition/steps/2_define_carrier/widget.js";
import scanfieldsWidget, { presetInk } from "../../workflows/target_acquisition/steps/3_define_scan_area/widget.js";
/* The rehearsal's own maths — the deterministic random stream, the autofocus
   sweep with its two metrics and its specks of debris, and the focus-surface
   fitting — is imported rather than written here, so the unit tests and the
   page read the same arithmetic. These files used to exist twice, once here
   and once beside the mock, and the two copies could disagree in silence. */
import { makeRng } from "../../workflows/target_acquisition/microscope/pretend-sample/rng.js";
import { METRICS, METRIC_KEYS, scoreAt } from "../../workflows/target_acquisition/microscope/pretend-sample/sweep.js";
import {
  affineSurface, fitSurface, residualsUm, surfaceZ,
} from "../../workflows/target_acquisition/microscope/pretend-sample/surface.js";

/* The workflows this page offers: every folder in `workflows/` with a
   `flow.js` inside it, found by the build tool's folder scan and assembled by
   the frame. The unit tests read the same folders, so a workflow the tests can
   see is a workflow the operator can choose. The list used to be written out
   by hand — twice, at one point — and the copies drifted apart in silence,
   which is why it is now read off the disk instead. */
const { WORKFLOWS, DEFAULT_WORKFLOW } = assembleWorkflows(
  import.meta.glob("../../workflows/*/flow.js", { eager: true }),
);

/* The page speaks to the controller through the bridge; which driver the
   controller runs — the mock or the Leica — is chosen on the Connect step.
   The in-browser rehearsal (timers and a synthetic sample) is reachable only
   by `?backend=pretend`, for this page's own browser tests, until they run
   through the bridge too and it goes. */
const backendFor = () =>
  (new URLSearchParams(location.search).get("backend") === "pretend" ? pretendBackend : liveBackend);
let backend = null;

(() => {
  "use strict";

  /* ============================================================
     the synthetic sample
     ============================================================ */
  /* Deterministic, so the mock looks the same every load and can be argued
     about. Carrier micrometres throughout — the same frame the scan fields and
     the carrier's areas are in.

     Two things, and the split is the point. Tissue belongs to the plate: soft
     patches spread over the carrier, there whether or not anybody looks. Cells
     belong to the plan: the run only knows about what it imaged, so they are
     generated inside the tiles the scan fields ask for. Look somewhere else
     and a different sample comes back, which is the honest behaviour — before
     this the sample was a 7 by 5 block in the corner and the plan could not
     move it. */
  const TARGET_CELLS = 1250;
  const AREA_LO = 60, AREA_HI = 400;

  let sample = { tissue: [], cells: [], bounds: null };

  function tissueFor(carrier) {
    const rnd = makeRng(20260728);
    const [w, h] = carrierWidget.extentUm(carrier);
    return Array.from({ length: 7 }, () => ({
      x: (0.08 + 0.84 * rnd()) * w,
      y: (0.08 + 0.84 * rnd()) * h,
      r: (0.10 + 0.16 * rnd()) * Math.min(w, h),
    }));
  }

  function density(x, y) {
    let d = 0;
    for (const b of sample.tissue) {
      const dx = x - b.x, dy = y - b.y;
      d += Math.exp(-(dx * dx + dy * dy) / (2 * b.r * b.r));
    }
    return Math.min(1, d);
  }

  /* Rebuilt whenever the plan or the plate changes, because either changes
     what there is to find. A cell remembers which tile it was imaged in, so
     tuning detection on one tile is a question the sample can answer. */
  function rebuildSample() {
    state.plan = scanfieldsWidget.plan(state.fields, activePreset(), state.carrier);
    /* Left where a test can reach it, the way the live picture is. The plan is
       what this half of the run produces — where the stage goes and what each
       frame covers — and a suite that could only read the sentence beside it
       was asking how many positions there are, never where. */
    window.__plan = state.plan;
    sample = { tissue: tissueFor(state.carrier), cells: [], bounds: null };
    if (!state.plan.length) return;

    const rnd = makeRng(90210);
    const per = TARGET_CELLS / state.plan.length;
    const cells = [];
    let xMin = Infinity, yMin = Infinity, xMax = -Infinity, yMax = -Infinity;

    state.plan.forEach((t, tile) => {
      const half = t.frameUm / 2;
      xMin = Math.min(xMin, t.x - half); xMax = Math.max(xMax, t.x + half);
      yMin = Math.min(yMin, t.y - half); yMax = Math.max(yMax, t.y + half);
      const d = density(t.x, t.y);
      // a rich patch comes back crowded and a bare one nearly empty, rather
      // than every tile returning the same handful
      const n = Math.round(per * (0.15 + 1.85 * d));
      for (let i = 0; i < n; i++) {
        const area = 62 + 330 * Math.pow(rnd(), 1.7);
        cells.push({
          id: cells.length + 1, tile,
          x: t.x + (rnd() - 0.5) * t.frameUm,
          y: t.y + (rnd() - 0.5) * t.frameUm,
          area,
          intensity: Math.max(0.02, Math.min(1, 0.18 + 0.62 * d + 0.22 * (rnd() - 0.5))),
          r: Math.sqrt(area / Math.PI),
        });
      }
    });
    sample.cells = cells;
    sample.bounds = { xMin, yMin, xMax, yMax };
  }

  const cellsInTile = (tile) => sample.cells.filter((c) => c.tile === tile);

  /* ============================================================
     run state
     ============================================================ */
  /* The focus strategy is its own little document: which approach, that
     approach's parameters, and whatever it has produced so far.

     Only "plane" can be reached at the moment — the bar that chose between the
     four went, and comes back carrying whichever of them turns out to be
     wanted. The rest are parked rather than deleted: the model is what the step
     is about, and the readiness rules, the drawing and the trace all still ask
     which strategy this is. One row of markup arms them again. */
  /* The focus maps a run holds, and which of them is being worked on.
     A map is a named thing the operator makes: where to measure, what was
     measured, and the surface fitted to it. Named on the way in, because a run
     may carry several — one per plate region, one measured before a long
     acquisition and reused after — and a list of unnamed ones is a list
     nobody can choose from. */
  function newFocus() {
    return {
      strategy: "plane",
      metric: "brenner",   // which sharpness score the sweep is scored with
      points: [],          // picked positions, plane strategy only
      perField: 1,         // how many Place lays in each scan field
      selected: 0,         // which point's trace is charted
      picked: new Set(),   // which are held, for moving or taking away together
      hovered: -1,         // which one the pointer has found, if any
      placing: false,      // whether the crosshair is armed for a press
      zFixed: -412,
      reuse: "run_0714_a",
      applied: false,
      surface: null,       // constant | plane | spline, chosen by geometry
      residual: null,
      worst: -1,
    };
  }

  // detection settings live next to the focus strategy: chosen, tried on one
  // tile, then applied to the rest
  function newDetect() {
    return {
      algo: "cellpose",
      diameter: 18,
      cellprob: 0,
      thresh: 0.35,
      minArea: 80,
      tile: 0,
      tested: false,
    };
  }

  const PREVIOUS_SURFACES = {
    run_0714_a: { label: "2026-07-14 · slide A", plane: { a: 96, b: 61, c: -412 }, residual: 1.8, ageDays: 14 },
    run_0709_c: { label: "2026-07-09 · slide C", plane: { a: 71, b: 88, c: -389 }, residual: 3.1, ageDays: 19 },
  };

  /* A recording-to-be: nothing until the instrument has been read, because a
     preset is a reading taken off this instrument today and a run that begins
     with one begins by telling the operator something untrue. Built fresh
     each time, because a bar is edited in place and a shared one would carry
     the last run's typing into the next.

     There is no presets step: each recording lives in the step that uses it —
     the overview preset with the scan fields, the focus preset with the
     focus strategy, the acquisition type with the targets. */
  /* Which workflow to open on — `?workflow=target_acquisition`.
   *
   * For pointing this page at a run and looking at it, which is what somebody
   * with an acquisition in their hand wants and what `serve_a_run.py` prints an
   * address for. Without it that address lands on the first step of the ordinary
   * run and the picture is two clicks away, every time.
   *
   * A name that is not a workflow is ignored rather than refused: the page is
   * still perfectly usable on its ordinary workflow, and an address that opens
   * something slightly unexpected is a smaller failure than one that opens
   * nothing. The first step is then shown as it always is — there is no separate
   * path here, and no `?step=`, because a workflow whose first step is not where
   * you want to start is a workflow that has its steps in the wrong order.
   */
  const WORKFLOW_ASKED_FOR = new URLSearchParams(location.search).get("workflow");

  const state = {
    session: { ...DEFAULT_SESSION },
    overviewPreset: emptySlot("acquisition"),
    focusPreset: emptySlot("autofocus"),
    /* Read from further along the instrument's list than the overview: what
       the targets are taken with is a different setting from what found them,
       and a mock that answered with the same one twice would let a plan that
       never switched objectives look right. */
    targetType: emptySlot("acquisition", 1),
    carrier: { ...DEFAULT_CARRIER },
    /* Points put on the carrier drawing, in the carrier's own coordinates, to
       be driven to on the microscope. Placed the way focus points are: the
       button arms, and the next press on the canvas puts one down. */
    anchors: [],
    anchoring: false,
    /* How the overview scan keeps every tile sharp: by driving to the surface
       the focus map fitted, or by focusing at each tile as it arrives. The map
       is faster — one drive, no stack — and only there once it has been
       measured, so the choice starts on the other one. */
    fields: [],
    plan: [],
    editor: null,
    checks: [],
    wf: WORKFLOWS[WORKFLOW_ASKED_FOR] ? WORKFLOW_ASKED_FOR : DEFAULT_WORKFLOW,
    activeIdx: 0,
    done: new Set(),
    /* Which steps have actually been run, as against settled by doing the
       thing they are about. Only a step that ran can be run *again*, and a
       button offering that on a step nobody has pressed is a button lying
       about what happened. */
    ran: new Set(),
    running: null,
    notes: {},
    tabs: ["canvas"],     // canvas plus whatever the active step asks for
    tab: null,
    tilesShown: 0,
    focus: newFocus(),
    /* A focus map apiece: the points measured under one focussing preset are
       not the points measured under another, and switching between them is
       switching between two maps rather than editing one. Kept by the
       recording's id, with `focusFor` saying whose map `focus` currently is. */
    focusMaps: {},
    focusFor: null,
    detect: newDetect(),
    detected: new Set(),
    cellsShown: false,
    gate: null,          // {aLo,aHi,iLo,iHi}
    gated: new Set(),
    acquired: [],
    verdicts: {},
    locked: false,
  };

  backend = backendFor();

  const steps = () => WORKFLOWS[state.wf].steps;
  const step = (i) => steps()[i];

  const el = (id) => document.getElementById(id);

  /* ============================================================
     left rail
     ============================================================ */
  const selectEl = el("wf-select");
  for (const [key, wf] of Object.entries(WORKFLOWS)) {
    const opt = document.createElement("option");
    opt.value = key; opt.textContent = wf.name;
    /* Each workflow's own sentence about itself, shown when the pointer rests on
       it. A name has to be short enough for the rail, which is not always long
       enough to say what a workflow is for — and it matters most for the one
       that is a demonstration rather than a run, because somebody choosing it by
       mistake should be able to find that out before they choose it. */
    opt.title = wf.blurb;
    selectEl.append(opt);
  }
  selectEl.value = state.wf;

  /* Choosing a workflow is choosing to begin it: the switch restarts the run.
     There is no Restart button — the session card's Disconnect ends a run,
     and picking a workflow starts one. */
  selectEl.addEventListener("change", () => {
    state.wf = selectEl.value;
    backend = backendFor();
    resetRun();
  });

  /* Closing the session takes the run with it: settings were read off this
     microscope, the origin is in its coordinates, and the tiles came from it.
     Keeping any of that against a session that has been closed would be
     keeping something that might now be a lie. The chosen microscope, API and
     password stay, since editing them is the reason to disconnect. */
  function resetRun() {
    Object.assign(state, {
      activeIdx: 0, done: new Set(), ran: new Set(), running: null, notes: {},
      overviewPreset: emptySlot("acquisition"),
      focusPreset: emptySlot("autofocus"),
      targetType: emptySlot("acquisition", 1),
      carrier: { ...DEFAULT_CARRIER }, anchors: [], anchoring: false,
      fields: [], plan: [], checks: [],
      tabs: ["canvas"], tab: "canvas", tilesShown: 0,
      focus: newFocus(), focusMaps: {}, focusFor: null,
      detect: newDetect(), detected: new Set(),
      cellsShown: false, gate: null, gated: new Set(), acquired: [], verdicts: {},
      locked: false,
    });
    view.fitted = false;
    focusPanelsFor(0);
    renderGateReadout();
    renderPointList();
    renderAll();
  }

  function renderRail() {
    const host = el("steps");
    host.textContent = "";

    steps().forEach((s, i) => {
      const done = state.done.has(s.id);
      const active = i === state.activeIdx;
      const running = state.running === s.id;
      const reachable = isReachable(steps(), state.done, i);

      const b = document.createElement("button");
      b.className = "step" + (active ? " active" : "") + (done ? " done" : "") + (reachable ? "" : " locked");
      b.type = "button";
      if (!reachable) b.disabled = true;

      const head = document.createElement("div");
      head.className = "step-head";
      head.innerHTML =
        `<span class="step-n">${s.n}</span><span class="step-name"></span>`;
      head.querySelector(".step-name").textContent = s.title;
      if (running) head.insertAdjacentHTML("beforeend", '<span class="spin"></span>');
      b.append(head);

      /* Number and title, nothing else: the rail is navigation, the green
         badge already says done, and what a step produced is on the canvas
         and in the action bar. A note under every finished step read as a
         second, worse copy of the run. */

      b.addEventListener("click", () => {
        if (state.running || !reachable) return;
        state.activeIdx = i;
        if (step(i).id === "carrier") carrierSettled();
        if (step(i).id === "scanfields") scanfieldsSettled();
        focusPanelsFor(i);
        renderAll();
      });

      host.append(b);
    });
  }

  /* What this step still needs before it may run, and what to say when it is
     not met. The step itself holds the rule — see the step's own `step.js` file under `workflows/` — and
     this only asks it, which is why adding a workflow never means adding a
     condition here. The server would enforce the same list. */
  const readiness = (s) => blockedBecause(s, state);

  /* A step's action lives with the panel it operates, at the end of it — the
     way Connect's button has always sat inside its form. There is no bar above
     the panel any more: a button that runs the thing you are looking at should
     not be somewhere else, and a sentence explaining the step belongs with the
     step, which is the rail.

     `ownButton` now means "this panel builds its own", not "hide the bar". */
  function renderStepAction(shown) {
    for (const id of FOOT_IDS) el(id).textContent = "";
    for (const slot of document.querySelectorAll(".carrier-action, .scan-action, .focus-action")) {
      slot.textContent = "";
    }
    if (!shown) return;
    const i = state.activeIdx, s = step(i);
    /* A step with controls of its own puts its action at the end of them; the
       rest fall back to the bar under the panel they are looking at. */
    const host = document.querySelector(`.${s.id}-action`) ?? el(`foot-${shown}`);
    if (!host || s.ownButton || !s.btn) return;
    /* Some steps have nothing to run under the state they are in — a focus
       step is finished by the recording itself until a map is made to measure.
       A step says so for itself; the frame only asks. */
    if (s.acts && !s.acts(state)) return;

    const done = state.done.has(s.id);
    const running = state.running === s.id;
    const blocked = readiness(s);

    const run = document.createElement("button");
    /* marked as the step's own, because where it sits depends on the step */
    run.className = "run step-run"; run.type = "button";
    run.textContent = running ? "working…" : (state.ran.has(s.id) ? "Run again" : s.btn);
    run.disabled = !!state.running || !!blocked;
    run.addEventListener("click", () => runStep(i));
    host.append(run);

    /* The focus step says nothing beside its press. What it waits for is the
       box it stands in — points, laid by the row above it — and what it came to
       is the traces below; a greyed button between the two is already the whole
       sentence. */
    const hint = document.createElement("span");
    if (s.mode === "focus") { host.append(hint); return; }
    if (blocked) { hint.className = "action-hint"; hint.textContent = blocked; }
    else if (running) { hint.className = "action-hint"; hint.textContent = "working…"; }
    else if (s.mode === "select" && !done) { hint.className = "action-hint ok"; hint.textContent = `${state.gated.size} gated`; }
    /* What a step came to is said beside the button that produced it — except
       on the focus step, which has a box of its own for the answer: the traces,
       the heights and the residual, point by point. A sentence about focussing
       standing beside the press that measures the map was the same answer in
       worse words. What is missing is another matter: that is why the button
       cannot be pressed, and it belongs beside it. */
    else if (state.notes[s.id] && s.mode !== "focus") {
      hint.className = "action-hint ok";
      hint.textContent = state.notes[s.id];
    }
    host.append(hint);
  }

  /* Which panel is showing decides which foot fills, so the action follows the
     operator rather than the step declaring where to put it. */
  const renderActionBar = () => renderStepAction(shownPanel());

  /* ============================================================
     running a step — fake work with real state changes
     ============================================================ */
  function runStep(i) {
    const s = step(i);
    if (state.running) return;
    state.running = s.id;
    state.locked = true;
    renderAll();

    const started = performance.now();
    let raf = null;

    /** How far through the plan the scan is, worded once. */
    const scanNote = () => `${state.tilesShown} / ${state.plan.length} tiles`;

    /* Connecting is a handful of questions, not one action. Each answer lands
       as it arrives, so a session that fails does so at a named check rather
       than as a spinner that stops. */
    if (s.id === "connect") {
      /* Every question is on screen from the moment it is asked; only the
         answers arrive. The backend owns the asking — it opens the session
         and verifies it — and each answer lands here as it comes. */
      backend.connect({
        ...state.session,
        /* Which driver the bridge should connect is the microscope chosen on
           this card; the pretend backend ignores it. */
        instrument: MICROSCOPES[state.session.microscope]?.instrument,
      }, {
        /* The questions, before any answer: one row per key the driver reports. */
        onChecks: (keys) => {
          if (state.running !== "connect") return;
          state.checks = keys.map((label) => ({ label, result: null }));
          renderSetup();
        },
        onCheck: (k, result) => {
          if (state.running !== "connect") return;
          state.checks[k].result = result;
          answerCheck(k);
        },
      }).then(async ({ info }) => {
        /* The session is open and every check has answered. The canvas is
           the instrument's from here — its travel from get_info — and the
           stage mark stands where get_xyz says the stage is. */
        takeTheCanvas(info?.canvas);
        takeThePosition(await backend.xyz());
        finish();
      }).catch((why) => {
        /* The instrument's side said no — the bridge is not there, the
           driver it needs is not, or a check failed. The sentence lands where
           the answers would have, marked as the failure it is, and the step
           stays undone: a connection that failed is not a session. */
        state.failed = s.id;
        state.running = null;
        if (!state.checks.some((c) => c.result !== null && isFailed(c.result))) {
          state.checks = [...state.checks.filter((c) => c.result !== null),
            { label: "Connection failed", result: `failed — ${why.message}` }];
        }
        renderSetup();
        renderAll();
      });
      return;
    }

    if (s.mode === "scan") {
      state.tilesShown = 0;
      backend.scanOverview({
        positions: state.plan,
        ms: s.ms,
        onProgress: (done) => {
          if (state.running !== s.id) return;
          state.tilesShown = done;
          state.notes[s.id] = scanNote();
          /* Each position the scan reports is a reason to read the run again,
             because the tile it just saved is new picture that nothing on disk
             announces — the images were declared at their full size before any
             of them existed, so their description is the same before and after
             a tile lands. The picture decides how often to actually look; see
             `steps/5_scan_the_overview/overview.js`, which explains why. */
          liveOverview.tileMayHaveLanded();
          drawStage(); renderAll();
        },
      });
    }

    /* Finishing a step: the connect step finishes when its backend resolves,
       every other step when its rehearsal's time is up. A declaration, so the
       connect arm above — which returns early — can reach it. */
    async function finish() {
      /* A step that failed while running was already put down; finishing it
         anyway would mark a failed connection as a session. */
      if (state.failed === s.id) { state.failed = null; return; }
      state.running = null;
      state.done.add(s.id);
      state.ran.add(s.id);
      if (s.note) state.notes[s.id] = s.note;

      if (s.mode === "focus") {
        const f = state.focus;
        if (f.strategy === "plane") { await remeasure(); f.selected = 0; }
        f.applied = true;
        state.notes[s.id] =
          f.strategy === "plane" ? `${f.surface.model} from ${f.points.length} points · rms ${f.residual.toFixed(1)} µm`
          : f.strategy === "fixed" ? `fixed z ${f.zFixed} µm`
          : f.strategy === "auto" ? `focused at every position · ${METRICS[f.metric].label}`
          : `reusing ${PREVIOUS_SURFACES[f.reuse].label}`;
        renderPointList(); drawTrace();
      }
      /* Say the finished count, not whatever the last animation frame got to
         before it was cancelled. The tiles and the sentence about them come
         from one place, or a run that scanned everything reports one short. */
      if (s.mode === "scan") {
        state.tilesShown = state.plan.length;
        state.notes[s.id] = scanNote();
      }
      if (s.mode === "detect") {
        // the settings proven on one tile, now applied to every tile
        state.detected = new Set(sample.cells.filter(detects).map((c) => c.id));
        state.cellsShown = true;
        state.notes[s.id] = `${state.detected.size} targets · ${ALGOS[state.detect.algo].label}`;
      }
      if (s.mode === "select") { state.notes[s.id] = `${state.gated.size} targets selected`; }
      if (s.mode === "targets") {
        const picked = [...state.gated].slice(0, 12);
        state.acquired = picked;
        state.notes[s.id] = `${picked.length} pairs acquired`;
        buildGallery();
      }

      /* Finishing a run never moves the operator. The gallery is still being
         curated, the trace still being read, and a step that quietly hands
         the page to the next one takes that away. Advancing is a click. */
      focusPanelsFor(state.activeIdx);
      renderAll();
    }
    setTimeout(finish, s.ms);
  }

  /* ============================================================
     tabs — they accumulate as steps declare panels
     ============================================================ */
  /* Each setup step brings its own panel rather than sharing one called Setup.
     They are three different things — a session, a list of presets, a carrier —
     and a tab beside the canvas should say which of them it opens. They draw
     into the same element because only one is ever shown. */
  const FOOT_IDS = ["foot-canvas"];

  /* Every panel a step may ask for, by the name a step uses for it. `whenShown`
     is how a panel that has to build something of its own — a picture drawn by a
     graphics engine, rather than shapes on one of the page's own canvases —
     learns that it is on screen. It is called every time the panel comes up, and
     a panel that need do nothing simply has none. */
  const PANEL_META = {
    canvas: { label: "Canvas", panel: "panel-canvas" },
  };

  /* Which panels a step gets is `panelsFor` in `frame/rules/steps.js`, and the reason
     it lives there rather than here is that it is a rule about steps rather than
     about this page. What it comes to for the workflows on offer:

     The canvas is the microscope's own limits drawn to scale, so it is there
     from the carrier step onward — the step that first asks for it. Nothing
     about the frame depends on the carrier chosen inside it; the carrier only
     says where within those limits the sample sits. Setting it up fixes the
     run's zero as well, which is why no step asks for an origin any more. That
     happens behind the scenes and is deliberately not drawn: it is a
     consequence of having a frame, not a thing to confirm.

     From there the canvas is the window into the run, filling with data rather
     than appearing once data exists. The tab set is rebuilt on every render
     rather than growing forever. It belongs to the steps that happen inside it,
     and to no others — the same rule every other panel follows. The session and
     the instrument are not on the stage, so walking back to those steps leaves
     the canvas behind rather than parking a tab there for something the step
     has nothing to do with. Which makes this a question about the step being
     looked at, not about how far the run has got. */
  function focusPanelsFor(i) {
    state.tabs = panelsFor(steps(), i);
    // a step that brings a panel of its own opens on it; otherwise the base
    state.tab = state.tabs.length > 1 ? state.tabs[1] : state.tabs[0];
  }

  /* ============================================================
     the setup panel — the run's configuration, before it has data
     ============================================================ */
  /* Connecting is a card that reads downward — the form, the checks, what they
     came to, and the button that acts on all of it. Its button is its own
     rather than the frame's, because it is disabled until there is a password
     and it changes what it does once a session is open. */
  function renderSessionCard(host) {
    const connected = state.done.has("connect");
    let connectBtn = null;
    let connectHint = null;
    const connecting = state.running === "connect";
    /* The first step is headed the way every other step is: the name above the
       box, the box holding the work. What the session was opened with is
       already in the fields and in the rail beside them, so a third copy in the
       corner was the panel talking about itself. */
    const { group, body: card } = sideGroup("Connect to the microscope");
    card.classList.add("session-card");
    if (connected) card.classList.add("done");

    {
      const locked = connected || connecting;
      const form = document.createElement("div");
      form.className = "session-form";

      const scope = document.createElement("label");
      scope.className = "field";
      scope.innerHTML = "<span>Microscope</span><select></select>";
      const scopeSel = scope.querySelector("select");
      for (const [key, m] of Object.entries(MICROSCOPES)) {
        const o = document.createElement("option");
        o.value = key;
        o.textContent = m.detail ? `${m.label} · ${m.detail}` : m.label;
        scopeSel.append(o);
      }
      scopeSel.value = state.session.microscope;
      scopeSel.disabled = locked;
      scopeSel.addEventListener("change", () => {
        state.session.microscope = scopeSel.value;
        state.session.api = defaultApiFor(scopeSel.value);
        renderSetup(); renderActionBar();
      });

      const api = document.createElement("label");
      api.className = "field";
      api.innerHTML = "<span>API</span><select></select>";
      const apiSel = api.querySelector("select");
      for (const [key, a] of apisFor(state.session.microscope)) {
        const o = document.createElement("option");
        o.value = key;
        o.textContent = `${a.label} · ${a.detail}`;
        apiSel.append(o);
      }
      apiSel.value = state.session.api;
      apiSel.disabled = locked;
      apiSel.addEventListener("change", () => {
        state.session.api = apiSel.value;
        renderSetup(); renderActionBar();
      });

      const pw = document.createElement("label");
      pw.className = "field";
      pw.innerHTML = '<span>Password</span><input type="password" autocomplete="current-password">';
      const pwInput = pw.querySelector("input");
      pwInput.value = state.session.password;
      pwInput.disabled = locked;
      /* Typing must not rebuild the card: re-rendering destroys the very
         input being typed into, which drops focus after every keystroke.
         Only what depends on the password is touched. */
      pwInput.addEventListener("input", () => {
        state.session.password = pwInput.value;
        const ready = !!pwInput.value;
        if (connectBtn) connectBtn.disabled = connecting || !ready;
        if (connectHint) connectHint.hidden = ready;
      });

      form.append(scope, api, pw);
      card.append(form);
    }

    /* What the session was opened with is one thing; what came back when it
       was opened is another, so the answers stand in a box of their own under
       it. Every check is listed the moment the session is opened and each one
       ticks as its answer comes back — the row is the question, the mark is the
       answer. An open session is not editable, so the fields above stay on show
       as the record of what it was opened with. */
    let checks = null;
    if (state.checks.length) {
      const made = sideGroup("Connection checks");
      checks = made.body;
      /* Beside the session's box, not inside it: two boxes standing in the
         channel, the way every other step's boxes stand. */
      host.append(made.group);
      const list = document.createElement("div");
      list.className = "check-list";
      for (const c of state.checks) {
        const answered = c.result !== null;
        const failed = answered && isFailed(c.result);
        const row = document.createElement("div");
        row.className = "check-row" + (answered ? "" : " pending") + (failed ? " failed" : "");
        row.innerHTML = '<span class="check-mark"></span><span class="check-name"></span>'
          + '<span class="check-value"></span>';
        row.querySelector(".check-mark").textContent = failed ? "✗" : "✓";
        row.querySelector(".check-name").textContent = c.label;
        row.querySelector(".check-value").textContent = answered ? c.result : "";
        list.append(row);
      }
      checks.append(list);
    }

    /* The button sits at the end of the card, after everything it acts on —
       the rule every other step already follows. Once the session is open the
       press has nothing left to do, so what stands in its place is not a button
       at all: a green lamp and the word for it, the way an instrument says it is
       on. The way back out is the button, beside it. */
    {
      const foot = document.createElement("div");
      foot.className = "session-foot";
      const row = document.createElement("div");
      row.className = "session-buttons";

      if (connected) {
        const held = document.createElement("div");
        held.className = "session-state";
        held.innerHTML = '<i class="lamp"></i>';
        held.append("Connected");

        const out = document.createElement("button");
        out.type = "button";
        out.className = "danger";
        out.textContent = "Disconnect";
        out.disabled = !!state.running;
        out.addEventListener("click", closeSession);
        row.append(held, out);
      } else {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "run";
        btn.textContent = connecting ? "connecting…" : "Connect";
        btn.disabled = connecting || !state.session.password;
        btn.addEventListener("click", () => runStep(indexOfStep("connect")));
        connectBtn = btn;

        connectHint = document.createElement("div");
        connectHint.className = "session-hint";
        connectHint.textContent = "a password is needed to open the session";
        connectHint.hidden = !!state.session.password || connecting;
        row.append(btn);
      }

      foot.append(row);
      if (connectHint) foot.append(connectHint);
      card.append(foot);
    }

    host.prepend(group);
  }

  /* Only the answer lands. The row is already on screen, so filling one in
     touches that row rather than rebuilding the card under the operator —
     which would restart every other row's arrival along with it. */
  function answerCheck(k) {
    const row = document.querySelectorAll(".check-row")[k];
    if (!row) return;
    const result = state.checks[k].result;
    row.classList.remove("pending");
    row.classList.toggle("failed", isFailed(result));
    row.querySelector(".check-mark").textContent = isFailed(result) ? "✗" : "✓";
    row.querySelector(".check-value").textContent = result;
  }

  /* Closing the session takes the run with it, for the reason resetRun already
     gives: everything after this was read off this session. Reopening against
     a different microscope is the reason to close one, so the choice of
     microscope, API and password is what survives. */
  function closeSession() {
    if (state.running) return;
    resetRun();
  }

  const indexOfStep = (id) => steps().findIndex((s) => s.id === id);
  /* One slot per step, and the rows in it are the recordings.
   *
   * The bar at the top takes the next reading; what has been read stands under
   * it, a row apiece. Readings accumulate rather than replace, because the
   * optics get changed in the middle of a session and both settings stay worth
   * having — an overview taken dry at 5x and a detail taken at 63x in oil are
   * one run. One row is marked as the one the step is taken with, so switching
   * between them is a click rather than a second reading. */

  /* Which recordings are unfolded, by id. As many at once as the operator
     wants open: comparing two readings means reading both, and folding one
     away to look at the other is asking them to hold it in their head. Here
     rather than on the record itself — it is a fact about this screen, not
     about what the instrument reported, and the rows are redrawn from the
     run's state whenever anything around them moves. */
  const unfolded = new Set();

  /* The name being typed for the next reading, per slot, for the same reason.
     A name half typed has to survive a field being laid beside it. */
  const draftNames = {};

  /* The summary is the headline; the detail is what the controller actually
     read. Folded away by default, because a recording should stay a line —
     but one click from view, because "trust me" is not a good answer when
     the run depends on it.

     `active` is whether this is the one the step is taken with and `choose`
     makes it so; `ink` is the colour it is drawn in wherever the step draws
     it. */
  function renderRecordedBar(record, {
    rerender, dropped, choose, hostId, locked = false, active = false, ink = null,
    about = {},
  }) {
    const wrap = document.createDocumentFragment();

    const row = document.createElement("div");
    row.className = "rec-row";
    // no kind cell: the group above names it, so the name starts at the left
    row.innerHTML = '<button type="button" class="rec-fold"></button>'
      + '<button type="button" class="rec-pick">'
      + '<span class="rec-name"></span><span class="rec-state"></span></button>'
      + '<button type="button" class="rec-drop">✕</button>';
    row.querySelector(".rec-name").textContent = record.name;
    row.querySelector(".rec-state").textContent = record.summary;

    /* The row activates the recording, and activating is the whole of using
       it: everything the step produces is taken with the active one. A list of
       recordings beside a list of buttons for choosing between them was the
       same list written twice, and the copy is the one that goes stale. */
    const pick = row.querySelector(".rec-pick");
    pick.setAttribute("aria-pressed", String(active));
    pick.title = active
      ? (about.active ?? "active — this step is taken with it")
      : (about.idle ?? "activate: this step, and everything already planned, is taken with it");
    pick.disabled = !!state.running;
    pick.addEventListener("click", choose);
    if (ink) {
      const dot = document.createElement("span");
      dot.className = "rec-dot";
      dot.style.background = ink;
      /* Inside the name rather than beside it: the row is two columns, the
         name and what was read, and a dot given a column of its own pushed the
         summary onto a second line. */
      row.querySelector(".rec-name").prepend(dot);
    }

    const expanded = unfolded.has(record.id);
    const fold = row.querySelector(".rec-fold");
    fold.textContent = "▸";
    fold.title = expanded ? "fold away" : (about.fold ?? "show everything recorded");
    fold.setAttribute("aria-expanded", String(expanded));
    fold.classList.toggle("open", expanded);
    fold.addEventListener("click", () => {
      if (expanded) unfolded.delete(record.id); else unfolded.add(record.id);
      rerender();
    });

    /* Forgotten, whatever is taken with it: nothing names a recording except
       the step itself, so what is left to be active takes over and the plan
       follows it. */
    const drop = row.querySelector(".rec-drop");
    drop.title = about.drop ?? "forget this preset";
    drop.disabled = !!state.running || locked;
    drop.addEventListener("click", dropped);

    wrap.append(row);

    if (expanded && record.detail) {
      const detail = document.createElement("dl");
      detail.className = "rec-detail";
      for (const [label, value] of record.detail) {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value;
        detail.append(dt, dd);
      }
      wrap.append(detail);
    }
    return wrap;
  }

  /* The bar that takes the next reading: a name and a button. What it reads
     goes to `recorded` rather than into a record of its own — the slot below
     owns what has been recorded — and the name it is carrying goes to `onName`
     as it is typed, so a redraw finds it again. */
  function renderOpenBar({ type, nth, name, onName, recorded }) {
    const row = document.createElement("div");
    row.className = "rec-new";

    const box = document.createElement("input");
    box.type = "text";
    // one word: the box is narrow, and a placeholder that has to be truncated
    // to fit says less than the short one it was truncated from
    box.placeholder = "Name";
    box.value = name;
    box.setAttribute("aria-label", "name for this preset");

    const go = document.createElement("button");
    go.className = "run";
    go.type = "button";
    // the box says what is being done; the button says do it
    go.textContent = "Record";

    /* The name is not what makes a recording worth taking: what makes it worth
       taking is that the instrument is set the way it is set, now, and that is
       what the button reads. So the button is always live and an unnamed
       recording gets a name of its own — the operator can rename it, and a
       recording that happened beats one that was refused over a blank field.

       Typing must not rebuild the row, or the field loses focus every
       keystroke. */
    const check = () => {
      onName(box.value);
      go.disabled = !!state.running;
    };
    box.addEventListener("input", check);
    check();

    go.addEventListener("click", () => {
      go.disabled = true;
      go.textContent = "reading…";
      /* A readout off the instrument, never a procedure: the state as it is
         set now, through the backend. Nothing on the instrument moves. */
      backend.readSetting(type, { nth })
        .then((reading) => recorded(box.value, reading));
    });

    /* The name leads, the way it leads a recorded row: it is the thing being
       filled in. The kind is said once by the heading above, not by the bar. */
    row.append(box, go);
    return row;
  }

  /* A slot: a bold heading, the bar that takes the next reading, and a row for
     each reading taken. Each of the three lives in the step that uses it, so
     the state is tested where it matters.

     `ink` colours a record wherever the step draws it. `changed` is what the
     run does when the slot's contents change; `activated` when the contents
     stand and another record becomes the one in use — a lighter answer,
     because nothing has to be built again to say so. */
  function renderRecordingSlot(hostId, opts) {
    const {
      label, key, changed, activated = changed, locked = false, ink = null,
    } = opts;
    const host = el(hostId);
    if (!host) return;
    host.textContent = "";
    // two boxes in here, standing apart the way the boxes around them do
    host.className = "setting-slot";

    /* One box: the act and what the act has made. It is headed by the doing
       and names what it will make — recording is the same gesture everywhere,
       but what comes out of it is an acquisition preset here and a focussing
       preset there, and the operator is after the thing rather than the gesture.
       What has been recorded stands directly under the bar that took it; a box
       of its own said the readings were a second subject when they are the
       answer to this one. */
    const { group, body } = sideGroup(
      `Record ${label[0].toLowerCase()}${label.slice(1)}`,
    );

    const slot = state[key];
    const rerender = () => renderRecordingSlot(hostId, opts);

    /* The bar that takes a reading leads, and what it has taken stands under
       it. Both, always: the bar used to be replaced by what it recorded, which
       said the reading was a thing done once — and it is not. The optics get
       changed in the middle of a session, and when they do the operator wants
       to say so here rather than throwing the preset away to get the bar back.

       It leads rather than follows because it is the control and the rows
       below are the answers. A control that moves down the panel as answers
       accumulate is a control the hand has to go looking for. */
    const box = document.createElement("div");
    box.className = "setting-box open";
    box.append(renderOpenBar({
      type: slot.type,
      nth: nextReadingIndex(slot),
      name: draftNames[hostId] ?? "",
      onName: (v) => { draftNames[hostId] = v; },
      recorded: (name, reading) => {
        state[key] = withRecording(slot, { name, reading });
        draftNames[hostId] = "";
        rerender();
        changed();
      },
    }));
    body.append(box);

    host.append(group);
    if (!slot.records.length) return;

    /* The readings, straight under the bar that took them. They carried a word
       of their own for a while — the way the two ways of laying tilesets do —
       and it was a heading saying what the heading above it had just said. As
       long a list as it needs to be: the channel scrolls if the step outgrows
       it, and a slot that scrolled inside itself hid readings behind a bar of
       its own and made the one in use something to go hunting for. */
    const list = document.createElement("div");
    list.className = "rec-list";

    for (const record of slot.records) {
      const active = record.id === slot.active;
      const done = document.createElement("div");
      done.className = active ? "setting-box done active" : "setting-box done";
      done.append(renderRecordedBar(record, {
        rerender, locked, active, hostId,
        ink: ink ? ink(record.id) : null,
        choose: () => {
          state[key] = withActive(slot, record.id);
          rerender();
          activated();
        },
        dropped: () => {
          state[key] = withoutRecording(slot, record.id);
          unfolded.delete(record.id);
          rerender();
          changed();
        },
      }));
      list.append(done);
    }
    body.append(list);
  }

  /* The carrier is what the canvas is drawing, so its controls sit beside the
     drawing and stay there. Not a menu that appears for one step: the frame is
     a property of the run, readable whenever the canvas is, and only editable
     until it has been applied.

     Mounted once per lock state rather than on every render, because the widget
     keeps its own and rebuilding it would throw away the number being typed. */
  /* The carrier is settled by being configured, so there is nothing to press:
     it always holds a valid one, and the operator either accepts what is there
     or edits it. Standing on the step is the whole of it. Completing is not
     advancing — the rail still waits for a click to move on.

     It stays editable until something has been done inside the frame, at which
     point changing it would invalidate what was done. */
  function carrierSettled() {
    if (indexOfStep("carrier") < 0) return;
    state.done.add("carrier");
    state.notes.carrier = describeCarrier(state.carrier);
  }

  /**
   * Point `state.focus` at the map belonging to the active focussing preset.
   *
   * The one being left is kept first, so going back to it finds the points
   * where they were and the heights that were read for them. A preset nobody
   * has worked under yet starts with nothing on the map — its points are the
   * ones it has, which is none.
   */
  function focusFollowsPreset() {
    const id = activeRecording(state.focusPreset)?.id ?? null;
    if (id === state.focusFor) return;
    if (state.focusFor) state.focusMaps[state.focusFor] = state.focus;
    state.focusFor = id;
    state.focus = id ? (state.focusMaps[id] ?? newFocus()) : newFocus();
    // and maps whose preset has been forgotten go with it
    const kept = new Set(state.focusPreset.records.map((r) => r.id));
    for (const held of Object.keys(state.focusMaps)) {
      if (!kept.has(held)) delete state.focusMaps[held];
    }
  }

  /* The recording settles the step. A hardware autofocus is held by the stand
     and there is nothing further to do; a software one focuses at every
     position it is sent to, which is also a complete answer. Measuring a focus
     map is the optional extra on top — worth having, because a measured
     surface is faster than focusing everywhere, but nothing waits for it.

     Forgetting the last reading takes the map with it, the way forgetting the
     last acquisition preset takes the plan: points measured through optics
     nobody can see any more are not points. */
  function focusSettled() {
    const kind = activeRecording(state.focusPreset)?.kind;
    if (!kind) {
      state.focus = newFocus();
      state.done.delete("focus");
      delete state.notes.focus;
      renderPointList();
      drawTrace();
      return;
    }
    state.done.add("focus");
    if (state.focus.applied) return;
    state.notes.focus = kind === "hardware"
      ? "held by the stand"
      : "focused at every position";
  }

  /* The focus preset is forgettable until a step after it has run, which
     is the rule the acquisition preset follows. Locking it on the strategy
     being applied took the cross away while the operator was still standing on
     the step, with nothing yet depending on the reading. */
  const focusLocked = () => {
    const i = indexOfStep("focus");
    return !!state.running || steps().slice(i + 1).some((s) => state.done.has(s.id));
  };

  const carrierLocked = () => {
    const i = indexOfStep("carrier");
    return !!state.running || steps().slice(i + 1).some((s) => state.done.has(s.id));
  };

  /* The channel belongs to the step standing in it.

     Both steps that own one are about the canvas rather than beside it — the
     carrier is what the canvas is drawing, the scan fields are what is being
     drawn on it — so each docks its controls in the same column and the
     heading says which. One column, because two would take the picture's width
     to show controls for a step nobody is on. */
  /* Focus is not a widget module yet — its controls are markup that was built
     once and is moved into the channel, not rebuilt from a declaration. It
     stands in the same list because the frame only asks two things of an owner:
     what it is called, and that it can be mounted. */
  const focusWidget = {
    id: "focus",
    label: "Focus strategy",
    mount(host) {
      /* The focus preset is recorded here, where the sweeps that will be
         measured with it are chosen — in the same box the acquisition preset
         is recorded in on the scan-fields step, since it is the same kind of
         thing being done. */
      const box = document.createElement("div");
      box.className = "side-pad-around";
      const rec = document.createElement("div");
      rec.id = "focus-preset";
      box.append(rec);
      host.append(box);
      /* Either kind of focussing can be given a focus map: measure a few
         positions, fit a surface, and the run drives to a known height instead
         of finding one everywhere. A software autofocus finds that height by
         taking a short stack and scoring it; a hardware one is driven to each
         point and the height it settles at is read — so both have something to
         measure and something to fit.

         One map, and it belongs to the recording above it: a run focuses one
         way, so there is one surface to fit and nothing to name or choose
         between. The ways of choosing where to measure appear as soon as
         something has been recorded, and the map is the optional extra either
         way — both kinds are a complete answer on their own. */
      const showTheRest = () => {
        focusControls.hidden = !activeRecording(state.focusPreset);
        focusSettled();
        renderPointList();
        drawTrace();
      };
      renderRecordingSlot("focus-preset", {
        label: "Focussing preset", key: "focusPreset",
        locked: focusLocked(),
        changed: () => {
          focusFollowsPreset(); showTheRest(); renderRail(); renderActionBar(); drawStage();
        },
        activated: () => {
          focusFollowsPreset(); showTheRest(); renderRail(); renderActionBar(); drawStage();
        },
      });
      showTheRest();
      host.append(focusControls);
      renderPointList();
      drawTrace();
    },
  };

  /* The scan consults nothing: it takes the run's one recorded preset, and it
     keeps focus with the map the focus step generated — or at every position,
     when no map was measured. There is nothing here to choose, so the channel
     is a short summary the operator can check at a glance, and the press that
     starts the scan. */
  const scanWidget = {
    id: "scan",
    label: "Scan the overview",
    mount(host) {
      host.textContent = "";
      const pad = document.createElement("div");
      pad.className = "side-pad-around";
      host.append(pad);

      const { group, body } = sideGroup("Scan summary");
      const line = (text) => {
        const row = document.createElement("div");
        row.className = "side-note";
        row.textContent = text;
        body.append(row);
      };
      line(`${state.plan.length} positions to image`);
      const measured = state.focus.applied && state.focus.strategy === "plane";
      line(measured
        ? `focus follows the measured map · rms ${state.focus.residual.toFixed(1)} µm`
        : "focus found at every position — no map measured");
      pad.append(group);

      // and the press that starts it, at the end of what it acts on
      const action = document.createElement("div");
      action.className = "scan-action";
      pad.append(action);
      renderActionBar();
    },
  };

  /* Detection is the same shape as focus: the step happens on the canvas —
     the cells it finds land there — and its controls sit in the channel,
     where the settings are tried on one position before the sample runs. */
  const detectWidget = {
    id: "detect",
    label: "Discover Targets",
    mount(host) {
      detectControls.hidden = false;
      host.append(detectControls);
      renderDetectToolbar();
      drawTilePreview();
    },
  };

  /* And selection once more: the gated cells light up on the canvas, and the
     channel holds the scatter they are gated on. */
  const analysisWidget = {
    id: "select",
    label: "Refine Targets",
    mount(host) {
      analysisControls.hidden = false;
      host.append(analysisControls);
      sizeCanvas(scatterCv);
      drawScatter();
      renderGateReadout();
    },
  };

  /* The session card lives in the channel like everything else: it is the
     controls of the step being stood on, beside the canvas it configures the
     run for. It rebuilds on every render, the way its panel used to, so
     nothing in it goes stale. */
  const connectWidget = {
    id: "connect", label: "Connect", mount: () => renderSetup(),
  };

  /* The gallery too: the acquired targets ring on the canvas, and the channel
     holds the acquisition type being recorded, the pairs, and the verdicts
     being collected on them. */
  const galleryWidget = {
    id: "acquire",
    label: "Acquire Targets",
    mount(host) {
      galleryControls.hidden = false;
      host.append(galleryControls);
      renderRecordingSlot("target-type", {
        /* Just the thing, not the gesture: the heading already says "Record",
           so a label that says it too reads "Record record …" on screen. */
        label: "Acquisition type", key: "targetType",
        changed: () => renderActionBar(),
      });
      buildGallery();
    },
  };

  const SIDE_WIDGETS = {
    connect: connectWidget,
    carrier: carrierWidget, scanfields: scanfieldsWidget,
    focus: focusWidget, scan: scanWidget, detect: detectWidget, select: analysisWidget,
    acquire: galleryWidget,
  };

  const sideWidget = () => SIDE_WIDGETS[step(state.activeIdx).id] ?? null;

  /* The plan stops being editable when something has been imaged against it —
     not when a later step has merely been done.

     The focus map is the one in between, and it does not depend on the plan: a
     fitted surface is a statement about the plate, measured at points that stay
     where they were put whatever the scan fields do. So walking back past it
     and moving a field is safe, and needs no ceremony to make it safe.

     The overview is where that stops being true. Its tiles are pictures taken
     at those positions, and a field moved afterwards would leave images
     claiming a place they were not taken from — which nothing downstream could
     detect, because a tile does not know where it should have been. Everything
     after the scan depends on the scan, so anchoring here covers all of it. */
  const scanfieldsLocked = () => {
    const i = indexOfStep("scan");
    return !!state.running || (i >= 0 && steps().slice(i).some((s) => state.done.has(s.id)));
  };

  /* Held rather than looked up: emptying the channel takes these out of the
     document, and getElementById cannot find what is not in it. */
  const focusControls = el("focus-controls");
  const detectControls = el("detect-controls");
  const analysisControls = el("analysis-controls");
  const galleryControls = el("gallery-controls");

  function renderSide(show) {
    const host = el("canvas-side");
    const widget = show === "canvas" ? sideWidget() : null;
    host.hidden = !widget;
    // the divider is the channel's edge, so it is only there when the channel is
    el("side-divider").hidden = !widget;
    const locked = widget?.id === "carrier" ? carrierLocked() : scanfieldsLocked();
    const key = widget && `${widget.id}:${locked}`;
    // the setup cards rebuild on every render, the way their panel used to;
    // the working widgets keep their state and mount once per key
    if (state.sideMounted === key && !(widget && SETUP_CARDS[widget.id])) return;
    state.sideMounted = key;
    state.editor?.destroy?.();
    state.editor = null;
    host.textContent = "";
    if (!widget) return;

    // a widget with a mount owns parked markup that moves into the channel
    if (widget.mount) { widget.mount(host); return; }

    if (widget.id === "carrier") {
      /* The anchor points belong to the run, not to the panel: the canvas
         draws them and the press that places them is the canvas's. The panel
         is handed the few things it needs to show and change them. */
      let redrawAnchors = () => {};
      widget.render(host, {
        config: state.carrier,
        locked,
        anchors: {
          list: () => state.anchors,
          arming: () => state.anchoring,
          arm: () => { state.anchoring = !state.anchoring; redrawAnchors(); drawStage(); },
          forget: (i) => {
            state.anchors = state.anchors.filter((_, at) => at !== i);
            redrawAnchors(); drawStage();
          },
          /* Where the microscope is standing now, kept against this point on
             the carrier: the pair is the registration — this place on the
             drawing is that place on the stage. */
          snap: (i) => {
            const at = whereTheStageIs();
            state.anchors = state.anchors.map((a, n) =>
              (n === i ? { ...a, stage: { x: at.x, y: at.y, z: at.z } } : a));
            redrawAnchors(); drawStage();
          },
          onChange: (fn) => { redrawAnchors = fn; },
        },
        onChange: (next) => {
          state.carrier = next;
          // the note in the rail says what the carrier now is
          carrierSettled();
          // the tissue is spread over the plate, so a different plate is a
          // different sample even before the plan moves
          rebuildSample();
          view.fitted = false;
          drawStage();
          renderRail();
          renderActionBar();
        },
      });
      return;
    }

    /* The overview's preset is recorded here, where the fields that will be
       taken with it are laid, because a field takes its frame from it.

       Until it exists there is nothing to lay — but the ways of laying are on
       screen anyway, greyed. They used to be absent, and an empty step is a
       worse answer than a disabled one: the operator arrives, sees a single
       box, and has no way to tell whether this step is about recording a
       preset or whether the rest of it is still loading. Greyed, the step
       shows what it is going to be, and that the open bar at the top of it is
       what the rest is waiting on — which is a sentence the panel no longer
       has to carry, because the picture of it says the same thing. */
    const rec = document.createElement("div");
    rec.id = "sf-preset";
    host.append(rec);
    const presetSlot = {
      label: "Acquisition settings from microscope", key: "overviewPreset", locked,
      ink: (id) => recordedPresets().find((p) => p.id === id)?.ink ?? null,
      /* A recording taken or forgotten changes what there is to be taken with,
         so the run is asked again from the top. Activating another one changes
         what the plan covers without changing the plan: the editor is told,
         the tiles are worked out again, and every field stays where the
         operator put it. */
      changed: () => {
        /* The last recording forgotten takes the plan with it. A region or a
           grid position is a statement about what to image and with what, and
           with no preset left there is no with — keeping the outlines would
           leave the operator a picture of a plan the run could not run, and
           the next preset recorded would silently adopt shapes drawn for
           optics nobody can see any more. */
        if (!hasRecording(state.overviewPreset)) state.fields = [];
        state.sideMounted = null;
        scanfieldsSettled();
        renderAll();
      },
      activated: () => {
        state.editor?.setPreset(activePreset());
        scanfieldsSettled();
        drawStage();
        renderRail();
      },
    };
    renderRecordingSlot("sf-preset", presetSlot);

    state.editor = widget.render(host, {
      fields: state.fields,
      carrier: state.carrier,
      preset: activePreset(),
      presetSlot: el("sf-preset"),
      /* Locked by the run having moved past this step, and locked until the
         preset the plan would be taken with exists. */
      locked: locked || !hasRecording(state.overviewPreset),
      onChange: (next) => {
        state.fields = next;
        scanfieldsSettled();
        drawStage();
        renderRail();
      },
      redraw: drawStage,
    });
  }

  /* The channel's width is the operator's to set. The divider drags, the
     variable moves, and everything that reads --side-w — the channel and the
     name over it — follows. Written on the root, so the width survives
     walking between steps; the canvas is the bigger half by default and
     keeps whatever the channel does not take. Clamped so neither the picture
     nor the controls can be crushed. */
  {
    const divider = el("side-divider");
    const body = divider.parentElement;
    let resizing = false;
    divider.addEventListener("pointerdown", (e) => {
      resizing = true;
      divider.classList.add("dragging");
      divider.setPointerCapture(e.pointerId);
    });
    divider.addEventListener("pointermove", (e) => {
      if (!resizing) return;
      const box = body.getBoundingClientRect();
      const width = Math.max(240, Math.min(box.width - 360, Math.round(box.right - e.clientX)));
      document.documentElement.style.setProperty("--side-w", `${width}px`);
      /* The channel's own observers redraw what lives in it; the stage is
         resized here, since its panel — the thing observed — has not moved. */
      sizeCanvas(stageCv); drawStage();
    });
    const settle = (e) => {
      if (!resizing) return;
      resizing = false;
      divider.classList.remove("dragging");
      if (divider.hasPointerCapture?.(e.pointerId)) divider.releasePointerCapture(e.pointerId);
    };
    divider.addEventListener("pointerup", settle);
    divider.addEventListener("pointercancel", settle);
  }

  /* Every preset recorded beside the fields, in the order taken — which is
     the order their colours come in, so the row and the tiles it lays are the
     same fact seen twice. */
  const recordedPresets = () => state.overviewPreset.records.map((r, i) => ({
    id: r.id,
    kind: "acquisition",
    name: r.name,
    summary: r.summary,
    frameUm: r.frameUm,
    ink: presetInk(i),
  }));

  /* What the whole plan is taken with. One preset, not one per field:
     activating another one re-takes everything, which is the only reading of
     it that stays true when the objective in the light path has changed. */
  const activePreset = () =>
    recordedPresets().find((p) => p.id === state.overviewPreset.active) ?? null;

  /* Drawing fields is the work, the way recording and configuring are: the
     step is done once there is something to scan, and undone again if the last
     field is removed. */
  function scanfieldsSettled() {
    rebuildSample();
    if (indexOfStep("scanfields") < 0) return;
    const positions = state.plan.length;
    if (positions) {
      state.done.add("scanfields");
      state.notes.scanfields = `${positions} position${positions === 1 ? "" : "s"}`;
    } else {
      state.done.delete("scanfields");
      delete state.notes.scanfields;
    }
  }

  /* A card belongs to its step and shows while you are standing on it —
     click back on Connect and the session and its checks are there again;
     step away and the channel is about the step you moved to. */
  const SETUP_CARDS = {
    connect: renderSessionCard,
  };

  /* The setup cards render into the channel like every other step's controls:
     cleared and rebuilt on every call, which is how their panel behaved, so
     nothing in them goes stale. */
  function renderSetup() {
    const id = step(state.activeIdx).id;
    const card = SETUP_CARDS[id];
    if (!card) return;
    const host = el("canvas-side");
    host.textContent = "";
    const pad = document.createElement("div");
    pad.className = "side-pad";
    card(pad);
    host.append(pad);
  }

  /* Always drawn, even for one. It names what is loaded — the Canvas — and
     naming what you are looking at is worth a line whether or not there is a
     second one to switch to. */
  function renderTabs() {
    const host = el("tabs");
    host.textContent = "";

    for (const key of state.tabs) {
      const meta = PANEL_META[key];
      const b = document.createElement("button");
      b.className = "tab"; b.type = "button"; b.role = "tab";
      b.setAttribute("aria-selected", String(state.tab === key));
      b.append(document.createTextNode(meta.label));

      b.addEventListener("click", () => { state.tab = key; renderPanels(); renderTabs(); });
      host.append(b);
    }

    /* The channel beside the canvas is named where it sits, at the right end
       of the same row and over the column it heads. Not a tab: it is not an
       alternative to the canvas, it is the controls for what the canvas is
       showing — so it says whose controls those are rather than offering a
       switch. */
    const owner = shownPanel() === "canvas" ? sideWidget() : null;
    if (owner) {
      const side = document.createElement("span");
      side.className = "side-tab";
      /* The name is its own element: it carries the rule under it, so that
         rule is as wide as the word the way a tab's is, rather than as wide
         as the channel this stands over. */
      const label = document.createElement("span");
      label.textContent = owner.label;
      side.append(label);
      host.append(side);
    }
  }

  const shownPanel = () => (state.tabs.includes(state.tab) ? state.tab : state.tabs[0]);

  function renderPanels() {
    const show = shownPanel();
    if (!show) return;
    /* By element, not by key: the setup steps share one, so asking each key in
       turn would switch it on for its own and straight back off for the next. */
    const shown = PANEL_META[show].panel;
    for (const id of new Set(Object.values(PANEL_META).map((m) => m.panel))) {
      el(id).classList.toggle("on", id === shown);
    }
    renderSide(show);
    renderStepAction(show);
    // A panel that builds a picture of its own is told it is on screen; see
    // `PANEL_META`. Everything below this line is the page drawing on its own
    // canvases, which needs no such warning.
    PANEL_META[show].whenShown?.();
    // The acquired overview lies over the plan while the scan is what is being
    // looked at, so which of the two is on screen follows the step.
    liveOverview.showFor(step(state.activeIdx), show);
    if (show === "canvas") { sizeCanvas(stageCv); drawStage(); }
  }

  function renderAll() {
    /* The step being looked at decides the tab set on its own, so this is the
       one place that has to agree with it — recomputed rather than trusted,
       and the selection kept only while it still names a tab that is there. */
    state.tabs = panelsFor(steps(), state.activeIdx);
    if (!state.tabs.includes(state.tab)) state.tab = state.tabs[0];

    renderRail();
    renderActionBar();
    renderTabs();
    renderPanels();
  }

  /* ============================================================
     shared canvas plumbing
     ============================================================ */
  function sizeCanvas(cv) {
    const host = cv.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const w = host.clientWidth, h = host.clientHeight;
    if (!w || !h) return false;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cv.cssW = w; cv.cssH = h;
    return true;
  }

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /* ============================================================
     the overview being acquired — the real picture, when there is one
     ============================================================ */
  /* Everything else on this page is a rehearsal: a synthetic sample, a stage
     that moves on a timer. This one thing is not. Given the address of a run
     that a microscope is writing, the scan step draws that run — the same
     OME-Zarr images `zmart_storage` writes, read as they are being written — so
     the operator watches the overview appear tile by tile instead of watching a
     counter.

     It is asked for rather than assumed, with `?overview=<address of the run>`
     on the page's own address, for two reasons. A page opened without one has no
     run to watch and should not go looking for one; and the drawing engine is a
     large thing to load, so it is fetched only when there is something for it to
     draw. The demo run in `live_overview_demo.py` prints the address to use. */
  /* Which acquisitions to draw, from the bottom up. `?overview=` is the one that
     matters and is usually the only one; `?targets=` names a second acquisition
     to be drawn over it.

     Two of them is the shape a real run has. The writer keeps one image per
     acquisition type, so a low-power map of the whole carrier is one image and
     the high-power scan of the targets picked out of it is another. They cover
     the same ground, so drawing one over the other shows where in the sample
     each target came from — which is a question the operator asks constantly and
     cannot answer from two pictures side by side. */
  const ACQUISITIONS = (() => {
    const asked = new URLSearchParams(location.search);
    return [asked.get("overview"), asked.get("targets")].filter(Boolean);
  })();
  const RUN_TO_WATCH = ACQUISITIONS[0] ?? null;

  /* Which engine to open the canvas columns with — `?engine=neuroglancer-under`.

     It is there for asking a page one question about one engine: whether a page
     delivered in a particular way can draw with it at all. That is what the
     checks on the built page use it for. Left out, each column opens with the
     engine it is named after. `shared/canvas/engines.js` says what engines there
     are, and when one of them cannot be offered.

     **It overrides every column at once, which now defeats the point of the
     layout** — the columns exist to be seen against one another, and this makes
     them all the same. It made sense when the page showed one picture at a time.
     Whether it should be per column, or go, is on the list of things to decide;
     it is left as it was rather than changed in passing, because both checks on
     the built page stand on it. */
  const ENGINE_ASKED_FOR = new URLSearchParams(location.search).get("engine");

  /* What colour to paint the room the run declared, underneath the picture, as
     six hex digits — `?ground=1e3a5f`. Left out, nothing is drawn underneath and
     an unimaged part of the canvas is simply dark.

     This is worth having because a run declares far more room than it images,
     and painting that room says where the picture is going to appear. It is also
     how the tests ask a question the design rests on: whether the parts of the
     image nobody has imaged let what is beneath them show through. */
  const GROUND = (() => {
    const asked = new URLSearchParams(location.search).get("ground");
    if (!asked || !/^[0-9a-f]{6}$/i.test(asked)) return null;
    return [0, 2, 4].map((at) => parseInt(asked.slice(at, at + 2), 16));
  })();

  /* Whether the dark parts of the picture should be see-through — `?seethrough=1`.
     Off unless asked for, because it makes a place that was imaged and came back
     black look exactly like a place nobody has visited, and during a run those
     are two different things worth telling apart. `steps/5_scan_the_overview/overview.js` explains
     what it does and why it has to exist. */
  const SEE_THROUGH = new URLSearchParams(location.search).get("seethrough") === "1";

  /**
   * The scan itself, drawn beneath the plan by one of the drawing engines.
   *
   * Pointed at with `?picture=<folder>`, which is a folder of small JPEGs and a
   * `tiles.json` saying where each belongs — what
   * `viz_studio/backend/jpeg_tiles.py` makes from the files a microscope
   * exports. Nothing is opened unless the page was given one, because an engine
   * is a large thing to fetch and a page nobody pointed at a scan has no use
   * for it.
   *
   * ## The view is not shared, it is handed down
   *
   * The plan's canvas owns the gestures and this follows it. That is a
   * deliberate choice between two arrangements that look equally reasonable:
   * both surfaces could listen and each move the other, and then a drag would
   * be answered twice and the two would argue about rounding for ever. One
   * listens, one follows, and they cannot disagree.
   *
   * The two speak different dialects of the same thing, and converting between
   * them is the whole of the wiring. The plan places a point in the carrier's
   * frame at `x * scale + tx` browser pixels; the engine places it at
   * `width/2 + (x - centre) / zoom`. Setting `zoom = 1 / scale` and the centre
   * to whatever puts the middle of the box in the same place makes the two
   * projections identical, which is why the scan sits under the plan rather
   * than merely near it.
   */
  const thePicture = (() => {
    const asked = new URLSearchParams(location.search).get("picture");
    const host = el("picture-host");
    let viewer = null;
    let opening = false;

    async function open() {
      if (!asked || viewer || opening) return;
      opening = true;
      try {
        const { openViewer } = await import("../../../../../viz_studio/options/jpeg-under/viewer.js");
        viewer = await openViewer(host, {
          acquisitions: [{ url: asked, name: asked.split("/").filter(Boolean).pop() ?? "scan" }],
          /* The same colour the page paints, so the seam between the scan's own
             background and the ground above it never shows. */
          background: css("--screen"),
        });
        /* Left where a test can reach it. What matters about a picture is what
           reached the screen, and a viewer that reports itself perfectly opened
           while drawing nothing is the failure this project keeps meeting — so
           the tests photograph the box, and this is only the way to ask it
           where it is looking. */
        window.__thePicture = viewer;
        followTheStage();
      } catch (e) {
        console.error(`the scan at ${asked} could not be opened — ${e.message}`);
      } finally {
        opening = false;
      }
    }

    /** Put the scan where the plan is looking, exactly. */
    function followTheStage() {
      if (!viewer) return;
      const box = host.getBoundingClientRect();
      const [ox, oy] = carrierOriginUm();
      viewer.setView({
        zoom: 1 / view.scale,
        centre: {
          x: (box.width / 2 - view.tx) / view.scale - ox,
          y: (box.height / 2 - view.ty) / view.scale - oy,
        },
      });
    }

    return {
      /** Whether this page was pointed at a scan at all. */
      get asked() { return !!asked; },
      open,
      followTheStage,
      /** A field has landed, so there may be more of the scan to read. */
      mayHaveLanded() { viewer?.tilesMayHaveLanded?.(); },
    };
  })();

  /* Opened at once when the page was pointed at a scan. It is not opened lazily
     on the first draw, because the first draw is also the first thing an
     operator sees, and a picture that arrives a moment after everything else
     reads as the page having stumbled. */
  thePicture.open();

  const liveOverview = (() => {
    const cv = el("overview-canvas");
    const note = el("overview-note");
    /* No plane control here any more: stepping through a stack is a thing to
       do to a picture, and the viewer will bring its own. */
    let picture = null;      // the drawing, once the run has been opened
    let opening = false;
    let showing = false;
    let heartbeat = null;

    const say = (text) => { note.hidden = !text; note.textContent = text ?? ""; };

    /* Opened the first time it is needed, and kept afterwards. Opening reads the
       run's description over the network, so it is not something to do on every
       render — and re-opening would throw away where the operator had panned to. */
    async function open() {
      if (picture || opening) return;
      opening = true;
      try {
        const { showOverview } = await import("../../workflows/target_acquisition/steps/5_scan_the_overview/overview.js");
        picture = await showOverview(cv, {
          stores: ACQUISITIONS, onStatus: say, ground: GROUND, seeThrough: SEE_THROUGH,
        });
        /* Left where a test can reach it. Nothing on the page reads this: what
           matters about a picture is what is on the screen, and a viewer that
           reports itself perfectly loaded while drawing nothing is exactly the
           failure this is meant to catch. */
        window.__liveOverview = picture;
        picture.lookAgain();
      } catch (e) {
        say(`the run at ${RUN_TO_WATCH} could not be opened — ${e.message}`);
      } finally {
        opening = false;
      }
    }

    return {
      /** Whether this page was given a run to watch at all. */
      watching: !!RUN_TO_WATCH,

      get showing() { return showing; },

      /* The acquired picture belongs to the step that acquires it. Standing on
         the scan is what brings it up, and stepping away puts the plan back —
         the plan is what the other steps are about. */
      showFor(step, panel) {
        const wants = !!RUN_TO_WATCH && panel === "canvas" && step.mode === "scan";
        // Only the change is acted on. Framing the overview again on every
        // render would undo the operator's panning a few times a second.
        if (wants === showing) return;
        showing = wants;
        cv.hidden = !wants;
        note.hidden = !wants || !note.textContent;
        clearInterval(heartbeat);
        heartbeat = null;
        if (!wants) return;
        open().then(() => picture?.fit());
        /* And while it is on screen, it reads the run every second whether or
           not anything has told it to.

           This is not belt and braces. The scan on this page is a rehearsal that
           finishes after a couple of seconds, while a real acquisition takes as
           long as it takes — so the tiles that land after the rehearsal has
           stopped reporting are exactly the ones a picture driven only by the
           step would miss. A run stops changing when it is over, and reading a
           finished run again simply draws the same picture, so the cost of this
           when there is nothing new is a handful of requests a second. */
        heartbeat = setInterval(() => picture?.tileMayHaveLanded(), 1500);
      },

      /** A position has been saved, so there may be more picture to read. */
      tileMayHaveLanded() {
        picture?.tileMayHaveLanded();
        /* The scan drawn beneath the plan reads its own note again. Nothing on
           disk announces a new field, so it is asked rather than told — the
           same reason the overview above has to be asked. */
        thePicture.mayHaveLanded();
      },

      /** Frame the whole overview again, for the Fit button. */
      fit() { picture?.fit(); },
    };
  })();

  /* ============================================================
     the stage viewer — one projection, layers on top
     ============================================================ */
  const stageCv = el("stage-canvas");
  const stageTip = el("stage-tip");
  const view = { scale: 0.03, tx: 0, ty: 0, fitted: false };

  /* The canvas is the stage, so it is what the view frames — not the carrier
     inside it and not the scan inside that. Everything else is drawn in the
     same coordinates and lands where it belongs.

     Its size is the instrument's: `get_info().canvas` gives the travel and
     where the stage is, and connecting takes both. Before a session there
     is the placeholder, so the picture has a frame to draw. */
  const STAGE_UM = [STAGE_LIMITS_MM.width * 1000, STAGE_LIMITS_MM.height * 1000];
  let stageReported = null;

  function takeTheCanvas(canvas) {
    if (!canvas?.x_um || !canvas?.y_um) return;
    STAGE_UM[0] = canvas.x_um[1] - canvas.x_um[0];
    STAGE_UM[1] = canvas.y_um[1] - canvas.y_um[0];
    view.fitted = false;
    drawStage();
  }

  /** The stage mark, from `get_xyz`: per axis, a value in micrometres. */
  function takeThePosition(xyz) {
    if (!xyz?.x || !xyz?.y) return;
    stageReported = { x: Number(xyz.x.value), y: Number(xyz.y.value), z: Number(xyz.z?.value ?? 0) };
    drawStage();
  }

  /* Where the carrier's own zero sits on the stage.
   *
   * Centred in the travel, because that is where a holder puts a plate and it
   * is the only placement that can be worked out rather than measured. It is a
   * default and not a fact: the real offset comes from calibrating against a
   * plate actually on the stage, and this is the one line that answer replaces.
   *
   * Everything the run produces is placed from this point too, so the carrier
   * and what was imaged inside it move together instead of drifting apart the
   * moment either of them moves. */
  function carrierOriginUm() {
    const [w, h] = carrierWidget.extentUm(state.carrier);
    return [(STAGE_UM[0] - w) / 2, (STAGE_UM[1] - h) / 2];
  }

  function fitView() {
    const w = stageCv.cssW || 800, h = stageCv.cssH || 600;
    const pad = 26;
    const [fw, fh] = STAGE_UM;
    const s = Math.min((w - 2 * pad) / fw, (h - 2 * pad) / fh);
    view.scale = s;
    view.tx = (w - fw * s) / 2;
    /* At the top, with the margin the sides have, rather than floating in
       the middle of whatever height the window happens to give the canvas. */
    view.ty = pad;
    view.fitted = true;
  }

  /* Where the microscope is, in stage micrometres.
   *
   * Worked out rather than stored. It is wherever the run last drove to — the
   * position of the tile the scan has just taken — and the middle of the
   * travel before it has driven anywhere, which is where a stage sits when
   * nothing has asked it to be anywhere else. A stored copy would be a second
   * answer to keep right, and would be wrong the first time a step forgot to
   * write to it.
   */
  /* Where the stage is parked before the run has driven it anywhere, as a
     fraction of the travel. In the corner rather than the middle, and far
     enough into the corner to be off the carrier as well as off the middle of
     it: a carrier is mounted centred, so the margin around it is the only part
     of the travel where a mark is on the picture without being on top of a
     well. A real driver replaces this with the position it reads. */
  const PARKED = [0.04, 0.04];

  function whereTheStageIs() {
    const [ox, oy] = carrierOriginUm();
    const taken = state.plan[Math.min(state.tilesShown, state.plan.length) - 1];
    /* Reported by the instrument at connect when it was; parked otherwise. */
    if (!taken && stageReported) {
      return { x: stageReported.x, y: stageReported.y, z: stageReported.z };
    }
    const [cx, cy] = taken
      ? [taken.x, taken.y]
      : [STAGE_UM[0] * PARKED[0] - ox, STAGE_UM[1] * PARKED[1] - oy];
    /* The height is the sample's, because that is what the objective is on
       when it is anywhere at all. Before a focus strategy has been applied it
       is what the surface would be if it were measured there, which is the
       same claim the rest of the mock makes about the sample. */
    return { x: cx + ox, y: cy + oy, z: trueZ(cx, cy) };
  }

  /* Where the microscope is standing, over everything else on the picture.
   *
   * A crosshair rather than a dot, and a crosshair with a hole in the middle:
   * the arms reach out of whatever is under them, and the gap leaves the exact
   * position visible instead of covering the one pixel the mark is about. Its
   * size is in screen pixels and not in micrometres, because it is not a thing
   * on the stage that can be zoomed into — it is a statement about the stage,
   * and it has to stay the same size to keep being read as one.
   *
   * The numbers are beside it because the mark alone answers "where on this
   * picture", and the question is where on the stage. */
  /* The mark: a crosshair with a hole in the middle. The gap is the point of
     it — the arms reach out of whatever is behind them and the centre stays
     clear, so the mark shows a position rather than covering it. */
  function crosshair(ctx, x, y, arm, gap, dot) {
    ctx.beginPath();
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      ctx.moveTo(x + dx * gap, y + dy * gap);
      ctx.lineTo(x + dx * arm, y + dy * arm);
    }
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, dot, 0, Math.PI * 2);
    ctx.fill();
  }

  /* Whether the pointer is on the mark. Kept here rather than worked out while
     drawing, because it is the pointer that decides it and the drawing happens
     for many other reasons than the pointer having moved. */
  let stageMarkHot = false;

  /* How close the pointer has to be to count as on it, in screen pixels. A
     little wider than the mark itself: it is a cross made of thin lines, and
     asking for the exact pixel of one of them is asking for a fight. */
  const STAGE_MARK_REACH = 15;

  /** Where the mark is on screen, for the pointer to be measured against. */
  const stageMarkAt = () => {
    const at = whereTheStageIs();
    return toScreen(at.x, at.y);
  };

  /* Where the microscope is standing, drawn on the stage.
   *
   * Through the same projection as everything else on the canvas, so it is
   * registered to the stage rather than to the screen: pan the picture and it
   * travels with the carrier, zoom in and it stays over the same micrometre.
   * That is the whole point of it — a mark that sat still while the picture
   * moved would be decoration.
   *
   * Its size is the one thing not in stage units. It is in screen pixels,
   * because the mark is not a thing on the stage that can be zoomed into — it
   * is a statement about the stage, and it has to stay the same size to keep
   * being read as one.
   *
   * It says where and not what. The three numbers behind it are worth having
   * and are not worth having on screen at all times: a permanent readout in
   * the corner is three figures to read past on every step, when the question
   * they answer is only ever asked about this one mark. So they arrive on
   * hover, and the mark thickens to say it is the thing being asked about. */
  function drawWhereTheStageIs(ctx) {
    const [x, y] = stageMarkAt();
    ctx.save();
    ctx.strokeStyle = css("--mark-stage");
    ctx.fillStyle = css("--mark-stage");
    ctx.lineWidth = stageMarkHot ? 2.5 : 1.5;
    crosshair(ctx, x, y, 12, 4, stageMarkHot ? 2.2 : 1.6);
    ctx.restore();
  }

  /**
   * Point the tip at the mark, or say that it is not on it.
   *
   * The tip is the page's own hover panel — the one the cells use — so where a
   * hover answer appears is one decision made once, rather than this mark
   * inventing a second place for the same kind of answer to show up in.
   *
   * Millimetres across and micrometres down, because that is what the rest of
   * the page says: a stage is driven in millimetres and focused in micrometres.
   */
  function tipTheStageMark(e) {
    const [mx, my] = stageMarkAt();
    const hot = Math.hypot(e.offsetX - mx, e.offsetY - my) <= STAGE_MARK_REACH;
    if (hot !== stageMarkHot) { stageMarkHot = hot; drawStage(); }
    if (!hot) return false;
    const at = whereTheStageIs();
    stageTip.classList.add("on");
    stageTip.innerHTML =
      `<b>stage</b><br><b>x</b> ${(at.x / 1000).toFixed(2)} mm`
      + `<br><b>y</b> ${(at.y / 1000).toFixed(2)} mm`
      + `<br><b>z</b> ${at.z.toFixed(0)} µm`;
    stageTip.style.left = `${Math.min(e.offsetX + 14, stageCv.cssW - 130)}px`;
    stageTip.style.top = `${Math.max(6, e.offsetY - 66)}px`;
    return true;
  }

  /* Where the stage ends. Drawn first and faintly: it is the edge of what any
     of this can reach, which is context for everything else rather than a
     thing in its own right. */
  function drawStageLimits(ctx) {
    const [x, y] = toScreen(0, 0);
    ctx.save();
    ctx.strokeStyle = css("--line-strong");
    ctx.lineWidth = 1;
    ctx.strokeRect(x + 0.5, y + 0.5, STAGE_UM[0] * view.scale, STAGE_UM[1] * view.scale);
    ctx.restore();
  }

  const toScreen = (x, y) => [x * view.scale + view.tx, y * view.scale + view.ty];
  const toWorld = (px, py) => [(px - view.tx) / view.scale, (py - view.ty) / view.scale];

  function tileTexture(ctx, tile, place) {
    const [sx, sy] = place(tile.x - tile.frameUm / 2, tile.y - tile.frameUm / 2);
    const sz = tile.frameUm * view.scale;

    // tile ground with a gentle per-tile vignette — the flat-field seam
    // an operator actually sees in a stitched overview
    const g = ctx.createRadialGradient(sx + sz / 2, sy + sz / 2, sz * 0.1, sx + sz / 2, sy + sz / 2, sz * 0.75);
    g.addColorStop(0, "#0d1a24");
    g.addColorStop(1, "#05090e");
    ctx.fillStyle = g;
    ctx.fillRect(sx, sy, sz + 0.6, sz + 0.6);
  }

  const layersOff = new Set();
  let layerFade = 1;
  let layersLocked = false;
  let seeThroughGround = [];
  /* The stack as it was last drawn, so the controls and a click can ask about
     it without drawing a frame to find out. */
  let theStack = [];

  function theStageLayers({ place, shown, ch0, ch1, w, h, editing }) {
    const activeMode = step(state.activeIdx).mode;

    return [
      {
        key: "ground",
        label: "Background",
        explains: "The page's own surface, under everything else the canvas draws. Turn it "
          + "off and the picture underneath shows through everywhere; leave it on and the "
          + "picture shows only where a window has been opened.",
        /* **This is the layer that decides whether a picture underneath can be
           seen at all**, and it is worth being plain about why it is a layer
           rather than a fill.
        
           The scan itself is drawn on a surface of its own, beneath this one.
           Anything painted here covers it. So if this were painted outside the
           stack — which is how it was written first — a window cut through the
           layers would have nothing to reveal: the drawing above would go, and
           the page's own grey would still be sitting on top of the picture.
        
           As the bottom layer of the stack it is cut by the same window as
           everything above it, by the same rule and in the same pass. Open a
           window over the fields that have landed and the scan appears there,
           through every layer including this one. Turn this off altogether and
           the scan is simply visible everywhere.
        
           It is a flat fill and therefore the one layer that is not sparse, but
           that is exactly its job: it is the ground, and ground is not sparse. */
        shown: true,
        paint: ({ context: ctx, width, height }) => {
          ctx.fillStyle = css("--screen");
          ctx.fillRect(0, 0, width, height);
        },
      },

      {
        key: "limits",
        label: "Stage",
        explains: "The edge of where the stage can travel. Context for everything else "
          + "rather than a thing the run produced, which is why it is drawn faintly.",
        /* With the session, not before: the limits are a readout from the
           connected microscope's configuration, so an unconnected page shows
           nothing it cannot yet know. */
        shown: state.done.has("connect"),
        paint: ({ context: ctx }) => drawStageLimits(ctx),
      },

      {
        key: "carrier",
        label: "Carrier",
        explains: "The plate the sample is mounted in — its outline and its wells. The "
          + "room the run happens in.",
        shown: state.done.has("carrier"),
        paint: ({ context: ctx }) => {
          /* Grey, not the accent: the carrier is the room the run happens in,
             not a thing the run produced. Dark enough to read against the stage
             behind it, which is grey too. */
          carrierWidget.drawOn(ctx, {
            config: state.carrier, toScreen: place, scale: view.scale,
            colour: css("--ink-3"), fill: css("--surface-3"),
          });
        },
      },

      {
        key: "tiles",
        label: "Tiles",
        explains: "The fields the scan has taken, in the order it wrote them, with the "
          + "tissue each one found. This is what the run has actually seen.",
        shown: shown > 0,
        paint: ({ context: ctx }) => {
          ctx.save();
          const done = state.plan.slice(0, shown);
          for (const t of done) tileTexture(ctx, t, place);
          /* Tissue is drawn inside the tiles that have been taken, because an
             image is the only way the run knows it is there. */
          ctx.globalCompositeOperation = "lighter";
          for (const t of done) {
            const d = density(t.x, t.y);
            if (d < 0.02) continue;
            const [bx, by] = place(t.x, t.y);
            const br = (t.frameUm * 0.75) * view.scale;
            const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
            if (ch0) g.addColorStop(0, `rgba(34,211,238,${0.34 * d})`);
            g.addColorStop(0.55, ch1 ? `rgba(245,158,11,${0.16 * d})` : `rgba(34,211,238,${0.12 * d})`);
            g.addColorStop(1, "rgba(0,0,0,0)");
            ctx.fillStyle = g;
            ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
          }
          ctx.restore();

          // ---- scan frontier: the tile the stage is standing on
          if (state.running === "scan" && state.plan[shown]) {
            const t = state.plan[shown];
            const [fx, fy] = place(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
            ctx.strokeStyle = css("--accent");
            ctx.lineWidth = 2;
            ctx.setLineDash([5, 4]);
            ctx.strokeRect(fx, fy, t.frameUm * view.scale, t.frameUm * view.scale);
            ctx.setLineDash([]);
          }

          /* ---- sample bounds: the edge of what has been imaged, so it exists
             once something has been. Drawn from the first tile it was a second
             square sitting in the plate's corner before any of this had
             happened, which says the run has a sample somewhere it does not yet
             have one. */
          if (sample.bounds) {
            const b = sample.bounds;
            const [bx, by] = place(b.xMin, b.yMin);
            ctx.strokeStyle = css("--line-strong");
            ctx.lineWidth = 1;
            ctx.strokeRect(bx, by, (b.xMax - b.xMin) * view.scale, (b.yMax - b.yMin) * view.scale);
          }
        },
        /* A click on a taken field is a click on that field. This is what
           opening a position from the picture will hang off. */
        reaches: (at) => {
          const half = (t) => t.frameUm / 2;
          return state.plan.slice(0, shown).find(
            (t) => Math.abs(at.x - t.x) <= half(t) && Math.abs(at.y - t.y) <= half(t),
          ) ?? null;
        },
      },


      {
        key: "cells",
        label: "Cells",
        explains: "What detection found. The ones that passed the gate are ringed, so which "
          + "is which does not rest on colour alone.",
        shown: state.cellsShown,
        paint: ({ context: ctx }) => {
          const ctxRad = Math.max(1.1, 1.4 * Math.sqrt(view.scale / 0.03));
          ctx.fillStyle = css("--mark-context");
          ctx.globalAlpha = 0.55;
          ctx.beginPath();
          for (const c of sample.cells) {
            if (!state.detected.has(c.id) || state.gated.has(c.id)) continue;
            const [x, y] = place(c.x, c.y);
            if (x < -8 || y < -8 || x > w + 8 || y > h + 8) continue;
            ctx.moveTo(x + ctxRad, y);
            ctx.arc(x, y, ctxRad, 0, Math.PI * 2);
          }
          ctx.fill();
          ctx.globalAlpha = 1;

          // gated cells — ringed, so identity is not carried by colour alone
          const gr = Math.max(3, 4.2 * Math.sqrt(view.scale / 0.03));
          for (const c of sample.cells) {
            if (!state.gated.has(c.id)) continue;
            const [x, y] = place(c.x, c.y);
            if (x < -10 || y < -10 || x > w + 10 || y > h + 10) continue;
            ctx.beginPath(); ctx.arc(x, y, gr, 0, Math.PI * 2);
            ctx.fillStyle = "#0284c7"; ctx.fill();
            ctx.lineWidth = 1.5; ctx.strokeStyle = css("--screen"); ctx.stroke();
          }
        },
        reaches: (at) => {
          let best = 12 / view.scale, hit = null;
          for (const c of sample.cells) {
            if (!state.detected.has(c.id)) continue;
            const d = Math.hypot(c.x - at.x, c.y - at.y);
            if (d < best) { best = d; hit = c; }
          }
          return hit;
        },
      },

      {
        key: "targets",
        label: "Targets",
        explains: "The cells that have been imaged at high resolution.",
        shown: state.acquired.length > 0,
        paint: ({ context: ctx }) => {
          for (const id of state.acquired) {
            const c = sample.cells[id - 1];
            const [x, y] = place(c.x, c.y);
            const rr = Math.max(7, 9 * Math.sqrt(view.scale / 0.03));
            ctx.beginPath(); ctx.arc(x, y, rr, 0, Math.PI * 2);
            ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 2.2; ctx.stroke();
            ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2);
            ctx.fillStyle = "#16a34a"; ctx.fill();
          }
        },
      },

      {
        key: "focus",
        label: "Focus",
        explains: "Where the microscope will focus, and what it has measured there. Stays "
          + "solid however far the rest is faded: fading the plan to see the picture is "
          + "not a request to lose the focus points too.",
        /* Only while standing on that step — walking away leaves the canvas the
           plain picture every other step reads. */
        shown: activeMode === "focus",
        /* Not held back to the end, though it was at first. The scan fields are
           drawn *over* the focus map — that is the order the page had before
           any of this was a stack — and holding the map back put it on top
           instead, which covered the very fields the operator is placing focus
           points among. A layer that stays solid is a layer drawn last, so it
           cannot also be a layer drawn early: this one has to be early, and the
           cost is that the shared fade reaches it. Splitting the map from the
           points would buy back both, and is the thing to do if that fade ever
           matters here. */
        paint: ({ context: ctx }) => drawFocusLayer(ctx, place, view.scale, w, h),
      },

      {
        key: "plan",
        label: "Plan",
        explains: "The positions the microscope was told to visit. It stays readable once "
          + "the tiles start landing on top of it, dimmed, because by then the images "
          + "are the answer and this is only the question.",
        /* Not before the step that says where to scan. Walking back to the
           carrier is walking back to a question the plan is an answer to — the
           fields were placed against these areas, and drawing them over a plate
           that is still being changed shows a plan for a carrier that may be
           about to stop existing. The fields are kept, not discarded: coming
           forward again finds them where they were. */
        shown: state.activeIdx >= indexOfStep("scanfields"),
        paint: ({ context: ctx }) => {
          scanfieldsWidget.drawOn(ctx, {
            fields: state.fields, preset: activePreset(), carrier: state.carrier,
            toScreen: place, scale: view.scale, dim: shown > 0,
            marked: editing?.marked(),
          });
        },
      },

      {
        key: "detect",
        label: "Test field",
        explains: "The one position detection is being tuned on, so the canvas says which "
          + "tile the channel's preview is of.",
        shown: activeMode === "detect" && !!state.plan[state.detect.tile],
        staysSolid: true,
        paint: ({ context: ctx }) => {
          const t = state.plan[state.detect.tile];
          const half = t.frameUm / 2;
          const [x, y] = place(t.x - half, t.y - half);
          ctx.strokeStyle = css("--accent");
          ctx.lineWidth = 2;
          ctx.strokeRect(x, y, t.frameUm * view.scale, t.frameUm * view.scale);
        },
      },

      {
        key: "editing",
        label: "Editing",
        explains: "The handles and guides of whatever is being drawn by hand. Always solid "
          + "and always on top: you cannot edit what you cannot see.",
        shown: !!editing,
        staysSolid: true,
        paint: ({ context: ctx }) => editing.drawChrome(ctx, { toScreen: place, scale: view.scale }),
      },

      {
        key: "anchors",
        label: "Anchors",
        explains: "The points the carrier is being registered from — where the plate really "
          + "is, as opposed to where it was assumed to be. Solid, because a mark you are "
          + "placing by hand has to be exactly where you put it.",
        /* Only on the step that places them: away from it they are answered
           questions, and the carrier drawn from them says the same thing. */
        shown: activeMode === "carrier" && state.anchors.length > 0,
        staysSolid: true,
        paint: ({ context: ctx }) => {
          const [ox, oy] = carrierOriginUm();
          ctx.strokeStyle = css("--mark-focus");
          ctx.fillStyle = css("--mark-focus");
          for (const a of state.anchors) {
            const [x, y] = toScreen(a.x + ox, a.y + oy);
            ctx.lineWidth = a.stage ? 2.4 : 1.6;
            crosshair(ctx, x, y, 11, 4, a.stage ? 3 : 2);
          }
        },
      },

      {
        key: "stage",
        label: "Where the stage is",
        explains: "A crosshair on the position the stage is standing at. Always solid: it "
          + "is where the microscope actually is, and that should never be the thing that "
          + "went faint.",
        /* With the session: where the stage is standing is a readout from the
           microscope, and there is no microscope until the operator has
           connected. */
        shown: state.done.has("connect"),
        staysSolid: true,
        paint: ({ context: ctx }) => drawWhereTheStageIs(ctx),
      },

      {
        key: "scale",
        label: "Scale bar",
        explains: "How far a stretch of screen is on the sample. A reading rather than a "
          + "drawing, so it stays solid — a scale bar you can half see through is a scale "
          + "bar you cannot trust.",
        /* A reading about a stage nobody has connected to yet would be a
           reading about nothing. */
        shown: state.done.has("connect"),
        staysSolid: true,
        paint: ({ context: ctx }) => drawScaleBar(ctx, w, h),
      },
    ];
  }

  function drawStage() {
    if (!sizeCanvas(stageCv)) return;
    if (!view.fitted) fitView();
    const ctx = stageCv.getContext("2d");
    const w = stageCv.cssW, h = stageCv.cssH;

    /* Cleared to nothing. The page's own surface is painted by the bottom
       layer of the stack rather than here, and that is not tidiness — it is
       what lets a picture be seen underneath at all. See the `ground` layer. */
    ctx.clearRect(0, 0, w, h);

    /* The canvas only shows what the run actually knows. Before a session is
       open it knows nothing, so it is empty; the stage limits are a readout
       from the connected microscope's configuration, so they appear with the
       session; the carrier appears at its own step, when the run is told what
       the sample is mounted in.

       **Each layer decides that for itself, and the drawing never stops early.**
       It used to return here, before anything had been drawn, which was right
       while this surface was opaque and wrong the moment a picture was put
       beneath it: returning skipped the background along with everything else,
       so a scan the run had not got to yet was showing through an empty canvas
       before the operator had even connected. A layer with nothing to say draws
       nothing; the ground is still ground. */

    /* One projection for everything that sits in the carrier: the carrier
       itself and every tile, cell and target the run put inside it. Handed
       down rather than reached for, so where the carrier stands is decided in
       one place and nothing can be drawn against a different answer. */
    const [ox, oy] = carrierOriginUm();
    const place = (x, y) => toScreen(x + ox, y + oy);

    const editing = sideWidget()?.id === "scanfields" ? state.editor : null;
    const stack = theStageLayers({
      place,
      shown: Math.max(state.tilesShown, 0),
      /* Both colours, always. Which channels are mixed is a question about a
         picture, and the viewer that draws it is where it will be asked —
         which is why the switches that used to be under the canvas are gone. */
      ch0: true,
      ch1: true,
      w, h, editing,
    });
    /* Two different questions, and they must not be run together. `hasSomething`
       is whether the *run* has anything for this layer — no cells have been
       found, no targets imaged — and it decides whether the layer gets a
       control at all. `shown` is what reaches the screen, which is that answer
       and then whatever the operator hid.

       Conflating them was wrong in both directions: a layer the operator hid
       lost its own button, so there was no way to bring it back; and a layer
       the run had nothing for still offered a button that did nothing. */
    for (const layer of stack) {
      layer.hasSomething = layer.shown !== false;
      if (layersOff.has(layer.key)) layer.shown = false;
    }
    theStack = stack;

    /* The whole stack in one drawing, faded and cut through as the controls
       say. Micrometres in the carrier's own frame, which is where the tiles,
       the cells and the targets all live — so a window given in those numbers
       lands on the fields it names. */
    theDrawingAbove(stack, { dial: layerFade, seeThrough: seeThroughGround })?.({
      context: ctx,
      centre: { x: 0, y: 0 },
      zoom: 1 / view.scale,
      width: w,
      height: h,
      density: 1,
      project: (x, y) => { const [px, py] = place(x, y); return { x: px, y: py }; },
      unproject: (px, py) => { const [wx, wy] = toWorld(px, py); return { x: wx - ox, y: wy - oy }; },
    });

    /* Set here rather than on the pointer alone, so a tool armed from the panel
       or a key says so before the mouse is moved to find out. */
    stageCv.style.cursor = editing ? editing.cursor() : focusCursor();

    /* The scan beneath follows the view the plan was just drawn with, so the
       two are never a frame apart. Cheap: it is two divisions and a setView,
       and the engine only redraws if something actually moved. */
    thePicture.followTheStage();
    renderStageLayerControls();
  }

  /**
   * The controls for the stack, built again whenever the stack changes.
   *
   * Built rather than written into the markup, because the stack is not fixed:
   * it grows as a run goes — the cells appear when detection has found some,
   * the targets when any have been imaged — and a row of controls written out
   * in advance would either name layers that do not exist yet or leave a layer
   * on screen with no way to turn it off.
   *
   * A layer the run has nothing for is left out entirely rather than shown
   * unavailable. There is no useful difference for an operator between a
   * control that cannot be pressed and a control that is not there, and the
   * second takes less room in a bar that has other things to say.
   */
  let barSaysThis = "";

  function renderStageLayerControls() {
    const stageLayerBar = el("stage-layers");
    if (!stageLayerBar) return;
    const here = theStack.filter((layer) => layer.paint && layer.hasSomething);
    /* Rebuilt only when the set of layers actually changes. A run redraws the
       canvas many times a second while scanning, and rebuilding a row of
       buttons that often would take the press an operator was in the middle
       of. */
    const signature = here.map((l) => `${l.key}:${layersOff.has(l.key)}`).join("|")
      + `|${layerFade}|${layersLocked}`;
    if (signature === barSaysThis) return;
    barSaysThis = signature;
    stageLayerBar.textContent = "";
    if (!here.length) return;

    const title = document.createElement("span");
    title.style.cssText = "font-weight:600;color:var(--ink-3)";
    title.textContent = "Layers";
    stageLayerBar.append(title);

    for (const layer of here) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "layer-chip";
      button.dataset.layer = layer.key;
      button.setAttribute("aria-pressed", String(!layersOff.has(layer.key)));
      button.title = layer.explains ?? "";
      button.textContent = layer.label ?? layer.key;
      button.addEventListener("click", () => {
        if (layersOff.has(layer.key)) layersOff.delete(layer.key);
        else layersOff.add(layer.key);
        drawStage();
      });
      stageLayerBar.append(button);
    }

    /* One dial for the whole stack. "Let me see what is underneath" is one
       thought and should be one movement, not a visit to every layer in turn.
       It only ever fades: a layer already set faint does not become solid
       because this is turned up. */
    const fade = document.createElement("label");
    fade.className = "layer-fade";
    fade.title = "How solid the layers are drawn. Turn it down to see what is underneath "
      + "them. Layers that stay solid — the focus points, the editing handles — are not "
      + "affected.";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0"; slider.max = "100"; slider.step = "1";
    slider.value = String(Math.round(layerFade * 100));
    slider.id = "layer-fade";
    slider.setAttribute("aria-label", "How solid the layers are drawn");
    slider.addEventListener("input", () => {
      layerFade = Number(slider.value) / 100;
      barSaysThis = "";
      drawStage();
    });
    fade.append(document.createTextNode("Fade"), slider);
    stageLayerBar.append(fade);

    /* The lock. An operator spends a long time looking at a plan they have
       already settled — checking it, showing it to somebody, panning around it
       while the run goes — and in all that time a stray click can only do harm.
       Locking leaves panning and zooming exactly as they were and stops only
       the picking. */
    const lock = document.createElement("button");
    lock.type = "button";
    lock.className = "layer-chip";
    lock.id = "layers-lock";
    lock.setAttribute("aria-pressed", String(layersLocked));
    lock.title = "Lock the layers so nothing can be picked, moved or drawn by accident. "
      + "Panning and zooming go on working.";
    lock.textContent = "Lock";
    lock.addEventListener("click", () => {
      layersLocked = !layersLocked;
      barSaysThis = "";
      drawStage();
    });
    stageLayerBar.append(lock);
  }

  /**
   * Open the ground the scan has already covered, so the picture shows through.
   *
   * Called as fields land. The plan, the tiles and everything else drawn over a
   * field that has been taken is opened up there, which is how an operator
   * watches the scan appear through their own drawing rather than beside it.
   *
   * In micrometres in the carrier's own frame, which is where the fields are,
   * so the window travels with the sample when the view is panned and grows
   * when it is magnified.
   */
  function openTheGroundThatHasBeenScanned(howMuch = 1) {
    const shown = Math.max(state.tilesShown, 0);
    seeThroughGround = state.plan.slice(0, shown).map((t) => ({
      x: t.x - t.frameUm / 2,
      y: t.y - t.frameUm / 2,
      w: t.frameUm,
      h: t.frameUm,
      letThrough: howMuch,
    }));
    drawStage();
  }

  /**
   * What the canvas will answer to, from outside it.
   *
   * There is no picture drawn beneath this canvas yet — that is the next piece
   * of work — so nothing on the page calls these. They are here rather than
   * held back because they are what the picture will be shown *through*, and
   * because a rule nobody can exercise is a rule nobody can check. The browser
   * tests drive them.
   */
  window.__theStageCanvas = {
    /** Open the ground the scan has covered, so a picture beneath shows there. */
    openScannedGround: openTheGroundThatHasBeenScanned,
    /** Close every window again. */
    closeTheGround() { seeThroughGround = []; drawStage(); },
    /** Open one named piece of the sample, in micrometres in the carrier's frame. */
    openThisGround(windows) { seeThroughGround = windows ?? []; drawStage(); },
    /** Which layers there are, and which are being drawn. */
    layers: () => theStack.map(({ key, label, shown, staysSolid }) =>
      ({ key, label, shown, staysSolid: !!staysSolid })),
    /**
     * Draw one of the layers, or stop drawing it.
     *
     * The same thing the controls in the canvas foot did before that strip was
     * taken off the screen. Here rather than only on a button because turning a
     * layer on and off is a thing the canvas can do, and it should not stop
     * being possible because nobody has yet decided where the button for it
     * belongs.
     */
    showLayer(key, on) {
      if (on) layersOff.delete(key);
      else layersOff.add(key);
      barSaysThis = "";
      drawStage();
    },
    /** How solid the layers are drawn, 0 to 1. */
    fadeTo(howSolid) {
      layerFade = Math.min(1, Math.max(0, Number(howSolid)));
      barSaysThis = "";
      drawStage();
    },
    /**
     * Where the run means to send the stage, in micrometres in the carrier's
     * own frame.
     *
     * This is the pairing the whole arrangement rests on, and it is worth
     * saying plainly where it shows up: **the files a microscope writes do not
     * say where they were taken.** The run knows, because it is the run that
     * sent the stage there. So making the small pictures for a scan means
     * handing these positions in alongside the files, and this is where a
     * rehearsal gets them from — exactly as the real thing will.
     */
    plan: () => state.plan.map(({ x, y, frameUm }) => ({ x, y, frameUm })),
    /**
     * Where a place on the sample lands on screen, as the plan itself works it
     * out.
     *
     * Here so that a test can ask the plan and the scan the same question and
     * compare their answers. That comparison is the one that matters: the two
     * are drawn by different code on different surfaces, and the only thing
     * making them one picture is that they agree about where things are. A
     * difference of a few pixels would look like a slightly blurry scan and be
     * a run pointed at the wrong place.
     */
    project: (x, y) => {
      const [ox, oy] = carrierOriginUm();
      return toScreen(x + ox, y + oy);
    },
  };

  /* Carrier coordinates for the editor: it places fields inside the carrier,
     so it is handed where the pointer is in that frame rather than where it is
     on the stage. */
  function toCarrier(px, py) {
    const [wx, wy] = toWorld(px, py);
    const [ox, oy] = carrierOriginUm();
    return { x: wx - ox, y: wy - oy };
  }

  /* The editor sees the pointer first and says whether it took it. Only what
     it turns down pans or picks, so drawing a region does not drag the stage
     out from under the shape being drawn. */
  function editorTook(kind, e) {
    /* Locked, nothing can be drawn or moved by accident. Panning and zooming
       are untouched — the lock is about picking, not about looking. */
    if (layersLocked) return false;
    if (sideWidget()?.id !== "scanfields" || !state.editor) return false;
    const { x, y } = toCarrier(e.offsetX, e.offsetY);
    const took = state.editor.pointer(kind, { x, y, shift: e.shiftKey, scale: view.scale });
    // the redraw is also what puts the cursor right, and it has to happen after
    // the editor has been told, or the answer is for where the pointer was
    if (took) drawStage();
    /* Only a true means the editor claimed the event. Anything else it answers
       is "the picture changed" — the pointer moved over a field — and the
       canvas still gets to say where the stage is under the cursor. */
    return took === true;
  }

  /* How big the picture is, said along the bottom of the canvas.
   *
   * Flat: a line and a number, no upstanding ends. The ticks were there to say
   * where the bar stops, which the bar already says, and two little uprights
   * in a picture full of drawn edges read as one more thing the run had put
   * there.
   *
   * It sits in a strip of its own, kept clear of the drawing: the plan is cut
   * off above it rather than running under it, because a rule with a plate
   * showing through it can be read as either. The strip is the page's own
   * surface, the same as the empty stage. */
  const SCALE_STRIP = 24;

  function drawScaleBar(ctx, w, h, scale = view.scale) {
    const targetPx = 130;
    const raw = targetPx / scale;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const nice = [1, 2, 5, 10].map((m) => m * pow).reduce((a, b) =>
      Math.abs(b - raw) < Math.abs(a - raw) ? b : a);
    const px = nice * scale;
    const x = w - px - 20, y = h - 9;

    ctx.fillStyle = css("--screen");
    ctx.fillRect(0, h - SCALE_STRIP, w, SCALE_STRIP);

    ctx.strokeStyle = css("--ink-2");
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, y); ctx.lineTo(x + px, y);
    ctx.stroke();
    ctx.fillStyle = css("--ink-2");
    ctx.font = '11.5px ui-monospace, Consolas, monospace';
    ctx.textAlign = "center";
    ctx.fillText(nice >= 1000 ? `${nice / 1000} mm` : `${nice} µm`, x + px / 2, y - 4);
    ctx.textAlign = "left";
  }

  /* ---- stage interaction ------------------------------------------------
     One button does everything, and what it does is decided by what is under
     it. The editor is asked first: a field is picked up, a tool draws. Only
     what it turns down moves the stage, so a press on empty canvas pans and a
     press on a shape does not drag the picture out from under it.

     A double-click ends an outline that has no last point of its own — the
     same press that places the final vertex, said twice.

     Alt+drag pans regardless. Without it there is no way to move the stage
     while a drawing tool is armed, since then the editor wants every press on
     empty canvas for the shape it is about to make. */
  let dragging = false, panMoved = false, lastX = 0, lastY = 0;

  const startPan = (e) => {
    dragging = true; panMoved = false;
    lastX = e.offsetX; lastY = e.offsetY;
    stageCv.setPointerCapture(e.pointerId);
  };

  // the canvas has no menu of its own, and a borrowed one over the plan is noise
  stageCv.addEventListener("contextmenu", (e) => e.preventDefault());
  stageCv.addEventListener("dblclick", (e) => editorTook("finish", e));

  stageCv.addEventListener("pointerdown", (e) => {
    if (e.button === 0 && e.altKey) { e.preventDefault(); startPan(e); return; }
    if (e.button !== 0) return;
    if (editorTook("down", e)) { stageCv.setPointerCapture(e.pointerId); return; }
    // a point already on the map is taken hold of before the picture is
    if (focusGrabbed(e)) { stageCv.setPointerCapture(e.pointerId); return; }
    startPan(e);
  });

  stageCv.addEventListener("pointermove", (e) => {
    if (focusMarquee) { focusMarqueeTo(e.offsetX, e.offsetY); return; }
    if (focusDrag) { focusDraggedTo(e.offsetX, e.offsetY); return; }
    if (!dragging && editorTook("move", e)) return;
    if (dragging) {
      const dx = e.offsetX - lastX, dy = e.offsetY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) panMoved = true;
      view.tx += dx; view.ty += dy;
      lastX = e.offsetX; lastY = e.offsetY;
      drawStage();
      return;
    }
    /* The readout is where the stage is, because the canvas is the stage. The
       hit test is not: a cell knows where it is in the carrier, so the pointer
       is put into the carrier's coordinates to meet it. */
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    el("stage-readout").textContent =
      `x ${wx.toFixed(0)} µm · y ${wy.toFixed(0)} µm · ${(view.scale * 1000).toFixed(1)} px/mm`;

    /* A focus point answers before anything under it: it is the small thing
       on top, and the press that finds it moves it rather than the picture. */
    if (focusHovered(e)) return;

    /* The mark first: it is drawn over everything, so it answers for the
       pointer before anything underneath it does. */
    if (tipTheStageMark(e)) return;

    // hover the nearest visible cell
    let hit = null;
    if (state.cellsShown) {
      const [ox, oy] = carrierOriginUm();
      let best = 12 / view.scale;
      for (const c of sample.cells) {
        if (!state.detected.has(c.id)) continue;
        const d = Math.hypot(c.x + ox - wx, c.y + oy - wy);
        if (d < best) { best = d; hit = c; }
      }
    }
    if (hit) {
      stageTip.classList.add("on");
      stageTip.innerHTML =
        `<b>cell</b> ${hit.id}<br><b>area</b> ${hit.area.toFixed(0)} µm²<br><b>int</b> ${hit.intensity.toFixed(2)}`;
      const left = Math.min(e.offsetX + 14, stageCv.cssW - 130);
      stageTip.style.left = `${left}px`;
      stageTip.style.top = `${Math.max(6, e.offsetY - 52)}px`;
    } else {
      stageTip.classList.remove("on");
    }
  });

  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    if (e && stageCv.hasPointerCapture?.(e.pointerId)) stageCv.releasePointerCapture(e.pointerId);
  };
  stageCv.addEventListener("pointerup", (e) => {
    if (focusMarquee) {
      if (stageCv.hasPointerCapture?.(e.pointerId)) stageCv.releasePointerCapture(e.pointerId);
      focusMarqueeTook(e.shiftKey);
      renderActionBar();
      return;
    }
    if (focusDrag) {
      const { moved } = focusDrag;
      focusDrag = null;
      if (stageCv.hasPointerCapture?.(e.pointerId)) stageCv.releasePointerCapture(e.pointerId);
      /* Held still on a point: the press picked it, and that is the whole of
         it. Placing happens where there is no point yet, which `focusPressed`
         answers for. */
      if (!moved && state.focus.placing) focusPressed(e.offsetX, e.offsetY);
      renderActionBar();
      return;
    }
    if (dragging) {
      const still = !panMoved;
      endDrag(e);
      /* Locked, a press picks nothing. Panning and zooming are untouched — the
         lock is about picking, not about looking. */
      if (still && !layersLocked) {
        anchorPressed(e.offsetX, e.offsetY)
          || focusPressed(e.offsetX, e.offsetY)
          || detectPressed(e.offsetX, e.offsetY);
      }
      return;
    }
    if (editorTook("up", e)) {
      if (stageCv.hasPointerCapture?.(e.pointerId)) stageCv.releasePointerCapture(e.pointerId);
      renderRail();
      return;
    }
    endDrag(e);
  });
  stageCv.addEventListener("pointerleave", (e) => {
    editorTook("leave", e);
    endDrag(e);
    stageTip.classList.remove("on");
    // the pointer is off the canvas, so it is off the mark whatever it was on
    if (stageMarkHot) { stageMarkHot = false; drawStage(); }
  });

  stageCv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [wx, wy] = toWorld(e.offsetX, e.offsetY);
    const f = Math.exp(-e.deltaY * 0.0016);
    view.scale = Math.max(0.004, Math.min(3, view.scale * f));
    view.tx = e.offsetX - wx * view.scale;
    view.ty = e.offsetY - wy * view.scale;
    drawStage();
  }, { passive: false });

  /* Fit frames whichever picture is on show. While the acquired overview is
     covering the plan, it is the thing being looked at, so it is the thing that
     gets framed. */
  el("fit-btn").addEventListener("click", () => {
    if (liveOverview.showing) { liveOverview.fit(); return; }
    fitView(); drawStage();
  });
  /* ============================================================
     the focus strategy panel — positions come from the microscope
     software; the operator drops focus points onto them
     ============================================================ */

  // ground truth the "microscope" would measure, so picked points behave
  /* The sample is not flat and not level: a gentle tilt across the plate. Over
     the carrier's own extent, so it is the same surface wherever the plan
     decides to look at it. */
  const carrierSpan = () => carrierWidget.extentUm(state.carrier);
  const trueZ = (x, y) => {
    const [w, h] = carrierSpan();
    return -412 + 96 * (x / w - 0.5) + 61 * (y / h - 0.5);
  };

  function focusSurface() {
    const f = state.focus;
    const [w, h] = carrierSpan();
    if (f.strategy === "fixed") return affineSurface({ c: f.zFixed, width: w, height: h });
    if (f.strategy === "reuse") {
      return affineSurface({ ...PREVIOUS_SURFACES[f.reuse].plane, width: w, height: h });
    }
    return f.surface;
  }

  /* Fitting the focus surface — which model the geometry buys, the fit, the
     height it predicts anywhere, and the residuals — lives in
     `microscope/pretend-sample/surface.js`, imported above, mirroring the
     Python `workflow/_focus_surface.py`. */

  // viridis — multi-hue but monotone in lightness, which is the property that
  // matters: it stays readable in greyscale and for every kind of colour vision
  const VIRIDIS = [
    [68, 1, 84], [72, 36, 117], [65, 68, 135], [53, 95, 141], [42, 120, 142],
    [33, 145, 140], [34, 168, 132], [68, 190, 112], [122, 209, 81], [189, 223, 38], [253, 231, 37],
  ];

  function viridis(t) {
    const u = Math.max(0, Math.min(0.99999, t)) * (VIRIDIS.length - 1);
    const i = Math.floor(u), f = u - i;
    const a = VIRIDIS[i], b = VIRIDIS[i + 1];
    return [
      Math.round(a[0] + (b[0] - a[0]) * f),
      Math.round(a[1] + (b[1] - a[1]) * f),
      Math.round(a[2] + (b[2] - a[2]) * f),
    ];
  }

  const zColor = (t) => { const c = viridis(t); return `rgb(${c[0]},${c[1]},${c[2]})`; };

  /* The surface is continuous, so it is painted as a continuous field: one
     small offscreen buffer sampled across the sample bounds, then scaled up
     with smoothing. Nothing about z is per-tile — only the positions are. */
  /* Its own camera. Sharing one with the canvas was tempting, but the two
     panels are different sizes, so a fit computed against one of them puts
     the sample off the edge of the other and clicks land nowhere. */

  /** The plate, in the frame the plan is written in. */
  function carrierBox() {
    const [w, h] = carrierSpan();
    return { xMin: 0, yMin: 0, xMax: w, yMax: h };
  }

  /* How far the positions themselves reach — the plate while there are none. */
  function planBox() {
    return sample.bounds ?? carrierBox();
  }

  /* Every position inside one compartment, by where it is rather than by any
     tag it carries: the plan is a flat list of tiles and a tile does not know
     which well it fell in, but the carrier says where every well is. */

  /**
   * Where to measure the focus: so many points in every scan field, or by hand.
   *
   * A scan field is the unit because it is the unit of the plan: the operator
   * drew it, or the grid laid it, around something worth imaging, and a field
   * is small enough that a height measured in it is true of the rest of it.
   * There used to be four patterns to choose between — first, centre, every
   * nth, n at random — which was four answers to a question that only ever
   * had one: how many.
   *
   * A point sits on a scan position, never beside one: focus is measured where
   * the run will image, and a height read off the gap between positions is a
   * real number and a worthless one. Which positions is `sharePoints` in
   * `shared/scanfields.js`: the field is cut into as many equal blocks as points
   * were asked for, and the position nearest the middle of each is taken.
   */
  const inScanOrder = (tiles) => [...tiles].sort((a, b) => (a.y - b.y) || (a.x - b.x));

  /** The positions of each scan field, in scan order, fields with any tiles. */
  /* The plan, in tilesets. Which positions make a tileset is the plan's own
     answer — a drawn one is a tileset, and the positions a grid laid in one
     area are that area's — because counting per field would be counting per
     frame, and a point asked for per tileset would land in every frame of the
     plate. */
  function tilesByField() {
    const byTileset = new Map();
    for (const t of state.plan) {
      const key = t.tileset ?? t.fieldId;
      if (!byTileset.has(key)) byTileset.set(key, []);
      byTileset.get(key).push(t);
    }
    return [...byTileset.values()].map(inScanOrder);
  }



  const perField = (f) => Math.max(1, Math.round(f.perField) || 1);

  function patternFocusPoints() {
    if (!state.plan.length) return [];
    const n = perField(state.focus);
    return tilesByField()
      .flatMap((held) => sharePoints(held, n))
      .map((t) => ({ x: t.x, y: t.y, z: null }));
  }

  /* The position under the pointer, if it is over one. A list of positions has
     no rows and columns to index into, so it is asked by distance. */
  function nearestPosition(x, y) {
    let best = null;
    state.plan.forEach((t, i) => {
      const half = t.frameUm / 2;
      if (x < t.x - half || x > t.x + half || y < t.y - half || y > t.y + half) return;
      const d = Math.hypot(t.x - x, t.y - y);
      if (!best || d < best.d) best = { t, i, d };
    });
    return best;
  }

  const FIELD_W = 148, FIELD_H = 108;
  const fieldCv = document.createElement("canvas");
  fieldCv.width = FIELD_W; fieldCv.height = FIELD_H;

  function paintSurface(surf, zLo, zHi, box) {
    const fctx = fieldCv.getContext("2d");
    const img = fctx.createImageData(FIELD_W, FIELD_H);
    const span = zHi - zLo || 1;
    let k = 0;
    for (let j = 0; j < FIELD_H; j++) {
      const y = box.yMin + ((j + 0.5) / FIELD_H) * (box.yMax - box.yMin);
      for (let i = 0; i < FIELD_W; i++) {
        const x = box.xMin + ((i + 0.5) / FIELD_W) * (box.xMax - box.xMin);
        const c = viridis((surfaceZ(surf, x, y) - zLo) / span);
        img.data[k++] = c[0]; img.data[k++] = c[1]; img.data[k++] = c[2]; img.data[k++] = 255;
      }
    }
    fctx.putImageData(img, 0, 0);
  }

  /**
   * The focus map, drawn onto the canvas rather than onto a map of its own.
   *
   * It is the same plate the rest of the run is looking at, so it is drawn in
   * the same place with the same projection: the carrier, the positions and
   * where the surface says each of them sits. A second map with a second
   * camera meant two answers to where a well is, and the operator holding both.
   */
  function drawFocusLayer(ctx, toScreen, scale, w, h) {
    const f = state.focus;
    const surf = focusSurface();
    const showSurface = surf && (f.strategy !== "plane" || f.applied);

    // predicted z range across the sample, for the ramp and its legend
    const box = planBox();
    let zLo = 0, zHi = 1;
    if (showSurface) {
      // a spline can bulge between its points, so sample the field rather than
      // trusting the corners the way a plane would let you
      zLo = Infinity; zHi = -Infinity;
      for (let j = 0; j <= 12; j++) {
        for (let i = 0; i <= 16; i++) {
          const z = surfaceZ(surf,
            box.xMin + (i / 16) * (box.xMax - box.xMin),
            box.yMin + (j / 12) * (box.yMax - box.yMin));
          if (z < zLo) zLo = z;
          if (z > zHi) zHi = z;
        }
      }
      if (zHi - zLo < 1) { zLo -= 0.5; zHi += 0.5; }
    }

    /* ---- the surface: fitted everywhere, shown only where it is used.
       The fit is global on purpose — every measured point informs it, and the
       ramp and its legend keep the range across the whole sample, so a tile's
       colour means the same thing wherever it sits. What gets painted is
       clipped to the positions, because the z it predicts between them is
       never going to be driven to: colouring the gaps states a focus for
       places this run does not visit. */
    if (showSurface && state.plan.length) {
      const [sx0, sy0] = toScreen(box.xMin, box.yMin);
      const sw = (box.xMax - box.xMin) * scale, sh = (box.yMax - box.yMin) * scale;
      paintSurface(surf, zLo, zHi, planBox());
      ctx.save();
      ctx.beginPath();
      for (const t of state.plan) {
        const [tx, ty] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
        const sz = t.frameUm * scale;
        ctx.rect(tx, ty, sz, sz);
      }
      ctx.clip();
      ctx.globalAlpha = 0.82;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(fieldCv, sx0, sy0, sw, sh);
      ctx.restore();
    }

    // ---- the positions, exactly as the software reports them
    /* The positions themselves, as the scan fields laid them out. This panel
       works on the list the run is going to drive, not on a grid of its own. */
    for (const t of state.plan) {
      const [tx, ty] = toScreen(t.x - t.frameUm / 2, t.y - t.frameUm / 2);
      const sz = t.frameUm * scale;
      ctx.strokeStyle = showSurface ? "rgba(255,255,255,0.30)" : css("--line-strong");
      ctx.lineWidth = 1;
      if (sz < 2) { ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(tx, ty, 2, 2); continue; }
      ctx.strokeRect(tx + 0.5, ty + 0.5, sz - 1, sz - 1);
    }

    if (f.strategy === "auto") {
      ctx.fillStyle = css("--ink-3");
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.textAlign = "center";
      for (const t of state.plan) {
        const [tx, ty] = toScreen(t.x, t.y);
        if (t.frameUm * scale > 34) ctx.fillText("AF", tx, ty + 4);
      }
      ctx.textAlign = "left";
    }

    /* ---- focus points, as a reticle rather than a dot.
       Open in the middle, because the middle is the thing being pointed at:
       a filled marker hides the one pixel of the map it is about. The height
       is not written beside it either — the map says it in colour and the list
       says it in numbers, and a label per point tiles over the field it is
       annotating once there are more than a handful. */
    if (f.strategy === "plane") {
      const R = 4.5, ARM_IN = 6.5, ARM_OUT = 11;
      const reticle = (x, y) => {
        ctx.beginPath();
        ctx.arc(x, y, R, 0, Math.PI * 2);
        ctx.moveTo(x - ARM_OUT, y); ctx.lineTo(x - ARM_IN, y);
        ctx.moveTo(x + ARM_IN, y); ctx.lineTo(x + ARM_OUT, y);
        ctx.moveTo(x, y - ARM_OUT); ctx.lineTo(x, y - ARM_IN);
        ctx.moveTo(x, y + ARM_IN); ctx.lineTo(x, y + ARM_OUT);
      };
      /* The rectangle being drawn, if one is: grey and dashed, because it is a
         question about what it covers rather than a thing on the plate. */
      if (focusMarquee) {
        const [mx0, my0] = toScreen(
          Math.min(focusMarquee.sx, focusMarquee.cx), Math.min(focusMarquee.sy, focusMarquee.cy),
        );
        const [mx1, my1] = toScreen(
          Math.max(focusMarquee.sx, focusMarquee.cx), Math.max(focusMarquee.sy, focusMarquee.cy),
        );
        ctx.save();
        ctx.setLineDash([4, 3]);
        ctx.lineWidth = 1;
        ctx.strokeStyle = css("--ink-3");
        ctx.fillStyle = "rgba(100, 116, 139, 0.12)";
        ctx.fillRect(mx0, my0, mx1 - mx0, my1 - my0);
        ctx.strokeRect(mx0, my0, mx1 - mx0, my1 - my0);
        ctx.restore();
      }

      f.points.forEach((p, i) => {
        const [x, y] = toScreen(p.x, p.y);
        /* Held, found by the pointer, or charted: all three are the same claim
           — this is one the next thing you do will happen to — so all three are
           said the same way, by drawing the mark heavier and ringing it. */
        const lit = picked().has(i) || i === f.hovered
          || (!picked().size && i === f.selected);
        /* One colour, whether the height has been read or not: the mark says
           where focus is measured, and the heat under it says what came back.
           Drawn over a dark halo, because viridis runs dark to bright and a
           mark that carried no contrast of its own disappeared into one end of
           it or the other. */
        reticle(x, y);
        ctx.lineWidth = lit ? 6 : 3.6; ctx.lineCap = "round";
        // a pale halo, because the mark itself is ink and the picture under
        // it can run dark
        ctx.strokeStyle = "rgba(255, 255, 255, 0.75)";
        ctx.stroke();
        reticle(x, y);
        ctx.lineWidth = lit ? 4 : 1.9;
        ctx.strokeStyle = css(lit ? "--mark-focus-lit" : "--mark-focus");
        ctx.stroke();
        ctx.lineCap = "butt";
      });
    }

    // ---- ramp legend
    if (showSurface) {
      // the legend sits ON the field, so it carries its own plate
      const bw = 132, bh = 9, bx = 20, by = h - 26;
      const padL = 8, top = by - 36;
      ctx.fillStyle = css("--screen");
      ctx.globalAlpha = 0.88;
      ctx.fillRect(bx - padL, top, bw + padL * 2, (by + bh + 7) - top);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = css("--line");
      ctx.lineWidth = 1;
      ctx.strokeRect(bx - padL + 0.5, top + 0.5, bw + padL * 2 - 1, (by + bh + 7) - top - 1);

      for (let i = 0; i < bw; i++) {
        ctx.fillStyle = zColor(i / bw);
        ctx.fillRect(bx + i, by, 1.4, bh);
      }
      ctx.strokeStyle = css("--line-strong");
      ctx.strokeRect(bx - 0.5, by - 0.5, bw + 1, bh + 1);

      ctx.fillStyle = css("--ink-3");
      ctx.font = '11.5px system-ui, sans-serif';
      ctx.fillText("predicted focus height", bx, top + 14);
      ctx.font = '11px ui-monospace, Consolas, monospace';
      ctx.fillStyle = css("--ink-2");
      ctx.fillText(`${zLo.toFixed(0)}`, bx, by - 5);
      ctx.textAlign = "right";
      ctx.fillText(`${zHi.toFixed(0)} µm`, bx + bw, by - 5);
      ctx.textAlign = "left";
    }

  }

  /* A focus point being dragged: which one, and whether the pointer has
     actually moved since it was taken hold of. A press that never moves is
     still a press, and means the other thing — take this point away. */
  let focusDrag = null;

  /* Shift and drag over the map picks out the points the rectangle covers, the
     same gesture that picks tilesets a step earlier. Held in screen pixels
     while it is being drawn, because that is where the rectangle is. */
  let focusMarquee = null;

  /** How small a rectangle is too small to have been meant — a shifted press. */
  const MARQUEE_MIN_PX = 4;

  /** Which points the picked set holds, kept as a set of places, not indexes. */
  const picked = () => state.focus.picked ?? (state.focus.picked = new Set());

  /** Where the pointer is, in the carrier's own coordinates. */
  function pointerInCarrier(px, py) {
    const [wx, wy] = toWorld(px, py);
    const [ox, oy] = carrierOriginUm();
    return [wx - ox, wy - oy];
  }

  /* How near a press has to be to take hold of a point: a few pixels, measured
     in what the picture is showing rather than in micrometres, so it is the
     same reach whatever the zoom. */
  const POINT_REACH_PX = 10;

  /** The focus point under the pointer, if the map is open to being changed. */
  function focusPointAt(px, py) {
    const f = state.focus;
    if (step(state.activeIdx).mode !== "focus") return -1;
    if (f.strategy !== "plane" || state.running) return -1;
    const [x, y] = pointerInCarrier(px, py);
    const reach = POINT_REACH_PX / view.scale;
    let at = -1, bestD = reach;
    f.points.forEach((p, i) => {
      const d = Math.hypot(p.x - x, p.y - y);
      if (d <= bestD) { at = i; bestD = d; }
    });
    return at;
  }

  /**
   * Taking hold of a point on the canvas, so it can be moved to another
   * position — dragged rather than deleted and placed again, because moving one
   * is what an operator means by "not there, there", and two gestures to say
   * one thing is one gesture too many.
   */
  function focusGrabbed(e) {
    const f = state.focus;
    if (step(state.activeIdx).mode !== "focus") return false;
    if (f.strategy !== "plane" || state.running) return false;

    const at = focusPointAt(e.offsetX, e.offsetY);
    if (at < 0) {
      /* Shift on empty ground draws the rectangle; a plain press there lets go
         of whatever was picked and falls through to the pan. */
      if (e.shiftKey) {
        const [x, y] = pointerInCarrier(e.offsetX, e.offsetY);
        focusMarquee = { sx: x, sy: y, cx: x, cy: y };
        return true;
      }
      if (picked().size) { picked().clear(); renderPointList(); drawStage(); }
      return false;
    }

    /* Shift on a point adds it to what is held, or takes it back out. Without
       shift, a press on a point that is not held picks that one alone — and a
       press on one that is held keeps the whole set, so a group can be dragged
       by any of its members. */
    if (e.shiftKey) {
      if (picked().has(at)) picked().delete(at); else picked().add(at);
    } else if (!picked().has(at)) {
      picked().clear();
      picked().add(at);
    }
    focusDrag = { at, moved: false, held: f.points.map((p) => ({ x: p.x, y: p.y })) };
    f.selected = at;
    renderPointList(); drawTrace(); drawStage();
    return true;
  }

  /** The rectangle being drawn, in the carrier's own coordinates. */
  function focusMarqueeTo(px, py) {
    const [x, y] = pointerInCarrier(px, py);
    focusMarquee = { ...focusMarquee, cx: x, cy: y };
    drawStage();
  }

  /* What the rectangle covered. A rectangle too small to have been meant is a
     shifted press that was about to add to what is held, so it leaves the set
     alone rather than emptying it. */
  function focusMarqueeTook(shift) {
    const m = focusMarquee;
    focusMarquee = null;
    if (!m) return;
    const box = {
      xMin: Math.min(m.sx, m.cx), yMin: Math.min(m.sy, m.cy),
      xMax: Math.max(m.sx, m.cx), yMax: Math.max(m.sy, m.cy),
    };
    if (Math.max(box.xMax - box.xMin, box.yMax - box.yMin) * view.scale < MARQUEE_MIN_PX) {
      drawStage();
      return;
    }
    const f = state.focus;
    if (!shift) picked().clear();
    f.points.forEach((p, i) => {
      if (p.x >= box.xMin && p.x <= box.xMax && p.y >= box.yMin && p.y <= box.yMax) {
        picked().add(i);
      }
    });
    if (picked().size) f.selected = Math.min(...picked());
    renderPointList(); drawTrace(); drawStage();
  }

  /* A point goes wherever the pointer goes: it is a place the stage is driven
     to, not a frame the run images, so nothing about the plan's grid has a
     say in where it may sit. */
  function focusDraggedTo(px, py) {
    if (!focusDrag) return;
    focusDrag.moved = true;
    const f = state.focus;
    const was = focusDrag.held[focusDrag.at];
    if (!was) return;
    const [x, y] = pointerInCarrier(px, py);
    /* Measured from where the points were when they were taken hold of, not
       from where they are now: a drag that added its own last step every time
       would run away from the pointer. Everything held moves together. */
    const dx = x - was.x, dy = y - was.y;
    const moving = picked().size ? picked() : new Set([focusDrag.at]);
    for (const i of moving) {
      const p = f.points[i], from = focusDrag.held[i];
      if (!p || !from) continue;
      /* Moved off what was read for it: the height belonged to where it was.
         A point that had one is kept in the list and greyed — the reading is
         stale, not missing — where one that never had a reading is not listed
         at all until the map is measured again. */
      f.points[i] = {
        ...p, x: from.x + dx, y: from.y + dy,
        z: null, residual: null, stale: p.z !== null || !!p.stale,
      };
    }
    refitSurface();
    drawStage(); renderPointList();
  }

  /**
   * What the pointer says on the focus step. Answered here rather than at the
   * moment of the press, so a crosshair armed from the panel says so before the
   * mouse is moved to find out — and so the one place that sets the canvas
   * cursor keeps setting it. The drawing calls this; nothing else assigns it.
   */
  function focusCursor() {
    if (step(state.activeIdx).mode !== "focus") return "";
    const f = state.focus;
    if (f.strategy !== "plane" || state.running) return "";
    if (f.hovered >= 0) return "grab";
    return f.placing ? "crosshair" : "";
  }

  /**
   * The pointer passing over the map: whether it has found a focus point, and
   * saying so on the canvas. Answered true when it has, so whatever else the
   * pointer would have reported is not asked.
   */
  function focusHovered(e) {
    const f = state.focus;
    if (step(state.activeIdx).mode !== "focus") return false;
    const at = focusPointAt(e.offsetX, e.offsetY);
    if (at === f.hovered) return at >= 0;
    f.hovered = at;
    drawStage();
    return at >= 0;
  }

  /* Placing a point is a press on the canvas with the crosshair armed. Armed
     rather than always live, because the same press pans the picture and a
     step where every press moves the plan is a step nobody can look around in.

     The point lands where the press landed, on ground that has none. */
  function focusPressed(px, py) {
    const f = state.focus;
    if (step(state.activeIdx).mode !== "focus") return false;
    if (!f.placing || f.strategy !== "plane" || state.running) return false;
    /* A press that landed on a point has already done its work: the press
       picked it, and picking is what a press on a thing means. It used to take
       the point away instead — the armed tool's other half — which made every
       point one careless press from gone and made choosing one on the map
       impossible while the tool was armed. Taking one away is the cross in the
       list, or Delete. */
    if (focusPointAt(px, py) >= 0) return true;

    const [x, y] = pointerInCarrier(px, py);
    f.points.push({ x, y, z: null });
    /* The one just put down is the one being worked on: it is what the hand is
       pointing at, and the next thing said — a drag, Delete — is about it
       rather than about whatever was picked before. */
    picked().clear();
    picked().add(f.points.length - 1);
    f.selected = f.points.length - 1;
    drawTrace();
    drawStage(); renderPointList(); renderActionBar();
    return true;
  }

  /* An anchor point lands where the press landed, once the button has armed
     it. Armed rather than always live, for the reason the focus crosshair is:
     the same press pans the picture. */
  function anchorPressed(px, py) {
    if (step(state.activeIdx).mode !== "carrier" || !state.anchoring) return false;
    const [x, y] = pointerInCarrier(px, py);
    state.anchors = [...state.anchors, { x, y }];
    state.anchoring = false;
    renderSide(true);
    drawStage();
    return true;
  }

  /* The same press during detection picks the test position: the channel's
     preview is one tile, and pointing at a position on the canvas is how it
     is chosen — the pager beside the preview is the other way. */
  function detectPressed(px, py) {
    if (step(state.activeIdx).mode !== "detect" || state.running) return false;
    const [wx, wy] = toWorld(px, py);
    const [ox, oy] = carrierOriginUm();
    const hit = nearestPosition(wx - ox, wy - oy);
    if (!hit) return false;
    const d = state.detect;
    if (d.tile !== hit.i) {
      d.tile = hit.i;
      d.tested = false;
    }
    renderDetectToolbar(); drawTilePreview(); drawStage(); renderActionBar();
    return true;
  }

  /* The rehearsed autofocus sweep — the two sharpness metrics, the debris a
     position may carry, every candidate peak and the one worth trusting —
     lives in `microscope/pretend-sample/sweep.js`, imported above. The trace
     below draws exactly the curve the unit tests measure. */

  /* The bar that makes the points and the list of the ones there are: one
     section, so they are drawn together and cannot disagree about how many. */
  function renderFocusBar() {
    if (!focusMounted()) return;
    const f = state.focus;
    /* Running freezes the box, a finished test does not: measuring a map is a
       reading of it, not a lock on it. Points can be added, moved and taken
       away afterwards, and the map measured again — what has no reading yet
       says so in the list until it does. */
    const frozen = !!state.running || f.strategy !== "plane";

    /* One number, always asked: how many points to lay in each scan field. */
    const count = el("fp-count");
    // never while it is being typed into, or a 1 on its way to 12 is corrected
    if (document.activeElement !== count) count.value = String(perField(f));
    count.disabled = frozen;

    el("fp-place").disabled = frozen || !state.plan.length;
    el("fp-clear").disabled = frozen || !f.points.length;
    /* The traces are what the run came back with, so the box that reads them
       is not there until it has. What the map came to is in the rows: a height
       for every point and how far each sits from the surface. */
    el("focus-traces").hidden = !f.applied;

    const pick = el("fp-pick");
    pick.disabled = frozen || !state.plan.length;
    pick.classList.toggle("on", !!f.placing && !frozen);
    // the cursor says what the next press will do, the way it does when a
    // scan field is being drawn — worked out in one place, and set there
    stageCv.style.cursor = focusCursor();
  }

  /* The focus controls are in the document only while their step is standing —
     the channel takes them in and gives them back. Anything that writes into
     them has to ask first, or a redraw from somewhere else reaches for an
     element that is not there. */
  const focusMounted = () => focusControls.isConnected;

  function renderPointList() {
    if (!focusMounted()) return;
    const f = state.focus;
    const host = el("point-list");
    host.textContent = "";
    renderFocusBar();

    if (f.strategy !== "plane") {
      const d = document.createElement("div");
      d.className = "none";
      d.textContent = f.strategy === "auto"
        ? "Per-tile autofocus measures every position — no points to place."
        : f.strategy === "fixed"
          ? "A fixed height needs no measured points."
          : "The stored surface already carries its points.";
      host.append(d);
      return;
    }
    if (!f.points.length) {
      const d = document.createElement("div");
      d.className = "none";
      d.textContent = "Click the position map to place focus points. Three or more spread-out points make a plane.";
      host.append(d);
      return;
    }

    f.points.forEach((p, i) => {
      /* Only what has a trace to inspect, or had one: a point put down after
         the map was measured has nothing to show and waits on the map until
         the next test gives it a reading. */
      if (p.z === null && !p.stale) return;

      /* A row, not a button: it holds one — the row itself picks the point —
         and a cross of its own for throwing it away. A button inside a button
         is not a thing a browser will draw. */
      const row = document.createElement("div");
      row.className = p.stale ? "point-row stale" : "point-row";
      /* Held, or the one whose trace is charted: the list marks what the
         canvas marks, so a rectangle drawn over the map is answered here. */
      row.setAttribute("aria-current",
        String(picked().has(i) || (!picked().size && i === f.selected)));
      const suspect = p.onNarrow || (f.worst === i && Math.abs(p.residual || 0) > 3);
      const pick = document.createElement("button");
      pick.className = "point-pick"; pick.type = "button";
      pick.innerHTML =
        `<span class="idx">${i + 1}</span>` +
        `<span>${(p.x / 1000).toFixed(2)}, ${(p.y / 1000).toFixed(2)} mm</span>` +
        (p.residual === undefined || p.residual === null ? ""
          : `<span class="res"${suspect ? ' style="color:var(--bad)"' : ""}>` +
            `${p.residual >= 0 ? "+" : ""}${p.residual.toFixed(1)}</span>`) +
        `<span class="z${p.z === null ? " pending" : ""}"` +
        `${suspect && !p.manual ? ' style="color:var(--bad)"' : ""}>` +
        `${p.z === null ? "—" : (p.manual ? "✎ " : suspect ? "⚠ " : "") + p.z.toFixed(1) + " µm"}</span>`;
      /* A moved point has no trace to show — what was read was read of where it
         used to be — so its row says so by being unpressable until the map is
         measured again. */
      pick.disabled = !!p.stale;
      pick.addEventListener("click", () => {
        f.selected = i;
        renderPointList(); drawTrace(); drawStage();
      });

      const drop = document.createElement("button");
      drop.className = "rec-drop point-drop"; drop.type = "button";
      drop.textContent = "✕";
      drop.title = "stop measuring here";
      drop.disabled = !!state.running;
      drop.addEventListener("click", () => {
        f.points.splice(i, 1);
        f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
        refitSurface();
        renderPointList(); drawTrace(); drawStage(); renderActionBar();
      });

      row.append(pick, drop);
      host.append(row);
    });
  }

  const traceCv = el("trace-canvas");

  function drawTrace() {
    if (!focusMounted()) return;
    const f = state.focus;
    /* A point put down after the map was measured has no reading yet, and a
       trace is the reading: there is nothing to draw for it until the map is
       measured again. */
    const has = f.strategy === "plane" && f.applied
      && f.points.length > f.selected && f.points[f.selected]?.z !== null;
    el("trace-empty").classList.toggle("hidden", has);
    /* Which point is being read is said by the list, where the row is marked,
       and by the map, where the mark is drawn heavier. The heading says what
       the box is, once. */
    if (!has || !sizeCanvas(traceCv)) return;

    const ctx = traceCv.getContext("2d");
    const w = traceCv.cssW, h = traceCv.cssH;
    ctx.clearRect(0, 0, w, h);
    // the plot stands on the same white the box does: a tinted panel inside a
    // white card read as a second surface for one of the three parts
    ctx.fillStyle = css("--screen");
    ctx.fillRect(0, 0, w, h);

    /* Both metrics on one plot. They score the same stack on different
       scales, so each is normalised to its own maximum — the shapes are the
       comparison, not the absolute numbers. */
    const traces = f.points[f.selected]?.traces;
    if (!traces) return;
    const curves = METRIC_KEYS.map((key) => {
      const sw = traces[key];
      const peak = Math.max(...sw.samples.map((q) => q.s)) || 1;
      return { key, sw, norm: sw.samples.map((q) => ({ z: q.z, s: q.s / peak })) };
    });
    const deciding = curves.find((c) => c.key === f.metric) || curves[0];
    const t = deciding.sw;

    const P = { l: 40, r: 14, t: 16, b: 30 };
    const zs = t.samples.map((p) => p.z);
    const zLo = Math.min(...zs), zHi = Math.max(...zs);
    const sHi = 1.16;
    const X = (z) => P.l + ((z - zLo) / (zHi - zLo)) * (w - P.l - P.r);
    const Y = (s) => (h - P.b) - (s / sHi) * (h - P.t - P.b);
    const decidingPeak = Math.max(...t.samples.map((q) => q.s)) || 1;

    // recessive frame
    ctx.strokeStyle = css("--line");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(P.l, P.t); ctx.lineTo(P.l, h - P.b); ctx.lineTo(w - P.r, h - P.b);
    ctx.stroke();

    ctx.fillStyle = css("--ink-3");
    ctx.font = '10.5px ui-monospace, Consolas, monospace';
    ctx.textAlign = "center";
    ctx.fillText(`${zLo.toFixed(0)}`, X(zLo) + 10, h - P.b + 15);
    ctx.fillText(`${zHi.toFixed(0)} µm`, X(zHi) - 16, h - P.b + 15);
    ctx.save();
    ctx.translate(13, (P.t + h - P.b) / 2); ctx.rotate(-Math.PI / 2);
    ctx.font = '11px system-ui, sans-serif';
    ctx.fillText("sharpness", 0, 0);
    ctx.restore();
    ctx.textAlign = "left";

    // the comparison curve first, so the deciding one reads on top
    legendHits = [];
    let lx = P.l + 8;
    for (const c of curves) {
      const isDeciding = c === deciding;
      ctx.save();
      ctx.strokeStyle = css(METRICS[c.key].token);
      ctx.lineWidth = isDeciding ? 2 : 1.5;
      ctx.globalAlpha = isDeciding ? 1 : 0.55;
      if (!isDeciding) ctx.setLineDash([4, 3]);
      ctx.beginPath();
      c.norm.forEach((q, i) => { const x = X(q.z), y = Y(q.s); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      ctx.restore();

      // legend doubles as the control: click a metric to let it decide
      ctx.save();
      ctx.strokeStyle = css(METRICS[c.key].token);
      ctx.lineWidth = isDeciding ? 2.5 : 1.5;
      if (!isDeciding) ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(lx, P.t + 3); ctx.lineTo(lx + 16, P.t + 3); ctx.stroke();
      ctx.restore();
      ctx.font = `${isDeciding ? "600 " : ""}11px system-ui, sans-serif`;
      ctx.fillStyle = isDeciding ? css("--ink") : css("--ink-3");
      const label = METRICS[c.key].short + (isDeciding ? " · deciding" : "");
      ctx.fillText(label, lx + 22, P.t + 7);
      const wLab = 22 + ctx.measureText(label).width;
      legendHits.push({ key: c.key, x0: lx - 4, x1: lx + wLab + 4, y0: P.t - 6, y1: P.t + 13 });
      lx += wLab + 18;
    }

    // everything below is drawn against the deciding curve, so its raw scores
    // are normalised the same way the curve was
    const N = (s) => s / decidingPeak;
    const p = f.points[f.selected];
    // sweep() is deterministic, so the recomputed candidate at the recorded
    // height is the same peak the rule picked when the strategy ran
    const chosen = t.candidates.find((c) => Math.abs(c.z - p.zAuto) < 1e-6) || t.candidates[0];

    // every measured z
    for (const q of t.samples) {
      ctx.beginPath();
      ctx.arc(X(q.z), Y(N(q.s)), 2.2, 0, Math.PI * 2);
      ctx.fillStyle = css("--mark-context");
      ctx.fill();
    }

    // candidate peaks the rule turned down — a narrow one is almost always a
    // speck of debris, and this is where it becomes visible instead of silent
    for (const c of t.candidates) {
      if (c === chosen || Math.abs(c.z - chosen.z) < 1e-6) continue;
      ctx.beginPath();
      ctx.arc(X(c.z), Y(N(c.s)), 4, 0, Math.PI * 2);
      ctx.strokeStyle = c.narrow ? css("--bad") : css("--ink-3");
      ctx.lineWidth = 1.6;
      ctx.stroke();
      if (c.narrow) {
        ctx.fillStyle = css("--bad");
        ctx.font = '10px ui-monospace, Consolas, monospace';
        const lbl = `${c.width.toFixed(1)} µm wide`;
        const lw = ctx.measureText(lbl).width;
        ctx.fillText(lbl, Math.max(P.l, Math.min(X(c.z) - lw / 2, w - P.r - lw)), Y(N(c.s)) - 8);
      }
    }

    // the parabola through the chosen peak's three samples
    if (chosen.used && chosen.used.length === 3 && chosen.used[0] !== chosen.used[1]) {
      ctx.save();
      ctx.strokeStyle = "#16a34a";
      ctx.lineWidth = 1.6;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      const [q0, q1, q2] = chosen.used;
      for (let i = 0; i <= 40; i++) {
        const z = q0.z + ((q2.z - q0.z) * i) / 40;
        const l0 = ((z - q1.z) * (z - q2.z)) / ((q0.z - q1.z) * (q0.z - q2.z));
        const l1 = ((z - q0.z) * (z - q2.z)) / ((q1.z - q0.z) * (q1.z - q2.z));
        const l2 = ((z - q0.z) * (z - q1.z)) / ((q2.z - q0.z) * (q2.z - q1.z));
        const s = q0.s * l0 + q1.s * l1 + q2.s * l2;
        const x = X(z), y = Y(N(s));
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
      ctx.restore();
      for (const q of chosen.used) {
        ctx.beginPath(); ctx.arc(X(q.z), Y(N(q.s)), 3.6, 0, Math.PI * 2);
        ctx.fillStyle = "#0284c7"; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = css("--surface-2"); ctx.stroke();
      }
    }

    // where the metric put the peak — kept visible as a reference once the
    // operator has dragged the chosen height somewhere else
    if (p.manual) {
      ctx.save();
      ctx.globalAlpha = 0.45;
      ctx.strokeStyle = "#16a34a"; ctx.lineWidth = 1.5;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(X(p.zAuto), P.t); ctx.lineTo(X(p.zAuto), h - P.b);
      ctx.stroke();
      ctx.restore();
    }

    // the draggable height
    const zSel = p.z;
    const sSel = N(scoreAt(t.samples, zSel));
    const xSel = X(zSel);
    // a peak too narrow to be tissue never gets to look like a confident answer
    const pickColour = p.manual ? css("--accent") : (p.onNarrow ? css("--bad") : "#16a34a");
    ctx.strokeStyle = pickColour;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xSel, P.t); ctx.lineTo(xSel, h - P.b);
    ctx.stroke();

    // a grab handle, so it reads as draggable
    ctx.fillStyle = pickColour;
    ctx.beginPath();
    ctx.moveTo(xSel - 5, P.t); ctx.lineTo(xSel + 5, P.t); ctx.lineTo(xSel, P.t + 7);
    ctx.closePath(); ctx.fill();

    ctx.beginPath(); ctx.arc(xSel, Y(sSel), 4.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = 1.8; ctx.strokeStyle = css("--surface-2"); ctx.stroke();

    const lab = p.onNarrow && !p.manual
      ? `${zSel.toFixed(1)} µm · ${chosen.width.toFixed(1)} µm wide`
      : `${zSel.toFixed(1)} µm`;
    ctx.font = '11px ui-monospace, Consolas, monospace';
    const tw = ctx.measureText(lab).width;
    ctx.fillStyle = p.manual ? css("--accent-deep") : pickColour;
    ctx.fillText(lab, Math.min(xSel + 7, w - P.r - tw), Y(sSel) - 7);

    traceGeom = { zLo, zHi, P, w, h, samples: t.samples };
    drawZPreview(p, f.selected);
  }

  let traceGeom = null;
  let legendHits = [];

  /* ---- the image at whatever height the line is sitting on ---------------
     Defocus is the whole point of the preview, so it is drawn once sharp and
     blurred by how far the chosen height sits from this point's true focus. */
  function drawZPreview(point, idx) {
    const cv = el("zpreview-canvas");
    const ctx = cv.getContext("2d");
    const S = cv.width;
    const trueFocus = point.focusZ ?? 0;
    const defocus = Math.abs(point.z - trueFocus);
    const blur = Math.min(11, defocus * 0.42);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, S, S);
    ctx.fillStyle = "#05090e";
    ctx.fillRect(0, 0, S, S);

    const r = makeRng(4400 + idx * 131);
    const nuclei = Array.from({ length: 14 }, () => ({
      x: S * (0.08 + 0.84 * r()), y: S * (0.08 + 0.84 * r()),
      rad: S * (0.045 + 0.055 * r()), amp: 0.5 + 0.5 * r(),
    }));

    if ("filter" in ctx) ctx.filter = blur > 0.25 ? `blur(${blur.toFixed(2)}px)` : "none";
    // out-of-focus light spreads out instead of vanishing
    const spread = 1 + blur * 0.16;
    for (const n of nuclei) {
      const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.rad * spread);
      g.addColorStop(0, `rgba(34,211,238,${(0.85 * n.amp) / spread})`);
      g.addColorStop(0.6, `rgba(34,211,238,${(0.3 * n.amp) / spread})`);
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.rad * spread, 0, Math.PI * 2); ctx.fill();
    }
    // the speck of debris, if this position has one — it comes into focus in a
    // plane of its own, which is exactly what fools the metric
    const speck = point.speck;
    if (speck) {
      const speckZ = trueFocus + METRICS[state.focus.metric].bias + speck.offset;
      const speckBlur = Math.min(11, Math.abs(point.z - speckZ) * 0.55);
      ctx.filter = speckBlur > 0.25 ? `blur(${speckBlur.toFixed(2)}px)` : "none";
      const sr = makeRng(9100 + idx * 17);
      const cx = S * (0.3 + 0.4 * sr()), cy = S * (0.3 + 0.4 * sr());
      const sSpread = 1 + speckBlur * 0.5;
      ctx.fillStyle = `rgba(226,232,240,${Math.min(0.95, 0.95 / sSpread)})`;
      ctx.beginPath();
      ctx.ellipse(cx, cy, S * 0.035 * sSpread, S * 0.022 * sSpread, sr() * 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.filter = "none";
    }

    el("zpreview-z").textContent = point.z === null ? "—" : `${point.z.toFixed(1)} µm`;
    const st = el("zpreview-state");
    st.classList.toggle("manual", !!point.manual);
    if (point.manual) {
      const d = point.z - point.zAuto;
      st.textContent = `moved by hand · ${d >= 0 ? "+" : ""}${d.toFixed(1)} µm off the pick`;
    } else if (point.onNarrow) {
      st.textContent = "locked onto a narrow peak";
      st.classList.add("manual");
    } else {
      st.textContent = defocus < 2 ? "cells in focus" : "off the tissue plane";
    }
  }

  /* ---- drag the height, and watch the image follow -----------------------
     The whole reason the preview is here: a peak the metric loved can be a
     speck, and the operator decides by looking rather than by trusting. */
  let scrubbing = false;

  function scrubTo(clientOffsetX) {
    const f = state.focus;
    if (!traceGeom || f.strategy !== "plane" || !f.applied) return;
    const p = f.points[f.selected];
    const { zLo, zHi, P, w } = traceGeom;
    const t = Math.max(0, Math.min(1, (clientOffsetX - P.l) / (w - P.l - P.r)));
    p.z = zLo + t * (zHi - zLo);
    p.manual = Math.abs(p.z - p.zAuto) > 0.05;
    refitSurface();
    drawTrace(); renderPointList(); drawStage();
  }

  traceCv.addEventListener("pointerdown", (e) => {
    const f = state.focus;
    if (f.strategy !== "plane" || !f.applied) return;
    // the legend is the metric control — no separate row of buttons for it
    const hit = legendHits.find((g) =>
      e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
    if (hit) {
      if (hit.key !== f.metric) {
        f.metric = hit.key;
        remeasure().then(() => {
          drawTrace(); renderPointList(); drawStage(); renderActionBar();
        });
      }
      return;
    }
    scrubbing = true;
    traceCv.setPointerCapture(e.pointerId);
    scrubTo(e.offsetX);
  });

  traceCv.addEventListener("pointermove", (e) => {
    if (scrubbing) return;
    const over = legendHits.some((g) =>
      e.offsetX >= g.x0 && e.offsetX <= g.x1 && e.offsetY >= g.y0 && e.offsetY <= g.y1);
    traceCv.style.cursor = over ? "pointer" : "ew-resize";
  });
  traceCv.addEventListener("pointermove", (e) => { if (scrubbing) scrubTo(e.offsetX); });
  traceCv.addEventListener("pointerup", (e) => {
    scrubbing = false;
    traceCv.releasePointerCapture?.(e.pointerId);
  });
  traceCv.addEventListener("pointercancel", () => { scrubbing = false; });

  // keyboard equivalent, because a drag-only control is not operable by everyone
  traceCv.tabIndex = 0;
  traceCv.setAttribute("role", "slider");
  traceCv.setAttribute("aria-label", "focus height for the selected point");
  traceCv.addEventListener("keydown", (e) => {
    const f = state.focus;
    if (f.strategy !== "plane" || !f.applied) return;
    const nudge = { ArrowLeft: -0.5, ArrowRight: 0.5, PageDown: -3, PageUp: 3 }[e.key];
    if (nudge === undefined) return;
    e.preventDefault();
    const p = f.points[f.selected];
    p.z += nudge * (e.shiftKey ? 4 : 1);
    p.manual = Math.abs(p.z - p.zAuto) > 0.05;
    refitSurface();
    drawTrace(); renderPointList(); drawStage();
  });

  // ---- laying points by the number, rather than clicking positions one by one
  el("fp-count").addEventListener("input", () => {
    const v = parseInt(el("fp-count").value, 10);
    if (Number.isNaN(v)) return;
    state.focus.perField = Math.min(99, Math.max(1, v));
    renderFocusBar();
  });
  el("fp-count").addEventListener("blur", () => { renderFocusBar(); });
  el("fp-pick").addEventListener("click", () => {
    const f = state.focus;
    f.placing = !f.placing;
    renderPointList();
  });
  el("fp-place").addEventListener("click", () => {
    const f = state.focus;
    /* A fresh set, not more on top: the points are settled against each other
       — every one stands for its own share of the tileset — so laying a second
       set through the first would leave neither arrangement true. What is kept
       by hand is kept by not pressing this. */
    f.points = patternFocusPoints();
    picked().clear();
    f.selected = 0;
    drawStage(); renderPointList(); drawTrace(); renderActionBar();
  });
  /* Delete takes away whichever point is chosen — the one the canvas is
     drawing heavier and the list has highlighted. The same key does the same
     thing to a scan field one step earlier, and a map is edited the way a plan
     is. */
  window.addEventListener("keydown", (e) => {
    if (step(state.activeIdx).mode !== "focus" || state.running) return;
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    const f = state.focus;
    if (f.strategy !== "plane" || !f.points.length) return;
    e.preventDefault();
    /* Everything held, or the charted one when nothing is: the same key, and
       the same meaning, whether one point was picked or a rectangle full. */
    const going = picked().size ? picked() : new Set([f.selected]);
    f.points = f.points.filter((_, i) => !going.has(i));
    picked().clear();
    f.selected = Math.max(0, Math.min(f.selected, f.points.length - 1));
    f.hovered = -1;
    refitSurface();
    drawStage(); renderPointList(); drawTrace(); renderActionBar();
  });

  el("fp-clear").addEventListener("click", () => {
    state.focus.points = [];
    picked().clear();
    drawStage(); renderPointList(); drawTrace(); renderActionBar();
  });

  /* Measure every placed point with the current metric, then fit the plane.
     The backend drives to each point and focuses there; what comes back is
     the height, the traces the chart draws, and the speck the preview shows.
     A height the operator dragged by hand survives a change of metric. */
  async function remeasure() {
    const f = state.focus;
    const { points } = await backend.measureFocus(f.points, {
      metric: f.metric,
      extent: carrierSpan(),
    });
    f.points = points;
    refitSurface();
  }

  function refitSurface() {
    const f = state.focus;
    f.surface = fitSurface(f.points);
    const errs = residualsUm(f.surface, f.points);
    f.points.forEach((p, i) => { p.residual = errs[i]; });
    f.residual = Math.sqrt(errs.reduce((a, e) => a + e * e, 0) / Math.max(1, errs.length));
    let worst = -1;
    errs.forEach((e, i) => { if (worst < 0 || Math.abs(e) > Math.abs(errs[worst])) worst = i; });
    f.worst = errs.length ? worst : -1;
  }

  /* ============================================================
     detection — tuned on one tile, then run across all of them
     ============================================================ */
  const tileCv = el("tile-canvas");

  const ALGOS = {
    cellpose: {
      label: "Cellpose",
      blurb: "Diameter is the size it looks for; cell probability is how sure it has to be.",
    },
    threshold: {
      label: "Threshold",
      blurb: "Everything brighter than the level, larger than the minimum area.",
    },
  };

  // the same rule the tile test and the full run both use
  function detects(c) {
    const d = state.detect;
    const dia = 2 * c.r;
    if (d.algo === "cellpose") {
      // a diameter well off the truth costs you objects at both ends, which is
      // the whole reason to try it on a tile before running the sample
      return dia > d.diameter * 0.70 && dia < d.diameter * 1.55
        && c.intensity > 0.36 + d.cellprob * 0.05;
    }
    return c.intensity >= d.thresh && c.area >= d.minArea;
  }

  // golden-angle hues, so neighbouring labels never share a colour
  const labelColour = (id, a = 1) => `hsla(${(id * 137.508) % 360}, 68%, 58%, ${a})`;

  function drawTilePreview() {
    if (!sizeCanvas(tileCv)) return;
    const ctx = tileCv.getContext("2d");
    const w = tileCv.cssW, h = tileCv.cssH;
    const d = state.detect;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--surface-3");
    ctx.fillRect(0, 0, w, h);

    const tile = state.plan[d.tile];
    if (!tile) return;
    const frame = tile.frameUm;
    const pad = 18;
    const s = Math.min((w - 2 * pad) / frame, (h - 2 * pad) / frame);
    const ox = (w - frame * s) / 2, oy = (h - frame * s) / 2;
    const X = (x) => ox + (x - (tile.x - frame / 2)) * s;
    const Y = (y) => oy + (y - (tile.y - frame / 2)) * s;

    ctx.save();
    ctx.beginPath();
    ctx.rect(ox, oy, frame * s, frame * s);
    ctx.clip();

    ctx.fillStyle = "#05090e";
    ctx.fillRect(ox, oy, frame * s, frame * s);
    {
      // the tissue this tile happens to sit on, at the brightness it was found
      const dens = density(tile.x, tile.y);
      const cx = X(tile.x), cy = Y(tile.y), rr = frame * 0.8 * s;
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rr);
      g.addColorStop(0, `rgba(34,211,238,${0.30 * dens})`);
      g.addColorStop(0.6, `rgba(34,211,238,${0.10 * dens})`);
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx, cy, rr, 0, Math.PI * 2); ctx.fill();
    }

    // objects are drawn larger than life: at 5x a cell is a couple of pixels,
    // and the point of this view is to judge the labels
    const inTile = cellsInTile(d.tile);
    for (const c of inTile) {
      const rr = Math.max(5, c.r * s * 2.4);
      const found = d.tested && detects(c);
      ctx.beginPath(); ctx.arc(X(c.x), Y(c.y), rr, 0, Math.PI * 2);
      if (found) {
        ctx.fillStyle = labelColour(c.id, 0.55);
        ctx.fill();
        ctx.lineWidth = 1.6; ctx.strokeStyle = labelColour(c.id, 1); ctx.stroke();
      } else {
        // rejected objects stay visible — what a setting threw away matters
        ctx.fillStyle = `rgba(226,232,240,${d.tested ? 0.26 : 0.62})`;
        ctx.fill();
      }
    }
    ctx.restore();

    ctx.strokeStyle = css("--line-strong");
    ctx.lineWidth = 1;
    ctx.strokeRect(ox + 0.5, oy + 0.5, frame * s - 1, frame * s - 1);
    drawScaleBar(ctx, w, h, s);
  }

  /* Like the focus controls, these are in the document only while their step
     is standing — the channel takes them in and gives them back. */
  const detectMounted = () => detectControls.isConnected;

  function renderDetectToolbar() {
    if (!detectMounted()) return;
    const d = state.detect;
    for (const b of el("detect-algo").querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.algo === d.algo));
    }
    el("tile-label").textContent = `${d.tile + 1} / ${state.plan.length}`;

    const host = el("detect-params");
    host.textContent = "";
    const num = (label, key, min, max, step, unit) => {
      const wrap = document.createElement("div");
      wrap.className = "param";
      wrap.innerHTML = `<label>${label}</label><input type="number" min="${min}" max="${max}" step="${step}">` +
        (unit ? `<span class="hint">${unit}</span>` : "");
      const inp = wrap.querySelector("input");
      inp.value = d[key];
      inp.addEventListener("input", () => {
        d[key] = Number(inp.value);
        d.tested = false;
        drawTilePreview(); renderDetectToolbar(); renderActionBar();
      });
      host.append(wrap);
    };

    if (d.algo === "cellpose") {
      num("Diameter", "diameter", 4, 60, 1, "µm");
      num("Cell prob.", "cellprob", -6, 6, 0.5, "");
    } else {
      num("Level", "thresh", 0, 1, 0.05, "");
      num("Min area", "minArea", 20, 400, 10, "µm²");
    }

    const test = document.createElement("button");
    test.className = "ghost"; test.type = "button";
    test.textContent = "Test on this tile";
    test.addEventListener("click", () => {
      d.tested = true;
      drawTilePreview(); renderDetectToolbar(); renderActionBar();
    });
    host.append(test);

    const out = el("detect-readout");
    if (d.tested) {
      const inTile = cellsInTile(d.tile);
      const found = inTile.filter(detects).length;
      out.textContent = `${found} of ${inTile.length} objects at position ${d.tile + 1}`;
    } else {
      out.textContent = ALGOS[d.algo].blurb;
    }
  }

  el("detect-algo").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-algo]");
    if (!b || state.running) return;
    state.detect.algo = b.dataset.algo;
    state.detect.tested = false;
    renderDetectToolbar(); drawTilePreview(); renderActionBar();
  });

  for (const [id, step] of [["tile-prev", -1], ["tile-next", 1]]) {
    el(id).addEventListener("click", () => {
      const d = state.detect;
      const total = state.plan.length || 1;
      d.tile = (d.tile + step + total) % total;
      d.tested = false;
      renderDetectToolbar(); drawTilePreview(); renderActionBar();
    });
  }

  /* ============================================================
     the analysis panel — a scatter you gate on
     ============================================================ */
  const scatterCv = el("scatter-canvas");
  const scatterTip = el("scatter-tip");
  const PAD = { l: 62, r: 18, t: 18, b: 46 };

  const sx = (area, w) => PAD.l + ((area - AREA_LO) / (AREA_HI - AREA_LO)) * (w - PAD.l - PAD.r);
  const sy = (inten, h) => (h - PAD.b) - inten * (h - PAD.t - PAD.b);
  const invX = (px, w) => AREA_LO + ((px - PAD.l) / (w - PAD.l - PAD.r)) * (AREA_HI - AREA_LO);
  const invY = (py, h) => ((h - PAD.b) - py) / (h - PAD.t - PAD.b);

  function drawScatter() {
    if (!sizeCanvas(scatterCv)) return;
    const ctx = scatterCv.getContext("2d");
    const w = scatterCv.cssW, h = scatterCv.cssH;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = css("--screen");
    ctx.fillRect(0, 0, w, h);

    // recessive grid
    ctx.strokeStyle = css("--line");
    ctx.lineWidth = 1;
    ctx.fillStyle = css("--ink-3");
    ctx.font = '11.5px ui-monospace, Consolas, monospace';
    ctx.textAlign = "right";
    for (let v = 0; v <= 1.0001; v += 0.25) {
      const y = sy(v, h);
      ctx.beginPath(); ctx.moveTo(PAD.l, y); ctx.lineTo(w - PAD.r, y); ctx.stroke();
      ctx.fillText(v.toFixed(2), PAD.l - 9, y + 4);
    }
    ctx.textAlign = "center";
    for (let a = 100; a <= AREA_HI; a += 100) {
      const x = sx(a, w);
      ctx.beginPath(); ctx.moveTo(x, PAD.t); ctx.lineTo(x, h - PAD.b); ctx.stroke();
      ctx.fillText(String(a), x, h - PAD.b + 18);
    }

    // axis titles
    ctx.fillStyle = css("--ink-2");
    ctx.font = '12.5px system-ui, sans-serif';
    ctx.fillText("cell area (µm²)", (PAD.l + w - PAD.r) / 2, h - 12);
    ctx.save();
    ctx.translate(16, (PAD.t + h - PAD.b) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("mean intensity · ch2", 0, 0);
    ctx.restore();

    // context points
    ctx.fillStyle = css("--mark-context");
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    for (const c of sample.cells) {
      if (!state.detected.has(c.id) || state.gated.has(c.id)) continue;
      const x = sx(c.area, w), y = sy(c.intensity, h);
      ctx.moveTo(x + 2, y); ctx.arc(x, y, 2, 0, Math.PI * 2);
    }
    ctx.fill();
    ctx.globalAlpha = 1;

    // gated points — larger and ringed as well as coloured
    const acquired = new Set(state.acquired);
    for (const c of sample.cells) {
      if (!state.gated.has(c.id)) continue;
      const x = sx(c.area, w), y = sy(c.intensity, h);
      const isAcq = acquired.has(c.id);
      ctx.beginPath(); ctx.arc(x, y, isAcq ? 4.6 : 3.4, 0, Math.PI * 2);
      ctx.fillStyle = isAcq ? "#16a34a" : "#0284c7";
      ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = css("--screen"); ctx.stroke();
    }

    // the gate itself
    if (state.gate) {
      const g = state.gate;
      const x0 = sx(g.aLo, w), x1 = sx(g.aHi, w);
      const y0 = sy(g.iHi, h), y1 = sy(g.iLo, h);
      ctx.strokeStyle = "#0284c7"; ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
      ctx.setLineDash([]);
    }
    if (drag.active) {
      ctx.strokeStyle = css("--accent"); ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(Math.min(drag.x0, drag.x1), Math.min(drag.y0, drag.y1),
        Math.abs(drag.x1 - drag.x0), Math.abs(drag.y1 - drag.y0));
      ctx.setLineDash([]);
    }
  }

  const drag = { active: false, x0: 0, y0: 0, x1: 0, y1: 0 };

  scatterCv.addEventListener("pointerdown", (e) => {
    if (!state.cellsShown) return;
    drag.active = true;
    drag.x0 = drag.x1 = e.offsetX; drag.y0 = drag.y1 = e.offsetY;
    scatterCv.setPointerCapture(e.pointerId);
  });

  scatterCv.addEventListener("pointermove", (e) => {
    const w = scatterCv.cssW, h = scatterCv.cssH;
    if (drag.active) {
      drag.x1 = e.offsetX; drag.y1 = e.offsetY;
      drawScatter();
      return;
    }
    if (!state.cellsShown) return;
    let hit = null, best = 9;
    for (const c of sample.cells) {
      if (!state.detected.has(c.id)) continue;
      const d = Math.hypot(sx(c.area, w) - e.offsetX, sy(c.intensity, h) - e.offsetY);
      if (d < best) { best = d; hit = c; }
    }
    if (hit) {
      scatterTip.classList.add("on");
      scatterTip.innerHTML =
        `<b>cell</b> ${hit.id}<br><b>area</b> ${hit.area.toFixed(0)} µm²<br>` +
        `<b>int</b> ${hit.intensity.toFixed(2)}<br><b>at</b> ${(hit.x / 1000).toFixed(2)}, ${(hit.y / 1000).toFixed(2)} mm`;
      scatterTip.style.left = `${Math.min(e.offsetX + 14, w - 160)}px`;
      scatterTip.style.top = `${Math.max(6, e.offsetY - 68)}px`;
    } else {
      scatterTip.classList.remove("on");
    }
  });

  scatterCv.addEventListener("pointerup", (e) => {
    if (!drag.active) return;
    drag.active = false;
    scatterCv.releasePointerCapture?.(e.pointerId);
    const w = scatterCv.cssW, h = scatterCv.cssH;
    if (Math.abs(drag.x1 - drag.x0) < 6 || Math.abs(drag.y1 - drag.y0) < 6) { drawScatter(); return; }
    const g = {
      aLo: invX(Math.min(drag.x0, drag.x1), w), aHi: invX(Math.max(drag.x0, drag.x1), w),
      iLo: invY(Math.max(drag.y0, drag.y1), h), iHi: invY(Math.min(drag.y0, drag.y1), h),
    };
    applyGate(g);
  });

  scatterCv.addEventListener("pointerleave", () => scatterTip.classList.remove("on"));

  /* Like the other channels, these controls leave the document with the step.
     The readout is rendered from the run's state rather than written at the
     moment of gating, so mounting again always shows what is true now. */
  const analysisMounted = () => analysisControls.isConnected;

  function renderGateReadout() {
    if (!analysisMounted()) return;
    const g = state.gate;
    el("gate-readout").textContent = g
      ? `${state.gated.size} of ${state.detected.size} detected gated · area ${g.aLo.toFixed(0)}–${g.aHi.toFixed(0)} µm² · int ${g.iLo.toFixed(2)}–${g.iHi.toFixed(2)}`
      : "drag a rectangle to gate";
  }

  function applyGate(g) {
    state.gate = g;
    state.gated = new Set(sample.cells
      .filter((c) => state.detected.has(c.id)
        && c.area >= g.aLo && c.area <= g.aHi && c.intensity >= g.iLo && c.intensity <= g.iHi)
      .map((c) => c.id));
    renderGateReadout();
    drawScatter();
    drawStage();
    renderTabs();
    renderActionBar();
  }

  el("clear-gate").addEventListener("click", () => {
    state.gate = null; state.gated = new Set();
    renderGateReadout();
    drawScatter(); drawStage(); renderTabs(); renderActionBar();
  });

  /* ============================================================
     the gallery — acquired overview / target pairs
     ============================================================ */
  function cropCanvas(cell, zoom, seed) {
    const cv = document.createElement("canvas");
    const S = 132;
    cv.width = S; cv.height = S;
    const ctx = cv.getContext("2d");
    const r = makeRng(seed);
    ctx.fillStyle = "#05090e";
    ctx.fillRect(0, 0, S, S);
    const blobN = zoom > 1 ? 5 : 14;
    for (let i = 0; i < blobN; i++) {
      const bx = S * r(), by = S * r();
      const br = (zoom > 1 ? 26 : 9) * (0.5 + r());
      const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
      g.addColorStop(0, `rgba(34,211,238,${0.30 + 0.35 * r()})`);
      g.addColorStop(1, "rgba(34,211,238,0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(bx, by, br, 0, Math.PI * 2); ctx.fill();
    }
    // the cell itself, centred
    const cr = zoom > 1 ? 34 : 7;
    const g2 = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, cr);
    g2.addColorStop(0, `rgba(245,158,11,${0.55 + 0.4 * cell.intensity})`);
    g2.addColorStop(0.7, "rgba(245,158,11,0.22)");
    g2.addColorStop(1, "rgba(245,158,11,0)");
    ctx.fillStyle = g2;
    ctx.beginPath(); ctx.arc(S / 2, S / 2, cr, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = "rgba(22,163,74,0.85)";
    ctx.lineWidth = zoom > 1 ? 2 : 1.5;
    ctx.beginPath(); ctx.arc(S / 2, S / 2, cr * 0.75, 0, Math.PI * 2); ctx.stroke();
    return cv;
  }

  /* In the document only while the step is standing, like every channel;
     mounting rebuilds from the run's state, so nothing stale survives. */
  const galleryMounted = () => galleryControls.isConnected;

  function buildGallery() {
    if (!galleryMounted()) return;
    const host = el("pairs");
    host.textContent = "";
    state.acquired.forEach((id, i) => {
      const cell = sample.cells[id - 1];
      const card = document.createElement("div");
      card.className = "pair";

      const imgs = document.createElement("div");
      imgs.className = "imgs";
      imgs.append(cropCanvas(cell, 1, 7000 + i), cropCanvas(cell, 3, 9100 + i));
      card.append(imgs);

      const meta = document.createElement("div");
      meta.className = "meta";
      meta.append(document.createTextNode(
        `#${cell.id} · ${(cell.x / 1000).toFixed(2)}, ${(cell.y / 1000).toFixed(2)} mm`));

      const verdict = document.createElement("div");
      verdict.className = "verdict";
      for (const [kind, glyph] of [["good", "✓"], ["bad", "✗"]]) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = `pick-${kind}`;
        b.textContent = glyph;
        b.setAttribute("aria-pressed", "false");
        b.setAttribute("aria-label", `mark cell ${cell.id} ${kind}`);
        b.addEventListener("click", () => {
          state.verdicts[cell.id] = state.verdicts[cell.id] === kind ? null : kind;
          for (const sib of verdict.querySelectorAll("button")) {
            sib.setAttribute("aria-pressed",
              String(sib.classList.contains(`pick-${state.verdicts[cell.id]}`)));
          }
          updateGalleryReadout();
        });
        verdict.append(b);
      }
      meta.append(verdict);
      card.append(meta);
      host.append(card);
    });
    updateGalleryReadout();
  }

  function updateGalleryReadout() {
    if (!galleryMounted()) return;
    const total = state.acquired.length;
    const marked = state.acquired.filter((id) => state.verdicts[id]).length;
    const good = state.acquired.filter((id) => state.verdicts[id] === "good").length;
    el("gallery-readout").textContent =
      total ? `${total} pairs · ${marked} marked · ${good} good` : "—";
  }

  /* ============================================================
     boot
     ============================================================ */
  const ro = new ResizeObserver(() => {
    if (el("panel-canvas").classList.contains("on")) { sizeCanvas(stageCv); drawStage(); }
    if (detectMounted()) drawTilePreview();
    drawTrace();
    if (analysisMounted()) { sizeCanvas(scatterCv); drawScatter(); }
  });
  ro.observe(el("panel-canvas"));
  ro.observe(focusControls);
  ro.observe(detectControls);
  ro.observe(analysisControls);

  const mo = new MutationObserver(() => { drawStage(); drawTilePreview(); drawTrace(); drawScatter(); });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  renderPointList();
  renderDetectToolbar();
  rebuildSample();
  focusPanelsFor(0);
  renderAll();
})();