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
               A press on a chip opens its box. -->
          <span class="canvas-toolbar-right">
            <!-- Colour or grey, a toggle of its own at the head of the
                 row. Each side is a ramp, the bar a microscopist knows
                 from the lookup table of any viewer: a rainbow ramp for
                 colour, a black-to-white ramp for grey. The knob sits
                 over the side in force. It acts on the pictures only;
                 the masks keep their own colours whichever side it is
                 on. -->
            <span class="grey-toggle" id="grey-toggle" role="group" aria-label="Colour or grey" data-grey="false">
              <button class="bare" id="colour-btn" type="button" aria-pressed="true" aria-label="Colour"
                      title="Colour: every channel in its own colour">
                <svg class="grey-glyph colours" width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
                  <defs>
                    <linearGradient id="ramp-colours" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0" stop-color="#3b82f6"/><stop offset="0.35" stop-color="#22c55e"/>
                      <stop offset="0.65" stop-color="#eab308"/><stop offset="1" stop-color="#ef4444"/>
                    </linearGradient>
                  </defs>
                  <rect class="ramp" x="1" y="4" width="16" height="8" rx="1.5"/>
                </svg>
              </button>
              <button class="bare" id="grey-btn" type="button" aria-pressed="false" aria-label="Grey"
                      title="Grey: the channels folded into one grey picture">
                <svg class="grey-glyph greys" width="18" height="16" viewBox="0 0 18 16" aria-hidden="true">
                  <defs>
                    <linearGradient id="ramp-greys" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0" stop-color="#111827"/><stop offset="1" stop-color="#f3f4f6"/>
                    </linearGradient>
                  </defs>
                  <rect class="ramp" x="1" y="4" width="16" height="8" rx="1.5"/>
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
                   strip: a numbered dot in each channel's colour, and no
                   more, since the colour and the number say which channel
                   it is. The dot opens the channel's box. The masks stand in the same box, past a short
                   dividing line: they lie on the acquisition, but they are
                   their own thing, and the colour-or-grey toggle leaves
                   them alone. -->
              <span class="canvas-channels" id="canvas-channels">
              <span class="canvas-chips" id="canvas-chips"></span>
              <!-- While the picture is grey the acquisition is one grey
                   channel: this chip stands in for the dots, and its box
                   holds the one window, opacity and Auto for the sum. -->
              <span class="chip grey-chip on" id="grey-chip" hidden>
                <button class="chip-dot grey-dot" id="grey-chip-btn" type="button" aria-label="Grey"
                        title="The grey channel: its histogram, window and opacity">1</button>
              </span>
              <span class="chip-divide" id="mask-divide" hidden></span>
              <span class="chip mask-chip on" id="mask-chip" hidden>
              <!-- The masks' chip is a cell's shape, not a circle: a small
                   spindle in the masks' colour. Pressed, its card opens. -->
              <button class="chip-dot mask-dot" id="mask-btn" type="button" aria-pressed="true" aria-haspopup="true" aria-expanded="false"
                      title="Masks: shown or hidden, their colour, look and opacity">
                <!-- A cell with six uneven bumps, no two sides alike, the
                     way a real cell lies. It wears the masks' own dress:
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
                  <path class="mask-shape" d="M16.70 14.15 C16.96 14.81 18.88 16.79 19.07 17.57 C19.25 18.36 18.58 19.05 17.79 18.89 C16.99 18.73 15.05 17.03 14.30 16.63 C13.55 16.23 13.45 16.24 13.28 16.50 C13.11 16.76 13.42 17.79 13.26 18.20 C13.10 18.62 12.63 18.86 12.32 18.99 C12.01 19.12 11.70 19.12 11.40 18.97 C11.10 18.83 10.91 18.46 10.50 18.15 C10.08 17.83 9.52 17.66 8.93 17.08 C8.33 16.51 7.79 15.26 6.93 14.70 C6.07 14.14 4.34 14.24 3.78 13.74 C3.23 13.25 3.15 12.32 3.60 11.74 C4.06 11.16 5.92 10.57 6.53 10.24 C7.14 9.92 7.10 10.17 7.27 9.80 C7.43 9.43 7.52 8.66 7.52 8.03 C7.53 7.40 7.19 6.46 7.32 6.01 C7.45 5.57 7.84 5.30 8.31 5.36 C8.77 5.41 9.53 6.12 10.09 6.33 C10.65 6.54 11.44 6.47 11.67 6.61 C11.89 6.75 11.25 7.82 11.46 7.16 C11.67 6.50 12.40 3.35 12.92 2.65 C13.44 1.95 14.35 2.12 14.58 2.96 C14.81 3.80 14.22 6.76 14.28 7.70 C14.34 8.64 14.33 8.33 14.94 8.59 C15.55 8.85 17.33 9.03 17.93 9.27 C18.53 9.51 18.38 9.78 18.51 10.04 C18.64 10.31 18.70 10.55 18.70 10.84 C18.70 11.13 18.72 11.32 18.52 11.79 C18.33 12.26 17.82 13.26 17.52 13.66 C17.21 14.05 16.44 13.50 16.70 14.15Z"/>
                </svg>
              </button>
              <div class="canvas-card mask-pop" id="mask-pop" hidden>
                <!-- The masks' card, in the language of a channel's box: an
                     eye and a name at the head, then the colour, the look
                     and the opacity, one quiet row each. -->
                <div class="mask-pop-head">
                  <button class="mask-eye" id="mask-eye" type="button" aria-pressed="true" title="Show or hide the masks">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/><path class="mask-eye-slash" d="M3 13L13 3"/></svg>
                  </button>
                  <span class="mask-pop-name">Masks</span>
                </div>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Colour</span>
                  <span class="mask-colours" id="mask-colours"></span>
                </div>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Look</span>
                  <span class="seg mask-look">
                    <button id="mask-fill" type="button" aria-pressed="true">Solid</button>
                    <button id="mask-line" type="button" aria-pressed="false">Outline</button>
                  </span>
                </div>
                <div class="mask-pop-row">
                  <span class="mask-pop-label">Opacity</span>
                  <span class="mask-opacity-row">
                    <input class="zv-range" id="mask-opacity" type="range" min="10" max="100" step="5" aria-label="mask opacity">
                    <output class="mask-opacity-value" id="mask-opacity-value" aria-hidden="true">80%</output>
                  </span>
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
        maskEye: find("mask-eye"),
        maskOpacityValue: find("mask-opacity-value"),
        channelPop: find("channel-pop"),
        greyChip: find("grey-chip"),
        greyChipButton: find("grey-chip-btn"),
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
