/**
 * What this workflow puts on its canvas, wired to the page: the stage
 * picture, the live picture of the run being acquired, and the axes under
 * them.
 *
 * The canvas panel itself is a part (`workflows/target_acquisition/canvas/`) and knows nothing
 * about any workflow. This file is the workflow's side of it: it opens the
 * stage picture (`shared/stage.ts`) and the live overview
 * (`steps/scan_the_overview/watching-the-run.ts`) on that panel, hands them
 * the run and the few things they must be able to call back into, and gives
 * the page its own names for what it does to the picture.
 *
 * Everything the stage calls back into is reached through the page at call
 * time (`page.anchorPressed`, ...), because the steps that answer those calls
 * are wired after the canvas is.
 */

import { mountTheAxes } from "./canvas/axes.ts";
import { showPublicationStatus } from "./canvas/publication-note.ts";
import { css, status, type BuiltPanel } from "zmart-interface/api";
import type { canvasPanel } from "./canvas/panel.ts";
import type { Axes } from "./canvas/axes.ts";
import type { View } from "./canvas/engines/opening-view.ts";
import type { theCanvasOf } from "./microscope/canvas.ts";
import { stageAt, type StageAt } from "./shared/stage-position.ts";
import type { TaPage, ThePicture } from "./types.ts";

/** The canvas panel as this workflow built it: the framework's panel, and its own parts. */
type TheCanvasPanel = BuiltPanel & ReturnType<NonNullable<typeof canvasPanel.build>> & { shown?: () => void };

/**
 * What the canvas lends the page. Written out rather than read off
 * `installTheCanvas`, because the page's own type is made of what is lent,
 * and a lend whose type came from the page would make the page's type
 * depend on itself.
 */
export interface CanvasOnThePage {
  stage: ReturnType<typeof openTheStage>;
  view: ReturnType<typeof openTheStage>["view"];
  theAxes: Axes;
  thePicture: ThePicture;
  drawStage(): void;
  carrierOriginUm(): [number, number];
  whereTheStageIs(): StageAt | null;
  takeTheCanvas(reading: Parameters<typeof theCanvasOf>[0]): void;
  takeThePosition(at: StageAt | null | undefined): void;
  drawScaleBar(ctx: CanvasRenderingContext2D, w: number, h: number, scale: number): void;
  renderFramingPresses(): void;
}

/** What a browser test may ask of the picture: read-only geometry and the layers' switches. */
interface TheStageCanvas {
  layers(): { key?: string; label?: string; shown?: boolean; staysSolid: boolean }[];
  showLayer(key: string, on: boolean): void;
  layerShown(key: string): boolean;
  acquisitionOnShow(): string | null;
  fadeTo(value: number): void;
  plan(): { x: number; y: number; frameUm: number; tileset: unknown }[];
  targets(): unknown[];
  project(x: number, y: number): [number, number];
  view(): View | null;
  lookAt(where: { centre?: { x: number; y: number }; zoom?: number }): void;
  carrierOriginUm(): [number, number];
  focusZAt(x: number, y: number): unknown;
  /** Where the stage mark stands: what `whereTheStageIs` answers. */
  stageAt(): StageAt | null;
}

declare global {
  interface Window {
    /** The T slider under the picture, for a browser test. */
    __theAxes?: Axes;
    /** The picture, for a browser test. */
    __theStageCanvas?: TheStageCanvas;
  }
}

/* How the status bar begins a drive the microscope declined. */
const REFUSED = "The stage did not go there: ";
import carrierWidget from "./shared/carrier-panel.ts";
import scanfieldsWidget from "./steps/define_scan_area/scanfield-editor.ts";
import { watchTheRun } from "./steps/scan_the_overview/watching-the-run.ts";
import { openTheStage } from "./shared/stage.ts";
/* What each step draws on the picture, in no particular order: the stack's
   order is the picture's own (`THE_STACK` in `shared/stage.ts`). */
import { carrierLayers } from "./steps/define_carrier/layers.ts";
import { scanAreaLayers } from "./steps/define_scan_area/layers.ts";
import { focusLayers } from "./steps/focus_strategy/layers.ts";
import { overviewLayers } from "./steps/scan_the_overview/layers.ts";
import { targetLayers } from "./steps/discover_targets/layers.ts";
import { acquiredLayers } from "./steps/acquire_targets/layers.ts";
import { MASK_RAINBOW } from "./steps/discover_targets/mask-dress.ts";

/**
 * Open the canvas on the page. Answers `stage`, `view`, `drawStage`,
 * `thePicture`, `theAxes`, the stage's readings
 * (`whereTheStageIs`, `carrierOriginUm`, `takeTheCanvas`, `takeThePosition`,
 * `drawScaleBar`) and `renderFramingPresses`.
 */
export function installTheCanvas(page: TaPage): CanvasOnThePage {
  const { run: state, panels: thePanels, step, indexOfStep } = page;

  /* The canvas panel this workflow declared, and everything that draws in it. */
  const theCanvas = thePanels.canvas as TheCanvasPanel;
  /* The T slider under the picture, on whichever picture is open. It asks
     only once the page is running, so the picture below is there by then. */
  const theAxes = mountTheAxes(theCanvas.parts, { picture: () => thePicture.engine() });
  window.__theAxes = theAxes;

  /* The picture of a real run: the scan beneath the plan. The scan step's, so
     it lives with it; this hands it the box and the projection and asks it to
     draw. */
  const { thePicture } = watchTheRun({
    pictureHost: theCanvas.parts.pictureHost,
    /* Where this backend's scans can be fetched from, if anywhere. The live
       one serves what the microscope wrote; the pretend one has nothing. */
    /* The run's OME-Zarr sources, as the viewer server beside the bridge
       serves them — the real picture, linked position by position. `null`
       while there is none, and the JPEG copies stand in.

       Both answer nothing once the session is closed. The backend object
       outlives the session, and its addresses used to be handed out after
       Disconnect, so the page reopened an empty JPEG picture on a bridge
       that had no run to serve. */
    viewerSources: () => {
      const report = (status: Parameters<typeof showPublicationStatus>[1]) => showPublicationStatus(theCanvas.parts.publicationNote, status);
      if (!state.done.has("connect")) { report(null); return null; }
      return page.backend?.viewerSources?.(report) ?? null;
    },
    connected: () => state.done.has("connect"),
    view: () => stage.pictureView(),
    carrierOriginUm: () => stage.carrierOriginUm(),
    /* Where the picture's own panel is mounted, out of sight; and the word
       that the picture came or went, so what wears its settings is drawn
       again. */
    displayHost: () => theCanvas.display,
    displayChanged: () => {
      theAxes.refresh();
      /* The gallery's pairs wear the picture's settings: rows that have just
         come -- the targets' own, at the end of their run -- are what its
         first pair should already be drawn with. */
      page.shown.gallery?.rebuild();
    },
    /* A display control changed after the panel was mounted. The available
       tabs did not change, only displayed copies that use the snapshot did.
       The gallery's pairs and the detection card both wear the overview's
       dress, colour or grey, so both are drawn again when it changes. */
    displaySettingsChanged: () => { page.shown.gallery?.rebuild(); page.shown.detection?.redraw(); },
    css,
  });

  /* The stage picture — the run drawn to scale, layer on layer. It is the
     workflow's, so it lives with the workflow; the framework hands it the canvas,
     the run, and the few things it must be able to call back into. */
  const stage = openTheStage({
    pictureHost: theCanvas.parts.pictureHost,
    box: theCanvas.parts.box,
    layerBar: theCanvas.parts.layerBar,
    tip: theCanvas.parts.tip,
    readout: theCanvas.parts.readout,
    carrierButton: theCanvas.parts.carrier,
    tilesetButton: theCanvas.parts.tileset,
    tileButton: theCanvas.parts.tile,
    masksBar: theCanvas.parts.masksBar,
    maskCells: theCanvas.parts.maskCells,
    maskName: theCanvas.parts.maskName,
    maskHow: theCanvas.parts.maskHow,
    maskEye: theCanvas.parts.maskEye,
    maskOpacityValue: theCanvas.parts.maskOpacityValue,
    channelPop: theCanvas.parts.channelPop,
    greyChip: theCanvas.parts.greyChip,
    greyChipMore: theCanvas.parts.greyChipMore,
    greyPop: theCanvas.parts.greyPop,
    maskPop: theCanvas.parts.maskPop,
    acquisitionPick: theCanvas.parts.acquisitionPick,
    acquisitionName: theCanvas.parts.acquisitionName,
    acquisitionEye: theCanvas.parts.acquisitionEye,
    acquisitionMenu: theCanvas.parts.acquisitionMenu,
    chips: theCanvas.parts.chips,
    channelsBox: theCanvas.parts.channelsBox,
    maskColours: theCanvas.parts.maskColours,
    maskFill: theCanvas.parts.maskFill,
    maskLine: theCanvas.parts.maskLine,
    maskOpacity: theCanvas.parts.maskOpacity,
    rampChip: theCanvas.parts.rampChip,
    legend: theCanvas.parts.legend,
    css,
    run: state,
    /* The boxes the steps put on screen; the scan-field editor among them. */
    shown: page.shown,
    carrierWidget, scanfieldsWidget,
    stepLayers: [carrierLayers, scanAreaLayers, focusLayers, overviewLayers, targetLayers, acquiredLayers],
    maskRainbow: MASK_RAINBOW,
    activePreset: () => page.activePreset(),
    indexOfStep,
    activeStep: () => page.activeStep(),
    step: () => step(state.activeIdx),
    anchorPressed: (...a) => page.anchorPressed(...a),
    /* The list of anchors is drawn by the carrier panel, so a mark dragged on
       the picture has to tell it the numbers moved. A mark dragged on the
       picture is the carrier edited; a mark merely pressed is not, and the
       layer says which. */
    anchorsChanged: (moved = false) => { page.redrawAnchors(); if (moved) page.stateEdited("carrier"); },
    testTilesChanged: () => page.testTilesChanged(),
    /* A tile chosen on the canvas appears in the test box at once. */
    tileChosen: () => page.shown.detection?.redraw(),
    detectPressed: (...a) => page.detectPressed(...a),
    targetPressed: (...a) => page.targetPressed(...a),
    targetAt: (world, reachUm) => page.targetAt(world, reachUm),
    renderActionBar: () => page.renderActionBar(),
    renderRail: () => page.renderRail(),
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
     * A refusal is said in the status bar, in the microscope's own words:
     * a double-click that does nothing, with no reason, looks like a fault.
     */
    driveTo: async ({ x, y }) => {
      if (!page.backend?.set_xyz || state.running) return null;
      try {
        const at = await page.backend.set_xyz({ x, y });
        /* The last refusal, if it is still showing, is no longer true. */
        if (document.getElementById("status-bar")?.textContent?.startsWith(REFUSED)) status.quiet();
        return stageAt(at);
      } catch (why) {
        status.say(`${REFUSED}${(why as Error).message}`);
        return null;
      }
    },
    thePicture,
    focus: {
      focusPressed: (...a) => page.focusPressed(...a),
      focusCursor: (...a) => page.focusCursor(...a),
      focusDraggedTo: (...a) => page.focusDraggedTo(...a),
      focusGrabbed: (...a) => page.focusGrabbed(...a),
      focusHovered: (...a) => page.focusHovered(...a),
      focusMarqueeTo: (...a) => page.focusMarqueeTo(...a),
      focusMarqueeTook: (...a) => page.focusMarqueeTook(...a),
      drawFocusLayer: (...a) => page.drawFocusLayer(...a),
      drawFocusPoints: (...a) => page.drawFocusPoints(...a),
      marqueeing: () => page.focusMap.marqueeing(),
      dragging: () => page.focusMap.dragging(),
      endDrag: () => page.focusMap.endDrag(),
    },
  });

  /* Left where a test can reach it: what matters about a picture is what
     reached the screen, and only the page can be asked. */
  window.__theStageCanvas = {
    layers: () => stage.layers(),
    showLayer: (key, on) => stage.showLayer(key, on),
    layerShown: (key) => stage.layerShown(key),
    acquisitionOnShow: () => stage.acquisitionOnShow?.() ?? null,
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
    focusZAt: (x, y) => page.surfaceZAt(x, y),
    stageAt: () => stage.whereTheStageIs(),
  };

  /* The canvas's three framing presses -- carrier, tile set, tile -- are
     about a stage, and there is no stage until a session is open. They
     appear with the connection and go with it, rather than standing over
     an empty canvas offering to frame what is not there. */
  function renderFramingPresses() {
    const connected = state.done.has("connect");
    const parts = theCanvas.parts;
    for (const press of [parts.carrier, parts.tileset, parts.tile]) {
      if (press) press.hidden = !connected;
    }
  }
  /* A picture cannot be laid out while it is hidden: a hidden box has no
     size. So the panel re-measures when it comes up. */
  theCanvas.shown = () => stage.resize();
  const ro = new ResizeObserver(() => {
    if (theCanvas.host.classList.contains("on")) stage.resize();
  });
  ro.observe(theCanvas.host);

  return {
    stage, view: stage.view, theAxes, thePicture,
    drawStage: () => stage.draw(),
    carrierOriginUm: () => stage.carrierOriginUm(),
    whereTheStageIs: () => stage.whereTheStageIs(),
    takeTheCanvas: (reading: Parameters<typeof theCanvasOf>[0]) => stage.takeTheCanvas(reading),
    takeThePosition: (at: StageAt | null | undefined) => stage.takeThePosition(at),
    drawScaleBar: (...a: Parameters<typeof stage.drawScaleBar>) => stage.drawScaleBar(...a),
    renderFramingPresses,
  };
}
