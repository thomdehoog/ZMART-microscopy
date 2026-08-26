/**
 * Recording a setting off the microscope: the bar that takes a reading, and
 * the readings taken.
 *
 * Three steps record something — the overview's acquisition preset, the
 * focussing preset, the acquisition type the targets are imaged with — and
 * all three are the same gesture: the operator sets the instrument up in its
 * own software, names what they have set up, and presses record. So the
 * gesture is written once, here, and each step says which slot it is filling
 * and what to do when it changes.
 *
 * Nothing is typed in twice: what a recording holds is read back off the
 * instrument through the backend. A value re-entered by hand is a value that
 * can disagree with the instrument.
 */

import { sideGroup } from "../../../framework/window/panels.js";
import {
  nextReadingIndex, withActive, withRecording, withoutRecording,
} from "../microscope/recordings.js";

/* Which recordings are unfolded, by id. As many at once as the operator
   wants open: comparing two readings means reading both, and folding one
   away to look at the other is asking them to hold it in their head. Here
   rather than on the record itself — it is a fact about this screen, not
   about what the instrument reported, and the rows are redrawn from the
   run's state whenever anything around them moves. */
const unfolded = new Set();

/* The name being typed for the next reading, per slot, for the same reason.
   A name half typed has to survive a field being laid beside it. */
const draftNames = {};

/* The summary is the headline; the detail is what the controller actually
   read. Folded away by default, because a recording should stay a line —
   but one click from view, because "trust me" is not a good answer when
   the run depends on it.

   `active` is whether this is the one the step is taken with and `choose`
   makes it so; `ink` is the colour it is drawn in wherever the step draws
   it. */
function renderRecordedBar(record, {
  rerender, dropped, choose, hostId, running, locked = false, active = false,
  ink = null, about = {}, unnamed = false,
}) {
  const wrap = document.createDocumentFragment();

  const row = document.createElement("div");
  /* A row with no name is one column of content, not two: the reading begins
     where the name would have, beside the dot that colours it. Left in the
     two-column layout it sat right-aligned against an empty cell, a long way
     from the mark it belongs to. */
  row.className = unnamed ? "rec-row unnamed" : "rec-row";
  // no kind cell: the group above names it, so the name starts at the left
  row.innerHTML = '<button type="button" class="rec-fold"></button>'
    + '<button type="button" class="rec-pick">'
    + '<span class="rec-name"></span><span class="rec-state"></span></button>'
    + '<button type="button" class="rec-drop">✕</button>';
  /* A reading that nobody named says what it is instead of what it is called.
     The name was only ever a handle for telling two readings apart, and where
     there is one reading at a time the handle is a word doing no work. */
  row.querySelector(".rec-name").textContent = unnamed ? "" : record.name;
  row.querySelector(".rec-state").textContent = record.summary;

  /* The row activates the recording, and activating is the whole of using
     it: everything the step produces is taken with the active one. A list of
     recordings beside a list of buttons for choosing between them was the
     same list written twice, and the copy is the one that goes stale. */
  const pick = row.querySelector(".rec-pick");
  pick.setAttribute("aria-pressed", String(active));
  pick.title = active
    ? (about.active ?? "active — this step is taken with it")
    : (about.idle ?? "activate: this step, and everything already planned, is taken with it");
  pick.disabled = !!running();
  pick.addEventListener("click", choose);
  if (ink) {
    const dot = document.createElement("span");
    dot.className = "rec-dot";
    dot.style.background = ink;
    /* Inside the name rather than beside it: the row is two columns, the
       name and what was read, and a dot given a column of its own pushed the
       summary onto a second line. */
    row.querySelector(".rec-name").prepend(dot);
  }

  const expanded = unfolded.has(record.id);
  const fold = row.querySelector(".rec-fold");
  fold.textContent = "▸";
  fold.title = expanded ? "fold away" : (about.fold ?? "show everything recorded");
  fold.setAttribute("aria-expanded", String(expanded));
  fold.classList.toggle("open", expanded);
  fold.addEventListener("click", () => {
    if (expanded) unfolded.delete(record.id); else unfolded.add(record.id);
    rerender();
  });

  /* Forgotten, whatever is taken with it: nothing names a recording except
     the step itself, so what is left to be active takes over and the plan
     follows it. */
  const drop = row.querySelector(".rec-drop");
  drop.title = about.drop ?? "forget this preset";
  drop.disabled = !!running() || locked;
  drop.addEventListener("click", dropped);

  wrap.append(row);

  if (expanded && record.detail) {
    const detail = document.createElement("dl");
    detail.className = "rec-detail";
    for (const [label, value] of record.detail) {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      detail.append(dt, dd);
    }
    wrap.append(detail);
  }
  return wrap;
}

/* The bar that takes the next reading: a name and a button. What it reads
   goes to `recorded` rather than into a record of its own — the slot below
   owns what has been recorded — and the name it is carrying goes to `onName`
   as it is typed, so a redraw finds it again. */
function renderOpenBar({
  type, nth, name, onName, recorded, running, readSetting, unnamed, says,
}) {
  const row = document.createElement("div");
  /* Nothing to fill in, so nothing to lay a field out against: the button is
     the whole bar and stands at the left where a reading would have begun. */
  row.className = unnamed ? "rec-new alone" : "rec-new";

  const box = document.createElement("input");
  box.type = "text";
  // one word: the box is narrow, and a placeholder that has to be truncated
  // to fit says less than the short one it was truncated from
  box.placeholder = "Name";
  box.value = name;
  box.setAttribute("aria-label", "name for this preset");

  const go = document.createElement("button");
  go.className = "run";
  go.type = "button";
  /* With a field beside it the button only has to say *do it*, because the
     field says what. Alone, it has to say the whole thing. */
  go.textContent = says ?? "Record";

  /* The name is not what makes a recording worth taking: what makes it worth
     taking is that the instrument is set the way it is set, now, and that is
     what the button reads. So the button is always live and an unnamed
     recording gets a name of its own — the operator can rename it, and a
     recording that happened beats one that was refused over a blank field.

     Typing must not rebuild the row, or the field loses focus every
     keystroke. */
  const check = () => {
    onName(box.value);
    go.disabled = !!running();
  };
  if (!unnamed) box.addEventListener("input", check);
  check();

  go.addEventListener("click", () => {
    go.disabled = true;
    go.textContent = "reading…";
    /* A readout off the instrument, never a procedure: the state as it is
       set now, through the backend. Nothing on the instrument moves. */
    readSetting(type, { nth })
      .then((reading) => recorded(box.value, reading));
  });

  /* The name leads, the way it leads a recorded row: it is the thing being
     filled in. The kind is said once by the heading above, not by the bar.
     A slot that takes no name has only the button, and a recording made
     without one is given a name of its own. */
  if (unnamed) row.append(go);
  else row.append(box, go);
  return row;
}

/* A slot: a bold heading, the bar that takes the next reading, and a row for
   each reading taken. Each of the three lives in the step that uses it, so
   the state is tested where it matters.

   `ink` colours a record wherever the step draws it. `changed` is what the
   run does when the slot's contents change; `activated` when the contents
   stand and another record becomes the one in use — a lighter answer,
   because nothing has to be built again to say so. */
export function renderRecordingSlot(host, opts) {
  const {
    label, slot: theSlot, setSlot, running, readSetting,
    changed, activated = changed, locked = false, ink = null,
    /* A slot whose readings need no name of the operator's: the button is the
       whole bar, and says the act rather than the word "Record". `takes` is
       what it says with nothing recorded yet, `retakes` once there is. */
    unnamed = false, takes = null, retakes = takes,
  } = opts;
  if (!host) return;
  /* The id is the key a half-typed name is remembered under, so a host
     that wants its typing to survive a redraw has to carry one. */
  const hostId = host.id;
  host.textContent = "";
  // two boxes in here, standing apart the way the boxes around them do
  host.className = "setting-slot";

  /* One box: the act and what the act has made. It is headed by the doing
     and names what it will make — recording is the same gesture everywhere,
     but what comes out of it is an acquisition preset here and a focussing
     preset there, and the operator is after the thing rather than the gesture.
     What has been recorded stands directly under the bar that took it; a box
     of its own said the readings were a second subject when they are the
     answer to this one. */
  /* The heading says the subject; the bar under it says the act. Where the bar
     is only a button, that button carries the act in full — so the heading
     drops the verb rather than saying it twice. */
  const { group, body } = sideGroup(
    unnamed ? label : `Record ${label[0].toLowerCase()}${label.slice(1)}`,
  );

  const slot = theSlot();
  const rerender = () => renderRecordingSlot(host, opts);

  /* The bar that takes a reading leads, and what it has taken stands under
     it. Both, always: the bar used to be replaced by what it recorded, which
     said the reading was a thing done once — and it is not. The optics get
     changed in the middle of a session, and when they do the operator wants
     to say so here rather than throwing the preset away to get the bar back.

     It leads rather than follows because it is the control and the rows
     below are the answers. A control that moves down the panel as answers
     accumulate is a control the hand has to go looking for. */
  const box = document.createElement("div");
  box.className = "setting-box open";
  box.append(renderOpenBar({
    type: slot.type,
    nth: nextReadingIndex(slot),
    name: draftNames[hostId] ?? "",
    onName: (v) => { draftNames[hostId] = v; },
    running,
    readSetting,
    unnamed,
    /* The first reading brings the configuration in; every one after replaces
       what is being worked with. Two words for two different acts, because an
       operator about to overwrite a reading the plan was laid under should be
       told that is what the button does. */
    says: unnamed && (takes ?? retakes)
      ? (slot.records.length ? retakes : takes)
      : undefined,
    recorded: (name, reading) => {
      setSlot(withRecording(slot, { name, reading }));
      draftNames[hostId] = "";
      rerender();
      changed();
    },
  }));
  /* Where the bar goes depends on what it is.
   *
   * A bar that takes a name leads: it is the thing being filled in, and what
   * has been taken stands under it. A bar that is only a button does not — the
   * reading is the subject of the box and should be the first thing read, with
   * the button under it as what to do about it. Put above, a button saying
   * "Update" is offering to replace something the eye has not reached yet. */
  if (!unnamed) body.append(box);

  host.append(group);
  if (!slot.records.length) { if (unnamed) body.append(box); return; }

  /* The readings, straight under the bar that took them. They carried a word
     of their own for a while — the way the two ways of laying tilesets do —
     and it was a heading saying what the heading above it had just said. As
     long a list as it needs to be: the channel scrolls if the step outgrows
     it, and a slot that scrolled inside itself hid readings behind a bar of
     its own and made the one in use something to go hunting for. */
  const list = document.createElement("div");
  list.className = "rec-list";

  for (const record of slot.records) {
    const active = record.id === slot.active;
    const done = document.createElement("div");
    done.className = active ? "setting-box done active" : "setting-box done";
    done.append(renderRecordedBar(record, {
      unnamed,
      rerender, locked, active, hostId, running,
      ink: ink ? ink(record.id) : null,
      choose: () => {
        setSlot(withActive(slot, record.id));
        rerender();
        activated();
      },
      dropped: () => {
        setSlot(withoutRecording(slot, record.id));
        unfolded.delete(record.id);
        rerender();
        changed();
      },
    }));
    list.append(done);
  }
  body.append(list);
  if (unnamed) body.append(box);
}

/* The carrier is what the canvas is drawing, so its controls sit beside the
   drawing and stay there. Not a menu that appears for one step: the frame is
   a property of the run, readable whenever the canvas is, and only editable
   until it has been applied.

   Mounted once per lock state rather than on every render, because the widget
   keeps its own and rebuilding it would throw away the number being typed. */
/* The carrier is settled by being configured, so there is nothing to press:
   it always holds a valid one, and the operator either accepts what is there
   or edits it. Standing on the step is the whole of it. Completing is not
   advancing — the rail still waits for a click to move on.

   It stays editable until something has been done inside the frame, at which
   point changing it would invalidate what was done. */
