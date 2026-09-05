import { status } from "./status.js";
import "./style.css";
import { sideGroup } from "./panels.js";
import { renderRecordingSlot }
  from "../../workflows/target_acquisition/shared/recording-slot.js";
import { renderSessionCard }
  from "../../workflows/target_acquisition/steps/connect/session-card.js";
import { watchTheRun }
  from "../../workflows/target_acquisition/steps/scan_the_overview/watching-the-run.js";
import { openTheStage } from "../../workflows/target_acquisition/shared/stage.js";
import { openTheFocusMap }
  from "../../workflows/target_acquisition/steps/focus_strategy/focus-map.js";
import { blockedBecause, isReachable, panelsFor } from "../rules/steps.js";
import { assembleWorkflows } from "../rules/finding-workflows.js";
import { watchStagePosition } from "../../workflows/target_acquisition/shared/stage-position.js";
import {
  DEFAULT_SESSION, choicesFrom, describeSession,
} from "../../parts/microscope/instruments.js";
import { isFailed } from "../../parts/microscope/connection-status.js";
import { displayedPictureAddress } from "../../parts/canvas/display-of.js";
import { cellsInAllGates, keptUnderCeiling }
  from "../../workflows/target_acquisition/steps/refine_targets/gating.js";
import { selectionPanel }
  from "../../workflows/target_acquisition/steps/target_scan_area/step.js";
import { planScanAreas }
  from "../../workflows/target_acquisition/steps/target_scan_area/scan-areas.js";
/* The seam. Connecting, reading a preset off the instrument, measuring the
   focus map and driving the overview scan all go through the backend and are
   awaited; this window never knows whether a real stage moved. Which side of
   the seam answers is the chosen workflow's declaration: the prototype
   rehearses everything in the browser, and the mock and real workflows speak
   HTTP to the bridge — through it to the zmart controller, and on to the
   driver each of them names. */
import { backend as pretendBackend } from "../../parts/microscope/mock.js";
import { backend as liveBackend } from "../../parts/microscope/live.js";
import { centres, DEFAULT_CARRIER, describeCarrier } from "../../workflows/target_acquisition/shared/carriers.js";
import {
  emptySlot, hasRecording, withRecording, withoutRecording, withActive,
  activeRecording, nextReadingIndex,
} from "../../parts/microscope/recordings.js";
import carrierWidget from "../../workflows/target_acquisition/steps/define_carrier/carrier-panel.js";
import scanfieldsWidget, { presetInk } from "../../workflows/target_acquisition/steps/define_scan_area/scanfield-editor.js";
import detectionPanel, { settingsFor }
  from "../../workflows/target_acquisition/steps/discover_targets/detection.js";
import { forgetTheMasks } from "../../workflows/target_acquisition/steps/discover_targets/layers.js";
import gatingPanel from "../../workflows/target_acquisition/steps/refine_targets/gate.js";
import galleryWidget from "../../workflows/target_acquisition/steps/acquire_targets/gallery.js";
/* The rehearsal's own maths — the deterministic random stream, the autofocus
   sweep with its two metrics and its specks of debris, and the focus-surface
   fitting — is imported rather than written here, so the unit tests and the
   page read the same arithmetic. These files used to exist twice, once here
   and once beside the mock, and the two copies could disagree in silence. */
import { METRICS, METRIC_KEYS } from "../../parts/microscope/pretend-sample/sweep.js";
import {
  affineSurface, fitSurface, residualsUm, surfaceZ,
} from "../../parts/microscope/pretend-sample/surface.js";

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
/* The page's usual backend is the controller's bridge, or the pretend one in
   development. A workflow that brings its own -- the driver-configuration
   workflow speaks to the setup seam, not to a session -- gets that instead,
   and the framework never has to know which workflow is which. */
const backendFor = (wf) =>
  WORKFLOWS[wf]?.backend
  ?? (new URLSearchParams(location.search).get("backend") === "pretend" ? pretendBackend : liveBackend);
let backend = null;
/* The stage-position watch, running while a session is open. */
let stageWatch = null;

(() => {
  "use strict";

  function rebuildPlan() {
    state.plan = scanfieldsWidget.plan(state.fields, activePreset(), state.carrier);
    /* Left where a test can reach it, the way the live picture is. The plan is
       what this half of the run produces — where the stage goes and what each
       frame covers — and a suite that could only read the sentence beside it
       was asking how many positions there are, never where. */
    window.__plan = state.plan;
  }

  /* A field's targets, as discovery reports them: in the stage's frame, where
     the instrument imaged them. They are kept in the carrier's frame, as
     everything drawn on the picture is, and the field's label is kept with
     them, because it is where the field's picture is. */
  function fieldFound(field) {
    state.fieldLabels[field.field] = field.position_label;
    state.examined.add(field.field);
    for (const cell of field.cells) state.cells.set(cell.id, stage.toCarrier(cell));
  }

  /** What discovery came to, said beside the button. */
  const discoveryNote = () => `${state.cells.size} targets`;

  /** Where a capture's picture is: the viewer's small copy, by the capture's
      label -- drawn with the canvas's own display settings for that
      acquisition when there are any, so the preview and the gallery show the
      sample the way the picture shows it. */
  const pictureOf = (
    kind, label, { displayAs = kind, requireDisplay = false } = {},
  ) => {
    const where = backend.viewOf(kind);
    const snapshot = window.__viewerPanel?.snapshot?.() ?? null;
    return displayedPictureAddress(where, label, snapshot, displayAs, { requireDisplay });
  };

  /* Targets arrive far faster than a picture can be drawn. One redraw per
     frame, however many fields landed in it. */
  let redrawPending = false;
  function redrawSoon() {
    if (redrawPending) return;
    redrawPending = true;
    requestAnimationFrame(() => { redrawPending = false; drawStage(); renderAll(); });
  }

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
      algo: "fast",  // how objects are found: fast (watershed) | accurate (Cellpose)
      diameter: 30,
      cellprob: 0,
      threshold: 100,  // fast only: a nucleus's mean above background, in counts
      border: 0,       // µm from the field's edge inside which a cell is dropped
      binning: 1,      // segment on a copy this many times smaller each side
      maskShow: "fill", // how the test view wears the masks: fill | line | off
      maskAlpha: 0.65,  // how strongly the masks sit on the image (0..1)
      imageGrey: false, // the test image in grey (set by a landed test, hand-flipped)
      tile: 0,
      hovered: -1,     // the tile under the pointer, a press from being tested
      tested: false,
      tried: [],
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
    /* What discovery found, by id, and the label of the field each came
       from, which is where its picture is. */
    cells: new Map(),
    fieldLabels: {},
    /* The fields the run's own discovery has examined: the masks the canvas
       shows are theirs alone, never a tile test's left on disk. */
    examined: new Set(),
    overviewPictures: backendFor(WORKFLOWS[WORKFLOW_ASKED_FOR] ? WORKFLOW_ASKED_FOR : DEFAULT_WORKFLOW).viewOf?.("overview") ?? null,
    targetPictures: backendFor(WORKFLOWS[WORKFLOW_ASKED_FOR] ? WORKFLOW_ASKED_FOR : DEFAULT_WORKFLOW).viewOf?.("targets") ?? null,
    cellsShown: false,
    /* Which of the two the column beside the canvas shows: the step's own
       channel, or the picture's display settings. A page preference, kept
       across steps and sessions alike. */
    sideView: "channel",
    /* Whether the column is folded away to the right, the canvas taking its
       room. A page preference too. */
    sideFolded: false,
    gates: [],           // [{fx, fy, vertices: [[x, y], ...]}] — see gating.js
    /* The selection as it stands: what the gates let through, and once
       Restrict has been pressed, that held under the ceiling. The canvas
       rings it and the targets scan images it. */
    gated: new Set(),
    /* What Restrict kept of it under the ceiling, and the tiles laid round
       those -- the plan the acquisition images. */
    restricted: new Set(),
    targetTiles: [],
    targetTilesAlpha: 0.5,
    /* The placing levers, as scan-areas.js reads them, and what the last
       placing came to. */
    placing: { margin: 1, objectsMax: 50, tilesMax: null, overlapMin: 0.2 },
    tilePlan: null,
    acquired: [],
    /* The acquired target whose pair the gallery shows, chosen there or on
       the canvas; null until one is acquired. */
    selectedTarget: null,
    /* The acquired target under the pointer on the acquisition step: what a
       press would choose, outlined so the hand knows before it presses. */
    hoveredTarget: null,
    acquiredLabels: {},
    acquiredTiles: {},
    locked: false,
  };

  backend = backendFor(state.wf);

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
  /* Every workflow's panels, built once and kept: switching workflows shows
     a different set of them rather than rebuilding, so the canvas and what
     draws on it are wired once. Two workflows naming the same key share the
     panel, which is what sharing a key means. */
  const everyPanel = new Map();
  for (const wf of Object.values(WORKFLOWS)) {
    for (const declared of wf.panels) if (!everyPanel.has(declared.key)) everyPanel.set(declared.key, declared);
  }
  for (const declared of everyPanel.values()) {
    const host = document.createElement("div");
    host.className = "panel";
    host.id = `panel-${declared.key}`;
    host.setAttribute("role", "tabpanel");
    document.querySelector(".stage").append(host);
    thePanels[declared.key] = { ...declared, host, ...(declared.build?.(host) ?? {}) };
  }

  /* The keys that stay for the rest of the run once a step has asked for one.
     `panelsFor` is handed these rather than knowing any of them. */
  const panelsThatStay = () =>
    WORKFLOWS[state.wf].panels.filter((p) => p.stays).map((p) => p.key);

  /* The rule, with the workflow's own staying panels already in it. Bound once
     because it is asked in two places — when a step is walked to, and again on
     every render — and two callers passing the list separately is one caller
     forgetting to. */
  const tabsForStep = (i) => panelsFor(steps(), i, panelsThatStay());

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
    backend = backendFor(state.wf);
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
    setupRun = newSetupRun();
    /* Every panel's channel is emptied, not only the one about to be shown:
       switching workflows leaves the other workflow's panel hidden with its
       last step's controls still in it, and a hidden form is still a form
       -- a second password field the page can find. */
    for (const panel of Object.values(thePanels)) {
      if (panel.channel) panel.channel.textContent = "";
      if (panel.foot) panel.foot.textContent = "";
    }
    state.sideMounted = null;
    Object.assign(state, {
      activeIdx: 0, done: new Set(), ran: new Set(), running: null, notes: {},
      overviewPreset: emptySlot("acquisition"),
      focusPreset: emptySlot("autofocus"),
      targetType: emptySlot("acquisition", 1),
      carrier: { ...DEFAULT_CARRIER }, anchors: [], anchoring: false,
      fields: [], plan: [], checks: [],
      tabs: [], tab: null, tilesShown: 0,
      focus: newFocus(), focusMaps: {}, focusFor: null,
      detect: newDetect(), cells: new Map(), fieldLabels: {}, examined: new Set(),
      overviewPictures: backendFor(state.wf).viewOf?.("overview") ?? null,
      targetPictures: backendFor(state.wf).viewOf?.("targets") ?? null,
      cellsShown: false, gates: [], gated: new Set(), restricted: new Set(),
      targetTiles: [], targetTilesAlpha: 0.5, tilePlan: null,
      placing: { margin: 1, objectsMax: 50, tilesMax: null, overlapMin: 0.2 },
      acquired: [], acquiredLabels: {}, acquiredTiles: {},
      selectedTarget: null, hoveredTarget: null,
      locked: false,
    });
    view.fitted = false;
    stage?.groundFollowsTheScan();
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
    for (const slot of document.querySelectorAll(
      ".carrier-action, .scan-action, .focus-action, "
      + ".detect-action, .select-action, .acquire-action",
    )) {
      slot.textContent = "";
      slot.classList.remove("split-actions");
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
    /* marked as the step's own, because where it sits depends on the step —
       and marked `running` while the step is, because the label is for the
       operator and changes with what pressing it means ("working…",
       "Interrupt", "stopping…"): anything that needs to know whether the
       run is still going reads the class, never the prose. */
    run.className = `run step-run${running ? " running" : ""}`; run.type = "button";
    /* A running step the operator can stop offers its own brake: the press
       that started the run becomes Interrupt, and the backend stops between
       two fields — what was captured stands. The steps that drive the stage
       for minutes are exactly the ones a hand must be able to reach. Each
       brake matches the machinery its run drives: acquiring the targets is a
       scan under the hood, and discovery is the analysis run. */
    const brake = {
      scan: () => backend.stopScan?.(),
      detect: () => backend.stopTargets?.(),
      targets: () => backend.stopScan?.(),
      focus: () => backend.stopFocusMeasure?.(),
    }[s.mode];
    const currentFrame = s.mode === "targets"
      ? state.acquiredTiles[state.selectedTarget] : null;
    if (!running && !blocked && state.ran.has(s.id) && currentFrame?.tile) {
      const current = document.createElement("button");
      current.className = "run rerun-current";
      current.type = "button";
      current.textContent = "Rerun current";
      current.addEventListener("click", () => runStep(i, {
        targetTiles: [currentFrame.tile], append: true,
      }));
      host.classList.add("split-actions");
      host.append(current);
    }
    if (running && brake) {
      run.textContent = state.interrupting === s.id ? "stopping…" : "Interrupt";
      run.disabled = state.interrupting === s.id;
      run.addEventListener("click", () => {
        state.interrupting = s.id;
        brake();
        renderActionBar();
      });
    } else {
      run.textContent = running
        ? "working…"
        : (state.ran.has(s.id) ? (s.mode === "targets" ? "Rerun all" : "Run again") : s.btn);
      run.disabled = !!state.running || !!blocked;
      run.addEventListener("click", () => runStep(i));
    }
    host.append(run);

    /* The focus step says nothing beside its press. What it waits for is the
       box it stands in — points, laid by the row above it — and what it came to
       is the traces below; a greyed button between the two is already the whole
       sentence. */
    const hint = document.createElement("span");
    if (s.mode === "focus") { host.append(hint); return; }
    if (blocked) { hint.className = "action-hint"; hint.textContent = blocked; }
    /* Only when the button itself says Interrupt: a hint repeating the
       button's own "working…" said the same thing twice, side by side. */
    else if (running && brake) { hint.className = "action-hint"; hint.textContent = "working…"; }
    else if (s.mode === "select" && !done) { hint.className = "action-hint ok"; hint.textContent = `${state.gated.size} gated`; }
    /* What a step came to is said beside the button that produced it — except
       where the panel has a result box of its own: focus has its traces and
       select has its Scan area summary. What is missing is another matter:
       that is why the button cannot be pressed, and it belongs beside it. */
    else if (state.notes[s.id] && s.mode !== "focus" && s.mode !== "select"
      && !(s.mode === "targets" && currentFrame)) {
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
  function runStep(i, { targetTiles = null, append = false } = {}) {
    const s = step(i);
    if (state.running) return;
    /* A fresh run is a fresh run. The failure of the last one was cleared
       only when a run finished -- which a failed connect never did -- so the
       next press re-checked everything and then refused to finish, leaving
       the old answers standing. The operator fixed autosave and the page went
       on saying it was off. */
    if (state.failed === s.id) state.failed = null;
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
        /* A setup, not a session: there is no canvas to take and no stage
           to watch. What the driver said about itself is what the steps
           after this one draw from. */
        if (backend.kind === "setup") {
          await primeSetupRun(info);
          finish();
          return;
        }
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
        /* The bridge had already opened the driver's session before a check
           failed; left open, the next press opened a second one. A failed
           connection is not a session, so it is closed like one. */
        backend?.disconnect?.().catch(() => {});
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
        /* Each position at the measured focus height for that place. One
           with no surface to read carries no height, and the bridge images
           it where the objective stands -- never at an invented zero. */
        positions: state.plan.map((p) => {
          const z = surfaceZAt(p.x, p.y);
          return stage.toStage(z === null ? p : { ...p, z });
        }),
        /* The recorded overview configuration, reapplied as the scan starts:
           a recording that gated the step and configured nothing left every
           capture on whatever job was selected. */
        state: activeRecording(state.overviewPreset)?.changeable ?? null,
        onProgress: (done, of, at) => {
          if (state.running !== s.id) return;
          state.tilesShown = done;
          status.say(`scanning field ${done} of ${state.plan.length}`);
          /* The lit frame follows the scan, as it follows the segmentation. */
          state.detect.tile = Math.max(0, done - 1);
          /* The mark keeps up with the stage field by field, not every few
             seconds. */
          stageWatch?.refresh();
          /* The mark moves with the scan: each answer says where the stage
             stood, and the watch's own poll is seconds behind it. */
          if (at) takeThePosition(at);
          state.notes[s.id] = scanNote();
          stage.groundFollowsTheScan();
          /* Each position the scan reports is a reason to read the run again,
             because the tile it just saved is new picture that nothing on disk
             announces — the images were declared at their full size before any
             of them existed, so their description is the same before and after
             a tile lands. The picture decides how often to actually look; see
             `steps/scan_the_overview/overview.js`, which explains why. */
          liveOverview.tileMayHaveLanded();
          drawStage(); renderAll();
        },
      }).then((outcome) => {
        /* The scan's records name every field's picture. Dropped, the test
           tile on the discover step stayed black until a discovery answered;
           kept, a field can be looked at the moment its scan is done. */
        (outcome?.records ?? []).forEach((r, i) => {
          if (r?.position_label) state.fieldLabels[i] = r.position_label;
        });
        /* Detection starts at the first field. During the scan the current
           field follows the stage, but carrying the last scan position into
           Step 6 opened its test picker at 9 / 9 and made the first field look
           as though it had disappeared. */
        state.detect.tile = 0;
        return outcome?.stopped
          ? stoppedShort(`stopped by hand — ${scanNote()}`)
          : finish();
      }, itFailed);
      return;
    }

    if (s.mode === "focus" && state.focus.strategy === "plane") {
      /* The one step that drives the stage must finish on its promise, not on
         a rehearsal timer: finishing first marked the map done -- and the rail
         green -- before the objective had moved, and kept it done when the run
         failed on the instrument. */
      /* Nothing goes back to point one when the map is done: the stage,
         the mark and the lit row all end on the last point measured. */
      remeasure().then((came) => {
        if (!came?.stopped) return finish();
        const f = state.focus;
        const measured = f.points.filter((p) => Number.isFinite(p.z)).length;
        return stoppedShort(
          `stopped by hand — ${measured} of ${f.points.length} points measured`);
      }, itFailed);
      return;
    }

    if (s.mode === "detect") {
      state.cells = new Map();
      /* A fresh discovery invalidates everything named by the old ids: the
         gate and the acquired pairs -- a stale id crashed
         the draw and the gallery alike. */
      state.gates = [];
      state.gated = new Set();
      state.restricted = new Set();
      state.targetTiles = [];
      state.acquired = [];
      state.acquiredLabels = {};
      state.acquiredTiles = {};
      state.selectedTarget = null;
      state.hoveredTarget = null;
      state.cellsShown = true;
      state.examined = new Set();
      forgetTheMasks();
      /* The picture goes grey the moment the run starts: the objects are
         what is being looked at now, and the colours would fight their
         labels as they land. */
      window.__viewerPanel?.drawInGrey?.("overview", true);
      detectionShown?.progress?.({ start: true });
      backend.discoverTargets({
        settings: settingsFor(state.detect),
        onDoing: (sentence) => {
          status.say(sentence);
          detectionShown?.progress?.({ doing: sentence });
        },
        onProgress: (done, of, detail = {}) => {
          detectionShown?.progress?.({ done, of, ...detail });
          /* A field's masks land on the canvas as its object detection does. */
          redrawSoon();
        },
        onField: (field) => {
          if (state.running !== s.id) return;
          fieldFound(field);
          /* The lit frame follows the run across the sample: the field just
             detected is the one the picture and the preview are about. */
          state.detect.tile = field.field;
          state.notes[s.id] = discoveryNote();
          redrawSoon();
        },
      }).then((out) => {
        /* Fields first arrive when their per-position analysis completes.
           They arrive once more here with the population-wide UMAP axes;
           replacing by id makes Step 7 complete on its first paint. */
        for (const field of out?.fields ?? []) fieldFound(field);
        const failed = out?.failed ?? [];
        detectionShown?.progress?.({
          ended: true,
          note: out?.stopped
            ? "stopped by hand"
            : failed.length
              ? `finished — ${failed.length} field(s) failed; the first said: ${failed[0].why}`
              : out?.embeddingError
                ? `object detection finished; UMAP unavailable: ${out.embeddingError}`
                : "object detection finished",
        });
        return out?.stopped
          ? stoppedShort(`stopped by hand — ${state.cells.size} targets found`)
          : finish();
      }, (why) => {
        detectionShown?.progress?.({ ended: true, note: why.message });
        return itFailed(why);
      });
      return;
    }

    if (s.mode === "targets") {
      /* Imaging the targets is a scan whose positions are the gated cells,
         driven in the stage's frame like the overview was. */
      /* The tiles are the plan. Several may belong to one large target, and
         a tile shared by nearby targets may sit between their centres, so the
         stage is driven to the planned tile rather than back to a cell. */
      const picked = targetTiles ?? state.targetTiles;
      const positionFor = (tile) => {
        const { x, y } = tile;
        const z = surfaceZAt(x, y);
        const positionIndex = tile.positionIndex ?? state.targetTiles.indexOf(tile);
        return stage.toStage({
          ...(z === null ? { x, y } : { x, y, z }),
          position_index: Math.max(0, positionIndex),
        });
      };
      const accountFor = (records, n = records.length) => {
        const captures = picked.slice(0, n);
        if (!append) {
          state.acquired = [];
          state.acquiredLabels = {};
          state.acquiredTiles = {};
        }
        /* The comparison is with the frame that was actually acquired. A
           shared or multi-tile area need not be centred on its anchor target,
           so keeping only the target id made the overview crop show a nearby
           but different physical window. */
        captures.forEach((tile, i) => {
          const id = tile.key;
          if (!state.acquired.includes(id)) state.acquired.push(id);
          state.acquiredLabels[id] = records[i]?.position_label;
          const positionIndex = tile.positionIndex ?? state.targetTiles.indexOf(tile);
          state.acquiredTiles[id] = {
            x: tile.x, y: tile.y,
            frameUm: tile.frameUm ?? state.targetFrameUm,
            label: records[i]?.position_label,
            positionIndex,
            tile: { ...tile, positionIndex },
          };
        });
      };
      /* How wide each acquired frame is on the sample, for the canvas to
         print each picture at its true size and place -- known before the
         run starts, so the frames can be printed as they are captured. */
      state.targetFrameUm = activeRecording(state.targetType)?.frameUm ?? null;
      if (!append) {
        state.acquired = [];
        state.acquiredLabels = {};
        state.acquiredTiles = {};
        galleryPanel?.rebuild();
      }
      backend.scanOverview({
        positions: picked.map(positionFor),
        planned: state.targetTiles.map(positionFor),
        append,
        acquisition_type: "targets",
        state: activeRecording(state.targetType)?.changeable ?? null,
        /* Each capture prints itself onto the canvas as it lands, the way the
           overview's tiles do: the records so far name the pictures, and only
           the cells with a record are drawn as acquired. */
        onProgress: (done, of, at, records = []) => {
          if (state.running !== s.id) return;
          status.say(`acquiring pair ${done} of ${picked.length}`);
          if (at) takeThePosition(at);
          accountFor(records);
          state.notes[s.id] = `${done} / ${picked.length} pairs`;
          /* The ground opens over each acquired frame the way it opens over
             each overview field, so a target imaged at the edge of the plan
             shows through where it was taken rather than under the ground. */
          stage.groundFollowsTheScan();
          /* The list beside the canvas grows with the rings on it. */
          galleryPanel?.rebuild();
          redrawSoon(); renderAll();
        },
      }).then(({ records, stopped }) => {
        /* A stopped run accounts for what it took, and claims nothing more:
           only the cells with a record are acquired. */
        accountFor(records, stopped ? records.length : picked.length);
        stage.groundFollowsTheScan();
        redrawSoon();
        /* The gallery shows what was acquired, stopped or not: a run put
           down by hand after two pairs showed its two rings on the canvas
           and an empty gallery beside them. */
        galleryPanel?.rebuild();
        return stopped
          ? stoppedShort(`stopped by hand — ${records.length} of ${picked.length} pairs acquired`)
          : finish();
      }, itFailed);
      return;
    }

    /* Finishing a step: the connect step finishes when its backend resolves,
       every other step when its rehearsal's time is up. A declaration, so the
       connect arm above — which returns early — can reach it. */
    async function finish() {
      /* A step that failed while running was already put down; finishing it
         anyway would mark a failed connection as a session. */
      if (state.failed === s.id) return;
      status.quiet();
      state.running = null;
      state.interrupting = null;
      state.done.add(s.id);
      state.ran.add(s.id);
      if (s.note) state.notes[s.id] = s.note;

      if (s.mode === "focus") {
        const f = state.focus;
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
        stage.groundFollowsTheScan();
        stageWatch?.refresh();
      }
      if (s.mode === "detect") {
        state.notes[s.id] = discoveryNote();
      }
      if (s.mode === "select") {
        /* The press samples, then places: a systematic uniform random
           sample of what the gates let through, so many per tileset, and
           scan areas over it by the optimisation under the box's levers. */
        const p = state.placing;
        state.restricted = keptUnderCeiling(
          state.cells.values(), state.gated, p.objectsMax ?? state.gated.size, tilesetOfField);
        placeTheScanAreas();
        const covered = state.restricted.size - (state.tilePlan?.uncovered?.length ?? 0);
        state.notes[s.id] = `${state.targetTiles.length} target tiles · ${covered} of ${state.restricted.size} sampled targets covered`;
        gatingShown?.redraw(); selectionShown?.redraw?.();
      }
      if (s.mode === "targets") {
        state.notes[s.id] = `${state.acquired.length} pairs acquired`;
      }

      /* Finishing a run never moves the operator. The gallery is still being
         curated, the trace still being read, and a step that quietly hands
         the page to the next one takes that away. Advancing is a click. */
      focusPanelsFor(state.activeIdx);
      renderAll();
    }
    setTimeout(() => finish().catch(itFailed), s.ms);

    /** The operator's own Interrupt: not a failure, and not a finish either.
        What the run measured stands; the step is not marked done, so the
        press that stopped a run leaves a step that can simply be run again. */
    function stoppedShort(note) {
      status.quiet();
      state.running = null;
      state.interrupting = null;
      state.ran.add(s.id);
      state.notes[s.id] = note;
      focusPanelsFor(state.activeIdx);
      renderAll();
    }

    /** The step stops, marked as the failure it is, saying what went wrong. */
    function itFailed(why) {
      /* Said in the console too: the focus step draws no note, so a failure
         there had nowhere on screen to land and nobody could say why. */
      console.error(`${s.id} failed:`, why);
      status.quiet();
      state.failed = s.id;
      state.running = null;
      state.interrupting = null;
      state.notes[s.id] = `failed — ${why.message}`;
      renderAll();
    }
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
    /* Walking to a step is asking for its channel: the display settings a
       step was left on do not follow the operator to the next one. */
    state.sideView = "channel";
    /* The focus stack was there to judge the focus; over the overview it
       is a square of other pixels on the picture the operator came to
       look at. Its eye is pressed for them on the way to the scan. */
    if (steps()[i]?.id === "scan") window.__viewerPanel?.showAcquisition?.("focussing", false);
    /* The gallery's pictures wear the canvas's display settings, which may
       have changed since they were drawn: coming back to the step draws
       them again with the settings of now. */
    if (steps()[i]?.id === "acquire") galleryPanel?.rebuild();
  }

  /* ============================================================
     the setup panel — the run's configuration, before it has data
     ============================================================ */
  /* Connecting is a card that reads downward — the form, the checks, what they
     came to, and the button that acts on all of it. Its button is its own
     rather than the framework's, because it waits for an instrument to be
     chosen and it changes what it does once a session is open. */
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
    const leaving = state.focus;
    if (state.focusFor) state.focusMaps[state.focusFor] = leaving;
    state.focusFor = id;
    state.focus = id ? (state.focusMaps[id] ?? inheritedFocus(leaving)) : newFocus();
    // and maps whose preset has been forgotten go with it
    const kept = new Set(state.focusPreset.records.map((r) => r.id));
    for (const held of Object.keys(state.focusMaps)) {
      if (!kept.has(held)) delete state.focusMaps[held];
    }
  }

  /* An updated configuration does not take the operator's places with it.
     The recording is right that its READINGS are its own -- a height read
     through optics this recording no longer describes goes stale, and the
     surface fitted through such heights goes with them -- but the points
     are where the operator decided to measure, and pressing Update used to
     throw the whole laid map away with the reading it replaced. */
  function inheritedFocus(leaving) {
    if (!leaving || leaving.strategy !== "plane" || !leaving.points.length) {
      return newFocus();
    }
    return {
      ...newFocus(),
      metric: leaving.metric,
      perField: leaving.perField,
      perCarrier: leaving.perCarrier,
      points: leaving.points.map((p) =>
        (p.z !== null || p.traces || p.lost) ? { ...p, stale: true } : { ...p }),
    };
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
        retakes: "Update",
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

      /* What the scan will do, as labelled rows: how many positions, how
         wide each frame, and how the focus is found at each. */
      const { group, body } = sideGroup("Scan summary");
      const summary = document.createElement("div");
      summary.className = "scan-summary";
      const row = (label, value) => {
        const key = document.createElement("div");
        key.className = "k";
        key.textContent = label;
        const val = document.createElement("div");
        val.className = "v";
        val.textContent = value;
        summary.append(key, val);
      };
      row("Positions", String(state.plan.length));
      const frameUm = state.plan[0]?.frameUm;
      if (frameUm) row("Frame", `${Math.round(frameUm)} µm`);
      const measured = state.focus.applied && state.focus.strategy === "plane";
      row("Focus", measured
        ? `measured map · rms ${state.focus.residual.toFixed(1)} µm`
        : "found at every position");
      body.append(summary);
      pad.append(group);

      // and the press that starts it, at the end of what it acts on
      const action = document.createElement("div");
      action.className = "scan-action side-act";
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
      tryOn: (field, settings) => backend.discoverTargets({ fields: [field], settings })
        .then(({ fields, failed, stopped }) => {
          const found = fields?.[0];
          /* Stopped by the operator's hand before the field answered: the
             backend says so, and that is neither a field nor a failure. */
          if (!found && stopped) return { stopped: true };
          /* A field the bridge could not examine arrives under `failed` with
             the analysis's own sentence. Reading `fields[0]` regardless threw
             a TypeError, and the panel showed that instead of the reason. */
          if (!found) {
            throw new Error(failed?.[0]?.why ?? `position ${field + 1} was not examined`);
          }
          return { ...found, cells: found.cells.map(stage.toCarrier) };
        }),
      /* The same brake the step's own Run has: the bridge stops the field
         being segmented now, not at the next one. */
      stopTargets: () => backend.stopTargets?.(),
      pictureOf: (label) => pictureOf("overview", label),
      /* Which capture stands at a plan position: the scan filed each field's
         label as it landed, so the panel can show a field's picture without
         having tested anything on it. */
      labelOf: (field) => state.fieldLabels[field],
      /* The field's colorized segmentation, served beside its picture. */
      maskOf: (label) => {
        const where = backend.viewOf("overview");
        return where && label ? `${where}/${label}.mask.png` : null;
      },
      status,
      sizeCanvas, css, drawScaleBar,
      changed: () => { renderActionBar(); drawStage(); },
    });
  };

  /* And selection once more: the gated cells light up on the canvas, and the
     channel holds the scatter they are gated on. */
  /* The scatter is the refine step's own panel, built beside its step. It is
     handed what to draw and what a gate means for the run; the handle it
     gives back is how the page asks it to draw again. */
  let gatingShown = null;
  /** Which compartment a field belongs to, for the per-tileset ceiling. */
  const tilesetOfField = (field) => {
    const t = state.plan[field];
    return t ? (t.tileset ?? t.fieldId ?? field) : field;
  };
  const gatingMount = (host) => {
    gatingShown = gatingPanel.mount(host, {
      cells: () => state.cells.values(),
      gated: () => state.gated,
      gates: () => state.gates,
      cap: () => state.placing.objectsMax ?? Infinity,
      acquired: () => state.acquired,

      showing: () => state.cellsShown,
      setGates: (gates, ids) => {
        state.gates = gates;
        state.gated = ids;
        /* Something gated is what makes the gating step done; and a gate
           touched after Restrict is a selection not yet restricted, so the
           step after asks for its press again. */
        if (ids.size) state.done.add("gate"); else state.done.delete("gate");
        state.restricted = new Set();
        state.targetTiles = [];
        state.done.delete("select");
        state.ran.delete("select");
        drawStage(); renderTabs(); renderActionBar(); renderRail();
      },
      tilesetOf: tilesetOfField,
      /* Whether Restrict has drawn under the ceiling: the plot then marks
         what it kept over what the gates let through. */
      restricted: () => state.restricted,
      /* The target acquisition settings are recorded here, beside the
         selection they will image. */
      recordingSlot: (into, opts) => renderRecordingSlot(into, recordingOptions(opts)),
      changed: () => { renderActionBar(); renderRail(); },
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
      tileByKey: (key) => state.acquiredTiles[key]?.tile,
      cellById: (id) => state.cells.get(id),
      /* Both halves wear the target display settings and cover the exact
         acquired frame. That makes their colours, intensity windows and
         physical scale directly comparable despite different resolutions. */
      fieldOf: (tile, cell) => {
        const frame = state.acquiredTiles[tile.key];
        return {
          ...state.plan[cell.field],
          cropX: frame?.x ?? cell.x,
          cropY: frame?.y ?? cell.y,
          cropFrameUm: frame?.frameUm ?? state.targetFrameUm,
          picture: pictureOf("overview", state.fieldLabels[cell.field], {
            displayAs: "targets", requireDisplay: true,
          }),
        };
      },
      pictureOf: (id) => pictureOf(
        "targets", state.acquiredTiles[id]?.label ?? state.acquiredLabels[id],
        { requireDisplay: true },
      ),
      selected: () => state.selectedTarget,
      select: (id, opts) => selectTarget(id, opts),
      recordingSlot: (into, opts) => renderRecordingSlot(into, recordingOptions(opts)),
      changed: () => renderActionBar(),
    });
  };

  /** Choose an acquired tile: the gallery shows its pair and the canvas
      outlines the physical frame. `quietly` is the gallery choosing for
      itself while it rebuilds, so it is not told what it just did. */
  function selectTarget(id, { quietly = false } = {}) {
    if (state.selectedTarget === id) return;
    state.selectedTarget = id;
    if (!quietly) galleryPanel?.chosen();
    /* The chosen frame is raised above its neighbours in the picture, where
       frames overlap: the backend writes it on top and the picture follows. */
    const label = state.acquiredLabels[id];
    /* The gallery quietly follows the newest frame as a run grows. That
       frame has just been written last already; raising it again adds disk
       traffic and can contend with the live viewer for the same Zarr chunk.
       Only an operator's explicit choice changes the stacking order. */
    if (!quietly && label) {
      backend.raiseTarget?.(label)?.catch?.((why) => console.warn("the target was not raised: " + why.message));
    }
    stage.draw();
  }

  /** The acquired tile whose frame stands at a place on the sample, or null:
      the frame is the thing on the picture, so a press or a hover anywhere
      inside it means that acquisition. `reachUm` is a hand's reach in
      the sample's own units -- zoomed out to the plate a frame is smaller
      than a pixel, and a press within reach of its middle still means it. */
  function targetAt(world, reachUm = 0) {
    let hit = null;
    let nearest = Infinity;
    for (const id of state.acquired) {
      const tile = state.acquiredTiles[id];
      if (!tile) continue;
      const half = Math.max(tile.frameUm / 2, reachUm);
      const dx = Math.abs(world.x - tile.x), dy = Math.abs(world.y - tile.y);
      if (dx <= half && dy <= half && Math.hypot(dx, dy) < nearest) { nearest = Math.hypot(dx, dy); hit = id; }
    }
    return hit;
  }

  /** A press on the canvas in the acquisition step: the frame under it, if
      one is, becomes the chosen one. */
  function targetPressed(px, py) {
    if (step(state.activeIdx).mode !== "targets") return false;
    const hit = targetAt(stage.unproject(px, py), stage.umPerPixel() * 8);
    if (hit === null) return false;
    selectTarget(hit);
    return true;
  }

  /* The target scan area's channel: the ceiling and the settings the targets
     are imaged with. A ceiling typed is not a ceiling applied -- the press
     is -- so typing one asks for the press again; the settings recorded
     say how wide each frame on the picture is. */
  /* Scan areas over the sampled targets, by the optimisation in
     scan-areas.js under the levers the box holds. The sampled targets go
     in their systematic order, cells and all: the object's own size is what
     the margin is measured in. */
  function placeTheScanAreas() {
    const p = state.placing;
    const targets = [...state.restricted].flatMap((id) => (state.cells.has(id) ? [state.cells.get(id)] : []));
    const byTileset = new Map();
    for (const target of targets) {
      const tileset = tilesetOfField(target.field);
      if (!byTileset.has(tileset)) byTileset.set(tileset, []);
      byTileset.get(tileset).push(target);
    }
    /* A target-tile ceiling belongs to one overview tileset. Planning the
       groups independently makes that accounting real; a target in a
       neighbouring tileset cannot consume this one's allowance or share one
       of its target tiles. */
    const plans = [...byTileset].map(([overviewTileset, group]) => ({
      overviewTileset,
      plan: planScanAreas(group, state.targetFrameUm, {
        margin: p.margin,
        areas: { max: p.tilesMax },
        overlap: { min: p.overlapMin },
      }),
    }));
    const noteCounts = new Map();
    for (const { plan: one } of plans) for (const note of one.notes) {
      noteCounts.set(note, (noteCounts.get(note) ?? 0) + 1);
    }
    const plan = {
      placed: plans.flatMap(({ overviewTileset, plan: one }) =>
        one.placed.map((tile) => ({ ...tile, overviewTileset }))),
      uncovered: plans.flatMap(({ plan: one }) => one.uncovered),
      leftOut: [],
      notes: [...noteCounts].map(([note, count]) => count > 1
        ? `${note} (${count} overview tilesets)` : note),
    };
    state.targetTiles = plan.placed.map((tile, positionIndex) => ({ ...tile, positionIndex }));
    plan.placed = state.targetTiles;
    state.tilePlan = plan;
  }

  let selectionShown = null;
  const selectionMount = (host) => (selectionShown = selectionPanel.mount(host, {
    recordingSlot: (into, opts) => renderRecordingSlot(into, recordingOptions(opts)),
    restricted: () => state.restricted,
    /* Forget the sample and the scan areas: the gated targets stand whole
       again and the press is asked for. */
    reset: () => {
      state.restricted = new Set();
      state.targetTiles = [];
      state.tilePlan = null;
      state.done.delete("select");
      state.ran.delete("select");
    },
    tiles: () => state.targetTiles,
    showTiles: (on) => stage.showLayer("frames", on),
    tilesShown: () => stage.layerShown("frames"),
    rules: () => state.placing,
    /* A lever moved is a plan not yet placed: the press is asked for again. */
    setRule: (key, value) => {
      state.placing[key] = value;
      state.restricted = new Set();
      state.targetTiles = [];
      state.tilePlan = null;
      state.done.delete("select");
      state.ran.delete("select");
    },
    plan: () => state.tilePlan,
    alpha: () => state.targetTilesAlpha,
    setAlpha: (alpha) => { state.targetTilesAlpha = alpha; },
    changed: () => {
      state.targetFrameUm = activeRecording(state.targetType)?.frameUm ?? null;
      drawStage(); renderRail(); renderActionBar(); gatingShown?.redraw(); selectionShown?.redraw?.();
    },
  }));

  const SIDE_WIDGETS = {
    connect: connectWidget,
    carrier: carrierWidget, scanfields: scanfieldsWidget,
    focus: focusWidget, scan: scanWidget,
    detect: { id: detectionPanel.id, label: detectionPanel.label, mount: detectionMount },
    gate: { id: gatingPanel.id, label: gatingPanel.label, mount: gatingMount },
    select: { id: selectionPanel.id, label: selectionPanel.label, mount: selectionMount },
    acquire: { id: galleryWidget.id, label: galleryWidget.label, mount: galleryMount },
  };

  /* A step's channel: one the page knows by the step's id, or one the step
     brought with it. The second is how a workflow adds steps without adding
     to this file -- the step says `channel: {id, label, mount(host, ctx)}`
     and the page hands it the run. The channel is remounted on every render,
     the way the setup cards are: its cells say what the last press came to,
     and a press changes that. */
  const sideWidget = () => {
    const s = step(state.activeIdx);
    if (SIDE_WIDGETS[s.id]) return SIDE_WIDGETS[s.id];
    if (!s.channel) return null;
    return { id: s.channel.id, label: s.channel.label, ownChannel: true,
      mount: (host) => s.channel.mount(host, channelContextFor(s)) };
  };

  /* What the driver-configuration steps hold between renders: the last
     measurement per step, the lens views captured for the optics pair, where
     the stage was last read, the document the limits step is editing, and
     what each step published. Cleared with the run. */
  let setupRun = newSetupRun();
  function newSetupRun() {
    return { held: {}, views: {}, here: null, hereProblem: null, moveUm: 40,
      limitsDoc: null, standing: {}, published: {}, describe: null };
  }

  /* After a setup opens: what the driver says about itself, what stands for
     each subsystem, and where the stage is -- read once so the cells have
     something to show before any press. */
  async function primeSetupRun(info) {
    const seam = backend.setup;
    setupRun.describe = info?.describe ?? (await seam.status())?.describe ?? null;
    for (const name of ["limits", "orientation", "calibration", "origin"]) {
      try { setupRun.standing[name] = await seam.read(name); } catch (why) { setupRun.standing[name] = null; }
    }
    setupRun.limitsDoc = setupRun.standing.limits?.document
      ? JSON.parse(JSON.stringify(setupRun.standing.limits.document)) : null;
    try { setupRun.here = await seam.where(); } catch (why) { setupRun.hereProblem = why.message; }
  }

  /* The orientation the optics step corrects its pictures with: what this
     run measured and accepted, else what the machine has published and
     measured, else nothing -- the pictures stay raw. */
  const orientationInHand = () => {
    const measured = setupRun.held.orientation;
    if (measured?.accepted) {
      return { rotation_deg: measured.orientation.rotation_deg, reflection: measured.orientation.reflection };
    }
    const standing = setupRun.standing.orientation?.document;
    if (standing?.measured) return { rotation_deg: standing.rotation_deg, reflection: standing.reflection };
    return null;
  };

  function channelContextFor(s) {
    return {
      setup: backend.setup,
      supported: () => Boolean(setupRun.describe?.subsystems?.[s.id]?.supported),
      document: () => setupRun.describe?.subsystems?.limits?.document ?? null,
      standing: () => setupRun.standing[s.id] ?? null,
      held: () => setupRun.held[s.id] ?? null,
      hold: (answer) => { setupRun.held[s.id] = answer; },
      views: () => setupRun.views,
      holdView: (name, view) => { setupRun.views[name] = view; },
      orientation: orientationInHand,
      here: () => setupRun.here,
      holdHere: (here, problem = null) => { setupRun.here = here ?? setupRun.here; setupRun.hereProblem = problem; },
      hereProblem: () => setupRun.hereProblem,
      moveUm: () => setupRun.moveUm,
      setMoveUm: (v) => { if (Number.isFinite(v) && v > 0) setupRun.moveUm = v; },
      limits: () => setupRun.limitsDoc,
      edit: (key, value) => { if (setupRun.limitsDoc) setupRun.limitsDoc[key] = value; },
      publishedNote: () => setupRun.published[s.id] ?? null,
      /* After a publish, what stands is what was just written; the cell
         reads it back rather than remembering, so the sentence about it is
         the driver's word and not the page's. */
      restand: async () => {
        try { setupRun.standing[s.id] = await backend.setup.read(s.id); } catch (why) { /* left as it was */ }
      },
      /* A step settles by publishing: it is done, and the rail says what it
         came to. A failed publish leaves it undone and says why instead. */
      settle: (note, said) => {
        setupRun.published[s.id] = said;
        if (note) { state.done.add(s.id); state.ran.add(s.id); state.notes[s.id] = note; }
      },
      refresh: () => { state.sideMounted = null; renderAll(); },
    };
  }

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
    /* One column, two things that can stand in it. The display settings
       show only while there are some and they were asked for; the channel
       the rest of the time. */
    const display = thePanels[show].display ?? null;
    const showingDisplay = state.sideView === "display" && Boolean(display) && displaySettingsAvailable();
    if (state.sideView === "display" && !showingDisplay) state.sideView = "channel";
    /* Folded, the column is away to the right and only its fold strip stays,
       the press that brings it back. */
    const somethingToShow = Boolean(widget) || showingDisplay;
    const folded = state.sideFolded && somethingToShow;
    host.hidden = !widget || showingDisplay || folded;
    if (display) display.hidden = !showingDisplay || folded;
    // the divider is the column's edge, so it is only there when the column is
    thePanels[show].divider.hidden = !somethingToShow || folded;
    const fold = thePanels[show].fold;
    if (fold) {
      fold.hidden = !somethingToShow;
      fold.classList.toggle("collapsed", folded);
      const icon = fold.querySelector("span") ?? fold;
      icon.textContent = folded ? "‹" : "›";
      fold.title = folded ? "Open right sidebar" : "Collapse right sidebar";
      fold.setAttribute("aria-label", fold.title);
      fold.setAttribute("aria-expanded", String(!folded));
    }
    const locked = widget?.id === "carrier" ? carrierLocked() : scanfieldsLocked();
    const key = widget && `${widget.id}:${locked}`;
    // the setup cards rebuild on every render, the way their panel used to;
    // the working widgets keep their state and mount once per key
    if (state.sideMounted === key && !(widget && (SETUP_CARDS[widget.id] || widget.ownChannel))) return;
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
            if (!at) return;
            const [oxBefore, oyBefore] = stage.carrierOriginUm();
            state.anchors = state.anchors.map((a, n) =>
              (n === i ? { ...a, stage: { x: at.x, y: at.y, z: at.z } } : a));
            /* The carrier's frame just moved under everything already
               measured. What was measured was measured on the stage — that
               truth is unchanged — so its carrier coordinates are re-derived
               by the shift, or the cells and the focus map silently stand a
               frame-move away from the plan they were measured against. */
            const [oxAfter, oyAfter] = stage.carrierOriginUm();
            const dx = oxBefore - oxAfter, dy = oyBefore - oyAfter;
            if (dx || dy) {
              const moved = (p) => ({ ...p, x: p.x + dx, y: p.y + dy });
              state.cells = new Map(
                [...state.cells].map(([id, c]) => [id, moved(c)]));
              for (const map of [state.focus, ...Object.values(state.focusMaps)]) {
                map.points = map.points.map(moved);
              }
            }
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
          rebuildPlan();
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
      /* One word: the heading over the box already says what would be
         updated, and the reading now stands on the same row. */
      retakes: "Update",
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
      /* How far a field may be drawn: the stage's travel, said in the
         carrier's own micrometres. Not the carrier — a plate does not limit
         imaging, the instrument does, and a plate centred in a 120 x 80 mm
         travel has reachable stage all round it that the drawing was refusing
         to enter. The instrument reports the travel at connect; where the
         carrier sits in it is what alignment measures, so this moves when the
         operator snaps a point. */
      reach: (() => {
        const [fw, fh] = stage.travelUm;
        const [sx, sy] = stage.travelOriginUm;
        const [ox, oy] = stage.carrierOriginUm();
        return {
          xMin: sx - ox, xMax: sx + fw - ox,
          yMin: sy - oy, yMax: sy + fh - oy,
        };
      })(),
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
      /* No narrower than the widest card's row: the focus step's two hand
         tools and two counts side by side, which a 240 px column cut in
         half. */
      const width = Math.max(440, Math.min(box.width - 360, Math.round(box.right - e.clientX)));
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
    /* The fold on the same edge: the column goes away to the right and the
       canvas takes the room, or comes back the same width it had. The stage
       is resized here for the same reason as above. */
    withAnEdge.fold?.addEventListener("click", () => {
      state.sideFolded = !state.sideFolded;
      renderSide(shownPanel());
      renderTabs();
      stage.resize();
    });
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
    rebuildPlan();
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
           everything after this was read off this session. It works while
           something is running -- that is when an operator needs it. A step
           still in flight finds `running` cleared under it and stops there;
           the session it was talking to is closed at the bridge. */
        disconnect: () => {
          backend?.disconnect?.().catch((why) => console.warn(`closing: ${why.message}`));
          resetRun();
          thePicture.reset();
          stage.forgetTheCanvas();
          renderAll();
        },
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
    /* A panel whose channel is the whole window -- the notebook of the
       driver-configuration workflow -- has no side column to head, and no
       picture whose display settings could be offered. */
    const shownMeta = thePanels[shownPanel()];
    const owner = shownMeta?.channel && !shownMeta.wholeWindow ? sideWidget() : null;
    /* A folded column has no heading: the strip on its edge is all that is
       left of it, and the name would stand over the canvas. */
    if (owner && !state.sideFolded) {
      const side = document.createElement("span");
      side.className = "side-tab";
      if (displaySettingsAvailable()) {
        /* Two things can stand in the column, and these say which: the
           step's channel, or the picture's display settings. Real tabs,
           because there is a choice -- and one column, so the canvas does
           not move when the choice changes. The settings become a thing
           with the first picture, the focus stack of Step 4, and go with
           the picture at Disconnect; the tab is offered exactly then. */
        for (const [view, label] of [["channel", owner.label], ["display", "Display settings"]]) {
          const b = document.createElement("button");
          b.className = "tab"; b.type = "button"; b.role = "tab";
          b.setAttribute("aria-selected", String(state.sideView === view));
          b.textContent = label;
          b.addEventListener("click", () => { state.sideView = view; renderSide(shownPanel()); renderTabs(); });
          side.append(b);
        }
      } else {
        /* The name is its own element: it carries the rule under it, so that
           rule is as wide as the word the way a tab's is, rather than as wide
           as the channel this stands over. */
        const label = document.createElement("span");
        label.textContent = owner.label;
        side.append(label);
      }
      host.append(side);
    }
  }

  /** Whether there are display settings to show. Canvas-layer visibility is
      always useful once the canvas exists; acquisition/channel controls join
      the same column when a picture arrives. */
  function displaySettingsAvailable() {
    return Boolean(theCanvas?.display?.querySelector(".display-layer-settings, .viewer-panel"));
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
    /* Where this backend's scans can be fetched from, if anywhere. The live
       one serves what the microscope wrote; the pretend one has nothing. */
    pictures: (kind) => (state.done.has("connect") ? backend?.viewOf?.(kind) : null) ?? null,
    /* The run's OME-Zarr sources, as the viewer server beside the bridge
       serves them — the real picture, linked position by position. `null`
       while there is none, and the JPEG copies stand in.

       Both answer nothing once the session is closed. The backend object
       outlives the session, and its addresses used to be handed out after
       Disconnect, so the page reopened an empty JPEG picture on a bridge
       that had no run to serve. */
    viewerSources: () => (state.done.has("connect") ? backend?.viewerSources?.() : null) ?? null,
    overviewCanvas: theCanvas.parts.overviewCanvas,
    overviewNote: theCanvas.parts.overviewNote,
    view: () => stage.pictureView(),
    carrierOriginUm: () => carrierOriginUm(),
    /* The column the picture's display settings stand in, a tab away from
       the step's channel; and the word that the settings came or went, so
       the tab row can offer the tab exactly while there is something to
       show under it. */
    displayHost: () => theCanvas.display,
    /* Only the tab row and the column: rendering every panel from here
       reaches the picture, which mounts the settings again, which says so
       again -- a loop that never let the page settle. */
    displayChanged: () => {
      renderTabs(); renderSide(shownPanel());
      /* The gallery's pairs wear the picture's settings: rows that have just
         come -- the targets' own, at the end of their run -- are what its
         first pair should already be drawn with. */
      galleryPanel?.rebuild();
    },
    /* A display control changed after the panel was mounted. The available
       tabs did not change, only displayed copies that use the snapshot did. */
    displaySettingsChanged: () => galleryPanel?.rebuild(),
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
    carrierWidget, scanfieldsWidget,
    activePreset: () => activePreset(),
    indexOfStep, sideWidget,
    step: () => step(state.activeIdx),
    anchorPressed: (...a) => anchorPressed(...a),
    /* The list of anchors is drawn by the carrier panel, so a mark dragged on
       the picture has to tell it the numbers moved. */
    anchorsChanged: () => redrawAnchors(),
    /* A tile chosen on the canvas appears in the test box at once. */
    tileChosen: () => detectionShown?.redraw(),
    detectPressed: (...a) => detectPressed(...a),
    targetPressed: (...a) => targetPressed(...a),
    targetAt: (world, reachUm) => targetAt(world, reachUm),
    renderActionBar: () => renderActionBar(),
    renderRail: () => renderRail(),
    /* Whether the picture draws an acquisition of this name itself, so a
       layer that would print copies of it can leave the engine's own pixels
       to the display settings. */
    pictureShows: (name) => thePicture.shows(name),
    /**
     * Drive the stage to a place on the travel, and answer with where it
     * ended up — in micrometres per axis, the shape every reading takes.
     *
     * The picture asks for this when a place on it is double-clicked. Only
     * `x` and `y` are named: driving across the sample is not a request to
     * change how far the objective is from it.
     *
     * `null` when there is no session, when the run is driving the stage
     * itself, or when the instrument refused — and the mark then stays where
     * the last reading put it, which is the truth as far as the page knows it.
     */
    driveTo: async ({ x, y }) => {
      if (!backend?.set_xyz || state.running) return null;
      try {
        const at = await backend.set_xyz({ x, y });
        return {
          x: Number(at.x.value), y: Number(at.y.value),
          z: Number(at.z?.value ?? 0),
        };
      } catch (why) {
        console.warn(`the stage would not go there: ${why.message}`);
        return null;
      }
    },
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
      drawFocusPoints: (...a) => drawFocusPoints(...a),
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
    groundWindows: () => stage.groundWindows(),
    layers: () => stage.layers(),
    showLayer: (key, on) => stage.showLayer(key, on),
    layerShown: (key) => stage.layerShown(key),
    fadeTo: (value) => stage.fadeTo(value),
    plan: () => stage.plan(),
    targets: () => stage.targets(),
    project: (x, y) => stage.project(x, y),
    view: () => stage.pictureView(),
    lookAt: (where) => stage.lookAt(where),
    carrierOriginUm: () => stage.carrierOriginUm(),
    /* Acquisition Z is deliberately distinct from the flat picture's Z=0
       display plane. Evidence that publishes positions through the bridge
       must ask the same measured surface the real Step 5 Run path asks. */
    focusZAt: (x, y) => surfaceZAt(x, y),
  };
  /* The selected focus point, for a test that needs to take hold of one. */
  window.__theFocusPoints = () => state.focus.points[state.focus.selected] ?? null;
  /* The run's own state, read-only, for a test that needs to say why a step
     did nothing rather than only that it did. */
  window.__theRunState = () => JSON.parse(JSON.stringify({
    running: state.running, failed: state.failed, notes: state.notes,
    activeIdx: state.activeIdx, done: [...state.done], ran: [...state.ran],
    focus: { strategy: state.focus.strategy, applied: state.focus.applied,
             points: state.focus.points.length, selected: state.focus.selected },
    /* How wide each acquired frame is, so a test can check the ground is
       opened over exactly the frame the recording describes. */
    targetFrameUm: state.targetFrameUm ?? null,
    /* The chosen acquired tile key, so a test can press on the picture and
       see the choice land. */
    selectedTarget: state.selectedTarget ?? null,
    acquiredTileKeys: [...state.acquired],
    restricted: [...state.restricted],
    targetTiles: state.targetTiles.length,
    targetTilePositions: state.targetTiles.map((tile) => ({
      x: tile.x, y: tile.y, frameUm: tile.frameUm,
      key: tile.key,
      overviewTileset: tile.overviewTileset,
      targetId: tile.targetId ?? tile.id,
      covers: tile.covers ?? [],
    })),
  }));

  /* The focus map — the points, their sweeps, the surface through them, and
     the controls for all three. Step 4's, so it lives with step 4; it draws
     on the stage and is handed it. */
  const focusMap = openTheFocusMap({
    run: state,
    backend: {
      measureFocus: (...a) => backend.measureFocus(...a),
      /* Where a focus stack's slice pictures are fetched from -- the same
         answer every other picture gets, and `null` from a backend that
         serves none, which is what hides the preview. */
      slicesAt: () => backend.viewOf?.("focussing") ?? null,
    },
    stage,
    el, css, sizeCanvas,
    step: () => step(state.activeIdx),
    focusControls: el("focus-controls"),
    renderActionBar: () => renderActionBar(),
    renderSide: (...a) => renderSide(...a),
  });

  /* The page's own names for what it asks of the focus map. */
  const {
    drawFocusLayer, drawFocusPoints, focusPressed, focusCursor, focusDraggedTo, focusGrabbed,
    focusHovered, focusMarqueeTo, focusMarqueeTook, anchorPressed, detectPressed,
    surfaceZAt, nearestPosition, renderFocusBar, renderPointList, drawTrace,
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
  rebuildPlan();
  focusPanelsFor(0);
  renderAll();
})();
