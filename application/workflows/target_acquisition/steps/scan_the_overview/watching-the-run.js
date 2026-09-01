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
    /* What the canvas was last told to draw, so a run that has grown a second
       kind of acquisition is noticed and the canvas told again. */
    let showing = null;
    let telling = false;
    let panel = null;

    /**
     * What there is to draw, asked fresh each time.
     *
     * Two answers: a store the address named (`?picture=`, for looking at a
     * run from somewhere else), and the run's own OME-Zarr sources, served by
     * the viewer beside the bridge — the real picture, every acquisition type
     * a source of its own.
     *
     * **A third answer used to be the backend's small JPEG copies**, drawn by
     * an engine of their own, and it is gone. It existed because the run's own
     * images could not be opened at the scale a plate reaches; they can now,
     * and a whole plate of eight hundred and sixty-four fields has been drawn
     * from them. Keeping it cost more than it gave: the bridge built a small
     * JPEG for every field as the scan went and rewrote its note under a lock
     * each time, which is real work on the acquisition's own thread for a
     * picture nobody was looking at; and — the reason it is worth a paragraph
     * — it left the page always able to draw *something*, so when the real
     * path was broken the window still showed a scan and "the overview is not
     * showing up" looked like a quirk rather than a pipeline that had never
     * worked.
     */
    async function whatToDraw() {
      const picture = search.get("picture");
      if (picture) {
        return {
          acquisitions: [{
            url: picture,
            name: picture.split("/").filter(Boolean).pop() ?? "scan",
          }],
          signature: `picture:${picture}`,
        };
      }
      const sources = await ctx.viewerSources?.();
      if (sources?.length) {
        return {
          acquisitions: sources,
          signature: `sources:${sources.map((one) => one.url).join("|")}`,
        };
      }
      return null;
    }

    /**
     * Tell the canvas what the run has to show, if it has anything new.
     *
     * There is no viewer of its own here any more. The canvas draws the
     * acquisition itself — it is the only thing on this page that draws image
     * data — and this only hands it the addresses. What that removed, besides
     * a whole viewer, is the forwarding: the picture no longer has to be told
     * where the plan is looking, because they are the same picture.
     */
    async function draw() {
      if (telling) return;
      telling = true;
      try {
        const wanted = await whatToDraw();
        if (!wanted || wanted.signature === showing) return;
        await ctx.drawTheseAcquisitions(wanted.acquisitions);
        showing = wanted.signature;
        /* Left where a test can reach it. What matters about a picture is what
           reached the screen, and a viewer that reports itself perfectly
           opened while drawing nothing is the failure this project keeps
           meeting — so the tests photograph the box, and this is only the way
           to ask it where it is looking. */
        window.__thePicture = ctx.picture();
        await putThePanelUp(wanted);
      } catch (why) {
        console.error(`the run's picture could not be drawn — ${why.message}`);
      } finally {
        telling = false;
      }
    }

    /* The viewer's own controls — the acquisitions and their channels — on the
       left, the workflow's step panels keeping the right. Built again whenever
       what is drawn changes, because the rows it lists are the picture's. */
    async function putThePanelUp(wanted) {
      /* Which channel the operator had the settings pointed at, kept across
         the rebuild. This happens in the middle of a scan — the run lands its
         first target acquisition and the list of channels changes underneath
         whoever is working in it — and without this the settings jump back to
         the first channel of the first acquisition, so somebody part-way
         through choosing a colour finds themselves adjusting something else.
         It is carried by name rather than by position, because a position is
         still a valid number after a rebuild and would quietly refer to a
         different channel. */
      const wasInHand = panel?.theChannelInHand?.() ?? null;
      panel?.destroy?.();
      panel = null;
      window.__viewerPanelHandle = null;
      const picture = ctx.picture();
      if (!picture || !wanted.acquisitions.length) return;
      const { mountViewerPanel } = await import("../../../../parts/canvas/viewer-panel.js");
      panel = await mountViewerPanel(ctx.panelHost ?? ctx.pictureHost, {
        viewer: picture, acquisitions: wanted.acquisitions, css: ctx.css,
        startOn: wasInHand,
      });
      /* Left where a test can reach it, beside the picture itself: what the
         panel says about the picture is as much a part of what an operator
         sees as the picture is, and a photograph cannot tell a truthful eye
         from a stale one. */
      window.__viewerPanelHandle = panel;
    }

    function reset() {
      panel?.destroy?.();
      panel = null;
      window.__viewerPanelHandle = null;
      showing = null;
      window.__thePicture = null;
      ctx.drawTheseAcquisitions([]);
    }

    /* Left where a test can reach it: when the picture is missing, the one
       question that matters is whether the page believes it is drawing, is
       still opening, or has given up — and only the page can answer. */
    window.__thePictureState = () => ({
      opened: !!ctx.picture(), opening: telling, openedOn: showing,
    });

    return {
      /** Whether this page was pointed at a scan by its own address. The run's
          sources are asked for asynchronously, so they do not answer here. */
      get asked() { return !!search.get("picture"); },
      /** Whether there is a picture being drawn. */
      get opened() { return !!showing; },
      open: draw,
      /** Nothing to follow any more: the plan and the picture are one canvas. */
      followTheStage() {},
      reopenIfTheRunGrew: draw,
      /** A field has landed, so there may be more of the scan to read. */
      mayHaveLanded() { ctx.picture()?.tilesMayHaveLanded?.(); },
      /** The session is over, and what was drawn belongs to it. A reconnect is
          a fresh session: its run starts with nothing scanned, and the picture
          of the last one must not stand in for it. */
      reset,
    };
  })();

  /* Opened at once when the page was pointed at a scan. It is not opened lazily
     on the first draw, because the first draw is also the first thing an
     operator sees, and a picture that arrives a moment after everything else
     reads as the page having stumbled. */
  thePicture.open();

  /* One clock, doing both halves of the same job. Nothing on disk announces a
     new field, so the scan has to be asked for rather than told — and nothing
     announces the *first* field either: a scan that has imaged nothing has no
     note to open, so the picture cannot be opened until one lands.

     This used to hang off the overview's own heartbeat, which meant a page
     watching a scan and nothing else — the ordinary case for a run the page is
     taking itself — opened once against an empty run, failed, and never asked
     again. The picture stayed black for the whole acquisition.

     A run that has stopped changing simply draws the same picture again, so
     the cost of this when there is nothing new is one small request every
     couple of seconds. */
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
