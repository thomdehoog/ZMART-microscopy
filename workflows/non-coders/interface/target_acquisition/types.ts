/**
 * Target acquisition's types: its run, its page and its steps, as the
 * workflow API's own types filled in for this workflow.
 *
 * The API's `Page`, `Run` and `Step` take one bag of types (`WorkflowTypes`)
 * and speak of whichever workflow fills it. This file fills it for target
 * acquisition: the run is the framework's keys and `freshState`'s
 * (`shared/run-document.ts`), the backend is the one list of verbs
 * (`backend/verbs.ts`), and the page carries what `on-the-page.js` lends
 * it. Each is read off the code that makes it, so a key added to the fresh
 * run or a function added to the lends is typed where it is written.
 *
 * Author: Thom de Hoog, Center for Microscopy and Image Analysis (ZMB),
 * University of Zurich (thom.dehoog@zmb.uzh.ch, thomdehoog@gmail.com).
 */

import type { Page, Run, Step, WorkflowTypes } from "zmart-interface/api";
import type { Backend } from "./backend/verbs.ts";
import type { View } from "./canvas/engines/opening-view.ts";
import type { EngineViewer } from "./canvas/engines/neuroglancer-under/viewer.ts";
import type { ViewerPanelElement } from "./canvas/viewer-panel.ts";
import type { freshState } from "./shared/run-document.ts";
import type { StageWatch } from "./shared/stage-position.ts";
import type { ProgressBox } from "./shared/progress.ts";
import type * as helpers from "./shared/page-helpers.ts";
import type { CanvasOnThePage } from "./the-canvas.ts";
import type * as connect from "./steps/connect/channel.ts";
import type { CarrierOnThePage } from "./steps/define_carrier/channel.ts";
import type * as scanArea from "./steps/define_scan_area/channel.ts";
import type { FocusOnThePage } from "./steps/focus_strategy/channel.ts";
import type { focusFitWord } from "./steps/focus_strategy/run.ts";
import type { testTilesChanged } from "./steps/scan_the_overview/channel.ts";
import type { overviewGoesGreyForTheMasks } from "./steps/discover_targets/channel.ts";
import type * as acquire from "./steps/acquire_targets/channel.ts";
import type { renderProtocolProgress } from "./steps/run_protocol/channel.ts";
import type { protocolWithin } from "./steps/run_protocol/run.ts";
import type galleryWidget from "./steps/acquire_targets/gallery.ts";
import type { renderSessionCard } from "./steps/connect/session-card.ts";
import type scanfieldsWidget from "./steps/define_scan_area/scanfield-editor.ts";
import type detectionPanel from "./steps/discover_targets/detection.ts";
import type gatingPanel from "./steps/refine_targets/gate.ts";
import type { selectionPanel } from "./steps/target_scan_area/selection-panel.ts";

/** A function that takes the page first, as the page lends it: the page already given. */
type Lent<F> = F extends (page: never, ...rest: infer A) => infer R ? (...rest: A) => R : never;

/** What target acquisition lends its page, by the names its steps call (`on-the-page.js`). */
export type Lends = {
  pictureOf: Lent<typeof helpers.pictureOf>;
  redrawSoon: Lent<typeof helpers.redrawSoon>;
  /** Generic over what the step tells its slot, which `Lent` would drop: the options come back with it. */
  recordingOptions: <O extends Parameters<typeof helpers.recordingOptions>[1]>(opts: O) =>
    ReturnType<typeof helpers.recordingOptions<O>>;
  scannedPlan: Lent<typeof helpers.scannedPlan>;
  tilesetOfField: Lent<typeof helpers.tilesetOfField>;
  chosenInstrument: Lent<typeof connect.chosenInstrument>;
  chosenMicroscope: Lent<typeof connect.chosenMicroscope>;
  listInstruments: Lent<typeof connect.listInstruments>;
  listProtocols: Lent<typeof connect.listProtocols>;
  renderSetup: Lent<typeof connect.renderSetup>;
  theRestOfTheProtocolAppears: Lent<typeof connect.theRestOfTheProtocolAppears>;
  activePreset: Lent<typeof scanArea.activePreset>;
  rebuildPlan: Lent<typeof scanArea.rebuildPlan>;
  testTilesChanged: Lent<typeof testTilesChanged>;
  overviewGoesGreyForTheMasks: Lent<typeof overviewGoesGreyForTheMasks>;
  selectTarget: Lent<typeof acquire.selectTarget>;
  targetAt: Lent<typeof acquire.targetAt>;
  targetPressed: Lent<typeof acquire.targetPressed>;
  protocolWithin: Lent<typeof protocolWithin>;
  renderProtocolProgress: Lent<typeof renderProtocolProgress>;
  focusFitWord: typeof focusFitWord;
  /** The clock reading where the stage is while a session is open. */
  stageWatch: StageWatch | null;
  /** Redraw the carrier panel's list of anchors: set by the panel when it mounts. */
  redrawAnchors: () => void;
} & CanvasOnThePage & FocusOnThePage & CarrierOnThePage;

/** The boxes this workflow's steps put on screen, while they are mounted. */
export interface Shown {
  session?: ReturnType<typeof renderSessionCard> | null;
  editor?: ReturnType<typeof scanfieldsWidget.render> | null;
  detection?: ReturnType<typeof detectionPanel.mount> | null;
  gating?: ReturnType<typeof gatingPanel.mount> | null;
  selection?: ReturnType<typeof selectionPanel.mount> | null;
  gallery?: ReturnType<typeof galleryWidget.mount> | null;
  scanProgress?: ProgressBox | null;
  playBurst?: (() => boolean) | null;
}

/** Target acquisition, as the workflow API's types take it. */
export interface TargetAcquisition extends WorkflowTypes {
  state: ReturnType<typeof freshState>;
  backend: Backend;
  lends: Lends;
  shown: Shown;
  step: Record<never, never>;
}

/** This workflow's page, as each of its steps is handed it. */
export type TaPage = Page<TargetAcquisition>;

/** This workflow's run document: the framework's keys and its own. */
export type TaRun = Run<TargetAcquisition>;

/** One of this workflow's steps. */
export type TaStep = Step<TargetAcquisition>;

/** The run's picture beneath the plan, as the scan step's watcher opens it. */
export interface ThePicture {
  /** Whether there was a scan there to open, and it opened. */
  readonly opened: boolean;
  /** Whether the picture draws the acquisition of this name itself. */
  shows(name: string): boolean;
  open(): unknown;
  /** Put the scan where the plan is looking, exactly. */
  followTheStage(stageView?: Partial<View> | null): void;
  reopenIfTheRunGrew(): unknown;
  /** A field has landed, so there may be more of the scan to read. */
  mayHaveLanded(): unknown;
  /** The session is over, and what was opened belongs to it. */
  reset(): void;
  /** The drawing engine's picture, while one is open. */
  engine(): EngineViewer | null;
  /** The picture's display settings -- its acquisitions, their eyes and
      greys, its channels -- while they are on the page. */
  panel(): ViewerPanelElement | null;
}

/** The scan-field editor, while it is on screen. */
export type Editor = NonNullable<Shown["editor"]>;

/** The scan fields' widget: the plan, how it is drawn, and the editor it mounts. */
export type ScanfieldsWidget = typeof scanfieldsWidget;

/** The preset the whole plan is taken with, or null before one is recorded. */
export type ActivePreset = scanArea.RecordedPreset | null;
