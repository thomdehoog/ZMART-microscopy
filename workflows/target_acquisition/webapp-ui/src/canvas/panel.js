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
 * ## What it draws over and under the picture, which for now is nothing
 *
 * The interface offers two slots for the application's own drawing: one beneath
 * the picture and one above it. This step uses neither, because it exists to
 * show the canvas on its own. Each slot is handed nothing at all rather than a
 * function that paints nothing, and the difference is not tidiness — told there
 * is nothing to draw, an engine need not lay a drawing surface down, clear it
 * every frame or carry it to the graphics card, so a step that draws nothing
 * costs nothing for the slots it is not using.
 *
 * ## One thing the page cannot yet tell the canvas
 *
 * The interface asks the page to say what colours of light a run recorded and
 * how bright to draw them. This page does not know: a run records that in its
 * own description, and the only way to read it is to open the run — which is
 * the very thing the canvas is being asked to do. So nothing is said, and each
 * engine falls back to drawing the first channel in white over a wide
 * brightness range. That is enough to see a picture and to compare two engines
 * on the same one, and it is not enough for a run of several colours. Reading
 * the description first, or asking the canvas for it afterwards, is the fix, and
 * it wants a decision on the interface rather than a workaround here.
 */

import { onlyPanAndZoom } from "../../../../../viz_studio/options/harness/src/gestures.js";
import { describeEngine, enginesBuiltIn, openerFor } from "./engines.js";

/**
 * The colour of the box the picture is drawn in.
 *
 * Dark, because an acquisition is dark and ground the microscope has never
 * visited should look empty rather than look broken. The engine is told this
 * colour as well as the box being painted with it, so that wherever there is no
 * picture there is no visible seam between one drawing surface and the next.
 */
const THE_COLOUR_BEHIND_THE_PICTURE = "#05070d";

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
 * @param chooser an element to fill with one button per engine, so that the same
 *   run can be looked at through one engine and then another.
 * @param readout a small element that says where the view is, in micrometres.
 * @param acquisitions the addresses of the run's images, as whole addresses
 *   including the scheme and the host, in the order they should be drawn with
 *   the first at the bottom. An empty list means the page was not pointed at a
 *   run, which is said on screen rather than left as an empty box.
 * @param engine which engine to open with. An unknown name is refused with a
 *   list of what there is.
 *
 * @returns a handle with `whenShown()`, to be called each time the panel comes
 *   into view; `changeTo(name)`, which swaps the engine and keeps the view; and
 *   `destroy()`. All of them are safe to call after `destroy()`, so a page
 *   tearing itself down need not keep track of the order.
 */
export function putTheCanvasIn({ box, note, chooser, readout, acquisitions, engine }) {
  const built = enginesBuiltIn();
  let wanted = built.includes(engine) ? engine : built[0];

  let viewer = null;      // the picture, once an engine has been opened on it
  let opening = false;
  let gestures = null;
  let destroyed = false;
  /* Where the view was when the engine was last changed. Held here rather than
     inside any one engine, because comparing two ways of drawing the same thing
     is very hard if reaching the second one means finding your way back to where
     you were: small differences are only visible when the two pictures are of
     the same view moments apart. */
  let carriedOver = null;

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

  function sayWhichEngineIsDrawing() {
    if (!viewer) return;
    say(`${wanted} — ${describeEngine(wanted)}`);
    for (const button of chooser.querySelectorAll("button")) {
      button.setAttribute("aria-checked", String(button.dataset.engine === wanted));
    }
  }

  /** Open the chosen engine on the run, and put the view where it was. */
  async function openTheCanvas() {
    const openViewer = await openerFor(wanted);
    const opened = await openViewer(box, {
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
    });
    // Both slots left empty; the long note at the top of this file says why.
    opened.drawUnder(null);
    opened.drawOver(null);
    if (carriedOver) opened.setView(carriedOver);
    viewer = opened;
    sayWhichEngineIsDrawing();
    sayWhereTheViewIs(opened.getView());
    return opened;
  }

  /**
   * Change the engine underneath, keeping the view exactly where it is.
   *
   * The old picture is closed, the new one is opened in the same box, and the
   * centre and the magnification are carried across. If the new one will not
   * open, the one that was working is put back on the same view and the reason
   * is written in the corner — a box that has quietly gone blank because
   * somebody pressed a button is worse than one that never worked.
   */
  async function changeTo(name) {
    if (destroyed || opening || name === wanted || !viewer) return;
    opening = true;
    const wasDrawing = wanted;
    carriedOver = viewer.getView();
    say(`opening ${name}…`);
    try {
      viewer.destroy();
      viewer = null;
      wanted = name;
      await openTheCanvas();
    } catch (why) {
      wanted = wasDrawing;
      try {
        await openTheCanvas();
        say(`${wanted} — could not change to ${name}: ${why.message}`);
      } catch (alsoWhy) {
        say(`nothing could be drawn: ${alsoWhy.message}`);
      }
    } finally {
      opening = false;
    }
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

  const handle = {
    /** Which engine is drawing now. */
    get engine() { return wanted; },

    /** Whether a picture is open, which is what a test asks before looking. */
    get open() { return !!viewer; },

    changeTo,

    /**
     * Called each time the panel comes into view.
     *
     * The canvas is opened the first time and kept afterwards. Opening reads the
     * run's description over the network, so it is not something to do on every
     * render, and opening again would throw away wherever the operator had
     * panned to.
     */
    async whenShown() {
      if (destroyed || viewer || opening) return;
      if (!acquisitions.length) {
        say(
          "this page was not given a run to look at. Add the address of one to " +
            "the page's own address — ?overview=http://host:port/run.ome.zarr — " +
            "and reload. `live_overview_demo.py` writes a run and prints the " +
            "address to use.",
        );
        return;
      }
      opening = true;
      say(`opening ${wanted}…`);
      try {
        const opened = await openTheCanvas();
        /* Dragging pans and the plain wheel zooms, and nothing else moves the
           view. The two gestures belong to the page rather than to any one
           engine: if each engine interpreted them for itself, a difference in
           how the two feel might be the engine or might be somebody's idea of
           how far a wheel notch should zoom, and there would be no way to tell
           which. They listen on the box, which stays put when the engine
           changes, and they reach whichever picture is in it now. */
        gestures = onlyPanAndZoom(box, {
          getView: () => viewer.getView(),
          setView: (view) => viewer.setView(view),
          sizeOf: () => ({ width: box.clientWidth, height: box.clientHeight }),
        });
        /* Left where a browser test can reach it. Nothing on the page reads
           this. What matters about a picture is what reached the screen, and a
           viewer that reports itself perfectly loaded while drawing nothing is
           the failure this is meant to catch — so the tests photograph the box
           and this is only the means to ask the picture to move. */
        window.__theCanvas = handle;
        return opened;
      } catch (why) {
        say(`the run could not be opened — ${why.message}`);
      } finally {
        opening = false;
      }
      return null;
    },

    destroy() {
      if (destroyed) return;
      destroyed = true;
      gestures?.stop();
      viewer?.destroy();
      viewer = null;
      box.textContent = "";
      say("");
    },
  };

  return handle;
}
