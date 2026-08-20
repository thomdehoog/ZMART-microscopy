/**
 * What has been read off the instrument in one step, and which of it that step
 * works with.
 *
 * A recording is a state of the microscope, taken now: the objective in the
 * light path, the channels, the frame it sees. A step that needs one keeps a
 * slot of them rather than a single record, because the optics get changed in
 * the middle of a session and both settings stay worth having — the overview
 * taken dry at 5x and the detail taken at 63x in oil are one run, and a slot
 * that replaced its record on every reading made the second one cost the
 * first.
 *
 * So readings accumulate and one of them is active. The active one is what the
 * step is taken with; switching between them is the point of keeping more than
 * one. Everything here returns a new slot rather than editing the one it was
 * handed, so what a panel is drawing never changes underneath it.
 */

/**
 * A step's slot, before anything has been read into it.
 *
 * `from` is which state of the instrument the first reading comes back as. It
 * exists for the mock controller, which answers with a list it knows rather
 * than with an instrument: two steps that both read an acquisition want to
 * come back with different ones, or a plan that never switched objectives
 * would look like one that did. A real controller reads what is there and
 * ignores it.
 */
export const emptySlot = (type, from = 0) => ({
  type, from, records: [], active: null, seq: 0,
});

/** Whether anything has been read into it yet. */
export const hasRecording = (slot) => !!slot?.records?.length;

/**
 * The name an unnamed recording gets. Counted from what the slot already
 * holds, so the operator who names nothing still ends up with records they can
 * tell apart — a recording that happened under a dull name beats one refused
 * over a blank field.
 */
export const nextName = (slot) => `Default ${slot.records.length + 1}`;

/**
 * Which reading of its kind the next recording is. The mock controller answers
 * with the nth state it knows; a real one reads the instrument and ignores it.
 * It lives here because it counts the same recordings this module holds.
 */
export const nextReadingIndex = (slot) => slot.from + slot.records.length;

const capitalised = (v) => (v ? v[0].toUpperCase() + v.slice(1) : v);

/**
 * The reading, kept. Named as it comes in — capitalised, because the name is
 * an identifier the run refers to afterwards — and active, because a reading
 * is taken in order to be used and the hand that took it is already here.
 */
export const withRecording = (slot, { name, reading }) => {
  const seq = slot.seq + 1;
  /* Counted rather than positional: a record forgotten must not hand its id to
     the next one, or a field still naming the old preset would silently find
     itself taken with the new. */
  const id = `${slot.type}-${seq}`;
  const record = {
    id,
    name: capitalised((name ?? "").trim()) || nextName(slot),
    summary: reading.summary,
    detail: reading.detail,
    frameUm: reading.frameUm,
    /* What kind of thing was read, when the kind changes what the step can
       do with it — an autofocus is software or hardware, and only one of
       them has a focus surface to measure. */
    kind: reading.kind ?? null,
  };
  return { ...slot, seq, records: [...slot.records, record], active: id };
};

/**
 * Forgotten. The choice falls to the last one left rather than to nothing,
 * since a slot that still holds recordings has no reason to be working with
 * none of them.
 */
export const withoutRecording = (slot, id) => {
  const records = slot.records.filter((r) => r.id !== id);
  const active = slot.active === id
    ? (records[records.length - 1]?.id ?? null)
    : slot.active;
  return { ...slot, records, active };
};

/**
 * Activated: what this step is taken with from now on — if it is in fact in
 * the slot. Activating is the whole of applying it. The step has one active
 * recording and everything it produces is taken with that one, so there is no
 * second gesture that says where it applies.
 */
export const withActive = (slot, id) =>
  (slot.records.some((r) => r.id === id) ? { ...slot, active: id } : slot);

/** The one this step is taken with. */
export const activeRecording = (slot) =>
  slot.records.find((r) => r.id === slot.active) ?? null;
