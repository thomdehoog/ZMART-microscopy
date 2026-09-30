# Controller release review (2026-09-30)

This review asks one question: is `zmart_controller` ready to be released as
its own repository, for people outside ZMB to install and to write drivers
for? It looks at the controller code itself (`__init__.py`, `layer.py`,
`registry.py`), at its tests, and at how the five existing drivers (the mock,
Leica, Nikon, ZEISS and mesoSPIM) actually fulfil its contract.

## The short answer

The controller code is in good shape. It is small (about 430 lines), has no
dependencies, does exactly what it says, and its 35 tests pass in well under a
second. Very little in it needs to change.

What is not ready is the *contract*: the description of what each command
must return. Today it lives only in prose and in the mock driver, and the real
drivers have drifted apart from it and from each other. For a controller whose
whole promise is "write the experiment once, run it on any microscope", this is
the thing that matters most. An outside driver author has nothing to check
their work against, and a workflow written on one microscope can break on
another in ways nobody notices until the experiment runs.

There are also four packaging steps that any standalone release needs.

The findings below are ordered by how much they matter for the release.

## 1. The contract is unwritten, and the drivers have drifted

Every driver agrees on the basic outline: `get_xyz` returns
`{axis: {"value", "actuator", "unit"}}`, the option menus are
`{name: {"options", "active"}}`, states are split into `changeable` and
`observed`, procedures are chosen by `{"name": ...}`, and every `get_info`
reports `output_root`. The new README lists these as the guaranteed shape.

Beyond that outline, they disagree in ways that a portable workflow would trip
over:

| Where | What differs | Why it matters |
|---|---|---|
| `get_info()["tile_positions"]` | Present on the mock and Leica; absent on Nikon, ZEISS and mesoSPIM. | The example notebook read it, so it ran on only two of the five. Now resolved: it is an extra (see below). |
| Autofocus result | Mock, Leica, Nikon and ZEISS return `frame_z_um`. mesoSPIM returns `{"ran", "data"}` with no z. | A focus step written for one microscope fails on mesoSPIM. |
| Autofocus name | ZEISS has no procedure called `autofocus`, only `software_autofocus`, `find_surface` and `recall_focus`. | The same call raises on ZEISS. |
| Saved files in the `acquire` record | `filename` (mock), `images` + `planes` (Leica), `image_files` (Nikon, ZEISS, mesoSPIM). `planes` is a list on Leica and a count elsewhere. | Nothing downstream can find the data without knowing the vendor. |
| Unknown acquisition options | The mock and Leica raise `ValueError`. Nikon, ZEISS and mesoSPIM ignore them silently. Nikon and mesoSPIM also read option keys they never list. | A typo such as `exposre_ms` is silently ignored on three microscopes. This is the most likely way for the contract to cost someone an experiment. |
| Unknown procedure name | Every real driver raises; the mock quietly returns `{"ran": ...}`. | The reference implementation teaches the wrong behaviour. |
| Origin at connect | Nikon, ZEISS and mesoSPIM restore the last saved origin; Leica and the mock start fresh. | A notebook that forgets `set_origin()` gets different coordinates on different microscopes. |
| After `disconnect()` | Every driver refuses further calls except mesoSPIM, which has no closed check. | Behaviour after closing is not uniform. |
| mesoSPIM `get_xyz` | Always reports the default actuator instead of the one asked for. | Small, but it breaks the "echo the choice" rule. |
| mesoSPIM `set_xyz` | `confirmed` is the raw stage value, not in the frame. The other drivers report it in the frame. | Mixing frames in one record is confusing. |
| Silent partial failures | ZEISS returns `"copied": False` when the CZI copy fails. mesoSPIM skips backlash correction with only a log warning. | Both contradict the rule "fail by raising, never inside the answer". |

**Recommendation.** Write the contract down as a short, versioned table (the
new README's "What each function receives and returns" is a first draft), then
turn it into a **shared conformance test** that ships with the controller. For
example, `zmart_controller.testing.check_driver(instrument)` would connect,
walk every command against the mock-free contract, and report what is
missing. Each driver runs it against its own simulator or fake. This one piece
is what makes the controller usable by outsiders, because it tells a driver
author exactly when they are done. It also catches the drift above
automatically.

Decisions by the maintainer:

- **`tile_positions` (and `focus_positions`) are driver extras, not part of
  the contract.** The contract holds only what every microscope can provide,
  so that it stays interoperable. The example notebook now defines its own
  positions and no longer asks for a piezo, which Leica does not have. The
  `get_info` docstring and the README say that extras must not be relied on.
  One consequence remains open: the target-acquisition workflow
  (`workflows/target_acquisition`, both notebooks and the web app) reads
  `get_info()["tile_positions"]`, so today it runs only on Leica and the
  mock. To make it portable, it needs its own way to get positions, such as a
  list, a file or a picker, with the vendor tiles used only when a driver
  happens to offer them.

- **The origin is driver configuration, not a controller command.**
  `set_origin` has been removed from the controller. The origin is set once
  in a separate setup step with the driver, saved to the driver's
  configuration file, and loaded by the driver every time it connects, in the
  same way as the limits and the calibration. Each driver keeps its own
  `set_origin` function for that setup step. The "origin at connect" row in
  the table above is therefore settled: every driver restores its saved
  origin. (Recorded as maintainer decision 9.)
- **Every call is synchronous.** A command calls the driver function, the
  driver does its work, and the command returns when that work is finished.
  A live mode (change settings while watching, then snap) is a possible
  future addition but is not part of the controller now.
- **The controller stays a plain pass-through.** It is one class whose
  methods each call the matching driver function. All checks, including
  "is the connection still open", belong to the driver.

Still open:

- **A common return shape (direction agreed, not yet built).** Every command
  will return `{"success": ..., "report": ...}`: whether it worked, plus a
  report whose content is free for each driver. Drivers keep raising an error
  when carrying on would be unsafe (the move did not happen, the connection is
  lost), and use `success: False` for softer outcomes such as "saved, but the
  copy to the output folder failed". No driver returns this shape yet.
- **How drivers are registered.** See section 2, point 3.

## 2. Packaging for a standalone repository

These are needed before anyone outside this repository can use the
controller:

1. **It cannot be installed.** `pyproject.toml` has only linter settings, and
   the package docstring says "requires the repository root on sys.path". A
   standalone release needs a `[project]` section (name, version, Python
   3.10+, no dependencies) so that `pip install` works.
2. **The mock is hidden inside `tests/`.** The example notebook reaches it by
   editing `sys.path`. For newcomers the mock *is* the front door, so it should
   become a public module, for example `zmart_controller.mock`, with the tests
   importing it from there.
3. **Drivers are found only by being imported.** That works inside one
   repository, but separately installed drivers need a way to announce
   themselves. The usual Python mechanism is an *entry point*: a line in the
   driver's own `pyproject.toml` that says "I provide a ZMART driver", which
   `get_instruments()` can then discover without the user importing anything.
   Also note that the Leica adapter imports the controller unconditionally,
   while the others guard that import.
4. **Decide the name before publishing.** `docs/ZMART.md` says the public
   package should be `zmart` and that the rename should happen once. A public
   release is that moment; renaming after other people depend on it breaks
   their code.

The README's links to files elsewhere in this repository (`../docs/ZMART.md`,
the driver folders) have been replaced with links that will still work from a
separate repository.

## 3. Findings in the controller code

All of these are small, and each was confirmed by running it. After the
maintainer's decision that the controller stays a plain pass-through, the
first two are no longer changes to the controller: they are rules for the
drivers.

1. **Calls after `disconnect()` are refused only if the driver refuses them.**
   This is the driver's job, and every driver except mesoSPIM already does it.
   The fix belongs in the mesoSPIM driver.
2. **`register()` accepts entries that are not functions.** Registering
   `{"get_xyz": None}` succeeds, and the mistake only shows up later as a
   confusing error at the microscope. Whether registration should check this
   is part of the open registration question.
3. **`get_instruments()` copies only the top level.** If a connection
   dictionary holds a nested dictionary, for example credentials, editing the
   returned copy changes the registry's own entry. Similarly, `resolve()`
   hands the caller's own dictionary to the driver, so a driver that edits it
   changes the user's variable. Using a full copy fixes both without adding
   any checks.
4. **The module-level shortcut exposes private attributes.**
   `zmart_controller._ops` and `zmart_controller._handle` resolve to the
   active session's internals. Delegation should skip names that start with an
   underscore.
5. **There is no contract version.** Adding a command to `OPS` would make every
   existing third-party driver fail at registration. Before outsiders write
   drivers, either give the contract a version number that drivers declare, or
   decide that new commands will always be optional.
6. **Re-running a `set_instrument` cell opens the new connection before closing
   the old one.** This order is deliberate, so a failed connect never loses a
   working session. It is worth checking, though, that none of the vendor
   programs refuses a second simultaneous client, because re-running a cell is
   the most common thing people do in a notebook.
7. **`from zmart_controller import acquire` captures the current microscope.**
   This is already documented as a caution.

## Open design questions

**A common return shape (option 1 chosen, see above).** The idea is that every command returns the same
two things: whether it worked (`success`), and a `report`, whose content is
free for each driver. This is simple and uniform, and it matches the
`success` / `confirmed` records the drivers already use internally. The one
thing to decide with it is what happens when a script does not look at
`success`. Today a failed move raises an error and the script stops. With a
returned `success: False`, a script that forgets to check would carry on and
image the wrong place. Two ways to keep that safe are: the driver still raises
for failures that make continuing unsafe and uses `success: False` only for
soft outcomes, or the notebooks always check `success` through one small
helper. Either choice keeps the controller a plain pass-through.

**Registration.** Today a driver registers by calling `register(connection,
ops=...)` when its module is imported. That is simple and works inside one
repository. For drivers installed separately, the lightest addition is an
entry point (see section 2), which leaves `register` unchanged.

## 4. What is already good

These are worth keeping exactly as they are:

- The controller really is thin. It forwards, caches nothing and does no
  arithmetic, which is why five very different microscopes fit under it.
- It has no dependencies at all, which makes it easy to install anywhere,
  including inside vendor software.
- Error messages name keys and never values, so credentials do not leak, and
  there is a test for it.
- `disconnect()` is safe to call twice, and switching microscopes never loses
  a working session when the old one fails to close. Both have tests.
- The "ask first, then act" pattern is consistent across every command, and
  the real drivers follow it.

## Suggested order of work

1. Decide the return shape, the registration route and the package name.
2. Write the conformance check, and fix the mock so it passes it first.
3. Fix code findings 3 and 4 in section 3 (each is a few lines, with a test).
4. Add packaging: `[project]`, a public mock and entry-point discovery.
5. Bring each driver up to the conformance check, starting with mesoSPIM, which
   has the most gaps.
6. Split the repository and publish 0.1.
