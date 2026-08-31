/**
 * The window's status bar: one sentence about what is running, or nothing.
 *
 * Born from an afternoon of "is anything running?": a worker took its
 * sixty-second spawn in silence and the screen looked exactly like idle.
 * Everything long-running says what it is doing here -- the focus run, the
 * scan, a segmentation test -- and says nothing the moment it is done.
 */

const bar = () => document.getElementById("status-bar");

export const status = {
  say(text) {
    const held = bar();
    if (!held) return;
    held.textContent = text ?? "";
    held.hidden = !text;
  },
  quiet() {
    this.say(null);
  },
};
