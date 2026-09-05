# ZMART driver setup: a second workflow, and the boundary it must respect

Written 2026-09-05, while the workflow was being started. This is a design
note rather than a description of finished code: the folder
`application/workflows/zmart_driver_configuration/` exists and holds the five
step declarations and its panel, but nothing is wired into the page yet. What
this note is for is the reasoning, which is the part that would be expensive to
rediscover.

## What the workflow is

Target acquisition is a run on a microscope that has already been set up. This
second workflow is the setting up: it walks an operator through the settings a
driver needs before any imaging workflow can stand on it.

Five steps, in order:

1. **Connect** — choose the microscope, its API and the password, and open the
   session. This is the same step target acquisition starts with, borrowed
   rather than retyped, so a fix to connecting reaches both workflows at once.
2. **Define limits** — how far the stage may travel, which objective slots
   automation may use, and a permitted value or range for each setting the
   driver can change.
3. **Image-to-stage calibration** — how the picture is turned relative to the
   stage, so that moving right on the stage means moving right in the image.
   One of eight lossless ways of laying the image down: a quarter, half or
   three-quarter turn, each optionally mirrored.
4. **Optics calibration** — the pixel size, and how every objective lines up
   with one reference objective, so a target found on a low-power overview is
   still centred under the high-power lens. The ideal is a parcentric and
   parfocal microscope, where every offset is zero; choosing the reference gives
   every other lens a preset at that ideal, and measuring a preset replaces the
   ideal with what the microscope actually does. Changing the reference starts
   the presets over, because every offset was relative to it.
5. **Define origin** — the point the run counts from. Once set, reported
   positions are micrometres from there. Like the three above it, this is
   published by the driver rather than reached through the controller; see
   the boundary section below.

Steps 2 to 5 correspond exactly to the four subsystems the driver already keeps
under `C:\ProgramData\zmart-microscopy\<vendor>\<microscope>\<api>\`: `limits`,
`orientation`, `calibration` and `origin`. Each is an append-only tree of dated
snapshots, and the newest snapshot in each subsystem wins independently, so
publishing limits never disturbs a calibration. `config/machine.py` in the Leica
driver is where that arrangement is written down.

There is no canvas in this workflow. Setting a microscope up is reading numbers
off the instrument and writing them down where the driver will find them again,
and every one of those readings is a control rather than something to look at.
The workflow therefore declares a panel of its own and the window belongs to it.

## The boundary: configuration does not go through the controller

The controller (`zmart_controller`) is the vendor-neutral layer the imaging
workflows drive a microscope through. It is deliberately **not** the path by
which a driver is configured, and that is a safety property rather than a gap
in the plumbing.

The Leica driver guards every stage move twice: once against the published
envelope, and then again, independently, against a hardcoded physical backstop
that no file can widen (`limits/checks.py`). A session with no published
envelope refuses to move at all — what the code calls failing closed. That
layering only means something as long as **the thing being limited cannot
rewrite its own limits.** If publishing an envelope were reachable from the
operating surface, then any workflow holding a session — or a runaway loop, or
a simple mistake — could widen the fence it is being held by.

This rules out something that otherwise looks like a perfect fit. The
controller's ops table already carries `get_procedures` and `run_procedure`
(`registry.py`, `layer.py`), a driver-declared and vendor-blind way to run named
work. Using it to run `set_limits` would be neat, and it would place
configuration inside the operating surface, which is exactly the boundary being
protected. A session that can run the limits procedure is a session that can
widen its own envelope.

### The reason this matters more later, not less

The intention is that AI agents will eventually drive these workflows. An agent
must not be able to arrive at new machine configurations on its own. Agents
drive the controller; so keeping configuration off the controller is what makes
that guarantee structural rather than a matter of asking an agent nicely.

Any further gating of the publish path — an explicit operator confirmation, or
a machine-local check that this really is the instrument's own PC — belongs with
that agent work and is deliberately **not** being built now.

### The origin moves out of the controller too

An earlier draft of this note argued that `set_origin` was a principled
exception and should stay on the controller, because the origin is
session-scoped and cannot widen the stage envelope. That argument was too
narrow, and the decision has gone the other way: the origin moves out with the
other three.

Widening the envelope is not the only way to do damage. Moving the origin
redefines the frame every recorded position is expressed in. Nothing breaks
loudly; a target list captured before the change simply means somewhere else
afterwards, and no tile knows it. Against the reason this boundary exists at
all — that an agent must not arrive at machine configuration on its own — a
silent redefinition of the coordinate frame is at least as serious as a wider
fence, and harder to notice.

The driver already treats it as configuration. `config/machine.py` lists
`origin` as one of its four subsystems, with its own `origin.json` and its own
dated, append-only snapshots, "so every origin change keeps its own immutable
record". What makes it unlike the other three is only that the driver does not
restore it at connect. That is a statement about when it is applied, not about
what kind of thing it is.

So all four subsystems — limits, calibration, orientation, origin — are
configured by the same path, and the controller keeps none of them.

**What this costs, and it is not nothing.** `set_origin` is in the controller's
required ops table (`registry.py`), which every registered driver must supply,
and `layer.py` currently tells the reader to "call `set_origin()` at session
start". Taking it out changes the op contract for every driver at once, and
changes the advice a workflow author is given. That is a deliberate change to
the controller rather than a side effect of adding a workflow, so it is
recorded here and done as its own piece of work.

## Why the steps need per-driver flexibility

The five steps mean the same thing on every microscope. The *procedure* is
different on each, and the drivers in this repository already differ more than
one panel could cover:

| driver | shape today |
| --- | --- |
| Leica `stellaris5_y42h93/navigator_expert` | all four subsystems, three notebooks, a flat `limits.json` |
| Zeiss `zenapi` | its own limits module and checks; no microscope level in the path |
| MesoSPIM | limits only, still in the older two-file shape that the Leica `machine.py` now reads only to migrate |
| Nikon, Evident | exploratory spikes; no driver to configure |
| Mock | a single file |

So a step holds the meaning and the driver holds the method. After Connect the
page knows the `(vendor, microscope, api)` identity — which is precisely the key
to both the registry and the ProgramData tree — and loads that driver's account
of how it is configured. A driver that cannot do a step says so, and the step
greys out and explains itself rather than offering a button that does nothing.

The decision taken was to keep those accounts **page-side**: one module per
driver under the workflow, chosen after Connect. `drivers/what-a-driver-declares.js`
says what such a module has to contain.

## Steps 3 and 4 are two parties, not one

Measuring the image-to-stage turn and measuring the optics look like driver
work, and half of each is. The other half is not, and separating them is what
keeps the per-driver modules small.

`docs/design/what-runs-where.md` already states the rule this follows:

> The **instrument** moves and captures. It produces pixels.
> **ZMART_analysis** reads pixels and produces numbers.
> The **page** decides.

Applied to these two steps:

- **Step 3, image-to-stage.** The instrument's part is to image a field that
  has structure in it and is in focus — nuclei, or anything else with edges to
  recognise — then move the stage a known distance and image it again. That is
  vendor work: only the driver can move this stage and expose this sensor. The
  analysis then takes the pair of images and answers which of the eight ways of
  laying an image down fits what it sees. Nothing in that answer is Leica's or
  Zeiss's; it is two pictures and a shift.
- **Step 4, optics.** The same shape. The driver images the same field through
  each objective of the pair, and moves a known distance in X, Y and Z. The
  analysis returns the pixel size and how the two lenses line up.

So the vendor-specific part of both steps is "move here, capture that", and the
numbers come back from an analysis workflow that never learns which microscope
took the pictures. That belongs in `zmart_analysis/workflows/`, beside `focus/`
and `object_analysis/`, as its own pipeline. Two consequences worth having in
mind:

1. **The per-driver modules stay small.** A new manufacturer has to say how to
   move and how to capture, and inherits the measurement itself.
2. **The measurement can be checked without a microscope.** A pipeline that
   takes images and returns numbers can be run against saved images, so the
   part most likely to be subtly wrong is the part that is testable offline.

These two steps also carry an operator prerequisite that no readiness rule can
check for them: there has to be a specimen under the objective with structure in
it, and it has to be in focus. The step says so in words rather than pretending
to verify it.

## What was built, and where

- **`zmart_setup/`** — the setup seam: a registry keyed the way the controller's
  is but separate from it, a `Setup` that forwards to a driver's small
  vocabulary (where, move, acquire, objective, markers, read, publish), and
  the vendor-blind procedures that drive it: read the boundary, measure the
  orientation, capture a lens view, measure the pair, origin here. The package
  never imports the controller, and a test says so.
- **`zmart_analysis/workflows/stage_calibration/`** — the two measurements as
  pipeline steps, `measure_orientation` and `measure_objective_pair`, with
  their recipes and tests against synthetic pictures. All eight orientations
  are recovered, and the pixel size with them.
- **`zmart_drivers/mock/mock_setup.py`** and the mock instrument window — a
  pretend rig with a quarter-turned camera, two lenses and a marker tool, so
  the whole workflow can be walked on a bench. The mock driver stands on what
  was published: the origin, the envelope, and the orientation correction.
- **`zmart_drivers/leica/.../zmart_adapter/setup.py`** — the Leica's side,
  mapped onto the functions the three notebooks already use; the adapter now
  reads the published origin at connect and has no `set_origin`.
- **The bridge** — `/api/setup/*` routes that hold a setup, never a session.
- **The page** — the workflow, its notebook-shaped panel, the cells of every
  step, and three small framework changes: a flow may name itself, may bring
  its own backend, and a step may carry its own channel.

## Deliberately not done

- **MesoSPIM is untouched** (the owner's decision: only the Leica and the mock
  get a setup side for now). Its adapter still offers `set_origin` in its own
  ops table and its own tests still call `session.set_origin()`; those will
  fail against the controller until it is brought across, which is a small,
  separate change.
- **Gating the publish path** — an operator confirmation, or a check that this
  is the instrument's own PC — belongs with the agent work and is not built.
- The Leica setup's `move`, `acquire` and `markers` are written against the
  same driver functions the notebooks use and are tested offline only where a
  seam can be patched; the first run on the bench is where they are proven.
