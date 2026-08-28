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
    /* Asked each time rather than settled once: which backend is running is
       not known until the operator has connected, and this closure is built
       before the page has anything on it. */
    const pointedAt = () => search.get("picture") ?? ctx.pictures?.("overview") ?? null;
    const engine = search.get("engine") ?? "jpeg-under";
    const host = ctx.pictureHost;
    let viewer = null;
    let opening = false;

    async function open() {
      const asked = pointedAt();
      if (!asked || viewer || opening) return;
      opening = true;
      try {
        const openViewer = await openerFor(engine);
        viewer = await openViewer(host, {
          acquisitions: [{ url: asked, name: asked.split("/").filter(Boolean).pop() ?? "scan" }],
          /* The same colour the page paints, so the seam between the scan's own
             background and the ground above it never shows. */
          background: ctx.css("--screen"),
        });
        /* Left where a test can reach it. What matters about a picture is what
           reached the screen, and a viewer that reports itself perfectly opened
           while drawing nothing is the failure this project keeps meeting — so
           the tests photograph the box, and this is only the way to ask it
           where it is looking. */
        window.__thePicture = viewer;
        followTheStage();
      } catch (e) {
        console.error(`the scan at ${asked} could not be opened by ${engine} — ${e.message}`);
      } finally {
        opening = false;
      }
    }

    /** Put the scan where the plan is looking, exactly. */
    function followTheStage() {
      if (!viewer) return;
      /* The same two numbers the picture above is drawn with, handed over as
         they are. This used to be worked out from a pan offset and a scale, in
         a second piece of arithmetic that had to agree with the first; when the
         picture above moved to the shared canvas those numbers stopped existing
         and the scan quietly drew nowhere. Asking for the view is one answer
         instead of two. */
      viewer.setView(ctx.view());
    }

    return {
      /** Whether this page was pointed at a scan at all. */
      get asked() { return !!pointedAt(); },
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
