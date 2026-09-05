/**
 * The panel this workflow works on: a notebook, not a canvas with a margin.
 *
 * Target acquisition happens on a stage, so it is looked at on a picture with
 * a narrow column of controls down its edge. Setting a microscope up is not
 * that kind of work. It is reading numbers off an instrument and writing them
 * down where the driver will find them again, and it is what the three set-up
 * notebooks do today: a paragraph saying what you are about to do, a control
 * to do it with, and underneath, what came back.
 *
 * So this workflow's panel is laid out the way those notebooks are. One column
 * down the middle of the window, read top to bottom, made of cells. A step
 * fills it with its own cells; the shell does not know or care how many.
 *
 * Two things follow from that, and both are deliberate.
 *
 * The column is held to a comfortable reading measure rather than stretched to
 * the window. A form whose labels are at one edge of a wide screen and whose
 * fields are at the other is a form people mis-read, and there is no picture
 * here competing for the room.
 *
 * And the styles are here rather than in the framework's stylesheet. The
 * framework is an engine that knows no workflow; a notebook layout is this
 * workflow's business, so it travels with it. What the shell knows about any
 * panel is only the three parts it reaches for, which this supplies:
 *
 * - `channel` is where a step puts its cells. Here it is the whole column
 *   rather than a strip at the side.
 * - `divider` is the channel's draggable edge. The shell reaches for it
 *   without checking, so it exists even here, where there is nothing beside
 *   the column to resize.
 * - `foot` is where the shell puts the button that carries a step out, for a
 *   step that does not build its own.
 */

export const setupPanel = {
  key: "setup",
  label: "Setup",

  /* Once the first step has asked for this panel it stays for the rest of the
     run. Every step of a configuration is filling in the same form about the
     same microscope, so taking the panel away between two of them would be
     closing the window only to open the same one again. */
  stays: true,

  /* The channel is the whole window, not a column beside a picture: the
     shell puts no heading over a side column that is not there, and offers
     no display settings for a picture that is not there either. */
  wholeWindow: true,

  build(host) {
    host.innerHTML = `
      <style>
        /* The column is the channel beside the canvas, given the whole
           window: the same grey ground, the same white boxes on it, the
           same padding round them -- read down from the top left rather
           than centred, because it is a form and forms start at the left. */
        /* The panel is a grid; the column takes its stretching row, the way
           the canvas does, so the ground reaches the bottom of the window. */
        #panel-setup.on { grid-template-rows: minmax(0, 1fr) auto; }
        .setup-notebook {
          min-height: 0;
          overflow-y: auto;
          background: var(--surface-2);
          padding: 12px 14px 40px;
          box-sizing: border-box;
        }
        /* Held to a reading measure: a label at one edge of a wide screen
           and its field at the other is a form people mis-read. */
        .setup-column, .setup-foot { max-width: 46rem; }
        .setup-column { display: flex; flex-direction: column; gap: var(--box-gap, 14px); }
        .setup-cell { margin: 0; }
        .setup-cell .side-note { padding: 0; margin: 0; }
        /* A row of the form: what it is on the left, the fields on the right. */
        .setup-row { display: flex; align-items: center; gap: 8px; }
        .setup-row > label { flex: 1 1 auto; font-size: 13px; }
        .setup-row input { flex: 0 0 auto; }
        /* What came back from the instrument, as pairs. */
        .setup-readout { display: grid; grid-template-columns: auto 1fr;
                         gap: 3px 12px; margin: 0; font-size: 13px; }
        .setup-readout dt { color: var(--ink-3); }
        .setup-readout dd { margin: 0; font-variant-numeric: tabular-nums; }
        .setup-note.ok { color: #1f7a3a; }
        .setup-note.bad { color: #b3261e; }
        .setup-note { font-size: 12px; line-height: 1.4; margin: 0; }
        .setup-publish { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
        /* The measurement's own picture, as wide as the card. */
        .setup-picture { display: block; width: 100%; margin: 4px 0 0;
                         border: 1px solid var(--line); border-radius: 6px; background: #fff; }
        .setup-foot { padding: 4px 0 0; }
        /* The two ways a setup may begin, one per line, the choice first. */
        .setup-choices { display: flex; flex-direction: column; gap: 6px; }
        .setup-choice { display: flex; align-items: baseline; gap: 8px; font-size: 13px; cursor: pointer; }
        .setup-choice-said { color: var(--ink-3); }
        /* A field looks the way the session card's fields look: the page
           says what a field is once, and these are fields. */
        .setup-field, .setup-row select, .setup-kind {
          font: inherit; font-size: 13px; color: var(--ink);
          background: var(--surface-2); border: 1px solid var(--line-strong);
          border-radius: 7px; height: var(--control, 30px); padding: 0 9px;
          width: 240px; box-sizing: border-box;
        }
        .setup-field:focus, .setup-row select:focus, .setup-kind:focus { outline: none; }
        .setup-field:disabled, .setup-row select:disabled, .setup-kind:disabled { opacity: .45; }
        .setup-number { width: 120px; }
        .setup-kind { width: 132px; }
        /* A limit's row: its tick first, then its name, then its fields. */
        .setup-limit > input[type="checkbox"] { flex: 0 0 auto; margin: 0 2px 0 0; }
        .setup-limit > label { flex: 1 1 auto; }
        /* The presets, one per row: the lens, its offset, its state. The
           chosen one is the row the cells below measure. */
        .setup-sets { display: flex; flex-direction: column; gap: 4px; }
        .setup-set { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: baseline;
                     font: inherit; font-size: 13px; color: var(--ink); text-align: left; cursor: pointer;
                     background: var(--surface-2); border: 1px solid var(--line); border-radius: 7px;
                     padding: 6px 10px; }
        .setup-set:hover { border-color: var(--line-strong); }
        .setup-set.chosen { border-color: var(--accent, #2f6fed); box-shadow: inset 0 0 0 1px var(--accent, #2f6fed); }
        .setup-set b { font-weight: 600; }
        .setup-set-pair { font-variant-numeric: tabular-nums; }
        .setup-set-state { color: var(--ink-3); font-size: 12px; }
        .setup-set.default .setup-set-state { color: var(--ink-3); }
        /* A part of a card: a tinted sub-box with a numbered heading, so a
           card holding the focus, the X/Y and the confirmation shows three
           things at a glance rather than one long column. */
        .setup-part { display: flex; flex-direction: column; gap: 10px;
                      background: var(--surface-2); border: 1px solid var(--line);
                      border-radius: 8px; padding: 12px 14px; }
        .setup-part-title { display: flex; align-items: center; gap: 8px;
                            font-size: 13px; font-weight: 600; color: var(--ink); }
        .setup-part-number { display: inline-flex; align-items: center; justify-content: center;
                             width: 20px; height: 20px; border-radius: 50%; font-size: 11px;
                             font-weight: 700; color: #fff; background: var(--accent); }
        .setup-part .setup-table td { border-top-color: var(--line-strong, var(--line)); }
        /* The reference row: label, dropdown and Reset in a row on the left. */
        .setup-reference { justify-content: flex-start; }
        .setup-reference > label { flex: 0 0 auto; }
        .setup-reference > button { margin-left: 4px; }
        /* The chosen set's X, Y and Z: three plain tiles, read at one glance. */
        .setup-xyz { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
        .setup-xyz-tile { display: flex; flex-direction: column; gap: 2px; align-items: flex-start;
                          background: #fff; border: 1px solid var(--line); border-radius: 8px;
                          padding: 10px 12px; }
        .setup-xyz-axis { font-size: 11px; font-weight: 700; letter-spacing: 0.07em; color: var(--ink-3); }
        .setup-xyz-value { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums;
                           color: var(--ink); line-height: 1.2; }
        .setup-xyz-unit { font-size: 12px; color: var(--ink-3); }
        .setup-xyz-tile.default .setup-xyz-value { color: var(--ink-3); }
      </style>
      <div class="setup-notebook">
        <!-- The column of cells. The shell fills this; what goes in it is the
             step's, and the step decides how many cells that is. -->
        <div class="setup-column" id="setup-side" hidden></div>
        <!-- Where the step's button lands. The shell looks this up by id, as
             "foot-" plus the panel key, so the name is a contract rather than
             a preference. -->
        <div class="setup-foot" id="foot-setup"></div>
      </div>
      <!-- The edge. Nothing stands beside the column in this workflow, so it
           is here because the shell reaches for it, not to be dragged. -->
      <div class="side-divider" id="setup-divider" role="separator"
           aria-orientation="vertical" aria-label="resize the controls" hidden></div>
      `;

    const find = (id) => host.querySelector(`#${id}`);
    return {
      channel: find("setup-side"),
      display: null,
      divider: find("setup-divider"),
      fold: null,
      foot: find("foot-setup"),
    };
  },
};
