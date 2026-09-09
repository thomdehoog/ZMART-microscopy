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
        <!-- The canvas's own controls, floating over the top of the picture
             so it reaches the top edge. Left, the two presses that say what
             to look at; right, whatever legend the layer on show needs read,
             such as the focus map's colour ramp. -->
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
               channels as chips, the masks as one of them. A press on a
               chip opens its box. -->
          <span class="canvas-toolbar-right">
            <!-- A joined strip: which acquisition the row is about -- the
                 eye, the ramp chip, its name, a caret that opens the list --
                 and its channels in a box beside it.

                 The press is a span rather than a button because the chip
                 inside it is a button of its own: colour or grey is a
                 property of the acquisition, so its switch stands on the
                 acquisition's name, and the same chip stands on every line
                 of the menu. The chip wears the ramp a microscopist knows
                 from the lookup table of any viewer: a rainbow ramp while
                 the acquisition is in colour, a black-to-white ramp while it
                 is grey. It acts on the pictures only; the masks keep their
                 own colours. -->
            <span class="canvas-strip" id="acquisition-pick" hidden>
              <span class="run strip-first acquisition-press" id="acquisition-btn" role="button" tabindex="0"
                    aria-haspopup="true" aria-expanded="false"
                    title="Which acquisition the row shows; show or hide any of them">
                <!-- The word says what kind of layer the press names, so the
                     masks' bar beside it, headed MASKS, reads as another kind
                     of thing before the eye reaches the dots and cells. -->
                <span class="bar-word">acquisitions</span>
                <!-- The eye is the acquisition's own switch, the same one its
                     line in the menu carries: pressed here it hides or shows
                     the acquisition the row is on, without opening the menu. -->
                <button class="acquisition-eye" id="acquisition-eye" type="button" aria-pressed="true"
                        aria-label="show or hide this acquisition" title="Hide this acquisition">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/><path class="acquisition-eye-slash" d="M3 13L13 3"/></svg>
                </button>
                <button class="ramp-chip" id="ramp-chip" type="button" aria-pressed="false" aria-label="Colour or grey"
                        title="Show this layer in grey">
                  <svg width="14" height="8" viewBox="0 0 14 8" aria-hidden="true">
                    <defs>
                      <linearGradient id="ramp-colours" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0" stop-color="#3b82f6"/><stop offset="0.35" stop-color="#22c55e"/>
                        <stop offset="0.65" stop-color="#eab308"/><stop offset="1" stop-color="#ef4444"/>
                      </linearGradient>
                      <linearGradient id="ramp-greys" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0" stop-color="#111827"/><stop offset="1" stop-color="#f3f4f6"/>
                      </linearGradient>
                    </defs>
                    <rect class="ramp colours" width="14" height="8" rx="1.5"/>
                    <rect class="ramp greys" width="14" height="8" rx="1.5"/>
                  </svg>
                </button>
                <span id="acquisition-name">Overview</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>
              </span>
              <!-- The acquisition's channels, in a flat box joined onto the
                   strip: a numbered dot in each channel's colour, and no
                   more, since the colour and the number say which channel
                   it is. The dot opens the channel's box. The masks stand in the same box, past a short
                   dividing line: they lie on the acquisition, but they are
                   their own thing, and stand in a bar of their own. -->
              <span class="canvas-channels" id="canvas-channels">
              <span class="canvas-chips" id="canvas-chips"></span>
              <!-- While the picture is grey the acquisition is one grey
                   channel: this chip stands in for the dots, and its box
                   holds the one window, opacity and Auto for the sum. -->
              <span class="chip grey-chip on" id="grey-chip" hidden>
                <!-- The one grey channel cannot be hidden on its own -- the
                     acquisition's eye does that -- so its dot is a glyph and
                     only the triangle answers, with the one box for the sum. -->
                <span class="chip-dot grey-dot" id="grey-chip-btn" aria-hidden="true">1</span>
                <button class="chip-more" id="grey-chip-more" type="button" aria-label="settings for the grey channel"
                        aria-haspopup="true" title="Open its box">
                  <svg width="8" height="8" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4l2.5 2.5L7.5 4"/></svg>
                </button>
              </span>
              </span>
              <div class="canvas-card acquisition-menu" id="acquisition-menu" hidden></div>
              <!-- The chosen channel's box, the very one from Display
                   settings, lent to the row while it is open here. -->
              <div class="canvas-card channel-pop" id="channel-pop" hidden></div>
              <div class="canvas-card grey-pop" id="grey-pop" hidden></div>
            </span>
            <!-- The masks' bar: one cell per mask layer lying on the
                 acquisition the row shows, each wearing its layer's dress,
                 so the bar is a legend of what is drawn. A press on a cell
                 shows or hides its layer; the triangle beside it opens the
                 layer's card. The bar stands only while there is a mask
                 layer on the picture the row is on, and never offers masks
                 on a picture they do not lie on. -->
            <span class="canvas-masks" id="canvas-masks" hidden>
              <span class="bar-word">masks</span>
              <svg width="0" height="0" aria-hidden="true" style="position:absolute">
                <defs>
                  <linearGradient id="mask-rainbow" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0" stop-color="#4f7bff"/><stop offset="0.25" stop-color="#c04bff"/>
                      <stop offset="0.5" stop-color="#ff4d6d"/><stop offset="0.7" stop-color="#ffb02e"/>
                      <stop offset="0.85" stop-color="#8be04a"/><stop offset="1" stop-color="#2fd6c9"/>
                    </linearGradient>
                </defs>
              </svg>
              <span class="mask-cells" id="mask-cells"></span>
              <div class="canvas-card mask-pop" id="mask-pop" hidden>
                <!-- One mask layer's card, in the language of a channel's
                     box: an eye, its name and how it was made at the head,
                     then the colour, the look and the opacity, one quiet
                     row each. -->
                <div class="mask-pop-head">
                  <button class="mask-eye" id="mask-eye" type="button" aria-pressed="true" title="Show or hide this mask layer">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/><path class="mask-eye-slash" d="M3 13L13 3"/></svg>
                  </button>
                  <span class="mask-pop-name" id="mask-pop-name">Masks</span>
                  <span class="mask-pop-how" id="mask-pop-how"></span>
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
          <div class="live-note" id="publication-note" role="status" hidden></div>
          <div class="tip" id="stage-tip"></div>
        </div>
        <!-- Under the picture: a way through a stack (Z) and along a
             timelapse (T), one slider each across the whole width, Z above
             T. A row stands only while the picture has more than one plane,
             or more than one moment, to choose between; a flat picture of
             one moment shows neither. -->
        <div class="canvas-axes" id="canvas-axes" hidden>
          <div class="canvas-axis" id="axis-z" hidden>
            <span class="canvas-axis-name">Z</span>
            <button class="canvas-axis-play" id="plane-play" type="button" aria-pressed="false"
                    aria-label="play through the planes" title="Play through the planes; press again to pause"></button>
            <input class="zv-range" id="plane" type="range" aria-label="depth of the picture">
            <output class="canvas-axis-value" id="plane-readout"></output>
          </div>
          <div class="canvas-axis" id="axis-t" hidden>
            <span class="canvas-axis-name">T</span>
            <button class="canvas-axis-play" id="moment-play" type="button" aria-pressed="false"
                    aria-label="play through the moments" title="Play through the moments; press again to pause"></button>
            <input class="zv-range" id="moment" type="range" aria-label="moment of the picture">
            <output class="canvas-axis-value" id="moment-readout"></output>
          </div>
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
        masksBar: find("canvas-masks"),
        maskCells: find("mask-cells"),
        maskName: find("mask-pop-name"),
        maskHow: find("mask-pop-how"),
        maskEye: find("mask-eye"),
        maskOpacityValue: find("mask-opacity-value"),
        channelPop: find("channel-pop"),
        greyChip: find("grey-chip"),
        greyChipMore: find("grey-chip-more"),
        greyPop: find("grey-pop"),
        maskPop: find("mask-pop"),
        acquisitionPick: find("acquisition-pick"),
        acquisitionName: find("acquisition-name"),
        acquisitionEye: find("acquisition-eye"),
        acquisitionMenu: find("acquisition-menu"),
        chips: find("canvas-chips"),
        channelsBox: find("canvas-channels"),
        maskColours: find("mask-colours"),
        maskFill: find("mask-fill"),
        maskLine: find("mask-line"),
        maskOpacity: find("mask-opacity"),
        rampChip: find("ramp-chip"),
        legend: find("canvas-legend"),
        overviewCanvas: find("overview-canvas"),
        overviewNote: find("overview-note"),
        publicationNote: find("publication-note"),
        pictureHost: find("picture-host"),
        axes: find("canvas-axes"),
        axisZ: find("axis-z"),
        plane: find("plane"),
        planePlay: find("plane-play"),
        planeReadout: find("plane-readout"),
        axisT: find("axis-t"),
        moment: find("moment"),
        momentPlay: find("moment-play"),
        momentReadout: find("moment-readout"),
      },
    };
  },
};
