# ZMART driver configuration: a second workflow, and the boundary it must respect

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
2. **Set up limits** — how far the stage may travel, which objective slots
   automation may use, and a permitted value or range for each setting the
   driver can change.
3. **Stage-to-image calibration** — how the picture is turned relative to the
   stage, so that moving right on the stage means moving right in the image.
   One of eight lossless ways of laying the image down: a quarter, half or
   three-quarter turn, each optionally mirrored.
4. **Optics calibration** — the pixel size, and how a pair of objectives line
   up with each other, so a target found on a low-power overview is still
   centred under the high-power lens.
5. **Set up origin** — the point the run counts from. Once set, reported
   positions are micrometres from there.

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

### The one exception, and why it is not an inconsistency

`set_origin` is already on the controller (`layer.py`), and should stay there.
The origin is session-scoped — the driver does not even restore it at connect —
and it cannot widen anything: changing where you count from does not change
where the stage may go. It is a frame convenience, not a safety envelope.

So step 5 goes through the controller while steps 2 to 4 do not. That asymmetry
is deliberate, and is written down here so that it is not later tidied away by
moving the other three alongside it.

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

## What is not done

The step declarations, the panel, and the driver contract are written. Not yet
built: the driver modules themselves, the controls each step shows, the
framework's ability to give a workflow a display name that keeps an acronym
(`zmart_driver_configuration` currently reads as "Zmart driver configuration"),
and the test updates that follow from a second workflow existing.
