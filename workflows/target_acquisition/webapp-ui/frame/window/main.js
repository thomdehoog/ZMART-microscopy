import "./style.css";
import { sideGroup } from "./panels.js";
import { renderRecordingSlot }
  from "../../workflows/target_acquisition/shared/recording-slot.js";
import { renderSessionCard }
  from "../../workflows/target_acquisition/steps/1_connect/session-card.js";
import { watchTheRun }
  from "../../workflows/target_acquisition/steps/5_scan_the_overview/watching-the-run.js";
import { openTheStage } from "../../workflows/target_acquisition/shared/stage.js";
import { blockedBecause, isReachable, panelsFor } from "../rules/steps.js";
import { assembleWorkflows } from "../rules/finding-workflows.js";
import { watchStagePosition } from "../../workflows/target_acquisition/shared/stage-position.js";
import {
  DEFAULT_SESSION, choicesFrom, describeSession,
} from "../../workflows/target_acquisition/microscope/instruments.js";
import { isFailed } from "../../workflows/target_acquisition/microscope/connection-status.js";
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
import carrierWidget from "../../workflows/target_acquisition/steps/2_define_carrier/carrier-panel.js";
import scanfieldsWidget, { presetInk } from "../../workflows/target_acquisition/steps/3_define_scan_area/scanfield-editor.js";
import detectionPanel, { ALGOS, detects }
  from "../../workflows/target_acquisition/steps/6_discover_targets/detection.js";
import gatingPanel from "../../workflows/target_acquisition/steps/7_refine_targets/gate.js";
import galleryWidget from "../../workflows/target_acquisition/steps/8_acquire_targets/gallery.js";
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
/* The stage-position watch, running while a session is open. */
let stageWatch = null;

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
    /* What can be connected to, as the controller lists it (`get_instruments`),
       grouped for the card: microscopes, each with its APIs. Loaded once the
       backend is known; empty until then. */
    instruments: [],
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

  /* The instrument the card has chosen: a microscope from the list and one
     of its APIs. The entry under them is what Connect sends. */
  const chosenMicroscope = () => state.instruments.find((m) => m.key === state.session.microscope);
  const chosenApi = () => chosenMicroscope()?.apis.find((a) => a.key === state.session.api);
  const chosenConnection = () => chosenApi()?.connection ?? null;

  /* Ask the backend what can be connected to, and choose for the operator
     when nothing is chosen yet: the mock when it is listed, so a page opened
     by accident drives nothing, otherwise the first entry. */
  function listInstruments() {
    return backend.instruments().then((list) => {
      state.instruments = choicesFrom(list);
      if (!chosenMicroscope()) {
        const mock = state.instruments.find((m) => m.vendor === "mock");
        state.session.microscope = (mock ?? state.instruments[0])?.key ?? null;
      }
      if (!chosenApi()) state.session.api = chosenMicroscope()?.apis[0]?.key ?? null;
      renderSetup(); renderActionBar();
    }).catch((why) => {
      state.instruments = [];
      state.session.microscope = null; state.session.api = null;
      console.warn(`could not list the instruments: ${why.message}`);
      renderSetup(); renderActionBar();
    });
  }

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
    listInstruments();
  });

  /* Closing the session takes the run with it: settings were read off this
     microscope, the origin is in its coordinates, and the tiles came from it.
     Keeping any of that against a session that has been closed would be
     keeping something that might now be a lie. The chosen microscope, API and
     password stay, since editing them is the reason to disconnect. */
  function resetRun() {
    stageWatch?.stop();
    stageWatch = null;
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
    gatingShown?.redraw();
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
        /* The registry entry under the microscope and API chosen on this card
           — what set_instrument takes. */
        connection: chosenConnection(),
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
          sessionShown?.answer(k, result);
        },
      }).then(async ({ info }) => {
        /* The session is open and every check has answered. The canvas is
           the instrument's from here — its travel from get_info — and the
           stage mark stands where get_xyz says the stage is. */
        takeTheCanvas(info?.canvas);
        /* From here the stage mark is the instrument's: a watch of its own
           reads get_xyz every few seconds for as long as the session is open,
           and again at once after any move this page makes. */
        stageWatch?.stop();
        stageWatch = watchStagePosition(backend, takeThePosition, {
          onError: (why) => console.warn(`where the stage is: ${why.message}`),
        });
        await stageWatch.refresh();
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
        stageWatch?.refresh();
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
        stageWatch?.refresh();
      }
      if (s.mode === "detect") {
        // the settings proven on one tile, now applied to every tile
        state.detected = new Set(sample.cells
          .filter((c) => detects(state.detect, c)).map((c) => c.id));
        state.cellsShown = true;
        state.notes[s.id] = `${state.detected.size} targets · ${ALGOS[state.detect.algo].label}`;
      }
      if (s.mode === "select") { state.notes[s.id] = `${state.gated.size} targets selected`; }
      if (s.mode === "targets") {
        const picked = [...state.gated].slice(0, 12);
        state.acquired = picked;
        state.notes[s.id] = `${picked.length} pairs acquired`;
        galleryPanel?.rebuild();
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
  const indexOfStep = (id) => steps().findIndex((s) => s.id === id);

  /* The instruments, asked for once the backend is known; the card fills in
     when the answer lands. */
  listInstruments();
  /* One slot per step, and the rows in it are the recordings.
   *
   * The bar at the top takes the next reading; what has been read stands under
   * it, a row apiece. Readings accumulate rather than replace, because the
   * optics get changed in the middle of a session and both settings stay worth
   * having — an overview taken dry at 5x and a detail taken at 63x in oil are
   * one run. One row is marked as the one the step is taken with, so switching
   * between them is a click rather than a second reading. */

  /* A slot's options, filled in from the run: a step says which recording it
     is showing and what to do when it changes; where that recording is kept,
     and how to read the instrument, is the run's business. */
  const recordingOptions = (opts) => ({
    ...opts,
    slot: () => state[opts.key],
    setSlot: (next) => { state[opts.key] = next; },
    running: () => state.running,
    readSetting: (type, how) => backend.readSetting(type, how),
  });

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
      renderRecordingSlot(el("focus-preset"), recordingOptions({
        label: "Focussing preset", key: "focusPreset",
        locked: focusLocked(),
        changed: () => {
          focusFollowsPreset(); showTheRest(); renderRail(); renderActionBar(); drawStage();
        },
        activated: () => {
          focusFollowsPreset(); showTheRest(); renderRail(); renderActionBar(); drawStage();
        },
      }));
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
  let detectionShown = null;
  const detectionMount = (host) => {
    detectionShown = detectionPanel.mount(host, {
      settings: () => state.detect,
      plan: () => state.plan,
      cellsInTile,
      density,
      sizeCanvas, css, drawScaleBar,
      changed: () => renderActionBar(),
    });
  };

  /* And selection once more: the gated cells light up on the canvas, and the
     channel holds the scatter they are gated on. */
  /* The scatter is the refine step's own panel, built beside its step. It is
     handed what to draw and what a gate means for the run; the handle it
     gives back is how the page asks it to draw again. */
  let gatingShown = null;
  const gatingMount = (host) => {
    gatingShown = gatingPanel.mount(host, {
      cells: () => sample.cells,
      detected: () => state.detected,
      gated: () => state.gated,
      acquired: () => state.acquired,
      gate: () => state.gate,
      showing: () => state.cellsShown,
      areaRange: [AREA_LO, AREA_HI],
      setGate: (gate, ids) => {
        state.gate = gate;
        state.gated = ids;
        drawStage(); renderTabs(); renderActionBar();
      },
      sizeCanvas, css,
    });
  };

  /* The session card lives in the channel like everything else: it is the
     controls of the step being stood on, beside the canvas it configures the
     run for. It rebuilds on every render, the way its panel used to, so
     nothing in it goes stale. */
  const connectWidget = {
    id: "connect", label: "Connect", mount: () => renderSetup(),
  };

  /* The gallery is the acquire step's own channel, built beside its step.
     What it shows and what it changes are handed to it; the handle it gives
     back is how the step's run fills the cards in once there are targets. */
  let galleryPanel = null;
  const galleryMount = (host) => {
    galleryPanel = galleryWidget.mount(host, {
      acquired: () => state.acquired,
      verdicts: () => state.verdicts,
      cellById: (id) => sample.cells[id - 1],
      recordingSlot: (into, opts) => renderRecordingSlot(into, recordingOptions(opts)),
      changed: () => renderActionBar(),
    });
  };

  const SIDE_WIDGETS = {
    connect: connectWidget,
    carrier: carrierWidget, scanfields: scanfieldsWidget,
    focus: focusWidget, scan: scanWidget,
    detect: { id: detectionPanel.id, label: detectionPanel.label, mount: detectionMount },
    select: { id: gatingPanel.id, label: gatingPanel.label, mount: gatingMount },
    acquire: { id: galleryWidget.id, label: galleryWidget.label, mount: galleryMount },
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
    renderRecordingSlot(el("sf-preset"), recordingOptions(presetSlot));

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
      stage.resize();
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
  /* The session card, and the handle it gives back: a check's answer lands in
     the row the card already put on screen. */
  let sessionShown = null;
  const SETUP_CARDS = {
    connect: (host) => {
      sessionShown = renderSessionCard(host, {
        connected: () => state.done.has("connect"),
        connecting: () => state.running === "connect",
        running: () => state.running,
        session: () => state.session,
        instruments: () => state.instruments,
        checks: () => state.checks,
        chosenMicroscope, chosenConnection,
        connect: () => runStep(indexOfStep("connect")),
        /* Closing takes the run with it, for the reason resetRun gives:
           everything after this was read off this session. */
        disconnect: () => { if (!state.running) resetRun(); },
        changed: () => { renderSetup(); renderActionBar(); },
      });
    },
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
    if (show === "canvas") stage.resize();
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

  /* The pictures of a real run — the overview being acquired, and the scan
     beneath the plan. The scan step's, so they live with it; this page hands
     them its canvases and its projection and asks them to draw. */
  const { thePicture, liveOverview } = watchTheRun({
    pictureHost: el("picture-host"),
    overviewCanvas: el("overview-canvas"),
    overviewNote: el("overview-note"),
    view: () => view,
    carrierOriginUm: () => carrierOriginUm(),
    css,
  });

  /* The stage picture — the run drawn to scale, layer on layer. It is the
     workflow's, so it lives with the workflow; the frame hands it the canvas,
     the run, and the few things it must be able to call back into. */
  const stage = openTheStage({
    canvas: el("stage-canvas"),
    tip: el("stage-tip"),
    css, sizeCanvas, el,
    run: state,
    sample: () => sample,
    carrierWidget, scanfieldsWidget,
    activePreset: () => activePreset(),
    indexOfStep, sideWidget,
    step: () => step(state.activeIdx),
    anchorPressed: (...a) => anchorPressed(...a),
    detectPressed: (...a) => detectPressed(...a),
    density: (...a) => density(...a),
    trueZ: (...a) => trueZ(...a),
    renderActionBar: () => renderActionBar(),
    renderRail: () => renderRail(),
    liveOverview, thePicture,
    focus: {
      focusPressed: (...a) => focusPressed(...a),
      focusCursor: (...a) => focusCursor(...a),
      focusDraggedTo: (...a) => focusDraggedTo(...a),
      focusGrabbed: (...a) => focusGrabbed(...a),
      focusHovered: (...a) => focusHovered(...a),
      focusMarqueeTo: (...a) => focusMarqueeTo(...a),
      focusMarqueeTook: (...a) => focusMarqueeTook(...a),
      drawFocusLayer: (...a) => drawFocusLayer(...a),
      marqueeing: () => focusMarquee,
      dragging: () => focusDrag,
      endDrag: () => { const held = focusDrag; focusDrag = null; return held ?? {}; },
    },
  });

  /* The page's own names for what it does to the picture. */
  const drawStage = () => stage.draw();
  const fitView = () => stage.fit();
  const view = stage.view;
  const STAGE_UM = stage.travelUm;
  const toScreen = (...a) => stage.toScreen(...a);
  const toWorld = (...a) => stage.toWorld(...a);
  const carrierOriginUm = () => stage.carrierOriginUm();
  const whereTheStageIs = () => stage.whereTheStageIs();
  const takeTheCanvas = (canvas) => stage.takeTheCanvas(canvas);
  const takeThePosition = (at) => stage.takeThePosition(at);
  const drawScaleBar = (...a) => stage.drawScaleBar(...a);

  /* Left where a test can reach it: what matters about a picture is what
     reached the screen, and only the page can be asked. */
  window.__theStageCanvas = {
    openScannedGround: (howMuch) => stage.openScannedGround(howMuch),
    closeTheGround: () => stage.closeTheGround(),
    openThisGround: (windows) => stage.openThisGround(windows),
    layers: () => stage.layers(),
    showLayer: (key, on) => stage.showLayer(key, on),
    fadeTo: (value) => stage.fadeTo(value),
    plan: () => stage.plan(),
    project: (x, y) => stage.project(x, y),
  };

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
    detectionShown?.redraw(); drawStage(); renderActionBar();
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
    stage.cursor(focusCursor());
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
     boot
     ============================================================ */
  const ro = new ResizeObserver(() => {
    if (el("panel-canvas").classList.contains("on")) stage.resize();
    drawTrace();
  });
  ro.observe(el("panel-canvas"));
  ro.observe(focusControls);

  const mo = new MutationObserver(() => {
    drawStage(); drawTrace();
    detectionShown?.redraw(); gatingShown?.redraw();
  });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  renderPointList();
  rebuildSample();
  focusPanelsFor(0);
  renderAll();
})();