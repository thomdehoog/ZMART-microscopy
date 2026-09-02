/**
 * The canvas, as a panel a workflow offers.
 *
 * The framework has no canvas. It runs whatever workflow it is given, and a
 * workflow that never looks at a stage — an analysis, a report, a set of
 * forms — should not be handed one, nor pay for the markup of one. So the
 * canvas is declared here, in the workflow that wants it, and the framework
 * only mounts what it is handed.
 *
 * It belongs to the workflow rather than to any one of its steps. Every step
 * from the carrier onward is looking at the same square millimetre of glass,
 * and the picture of it is one picture: the layers a step contributes are put
 * on the stack this panel holds, and pan, zoom and the transparency dial act
 * on all of them together. That is what makes the layers comparable, and it
 * is why no step owns the canvas.
 *
 * What this file is, precisely, is the panel's shape and the elements in it.
 * What gets drawn in it is `../stage.js`, and what any of it means is the
 * steps'.
 */

export const canvasPanel = {
  key: "canvas",
  label: "Canvas",

  /* Once a step has asked for the canvas it stays for the rest of the run.
     It is the microscope's own limits drawn to scale, so it is the window the
     run happens inside rather than one step's view of it; leaving it behind
     between two steps that both work on the stage would be closing the window
     to open the same one again. */
  stays: true,

  /**
   * Build the panel's insides.
   *
   * The channel is here rather than in the framework because it is the canvas's
   * own edge: a step whose work is about the picture docks its controls beside
   * what they change instead of on a tab that would hide it. A panel with no
   * channel simply returns none, and the step's controls have to live in a
   * panel of their own.
   */
  build(host) {
    host.innerHTML = `
      <div class="canvas-body">
        <div class="plot-host">
          <!-- Where the picture is built. The drawing engine makes its own
               surfaces inside this, and the workflow's layers are drawn over
               them, so nothing here is a canvas of the page's own. It keeps
               the id the tests aim by, because what they want of it is where
               the picture is on screen. -->
          <div class="plot stagecv" id="stage-canvas"></div>
          <!-- The overview as it is being acquired, drawn from the images the
               run is writing. It covers the plan while the scan is the thing
               being looked at, and is only there at all when the page was
               given a run to watch. -->
          <canvas class="plot livecv" id="overview-canvas" hidden></canvas>
          <!-- Where the scan itself is drawn, beneath the plan. Empty unless
               the page was pointed at a folder of small pictures with
               \`?picture=\`; the drawing engine builds its own surfaces inside
               it. See \`viz_studio/options/jpeg-under/\`. -->
          <div class="plot picturecv" id="picture-host"></div>
          <div class="live-note" id="overview-note" hidden></div>
          <div class="tip" id="stage-tip"></div>
        </div>
        <!-- The divider is the channel's edge made draggable: the operator
             reshapes how much of the window the channel takes. -->
        <div class="side-divider" id="side-divider" role="separator"
             aria-orientation="vertical" aria-label="resize the channel" hidden></div>
        <!-- The column's fold: one press puts the whole column away to the
             right and gives the canvas the room; the strip that stays is the
             press that brings it back. -->
        <button class="side-fold" id="side-fold" type="button" hidden
                aria-label="fold the channel away" title="Fold the channel away">›</button>
        <aside class="canvas-side" id="canvas-side" hidden></aside>
        <!-- The picture's own controls -- its acquisitions, channels and
             windows -- stand in the same column as the step's channel, and
             the tab row over the column says which of the two is showing.
             One column, one width: switching never moves the canvas. -->
        <aside class="canvas-side display-side" id="display-side" hidden></aside>
      </div>
      <div class="canvas-foot">
        <div class="toolbar">
          <!-- What is drawn and how is the picture's own business, not this
               bar's: which layers are on, how solid they are and which plane
               of a stack is showing are all questions about a picture, and
               the stack that draws it is where they will be asked. -->
          <!-- Which layers are on, how solid they are: questions about the
               picture, asked on the picture's own bar. -->
          <div class="layer-bar" id="stage-layers"></div>
          <button class="ghost" id="fit-btn">Fit</button>
          <div class="readout" id="stage-readout">—</div>
        </div>
        <div class="panel-foot" id="foot-canvas"></div>
      </div>`;

    const find = (id) => host.querySelector(`#${id}`);
    return {
      /* The channel, its edge, and the strip the framework puts a step's
         button in — the three things the framework does anything with. */
      channel: find("canvas-side"),
      display: find("display-side"),
      divider: find("side-divider"),
      fold: find("side-fold"),
      foot: find("foot-canvas"),
      /* Everything the picture is drawn on and into. Handed to `openTheStage`
         and to the pictures of a real run, so neither has to know an id. */
      parts: {
        box: find("stage-canvas"),
        layerBar: find("stage-layers"),
        tip: find("stage-tip"),
        readout: find("stage-readout"),
        fit: find("fit-btn"),
        overviewCanvas: find("overview-canvas"),
        overviewNote: find("overview-note"),
        pictureHost: find("picture-host"),
      },
    };
  },
};
