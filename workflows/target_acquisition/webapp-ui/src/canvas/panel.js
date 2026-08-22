/**
 * The canvas, put inside the operator window as a panel of its own.
 *
 * This is the page's side of the canvas: it finds a run to draw, opens one of
 * the drawing engines on it, gives the operator the two ways of moving around,
 * and lets the engine be changed without losing the view. Everything to do with
 * how a picture is actually drawn lives on the other side of a small interface,
 * in `viz_studio/options/`, and this file reaches it only through that.
 *
 * ## What the canvas is never told
 *
 * The canvas is handed a run to draw and, if the page wants them, two functions
 * to draw with. It is not told which step it is in, which workflow it belongs
 * to, or what the operator has done so far. That is deliberate. A picture that
 * has learned the shape of one workflow cannot be moved into the next one
 * without being taken apart again, and the whole reason for building the canvas
 * behind one small interface is that it can be put anywhere. If wiring it into
 * some future step ever seems to want a piece of run state passed in, that is a
 * sign the step wants something the interface does not yet offer, and the
 * interface is where the answer belongs.
 *
 * ## The three layers, and the three buttons that turn them on and off
 *
 * The picture an operator looks at is three drawings stacked one over the other.
 * At the bottom is the application's own drawing — the carrier, the positions
 * the microscope will visit, a region marked out by hand. In the middle is the
 * acquisition itself, read from the run. On top is more of the application's own
 * drawing, the part that has to stay visible over the picture rather than under
 * it. The interface offers the outer two as slots that take a function, and this
 * panel gives each of the three a button, so that what each layer contributes
 * can be seen by taking it away.
 *
 * The bottom slot is the one place where the three engines genuinely differ, and
 * the difference is not hidden here. Each viewer answers `drawsUnder` — whether
 * a drawing handed to the bottom slot really ends up beneath the picture — and
 * `drawsUnderBecause`, one sentence saying why it is what it is. This panel puts
 * that sentence on screen beside the button, because a button that appears to do
 * nothing teaches an operator that the page is broken, while a button with a
 * reason beside it teaches them something true about the engine.
 *
 * ## Turning the picture off, and what that turned out to cost
 *
 * The third button opens the canvas with no acquisitions at all: the operator's
 * own drawing above and below, and nothing in the middle. That is not an idle
 * case. It is what an operator sees before a run has started, laying positions
 * out on an empty plate, so it is a thing the canvas has to be able to do.
 *
 * Two of the three engines do it without complaint and open in a fraction of a
 * second. Neuroglancer does not: asked to open with no acquisitions its
 * `openViewer` never finishes at all, so a page that simply waited for it would
 * wait for ever. Waiting for ever looks exactly like loading, which is the
 * failure this project keeps being caught by, so this panel gives every open a
 * time limit and says plainly what happened when the limit is reached. It does
 * not paper over it and it does not pretend the engine succeeded; the button is
 * offered on every engine, and on the one that cannot manage it you watch it
 * fail and read why. The gap itself is written down in
 * `viz_studio/options/README.md`, which is where the interface is being kept
 * honest until it can be settled.
 *
 * ## Why this page says nothing about colours
 *
 * The interface lets a page say what colours of light a run recorded and how
 * bright to draw them. This page says nothing, on purpose. It does not know: a
 * run records that in its own description, and the only way to read it is to
 * open the run — which is the very thing the canvas is being asked to do.
 *
 * It no longer needs to. A canvas given no colours reads the run's own
 * description and draws every channel the run holds, each in the colour and
 * brightness range the run itself names. A two-colour run arrives looking like
 * a two-colour run. Saying nothing is therefore the ordinary case rather than a
 * gap, and a page only speaks up when it wants something other than what the
 * run asked for.
 */

import { theGroundBeneath, theOperatorsMarks } from "./demonstration-drawings.js";
import { describeEngine, enginesOnOffer, openerFor, whyOneIsMissing } from "./engines.js";
import { theDrawingAbove, whoIsAt } from "./layers-above.js";
// What a strict reader will refuse in a store's own description, so bad news
// can name a cause instead of reporting a silence. See that file for why the
// engine cannot be asked directly.
import {
  whyAReaderMayRefuse,
} from "../../../../../viz_studio/options/what-a-reader-refuses.js";

/**
 * The colour of the box the picture is drawn in.
 *
 * Dark, because an acquisition is dark and ground the microscope has never
 * visited should look empty rather than look broken. The engine is told this
 * colour as well as the box being painted with it, so that wherever there is no
 * picture there is no visible seam between one drawing surface and the next.
 *
 * The box itself is given the same colour in `src/style.css`, and the two have
 * to be changed together. That is not only tidiness: an engine is fetched when
 * this step is first opened, and for the second or two before it arrives the box
 * is whatever the stylesheet says. Page-white for a moment where a dark image
 * belongs reads as something having gone wrong.
 */
const THE_COLOUR_BEHIND_THE_PICTURE = "#05070d";

/**
 * How long to wait for an engine to open before saying that it has not.
 *
 * Generous on purpose. Opening reads the run's description over the network, and
 * on a development server the engine's own pieces are handed over one file at a
 * time, so the first open of a large engine is genuinely slow. Measured, the
 * slowest honest open here is a few seconds and the two that open with no
 * acquisitions take under a quarter of a second.
 *
 * What this is really for is the open that never finishes. A promise that never
 * settles and a picture that is still loading look identical from the outside,
 * and telling those two apart has cost this project days — so nothing here is
 * allowed to wait without a limit and without saying so afterwards.
 */
const HOW_LONG_TO_WAIT_FOR_AN_ENGINE = 25_000;

/**
 * A drawing that draws nothing, for a layer that has been switched off.
 *
 * There are two ways to say a slot is empty and they are not interchangeable,
 * which is worth explaining because the difference is invisible until it bites.
 *
 * Handing a slot `null` says the application has nothing for it at all, and an
 * engine is then free to skip laying a drawing surface down, clearing it every
 * frame and carrying it to the graphics card. That is the right thing to say
 * when a viewer has only just been opened and its surfaces are still blank, and
 * it is what this panel says then.
 *
 * It is not enough for a layer being switched off while somebody is watching.
 * Measured on this page: two of the three engines clear a drawing surface only
 * on their way to painting it, so a slot handed `null` after something has
 * already been drawn there keeps showing the last drawing for as long as the
 * viewer stays open. On those engines the button appears not to work. Handing a
 * drawing that paints nothing instead costs a surface that is cleared each frame
 * and settles the question, because the clearing happens either way.
 *
 * That difference belongs in the interface rather than here. Every engine ought
 * to answer `drawUnder(null)` by leaving nothing on screen, and the fact that
 * two of them do not is recorded in `viz_studio/options/README.md`. This is
 * what the page does in the meantime, and it is written the way it is so that
 * the day the interface is settled, this can go.
 */
const paintNothingAtAll = () => {};

/**
 * The two fixed slots, which every canvas has whatever workflow it is in.
 *
 * Everything above the picture is a stack instead, and the stack is not fixed:
 * a workflow adds to it as it goes — the carrier, the positions, the focus
 * points, the targets once they have been found, the refined targets after
 * that — and each one gets a button of its own here. See {@link THE_STACK_ABOVE}
 * for what a layer in that stack is.
 */
const THE_FIXED_SLOTS = [
  {
    key: "beneath",
    label: "Beneath",
    /* What each button is for, shown when the pointer rests on it. Written out
       in full because the label on a button this small can only be one word. */
    explains: "The operator's own drawing, beneath the picture. This is where a carrier " +
      "outline and the positions still to be visited belong, and you see it wherever " +
      "the picture does not reach.",
  },
  {
    key: "picture",
    label: "Picture",
    explains: "The acquisition itself, read from the run. Turning it off opens the canvas " +
      "with no acquisition at all, which is what an operator sees before a run has " +
      "started.",
  },
];

/**
 * What a layer above the picture is, and what a workflow may say about one.
 *
 * ```js
 * { key, label, explains, paint, reaches, shown, opacity, staysSolid }
 * ```
 *
 * - `key` — its name in the buttons and in what a test reads back.
 * - `label` — the word on its button.
 * - `explains` — one sentence, shown when the pointer rests on the button.
 * - `paint(frame)` — how it draws, exactly as any canvas drawing does: in
 *   micrometres on the sample, so it pans and magnifies with the picture.
 * - `reaches(at)` — what of it is at a place on the sample, or nothing. This is
 *   what makes a layer something an operator can work with rather than look at:
 *   clicking a position opens the field it stands for, clicking a target picks
 *   it. Optional; a layer that is only there to be seen leaves it out.
 * - `shown`, `opacity`, `staysSolid` — see `layers-above.js`.
 *
 * The canvas is never told which step of a workflow it is in. It is told what
 * to draw, and the step decides that. That is what keeps this movable from one
 * workflow into the next, and it is why this list is handed in rather than
 * written here.
 */

/**
 * The one layer the demonstration puts above the picture when nobody says
 * otherwise, so that the canvas has something to show on a page that is only
 * looking at it.
 */
const THE_DEMONSTRATION_LAYER = {
  key: "above",
  label: "Above",
  explains: "The operator's own drawing, above the picture. This is where anything that " +
    "has to stay visible over the acquisition belongs.",
  paint: theOperatorsMarks,
};

/**
 * Wait for a promise, but not for ever.
 *
 * @param promise what is being waited for.
 * @param sayWhat how to describe what did not finish, used to build the message.
 * @returns whatever the promise gave back.
 * @throws if the wait runs out, with a message an operator can read. The
 *   original promise is not cancelled — nothing here can cancel it — so a caller
 *   that gives up must also assume whatever it started is still running. There
 *   is a note about what that costs where this is called.
 */
/**
 * What the run's own description says about why it might not have opened.
 *
 * An engine that will not accept a store does not always say so — the strict one
 * never finishes opening and reports nothing at all — so what an operator meets
 * is a silence, and a message about a silence tells them only that something is
 * wrong somewhere. The description is small, it is already being served, and it
 * is where both faults met so far are plainly visible. So it is read once, here,
 * at the moment there is bad news to deliver.
 *
 * Nothing is asserted that has not been measured: `whyAReaderMayRefuse` reports
 * the two faults that were shown to stop a store opening and stays quiet about
 * everything else, so an empty answer leaves the original message exactly as it
 * was rather than adding a guess to it.
 */
async function whatTheRunItselfMaySayAboutThat(acquisitions) {
  const first = acquisitions?.[0];
  if (!first) return "";
  try {
    const address = first.split("|")[0].replace(/\/+$/, "");
    const answer = await fetch(`${address}/.zattrs`, { cache: "no-store" });
    if (!answer.ok) return "";
    const refusals = whyAReaderMayRefuse(await answer.json());
    if (!refusals.length) return "";
    return ` The run itself may be the reason: ${refusals.join("; and ")}.`;
  } catch {
    // The description could not be read, which is worth nothing extra on screen:
    // the message already says the run could not be opened.
    return "";
  }
}

async function beforeWeGiveUp(promise, sayWhat) {
  let ringTheBell = null;
  const theWaitRunningOut = new Promise((_, giveUp) => {
    ringTheBell = setTimeout(
      () => giveUp(new Error(
        `${sayWhat} was still not ready after ` +
        `${Math.round(HOW_LONG_TO_WAIT_FOR_AN_ENGINE / 1000)} seconds, so waiting was ` +
        "given up on. Nothing has gone wrong on this page; the engine simply never " +
        "finished opening.",
      )),
      HOW_LONG_TO_WAIT_FOR_AN_ENGINE,
    );
  });
  /* Whichever of the two loses, its outcome is caught rather than left loose. An
     unhandled rejection would be reported to the console as a fault on this
     page, which it is not. */
  promise.catch(() => {});
  try {
    return await Promise.race([promise, theWaitRunningOut]);
  } finally {
    clearTimeout(ringTheBell);
  }
}

/**
 * Put the canvas inside a box on the page and hand back the way to drive it.
 *
 * @param box the element the picture fills. Whatever surfaces the chosen engine
 *   needs are created inside it, and it is left empty again when the panel is
 *   closed.
 * @param note a small element in the corner of the box, where this says which
 *   engine is drawing or why nothing could be drawn. A blank picture and a
 *   picture that is still loading look exactly alike, so nothing here fails
 *   quietly.
 * @param chooser an element to fill with one button per engine that can draw
 *   here, so that the same run can be looked at through one engine and then
 *   another. Which engines those are can depend on how the page was opened; see
 *   `engines.js`.
 * @param layers an element to fill with one button per layer — the drawing
 *   beneath, the picture, the drawing above — each of which turns its layer on
 *   and off.
 * @param why a small element beside those buttons, where this says what the
 *   layers are doing and, when an engine cannot honour the layer beneath the
 *   picture, the engine's own sentence explaining that.
 * @param readout a small element that says where the view is, in micrometres.
 * @param acquisitions the addresses of the run's images, as whole addresses
 *   including the scheme and the host, in the order they should be drawn with
 *   the first at the bottom. An empty list means the page was not pointed at a
 *   run, which is said on screen rather than left as an empty box.
 * @param engine which engine to open with, or nothing to open with the first.
 *   A name that cannot be drawn with here — misspelled, or one this page cannot
 *   offer where it was opened from — opens the first instead and says so in the
 *   corner of the box, rather than substituting one in silence.
 *
 * @returns a handle with `whenShown()`, to be called each time the panel comes
 *   into view; `changeTo(name)`, which swaps the engine and keeps the view;
 *   `showTheLayer(key, on)`, which turns one of the three layers on or off; and
 *   `destroy()`. All of them are safe to call after `destroy()`, so a page
 *   tearing itself down need not keep track of the order.
 */
export function putTheCanvasIn({
  box, note, chooser, layers, why, readout, name, acquisitions, engine,
  depth, plane, planeReadout, volume,
  /* What the workflow wants drawn above the picture, bottom of the stack
     first. Left empty by a page that is only looking at the canvas, which then
     gets the demonstration's one layer so that there is something to see. */
  layersAbove = [],
  /* Told what an operator clicked, when a layer claims the click:
     `({ layer, what, at }) => …`. This is how clicking a position opens the
     field it stands for. The canvas does not act on the click itself — what a
     click means belongs to the workflow. */
  onTouched = null,
}) {
  /* What can be drawn with here, which is not always everything this page was
     built with — `engines.js` explains why. Asking for one that is not on offer
     is answered with the reason rather than by quietly opening a different one,
     because somebody who typed `?engine=…` had a reason for typing it. */
  const built = enginesOnOffer();
  const missing = whyOneIsMissing();
  const askedForSomethingAbsent = engine && !built.includes(engine);
  let wanted = built.includes(engine) ? engine : built[0];

  /* The heading says which engine is drawing, written from `wanted` rather than
     left as whatever the markup said — and rewritten whenever `wanted` changes,
     which `markTheButtons` does.

     Both halves have been wrong on screen. An engine that cannot be offered —
     neuroglancer, on a page opened straight off the disk, which cannot start its
     background programs — falls back to one that can, so a heading written into
     the markup names an engine that is not drawing. And a heading written only
     once goes stale the first time somebody presses the other button, which is
     worse here than it was when a panel was fixed to one engine: the whole point
     of the chooser is that the picture changes underneath you, and the heading is
     what says which picture you are looking at. */
  if (name) name.textContent = wanted;

  let viewer = null;      // the picture, once an engine has been opened on it
  let opening = false;
  let destroyed = false;
  /* Where the view was when the engine was last changed. Held here rather than
     inside any one engine, because comparing two ways of drawing the same thing
     is very hard if reaching the second one means finding your way back to where
     you were: small differences are only visible when the two pictures are of
     the same view moments apart. */
  let carriedOver = null;

  /* Which of the three layers are being drawn. The picture starts on and the
     operator's own two start off, which is the state that costs the least: told
     there is nothing to draw in a slot, an engine need not lay a drawing surface
     down, clear it every frame or carry it to the graphics card. It is also the
     state to open on, because the first thing worth seeing is the acquisition on
     its own. */
  const showing = { beneath: false, picture: true };

  /* The layers above the picture, in drawing order. Each carries its own
     `shown`, so turning the heatmap off leaves the focus points exactly where
     they were — which is the whole reason they are separate layers rather than
     one drawing.

     Copied rather than used in place, because the canvas writes `shown` on them
     and a workflow's own list should not change under it. */
  let stackAbove = (layersAbove.length ? layersAbove : [THE_DEMONSTRATION_LAYER])
    .map((layer) => ({ shown: false, ...layer }));

  /* How much of the whole stack above to keep, 0 to 1. One control for all of
     them, because "let me see the picture" is one thought and should be one
     movement. It only ever fades: a layer already set faint does not become
     solid when this is turned up. */
  let dial = 1;

  /* Ground where the drawing above is made see-through, in micrometres. This is
     how "let me see these particular fields" is said, and it is what the fields
     landing during a run use: as each one arrives, the plan over it is opened
     up so the picture that just appeared can be seen. */
  let seeThrough = [];

  const buttons = new Map();

  const say = (text) => {
    note.hidden = !text;
    note.textContent = text ?? "";
  };

  /* Where the view is, in micrometres on the stage. The centre and how much
     specimen one screen pixel covers are the two numbers that say it, and they
     are the same two numbers whichever engine is drawing — which is a large part
     of why the engines can be compared at all. */
  function sayWhereTheViewIs(where) {
    if (!where) {
      readout.textContent = "—";
      return;
    }
    readout.textContent =
      `centre ${Math.round(where.centre.x)}, ${Math.round(where.centre.y)} µm` +
      ` · ${where.zoom.toFixed(2)} µm per pixel`;
  }

  /**
   * Anything to add after the name of the engine that is drawing.
   *
   * There are two things worth saying and they can both be true at once: that
   * this page cannot offer everything it was built with, and that somebody asked
   * for one of the ones it cannot offer. Both belong in this corner of the box,
   * because that is where somebody looking for a missing button is looking.
   */
  function anythingElseWorthSaying() {
    if (askedForSomethingAbsent && missing) {
      return ` · ${engine} was asked for and is not here: ${missing}`;
    }
    if (askedForSomethingAbsent) {
      return ` · there is no engine called ${engine}, so this one is drawing instead`;
    }
    return missing ? ` · ${missing}` : "";
  }

  function sayWhichEngineIsDrawing() {
    if (!viewer) return;
    const withoutTheRun = showing.picture ? "" : " · opened with no acquisition";
    say(`${wanted} — ${describeEngine(wanted)}${withoutTheRun}${anythingElseWorthSaying()}`);
    for (const button of chooser.querySelectorAll("button")) {
      button.setAttribute("aria-checked", String(button.dataset.engine === wanted));
    }
  }

  /**
   * What the layers are doing, in a sentence beside their buttons.
   *
   * The sentence that matters is the one about the layer beneath the picture,
   * because that is the one an engine can refuse to draw. Each viewer answers
   * that question about itself, so what appears here is the engine's own words
   * rather than anything this page has worked out from its name — which means a
   * fourth engine added tomorrow explains itself without a line changing here.
   */
  function sayWhatTheLayersAreDoing() {
    /* Only the one class that says whether this is a warning is touched. The
       element carries other classes that give it its place in the toolbar, and
       replacing the whole list would take those away — which it did, once, and
       what it cost was the wrapping: a four-line explanation ran off the side of
       the window in one line, so the half that mattered could not be read. */
    const warning = !!viewer && !viewer.drawsUnder;
    why.classList.toggle("bad", warning);

    if (!viewer) {
      why.textContent = opening ? "waiting for the picture…" : "";
    } else if (locked) {
      why.textContent =
        "The layers are locked, so nothing can be picked or moved. Panning and " +
        "zooming still work.";
    } else if (warning) {
      why.textContent = showing.beneath
        ? `Beneath is being drawn and you will not see it. ${viewer.drawsUnderBecause}`
        : `This engine cannot show anything beneath the picture. ${viewer.drawsUnderBecause}`;
    } else if (!showing.picture && !showing.beneath && !stackAbove.some((l) => l.shown)) {
      why.textContent =
        "Nothing is being drawn at all, which is why the box is empty. Turn a layer back on.";
    } else if (!showing.picture) {
      why.textContent =
        "No acquisition is open — this is what the canvas shows before a run has started.";
    } else if (showing.beneath) {
      why.textContent =
        "Beneath shows wherever the picture does not reach, so zoom out to see more of it.";
    } else {
      why.textContent = "";
    }

    /* The same words again where hovering finds them. On a page showing several
       pictures at once the sentence is given a fixed few lines, so that a picture
       is never made smaller than the one beside it by an engine having more to
       say about itself — and an engine that has a great deal to say would then be
       cut off. This is where the rest of it goes. */
    why.title = why.textContent;
  }

  /** Show each button in the state its layer is actually in. */
  function markTheButtons() {
    /* Only while an open is in flight. Not "while there is no picture", which is
       what this used to say and which was a trap: these buttons decide what the
       next open will contain, so when there is no picture they are the way back
       to one.

       What that cost, exactly. Turning the picture off asks the canvas to open
       with no acquisition at all. One engine never finishes that — it cannot
       learn what space to draw in with no image layer to read it from — so the
       wait runs out, the box is emptied and no viewer is left. Every button was
       then disabled, including the one that would have put the picture back, and
       the only way out was to reload the page. An engine that cannot do one
       thing should cost you that one thing, not the panel. */
    for (const [key, button] of buttons) {
      button.setAttribute("aria-pressed", String(isShowing(key)));
      /* The picture cannot be turned on when this page was never pointed at a
         run: there would be nothing to turn on, and a button that does nothing
         is a worse answer than a button that is plainly unavailable. */
      button.disabled = opening || (key === "picture" && !acquisitions.length);
    }
    if (name) name.textContent = wanted;
  }

  /**
   * Hand the two drawing slots what the buttons say they should hold.
   *
   * @param picture the viewer to hand them to.
   * @param openedJustNow true when this viewer has only just been opened, so
   *   there is nothing on its surfaces yet. See the note below, which is the
   *   whole reason this has to be said.
   */
  function handTheSlotsTheirDrawings(picture = viewer, { openedJustNow = false } = {}) {
    if (!picture) return;
    const nothingToDraw = openedJustNow ? null : paintNothingAtAll;
    picture.drawUnder(showing.beneath ? theGroundBeneath : nothingToDraw);
    /* The whole stack above the picture arrives as one drawing, because that is
       what the interface takes: one function per slot. Which layers are in it,
       how faint each is and where it has been opened up are all settled here
       and the engine never learns about any of it — which is what makes all of
       this cost nothing per engine and behave the same whichever one is
       drawing. */
    picture.drawOver(theDrawingAbove(stackAbove, { dial, seeThrough }) ?? nothingToDraw);
  }

  /**
   * Turn a press that did not travel into a touch on whichever layer it reached.
   *
   * A press that *did* travel was a pan, and must not also count as a click —
   * an operator who drags the picture across the screen and lands on a position
   * has not chosen that position. So the distance is measured and anything
   * beyond a few pixels is left alone. A few rather than none because a hand on
   * a trackpad is never quite still, and demanding stillness would make the
   * layers feel unreliable to click.
   *
   * The place is turned into micrometres on the sample before any layer is
   * asked, so every layer answers about the same piece of specimen however the
   * view happens to be sitting.
   */
  const A_PRESS_THAT_DID_NOT_TRAVEL = 4;   // browser pixels
  let pressedAt = null;

  /**
   * Whether the layers may be touched at all.
   *
   * Locked, the canvas is something to look at: it still pans and zooms, and
   * every button still works, but a click reaches nothing and nothing can be
   * picked, moved or drawn by accident.
   *
   * This is worth having for a plain reason. An operator spends a long time
   * looking at a plan they have already settled — checking it, showing it to
   * somebody, panning around it while the run goes — and in all that time a
   * stray click can only do harm. Locking says "I am reading, not editing", and
   * it is the same idea as the lock on any drawing tool: not a restriction, a
   * way of putting the tools down without putting the picture away.
   *
   * It starts unlocked, because a canvas that quietly ignores clicks is a
   * canvas an operator will decide is broken.
   */
  let locked = false;

  box.addEventListener("pointerdown", (event) => {
    pressedAt = { x: event.clientX, y: event.clientY };
  });

  box.addEventListener("click", (event) => {
    const from = pressedAt;
    pressedAt = null;
    if (locked || !from || !viewer || !onTouched) return;
    if (Math.hypot(event.clientX - from.x, event.clientY - from.y) > A_PRESS_THAT_DID_NOT_TRAVEL) {
      return;
    }
    const where = viewer.whereThingsAreDrawn?.();
    if (!where?.unproject) return;
    const bounds = box.getBoundingClientRect();
    const at = where.unproject(event.clientX - bounds.left, event.clientY - bounds.top);
    const found = whoIsAt(stackAbove, at);
    if (found) onTouched({ ...found, at });
  });

  /** Redraw the stack above after something about it has changed. */
  function theStackAboveChanged() {
    handTheSlotsTheirDrawings();
    markTheButtons();
    sayWhatTheLayersAreDoing();
  }

  /** Open the chosen engine on the run, and put the view where it was. */
  async function openTheCanvas() {
    const openViewer = await openerFor(wanted);
    const opened = await beforeWeGiveUp(
      openViewer(box, {
        /* Every acquisition this page was given, whether or not the picture is
           being shown: the picture is switched with `showPicture` below rather
           than by opening without it. Opening with none is now only what happens
           when the page was never given a run at all. */
        acquisitions: acquisitions.map((url) => ({
          url,
          // The last part of the address, which is what the run is called on disk
          // and the only name this page has for it.
          name: url.split("/").filter(Boolean).pop() ?? url,
        })),
        // The run's record of where it has imaged, which this page does not have.
        // Given nothing, an engine draws the whole of the room the run declared
        // rather than only the part it has been to, which costs a few more
        // requests and is right in every other way.
        coverage: null,
        background: THE_COLOUR_BEHIND_THE_PICTURE,
        onViewChanged: sayWhereTheViewIs,
      }),
      acquisitions.length ? wanted : `${wanted}, opened with no acquisition,`,
    );
    handTheSlotsTheirDrawings(opened, { openedJustNow: true });
    /* A viewer opens drawing its acquisitions, so the switch only has to be said
       when it is off — but it is said either way, so that a canvas opened again
       for a change of engine comes back in the state the buttons show rather than
       in the one it happens to open in. */
    opened.showPicture(showing.picture);
    offerTheVolume(opened);
    offerTheStack(opened);
    if (carriedOver) opened.setView(carriedOver);
    viewer = opened;
    sayWhichEngineIsDrawing();
    sayWhatTheLayersAreDoing();
    sayWhereTheViewIs(opened.getView());
    return opened;
  }

  /**
   * Empty the box after an open that never finished.
   *
   * Worth being honest about what this does and does not do. An engine that
   * never finished opening cannot be handed back, so there is nothing to close
   * properly: what it built is taken out of the page, and whatever it is still
   * doing out of sight goes on until the page is left. Nothing on screen is
   * wrong afterwards, and the next open starts from an empty box. Cleaning up
   * after an open that cannot be abandoned is something the interface has no way
   * to do, which is part of what makes this a gap worth recording rather than a
   * quirk worth handling.
   */
  function emptyTheBox() {
    box.textContent = "";
  }

  /**
   * Open the picture again with something about it changed, keeping the view.
   *
   * The old picture is closed, the new one is opened in the same box, and the
   * centre and the magnification are carried across. If the new one will not
   * open, the arrangement that was working is put back on the same view and the
   * reason is written in the corner — a box that has quietly gone blank because
   * somebody pressed a button is worse than one that never worked.
   *
   * @param change what to open differently: `engine`, or whether to show the
   *   `picture`.
   * @param doing a few words for what is being done, shown while it happens.
   */
  async function openItAgain(change, doing) {
    if (destroyed || opening || !viewer) return;
    opening = true;
    markTheButtons();
    const goingBackTo = { engine: wanted, picture: showing.picture };
    carriedOver = viewer.getView();
    say(doing);
    sayWhatTheLayersAreDoing();
    try {
      viewer.destroy();
      viewer = null;
      if (change.engine !== undefined) wanted = change.engine;
      if (change.picture !== undefined) showing.picture = change.picture;
      await openTheCanvas();
    } catch (whyNot) {
      emptyTheBox();
      wanted = goingBackTo.engine;
      showing.picture = goingBackTo.picture;
      try {
        await openTheCanvas();
        say(`${whyNot.message} ${wanted} is drawing as it was.`);
      } catch (alsoWhyNot) {
        emptyTheBox();
        viewer = null;
        say(`nothing could be drawn: ${alsoWhyNot.message}`);
      }
    } finally {
      opening = false;
      markTheButtons();
      sayWhatTheLayersAreDoing();
    }
  }

  /* Where in the stack the picture is taken from.
   *
   * Kept here rather than in the viewer because it is the same question of both
   * engines and neither should answer it differently: the operator moves through
   * the specimen, and which engine happens to be drawing is not part of that. The
   * position is remembered across a change of engine for the same reason the view
   * is — flicking between two engines to compare them is useless if the second
   * one starts somewhere else.
   */
  let throughTheStack = null;
  let showingUm = null;

  /* Flat, or the whole stack at once.
   *
   * Offered only by an engine that can do it, and remembered across a change of
   * engine only in the sense that an engine which cannot draw a volume shows a
   * flat picture and says so — the alternative, silently carrying "3D" onto an
   * engine that ignores it, would leave a button reading 3D over a flat picture.
   */
  let showingVolume = false;

  function offerTheVolume(viewerNow) {
    if (!volume) return;
    const can = viewerNow.canShowVolume === true;
    volume.hidden = !can;
    if (!can) {
      showingVolume = false;
      return;
    }
    if (!volume.childElementCount) {
      for (const [key, label] of [[false, "Flat"], [true, "Volume"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.setAttribute("role", "radio");
        button.dataset.volume = String(key);
        button.textContent = label;
        button.addEventListener("click", () => {
          if (showingVolume === key) return;
          showingVolume = key;
          viewer?.showVolume(key);
          markTheVolume();
          // The plane slider goes with it: a volume is of every plane at once.
          if (viewer) offerTheStack(viewer);
          sayWhatTheLayersAreDoing();
        });
        volume.append(button);
      }
    }
    viewerNow.showVolume(showingVolume);
    markTheVolume();
    offerTheStack(viewerNow);
  }

  function markTheVolume() {
    for (const button of volume?.querySelectorAll("button") ?? []) {
      button.setAttribute("aria-checked",
        String((button.dataset.volume === "true") === showingVolume));
    }
  }

  function offerTheStack(viewerNow) {
    throughTheStack = viewerNow.theDepthItCanShow?.() ?? null;
    if (!depth) return;
    /* Not while a volume is drawn. The slider says which plane of the stack the
       picture is of, and a volume is of all of them at once — so there is no
       plane for it to name, and a control that names one would be describing a
       picture nobody is looking at. Depth in a volume means how thick a slab the
       engine draws, which is the engine's own control and a different question. */
    if (showingVolume || !throughTheStack) {
      depth.hidden = true;
      return;
    }
    const { lowUm, highUm, stepUm } = throughTheStack;
    /* The middle until the operator says otherwise, which is where the canvas
       opens: `viz_studio/options/planes.js` says why, and a control that started
       at nought would put the picture at the edge of the specimen the moment it
       was touched. */
    /* Where the picture already is, not the middle of the stack. The canvas opens
       on the specimen rather than on the middle of the declared room, and a
       control that started in the middle would undo that before anybody touched
       it — measured, it put a biopsy back from plane 467 to 417. */
    if (showingUm === null) showingUm = throughTheStack.atUm ?? (lowUm + (highUm - lowUm) / 2);
    showingUm = Math.min(Math.max(showingUm, lowUm), highUm);
    plane.min = String(lowUm);
    plane.max = String(highUm);
    plane.step = String(stepUm);
    plane.value = String(showingUm);
    depth.hidden = false;
    goToPlane(showingUm, viewerNow);
  }

  /* A drag can ask for a plane oftener than a frame is drawn, so only the last
     one asked for in any frame is acted on. Nothing on screen can show a plane
     that has already been replaced, so asking for the ones in between is work
     nobody sees.

     **It is not why a drag is expensive, and the measurement is worth keeping so
     nobody comes back expecting it to be.** Twenty steps through an 833-plane
     biopsy cost Viv 1266 requests before this and 980 after; neuroglancer 303
     and 352, which is noise. The cost is per *plane*: Viv asks for about sixty
     pieces for each one and sees every load through, where neuroglancer asks for
     about fifteen and lets its queue drop work that has been superseded. Visiting
     twenty planes is therefore expensive on Viv however tidily they are asked
     for, and that is a property of the engine rather than of this page.

     Coalescing per frame rather than waiting for the drag to stop, because a
     control that shows nothing until you let go is a control you cannot aim. */
  let planeWanted = null;
  let framePending = false;

  function goToPlane(um, viewerNow = viewer) {
    showingUm = um;
    sayWhichPlane(um);
    planeWanted = { um, viewerNow };
    if (framePending) return;
    framePending = true;
    requestAnimationFrame(() => {
      framePending = false;
      const asked = planeWanted;
      planeWanted = null;
      asked?.viewerNow?.setPlane?.(asked.um);
    });
  }

  /** The reading, written straight away so the number keeps up with the hand. */
  function sayWhichPlane(um) {
    if (!planeReadout || !throughTheStack) return;
    const { lowUm, stepUm } = throughTheStack;
    const which = Math.round((um - lowUm) / (stepUm || 1));
    const many = Math.round((throughTheStack.highUm - lowUm) / (stepUm || 1)) + 1;
    planeReadout.textContent = `${Math.round(um)} µm · plane ${which + 1} of ${many}`;
  }

  plane?.addEventListener("input", () => goToPlane(Number(plane.value)));

  /** Change the engine underneath, keeping the view exactly where it is. */
  async function changeTo(name) {
    if (name === wanted) return;
    await openItAgain({ engine: name }, `opening ${name}…`);
  }

  /**
   * Turn one of the three layers on or off.
   *
   * All three cost the same now — one frame — because all three are switches the
   * canvas offers rather than states it is opened in: the drawing beneath and
   * the drawing above are handed over as they are, and the picture is switched
   * with `showPicture`.
   *
   * **It used to reopen the canvas with no acquisitions**, and that is worth
   * remembering rather than quietly deleting, because it looked reasonable and
   * measured badly. Under Viv it cost 1.6 seconds each way and 45 requests to
   * fetch the picture again on the way back, since a new viewer knows nothing of
   * what the old one had decoded. Under neuroglancer it did not work at all: that
   * engine takes its axes from its image layers, so with none it never finished
   * opening — 26.7 seconds a press, both presses, with the picture never going
   * off. What looked like a slow button was a button that did nothing.
   */
  /** Whether the named layer is being drawn, whichever kind of layer it is. */
  function isShowing(key) {
    if (key in showing) return showing[key];
    return stackAbove.find((layer) => layer.key === key)?.shown ?? false;
  }

  async function showTheLayer(key, on) {
    if (destroyed || opening || !viewer || isShowing(key) === on) return;
    if (key in showing) {
      showing[key] = on;
      if (key === "picture") viewer.showPicture(on);
      else handTheSlotsTheirDrawings();
    } else {
      const layer = stackAbove.find((one) => one.key === key);
      if (!layer) return;
      layer.shown = on;
      handTheSlotsTheirDrawings();
    }
    markTheButtons();
    sayWhatTheLayersAreDoing();
  }

  /**
   * How solid the whole stack above the picture is drawn, 0 to 1.
   *
   * Kept even while there is no picture, so that reopening on another engine
   * comes back the way the operator left it rather than the way it happens to
   * start.
   */
  function fadeTo(howSolid) {
    dial = Math.min(1, Math.max(0, Number(howSolid)));
    handTheSlotsTheirDrawings();
    sayWhatTheLayersAreDoing();
  }

  for (const name of built) {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(name === wanted));
    button.dataset.engine = name;
    button.textContent = name;
    button.addEventListener("click", () => changeTo(name));
    chooser.append(button);
  }

  /**
   * Put a button on screen for every layer there is, and a dial beside them.
   *
   * Built again from scratch whenever the stack changes, because the stack
   * grows while an operator is working — targets appear when discovery
   * finishes, refined targets after that — and a row of buttons that does not
   * grow with it would leave a layer on screen with no way to turn it off.
   */
  function buildTheLayerButtons() {
    layers.textContent = "";
    /* The strip beside the buttons is rebuilt with them, so a stack that grew
       does not leave two fades and two locks behind it. */
    layers.parentElement?.querySelectorAll(":scope > .layer-extra")
      .forEach((old) => old.remove());
    buttons.clear();

    const addButton = (key, label, explains, pressed) => {
      const button = document.createElement("button");
      button.type = "button";
      button.disabled = true;      // until there is a picture to change
      button.setAttribute("aria-pressed", String(pressed));
      button.dataset.layer = key;
      button.title = explains;
      button.textContent = label;
      button.addEventListener("click", () => showTheLayer(key, !isShowing(key)));
      buttons.set(key, button);
      layers.append(button);
    };

    for (const slot of THE_FIXED_SLOTS) {
      addButton(slot.key, slot.label, slot.explains, showing[slot.key]);
    }
    for (const layer of stackAbove) {
      addButton(
        layer.key,
        layer.label ?? layer.key,
        layer.explains ?? "One of the operator's own layers, above the picture.",
        layer.shown,
      );
    }

    /* The fade and the lock go in a strip of their own beside the buttons
       rather than inside them. The buttons are a joined row of switches — one
       shape, one border, read as a single control — and a slider dropped into
       the middle of that reads as something having gone wrong with the page. */
    const beside = document.createElement("div");
    beside.className = "layer-extra";
    layers.after(beside);

    /* The shared fade. A slider rather than a button because it is not a yes or
       a no: what an operator wants is usually to see both the picture and their
       own drawing over it, and finding the balance is a thing you do by moving
       something and looking. */
    const fade = document.createElement("label");
    fade.className = "layer-fade";
    fade.title =
      "How solid everything above the picture is drawn. Turn it down to see the " +
      "picture through your own drawing. Layers marked to stay solid — the focus " +
      "points, say — are not affected.";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = "0";
    slider.max = "100";
    slider.step = "1";
    slider.value = String(Math.round(dial * 100));
    slider.dataset.layerFade = "";
    slider.setAttribute("aria-label", "How solid the layers above the picture are");
    slider.addEventListener("input", () => fadeTo(Number(slider.value) / 100));
    fade.append(document.createTextNode("Fade"), slider);
    beside.append(fade);

    /* The lock, at the end of the row. Last because it is about the whole
       canvas rather than about any one layer, and because it is the control an
       operator reaches for least often and wants to find in the same place
       every time. */
    lockButton = document.createElement("button");
    lockButton.type = "button";
    lockButton.dataset.lock = "";
    lockButton.setAttribute("aria-pressed", String(locked));
    lockButton.title =
      "Lock the layers so that nothing can be picked or moved by accident. " +
      "Panning and zooming go on working — this only stops a click reaching " +
      "your own drawing, which is what you want while you are reading a plan " +
      "rather than changing one.";
    lockButton.textContent = "Lock";
    lockButton.addEventListener("click", () => handle.lock(!locked));
    beside.append(lockButton);
  }

  /* The lock's own button, remembered so its state can be shown when the lock
     is changed from somewhere other than the button itself. */
  let lockButton = null;

  buildTheLayerButtons();

  const handle = {
    /** Which engine is drawing now. */
    get engine() { return wanted; },

    /** Whether a picture is open, which is what a test asks before looking. */
    get open() { return !!viewer; },

    /** Which layers are being drawn, for a test to read back. */
    get layers() {
      const state = { ...showing };
      for (const layer of stackAbove) state[layer.key] = layer.shown;
      return state;
    },

    /** How solid the stack above the picture is drawn, and a way to change it. */
    get fade() { return dial; },
    fadeTo,

    /**
     * Whether the layers may be touched, and a way to lock or unlock them.
     *
     * Locking leaves panning and zooming exactly as they were — the canvas is
     * still something to move around in — and only stops clicks reaching the
     * layers. See the note where the lock is declared for why that is the
     * useful half to be able to switch off.
     */
    get locked() { return locked; },
    lock(on = true) {
      locked = !!on;
      box.classList.toggle("locked", locked);
      if (lockButton) lockButton.setAttribute("aria-pressed", String(locked));
      sayWhatTheLayersAreDoing();
    },

    /**
     * Say what belongs above the picture now.
     *
     * The stack grows while an operator works: targets appear when discovery
     * finishes, refined targets after refinement, and each wants a button of
     * its own. So the whole list is handed in again rather than added to one
     * layer at a time — a workflow step says what should be above the picture
     * while it is standing, and the canvas makes that true.
     *
     * A layer that was already there keeps whether it was being shown. Losing
     * that would be its own small betrayal: an operator who turned the carrier
     * off should not find it back on because a target was discovered somewhere
     * else entirely.
     */
    setLayersAbove(list = []) {
      const before = new Map(stackAbove.map((layer) => [layer.key, layer.shown]));
      stackAbove = (list.length ? list : [THE_DEMONSTRATION_LAYER]).map((layer) => ({
        ...layer,
        shown: before.has(layer.key) ? before.get(layer.key) : (layer.shown ?? false),
      }));
      buildTheLayerButtons();
      theStackAboveChanged();
    },

    /** The stack as it stands, for a workflow that wants to add one to it. */
    get layersAbove() { return stackAbove.map((layer) => ({ ...layer })); },

    /**
     * Where the drawing above the picture is opened up, in micrometres.
     *
     * Each entry is `{ x, y, w, h, letThrough }` — a piece of sample, and how
     * much of the picture to reveal there. This is what the fields landing
     * during a run use: as each one arrives, the plan drawn over it is opened
     * so that the picture which just appeared can actually be seen.
     *
     * Given in micrometres because it describes a piece of specimen, so it
     * travels with the specimen when the view is panned and grows when the view
     * is magnified — like everything else drawn here.
     */
    seeThrough(windows = []) {
      seeThrough = windows;
      handTheSlotsTheirDrawings();
    },

    /**
     * The pictures inside the viewer itself, which is the bottom layer.
     *
     * A run is looked at as more than one picture — the survey of the whole
     * slide, and the detail scans taken from places found in it — and an
     * operator wants either on its own or both together. These are plainer than
     * the layers above on purpose: drawn or not drawn, with nothing in between.
     * Everything see-through lives above the picture, which is what lets the
     * arrangement survive being handed to an engine that cannot be made
     * see-through at all.
     *
     * Empty for an engine that does not offer them, rather than throwing, so
     * that a page can ask any engine and show what there is.
     */
    picturesInside() { return viewer?.picturesInside?.() ?? []; },
    showPictureInside(name, on) { viewer?.showPictureInside?.(name, on); },

    /**
     * Where this picture is looking, and a way to put it somewhere else.
     *
     * Wanted because several of these can be on screen at once, each with its own
     * engine, and three pictures of the same run at three different zooms are not
     * a comparison. Each engine chooses its own opening view — measured, Viv fits
     * the acquisition's extent and neuroglancer opens at one voxel to the pixel,
     * which on a 1.1 µm store is twenty times closer — so somebody has to say
     * which of them they should all be at, and the page is the only thing that
     * can see more than one of them.
     *
     * Null before the picture has opened; setting it then does nothing, rather
     * than throwing, because the panels open independently and one being ready
     * before another is ordinary.
     */
    get view() { return viewer?.getView?.() ?? null; },
    lookAt(where) { if (where) viewer?.setView?.(where); },

    changeTo,
    showTheLayer,

    /**
     * Called each time the panel comes into view.
     *
     * The canvas is opened the first time and kept afterwards. Opening reads the
     * run's description over the network, so it is not something to do on every
     * render, and opening again would throw away wherever the operator had
     * panned to.
     */
    async whenShown() {
      /* Left where a browser test can reach it, and set every time this panel
         comes up rather than only when it is built, so that it always names the
         canvas actually on screen. Nothing on the page reads it. What matters
         about a picture is what reached the screen, and a viewer that reports
         itself perfectly loaded while drawing nothing is the failure this is
         meant to catch — so the tests photograph the box and this is only the
         means to ask the picture to move. */
      if (!destroyed) window.__theCanvas = handle;
      if (destroyed || viewer || opening) return;
      /* A canvas with no run is opened all the same, rather than refused.
         **It used to refuse**, and that was wrong for the ordinary case: an
         operator lays a plan out on an empty plate before anything has been
         scanned, so the first steps of a workflow have no acquisition to look
         at and still need the canvas — the carrier, the positions, the focus
         points all belong to the layers above the picture, and none of them
         needs a picture to be drawn over. Refusing left those steps with a box
         that said "no run" and could draw nothing.

         What is said on the page is unchanged, because somebody who expected a
         run and does not have one still needs telling. It is now a note beside
         a working canvas instead of a note instead of one. */
      if (!acquisitions.length) {
        say(
          "this page was not given a run to look at, so there is no picture — " +
            "your own layers are drawn on their own. Add the address of one to " +
            "the page's own address — ?overview=http://host:port/run.ome.zarr — " +
            "and reload. `live_overview_demo.py` writes a run and prints the " +
            "address to use.",
        );
      }
      opening = true;
      if (acquisitions.length) say(`opening ${wanted}…`);
      sayWhatTheLayersAreDoing();
      try {
        /* Dragging pans and the plain wheel zooms, and nothing else moves the
           view. This page no longer arranges that for itself: a canvas now
           arrives with those two gestures already attached, all three engines
           sharing one piece of code for them. That is the point — if each
           engine interpreted a drag for itself, a difference in how two of them
           felt might be the engine or might be somebody's idea of how far a
           wheel notch should zoom, and there would be no way to tell which.
           One shared piece of code removes the question. */
        return await openTheCanvas();
      } catch (whyNot) {
        emptyTheBox();
        say(`the run could not be opened — ${whyNot.message}`
            + await whatTheRunItselfMaySayAboutThat(acquisitions));
      } finally {
        opening = false;
        markTheButtons();
        sayWhatTheLayersAreDoing();
      }
      return null;
    },

    destroy() {
      if (destroyed) return;
      destroyed = true;
      /* Closing the canvas takes its gestures down with it — they belong to the
         canvas now, so there is nothing left here to unhook. */
      viewer?.destroy();
      viewer = null;
      box.textContent = "";
      say("");
      why.textContent = "";
    },
  };

  return handle;
}
