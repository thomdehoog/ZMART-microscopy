/**
 * Acquiring the targets: a scan whose positions are the planned target
 * tiles, driven in the stage's frame like the overview was, with a
 * focussing stack first at each when the operator asked for one.
 *
 * The picture follows the run: when the stage moves on to a tile, the pair
 * that just landed stays in view for a moment, then the picture centres on
 * the tile being taken. A row chosen by hand ends the following for this
 * run; the next run follows again.
 */

import { status } from "zmart-interface/api";
import { activeRecording } from "../../microscope/recordings.ts";
import carrierWidget from "../../shared/carrier-panel.ts";
import type { RunAnswer } from "zmart-interface/api";
import type { CaptureRecord } from "../../backend/verbs.ts";
import type { TargetFocussing, TargetTile } from "../../shared/run-document.ts";
import type { TaPage, TaRun, TaStep } from "../../types.ts";

/** A target's capture record, with what the target run adds to it: how wide the frame is, when it was taken, and its focussing. */
interface TargetRecord extends CaptureRecord {
  frame_um?: number;
  taken?: unknown;
  focus?: TargetFocussing | null;
}

/* The pause before the picture moves on to the tile being taken, which
   gives the pair that just landed a moment in view. */
const FOLLOW_THE_RUN_AFTER_MS = 3000;
const followTheRun = { on: false, timer: null as ReturnType<typeof setTimeout> | null, done: -1 };

/** The operator's hand chose a tile: the picture stops following the run. */
export function stopFollowingTheRun(): void {
  followTheRun.on = false;
  clearTimeout(followTheRun.timer ?? undefined);
}

/**
 * Take every planned target tile, or the ones in `options.targetTiles`;
 * with `options.append`, what was acquired before stays in the gallery.
 */
export function runAcquisition(page: TaPage, s: TaStep, { targetTiles = null, append = false }: {
  targetTiles?: TargetTile[] | null; append?: boolean;
} = {}): Promise<RunAnswer> {
  const state = page.run;
  const gallery = page.shown.gallery;
  /* The tiles are the plan. Several may belong to one large target, and
     a tile shared by nearby targets may sit between their centres, so the
     stage is driven to the planned tile rather than back to a cell. */
  const picked = targetTiles ?? state.targetTiles;
  followTheRun.on = true;
  followTheRun.done = -1;
  const positionFor = (tile: TargetTile) => {
    const { x, y } = tile;
    const z = page.surfaceZAt(x, y);
    const positionIndex = tile.positionIndex ?? state.targetTiles.indexOf(tile);
    /* The focussing stack is taken on the object the tile was placed
       for, at its centre: a tile nudged to share its frame with
       neighbours may have its middle on background. */
    const object = state.cells.get(tile.targetId);
    const focusAt = object && Number.isFinite(object.x) && Number.isFinite(object.y)
      ? page.stage.toStage({ x: object.x, y: object.y }) : null;
    return {
      ...page.stage.toStage({
        ...(z === null ? { x, y } : { x, y, z }),
        position_index: Math.max(0, positionIndex),
      }),
      ...(focusAt ? { focusAt: { x: focusAt.x, y: focusAt.y } } : {}),
    };
  };
  const accountFor = (records: TargetRecord[], n = records.length) => {
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
        /* As wide as the capture actually is, once the record says; the
           recording's promise stands in only until it does. */
        frameUm: records[i]?.frame_um ?? tile.frameUm ?? state.targetFrameUm,
        label: records[i]?.position_label,
        taken: records[i]?.taken ?? null,
        focus: records[i]?.focus ?? null,
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
    gallery?.rebuild();
  }
  gallery?.progress?.({ start: true, of: picked.length, doing: "starting the acquisition…" });
  /* The page's own loop, tile by tile, with a focussing stack first
     when the operator asked for one under the target settings. */
  return page.backend.acquireTargets({
    positions: picked.map(positionFor),
    /* On top of the height each target would be taken at, map or peak. */
    zOffsetUm: state.targetZOffsetUm || 0,
    append,
    state: activeRecording(state.targetType)?.changeable ?? null,
    focus: state.targetFocusOn ? {
      state: activeRecording(state.targetFocus)?.changeable ?? null,
      metric: state.focus.metric,
      extent: carrierWidget.extentUm(state.carrier),
    } : null,
    /* Which half of a tile the run is in, in the box and the status bar. */
    onDoing: (sentence) => {
      if (state.running !== s.id) return;
      if (sentence) { status.say(sentence); gallery?.progress?.({ doing: sentence }); }
    },
    /* Each capture prints itself onto the canvas as it lands, the way the
       overview's tiles do: the records so far name the pictures, and only
       the cells with a record are drawn as acquired. */
    onProgress: (done, of, at, records = []) => {
      if (state.running !== s.id) return;
      /* The mark keeps up with the stage tile by tile, as it does
         through the overview scan: the watch is asked now rather than
         at its own next poll. The finished record's position is not
         the mark -- see the scan. */
      page.stageWatch?.refresh();
      accountFor(records);
      state.notes[s.id] = `${done} / ${picked.length} pairs`;
      page.protocolWithin(done, picked.length);
      /* The tile under the objective now, by its target's id: what is
         being taken, beside how far along the run is. */
      const next = picked[Math.min(done, picked.length - 1)];
      /* And the frame on the picture goes with it: the current target
         tile is the one being taken, so the frame stands where the
         acquisition is rather than where Tile last left it. */
      state.detect.targetTile = next.positionIndex ?? state.targetTiles.indexOf(next);
      if (followTheRun.on && done !== followTheRun.done && done < picked.length) {
        followTheRun.done = done;
        clearTimeout(followTheRun.timer ?? undefined);
        followTheRun.timer = setTimeout(() => {
          if (followTheRun.on && state.running === s.id) page.stage.standOn(next);
        }, FOLLOW_THE_RUN_AFTER_MS);
      }
      gallery?.progress?.({ done, of: picked.length });
      /* The list beside the canvas grows with the rings on it. */
      gallery?.rebuild();
      page.redrawSoon(); page.renderAll();
    },
  }).then(({ records, stopped }) => {
    stopFollowingTheRun();
    /* A stopped run accounts for what it took, and claims nothing more:
       only the cells with a record are acquired. */
    accountFor(records, stopped ? records.length : picked.length);
    page.redrawSoon();
    /* The gallery shows what was acquired, stopped or not: a run put
       down by hand after two pairs showed its two rings on the canvas
       and an empty gallery beside them. */
    gallery?.rebuild();
    gallery?.progress?.({
      done: records.length, of: picked.length,
      ended: true, note: stopped ? "stopped by hand" : `${records.length} pairs acquired`,
    });
    return stopped
      ? { stopped: true, note: `stopped by hand — ${records.length} of ${picked.length} pairs acquired` }
      : undefined;
  }, (why: Error) => {
    gallery?.progress?.({ ended: true, failed: true, note: `failed — ${why.message}` });
    throw why;
  });
}

export function acquisitionFinished(page: TaPage, s: TaStep): void {
  page.run.notes[s.id] = `${page.run.acquired.length} pairs acquired`;
}

/** The current tile taken again, as it stands now: the operator may have
    moved it, or remeasured the focus map, since it was last taken. The
    stored copy is only the fallback for a tile no longer in the plan.
    Answers the options for `runStep`, worked out at the press. */
export function rerunCurrentTile(page: TaPage): (() => { targetTiles: TargetTile[]; append: boolean }) | null {
  const state = page.run;
  const currentFrame = state.selectedTarget === null ? undefined : state.acquiredTiles[state.selectedTarget];
  if (!currentFrame?.tile) return null;
  return () => {
    const fresh = state.targetTiles.find((tile) => tile.key === currentFrame.tile.key);
    return { targetTiles: [fresh ?? currentFrame.tile], append: true };
  };
}

/** What stands beside the press: the note, unless a tile is chosen, whose
    pair the gallery already describes. */
export function besideTheAcquisitionPress(state: TaRun): string | null {
  return state.selectedTarget !== null && state.acquiredTiles[state.selectedTarget] ? null : state.notes.acquire;
}
