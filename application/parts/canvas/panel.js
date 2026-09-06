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
            <!-- Colour or grey, a toggle of its own at the head of the
                 row: a knob that sits on the left over three coloured
                 bars while the picture is in colour, and slides right
                 over three grey bars once it is grey. It acts on the
                 pictures only; the masks keep their own colours
                 whichever side it is on. -->
            <span class="grey-toggle" id="grey-toggle" role="group" aria-label="Colour or grey" data-grey="false">
              <button class="bare" id="colour-btn" type="button" aria-pressed="true" aria-label="Colour"
                      title="Colour: every picture in its own colours">
                <svg class="grey-glyph colours" width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
                  <rect class="bar-r" x="1" y="3" width="4.6" height="10" rx="1.2"/>
                  <rect class="bar-g" x="6.7" y="3" width="4.6" height="10" rx="1.2"/>
                  <rect class="bar-b" x="12.4" y="3" width="4.6" height="10" rx="1.2"/>
                </svg>
              </button>
              <button class="bare" id="grey-btn" type="button" aria-pressed="false" aria-label="Grey"
                      title="Grey: every picture in grey">
                <svg class="grey-glyph greys" width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
                  <rect class="bar-r" x="1" y="3" width="4.6" height="10" rx="1.2"/>
                  <rect class="bar-g" x="6.7" y="3" width="4.6" height="10" rx="1.2"/>
                  <rect class="bar-b" x="12.4" y="3" width="4.6" height="10" rx="1.2"/>
                </svg>
              </button>
            </span>
            <!-- A joined strip: which acquisition the row is about -- the
                 eye, its name, a caret that opens the list -- and its
                 channels in a box beside it. -->
            <span class="canvas-strip" id="acquisition-pick" hidden>
              <button class="run strip-first" id="acquisition-btn" type="button" aria-haspopup="true" aria-expanded="false"
                      title="Which acquisition the row shows; show or hide any of them">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/></svg>
                <span id="acquisition-name">Overview</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>
              </button>
              <!-- The acquisition's channels, in a flat box joined onto the
                   strip: a dot in each channel's colour with its name when
                   there is room, its number in the dot when there is not.
                   The dot shows or hides the channel; the name opens its
                   settings. The masks stand in the same box, past a short
                   dividing line: they lie on the acquisition, but they are
                   their own thing, and the colour-or-grey toggle leaves
                   them alone. -->
              <span class="canvas-channels" id="canvas-channels">
              <span class="canvas-chips" id="canvas-chips"></span>
              <!-- While the picture is grey the acquisition is one grey
                   channel: this chip stands in for the dots, and its box
                   holds the one window, opacity and Auto for the sum. -->
              <span class="chip grey-chip on" id="grey-chip" hidden>
                <button class="chip-dot grey-dot" id="grey-chip-btn" type="button"
                        title="The grey channel: its histogram, window and opacity">G</button>
                <button class="chip-name" id="grey-chip-name" type="button">Grey</button>
              </span>
              <span class="chip-divide" id="mask-divide" hidden></span>
              <span class="chip mask-chip on" id="mask-chip" hidden>
              <!-- The masks' chip is a cell's shape, not a circle: a small
                   spindle in the masks' colour. Pressed, its card opens. -->
              <button class="chip-dot mask-dot" id="mask-btn" type="button" aria-pressed="true"
                      title="Masks: shown or hidden, their colour, look and opacity">
                <!-- A cell with long branching processes, the way a
                     stellate cell lies. It wears the masks' own dress:
                     their colour, or the rainbow for each object its own;
                     filled, or a thick outline round a white middle when
                     Line is chosen. -->
                <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
                  <defs>
                    <linearGradient id="mask-rainbow" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0" stop-color="#4f7bff"/><stop offset="0.25" stop-color="#c04bff"/>
                      <stop offset="0.5" stop-color="#ff4d6d"/><stop offset="0.7" stop-color="#ffb02e"/>
                      <stop offset="0.85" stop-color="#8be04a"/><stop offset="1" stop-color="#2fd6c9"/>
                    </linearGradient>
                  </defs>
                  <path class="mask-shape" d="M20.4 12.2C20.6 12.4 20.9 12.6 21.1 12.9C21.3 13.1 21.4 13.4 21.5 13.6C21.5 13.9 21.4 14.1 21.2 14.3C21.1 14.5 20.8 14.7 20.5 14.8C20.2 15.0 19.8 15.1 19.5 15.1C19.1 15.2 18.7 15.2 18.4 15.3C18.1 15.3 17.8 15.4 17.5 15.4C17.3 15.4 17.1 15.5 16.9 15.6C16.8 15.6 16.6 15.7 16.6 15.8C16.5 16.0 16.4 16.1 16.4 16.3C16.4 16.5 16.4 16.7 16.4 17.0C16.4 17.2 16.5 17.5 16.5 17.8C16.5 18.1 16.4 18.4 16.4 18.6C16.3 18.9 16.2 19.1 16.1 19.3C15.9 19.4 15.7 19.5 15.5 19.5C15.3 19.6 15.1 19.5 14.8 19.4C14.6 19.3 14.3 19.1 14.1 19.0C13.9 18.8 13.6 18.6 13.4 18.5C13.2 18.3 13.1 18.2 12.9 18.1C12.7 18.0 12.6 17.9 12.4 17.8C12.3 17.8 12.1 17.8 12.0 17.8C11.9 17.9 11.7 17.9 11.6 18.0C11.4 18.1 11.2 18.3 11.1 18.5C10.9 18.6 10.7 18.9 10.4 19.1C10.2 19.3 9.9 19.5 9.7 19.7C9.4 19.9 9.1 20.1 8.8 20.3C8.6 20.4 8.3 20.4 8.0 20.4C7.8 20.4 7.6 20.3 7.4 20.1C7.3 19.9 7.2 19.7 7.1 19.4C7.0 19.1 7.0 18.7 7.0 18.4C7.1 18.1 7.1 17.7 7.2 17.4C7.2 17.1 7.3 16.8 7.3 16.5C7.4 16.3 7.4 16.0 7.4 15.8C7.5 15.6 7.5 15.5 7.4 15.3C7.4 15.1 7.4 15.0 7.3 14.9C7.3 14.8 7.2 14.6 7.2 14.5C7.1 14.4 7.0 14.3 6.9 14.2C6.7 14.1 6.6 14.0 6.4 13.9C6.3 13.8 6.1 13.7 5.9 13.6C5.7 13.5 5.4 13.4 5.2 13.2C4.9 13.1 4.6 12.9 4.4 12.8C4.2 12.6 4.0 12.4 3.9 12.2C3.7 12.0 3.6 11.8 3.6 11.6C3.6 11.4 3.7 11.2 3.8 11.0C4.0 10.8 4.2 10.6 4.4 10.5C4.6 10.3 4.9 10.2 5.1 10.1C5.4 10.0 5.7 9.9 5.9 9.8C6.1 9.7 6.3 9.6 6.5 9.5C6.6 9.4 6.7 9.3 6.8 9.2C6.8 9.0 6.8 8.9 6.8 8.7C6.8 8.5 6.7 8.2 6.7 7.9C6.6 7.7 6.5 7.4 6.4 7.0C6.4 6.7 6.3 6.3 6.2 6.0C6.2 5.6 6.2 5.3 6.2 5.0C6.3 4.7 6.4 4.4 6.5 4.1C6.6 3.9 6.8 3.7 7.0 3.5C7.1 3.3 7.3 3.1 7.6 3.0C7.8 2.8 8.0 2.7 8.2 2.6C8.4 2.4 8.7 2.3 8.9 2.2C9.2 2.1 9.4 2.1 9.7 2.0C9.9 2.0 10.2 2.1 10.5 2.2C10.8 2.3 11.0 2.5 11.3 2.7C11.5 2.9 11.8 3.2 12.0 3.5C12.2 3.8 12.4 4.2 12.6 4.5C12.7 4.8 12.9 5.1 13.0 5.4C13.2 5.7 13.3 5.9 13.4 6.1C13.5 6.4 13.6 6.5 13.7 6.7C13.8 6.8 13.9 6.9 14.1 6.9C14.2 7.0 14.3 7.0 14.5 7.0C14.7 7.0 14.8 7.0 15.1 6.9C15.3 6.8 15.5 6.8 15.8 6.7C16.0 6.6 16.3 6.5 16.6 6.4C16.9 6.4 17.2 6.3 17.5 6.3C17.8 6.3 18.0 6.3 18.2 6.4C18.4 6.5 18.6 6.7 18.7 6.9C18.8 7.0 18.8 7.3 18.8 7.6C18.8 7.8 18.7 8.1 18.6 8.4C18.5 8.6 18.4 8.9 18.3 9.2C18.2 9.4 18.0 9.7 18.0 9.9C17.9 10.1 17.9 10.2 17.9 10.4C17.9 10.5 18.0 10.7 18.1 10.8C18.2 10.9 18.4 11.1 18.6 11.2C18.8 11.3 19.1 11.5 19.4 11.6C19.7 11.8 20.1 12.0 20.4 12.2Z"/>
                </svg>
              </button>
              <button class="chip-name" id="mask-name" type="button" aria-haspopup="true" aria-expanded="false"
                      title="The masks' colour, look and opacity">Mask</button>
              <div class="canvas-card mask-pop" id="mask-pop" hidden>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Masks</span>
                  <span class="seg mask-look">
                    <button id="mask-shown" type="button" aria-pressed="true">Shown</button>
                    <button id="mask-hidden" type="button" aria-pressed="false">Hidden</button>
                  </span>
                </div>
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
              <!-- The chosen channel's box, the very one from Display
                   settings, lent to the row while it is open here. -->
              <div class="canvas-card channel-pop" id="channel-pop" hidden></div>
              <div class="canvas-card grey-pop" id="grey-pop" hidden></div>
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
        maskDivide: find("mask-divide"),
        maskShape: host.querySelector(".mask-shape"),
        maskName: find("mask-name"),
        maskShown: find("mask-shown"),
        maskHidden: find("mask-hidden"),
        channelPop: find("channel-pop"),
        greyChip: find("grey-chip"),
        greyChipButton: find("grey-chip-btn"),
        greyChipName: find("grey-chip-name"),
        greyPop: find("grey-pop"),
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
        colour: find("colour-btn"),
        greyToggle: find("grey-toggle"),
        legend: find("canvas-legend"),
        overviewCanvas: find("overview-canvas"),
        overviewNote: find("overview-note"),
        pictureHost: find("picture-host"),
      },
    };
  },
};
