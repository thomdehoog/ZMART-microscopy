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
        <div class="plot-column">
        <!-- A row the canvas keeps for its own controls, so the picture never
             reaches the top edge and nothing floats over it. Left, the two
             presses that say what to look at; right, whatever legend the
             layer on show needs read, such as the focus map's colour ramp. -->
        <div class="canvas-toolbar" id="canvas-toolbar">
          <!-- Left, the two presses that say what to look at. -->
          <button class="run icon" id="carrier-btn" type="button" aria-label="Carrier"
                  title="Carrier: frame the carrier on the stage">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 5.5V2h3.5M10.5 2H14v3.5M14 10.5V14h-3.5M5.5 14H2v-3.5"/><rect x="5" y="6" width="6" height="4" rx="0.8"/></svg>
          </button>
          <button class="run icon" id="tileset-btn" type="button" disabled aria-label="Tile set"
                  title="Tile set: frame the nearest tileset; press again for the next">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="2.5" y="2.5" width="4.5" height="4.5" rx="0.8"/><rect x="9" y="2.5" width="4.5" height="4.5" rx="0.8"/><rect x="2.5" y="9" width="4.5" height="4.5" rx="0.8"/><rect x="9" y="9" width="4.5" height="4.5" rx="0.8"/></svg>
          </button>
          <button class="run icon" id="tile-btn" type="button" disabled aria-label="Tile"
                  title="Tile: frame the one field the frame is on">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1"/></svg>
          </button>
          <!-- Right, the picture: which acquisition the row is about, its
               channels as chips, the masks as one of them, and Grayscale.
               A chip's dot shows or hides it; its name opens its settings. -->
          <span class="canvas-toolbar-right">
            <!-- A joined strip: which acquisition the row is about -- the
                 layers pictogram, its name, a caret that opens the list --
                 and beside it the grey switch. -->
            <span class="canvas-strip" id="acquisition-pick" hidden>
              <button class="run strip-first" id="acquisition-btn" type="button" aria-haspopup="true" aria-expanded="false"
                      title="Which acquisition the row shows; show or hide any of them">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/></svg>
                <span id="acquisition-name">Overview</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>
              </button>
              <!-- Grey, square-cornered so it sits flush between the picker
                   and the channels. Its glyph shows three colours while the
                   picture is in colour and three greys once it is grey. -->
              <button class="run icon switch strip-mid" id="grey-btn" type="button" aria-pressed="false" aria-label="Grey"
                      title="Grey: every picture in grey; press again for its colours">
                <svg class="grey-glyph" width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
                  <rect class="bar-r" x="1" y="3" width="4.6" height="10" rx="1.2"/>
                  <rect class="bar-g" x="6.7" y="3" width="4.6" height="10" rx="1.2"/>
                  <rect class="bar-b" x="12.4" y="3" width="4.6" height="10" rx="1.2"/>
                </svg>
              </button>
              <!-- The acquisition's channels, in a flat box joined onto the
                   strip: a dot in each channel's colour with its name when
                   there is room, its number in the dot when there is not.
                   The dot shows or hides the channel; the name opens its
                   settings. The masks are one chip more, of the same kind,
                   since they belong to the same acquisition. -->
              <span class="canvas-channels" id="canvas-channels">
              <span class="canvas-chips" id="canvas-chips"></span>
              <span class="chip mask-chip on" id="mask-chip" hidden>
              <button class="chip-dot mask-dot" id="mask-btn" type="button" aria-pressed="true"
                      title="Masks: press to show or hide, press twice for their colour, look and opacity">
                <!-- A cell's contour: the masks are outlines of objects. -->
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.8 10.2 2 13.8 5.6 12.6 11.2 7.4 13.8 2.6 10.4 2.2 6.2z"/></svg>
              </button>
              <button class="chip-name" id="mask-name" type="button" aria-haspopup="true" aria-expanded="false"
                      title="The masks' colour, look and opacity">Mask</button>
              <div class="canvas-card mask-pop" id="mask-pop" hidden>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Colour</span>
                  <span class="mask-colours" id="mask-colours"></span>
                </div>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Look</span>
                  <span class="seg mask-look">
                    <button id="mask-fill" type="button" aria-pressed="true">Fill</button>
                    <button id="mask-line" type="button" aria-pressed="false">Line</button>
                  </span>
                </div>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Opacity</span>
                  <input id="mask-opacity" type="range" min="10" max="100" step="5"
                         aria-label="mask opacity">
                </div>
              </div>
              </span>
              </span>
              <div class="canvas-card acquisition-menu" id="acquisition-menu" hidden></div>
            </span>
          </span>
        </div>
        <div class="plot-host">
          <!-- A legend for the layer on show -- the focus map's colour
               ramp -- at the foot of the picture on the left, on a plate,
               clear of the scale bar at the right. -->
          <div class="canvas-legend" id="canvas-legend" hidden>
            <span class="canvas-legend-ramp"></span>
            <span class="canvas-legend-ends">
              <span class="canvas-legend-lo"></span>
              <span class="canvas-legend-title"></span>
              <span class="canvas-legend-hi"></span>
            </span>
          </div>
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
        </div>
        <!-- The divider is the channel's edge made draggable: the operator
             reshapes how much of the window the channel takes. -->
        <div class="side-divider" id="side-divider" role="separator"
             aria-orientation="vertical" aria-label="resize the channel" hidden></div>
        <!-- The column's fold: one press puts the whole column away to the
             right and gives the canvas the room; the strip that stays is the
             press that brings it back. -->
        <button class="side-fold" id="side-fold" type="button" hidden
                aria-label="Collapse right sidebar" title="Collapse right sidebar"
                aria-expanded="true"><span aria-hidden="true">›</span></button>
        <aside class="canvas-side" id="canvas-side" hidden></aside>
        <!-- The picture's own controls -- its acquisitions, channels and
             windows -- stand in the same column as the step's channel, and
             the tab row over the column says which of the two is showing.
             One column, one width: switching never moves the canvas. -->
        <aside class="canvas-side display-side" id="display-side" hidden>
          <div class="display-layer-settings side-group">
            <div class="side-group-title">Canvas layers</div>
            <div class="side-group-body">
              <div class="layer-bar" id="stage-layers"></div>
            </div>
          </div>
        </aside>
      </div>
      `;

    const find = (id) => host.querySelector(`#${id}`);
    return {
      /* The channel, its edge, and the strip the framework puts a step's
         button in — the three things the framework does anything with. */
      channel: find("canvas-side"),
      display: find("display-side"),
      divider: find("side-divider"),
      fold: find("side-fold"),
      foot: null,
      /* Everything the picture is drawn on and into. Handed to `openTheStage`
         and to the pictures of a real run, so neither has to know an id. */
      parts: {
        box: find("stage-canvas"),
        layerBar: find("stage-layers"),
        tip: find("stage-tip"),
        readout: null,
        carrier: find("carrier-btn"),
        tileset: find("tileset-btn"),
        tile: find("tile-btn"),
        mask: find("mask-btn"),
        maskChip: find("mask-chip"),
        maskName: find("mask-name"),
        maskPop: find("mask-pop"),
        acquisitionPick: find("acquisition-pick"),
        acquisitionName: find("acquisition-name"),
        acquisitionMenu: find("acquisition-menu"),
        chips: find("canvas-chips"),
        channelsBox: find("canvas-channels"),
        maskColours: find("mask-colours"),
        maskFill: find("mask-fill"),
        maskLine: find("mask-line"),
        maskOpacity: find("mask-opacity"),
        grey: find("grey-btn"),
        legend: find("canvas-legend"),
        overviewCanvas: find("overview-canvas"),
        overviewNote: find("overview-note"),
        pictureHost: find("picture-host"),
      },
    };
  },
};
