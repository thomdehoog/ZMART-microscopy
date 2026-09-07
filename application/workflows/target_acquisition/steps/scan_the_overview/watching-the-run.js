/**
 * Watching a real run: the pictures the microscope is writing, on the canvas.
 *
 * Everything else on this page is a rehearsal — a synthetic sample, a stage
 * that moves on a timer. These two are not. Point the page at a run with
 * `?overview=` (and `?targets=`, `?picture=`) and it opens what is on disk:
 *
 *   the overview being acquired, over the plan, while the scan step is stood
 *   on — the tiles appearing as they land rather than a count of them;
 *
 *   the scan beneath the plan, in the same projection as the plan itself, so
 *   the two are registered rather than merely near each other.
 *
 * Nothing on disk announces a saved tile: the images are declared at their
 * full size before any of them exists, so their description never changes.
 * Both pictures are therefore asked again rather than told — by the step as
 * positions land, and by a heartbeat while the scan is on screen, because a
 * real acquisition goes on long after this page's rehearsal has finished.
 */

/**
 * Open both, on the canvases this page hands over.
 *
 * `ctx` carries the two canvases and the note, the projection the plan is
 * drawn in (so the scan beneath can be put in the same one), and the page's
 * colour lookup. Returns the two pictures.
 */
import { openerFor } from "../../../../parts/canvas/engines.js";

export function watchTheRun(ctx) {
  const ACQUISITIONS = (() => {
    const asked = new URLSearchParams(location.search);
    return [asked.get("overview"), asked.get("targets")].filter(Boolean);
  })();
  const RUN_TO_WATCH = ACQUISITIONS[0] ?? null;


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
     are two different things worth telling apart. `steps/scan_the_overview/overview.js` explains
     what it does and why it has to exist. */
  const SEE_THROUGH = new URLSearchParams(location.search).get("seethrough") === "1";

  /**
   * The scan itself, drawn beneath the plan by one of the drawing engines.
   *
   * A folder of small JPEGs with a `tiles.json` saying where each belongs —
   * what `viz_studio/backend/jpeg_tiles.py` makes from the files a microscope
   * exports, one per field as it lands. The backend says where its own are
   * (`viewOf`), because where a run's output is reachable is a fact about the
   * instrument's end; `?picture=<folder>` overrides it, which is how a run
   * served from somewhere else is looked at. Nothing is opened while neither
   * names a folder, because an engine is a large thing to fetch and a page
   * with no scan to draw has no use for one.
   *
   * Which engine draws it is `?engine=`, and the default is the JPEG one.
   * Every engine is reached through `openerFor`, the one interface they all
   * sit behind, so swapping in neuroglancer is choosing a different name and
   * changes nothing here.
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
    const search = new URLSearchParams(location.search);
    const host = ctx.pictureHost;
    let viewer = null;
    let opening = false;
    let checkingForGrowth = false;
    let generation = 0;
    /* What the open viewer was opened on, so a change — the run growing a
       second kind of scan — is noticed and the viewer reopened over it. */
    let openedOn = null;
    /* The names of the acquisitions the open picture draws. */
    let openedNames = [];
    let inStageFrame = true;
    let panel = null;
    const requestedPanelState = {
      acquisitions: new Map(),
      channels: new Map(),
      collapsed: new Map(),
      selectedKey: null,
      lastMismatch: null,
    };

    /* Every address that materially shapes a Viewer acquisition.  Smart
       Viewer puts the position stores on the channel rows, not beside the
       acquisition.  Leaving those addresses out made a growing run look
       unchanged after its first field, so the engine never received fields
       two through nine. */
    const addressesIn = (acquisitions) => acquisitions.flatMap((acquisition) => {
      const channelSources = (acquisition.channels ?? []).flatMap(
        (channel) => channel.sources ?? [],
      );
      return channelSources.length ? channelSources : [acquisition.url];
    }).filter(Boolean);

    /**
     * What there is to draw, asked fresh each time.
     *
     * Two answers, in order of preference: a store the address named
     * (`?picture=`, taken as it is); and the run's own OME-Zarr sources,
     * served by the viewer beside the bridge — the real picture, every
     * acquisition type a source of its own. The backend's JPEG copies are
     * not a third: the canvas opened on them first and reopened on the
     * sources a moment later, a picture changing under the operator for
     * nothing. `?engine=` still overrides the engine, so the comparisons
     * stay askable.
     */
    async function whatToOpen() {
      const picture = search.get("picture");
      if (picture) {
        return {
          engine: search.get("engine") ?? "jpeg-under",
          acquisitions: [{ url: picture, name: picture.split("/").filter(Boolean).pop() ?? "scan" }],
          signature: `picture:${picture}`,
          inStageFrame: false,
        };
      }
      const sources = await ctx.viewerSources?.();
      // An unavailable response is not an instruction to remove loaded images.
      if (sources == null && viewer) return null;
      if (sources?.length) {
        /* The engine draws acquisitions in the order supplied, first at the
           bottom. The overview is the base map and focussing is the local
           diagnostic overlay whose eye must make pixels appear and disappear,
           so keep that overlay last without changing any Viewer acquisition,
           channel, or source. */
        const drawOrder = [
          ...sources.filter(({ name }) => name !== "focussing"),
          ...sources.filter(({ name }) => name === "focussing"),
        ];
        return {
          engine: search.get("engine") ?? "neuroglancer-under",
          acquisitions: drawOrder,
          signature: `sources:${addressesIn(drawOrder).join("|")}`,
          inStageFrame: true,
        };
      }
      return ctx.connected?.() ? {
        engine: search.get("engine") ?? "neuroglancer-under",
        acquisitions: [], signature: "sources:", inStageFrame: true,
      } : null;
    }

    async function open() {
      if (viewer || opening) return;
      opening = true;
      const session = generation;
      try {
        const wanted = await whatToOpen();
        if (!wanted || session !== generation) return;
        const openViewer = await openerFor(wanted.engine);
        if (session !== generation) return;
        const opened = await openViewer(host, {
          acquisitions: wanted.acquisitions,
          presentation: "2d-overlay",
          transparentBackground: true,
          // NG's colour setting accepts RGB; its separate flag clears alpha.
          background: wanted.engine === "jpeg-under" ? "transparent" : ctx.css("--screen"),
        });
        if (session !== generation) {
          opened.destroy();
          return;
        }
        viewer = opened;
        openedOn = wanted.signature;
        openedNames = wanted.acquisitions.map(({ name }) => name);
        inStageFrame = wanted.inStageFrame;
        /* Left where a test can reach it. What matters about a picture is what
           reached the screen, and a viewer that reports itself perfectly opened
           while drawing nothing is the failure this project keeps meeting — so
           the tests photograph the box, and this is only the way to ask it
           where it is looking. */
        window.__thePicture = viewer;
        followTheStage();
        /* The viewer's own controls — the acquisitions and their channels —
           in the column the page keeps for them beside the step's channel
           (the display settings, a tab away), or beside the picture when the
           page keeps no such column. Only for the run's own sources: a JPEG
           copy has no channels to offer. */
        panel?.destroy?.();
        panel = null;
        if (wanted.signature.startsWith("sources:")) await mountPanel(wanted, session);
        if (session !== generation) return;
        ctx.displayChanged?.();
      } catch (e) {
        console.error(`the scan could not be opened — ${e.message}`);
      } finally {
        if (session === generation) opening = false;
      }
    }

    async function mountPanel(wanted, session) {
      const { mountViewerPanel } = await import("../../../../parts/canvas/viewer-panel.js");
      if (session !== generation) return;
      const mounted = await mountViewerPanel(host.parentElement ?? host, {
        viewer, acquisitions: wanted.acquisitions, css: ctx.css,
        requestedState: requestedPanelState,
        into: ctx.displayHost?.() ?? null,
        changed: () => ctx.displaySettingsChanged?.(),
      });
      if (session !== generation) mounted.destroy();
      else panel = mounted;
    }

    /** Put the scan where the plan is looking, exactly. */
    function followTheStage(stageView = null) {
      if (!viewer) return;
      /* The same two numbers the picture above is drawn with, handed over as
         they are. This used to be worked out from a pan offset and a scale, in
         a second piece of arithmetic that had to agree with the first; when the
         picture above moved to the shared canvas those numbers stopped existing
         and the scan quietly drew nowhere. Asking for the view is one answer
         instead of two. */
      /* A view-change callback carries the committed new view. Asking the
         stage engine for it again from inside that callback can return the
         previous frame and makes this picture visibly lag during zooming. */
      const v = stageView ?? ctx.view();
      if (inStageFrame && v?.centre) {
        const [ox, oy] = ctx.carrierOriginUm();
        viewer.setView({ ...v, centre: { x: v.centre.x + ox, y: v.centre.y + oy } });
        return;
      }
      viewer.setView(v);
    }

    /** Append positions and acquisition rows without retiring loaded images.
        Only removal or replacement of sources needs a different scene. */
    async function reopenIfTheRunGrew() {
      if (!viewer || opening || checkingForGrowth) return;
      checkingForGrowth = true;
      const session = generation;
      try {
        const wanted = await whatToOpen();
        if (session !== generation || !wanted || wanted.signature === openedOn) return;
        // Stop the old panel's indexed measurements before rows can move.
        const sameRows = await panel?.sourcesChanged(wanted.acquisitions);
        if (session !== generation) return;
        if (panel && !sameRows) {
          panel.destroy();
          panel = null;
        }
        if (wanted.signature.startsWith("sources:")
            && openedOn?.startsWith("sources:")
            && await viewer.addSources?.(wanted.acquisitions)) {
          if (session !== generation) return;
          openedOn = wanted.signature;
          openedNames = wanted.acquisitions.map(({ name }) => name);
          followTheStage();
          if (!panel) await mountPanel(wanted, session);
          if (session !== generation) return;
          /* New rows -- a fresh acquisition's channels -- are new display
             settings for everything drawn with them: the page is told, the
             way it is when the settings first come. */
          ctx.displayChanged?.();
          return;
        }
        if (session !== generation) return;
        closePicture();
        await open();
      } finally {
        if (session === generation) checkingForGrowth = false;
      }
    }

    function closePicture({ forgetVisibility = false } = {}) {
      generation += 1;
      opening = false;
      checkingForGrowth = false;
      panel?.destroy?.();
      panel = null;
      ctx.displayChanged?.();
      viewer?.destroy?.();
      viewer = null;
      openedOn = null;
      openedNames = [];
      window.__thePicture = null;
      if (forgetVisibility) {
        requestedPanelState.acquisitions.clear();
        requestedPanelState.channels.clear();
        requestedPanelState.collapsed.clear();
        requestedPanelState.selectedKey = null;
        requestedPanelState.lastMismatch = null;
      }
    }

    return {
      /** Whether this page was pointed at a scan by its own address. The run's
          sources are asked for asynchronously, so they do not answer here. */
      get asked() { return !!search.get("picture"); },
      /** Whether there was a scan there to open, and it opened. */
      get opened() { return !!viewer; },
      /** Whether the picture draws the acquisition of this name itself. A
          layer that would print copies of it asks first: the engine's own
          pixels answer to the display settings, copies laid over them would
          not. */
      shows(name) { return openedNames.includes(name); },
      open,
      followTheStage,
      reopenIfTheRunGrew,
      /** A field has landed, so there may be more of the scan to read. */
      mayHaveLanded() { viewer?.tilesMayHaveLanded?.(); },
      /** The session is over, and what was opened belongs to it. A reconnect
          is a fresh session: its run starts with nothing scanned, and the
          picture of the last one must not stand in for it. */
      reset() { closePicture({ forgetVisibility: true }); },
    };
  })();

  /* Opened at once when the page was pointed at a scan. It is not opened lazily
     on the first draw, because the first draw is also the first thing an
     operator sees, and a picture that arrives a moment after everything else
     reads as the page having stumbled. */
  thePicture.open();

  // Open an empty viewer after Connect, then poll for published sources and
  // refresh existing ones. There is no separate step-4/step-5 viewer lifecycle.
  setInterval(() => {
    if (thePicture.opened) {
      thePicture.mayHaveLanded();
      /* And whether the run has grown a source the open viewer does not
         hold — the targets landing beside the overview, say. The check is
         one small request, and nothing happens while the answer is the one
         already open. */
      thePicture.reopenIfTheRunGrew();
    } else {
      /* Asked even when the page's own address names nothing: the run's
         sources appear only once something has been captured, and the page
         cannot know when that is without asking. */
      thePicture.open();
    }
  }, 1500);

  const liveOverview = (() => {
    const cv = ctx.overviewCanvas;
    const note = ctx.overviewNote;
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
        const { showOverview } = await import("./overview.js");
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

  return { thePicture, liveOverview };
}
