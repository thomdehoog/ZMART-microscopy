# useq-schema as ZMART's experiment format: considered and deferred

Status: **deferred** (2026-09-20). ZMART will not adopt useq-schema as its
plan format for now. This note keeps the reasoning and the facts that were
checked, so the question does not have to be worked through again from
scratch. Written against `useq-schema` 0.9.2, the first release whose wheel
ships the `useq.v2` package. Everything quoted about useq below was checked by
running that version.

## The question

[useq-schema](https://github.com/pymmcore-plus/useq-schema) is the format the
pymmcore-plus family of tools (Micro-Manager from Python, napari-micromanager,
the MDA dialog in pymmcore-widgets) uses to describe a multi-dimensional
experiment: which positions to visit, which channels, which Z planes, how
often in time. The question was whether ZMART should speak it, so that every
ZMART driver, starting with the Nikon one, could run such experiments and so
that ZMART experiments could be shared with that community.

## What useq is, in plain words

A useq **sequence** is a list of **axes**: stage positions, channels, Z
planes, time points, a grid around each position. Iterating the sequence
yields **events**, one per combination, and an event is one thing to do: "go
to this x, y, z; use this channel and exposure; take an image". Other actions
exist ("run the hardware autofocus", "run a custom action with this name and
data"). Every event carries an `index` such as `{"p": 1, "c": 0, "z": 2}`.

useq only *describes* a plan. It never talks to hardware and never runs
anything. In its own ecosystem a separate runner walks the events and calls
Micro-Manager. It is a schema, not a workflow orchestrator, and it cannot
express the smart part of smart microscopy: reading the microscope, deciding
something from an image, and choosing the next acquisition from that. A
sequence is fixed once written.

## The design that was worked out

If ZMART adopted useq, the right place was clear and is worth recording: an
**engine above the controller**, an optional module that takes a `Session`
and translates each event into the calls that already exist (`set_xyz`,
`set_state`, `acquire`, `run_procedure`). Not inside the drivers (each would
need its own copy of the loop, and the Nikon bridge inside NIS-Elements must
stay standard-library only, while useq needs pydantic and numpy). Not in
place of the controller (useq has no words for connecting, limits, the frame
origin, discovering state, or vendor procedures). Nothing in the workflows
would have had to change: the engine has the same shape as the capture loop
in `workflows/target_acquisition/workflow/_capture_run.py` (a list of records
back, `on_record` and `cancel` callbacks), so swapping it in would have been a
change inside one function.

The vocabulary question was the interesting one, and the answer holds for any
future plan format, useq or not:

- **A vocabulary for everything is not achievable.** Microscopes differ too
  much: a point scanner has no exposure (it has dwell time, scan speed and
  averaging); a light sheet sweeps the sample instead of stepping a focus
  drive; "autofocus" is a hardware lock on one instrument, an image-based
  sweep on another, and a measured focus map on a third. Micro-Manager never
  standardised device properties either; it standardised only their *shape*
  (device, property, value).
- **The truly common core is only what the controller already commits to:**
  a position in the frame with an actuator choice per axis; an acquisition
  with driver-defined options; a named procedure with driver-defined
  arguments; state as an opaque, driver-owned dict; and order and timing.
- **useq has the same two-tier shape.** A small camera-flavoured core
  (`x_pos`/`y_pos`/`z_pos`, `exposure`, `Channel`, `AcquireImage`,
  `HardwareAutofocus`) and opaque carriers for everything else: `properties`
  as (device, property, value) triples, a free `metadata` dict per event and
  per sequence, and `CustomAction(name, data)`. ZMART's opaque state would
  have mapped onto `properties`, procedures onto `CustomAction`, and acquire
  options onto `metadata`.
- **The rule that would have kept it honest:** the engine interprets only
  what the controller interprets; every other useq field is an *alias* a
  driver may claim (a camera driver claims `exposure` and maps it to its
  `exposure_ms` state key; the Nikon driver claims `HardwareAutofocus` as its
  `pfs_on` procedure), and an unclaimed alias is refused before the run
  starts, with a message that names the instrument's equivalent.

## Why it is deferred

Weighed honestly, useq buys ZMART little today:

- Everything ZMART would use, an ordered list of "go here, set this, run
  that", Z and time series, grids, a saved JSON of the plan, is a small
  amount of plain Python on top of the controller. A ZMART-native plan format
  would be a short data structure and a loop written directly in ZMART's own
  verbs, with no camera-shaped fields to explain away, no aliases to declare
  per driver, and no serialisation workaround.
- It gives no help with the smart part, and no standard vocabulary for state,
  which is the thing that is actually hard across instruments.
- For point scanners and light sheets the interoperable part of a sequence
  is thin: positions and order. The rest is opaque state either way.
- useq's standard vocabulary is camera-shaped (one frame per event, exposure
  first class, Z as a stage axis, channels as Micro-Manager config groups,
  grids assuming a fixed field of view). That heritage would have to be
  explained to every biologist who meets a refused `exposure` on a scanner.

The one thing ZMART cannot build itself is other people's files and tools
understanding ZMART's. That is the whole remaining case for useq, and it is a
community decision, not an engineering one. The right time to make it is when
a concrete outside user or tool needs it, and the right form then is a thin
translator from a useq sequence into ZMART's own plan format, not a
foundation. Because a native format would speak the controller's contract,
that translator stays cheap to add later. Nothing needs to be decided now to
keep the door open.

## If it is picked up again

The shape to build is a useq layer between the workflows and the controller,
with the alias rule described above. Commands flow down; results flow back
up:

```
workflow / smart interface      decides, writes each planned batch as a useq sequence
        │  useq sequence
        ▼
useq layer                      plays the sequence as controller calls
        │  set_xyz / set_state / acquire / run_procedure
        ▼
controller Session
        │
        ▼
vendor driver                   Nikon, ZEISS, Leica, mesoSPIM: untouched
```

The workflows speak useq downward, the useq layer speaks the controller's
verbs, and no driver knows useq exists. The reads a smart loop needs
(`get_xyz`, `get_state`, `get_info`) come straight from the controller,
because useq has no place for them.

These facts were all observed by running useq 0.9.2:

- Iterating `MDASequence(axes=(StagePositions, ChannelsPlan, ZRangeAround),
  axis_order=("p", "c", "z"))` yields events with `x_pos`, `y_pos`, `z_pos`,
  `pos_name`, `channel.config`, `channel.group`, `exposure`, `index` and
  `action.type`.
- A relative Z plan is added to a position's own Z when the position has one
  (position z = 5 gave planes 4, 5, 6) and yields **bare offsets** when it
  does not (−1, 0, +1). An engine must add those to a reference Z read once
  at the start of the run, as pymmcore-plus does.
- `AxesBasedAF(axes=("p",))` inserts one `hardware_autofocus` event before
  the first image at every new position.
- `CustomAction(name="pfs_on", data={"timeout_s": 8})` serialises to
  `{"type": "custom", "name": "pfs_on", "data": {...}}`, a one-to-one fit for
  `run_procedure`.
- **The v2 `axes=` form does not survive a JSON round trip.** `model_dump_json`
  writes only `{"axis_key": "p"}` per axis, and loading fails with "Can't
  instantiate abstract class AxisIterable". The older keyword shape
  (`MDASequence(stage_positions=..., channels=..., z_plan=...)`) dumps fully
  and loads into `useq.v2.MDASequence` correctly. Custom axes would need a
  loader of our own, or an upstream fix.
- The v2 class accepts the older keyword arguments directly and sorts the
  axes into the conventional order when no `axis_order` is given.
- `useq-schema` pulls in pydantic 2 and numpy, both already in the ZMART
  environment through `ome-types` and the compute core. Nothing may be
  installed inside NIS-Elements.
- There is no useq-schema 2.x release, pre-releases included; "useq v2" is
  the `useq.v2` subpackage inside 0.9.2.

Things worth raising upstream if ZMART engages with the project: an actuator
choice per position axis, a non-camera equivalent of exposure, actions whose
result is a dataset rather than one frame, and working serialisation of
subclassed axes. useq v2 is being shaped now, and a non-Micro-Manager adopter
with scanner and light-sheet needs would be a useful voice.
