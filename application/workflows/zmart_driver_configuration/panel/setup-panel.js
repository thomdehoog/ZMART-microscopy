/**
 * The panel this workflow works on: one column of controls, and no picture.
 *
 * Target acquisition happens on a stage, so it is looked at on a canvas. This
 * workflow does not. Setting a microscope up is reading numbers off the
 * instrument and writing them down where the driver will find them again, and
 * every one of those readings is a control or a figure rather than something
 * to look at. So this workflow declares a panel of its own instead of the
 * canvas, and the window belongs to it entirely.
 *
 * What the shell does with a panel is small and fixed, and this file supplies
 * exactly those parts:
 *
 * - `channel` is the column a step fills with its own controls.
 * - `divider` is the channel's draggable edge. The shell reaches for it
 *   without checking, so it has to exist even here, where there is nothing on
 *   the other side of it to resize.
 * - `foot` is the strip along the bottom where the shell puts the button that
 *   carries a step out, for any step that does not build a button of its own.
 *
 * There is deliberately no `display`: those are the picture's own settings —
 * its channels, its windows — and there is no picture here to settle.
 */

export const setupPanel = {
  key: "setup",
  label: "Setup",

  /* Once the first step has asked for this panel it stays for the rest of the
     run, the same way the canvas does in an imaging workflow. Every step of a
     configuration is filling in the same form about the same microscope, so
     taking the panel away between two of them would be closing the window
     only to open the same one again. */
  stays: true,

  build(host) {
    host.innerHTML = `
      <div class="setup-body">
        <!-- The column of controls. It is the whole panel rather than a strip
             beside a picture, which is why it carries its own class as well as
             the one the stylesheet already knows. -->
        <aside class="canvas-side setup-side" id="setup-side" hidden></aside>
        <!-- The edge. Nothing stands to the left of it in this workflow, so it
             is here to satisfy the shell rather than to be dragged. -->
        <div class="side-divider" id="setup-divider" role="separator"
             aria-orientation="vertical" aria-label="resize the controls" hidden></div>
        <!-- Where the step's button lands. The shell looks this up by id, as
             "foot-" plus the panel key, so the name is a contract rather
             than a preference. -->
        <div class="panel-foot" id="foot-setup"></div>
      </div>
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
