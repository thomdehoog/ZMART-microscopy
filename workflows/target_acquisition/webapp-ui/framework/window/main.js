import "./style.css";
import { sideGroup } from "./panels.js";
import { renderRecordingSlot }
  from "../../workflows/target_acquisition/shared/recording-slot.js";
import { renderSessionCard }
  from "../../workflows/target_acquisition/steps/1_connect/session-card.js";
import { watchTheRun }
  from "../../workflows/target_acquisition/steps/5_scan_the_overview/watching-the-run.js";
import { openTheStage } from "../../workflows/target_acquisition/shared/stage.js";
import { openTheFocusMap }
  from "../../workflows/target_acquisition/steps/4_focus_strategy/focus-map.js";
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
import {
  AREA_HI, AREA_LO, cellsInTile as cellsOf, densityAt, sampleFor,
} from "../../workflows/target_acquisition/microscope/pretend-sample/sample.js";
import { METRICS, METRIC_KEYS, scoreAt } from "../../workflows/target_acquisition/microscope/pretend-sample/sweep.js";
import {
  affineSurface, fitSurface, residualsUm, surfaceZ,
} from "../../workflows/target_acquisition/microscope/pretend-sample/surface.js";

/* The workflows this page offers: every folder in `workflows/` with a
   `flow.js` inside it, found by the build tool's folder scan and assembled by
   the framework. The unit tests read the same folders, so a workflow the tests can
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

  /* What the pretend instrument would find, rebuilt whenever the plan or the
     plate changes — either changes what there is to find. It lives behind the
     microscope seam, because it is the instrument's answer and not the page's
     invention; a real backend reports what it imaged instead. */
  let sample = { tissue: [], cells: [], bounds: null };

  function rebuildSample() {
    state.plan = scanfieldsWidget.plan(state.fields, activePreset(), state.carrier);
    /* Left where a test can reach it, the way the live picture is. The plan is
       what this half of the run produces — where the stage goes and what each
       frame covers — and a suite that could only read the sentence beside it
       was asking how many positions there are, never where. */
    window.__plan = state.plan;
    sample = sampleFor(carrierWidget.extentUm(state.carrier), state.plan);
  }

  const density = (x, y) => densityAt(sample.tissue, x, y);
  const cellsInTile = (tile) => cellsOf(sample, tile);

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
      perField: 1,         // how many Place lays in each tileset
      perCarrier: 4,       // and how many it lays over the whole carrier
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
    tabs: [],             // worked out from the step, before anything is drawn
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

  /* ------------------------------------------------------------------
     the panels the running workflow offers
     ------------------------------------------------------------------
     One element apiece, inside the stage, filled by the workflow. The
     framework builds the box and knows what a panel is called, whether it
     stays once asked for, and whether it has a channel down its side; what
     goes in it, and what any of it means, is the workflow's.

     Built when the page opens, for the workflow the page opens on. A second
     workflow offering different panels will want them rebuilt at the switch,
     along with whatever draws in them — the same move as taking the drawing
     wired below out of this file. */
  const thePanels = {};
  for (const declared of WORKFLOWS[state.wf].panels) {
    const host = document.createElement("div");
    host.className = "panel";
    host.id = `panel-${declared.key}`;
    host.setAttribute("role", "tabpanel");
    document.querySelector(".stage").append(host);
    thePanels[declared.key] = { ...declared, host, ...(declared.build?.(host) ?? {}) };
  }

  /* The keys that stay for the rest of the run once a step has asked for one.
     `panelsFor` is handed these rather than knowing any of them. */
  const panelsThatStay =
    WORKFLOWS[state.wf].panels.filter((p) => p.stays).map((p) => p.key);

  /* The rule, with the workflow's own staying panels already in it. Bound once
     because it is asked in two places — when a step is walked to, and again on
     every render — and two callers passing the list separately is one caller
     forgetting to. */
  const tabsForStep = (i) => panelsFor(steps(), i, panelsThatStay);

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
      tabs: [], tab: null, tilesShown: 0,
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
    for (const panel of Object.values(thePanels)) {
      if (panel.foot) panel.foot.textContent = "";
    }
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
       A step says so for itself; the framework only asks. */
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

  /* Which panels a step gets is `panelsFor` in `framework/rules/steps.js`, and the reason
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
    state.tabs = tabsForStep(i);
    // a step that brings a panel of its own opens on it; otherwise the base
    state.tab = state.tabs.length > 1 ? state.tabs[1] : state.tabs[0];
  }

  /* ============================================================
     the setup panel — the run's configuration, before it has data
     ============================================================ */
  /* Connecting is a card that reads downward — the form, the checks, what they
     came to, and the button that acts on all of it. Its button is its own
     rather than the framework's, because it is disabled until there is a password
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

  /* Only while the stage is actually moving. Finishing a later step used to
     freeze the carrier as well, on the argument that what came after was
     measured against it — but going back to say the plate is a different plate
     is a thing operators do, and the answer to it is that the alignment goes
     and the picture is drawn again, both of which already happen. A step
     standing there greyed said "no" to a question that has a perfectly good
     answer. */
  const carrierLocked = () => !!state.running;

  /* The channel belongs to the step standing in it.

     Both steps that own one are about the canvas rather than beside it — the
     carrier is what the canvas is drawing, the scan fields are what is being
     drawn on it — so each docks its controls in the same column and the
     heading says which. One column, because two would take the picture's width
     to show controls for a step nobody is on. */
  /* Focus is not a widget module yet — its controls are markup that was built
     once and is moved into the channel, not rebuilt from a declaration. It
     stands in the same list because the framework only asks two things of an owner:
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
        label: "Focussing configuration", key: "focusPreset",
        /* Read off the microscope like the optical one, and named after what
           it is rather than by the operator. */
        unnamed: true,
        takes: "Import focussing configuration",
        retakes: "Update focussing configuration",
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

  /* How the carrier panel's list of anchors is redrawn. Set by the panel when
     it mounts; called from here and from the picture, because a mark dragged
     on the canvas has to move the numbers in the list with it. */
  let redrawAnchors = () => {};

  /* Delete takes away the alignment mark that was pressed — the one wearing a
     ring on the picture and standing as the current row in the list. The same
     key does the same thing to a focus point and to a scan field, so a carrier
     is edited the way everything else on this canvas is.

     Taking the last one away leaves the box as the Add button left it: an empty
     list and a press offering to lay a fresh set, which is what an operator
     wants after deciding the whole alignment was wrong. */
  window.addEventListener("keydown", (e) => {
    if (step(state.activeIdx)?.mode !== "carrier" || state.running) return;
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    // a number being typed into the count box is not a mark being deleted
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    const chosen = state.anchorPicked ?? -1;
    if (!(chosen >= 0) || !state.anchors[chosen]) return;
    e.preventDefault();
    state.anchors = state.anchors.filter((_, at) => at !== chosen);
    state.anchorPicked = -1;
    state.anchorLit = -1;
    redrawAnchors();
    drawStage();
  });

  function renderSide(show) {
    /* Only a panel with a channel down its side has anywhere to put a step's
       controls. A workflow whose panels have none gives its steps panels of
       their own instead. */
    const host = thePanels[show]?.channel;
    if (!host) return;
    const widget = sideWidget();
    host.hidden = !widget;
    // the divider is the channel's edge, so it is only there when the channel is
    thePanels[show].divider.hidden = !widget;
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
      /* declared beside the run, so the picture can reach it too */
      widget.render(host, {
        config: state.carrier,
        locked,
        anchors: {
          list: () => state.anchors,
          arming: () => state.anchoring,
          /* Which one the operator is pointing at in the list, so the picture
             can single it out. Four green crosses look alike; the list is
             where they are told apart, and this is what carries that across. */
          lit: () => state.anchorLit ?? -1,
          light: (i) => {
            if ((state.anchorLit ?? -1) === i) return;
            state.anchorLit = i;
            drawStage();
          },
          arm: () => { state.anchoring = !state.anchoring; redrawAnchors(); drawStage(); },
          /* The places this carrier is registered from, put down together.
             Replaces rather than adds, so pressing twice does not leave eight
             marks on four spots — and any that had been driven to lose their
             stage reading with them, because a fresh set is a fresh question. */
          suggest: (places) => {
            state.anchors = places.map((p) => ({ x: p.x, y: p.y, at: p.at }));
            state.anchorPicked = -1;
            redrawAnchors(); drawStage();
          },
          /* Which mark the keyboard is talking to: chosen by pressing it on the
             picture, and drawn as the current row in the list, so an operator
             can look at either and know which one the other means. */
          picked: () => state.anchorPicked ?? -1,
          /* And chosen from the list as well as from the picture. Pressing a
             row is how an operator says which of the four they mean when they
             are reading the list rather than looking at the plate, and it has
             to mean the same thing either way — the mark on the picture is
             what says which one that is. */
          pick: (i) => {
            state.anchorPicked = i;
            redrawAnchors(); drawStage();
          },
          forget: (i) => {
            state.anchors = state.anchors.filter((_, at) => at !== i);
            /* Nothing is chosen once the chosen one has gone. Moving the choice
               to the next mark along would leave a ring on a point nobody
               pressed, and the next press of Delete would take that one too. */
            state.anchorPicked = -1;
            state.anchorLit = -1;
            redrawAnchors(); drawStage();
          },
          /* Where the microscope is standing now, kept against this point on
             the carrier: the pair is the registration — this place on the
             drawing is that place on the stage. */
          snap: async (i) => {
            /* Ask the instrument where it is, now, rather than taking whatever
               the watch last happened to say. The watch reads every few
               seconds; an operator presses this the moment they have finished
               driving, so the reading it would otherwise record is the one from
               up to five seconds before the drive ended.

               And the reading itself, not the position the picture has worked
               out. Once a scan has run, `whereTheStageIs` answers with the last
               tile it imaged — right for drawing the mark as a scan goes by,
               and wrong for an operator who has since driven somewhere by hand
               to register the carrier from it. Falling back to it only for the
               case where there is no instrument to ask. */
            const at = (await stageWatch?.refresh()) ?? whereTheStageIs();
            state.anchors = state.anchors.map((a, n) =>
              (n === i ? { ...a, stage: { x: at.x, y: at.y, z: at.z } } : a));
            /* The carrier is where the anchors say it is now, so everything
               drawn in its frame moves with it — the plan, the focus map, the
               cells. What the operator sees is the green point they just drove
               to landing on the red one. */
            redrawAnchors(); drawStage();
          },
          onChange: (fn) => { redrawAnchors = fn; },
        },
        onChange: (next) => {
          state.carrier = next;
          /* The alignment goes with the old carrier. Where the four points sit
             comes from the shape, and what they were snapped to was measured
             against that shape — a plate 75 mm wide aligned by its own borders
             says nothing once it is 128 mm wide, and keeping the marks would
             leave the drawing standing somewhere nobody measured. */
          state.anchors = [];
          redrawAnchors();
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
      label: "Optical configuration", key: "overviewPreset", locked,
      /* No name to give it: what is being brought in is whatever the
         microscope is set to, and it is named after that. */
      unnamed: true,
      takes: "Import optical configuration",
      retakes: "Update optical configuration",
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
  for (const withAnEdge of Object.values(thePanels).filter((p) => p.divider)) {
    const divider = withAnEdge.divider;
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
    const host = thePanels[shownPanel()]?.channel;
    if (!host) return;
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
      const meta = thePanels[key];
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
    const owner = thePanels[shownPanel()]?.channel ? sideWidget() : null;
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
    for (const [key, panel] of Object.entries(thePanels)) {
      panel.host.classList.toggle("on", key === show);
    }
    renderSide(show);
    renderStepAction(show);
    /* A panel that draws something of its own is told it is on screen: a
       picture cannot be laid out while it is hidden, because a hidden box has
       no size. A panel with nothing to re-measure simply says nothing. */
    thePanels[show].shown?.();
    // The acquired overview lies over the plan while the scan is what is being
    // looked at, so which of the two is on screen follows the step.
    liveOverview.showFor(step(state.activeIdx), show);
  }

  function renderAll() {
    /* The step being looked at decides the tab set on its own, so this is the
       one place that has to agree with it — recomputed rather than trusted,
       and the selection kept only while it still names a tab that is there. */
    state.tabs = tabsForStep(state.activeIdx);
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
  /* The canvas panel this workflow declared, and everything that draws in it.
     All of it is the workflow's rather than this file's, and is here only
     until it moves into the panel's own building — which is the same move
     that makes the canvas step-agnostic. */
  const theCanvas = thePanels.canvas;

  const { thePicture, liveOverview } = watchTheRun({
    pictureHost: theCanvas.parts.pictureHost,
    overviewCanvas: theCanvas.parts.overviewCanvas,
    overviewNote: theCanvas.parts.overviewNote,
    view: () => stage.pictureView(),
    carrierOriginUm: () => carrierOriginUm(),
    css,
  });

  /* The stage picture — the run drawn to scale, layer on layer. It is the
     workflow's, so it lives with the workflow; the framework hands it the canvas,
     the run, and the few things it must be able to call back into. */
  const stage = openTheStage({
    box: theCanvas.parts.box,
    layerBar: theCanvas.parts.layerBar,
    tip: theCanvas.parts.tip,
    readout: theCanvas.parts.readout,
    fitButton: theCanvas.parts.fit,
    css, sizeCanvas, el,
    run: state,
    sample: () => sample,
    carrierWidget, scanfieldsWidget,
    activePreset: () => activePreset(),
    indexOfStep, sideWidget,
    step: () => step(state.activeIdx),
    anchorPressed: (...a) => anchorPressed(...a),
    /* The list of anchors is drawn by the carrier panel, so a mark dragged on
       the picture has to tell it the numbers moved. */
    anchorsChanged: () => redrawAnchors(),
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
      marqueeing: () => focusMap.marqueeing(),
      dragging: () => focusMap.dragging(),
      endDrag: () => focusMap.endDrag(),
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

  /* The focus map — the points, their sweeps, the surface through them, and
     the controls for all three. Step 4's, so it lives with step 4; it draws
     on the stage and is handed it. */
  const focusMap = openTheFocusMap({
    run: state,
    sample: () => sample,
    backend: { measureFocus: (...a) => backend.measureFocus(...a) },
    stage,
    el, css, sizeCanvas,
    step: () => step(state.activeIdx),
    focusControls: el("focus-controls"),
    renderActionBar: () => renderActionBar(),
    renderSide: (...a) => renderSide(...a),
  });

  /* The page's own names for what it asks of the focus map. */
  const {
    drawFocusLayer, focusPressed, focusCursor, focusDraggedTo, focusGrabbed,
    focusHovered, focusMarqueeTo, focusMarqueeTook, anchorPressed, detectPressed,
    trueZ, nearestPosition, renderFocusBar, renderPointList, drawTrace,
    refitSurface, remeasure,
  } = focusMap;

  /* ============================================================
     boot
     ============================================================ */
  /* A picture cannot be laid out while it is hidden: a hidden box has no
     size. So the panel re-measures when it comes up. */
  theCanvas.shown = () => stage.resize();

  const ro = new ResizeObserver(() => {
    if (theCanvas.host.classList.contains("on")) stage.resize();
    drawTrace();
  });
  ro.observe(theCanvas.host);
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