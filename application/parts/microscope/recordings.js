/**
 * What has been read off the instrument in one step.
 *
 * A recording is a state of the microscope, taken now: the objective in the
 * light path, the channels, the frame it sees. It is a readout, not a
 * procedure — nothing on the instrument moves when one is taken.
 *
 * A slot holds exactly one recording. Recording again replaces it: the
 * operator changed the instrument and read it again, and the run is taken
 * with the instrument as it now stands — a step never chooses between old
 * readings, because there is only ever the current one. Everything here
 * returns a new slot rather than editing the one it was handed, so what a
 * panel is drawing never changes underneath it.
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
 * The name an unnamed recording gets. Counted from every reading this slot has
 * taken — replaced ones included — so the operator who names nothing still
 * ends up with names that tell readings apart; a recording that happened
 * under a dull name beats one refused over a blank field.
 */
export const nextName = (slot) => `Default ${slot.seq + 1}`;

/**
 * Which reading of its kind the next recording is. The mock controller answers
 * with the nth state it knows, and re-recording reads the next one — the
 * pretend operator changed the instrument in between. A real controller reads
 * what is there and ignores this number.
 */
export const nextReadingIndex = (slot) => slot.from + slot.seq;

const capitalised = (v) => (v ? v[0].toUpperCase() + v.slice(1) : v);

/**
 * The reading, kept — in place of whatever the slot held before. Named as it
 * comes in, capitalised, because the name is an identifier the run refers to
 * afterwards; and active, because a reading is taken in order to be used and
 * the hand that took it is already here.
 */
export const withRecording = (slot, { name, reading }) => {
  const seq = slot.seq + 1;
  /* Counted rather than positional: a record replaced must not hand its id to
     the next one, or anything still naming the old preset would silently find
     itself taken with the new. A fresh id is how the rest of the run notices
     that the reading changed — a focus map measured under the old one, for
     instance, does not quietly claim to belong to the new. */
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
    /* The instrument's acquisition channels, kept structurally so the scan
       can publish one run-wide display contract without parsing detail text. */
    channels: reading.channels ?? null,
    channelCount: reading.channelCount ?? null,
    /* The reapplicable half of the reading: the instrument's changeable
       state, handed back when the step that recorded it runs. */
    changeable: reading.changeable ?? null,
  };
  return { ...slot, seq, records: [record], active: id };
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
