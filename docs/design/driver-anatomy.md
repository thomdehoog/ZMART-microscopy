# The anatomy of a ZMART driver

Status: design proposal, October 2026. It describes the parts every ZMART
driver should have, what each part is responsible for, and the rules that
connect them. It was written by comparing the Leica Navigator Expert driver
(release candidate 6.0.0rc1) with the Nikon, ZEISS and mesoSPIM drivers and
with the ZMART Controller release candidate. Nothing here has been built yet
in this exact form; the last sections say what is still open and in which
order we plan to get there.

## Why a common anatomy

ZMART drives very different microscopes: a Leica confocal through LAS X, a
Nikon through NIS-Elements, a ZEISS through ZEN, and a mesoSPIM light-sheet.
An experiment written for one of them should run on the others unchanged.
That only works if every driver is built from the same parts, in the same
order, with the same safety rules. When the parts are the same, a fix in one
place can reach every microscope, a new driver has a clear template to
follow, and someone reading an unfamiliar driver already knows where to look.

The microscopes themselves will always differ. The idea of this anatomy is to
keep those differences in one place, at the bottom, so that everything above
it can look and behave the same.

## The parts at a glance

A driver has nine parts. Read the picture from bottom to top: each part only
uses the parts below it.

```
  experiments and workflows
  ───────────────────────────────────────────────────────────────
  8  ZMART controller plugin    the 11 functions every microscope offers
  5  Procedures                 recipes built from get and set actions
  4  Set actions  ──────────┐   change the microscope, then confirm it
     + set dispatcher        │   (limits gate, retry, confirm, give up softly)
  3  Get actions  ◀─────────┘   ask the microscope something
     + get dispatcher            (one read at a time, time limit, "unknown")
  2  Error handling             sort every problem into a kind, then follow the rule
  1  Vendor interface           the only part that is completely microscope-specific
  ───────────────────────────────────────────────────────────────
  vendor software (LAS X, NIS-Elements, ZEN, mesoSPIM-control)

  alongside:  6 Data handling   7 Configuration   9 Testing
```

Suggested folder layout inside a driver:

```
my_driver/
    vendor_interface/
    error_handling/
    get_actions/
    set_actions/
    procedures/
    data_handling/
    configuration/
        origin/
        image_stage_registration/
        limits/
        optical_calibration/
        machine_description/
    zmart_controller/          # the plugin: zmart.json and the 11 functions
    testing/
        mock_api/
        unit/
        hardware/
        data/
        run_ci.py
    experimental/              # ideas that are not yet trusted on hardware
```

The folder names `get_actions/` and `set_actions/` are written out in full
on purpose. A folder called plain `set/` would clash with Python's built-in
`set`, and code that uses `set()` could quietly break.

## Words we use

A few words have a precise meaning in this document. Using them consistently
avoids a lot of confusion.

- **Action**: anything the driver asks the microscope to do. An action is
  either a *get* or a *set*. (A *command* is what a workflow sends the
  controller, such as `set_xyz`; the driver carries it out with actions.)
- **Get action**: asks the microscope something, such as the stage position
  or the selected objective. It never changes anything.
- **Set action**: changes the microscope. "Set" is meant broadly here: moving
  the stage, changing a laser power, selecting a job, and acquiring an image
  are all set actions, because each one changes the state of the instrument.
- **Primitive**: one plain Python function offered by the vendor interface,
  such as `read_position()` or `move_xy(x, y)`. Get and set actions are built
  on primitives.
- **Dispatcher**: the general engine that runs an action safely. There is one
  for gets and one for sets.
- **Procedure**: a recipe that combines several get and set actions, such as
  autofocus.
- **Raw stage coordinates**: positions in micrometers exactly as the vendor
  software reports them.
- **User coordinates**: positions in micrometers measured from the recorded
  origin. This is what experiments see.

## 1. Vendor interface

**Purpose.** This is where each microscope is allowed to be completely
different. It opens the connection to the vendor software and does whatever
that software needs, so that the parts above can stay simple.

What it looks like today in each driver:

| Driver | What the vendor interface has to deal with |
|---|---|
| Nikon | A small Python program runs inside NIS-Elements and calls the C functions in `g5_regprocs.dll`. Our driver talks to it with one JSON message per line over a local network socket. |
| mesoSPIM | Python script templates are sent into mesoSPIM-control and run there. |
| ZEISS | A secure gRPC connection (a network protocol) to the ZEN API gateway, with a control token on every call. |
| Leica | Calls into the LAS X CAM API, reading the command echo after each call, and parsing the LAS X log files. |

**Responsibilities.**

- Open and close the connection to the vendor software.
- Check the vendor software version when connecting. A version the driver has
  never been tested against should be refused, or at least warned about
  loudly.
- Offer a list of *primitives*: plain functions that each do one thing.

**The three promises.** Inside, the vendor interface may look like anything.
At its top edge it keeps three promises:

1. **Plain values.** Primitives take and return plain Python values, with
   positions in micrometers. No C types, macro text, log lines or network
   tokens leak above this line.
2. **Classified errors.** Every failure it raises can be sorted by the error
   handling (part 2) into one of the shared kinds.
3. **Replaceable by the mock API.** Everything above the vendor interface must
   run the same way against the mock API (part 9) as against the real
   microscope.

The list of primitives is not the same for every microscope. Leica thinks in
*jobs*, ZEISS in *experiments*, Nikon in *optical configurations*, and
mesoSPIM has none of these. Forcing one fixed list on all of them would either
be too small to be useful or push the awkward fit up into the actions. The
list that must be the same everywhere lives higher up, in the ZMART controller
plugin (part 8).

**Where a workaround belongs.** Every microscope needs workarounds. A simple
rule decides where each one goes:

- If it is about **how to talk to this vendor** (converting to C types,
  running code inside NIS, parsing a log line, a call that only works after
  selecting a job first), it belongs in the vendor interface.
- If it is about **what a value means** (for example, Leica's focus position
  is the sum of the z-wide and z-galvo drives), it belongs in a get or set
  action.
- If it is **a recipe of several get and set actions**, it is a procedure.

## 2. Error handling

**Purpose.** To decide, in one place, what happens when something goes wrong.
Without this, every action grows its own if-else rules about error messages,
and two actions end up treating the same problem differently.

Error handling has two pieces:

- **The classifier** is written per microscope. It takes whatever the vendor
  reported (an echo text, a gRPC status code, captured error output) and
  sorts it into one of the shared kinds below.
- **The rules** are the same for every microscope. For each kind, they say
  what the get dispatcher and the set dispatcher should do next.

The dispatchers never interpret error messages themselves. They ask the
classifier what kind of problem this is, and then follow the rule.

**The shared kinds and rules.**

| Kind | Example | Get dispatcher | Set dispatcher | What the experiment sees |
|---|---|---|---|---|
| Refused by limits | A target outside the travel range | – | Stops before anything is sent | `ValueError` |
| Bad request | An unknown option; the vendor says "is invalid" | Raises | Does not retry | `ValueError` |
| Temporary | The software is busy; a short timeout | Reads again | Sends again, up to a set number of times | `RuntimeError`, only if every retry fails |
| Permanent | The vendor reports a failure; a hardware fault | Raises | Does not retry | `RuntimeError` |
| Unknown reading | A stale log entry; a read that timed out | Returns "unknown" with the reason | Counts as "not confirmed yet" | – |
| Unconfirmed | The action was accepted, but the readback never matched | – | Sends again, then gives up softly | `success: False` with `confirmed: False`, and the experiment carries on |
| Connection lost | The vendor software was closed | Raises | Raises | `RuntimeError` |
| Stopped by user | See "Stop" under open questions | – | Stops waiting | To be decided |

**Rules that always hold.**

- **An error we do not recognise counts as permanent.** Retrying something we
  do not understand could repeat a harmful action. The Leica driver already
  works this way: its classifier checks the permanent patterns first and
  treats anything unrecognised as permanent.
- **Error messages name keys, never values.** The connection settings can
  contain passwords, so a message may say "the key `password` is missing" but
  never print what a key holds.
- **How many times** to retry and **how long** to wait may be tuned per
  action. **What to do** for each kind of error is fixed by the table.

## 3. Get actions and the get dispatcher

**Purpose.** To give one honest reading of the microscope: the value, where it
came from, and how old it is, or "unknown" when the driver cannot be sure.

**The get dispatcher** is the general engine behind every reading. It:

- lets only one read reach the vendor software at a time, so reads do not pile
  up on a busy microscope;
- applies a time limit and answers "unknown" instead of hanging;
- rejects readings that are too old;
- chooses between sources when a microscope offers more than one. Leica can
  read from the API and from the log file, and races the two. Most
  microscopes have a single source, and the dispatcher must not assume two.

In the Leica driver this engine exists today as `readers/router.py`.

**Get actions** are short definitions that use the dispatcher: which
primitive to call, and what the value means.

**Rules.**

- A get action never changes the microscope.
- A get action never knows a target. It does not know what value anyone is
  hoping for.
- The get dispatcher retries **the read**, never the hardware.

## 4. Set actions and the set dispatcher

**Purpose.** To change the microscope safely, and to know afterwards whether
the change really happened.

**The set dispatcher** runs every set action through the same steps:

1. **Limits gate.** Check the request against the limits from the
   configuration. If it is outside, refuse before anything is sent.
2. **Pre-check.** Ask the get dispatcher whether the microscope is ready, for
   example whether the scanner is idle.
3. **Send** the action through a primitive.
4. **Error check.** Classify any error and follow the rule: retry a temporary
   error, stop on anything else.
5. **Confirm.** Ask the get dispatcher, again and again within a time window,
   whether the value has reached the target.
6. **Send again** if the confirmation did not succeed, up to a set number of
   attempts.
7. **Give up softly** if it is still not confirmed: report the action as
   unconfirmed and let the experiment carry on.

In the Leica driver this engine exists today as `confirm_and_fire` in
`commands/dispatch.py`.

**Set actions** are short definitions that use the dispatcher. Each one says
which primitive to call and how to confirm it: which reading to check, the
target, the tolerance, and how long to wait. Most confirmations follow that
simple pattern and can be written as a single row of data, the way Leica's
`confirm_specs.py` already does. A few, such as acquisition, an objective
change or a z-stack, need their own code, and that is fine.

**Rules.**

- **Every set action goes through the set dispatcher**, and the limits gate
  is inside the dispatcher. No set action can skip the gate, because there is
  no other way to reach the hardware. (In Leica today each wrapper calls the
  gate itself; moving it into the dispatcher removes the chance of forgetting
  it.)
- **The set dispatcher uses the get dispatcher**, for the pre-check and for the
  confirmation. A get never calls a set.
- **A single read must fit inside one confirmation window.** Otherwise the set
  dispatcher gives up before the reading arrives, or an abandoned read is
  still running when the next attempt starts. The Leica driver learned this
  the hard way (finding CF-05 in `select_job`).
- **One read at a time is managed per read, not per confirmation.** When Leica
  held that rule around a whole confirmation, the confirmation's own reads
  were blocked (finding CF-01). Only the get dispatcher manages it.
- **One writer at a time.** Set actions assume a single caller. A workflow
  that sends commands from several threads at once can mix up the results.
- **Tuning numbers** (retries, time windows, time limits) live in one named
  file next to the dispatchers. The driver author sets them; the operator
  never needs to.

## 5. Procedures

**Purpose.** To offer recipes that combine several steps, such as autofocus,
backlash takeup (always finishing a move from the same side, so that
positions repeat), or parking the z-galvo at zero while keeping the focus.

**Rules.**

- **A procedure uses only get and set actions**, never the vendor interface
  directly. Every step then passes the limits gate and the error rules
  without any extra effort.
- **Each procedure describes itself** with a name and a plain-language
  description. That is what `get_procedures` lists and `run_procedure` runs.
- A procedure that needs image analysis, such as a software autofocus, uses
  the shared algorithms (see "Shared across drivers" below).

## 6. Data handling

**Purpose.** To turn what the microscope produced into ZMART's product, and to
say exactly where it was saved. "Data" here means the image data and the
metadata that travels with it. Configuration is not data in this sense; it
has its own part.

Acquiring the image is a set action (part 4): it starts the capture and
confirms that the capture finished. Data handling starts after that.

**Responsibilities.**

1. **Find** what the vendor software produced: files in a folder, or image
   data handed over directly.
2. **Wait until it is complete.** A file must have stopped growing and the
   export must have finished, so that we never read a half-written file.
3. **Convert** it to flat OME-TIFF (one plane per file) or OME-Zarr.
4. **Name and place** it in the experiment's folder layout, using the
   acquisition type and the position label.
5. **Attach the metadata**: the position in user coordinates, the instrument
   state, and the pixel size.
6. **Keep the command log**: for each acquisition, what was asked, what
   happened, how many attempts it took, and whether it was confirmed. The
   dispatchers already produce this information; data handling saves it next
   to the images so the experiment can be traced afterwards.
7. **Report** the saved paths. They go into `acquire`'s answer to the
   controller.

Problems here go through the same error handling. A file that never appears
after a confirmed capture is a permanent error.

## 7. Configuration

**Purpose.** To hold everything the person at the microscope sets up and
saves, and to load it every time the driver connects.

| Folder | What it holds | How often it changes |
|---|---|---|
| `origin/` | The point that reads as (0, 0, 0) in user coordinates. | Often, for example for each new sample. |
| `image_stage_registration/` | How image pixels relate to stage movement: which way each axis points, flips and 90° turns, and the pixel size. | Rarely: at installation, or after hardware changes. |
| `limits/` | How far each axis may travel, and the allowed values for each setting. | Rarely. |
| `optical_calibration/` | The x, y and z offsets between objectives, so that a change of objective keeps the same spot in view. | Rarely. |
| `machine_description/` | The fixed facts about this instrument: its objectives, detectors, axes, motors and serial number. | Only when the hardware changes. |

The origin has its own folder because recording it is a frequent, everyday
step, while the registration is measured rarely. Someone recording a new
origin should never be one notebook cell away from overwriting the
registration.

**Every item follows the same pattern:**

- **Defaults** shipped with the driver in the repository.
- **Load, check and save**: the saved copy lives under the computer's ZMART
  configuration folder (`config_root()`, for example
  `C:\ProgramData\zmart-microscopy` on Windows). A malformed file is refused,
  not guessed at. Saved copies never go into the repository.
- **A notebook** that walks the operator through setting it.

**Order at connect.** Each item depends on the one before it, so `connect`
loads them in this order: machine description, image-to-stage registration
and origin, limits, optical calibration. Loading the limits is what switches
on the limits gate.

**The coordinate system.** The arithmetic between raw stage coordinates and
user coordinates (subtracting the origin, applying the registration, adding
the objective offsets) lives once, as a pair of plain functions next to this
configuration. The get and set actions for position use these functions.
That way:

- everything above the actions (procedures, the plugin, experiments) speaks
  one coordinate system, the user's;
- the limits gate checks raw stage coordinates, so recording a new origin can
  never move the safe travel range;
- the plugin does no arithmetic of its own.

Today the Leica driver does this arithmetic inside its controller adapter.
Moving it down into the actions means procedures and setup notebooks can no
longer accidentally use a different coordinate system from the experiments.

## 8. ZMART controller plugin

**Purpose.** To present the driver to the ZMART Controller in the shape every
microscope shares.

It is a folder called `zmart_controller/` with two files:

- `zmart.json`, which names the instruments this driver serves;
- `__init__.py`, which holds the 11 functions of the controller contract:
  `connect`, `get_info`, `get_actuators`, `get_xyz`, `set_xyz`, `get_state`,
  `set_state`, `get_acquisition_options`, `acquire`, `get_procedures` and
  `run_procedure` (plus an optional `disconnect`).

The full contract is described in the ZMART Controller's `docs/driver.md`.

**Rules.**

- The plugin **only maps** the driver's get actions, set actions and
  procedures onto the 11 functions. It does no coordinate arithmetic and no
  safety checks of its own; those already happened further down.
- The controller finds it with `register_driver("path/to/driver")`, and
  `validate_driver(instrument)` checks that every answer has the right shape.
- An unconfirmed set action reaches the experiment as `success: False` with
  `confirmed: False` and a reason in the report. Anything unsafe is raised.

## 9. Testing

**Purpose.** To make every other part safe to change, and to let anyone try
the driver on a laptop without a microscope.

```
testing/
    mock_api/      the stand-in for the vendor software
    unit/          tests that run against the mock API, on any computer
    hardware/      checks that run on the real microscope
    data/          sample files: vendor exports, log files, example configuration
    run_ci.py      one entry point: offline by default, --hardware at the bench
```

**The mock API** stands in for the vendor software at the bottom edge of the
vendor interface. Each driver already has one, though at different depths:

| Driver | Mock API |
|---|---|
| Leica | `mock_lasx_api.py`, an in-memory stand-in for the LAS X client that tracks jobs, stage and focus and returns realistic errors. |
| mesoSPIM | `mock_mesospim_server.py`, a real socket server that speaks the real protocol and runs the driver's own scripts. |
| ZEISS | `fake_gateway.py`, a real gRPC server built on ZEISS's own service definitions, which can also be started on its own. |
| Nikon | `fake_nis_api.py`, an in-memory stand-in. |

The folder is called `testing/` rather than `tests/` on purpose. The mock API
is used beyond the tests: the controller's mock driver runs on it, and
workflows can be tried offline on it. Python packages often leave a folder
called `tests/` out when they are installed, and then the mock API would be
missing exactly where someone wants it.

**Rules.**

- **The driver never imports from `testing/`.** Only tests and the mock driver
  use the mock API. A layer check (Leica's `test_architecture_guard.py` is the
  model) enforces this, together with the "each part only uses the parts
  below it" rule from the picture at the top.
- **Hardware runs start offline.** `run_ci.py --hardware` first proves the
  limits gate and the error rules against the mock API, and stops before
  touching the stage if either fails. The Leica driver already does this for
  the limits gate.
- **The mock API can produce every kind of error on purpose**, so that one
  shared set of tests can check that both dispatchers follow the error rules.

## Shared across drivers

Some code is the same for every microscope and should live once, in a shared
package that all drivers use, instead of being copied into each one. Copies
drift apart, and safety behaviour must not drift.

```
zmart_drivers/
    shared/
        algorithms/        image registration and focus scoring
        ...                later: the dispatchers, the error rules,
                           configuration loading, OME writers
```

**The algorithms** are the clearest case. Today they live inside the Leica
driver (`algorithms/registration.py` and `algorithms/focus.py`), but nothing
in them is Leica-specific: phase correlation between two images, a vote
across four registration methods, and the Brenner sharpness score work the
same on any microscope. In Leica they are used only by setup (the
orientation measurement and the objective calibration), and every other
driver will need the same for its own setup notebooks.

**Rules for the shared package.**

- **Algorithms never touch a microscope.** They take images and numbers and
  return numbers, so they can be tested on sample images alone.
- **Drivers use the shared package; the shared package knows nothing about any
  driver.**
- **Only move something into the shared package once two drivers actually use
  it the same way.** Until then it stays inside the driver, even if it looks
  similar to something shared. This keeps us from building general solutions
  for cases we have not seen yet.

What is the same in every driver, and what differs:

| Part | The same everywhere | Specific to each microscope |
|---|---|---|
| Vendor interface | The three promises | Everything inside |
| Error handling | The rules | The classifier |
| Get actions | The get dispatcher | Which primitive, and what the value means |
| Set actions | The set dispatcher and limits gate | Which primitive, the target, the confirmation |
| Procedures | The "get and set actions only" rule; the algorithms | The recipes |
| Data handling | OME-TIFF and OME-Zarr writing, naming, the command log | Finding and reading the vendor's raw output |
| Configuration | Load, check and save; the notebook pattern | Default values; the machine description |
| ZMART controller plugin | The 11-function contract and `validate_driver` | Mapping actions onto those 11 |
| Testing | `run_ci.py`; the dispatcher and error-rule tests; offline before hardware | The mock API; the hardware checks |

## Experimental code

Every driver may have an `experimental/` folder for ideas that are not yet
trusted. Code there is left out of hardware validation and must not be used
by any other part of the driver. The Leica driver already works this way.

## Open questions

- **Stop.** No driver and no part of the controller contract offers a way to
  stop a running command. If an acquisition or a tile scan goes wrong, the
  only way out today is the vendor software itself. A defined `stop` would
  touch the set dispatcher (a long confirmation wait has to be
  interruptible), the error rules (a new kind, "stopped by user") and the
  controller contract (a new function). This is the largest safety gap we
  know of, and it needs a decision: add it now, or record it for a later
  version of the contract.
- **Limits in raw coordinates.** This document proposes that limits are
  stored and checked in raw stage coordinates, so that recording a new origin
  cannot move the safe travel range. The Leica driver's physical backstop
  already works in raw coordinates; we still need to confirm how its
  `limits.json` is interpreted today before we write this down as settled.
- **Unconfirmed results in the controller contract.** The Leica driver
  currently reports an unconfirmed action as `success: True` with
  `confirmed: False`, and its adapter never returns `success: False`. This
  document proposes `success: False` with `confirmed: False`, which matches
  the controller's idea of a soft outcome. The controller's `docs/driver.md`
  should say this explicitly.

## How we get there

1. **The mock driver first.** Rebuild the controller's mock driver
   (`tests/mock_zmart_driver/`) in exactly this layout, small and readable, running
   on a small mock API. It becomes the template a new driver author copies,
   and the first user of the shared package.
2. **Write the contract additions** into the controller's `docs/driver.md`:
   the unconfirmed rule, and stop once it is decided.
3. **Give Leica a `zmart_controller/` plugin folder.** Today it registers
   itself when its `zmart_adapter` module is imported, while the controller
   release candidate expects `register_driver` to find a `zmart.json`.
4. **Move the shared parts out of Leica one at a time** (the algorithms, then
   the set dispatcher and the error rules), keeping Leica's tests green after
   every step.
5. **Bring the Nikon, ZEISS and mesoSPIM drivers into the same layout**, each
   in its own pull request, so that a problem in one does not hold up the
   others.
