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
        /* The page the cells stand on. It scrolls as one, the way a notebook
           does, rather than each cell scrolling inside itself. */
        .setup-notebook {
          height: 100%;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          align-items: center;
        }
        /* The reading measure. Wide enough for a row of a label and two
           numbers, narrow enough to read a paragraph across without losing
           the line. */
        .setup-notebook > * { width: min(46rem, calc(100% - 3rem)); }
        /* A cell: something to read, something to do, and what came back.
           The rule between cells is what makes them read as separate moves
           rather than one long form. */
        .setup-cell { padding: 1.25rem 0; }
        .setup-cell + .setup-cell { border-top: 1px solid var(--rule, #e3e3e0); }
        .setup-cell-title { font-weight: 600; margin-bottom: .35rem; }
        /* Prose in a cell: the sentence that says what this is for. Held a
           little narrower still, and quieter than the controls under it. */
        .setup-cell p { margin: .35rem 0 .75rem; max-width: 40rem;
                        color: var(--muted, #55554f); }
        /* A row of the form: what it is on the left, the fields on the right,
           so a column of labels reads down the page. */
        .setup-row { display: flex; align-items: center; gap: .5rem;
                     padding: .2rem 0; }
        .setup-row > label { flex: 1 1 auto; }
        .setup-row input { flex: 0 0 auto; }
        /* What came back from the instrument, as pairs. */
        .setup-readout { display: grid; grid-template-columns: auto 1fr;
                         gap: .2rem .75rem; margin: .6rem 0 0; }
        .setup-readout dt { color: var(--muted, #55554f); }
        .setup-readout dd { margin: 0; font-variant-numeric: tabular-nums; }
        /* A sentence in the quieter voice: a note, a warning, where a file
           went. Coloured only when it is good or bad news. */
        .setup-note { margin: .5rem 0 0; color: var(--muted, #55554f); font-size: .95em; }
        .setup-note.ok { color: var(--ok, #1f7a3a); }
        .setup-note.bad { color: var(--bad, #b3261e); }
        /* The press that publishes, and the sentence beside it once done. */
        .setup-publish { display: flex; align-items: center; gap: .75rem; margin-top: .75rem;
                         flex-wrap: wrap; }
        .setup-publish .setup-note { margin: 0; }
        .setup-cell-body .run { margin-top: .35rem; }
        .setup-row + .setup-row { margin-top: .25rem; }
        /* The strip at the bottom, where a step's button lands when the step
           does not build one of its own. It sits under the last cell rather
           than being pinned to the window, because in a notebook the thing
           you press is the end of what you were reading. */
        .setup-foot { padding: 1rem 0 2.5rem; }
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
