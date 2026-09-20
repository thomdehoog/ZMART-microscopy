# Running useq experiments through the ZMART controller

Status: proposed, not yet implemented. Written on 2026-09-20 against
`useq-schema` 0.9.2, the first release whose wheel ships the `useq.v2`
package. The facts about useq quoted below were checked by running that
version, not taken from memory.

## In one paragraph

[useq-schema](https://github.com/pymmcore-plus/useq-schema) is a small,
vendor-neutral way to *describe* a multi-dimensional experiment: which
positions to visit, which channels to image, which Z planes, how often in time.
It is the format the pymmcore-plus family of tools (Micro-Manager from Python,
napari-micromanager, the MDA dialog in pymmcore-widgets) uses to say "here is
the experiment". ZMART already has a vendor-neutral way to *do* things to a
microscope: the controller's `Session`, with its handful of verbs (`set_xyz`,
`set_state`, `acquire`, `run_procedure`). This plan connects the two with one
small piece of code, an **engine**, that reads a useq sequence event by event
and turns each event into the controller calls that already exist. The engine
sits *above* the controller. Nothing goes around the controller, no driver
learns about useq, and every driver (Nikon, ZEISS, Leica, mesoSPIM) gains the
ability to run useq experiments at once.

## Why above the controller

Three places were considered.

- **Inside each driver.** Every driver would carry its own copy of the event
  loop, with its own bugs around relative Z, time waits and file naming. The
  Nikon bridge could not host it at all: the bridge runs in the Python that
  ships inside NIS-Elements and must stay standard-library only, while useq
  needs pydantic and numpy. And a workflow that wanted useq would have to
  import a vendor package, which breaks the "users never import drivers" rule
  in [`docs/ZMART.md`](../ZMART.md).
- **In place of the controller.** useq only describes acquisitions. It has no
  words for connecting, reading stage limits, setting the frame origin,
  discovering instrument state, or running a vendor procedure. In the
  pymmcore-plus world those jobs belong to MMCore; in ZMART they belong to the
  controller. The two are complementary.
- **Above the controller, as an optional module.** One event loop, one test
  suite against the controller's mock driver, and the controller core stays
  pure standard library (its CI installs only pytest today). This is the plan.

Where a vendor can do something faster natively, for example a Z-stack in one
NIS-Elements ND acquisition instead of one round trip per plane, the engine
hands that block of events to a single `acquire` call. The speed-up lives
*behind* the controller as a driver capability, never in front of it.

## What useq v2 is, in plain words

A useq **sequence** is a list of **axes**. Each axis is one thing that varies
during the experiment:

| Axis | Key | Example |
|---|---|---|
| Stage positions | `p` | `StagePositions(values=[Position(x=100, y=-100, z=5, name="tile_01"), ...])` |
| Channels | `c` | `ChannelsPlan(values=[Channel(config="DAPI"), Channel(config="FITC", exposure=50)])` |
| Z planes | `z` | `ZRangeAround(range=4, step=1)` (five planes, from 2 µm below to 2 µm above) |
| Time | `t` | `TIntervalLoops(interval=30, loops=10)` |
| Grid around a position | `g` | `GridRowsColumns(rows=3, columns=3)` |

`axis_order` says which axis is the outer loop and which the inner. Iterating
the sequence yields **events**, one per combination, and an event is one thing
to do: "go to this x, y, z; use this channel and exposure; take an image". The
default action is "take an image"; other actions are "run the hardware
autofocus" and "run a custom action with this name and data". Every event
carries an `index`, for example `{"p": 1, "c": 0, "z": 2}`, which is how the
saved data is labelled.

What is new in v2 compared with the older `MDASequence`: each axis is its own
object, you can add your own axis types, and an axis value can itself contain a
nested sequence (so one position can carry its own Z plan, say). The old
keyword form (`MDASequence(stage_positions=..., channels=..., z_plan=...)`)
is still accepted and converted, which matters for saving, see below.

## How one event becomes controller calls

The engine keeps a small amount of state per run (the reference Z, the last
commanded position, the sequence clock) and, for every event, does the
following in this order.

| Event field | What it means | What the engine calls |
|---|---|---|
| `x_pos`, `y_pos`, `z_pos` | Target in micrometres; `None` means "do not move that axis" | `session.set_xyz(x, y, z)`, filling any `None` axis with the last commanded value so the call is always complete |
| `pos_name` | The name of the position, when the plan gave one | `position_label` of `acquire` (falls back to a label built from `index`) |
| `channel.config`, `channel.group` | Which imaging configuration to use | `session.set_state({"changeable": {key: config}})`, only when the channel changed since the previous event. `key` is `channel.group` when the plan set one, otherwise the driver's declared channel key (see "What drivers declare") |
| `exposure` | Camera exposure in milliseconds | `options["exposure_ms"]` on `acquire` when the driver lists that option, otherwise `set_state` |
| `action` = `AcquireImage` | Take an image | `session.acquire(acquisition_type, position_label, options)` |
| `action` = `HardwareAutofocus` | Lock focus with the instrument's own focus device | `session.run_procedure({"name": <driver's hardware-focus procedure>})`; on Nikon that is `pfs_on` when a PFS is present, else `autofocus` |
| `action` = `CustomAction(name, data)` | Anything else | `session.run_procedure({"name": name, **data})`. This is a one-to-one fit with ZMART procedures, so `CustomAction(name="live")` simply runs the `live` procedure |
| `min_start_time`, `reset_event_timer` | When the event may start, in seconds on the sequence clock | The engine waits (sleeps) until that time; the clock restarts on an event flagged `reset_event_timer` |
| `index` | Where the event sits on every axis | Copied into the acquisition record and into the file label, e.g. `t000_p001_c00_z002` |
| `sequence.metadata` | Free-form notes on the whole experiment | Copied into every record; `acquisition_type` and `output_root` may be given here |
| `keep_shutter_open`, `slm_image`, `roi`, `properties` | Micro-Manager specific | Not supported. The engine refuses the sequence before touching the microscope, naming the field |

Relative Z plans are the one place where care is needed. useq's event builder
adds a relative Z plan to the position's own Z when the position has one, and
the engine passes the result straight to `set_xyz`. When a position has *no* Z
of its own, the events carry the bare offsets (for `ZRangeAround(range=2,
step=1)` they are −1, 0, +1). The engine adds those to a **reference Z**, which
it reads once with `get_xyz` at the start of the run, exactly as pymmcore-plus
does. This was confirmed by running useq 0.9.2 (see "Facts checked").

All positions are in the **ZMART frame**: micrometres from the origin the
operator set with `set_origin`, the same numbers `set_xyz` takes. useq itself
has no notion of a frame, so a sequence written for one microscope runs on
another once each has had its origin set on the sample.

## Rules the engine follows

These are the rules that make it safe to hand a whole experiment to a script.
They are written here so the code and its tests can cite them.

1. **Check everything before the stage moves.** At the start of a run the
   engine walks the entire sequence once without calling the microscope. It
   refuses, with a message that names the problem, when the sequence is
   infinite, uses an unsupported field, names a channel the driver does not
   list, or names a procedure `get_procedures` does not offer. A refused
   sequence has cost nothing.
2. **Stage limits stay the driver's job.** Every ZMART driver already refuses a
   move outside the limits NIS-Elements (or ZEN, or LAS X) reports, before the
   move is sent. The engine does not duplicate that check today, because
   drivers report limits in raw stage coordinates while the sequence is in
   frame coordinates. A later step can add a whole-sequence pre-check once
   drivers report limits in the frame as well (open decision 4).
3. **One record per event, nothing hidden.** Every `acquire` returns the
   driver's record unchanged; the engine only adds a `useq` entry to it
   carrying the event's `index` and the event itself. `run_sequence` returns
   the list of records in order, exactly like the capture loop in the
   target-acquisition workflow does today.
4. **The experiment is saved next to the data.** The engine writes the
   sequence as JSON into the output folder before the first event, so a run
   can be repeated or shared later. It writes the older keyword shape
   (`stage_positions`, `channels`, `z_plan`, ...) because that is the shape
   that reads back reliably (see "Facts checked").
5. **Cancelling is clean.** Like the existing capture loop, the engine asks an
   optional `cancel()` callback before every event and stops between events,
   never mid-move or mid-save. `on_record(index, event, record)` fires after
   every acquisition so a notebook can show images as they arrive.
6. **Channel changes are applied once, not per event.** Setting an optical
   configuration on NIS-Elements takes time; the engine only calls
   `set_state` when the channel actually changed since the previous event.
7. **Fold Z-stacks when the driver can take them whole.** In the event
   iterator, a run of consecutive events that differ only in their `z` index
   and lie on an even step is replaced by one acquisition call with
   `z_start`, `z_end` and `z_step`, when the driver's
   `get_acquisition_options` lists those options. Otherwise every plane is
   its own move and snapshot. The records still carry one `useq` index per
   plane so the data stays addressable either way.

## What drivers declare

Drivers stay unaware of useq, but the engine needs three small hints that
only the driver knows. They go into `get_info()`, which is documented as the
place for driver-defined extras, under one key:

```python
"useq": {
    "channel_key": "optical_configuration",  # the changeable state key a useq Channel maps to
    "hardware_focus": "pfs_on",              # the procedure a HardwareAutofocus action runs
    "native_stack": True,                    # acquire() accepts z_start / z_end / z_step
}
```

Without the block the engine still works, with `channel_key` taken from
`channel.group`, hardware autofocus mapped to the `autofocus` procedure, and
stacks taken plane by plane. Per driver, today's answers are:

| Driver | `channel_key` | `hardware_focus` | `native_stack` |
|---|---|---|---|
| Nikon `nis_elements_6_10` | `optical_configuration` | `pfs_on` when PFS is present, else `autofocus` | yes (ND Z-series) |
| ZEISS `zenapi` | `experiment` | `autofocus` (to be confirmed against the driver's procedures) | to be confirmed |
| Leica `navigator_expert` | the job name | `autofocus` | no (planes are separate jobs today) |
| mesoSPIM | laser / filter pair (needs a decision, see open decision 2) | none | the driver's own stack acquisition |

## The Nikon specifics

The Nikon driver is the first target because everything the engine needs is
already there and simulator-validated: `optical_configuration` as a changeable
state, `exposure_ms` both as state and as an acquire option, `pfs_on` /
`pfs_off` / `autofocus` / `live` / `freeze` as procedures, and a native Z-stack
through `acquire(acquisition_type="z_stack", options={z_start, z_end, z_step})`.

Two honest limits carry over from the driver. The exposure cannot be read back
from NIS-Elements, so a useq channel without an exposure keeps whatever the
optical configuration brought along, and the record reports the last value the
bridge set. And on the Ti2 simulator the image-based autofocus always answers
"focus failed" (its flat image gives the focus criterion nothing to work with),
so the simulator test for `HardwareAutofocus` uses the PFS path.

The bridge inside NIS-Elements is not touched by this plan and must not be:
it stays standard-library only.

## Where the code lives

```
zmart_controller/
  useq/
    __init__.py      run_sequence, ZmartEngine, save_sequence, load_sequence, positions_to_useq
    _engine.py       the event loop (setup_sequence, event_iterator, setup_event, exec_event, teardown)
    _convert.py      ZMART position dicts <-> useq Position / StagePositions; focus maps -> Z per position
    _validate.py     the before-the-stage-moves checks (rule 1)
    _persist.py      save / load in the keyword JSON shape (rule 4)
  tests/
    test_useq_engine.py     against the existing mock driver in zmart_controller/tests/mock_driver.py
    test_useq_convert.py
zmart_drivers/nikon/nis_elements_6_10/
  nis_zmart_adapter.py      get_info() gains the "useq" block
  tests/unit/test_useq_engine_nikon.py   engine over the real bridge server + fake NIS API (offline)
  tests/hardware/test_useq_simulator.py  one short sequence on the Ti2 simulator (pytest -m hardware)
zmart_controller/example_useq_experiment.ipynb   the operator-facing example
```

The engine's method names deliberately mirror pymmcore-plus's `PMDAEngine`
protocol (`setup_sequence`, `event_iterator`, `setup_event`, `exec_event`,
`teardown_event`, `teardown_sequence`) so that anyone who knows that world
recognises it, and so a thin adapter can later run the ZMART engine inside
their runner. ZMART does not depend on pymmcore-plus for any of this.

`useq-schema` becomes an *optional* dependency: listed in `requirements.txt`
under its own heading and in `environment.yml`, imported lazily inside
`zmart_controller.useq`, with a plain message ("install useq-schema to run
useq experiments") when it is missing. The controller's own CI job stays
stdlib-only; the useq tests run in a second job that installs the extra.

The public entry point is small on purpose:

```python
from zmart_controller.useq import run_sequence

records = run_sequence(
    session,                      # from zmart_controller.set_instrument(...)
    sequence,                     # a useq.v2.MDASequence (or the older MDASequence, or its JSON)
    acquisition_type="targetscan",
    output_root=r"D:\runs\today",
    on_record=show_image,         # optional
    cancel=stop_button.pressed,   # optional
)
```

## Phases

Each phase is shippable on its own and ends with tests that run offline.

**Phase 0, done while writing this plan.** A throwaway script iterated a
two-position, two-channel, three-plane v2 sequence and a plan with an
autofocus transform, and tried the JSON round trip. Its findings are in the
next section and shaped rules 1, 4 and the reference-Z handling.

**Phase 1, the engine on the mock driver (about two days).** `_engine.py`,
`_convert.py`, `_validate.py`, `_persist.py` and their tests against the
controller's mock driver. Covers: positions, channels, exposure, relative and
absolute Z, time waits with a fake clock, custom actions to procedures,
hardware autofocus, cancel and `on_record`, the refusal list of rule 1, and
the saved JSON reading back into the same events. A second CI job in
`controller.yml` installs `useq-schema` and runs these.

**Phase 2, Nikon (about one day, plus a simulator session).** The `useq`
block in the Nikon `get_info`, Z-stack folding (rule 7) exercised over the
fake NIS API, `HardwareAutofocus` to `pfs_on`, and one hardware-marked test
that runs a short sequence on the Ti2 simulator and checks the files and
records. FINDINGS.md gets a dated entry.

**Phase 3, the other drivers (half a day each).** Each adds its `useq` block
and a unit test that the engine drives it over the driver's existing fake.
Nothing else in those drivers changes.

**Phase 4, the workflows (about two days).** `run_capture` in
`workflows/target_acquisition/workflow/_capture_run.py` builds a
`StagePositions` axis from its position list and runs it through the engine,
so every capture run also leaves a `sequence.json` behind. The focus map
becomes a Z per position through `_convert.py`. The example notebook shows a
biologist the whole path: discover targets, turn them into a sequence, look at
the sequence, run it.

**Phase 5, optional.** A thin adapter that presents the ZMART engine as a
pymmcore-plus `PMDAEngine`, so the MDA dialog from pymmcore-widgets can drive a
ZMART microscope. Only worth doing if someone wants that dialog; it adds
pymmcore-plus as a dependency for that use alone.

## Facts checked against useq 0.9.2

These were observed by running the package, and the plan depends on them.

- Iterating `MDASequence(axes=(StagePositions, ChannelsPlan, ZRangeAround),
  axis_order=("p", "c", "z"))` yields events whose `x_pos`, `y_pos`, `z_pos`,
  `pos_name`, `channel.config`, `channel.group`, `exposure`, `index` and
  `action.type` are exactly the fields in the mapping table above.
- A relative Z plan is added to a position's own Z when it has one
  (position z = 5 gave planes 4, 5, 6) and yields bare offsets when it does
  not (−1, 0, +1). Hence the reference-Z rule.
- `AxesBasedAF(axes=("p",))` inserts one `hardware_autofocus` event before the
  first image at every new position. Hence the `hardware_focus` hint.
- `CustomAction(name="pfs_on", data={"timeout_s": 8})` serialises to
  `{"type": "custom", "name": "pfs_on", "data": {...}}`. Hence the one-to-one
  mapping onto `run_procedure`.
- **The v2 `axes=` form does not survive a JSON round trip.** `model_dump_json`
  writes only `{"axis_key": "p"}` for each axis, and reading that back fails
  with "Can't instantiate abstract class AxisIterable". The older keyword
  shape (`useq.MDASequence(stage_positions=..., channels=..., z_plan=...)`)
  dumps fully and loads into `useq.v2.MDASequence` correctly. Hence rule 4:
  save in the keyword shape until upstream fixes v2 serialisation, and keep a
  test that will tell us when they do.
- The v2 keyword form also accepts the older arguments directly and sorts the
  axes into the conventional order when no `axis_order` is given.
- `useq-schema` pulls in `pydantic` 2 and `numpy`. Both are already in the
  ZMART environment through `ome-types` and the compute core, so nothing new
  is installed on the analysis side. Nothing may be installed inside
  NIS-Elements.

## Open decisions

1. **Where the driver hints live.** This plan puts them in `get_info()["useq"]`
   because `get_info` is documented as the home for driver-defined extras.
   The alternative is a `channel` entry in `get_acquisition_options`, which
   would overload a dict that today lists only per-acquisition settings.
   Recommendation: `get_info`.
2. **The mesoSPIM channel key.** mesoSPIM's changeable state is a set of
   separate keys (laser, filter, intensity). A useq `Channel` is one name. The
   simplest answer is a named preset the driver resolves into those keys;
   that needs a maintainer decision on where presets are stored.
3. **`Session.run_sequence` as a convenience.** Not in this plan; the function
   form keeps the controller stdlib-only. Revisit once the engine has been
   used in a real run.
4. **Limits in the frame.** Rule 2 leaves the per-move refusal to drivers. A
   whole-sequence pre-check would need `get_info` to report the limits in
   frame coordinates, which every driver can compute since it owns the origin.
   Worth a small follow-up in each adapter.
5. **Time axis on a slow bridge.** Long `min_start_time` waits happen in the
   engine, not in the bridge, so the Nikon client's 30 s read timeout is not
   an issue. Confirm no driver has a session that times out while idle.

## Risks

- **useq v2 is still labelled "New MDASequence API".** Its own code carries
  deprecation shims and the serialisation gap above. Pin `useq-schema>=0.9.2`
  and keep the round-trip test so an upstream change is noticed, not
  discovered at the microscope.
- **Two coordinate conventions meeting.** useq positions are "microns",
  ZMART positions are "micrometres from the origin". The plan makes the frame
  explicit everywhere the sequence is built, and the example notebook sets the
  origin before building one.
- **Channel semantics differ per vendor.** An optical configuration on Nikon
  can also change the exposure and the objective; a Leica job changes the
  whole scan. The engine applies the channel first and the event's own
  exposure second, so an explicit exposure always wins, and the record shows
  what the driver reports afterwards.
